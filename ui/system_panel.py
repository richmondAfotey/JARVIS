"""
System panel - right side monitoring column.

Phase 1 shows the panel layout with placeholder values ("--").
Phase 9 will feed real CPU / RAM / storage / battery / network data
into these cards, so each card has a public `set_value()` method.

The two centre columns (CPU, RAM) also carry a small progress bar.
"""

from __future__ import annotations

import time

import flet as ft

_ACCENT = "#00e5ff"
_PURPLE = "#7c4dff"
_GREEN = "#22c55e"


class MetricCard(ft.Container):
    """A small stat card: title, big value, optional progress bar."""

    def __init__(self, title: str, unit: str = "", accent: str = _ACCENT):
        self._unit = unit
        self._accent = accent

        self._title_text = ft.Text(
            title.upper(),
            size=10,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.with_opacity(0.6, "#9fb3d1"),
            font_family="Consolas",
        )
        self._value_text = ft.Text(
            "--",
            size=22,
            weight=ft.FontWeight.BOLD,
            color=accent,
            font_family="Consolas",
        )
        self._bar = ft.ProgressBar(
            value=None,
            bar_height=4,
            color=accent,
            bgcolor=ft.Colors.with_opacity(0.15, accent),
        )

        body = ft.Column(
            controls=[
                self._title_text,
                ft.Row(
                    controls=[self._value_text],
                    spacing=4,
                ),
                self._bar,
            ],
            spacing=6,
        )

        super().__init__(
            content=body,
            bgcolor=ft.Colors.with_opacity(0.5, "#101828"),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.15, accent)),
            border_radius=10,
            padding=ft.Padding.all(12),
        )

    def set_value(self, value_text: str, percent: float | None = None) -> None:
        """Update the displayed value and optional progress bar.

        percent: 0.0..1.0 for the bar, or None to keep the bar neutral.
        """
        self._set_raw(value_text, percent)
        # The card may be updated before it is attached to the page (e.g.
        # while the dashboard is being built); ignore that error like the
        # chat view does.
        try:
            self.update()
        except RuntimeError:
            pass

    def _set_raw(self, value_text: str, percent: float | None) -> None:
        """Set values without repainting (used for batched refreshes)."""
        self._value_text.value = f"{value_text}{self._unit}"
        self._bar.value = percent


class FeedCard(ft.Container):
    """A small card showing a scrolling feed plus counters (Phase 16)."""

    def __init__(self, title: str, accent: str = _ACCENT):
        self._title_text = ft.Text(
            title.upper(),
            size=10,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.with_opacity(0.6, "#9fb3d1"),
            font_family="Consolas",
        )
        self._feed_text = ft.Text(
            "no activity yet",
            size=10,
            color="#9fb3d1",
            font_family="Consolas",
        )
        self._count_text = ft.Text(
            "",
            size=9,
            color=ft.Colors.with_opacity(0.7, accent),
            font_family="Consolas",
        )

        body = ft.Column(
            controls=[self._title_text, self._feed_text, self._count_text],
            spacing=6,
        )

        super().__init__(
            content=body,
            bgcolor=ft.Colors.with_opacity(0.5, "#101828"),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.15, accent)),
            border_radius=10,
            padding=ft.Padding.all(12),
        )

    def set_summary(self, feed: list[str], counts: str) -> None:
        self._feed_text.value = "\n".join(feed) if feed else "no activity yet"
        self._count_text.value = counts
        try:
            self.update()
        except RuntimeError:
            pass

    def record(
        self,
        title: str,
        detail: str,
        source: str = "",
        level: str = "info",
    ) -> None:
        """Append an event to the feed, keeping the newest entry on top."""
        marker = {"critical": "!!", "warning": "!", "info": "·"}.get(
            level, "·"
        )
        stamp = time.strftime("%H:%M")
        entry = f"[{stamp}] {marker} {title} {detail}".rstrip()
        if source:
            entry += f"  ({source})"
        feed = [entry] + self._feed_text.value.split("\n")
        self.set_summary(feed[:4], "")


class ThreatStatusCard(ft.Container):
    """A Phase 28 tile showing the security posture at a glance.

    Clicking it opens the full Security Dashboard (the dashboard wires the
    click handler). It reports posture honestly; a clean scan shows
    'No obvious indicators of compromise were detected.'
    """

    def __init__(self):
        self._label = ft.Text(
            "🟢 NORMAL",
            size=16,
            weight=ft.FontWeight.BOLD,
            color="#22c55e",
            font_family="Consolas",
        )
        self._sub = ft.Text(
            "No obvious indicators of compromise were detected.",
            size=10,
            color=ft.Colors.with_opacity(0.75, "#9fb3d1"),
        )
        body = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.SHIELD_OUTLINED, color="#22c55e", size=14),
                        ft.Text(
                            "THREAT MONITOR",
                            size=10,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.with_opacity(0.6, "#9fb3d1"),
                            font_family="Consolas",
                        ),
                    ],
                    spacing=6,
                ),
                self._label,
                self._sub,
            ],
            spacing=5,
        )
        super().__init__(
            content=body,
            bgcolor=ft.Colors.with_opacity(0.5, "#101828"),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.15, "#22c55e")),
            border_radius=10,
            padding=ft.Padding.all(12),
            ink=True,
        )

    def set_status(self, status: str, alert_count: int) -> None:
        from security.threats import status_meta

        meta = status_meta(status)
        self._label.value = meta["label"]
        self._label.color = meta["color"]
        self._sub.value = meta["message"] + (
            f"  ({alert_count} alert(s))" if alert_count else ""
        )
        try:
            self.update()
        except RuntimeError:
            pass


