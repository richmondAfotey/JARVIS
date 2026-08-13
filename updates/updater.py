"""
Self-update service (Phase 21).

JARVIS can check a remote manifest for a newer build of the packaged
executable, download it, and swap it in on the next launch.

How it works:

1. `check_for_update()` fetches a JSON manifest from the configured URL
   (`UPDATE_MANIFEST_URL`) and compares its ``version`` with the running
   version. Nothing is downloaded yet - the user is just told an update
   exists.
2. `stage_update()` downloads the new executable next to the running one
   (``JARVIS AI.new.exe``) and verifies its SHA-256.
3. `apply_update()` writes a tiny "finish the swap" script that waits for
   this process to exit, replaces the executable, and relaunches JARVIS.
   The script is spawned detached, then the app is asked to close.

Windows cannot overwrite a running executable, which is why the actual
file move happens in a separate small process after we exit.

Each function is small and pure so it can be unit-tested without network
or a real packaged build. In development ("frozen" is False) there is no
executable to replace, so self-update is reported as unavailable.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from utils.logger import get_logger

log = get_logger(__name__)

#: File name of the packaged executable (also used by jarvis.spec).
EXE_NAME = "JARVIS AI.exe"
#: Suffix used for the freshly downloaded build sitting next to the exe.
STAGED_SUFFIX = ".new.exe"
#: Backup the previous executable is kept as after a successful swap.
BACKUP_SUFFIX = ".old.exe"

_MANIFEST_TIMEOUT = 15
_DOWNLOAD_TIMEOUT = 120
_DOWNLOAD_CHUNK = 64 * 1024


@dataclass
class UpdateInfo:
    """A newer build advertised by the update manifest."""

    version: str
    url: str
    sha256: str = ""
    notes: str = ""


class UpdateError(RuntimeError):
    """Raised when an update cannot be checked, downloaded or applied."""


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------

def parse_version(version: str) -> tuple:
    """Turn a dotted version string into an orderable tuple.

    ``"1.2.3" -> (1, 2, 3)``. Only numeric segments are compared, so
    pre-release suffixes like ``"1.2.3-beta"`` are accepted and compare
    equal to the release at the same base version.
    """
    try:
        return tuple(int(p) for p in re.findall(r"\d+", version))
    except ValueError:  # pragma: no cover - the regex only yields ints
        return (0,)


def is_newer(remote: str | None, current: str | None) -> bool:
    """True if `remote` is a strictly newer version than `current`."""
    if not remote or not current:
        return False
    if remote == current:
        return False
    return parse_version(remote) > parse_version(current)


# ---------------------------------------------------------------------------
# Location helpers
# ---------------------------------------------------------------------------

def current_version() -> str:
    """The version this running build advertises."""
    from config import settings

    return settings.version


def exe_dir() -> Path:
    """The folder containing the running executable, or the project root
    in development."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    from config import PROJECT_ROOT

    return PROJECT_ROOT


