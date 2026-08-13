"""
Attachment bar (Phase 32) - chips for files the user is attaching to chat.

Sits above the message input. Each chip shows a small preview (thumbnail
for images, an icon for documents/others) plus the file name, and a close
button to remove it. The dashboard owns the list of Paths; the bar is a
pure view with callbacks.
"""

from __future__ import annotations

from pathlib import Path

import flet as ft

from tools.attachments import classify

_CHIP_TINT = ft.Colors.with_opacity(0.55, "#101828")
_BG = "#101828"
_BORDER = "#2f6bb0"
_TEXT = "#cfe3ff"
_MUTED = ft.Colors.with_opacity(0.75, "#9fb3d1")


class _Chip:
    def __init__(
        self,
        path: Path,
        on_remove: "callable[[str], None] | None",
    ):
        self.path = path
        kind = classify(path)
        if kind == "image":
            try:
                preview = ft.Image(
                    src=str(path),
                    width=44,
                    height=44,
                    fit=ft.ImageFit.COVER,
                    border_radius=8,
                )
            except Exception:  # noqa: BLE001 - bad image must not crash the row
                preview = ft.Icon(ft.Icons.IMAGE_OUTLINED, color=_MUTED, size=26)
        else:
            icon = ft.Icons.DESCRIPTION_OUTLINED if kind == "document" else ft.Icons.INSERT_DRIVE_FILE_OUTLINED
            preview = ft.Icon(icon, color=_MUTED, size=26)

        remove = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_size=14,
            tooltip="Remove",
            icon_color=ft.Colors.with_opacity(0.8, "#9fb3d1"),
            on_click=lambda e: on_remove(str(path)) if on_remove else None,
        )

        body = ft.Row(
            controls=[
                preview,
                ft.Container(
                    content=ft.Text(
                        path.name,
                        size=11,
                        color=_TEXT,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    width=170,
                ),
                remove,
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self._container = ft.Container(
            content=body,
            bgcolor=ft.Colors.with_opacity(0.9, _BG),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.35, _BORDER)),
            border_radius=10,
            padding=ft.Padding.symmetric(horizontal=8, vertical=6),
        )

    def to_control(self) -> ft.Control:
        return self._container


class AttachmentBar(ft.Container):
    """A horizontal band of attachment chips above the message input."""

    def __init__(self, on_remove=None):
        self._on_remove = on_remove
        self._chips: list[_Chip] = []
        self._row = ft.Row(spacing=8, wrap=True, controls=[])
        super().__init__(
            content=self._row,
            visible=False,
            padding=ft.Padding.only(bottom=8),
        )

    def add(self, paths) -> None:
        newly = 0
        for raw in paths:
            path = Path(raw)
            if not path.is_file():
                continue
            for chip in self._chips:
                if chip.path.resolve() == path.resolve():
                    break
            else:
                self._chips.append(_Chip(path, self._on_remove))
                newly += 1
        if newly:
            self._rebuild()

    def remove(self, path: str) -> None:
        target = Path(path).resolve()
        self._chips = [
            chip for chip in self._chips if chip.path.resolve() != target
        ]
        self._rebuild()

    def clear(self) -> None:
        if not self._chips:
            return
        self._chips = []
        self._rebuild()

    @property
    def paths(self) -> list[str]:
        return [str(chip.path) for chip in self._chips]

    @property
    def count(self) -> int:
        return len(self._chips)

    def _rebuild(self) -> None:
        self._row.controls = [chip.to_control() for chip in self._chips]
        self.visible = bool(self._chips)
        try:
            self.update()
        except RuntimeError:
            pass