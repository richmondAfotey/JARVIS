"""
Security Dashboard (Phase 28).

A modal dialog that shows the current security posture and every detected
indicator. Each alert lists:
    * what was detected
    * why it is suspicious
    * which process / application is involved
    * when it occurred
    * severity
    * recommended action

The dashboard never acts on its own: it only reports and recommends.
"""

from __future__ import annotations

import flet as ft

from security.threats import CLEAN_MESSAGE, sort_alerts

_ACCENT = "#00e5ff"
_TITLE = "#e6f1ff"
_MUTED = "#9fb3d1"

_SEV_COLORS = {
    "low": "#5a6b85",
    "medium": "#fbbf24",
    "high": "#ef4444",
}
_SEV_LABELS = {
    "low": "LOW",
    "medium": "MEDIUM",
    "high": "HIGH",
}


class SecurityDashboard(ft.AlertDialog):
    """Shows live security posture + every detected indicator."""

    def __init__(self, page: ft.Page, monitor):
        self._page = page
        self._monitor = monitor

        self.status_text = ft.Text(
            "🟢 NORMAL",
            size=30,
            weight=ft.FontWeight.BOLD,
            color="#22c55e",
            font_family="Consolas",
        )
        self.message_text = ft.Text(
            CLEAN_MESSAGE,
            size=13,
            color=_MUTED,
            italic=True,
        )
        self.counts_text = ft.Text(
            "",
            size=12,
            color=_MUTED,
            font_family="Consolas",
        )
        self.last_scan_text = ft.Text(
            "",
            size=11,
            color=_MUTED,
            font_family="Consolas",
        )
        self.alerts_list = ft.ListView(expand=True, spacing=6, padding=4)

        status_block = ft.Column(
            controls=[
                ft.Text(
                    "SECURITY STATUS",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=_ACCENT,
                    font_family="Consolas",
                ),
                self.status_text,
                self.message_text,
                self.counts_text,
                self.last_scan_text,
            ],
            spacing=4,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

        scan_btn = ft.FilledButton(
            "Scan now",
            icon=ft.Icons.REFRESH,
            on_click=self._scan_now,
        )

        super().__init__(
            modal=True,
            title=ft.Text(
                "SECURITY DASHBOARD",
                size=14,
                weight=ft.FontWeight.BOLD,
                color=_ACCENT,
                font_family="Consolas",
            ),
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        status_block,
                        scan_btn,
                        ft.Divider(height=1, color=ft.Colors.with_opacity(0.3, _ACCENT)),
                        self.alerts_list,
                    ],
                    spacing=10,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                width=520,
                height=440,
                padding=8,
            ),
            actions=[
                ft.TextButton("Close", on_click=self._close),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            bgcolor="#0d1424",
        )

    def _close(self, e) -> None:
        self.open = False
        self._page.update()

    def _scan_now(self, e) -> None:
        # Run synchronously in a worker thread so the UI stays responsive;
        # refresh when it returns.
        self._page.run_thread(self._do_scan)

    def _do_scan(self) -> None:
        self._monitor.scan_now()
        self.refresh()

    def refresh(self) -> None:
        """Repaint the whole dashboard from the monitor's latest state."""
        data = self._monitor.dashboard_data()
        self.status_text.value = data["label"]
        self.status_text.color = data["color"]
        self.message_text.value = data["message"]
        counts = data["counts"]
        self.counts_text.value = (
            f"low {counts.get('low', 0)}  ·  medium {counts.get('medium', 0)}"
            f"  ·  high {counts.get('high', 0)}"
        )
        last = data.get("last_scan")
        self.last_scan_text.value = f"last scan: {last or 'never'}"

        self.alerts_list.controls.clear()
        alerts = data["alerts"]
        if not alerts:
            self.alerts_list.controls.append(
                ft.Text(
                    CLEAN_MESSAGE,
                    size=13,
                    color=_MUTED,
                )
            )
        else:
            for alert in sort_alerts(alerts):
                self.alerts_list.controls.append(self._alert_row(alert))
        try:
            self.update()
        except RuntimeError:
            pass

    def _alert_row(self, alert) -> ft.Container:
        sev_color = _SEV_COLORS.get(alert.severity, _MUTED)
        sev_label = _SEV_LABELS.get(alert.severity, "INFO")
        body = [
            ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Text(
                            sev_label,
                            size=9,
                            weight=ft.FontWeight.BOLD,
                            color=sev_color,
                            font_family="Consolas",
                        ),
                        bgcolor=ft.Colors.with_opacity(0.15, sev_color),
                        border_radius=4,
                        padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                    ),
                    ft.Text(
                        (alert.when or "")[11:19],
                        size=10,
                        color=_MUTED,
                        font_family="Consolas",
                    ),
                ],
                spacing=8,
            ),
            ft.Text(
                alert.detected,
                size=13,
                color=_TITLE,
                weight=ft.FontWeight.BOLD,
            ),
            ft.Text(
                f"Why: {alert.why}",
                size=12,
                color=_MUTED,
            ),
            ft.Text(
                f"Process/App: {alert.process}",
                size=12,
                color=_MUTED,
            ),
        ]
        if alert.recommended:
            body.append(
                ft.Text(
                    f"Recommended: {alert.recommended}",
                    size=12,
                    color=sev_color,
                )
            )
        return ft.Container(
            content=ft.Column(controls=body, spacing=3),
            bgcolor=ft.Colors.with_opacity(0.4, "#0b1220"),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.35, sev_color)),
            border_radius=10,
            padding=ft.Padding.all(10),
        )