class CameraStatusCard(ft.Container):
    """A Phase 31 tile showing the always-on fall-detection camera status.

    Shows whether the camera monitor is running (a visible indicator that
    the camera is live) and lets the user toggle it. The dashboard wires
    the click handler.
    """

    def __init__(self):
        self._label = ft.Text(
            "● WATCHING",
            size=14,
            weight=ft.FontWeight.BOLD,
            color="#22c55e",
            font_family="Consolas",
        )
        self._sub = ft.Text(
            "Fall detection camera is live.",
            size=10,
            color=ft.Colors.with_opacity(0.75, "#9fb3d1"),
        )
        body = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.VIDEOCAM, color="#22c55e", size=14),
                        ft.Text(
                            "CAMERA / FALL DETECT",
                            size=10,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.with_opacity(0.6, "#9fb3d1"),
                            font_family="Consolas",
                        ),
                    ],
                    spacing=6,
                ),
                self._label,
                self._sub,
            ],
            spacing=5,
        )
        super().__init__(
            content=body,
            bgcolor=ft.Colors.with_opacity(0.5, "#101828"),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.15, "#22c55e")),
            border_radius=10,
            padding=ft.Padding.all(12),
            ink=True,
        )

    def set_status(self, running: bool, detail: str = "") -> None:
        color = "#22c55e" if running else "#5a6b85"
        self._label.value = "● WATCHING" if running else "○ OFF"
        self._label.color = color
        self._sub.value = detail or (
            "Fall detection camera is live."
            if running
            else "Camera fall detection is off."
        )
        self._sub.color = ft.Colors.with_opacity(0.75, "#9fb3d1")
        try:
            self.update()
        except RuntimeError:
            pass


class SystemPanel(ft.Container):
    """Right-hand column with the system monitoring cards."""

    def __init__(self):
        self.cpu = MetricCard("CPU Load", "%", accent=_ACCENT)
        self.ram = MetricCard("Memory", "%", accent=_PURPLE)
        self.storage = MetricCard("Storage", " free", accent=_GREEN)
        self.battery = MetricCard("Battery", "%", accent=_ACCENT)
        self.network = MetricCard("Network", "", accent=_PURPLE)
        self.uptime = MetricCard("Uptime", "", accent=_GREEN)
        self.tools = MetricCard("Tools", "", accent=_ACCENT)
        self.security = FeedCard("Security", accent="#ff6b9d")
        self.threats = ThreatStatusCard()
        self.camera = CameraStatusCard()

        header = ft.Row(
            controls=[
                ft.Icon(ft.Icons.SPEED, color=_ACCENT, size=16),
                ft.Text(
                    "SYSTEM MONITOR",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=_ACCENT,
                    font_family="Consolas",
                ),
            ],
            spacing=8,
        )

        self._status = ft.Text(
            "SENSORS PENDING",
            size=10,
            color=ft.Colors.with_opacity(0.5, "#9fb3d1"),
            font_family="Consolas",
        )

        column = ft.Column(
            controls=[
                header,
                self._status,
                self.cpu,
                self.ram,
                self.storage,
                self.battery,
                self.network,
                self.uptime,
                self.tools,
                self.camera,
                self.security,
                self.threats,
            ],
            spacing=10,
        )

        super().__init__(
            content=column,
            width=300,
            bgcolor=ft.Colors.with_opacity(0.5, "#0d1424"),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.12, _ACCENT)),
            border_radius=14,
            padding=ft.Padding.all(16),
        )

    def update_from(self, snapshot) -> None:
        """Repaint every card from a SystemSnapshot in one pass."""
        self.cpu._set_raw(snapshot.cpu_text, _percent(snapshot.cpu_percent))
        self.ram._set_raw(snapshot.ram_text, _percent(snapshot.ram_percent))
        self.storage._set_raw(snapshot.disk_free, None)
        self.battery._set_raw(snapshot.battery_text, _percent(snapshot.battery_percent))
        self.network._set_raw(snapshot.network, None)
        self.uptime._set_raw(snapshot.uptime, None)
        if snapshot.has_psutil:
            self._status.value = "LIVE FEED"
        try:
            self.update()
        except RuntimeError:
            pass


def _percent(value: float | None) -> float | None:
    """Convert a 0-100 reading to a 0-1 progress-bar value."""
    if value is None:
        return None
    return max(0.0, min(1.0, value / 100.0))
