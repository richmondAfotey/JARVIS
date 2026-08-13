"""
File picker helper (Phase 32) - wrap Flet's native file chooser.

Flet >= 0.86 changed the FilePicker API: it is now an async ``Service``
(no page overlay needed, no ``on_result`` callback). ``pick_files()``
returns the selected files directly, so this helper runs it as a page task
and feeds the resulting paths to the caller's callback.
"""

from __future__ import annotations

import flet as ft

_ACCEPTED = [
    "png", "jpg", "jpeg", "gif", "bmp", "webp", "svg",
    "txt", "md", "log", "csv", "json", "ini", "yaml", "yml",
    "pdf", "docx", "xlsx", "pptx",
]


class FilePickHelper:
    """Owns a Flet FilePicker instance and fires a callback on pick."""

    def __init__(self, page: ft.Page, on_pick=None):
        self._page = page
        self._on_pick = on_pick
        self.picker = ft.FilePicker()

    def open_attach(self) -> None:
        """Open the picker and hand the chosen absolute paths to on_pick."""
        self._page.run_task(self._pick)

    async def _pick(self) -> None:
        try:
            files = await self.picker.pick_files(
                allow_multiple=True,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=_ACCEPTED,
                dialog_title="Choose images or documents for JARVIS",
            )
        except Exception:  # noqa: BLE001 - cancelled/unsupported picker
            return
        paths = [f.path for f in files if getattr(f, "path", None)]
        if paths and self._on_pick:
            self._on_pick(paths)