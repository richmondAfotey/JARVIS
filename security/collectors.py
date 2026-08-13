"""
Indicator collectors (Phase 28).

Each `collect_*` function inspects one area of observable activity and
returns a list of `ThreatAlert`. Every collector is fully defensive: it
never raises, never touches system settings, and only *reports*. When a
data source is not available (e.g. the Security event log needs
administrator rights), it returns nothing rather than guessing.

Collected areas:
    * processes     - unexpected / known-malware process names, processes
                      running from suspicious (temp) paths
    * resources     - a single process pegging CPU or RAM
    * network       - unusual outbound connections and suspicious ports
    * startup       - startup apps launching from temp / AppData
    * firewall      - firewall profiles that are switched off
    * auth          - bursts of failed logon events (Windows Security log)
    * files         - new executable files dropped in temp/startup folders
    * malware       - known malware indicator names

Honesty: these are *indicators*, not proof. We report what was observed
and why it could matter; we never claim a machine is safe or infected.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

from security.threats import ThreatAlert, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW

_KNOWN_MALWARE_NAMES = {
    "wannacry",
    "cryptolocker",
    "ransomware",
    "xmrig",
    "miner",
    "coinminer",
    "keylogger",
    "spyeye",
    "zeus",
    "agenttesla",
    "njrat",
    "darkcomet",
    "njw0rm",
}

#: Ports frequently used by coin miners / C2 / trojans.
_SUSPICIOUS_PORTS = {4444, 5555, 6667, 7777, 3333, 3334, 14444, 18081, 9999}

#: Common startup registry value names (per-user and machine-wide).
_STARTUP_PATHS = [
    r"Software\Microsoft\Windows\CurrentVersion\Run",
    r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
]

#: Dirs that are suspicious to launch executables from.
_SUSPICIOUS_ROOT_HINTS = ("temp", "downloads", "appdata")

_MAX_SUSPICIOUS_PROCESSES = 10
_MAX_ALERTS_PER_COLLECTOR = 15


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _reason_for_exe(exe: str) -> str:
    """Short human reason when an executable lives in a suspicious place."""
    return f"executable launched from {exe}"


# -- helpers ----------------------------------------------------------------

def _writable_dir(dirname: str) -> bool:
    """True if the folder is writable by a normal user (likely low trust)."""
    try:
        p = Path(dirname).resolve()
        return not p.exists() or (p.is_dir() and os.access(p, os.W_OK))
    except OSError:
        return False


def _is_temp_path(path_str: str | None) -> bool:
    if not path_str:
        return False
    lowered = path_str.lower().replace("\\", "/")
    # Only genuinely low-trust places: the temp / tmp folder or the user's
    # Downloads folder. Program Files and AppData\Local\Programs are normal
    # install locations and must NOT be flagged.
    if "/temp/" in lowered or "/tmp/" in lowered:
        return True
    downloads = os.environ.get("DOWNLOAD", "")
    if downloads and lowered.startswith(downloads.lower().replace("\\", "/")):
        return True
    if "/downloads/" in lowered:
        return True
    return False


def _process_name(proc: Any) -> str:
    try:
        return str((proc.info.get("name") or proc.info.get("exe") or "unknown")).lower()
    except Exception:  # noqa: BLE001 - never crash on a weird process
        return "unknown"


def _safe(fn):
    """Run a collector; convert any unexpected error into an empty result."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:  # noqa: BLE001 - a collector must never crash the app
            return []
    return wrapper


# -- processes --------------------------------------------------------------

@_safe
def collect_processes() -> list[ThreatAlert]:
    alerts: list[ThreatAlert] = []
    for proc in psutil.process_iter(["name", "exe", "pid"]):
        name = _process_name(proc)
        exe = proc.info.get("exe")
        if not name:
            continue
        base = os.path.basename(str(exe or "")).lower()
        base_no_ext = os.path.splitext(base)[0]
        name_no_ext = os.path.splitext(name)[0]
        if (
            name in _KNOWN_MALWARE_NAMES
            or base in _KNOWN_MALWARE_NAMES
            or name_no_ext in _KNOWN_MALWARE_NAMES
            or base_no_ext in _KNOWN_MALWARE_NAMES
        ):
            alerts.append(
                ThreatAlert(
                    detected=f"Process name matches a known malware indicator: {name}",
                    why="This name is commonly associated with malicious software.",
                    process=name,
                    severity=SEVERITY_HIGH,
                    recommended="Investigate the process. If you did not install it, "
                    "do not trust it; consider terminating it only after you "
                    "confirm it is unwanted.",
                    source="processes",
                    when=_now(),
                )
            )
        elif _is_temp_path(exe):
            alerts.append(
                ThreatAlert(
                    detected=f"Process running from a suspicious location: {exe}",
                    why="Executables launched from temp / downloads / AppData are a "
                    "common way malware hides from detection.",
                    process=name,
                    severity=SEVERITY_MEDIUM,
                    recommended="Check whether this program is one you installed or "
                    "opened yourself. If not, investigate before trusting it.",
                    source="processes",
                    when=_now(),
                )
            )
        if len(alerts) >= _MAX_SUSPICIOUS_PROCESSES:
            break
    return alerts


