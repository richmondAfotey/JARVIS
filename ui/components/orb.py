"""
AI core orb - the animated centrepiece of the interface.

A glowing circular "core" with an outer ring. A background thread makes
it pulse gently while the app is running (Phase 1) and its colour and
pulse speed now react to JARVIS's activity (Phase 17):

    IDLE       - slow purple/cyan pulse
    THINKING   - amber pulse, faster
    SPEAKING   - cyan pulse, strong
    LISTENING  - red pulse

This is an ORIGINAL design - a simple glowing core - not a copy of any
movie interface.
"""

from __future__ import annotations

import threading
import time

import flet as ft

_ACCENT = "#00e5ff"
_PURPLE = "#7c4dff"

_MODES = {
    "idle": {
        "accent": _ACCENT,
        "core": _PURPLE,
        "speed": 0.09,
        "amplitude": 0.08,
    },
    "thinking": {
        "accent": "#ffbf3f",
        "core": _PURPLE,
        "speed": 0.055,
        "amplitude": 0.13,
    },
    "speaking": {
        "accent": _ACCENT,
        "core": "#00bcd4",
        "speed": 0.05,
        "amplitude": 0.17,
    },
    "listening": {
        "accent": "#ff4d5e",
        "core": "#d22f42",
        "speed": 0.06,
        "amplitude": 0.14,
    },
}


class Orb(ft.Container):
    """A pulsing AI core. Call `start()` to begin the animation."""

    def __init__(self, size: float = 140):
        self._size = size
        self._running = False
        self._mode = "idle"
        self._thread: threading.Thread | None = None

        style = _MODES["idle"]

        self.glow = ft.Container(
            width=size,
            height=size,
            border_radius=size / 2,
            bgcolor=ft.Colors.with_opacity(0.30, style["accent"]),
            animate_opacity=ft.Animation(900, "easeInOut"),
            opacity=0.35,
        )

        self.core = ft.Container(
            width=size - 24,
            height=size - 24,
            gradient=ft.RadialGradient(
                center=ft.Alignment(0.0, 0.0),
                radius=1.2,
                colors=[style["core"], "#1b2a4a", "#0d1424"],
            ),
            shape=ft.BoxShape.CIRCLE,
            border=ft.Border.all(2, ft.Colors.with_opacity(0.5, style["accent"])),
            shadow=ft.BoxShadow(
                blur_radius=30,
                spread_radius=2,
                color=ft.Colors.with_opacity(0.45, style["accent"]),
            ),
            content=ft.Icon(
                ft.Icons.BOLT,
                color=style["accent"],
                size=34,
            ),
            animate_scale=ft.Animation(900, "easeInOut"),
        )

        self.ring = ft.Container(
            width=size,
            height=size,
            border_radius=size / 2,
            border=ft.Border.all(1, ft.Colors.with_opacity(0.25, style["core"])),
            animate_opacity=ft.Animation(1200, "easeInOut"),
        )

        super().__init__(
            content=ft.Stack(
                controls=[self.glow, self.ring, self.core],
                alignment=ft.Alignment(0, 0),
            ),
            width=size,
            height=size,
            animate_scale=ft.Animation(900, "easeInOut"),
        )

    # -- State (Phase 17) -------------------------------------------------
    def set_mode(self, mode: str) -> None:
        """Switch the orb's colour + pulse to reflect JARVIS's activity."""
        style = _MODES.get(mode)
        if style is None:
            return
        self._mode = mode
        accent = style["accent"]
        try:
            self.glow.bgcolor = ft.Colors.with_opacity(0.30, accent)
            self.core.gradient = ft.RadialGradient(
                center=ft.Alignment(0.0, 0.0),
                radius=1.2,
                colors=[style["core"], "#1b2a4a", "#0d1424"],
            )
            self.core.border = ft.Border.all(2, ft.Colors.with_opacity(0.5, accent))
            self.core.shadow = ft.BoxShadow(
                blur_radius=30,
                spread_radius=2,
                color=ft.Colors.with_opacity(0.45, accent),
            )
            self.ring.border = ft.Border.all(1, ft.Colors.with_opacity(0.25, style["core"]))
            self.core.content.icon_color = accent
            self.update()
        except RuntimeError:
            pass

    def current_mode(self) -> str:
        return self._mode

    # -- Animation loop ----------------------------------------------------
    def start(self) -> None:
        """Begin the gentle pulsing animation in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._pulse, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the animation loop."""
        self._running = False

    def _pulse(self) -> None:
        up = True
        step = 0.08
        opacity = 0.30
        try:
            while self._running:
                style = _MODES[self._mode]
                speed = style["speed"]
                base_amp = style["amplitude"]

                if up:
                    opacity = min(opacity + step, 0.75)
                    if opacity >= 0.75:
                        up = False
                else:
                    opacity = max(opacity - step, 0.20)
                    if opacity <= 0.20:
                        up = True

                self.core.scale = ft.Scale(scale=1.0 + (opacity - 0.45) * base_amp)
                self.glow.opacity = opacity
                self.ring.opacity = 0.15 + (opacity - 0.20) * 0.4
                self.update()
                time.sleep(speed)
        except Exception:
            self._running = False
