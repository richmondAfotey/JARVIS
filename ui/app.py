"""
Flet application entry point.

This module owns the `ft.Page` and installs the Dashboard on it.

Run the whole application with:

    python main.py

(Flet opens a desktop window when running in FLET_APP view.)
"""

from __future__ import annotations

import flet as ft

from ui.dashboard import Dashboard

# The default futuristic colour scheme.
PAGE_BG = "#080c16"


def main(page: ft.Page) -> None:
    """Flet entry point. Called once the page is ready."""
    # Remove a leftover backup from a previous self-update (Phase 21).
    try:
        from updates.updater import cleanup_after_launch

        cleanup_after_launch()
    except Exception:  # noqa: BLE001 - never block startup on cleanup
        pass

    page.title = "JARVIS AI"
    page.bgcolor = PAGE_BG
    page.padding = 0
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 1280
    page.window.height = 800
    page.window.min_width = 1024
    page.window.min_height = 680

    dashboard = Dashboard(page)
    page.add(dashboard)

    # Start any background animations once the UI is shown.
    dashboard.start()

    # Orderly shutdown: intercept the close so every background thread
    # (mic/wake listener, reminder poller, orb, monitor) is stopped first.
    page.window.prevent_close = True
    page.window.on_event = lambda e: _on_window_event(e, page, dashboard)


def _on_window_event(event: ft.WindowEvent, page: ft.Page, dashboard: Dashboard) -> None:
    """Stop background work when the window close button is pressed."""
    if event.type != ft.WindowEventType.CLOSE:
        return
    try:
        dashboard.shutdown()
    except Exception:  # noqa: BLE001 - a failed teardown must not block close
        pass
    page.window.destroy()


def run() -> None:
    """Launch the desktop application."""
    ft.app(target=main, view=ft.AppView.FLET_APP)
