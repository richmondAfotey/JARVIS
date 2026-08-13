"""
Folder watcher (Phase 30).

Polls a configured folder on a daemon thread and reports new/modified files
through an `on_change` callback so the dashboard can surface them (and
optionally feed them into the local RAG index). Uses plain stdlib polling
(no watchdog dependency) so it works everywhere.

Enabled only when `settings.watch_folder` points at a real directory.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from config import settings
from utils.logger import get_logger

log = get_logger(__name__)

_SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", "dist", "build"}


def _iter_files(root: Path) -> list[tuple[Path, float, int]]:
    """Snap (path, mtime, size) for every interesting file under root."""
    snapshot: list[tuple[Path, float, int]] = []
    try:
        for child in root.rglob("*"):
            if child.is_dir():
                continue
            if any(part in _SKIP_DIRS for part in child.parts):
                continue
            try:
                stat = child.stat()
                snapshot.append((child, stat.st_mtime, stat.st_size))
            except OSError:
                continue
    except OSError as exc:  # noqa: BLE001 - a bad path must never crash
        log.warning("Folder scan failed: %s", exc)
    return snapshot


class FolderWatcher:
    """Tracks file changes under a folder using cheap mtime/size polling."""

    def __init__(
        self,
        folder: str | None = None,
        on_change: Callable[[list[Path]], None] | None = None,
        poll_seconds: float = 5.0,
        max_report: int = 10,
    ) -> None:
        self._folder = Path(folder).expanduser() if folder else None
        self._on_change = on_change
        self._poll = float(poll_seconds)
        self._max_report = int(max_report)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: dict[Path, tuple[float, int]] = {}

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def folder(self) -> Path | None:
        return self._folder

    def start(self) -> bool:
        """Start watching. Returns False when there is nothing to watch."""
        if self.running:
            return True
        if self._folder is None or not self._folder.is_dir():
            return False
        self._last = {(p, (m, s)) for p, m, s in _iter_files(self._folder)}
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="folder-watcher", daemon=True
        )
        self._thread.start()
        log.info("Watching folder: %s", self._folder)
        return True

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._check()
            except Exception as exc:  # noqa: BLE001 - watcher never dies
                log.debug("Folder watch check failed: %s", exc)
            self._stop.wait(self._poll)

    def _check(self) -> None:
        fresh = {(p, (m, s)) for p, m, s in _iter_files(self._folder)}
        changed: list[Path] = []
        for p, (m, s) in fresh:
            if p not in self._last or self._last[p] != (m, s):
                changed.append(p)
        for p in self._last:
            if p not in {item[0] for item in fresh}:
                changed.append(p)
        self._last = fresh
        if changed and self._on_change is not None:
            self._on_change(sorted(changed)[: self._max_report])


_shared_watcher: FolderWatcher | None = None


def get_shared_watcher() -> FolderWatcher:
    """A FolderWatcher over the configured folder (no callback)."""
    global _shared_watcher
    if _shared_watcher is None:
        _shared_watcher = FolderWatcher(folder=settings.watch_folder or None)
    return _shared_watcher