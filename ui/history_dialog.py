"""
History dialog - browse and reopen saved conversations (Phase 22).

The database keeps every conversation; this dialog lists them so the
user can reopen an old chat, delete one, or start fresh (the "new
conversation" top-bar button handles the last case).
"""

from __future__ import annotations

import flet as ft

_ACCENT = "#00e5ff"
_TEXT = "#e6f1ff"
_MUTED = "#9fb3d1"


class HistoryDialog(ft.AlertDialog):
    """List saved conversations with {open, delete} actions per row."""

    def __init__(self, page: ft.Page, database, dashboard):
        self._page = page
        self._db = database
        self._dashboard = dashboard

        self.list_view = ft.ListView(expand=True, spacing=6, padding=4)

        super().__init__(
            modal=True,
            title=ft.Text(
                "CONVERSATION HISTORY",
                size=14,
                weight=ft.FontWeight.BOLD,
                color=_ACCENT,
                font_family="Consolas",
            ),
            content=ft.Container(
                content=self.list_view,
                width=420,
                height=360,
                padding=4,
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

    def refresh(self) -> None:
        """Rebuild the list from the database."""
        self.list_view.controls.clear()
        conversations = self._db.list_conversations()
        if not conversations:
            self.list_view.controls.append(
                ft.Text(
                    "No saved conversations yet.",
                    size=13,
                    color=_MUTED,
                )
            )
        else:
            for conv in conversations:
                self.list_view.controls.append(self._row(conv))
        try:
            self.list_view.update()
        except RuntimeError:
            pass

    def _row(self, conv: dict) -> ft.Container:
        title = (conv.get("title") or "Conversation").strip()
        created = (conv.get("created_at") or "")[:16]
        count = conv.get("message_count") or 0
        active = conv["id"] == self._db.current_conversation_id()

        label = title
        if active:
            label += "   [current]"

        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Column(
                        controls=[
                            ft.Text(
                                label,
                                size=13,
                                color=_TEXT,
                                weight=ft.FontWeight.BOLD if active else None,
                            ),
                            ft.Text(
                                f"{created}   ·   {count} messages",
                                size=11,
                                color=_MUTED,
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.CHAT_BUBBLE_OUTLINE,
                        tooltip="Open conversation",
                        icon_color=_ACCENT,
                        icon_size=18,
                        style=ft.ButtonStyle(overlay_color=ft.Colors.with_opacity(0.3, _ACCENT)),
                        on_click=lambda e, cid=conv["id"]: self._open(cid),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        tooltip="Delete conversation",
                        icon_color="#ff6b6b",
                        icon_size=18,
                        style=ft.ButtonStyle(overlay_color=ft.Colors.with_opacity(0.3, "#ff6b6b")),
                        on_click=lambda e, cid=conv["id"]: self._delete(cid),
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.with_opacity(0.4, "#0b1220"),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.35, _ACCENT)),
            border_radius=10,
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
        )

    def _open(self, conversation_id: int) -> None:
        self._dashboard._open_conversation(conversation_id)
        self.open = False
        self._page.update()

    def _delete(self, conversation_id: int) -> None:
        self._dashboard._delete_conversation(conversation_id)
        self.refresh()
        self._page.update()