def current_exe() -> Path | None:
    """The packaged executable path, or None when running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return None


def can_self_update() -> bool:
    """Self-update is only possible for a packaged build."""
    return current_exe() is not None


def staged_exe_path() -> Path | None:
    """Where the downloaded update would live (next to the running exe."""
    exe = current_exe()
    if exe is None:
        return None
    return exe.with_name(exe.name + STAGED_SUFFIX)


def manifest_url() -> str:
    """The configured update-manifest URL (empty = updates disabled)."""
    from config import settings

    return settings.update_manifest_url


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------

def fetch_manifest(url: str) -> UpdateInfo | None:
    """GET the manifest and parse it into an UpdateInfo.

    Raises UpdateError on network or parsing problems. Returns None only
    when the remote says the current build is the newest.
    """
    import requests

    try:
        response = requests.get(url, timeout=_MANIFEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise UpdateError(f"Could not reach the update server: {exc}") from exc
    except ValueError as exc:
        raise UpdateError("The update manifest is not valid JSON.") from exc

    version = str(data.get("version") or "").strip()
    download_url = str(data.get("url") or "").strip()
    if not version or not download_url:
        raise UpdateError(
            "The update manifest is missing a 'version' or 'url' field."
        )
    return UpdateInfo(
        version=version,
        url=download_url,
        sha256=str(data.get("sha256") or "").strip().lower(),
        notes=str(data.get("notes") or "").strip(),
    )


def check_for_update(url: str | None = None) -> UpdateInfo | None:
    """Return the advertised update, or None if already up to date.

    Raises UpdateError when the update server cannot be contacted or the
    manifest is malformed.
    """
    url = url if url is not None else manifest_url()
    if not url:
        raise UpdateError("Updates are not configured - set UPDATE_MANIFEST_URL.")
    info = fetch_manifest(url)
    if info is None:
        return None
    if not is_newer(info.version, current_version()):
        return None
    return info


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------

def sha256_of(path: Path) -> str:
    """Hex SHA-256 digest of a file's contents."""
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_DOWNLOAD_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_to(url: str, dest: Path) -> None:
    """Stream `url` into `dest` (used for the staged executable)."""
    import requests

    try:
        with requests.get(url, stream=True, timeout=_DOWNLOAD_TIMEOUT) as response:
            response.raise_for_status()
            with open(dest, "wb") as handle:
                for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK):
                    if chunk:
                        handle.write(chunk)
    except requests.RequestException as exc:
        raise UpdateError(f"Download failed: {exc}") from exc


def stage_update(info: UpdateInfo) -> Path:
    """Download the new executable next to the running one.

    Verifies the SHA-256 from the manifest when one is supplied. Returns
    the path of the staged file.
    """
    dest = staged_exe_path()
    if dest is None:
        raise UpdateError("You are running from source - nothing to update.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _download_to(info.url, dest)

    if info.sha256:
        actual = sha256_of(dest)
        if actual != info.sha256:
            dest.unlink(missing_ok=True)
            raise UpdateError(
                f"Downloaded file failed its integrity check "
                f"(expected {info.sha256[:12]}…, got {actual[:12]}…)."
            )
    log.info("Update v%s staged at %s", info.version, dest)
    return dest


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------

def _swap_script() -> str:
    """A small batch script that completes the executable swap on Windows."""
    exe = current_exe()
    if exe is None:
        return ""
    old = exe
    new = exe.with_name(exe.name + STAGED_SUFFIX)
    backup = exe.with_name(exe.name + BACKUP_SUFFIX)

    lines = [
        "@echo off",
        # Give this process a moment to fully exit and release the file lock.
        "timeout /t 2 /nobreak >nul",
        f'move /y "{new}" "{old}"',
        f'del /f /q "{backup}" >nul 2>&1',
        'start "" "{old}"',
        'del "%~f0"',
    ]
    return "\r\n".join(lines) + "\r\n"


def apply_update() -> Path:
    """Finish a staged update: launch the swap script and return it.

    The caller is expected to close the app right after (see the settings
    view / `ui/dashboard.py`). Returns the path of the spawned script.
    """
    exe = current_exe()
    if exe is None:
        raise UpdateError("You are running from source - nothing to update.")
    staged = exe.with_name(exe.name + STAGED_SUFFIX)
    if not staged.exists():
        raise UpdateError("No staged update found. Download it first.")

    script = exe.with_name("_apply_update.cmd")
    script.write_text(_swap_script(), encoding="utf-8")

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            ["cmd", "/c", str(script)],
            creationflags=creation_flags,
            close_fds=True,
        )
    except OSError as exc:
        raise UpdateError(f"Could not launch the installer: {exc}") from exc
    log.info("Update installer launched; app will restart.")
    return script


def cleanup_after_launch() -> None:
    """Remove leftover update artifacts (stale .new/.old/builds).

    Called at startup so a half-finished update never blocks the next run.
    """
    exe = current_exe()
    if exe is None:
        return
    for suffix in (BACKUP_SUFFIX,):
        leftover = exe.with_name(exe.name + suffix)
        leftover.unlink(missing_ok=True)