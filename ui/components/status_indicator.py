"""
Status indicator - the small "assistant status" widget.

Shows the current state of JARVIS:
    IDLE      - waiting for input
    LISTENING - microphone is active
    THINKING  - the AI brain is generating a reply
    SPEAKING  - text-to-speech is playing
    EXECUTING - a tool / computer action is running
    ERROR     - something failed

Each state has its own colour so the user can read the app at a glance.
"""

from __future__ import annotations

import flet as ft

# colour per state: (label, colour)
_STATE_STYLES = {
    "idle":      ("IDLE",      ft.Colors.BLUE_GREY_300),
    "listening": ("LISTENING", ft.Colors.RED_400),
    "thinking":  ("THINKING",  ft.Colors.AMBER_400),
    "speaking":  ("SPEAKING",  ft.Colors.CYAN_400),
    "executing": ("EXECUTING", ft.Colors.PURPLE_400),
    "error":     ("ERROR",     ft.Colors.RED_400),
}


class StatusIndicator(ft.Row):
    """A dot + label that reflects the assistant's current state."""

    def __init__(self, initial: str = "idle", dot_size: float = 12):
        self._state = initial.lower()
        self._dot_size = dot_size

        label_text, colour = _STATE_STYLES.get(self._state, _STATE_STYLES["idle"])

        self.dot = ft.Container(
            width=dot_size,
            height=dot_size,
            border_radius=dot_size / 2,
            bgcolor=colour,
        )

        self.label = ft.Text(
            label_text,
            size=12,
            weight=ft.FontWeight.BOLD,
            color=colour,
            font_family="Consolas",
        )

        super().__init__(
            controls=[self.dot, self.label],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def set_state(self, state: str) -> None:
        """Change the visible state of the indicator."""
        state = (state or "idle").lower()
        if state not in _STATE_STYLES:
            state = "idle"
        self._state = state
        label, colour = _STATE_STYLES[state]
        self.dot.bgcolor = colour
        self.label.value = label
        self.label.color = colour
        try:
            self.update()
        except RuntimeError:
            pass
