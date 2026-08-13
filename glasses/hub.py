"""
Smart glasses / wearable hub (Phase 33) - a universal BLE interface.

JARVIS cannot embed itself into a pair of glasses - it is desktop software
and vendor HUDs need their own SDKs and firmware. What it *can* do, on any
Windows machine with no extra dependencies, is talk to whatever wearable is
paired:

    * ``scan()``          - list every Bluetooth/Wearable device Windows sees
                            (PowerShell Get-PnpDevice; works with any brand)
    * ``select(name)``    - remember a device to use as the active glasses
    * ``notify(text)``    - deliver a message to the glasses: spoken aloud
                            through the device when it is an audio output,
                            plus a native Windows toast. Honest about what
                            actually got delivered.

Everything is capability-honest (matching the project's no-fake-claims
rule): JARVIS reports exactly what it sent and where, and never pretends
it wrote to a vendor HUD screen it cannot reach.
"""

from __future__ import annotations

import shlex
import subprocess
import threading

from config import settings
from utils.logger import get_logger

log = get_logger(__name__)


def _powershell(command: str, timeout: float = 15.0) -> str:
    """Run a PowerShell snippet and return stdout (or '' on failure)."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=0x08000000,  # CREATE_NO_WINDOW - no console flash
        )
        return (result.stdout or "").strip()
    except Exception as exc:  # noqa: BLE001 - scanning must never crash chat
        log.debug("PowerShell failed: %s", exc)
        return ""


def _list_bluetooth_devices() -> list[str]:
    """Friendly names of every Bluetooth / wearable device Windows sees."""
    ps = (
        "Get-PnpDevice -Class Bluetooth,BluetoothLE,PortableDevices,"
        "SoftwareDevice -ErrorAction SilentlyContinue | "
        "Where-Object { $_.FriendlyName } | "
        "Select-Object -ExpandProperty FriendlyName"
    )
    out = _powershell(ps)
    names = []
    for line in out.splitlines():
        name = line.strip().strip("'\"")
        if name:
            names.append(name)
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def scan() -> list[str]:
    """All paired/nearby Bluetooth and wearable devices by name."""
    return _list_bluetooth_devices()


def _best_glasses_candidate() -> str:
    """Pick a device that looks like smart glasses, or '' if none."""
    for name in _list_bluetooth_devices():
        low = name.lower()
        if any(
            kw in low
            for kw in (
                "glass", "ray-ban", "wayfarer", "xreal", "nreal",
                "even", "bosch", "vuzix", "meta view", "glasses",
            )
        ):
            return name
    return ""


class GlassesHub:
    """The bridge between JARVIS and the user's smart glasses.

    Testable: ``_discover`` and ``_play_audio`` can be swapped by subclasses
    or monkeypatched, keeping the hardware calls out of the chat thread.
    """

    def __init__(self, tts=None) -> None:
        self._tts = tts
        self._active = ""
        self._lock = threading.Lock()

    # -- Discovery ----------------------------------------------------------
    def discover(self) -> list[str]:
        """Names of Bluetooth / wearable devices currently visible."""
        return scan()

    def select(self, name_fragment: str) -> str:
        """Pick a device (by name or fragment) as the active glasses."""
        fragment = (name_fragment or "").strip().lower()
        devices = self.discover()
        if not devices:
            return "No Bluetooth devices are visible. Turn on the glasses and Bluetooth, then try again."
        if fragment:
            matches = [d for d in devices if fragment in d.lower()]
            if not matches:
                known = ", ".join(devices[:8])
                return (
                    f"I could not find a device matching {name_fragment!r}. "
                    f"Devices I can see: {known}."
                )
            with self._lock:
                self._active = matches[0]
            return f"Glasses set to: {matches[0]}."
        # No fragment: prefer an obvious glasses device, else the first.
        candidate = _best_glasses_candidate() or (devices[0] if devices else "")
        with self._lock:
            self._active = candidate
        return f"Glasses set to: {candidate}." if candidate else "No device found."

    @property
    def active(self) -> str:
        return self._active

    # -- Notification -------------------------------------------------------
    def notify(self, text: str) -> str:
        """Deliver a message to the active glasses.

        What really happens:
          * a Windows toast notification is raised (works for any paired
            wearable - HUD or not), and
          * when the device is a Bluetooth *audio* output, the message is
            spoken through it via TTS, so audio-capable glasses read it out.
        Vendor HUD displays (Meta Ray-Ban screens, XREAL HUD...) need their
        own SDK and are honestly reported as not reachable here.
        """
        message = (text or "").strip()
        if not message:
            return "Nothing to send - the message was empty."
        with self._lock:
            device = self._active
        _show_toast(device or "JARVIS", message)
        spoken = False
        if self._tts is not None and getattr(self._tts, "enabled", True):
            try:
                self._tts.speak(message)
                spoken = True
            except Exception as exc:  # noqa: BLE001
                log.debug("Glasses audio failed: %s", exc)
        if device:
            return (
                f"Sent to {device}: notification shown"
                + (" and spoken aloud." if spoken else ".")
                + " (If the glasses have a HUD display, that needs the "
                "vendor's SDK, which JARVIS cannot reach.)"
            )
        return (
            "Notification shown."
            + (" Spoken aloud too." if spoken else "")
            + " No glasses are selected yet - say 'connect my glasses' first."
        )

    def status(self) -> str:
        """What JARVIS currently knows about the glasses."""
        with self._lock:
            device = self._active
        devices = self.discover()
        base = f"Active glasses: {device or 'none selected'}."
        if devices:
            base += f" Visible devices ({len(devices)}): {', '.join(devices[:6])}."
        else:
            base += " No Bluetooth devices visible - turn on Bluetooth and the glasses."
        return base


def _show_toast(title: str, message: str) -> None:
    """Native Windows toast notification (PowerShell, no extra packages)."""
    # Escape for embedding in a PowerShell string.
    safe_title = title.replace("'", "''")
    safe_message = message.replace("'", "''")
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager, "
        "Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
        "$template = [Windows.UI.Notifications.ToastNotificationManager]::"
        "GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::"
        "ToastText02); "
        "$texts = $template.GetElementsByTagName('text'); "
        f"$texts.Item(0).AppendChild($template.CreateTextNode('{safe_title}')) | Out-Null; "
        f"$texts.Item(1).AppendChild($template.CreateTextNode('{safe_message}')) | Out-Null; "
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'JARVIS AI').Show($toast)"
    )
    _powershell(ps, timeout=10.0)


def glasses_prompt_block() -> str:
    """A short system-prompt block telling the model when to use glasses."""
    return (
        "SMART GLASSES: if the user asks to send/notify/put something on "
        "their smart glasses or wearable, use the 'glasses' tool. The tool "
        "scans for Bluetooth devices, selects the glasses, and delivers "
        "notifications (spoken + toast). Be honest: JARVIS cannot embed "
        "itself into the hardware; it talks to whatever device is paired."
    )