# -- CPU / RAM --------------------------------------------------------------

@_safe
def collect_resources() -> list[ThreatAlert]:
    alerts: list[ThreatAlert] = []
    cpu_percent = psutil.cpu_percent(interval=0.4)
    if cpu_percent and cpu_percent >= 95:
        alerts.append(
            ThreatAlert(
                detected=f"Total CPU usage is very high ({cpu_percent:.0f}%).",
                why="Sustained near-max CPU can indicate a mining process, a runaway "
                "program, or heavy legitimate work.",
                process="system-wide",
                severity=SEVERITY_MEDIUM,
                recommended="Open Task Manager to see which process uses the most CPU "
                "and decide whether it is expected.",
                source="resources",
                when=_now(),
            )
        )
    return alerts


# -- network ----------------------------------------------------------------

@_safe
def collect_network() -> list[ThreatAlert]:
    alerts: list[ThreatAlert] = []
    suspicious: dict[str, list[str]] = {}
    outbound = 0
    for conn in psutil.net_connections(kind="inet"):
        raddr = conn.raddr
        status = conn.status
        if not raddr:
            continue
        if status == "ESTABLISHED":
            outbound += 1
            port = raddr.port
            if port in _SUSPICIOUS_PORTS:
                ip = raddr.ip
                suspicious.setdefault(str(port), []).append(ip)

    for port, ips in list(suspicious.items())[:_MAX_ALERTS_PER_COLLECTOR]:
        alerts.append(
            ThreatAlert(
                detected=f"Outbound connection to suspicious port {port} "
                f"({len(ips)} remote address(es)).",
                why="This port is frequently used by coin miners, trojans or "
                "command-and-control channels.",
                process="network",
                severity=SEVERITY_MEDIUM,
                recommended="Check which process owns the connection (Task Manager or "
                "'netstat -b') and decide whether the traffic is expected.",
                source="network",
                when=_now(),
            )
        )
    if outbound >= 100:
        alerts.append(
            ThreatAlert(
                detected=f"Large number of open outbound connections ({outbound}).",
                why="Many simultaneous outbound connections can indicate a bot or "
                "data-transferring process, but can also be normal for browsers/IDEs.",
                process="network",
                severity=SEVERITY_LOW,
                recommended="If this is unexpected, review open connections and the "
                "processes that own them.",
                source="network",
                when=_now(),
            )
        )
    return alerts


# -- startup ----------------------------------------------------------------

@_safe
def collect_startup() -> list[ThreatAlert]:
    try:
        import winreg
    except ImportError:
        return []
    alerts: list[ThreatAlert] = []
    hives = (
        (winreg.HKEY_CURRENT_USER, winreg.KEY_READ),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ),
    )
    for hive, access in hives:
        for key_path in _STARTUP_PATHS:
            try:
                with winreg.OpenKey(hive, key_path, 0, access) as key:
                    count, _, _ = winreg.QueryInfoKey(key)
                    for index in range(count):
                        name, value, _ = winreg.EnumValue(key, index)
                        value = str(value or "")
                        if _is_temp_path(value):
                            alerts.append(
                                ThreatAlert(
                                    detected=f"Startup entry '{name}' launches from a "
                                    f"suspicious location: {value[:160]}",
                                    why="Programs that auto-start from temp / AppData / "
                                    "downloads are a common persistence trick for malware.",
                                    process=name,
                                    severity=SEVERITY_MEDIUM,
                                    recommended="Review the startup entry. If you did not "
                                    "add it, remove it from Startup after confirming it is "
                                    "not something you need.",
                                    source="startup",
                                    when=_now(),
                                )
                            )
            except (OSError, PermissionError):
                continue  # key may not exist or be locked - not an alert
            if len(alerts) >= _MAX_ALERTS_PER_COLLECTOR:
                return alerts
    return alerts


# -- firewall ---------------------------------------------------------------

