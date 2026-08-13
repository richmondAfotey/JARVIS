"""
Chat view - the conversation area.

A scrollable list of message bubbles. "User" messages are aligned to
the right, "assistant" messages to the left, with a small label.

* `add_message(role, text)`   - append a finished message.
* `begin_message(role)`       - start a live streaming bubble (text
                                arrives token by token via `.append()`),
                                with a blinking caret until `.finish()`.
* `thinking()`                - a placeholder bubble with animated dots,
                                shown while JARVIS generates (Phase 17).
* `clear()`                   - remove all messages.

Phase 17 polish: blinking caret on streaming replies, an animated
"generating..." indicator, and auto-scroll.

IMPORTANT: every time the list contents change we call `self._list.update()`
so Flet repaints the new bubble immediately.
"""

from __future__ import annotations

import threading
import time

import flet as ft

_BG_USER = "#1e3a5f"
_BG_ASSISTANT = "#16233b"
_BORDER_USER = "#2f6bb0"
_BORDER_ASSISTANT = "#0f2a47"
_TEXT = "#e6f1ff"
_LABEL = ft.Colors.with_opacity(0.7, "#9fc8ff")
_CARET = "▌"
_THINK_DOTS = ["●", "● ○ ○", "○ ● ○", "○ ○ ●"]


class _StreamingBubble:
    """A growing message bubble with a blinking caret while streaming."""

    def __init__(self, list_view: ft.ListView, label: str, bg: str, border: str):
        self._list = list_view
        self._base = ""
        self._caret_on = False
        self._caret_running = False
        self._caret_thread: threading.Thread | None = None

        self.text = ft.Text(
            "",
            size=14,
            color=_TEXT,
            selectable=True,
        )
        bubble = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(
                        label,
                        size=10,
                        weight=ft.FontWeight.BOLD,
                        color=_LABEL,
                        font_family="Consolas",
                    ),
                    self.text,
                ],
                spacing=4,
            ),
            bgcolor=bg,
            border=ft.Border.all(1, border),
            border_radius=12,
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            width=700,
        )
        list_view.controls.append(bubble)

    # -- Caret animation --------------------------------------------------
    def start_caret(self) -> None:
        if self._caret_running:
            return
        self._caret_running = True
        self._caret_thread = threading.Thread(target=self._blink, daemon=True)
        self._caret_thread.start()

    def _blink(self) -> None:
        try:
            while self._caret_running:
                self._caret_on = not self._caret_on
                self._repaint()
                time.sleep(0.4)
        except Exception:
            self._caret_running = False

    def stop_caret(self) -> None:
        self._caret_running = False
        self._caret_on = False

    # -- Text -------------------------------------------------------------
    def append(self, chunk: str) -> None:
        self._base += chunk
        self._refresh()

    def set_text(self, text: str) -> None:
        self._base = text
        self.text.value = text
        self._refresh()

    def finish(self) -> None:
        """Stop the caret and settle the text at its final content."""
        self.stop_caret()
        self.text.value = self._base
        self._refresh()

    def _visible(self) -> str:
        return self._base + (_CARET if self._caret_on else "")

    def _repaint(self) -> None:
        self.text.value = self._visible()
        self._refresh()

    def _refresh(self) -> None:
        """Repaint the list, ignoring the error raised before the control
        is attached to the page (e.g. while the dashboard is being built)."""
        self._list.auto_scroll = True
        try:
            self._list.update()
        except RuntimeError:
            pass


class _ThinkingBubble:
    """An animated "generating..." placeholder, shown until a reply arrives."""

    def __init__(self, list_view: ft.ListView, label: str, bg: str, border: str):
        self._list = list_view
        self._index = 0
        self._running = False
        self._thread: threading.Thread | None = None

        self._container = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(
                        label,
                        size=10,
                        weight=ft.FontWeight.BOLD,
                        color=_LABEL,
                        font_family="Consolas",
                    ),
                    ft.Text(
                        "generating " + _THINK_DOTS[0],
                        size=14,
                        color=ft.Colors.with_opacity(0.65, _TEXT),
                        font_family="Consolas",
                    ),
                ],
                spacing=4,
            ),
            bgcolor=bg,
            border=ft.Border.all(1, border),
            border_radius=12,
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            width=700,
        )
        list_view.controls.append(self._container)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def _animate(self) -> None:
        try:
            while self._running:
                self._index = (self._index + 1) % len(_THINK_DOTS)
                self._container.content.controls[1].value = (
                    "generating " + _THINK_DOTS[self._index]
                )
                self._list.auto_scroll = True
                try:
                    self._list.update()
                except RuntimeError:
                    pass
                time.sleep(0.35)
        finally:
            self._running = False

    def remove(self) -> None:
        self._running = False
        try:
            if self._container in self._list.controls:
                self._list.controls.remove(self._container)
            self._list.update()
        except RuntimeError:
            pass
        except Exception:
            pass


class ChatView(ft.Container):
    """Scrollable message list."""

    def __init__(self, assistant_name: str = "JARVIS"):
        self._assistant_label = assistant_name.upper()

        self._list = ft.ListView(
            spacing=10,
            padding=ft.Padding.symmetric(horizontal=16, vertical=12),
            auto_scroll=True,
            expand=True,
        )

        super().__init__(
            content=self._list,
            expand=True,
            bgcolor=ft.Colors.with_opacity(0.35, "#0b1220"),
            border_radius=14,
            border=ft.Border.all(1, ft.Colors.with_opacity(0.12, "#00e5ff")),
        )

        # A friendly welcome message so the screen is not empty.
        self.add_message(
            "assistant",
            f"Systems online. I am {assistant_name}, your assistant. "
            "Type a message below or use the microphone button.",
        )

    def _style(self, role: str) -> tuple[str, str, str]:
        is_user = role == "user"
        label = "YOU" if is_user else self._assistant_label
        bg = _BG_USER if is_user else _BG_ASSISTANT
        border = _BORDER_USER if is_user else _BORDER_ASSISTANT
        return label, bg, border

    def _bubble(self, role: str) -> _StreamingBubble:
        label, bg, border = self._style(role)
        return _StreamingBubble(self._list, label, bg, border)

    def add_message(self, role: str, text: str) -> None:
        """Append one finished message bubble to the conversation."""
        bubble = self._bubble(role)
        bubble.set_text(text)

    def begin_message(self, role: str) -> _StreamingBubble:
        """Start a live, streaming message bubble (caret optional)."""
        return self._bubble(role)

    def thinking(self) -> _ThinkingBubble:
        """Show an animated 'generating...' bubble and return it so the
        caller can `remove()` it once a real reply starts (Phase 17)."""
        label, bg, border = self._style("assistant")
        bubble = _ThinkingBubble(self._list, label, bg, border)
        bubble.start()
        return bubble

    def clear(self) -> None:
        """Remove all messages."""
        self._list.controls.clear()
        try:
            self._list.update()
        except RuntimeError:
            pass