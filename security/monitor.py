"""
ThreatMonitor (Phase 28) - runs the collectors on a schedule.

Design:
    * a daemon thread runs a full scan every `interval_seconds`;
    * the latest alerts are kept in an in-memory ring buffer;
    * each scan is persisted into the SQLite `security_events` table
      (category "threat") when a Database is available;
    * a callback (`on_update`) is fired after every scan so the UI can
      repaint the security dashboard.

The monitor ONLY reports. It never performs remediation of any kind.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from typing import Callable

from security.collectors import run_all
from security.threats import (
    ThreatAlert,
    status_from_alerts,
    status_meta,
    sort_alerts,
)

_DEFAULT_INTERVAL = 60  # seconds between scans
_MAX_KEPT_ALERTS = 50


class ThreatMonitor:
    def __init__(
        self,
        database=None,
        on_update: Callable[[str, list[ThreatAlert]], None] | None = None,
        interval_seconds: int = _DEFAULT_INTERVAL,
        runner: Callable[[], list[ThreatAlert]] = run_all,
    ):
        self._database = database
        self._on_update = on_update
        self._interval = max(5, int(interval_seconds))
        self._runner = runner
        self._alerts: deque[ThreatAlert] = deque(maxlen=_MAX_KEPT_ALERTS)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_scan: str | None = None

    # -- lifecycle ------------------------------------------------------
    def start(self) -> None:
        """Begin periodic scanning in a background daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="threat-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the scan loop (the thread exits at the next wait)."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def scan_now(self) -> list[ThreatAlert]:
        """Run one scan synchronously and update state. Safe to call anytime."""
        alerts = self._runner()
        with self._lock:
            for alert in alerts:
                self._alerts.append(alert)
            self._last_scan = datetime.now().isoformat(timespec="seconds")
            current = list(self._alerts)
        if self._database is not None:
            self._persist(alerts)
        if self._on_update is not None:
            self._on_update(self.status(), current)
        return alerts

    # -- reporting ------------------------------------------------------
    def status(self) -> str:
        """Overall posture string (normal / suspicious / high_risk)."""
        with self._lock:
            current = list(self._alerts)
        return status_from_alerts(current)

    def alerts(self) -> list[ThreatAlert]:
        """All retained alerts, newest/most severe first."""
        with self._lock:
            current = list(self._alerts)
        return sort_alerts(current)

    def last_scan(self) -> str | None:
        with self._lock:
            return self._last_scan

    def dashboard_data(self) -> dict:
        """Everything the UI needs to render the security dashboard."""
        status = self.status()
        meta = status_meta(status)
        alerts = self.alerts()
        by_sev = {"low": 0, "medium": 0, "high": 0}
        for alert in alerts:
            by_sev[alert.severity] = by_sev.get(alert.severity, 0) + 1
        return {
            "status": status,
            "label": meta["label"],
            "color": meta["color"],
            "message": meta["message"],
            "alerts": alerts,
            "counts": by_sev,
            "last_scan": self.last_scan(),
        }

    # -- internals ------------------------------------------------------
    def _loop(self) -> None:
        self.scan_now()  # one scan immediately so the dashboard is populated
        while not self._stop_event.wait(self._interval):
            try:
                self.scan_now()
            except Exception:  # noqa: BLE001 - monitoring never kills the app
                pass

    def _persist(self, alerts: list[ThreatAlert]) -> None:
        db = self._database
        if db is None:
            return
        for alert in alerts:
            if alert.severity not in ("medium", "high"):
                continue  # only persist findings worth reviewing
            try:
                db.add_security_event(
                    level=alert.severity,
                    category="threat",
                    action=alert.source,
                    detail=f"{alert.detected} [{alert.process}]",
                )
            except Exception:  # noqa: BLE001 - persistence must never crash
                pass