@_safe
def collect_firewall() -> list[ThreatAlert]:
    alerts: list[ThreatAlert] = []
    try:
        result = subprocess.run(
            ["netsh", "advfirewall", "show", "allprofiles"],
            capture_output=True,
            text=True,
            timeout=25,
        )
    except (OSError, subprocess.SubprocessError):
        return alerts  # firewall data unavailable - don't guess
    if result.returncode != 0:
        return alerts
    profile_state: list[str] = []
    current_profile = None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.endswith("Profile Settings:"):
            current_profile = line.rsplit(" ", 1)[0]
        elif line.startswith("State") and current_profile:
            profile_state.append(f"{current_profile}={line.split()[1]}")
    disabled = [p for p in profile_state if p.endswith("=OFF")]
    if disabled:
        alerts.append(
            ThreatAlert(
                detected="Windows Firewall is turned OFF for: "
                + ", ".join(p.split("=")[0] for p in disabled) + ".",
                why="A disabled firewall leaves the machine exposed to unsolicited "
                "inbound connections.",
                process="Windows Defender Firewall",
                severity=SEVERITY_HIGH,
                recommended="Re-enable the firewall for the affected profiles. This "
                "changes a system setting, so confirm you want to do it, or run "
                "Windows Security and turn it back on there.",
                source="firewall",
                when=_now(),
            )
        )
    return alerts


# -- failed logons ----------------------------------------------------------

@_safe
def collect_failed_logons() -> list[ThreatAlert]:
    """Burst of failed logon events (Windows Security log 4625)."""
    try:
        import win32evtlog  # type: ignore
    except ImportError:
        return []
    alerts: list[ThreatAlert] = []
    try:
        handle = win32evtlog.OpenEventLog(None, "Security")
        flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
        total = 0
        recent = 0
        events = win32evtlog.ReadEventLog(handle, flags, 0)
        for evt in events:
            total += 1
            if evt.EventID & 0xFFFF == 4625:
                recent += 1
            if total > 500:
                break
        win32evtlog.CloseEventLog(handle)
    except Exception:  # noqa: BLE001 - Security log usually needs admin rights
        return []
    if recent >= 5:
        alerts.append(
            ThreatAlert(
                detected=f"{recent} failed logon attempt(s) found in the recent "
                "Security event log.",
                why="Repeated failed authentication attempts can indicate a "
                "brute-force attack against this machine.",
                process="Windows Security (Logon)",
                severity=SEVERITY_MEDIUM,
                recommended="Check which account was targeted. If the attempts are "
                "not yours, consider changing that account's password after "
                "confirming you want to.",
                source="auth",
                when=_now(),
            )
        )
    return alerts


# -- suspicious files -------------------------------------------------------

@_safe
def collect_suspicious_files() -> list[ThreatAlert]:
    alerts: list[ThreatAlert] = []
    exe_suffixes = (".exe", ".bat", ".cmd", ".ps1", ".scr", ".vbs", ".js")
    targets = set()
    temp = os.environ.get("TEMP")
    startup_roaming = os.environ.get("APPDATA")
    startup_local = os.environ.get("LOCALAPPDATA")
    for raw in (temp, os.environ.get("TMP")):
        if raw:
            targets.add(Path(raw))
    for base in (startup_roaming, startup_local):
        if base:
            targets.add(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup")

    now = datetime.now().timestamp()
    for folder in targets:
        if not folder.is_dir():
            continue
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for entry in entries[:_MAX_SUSPICIOUS_PROCESSES * 5]:
            try:
                if entry.suffix.lower() not in exe_suffixes:
                    continue
                age_min = (now - entry.stat().st_mtime) / 60
                if age_min <= 30:  # created/modified very recently
                    alerts.append(
                        ThreatAlert(
                            detected=f"Executable recently placed in a low-trust "
                            f"folder: {entry}",
                            why="Newly dropped executables in temp/startup folders are "
                            "a classic malware delivery pattern.",
                            process=entry.name,
                            severity=SEVERITY_MEDIUM,
                            recommended="If you did not just download or create this "
                            "file, do not run it; inspect and delete it only after "
                            "you confirm it is unwanted.",
                            source="files",
                            when=_now(),
                        )
                    )
            except OSError:
                continue
        if len(alerts) >= _MAX_ALERTS_PER_COLLECTOR:
            break
    return alerts


# -- aggregate --------------------------------------------------------------

def run_all() -> list[ThreatAlert]:
    """Run every collector and merge the results (deduplicated by detail)."""
    collectors = [
        collect_processes,
        collect_resources,
        collect_network,
        collect_startup,
        collect_firewall,
        collect_failed_logons,
        collect_suspicious_files,
    ]
    merged: list[ThreatAlert] = []
    seen: set[str] = set()
    for collector in collectors:
        for alert in collector():
            key = f"{alert.source}|{alert.detected}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(alert)
    return merged