"""
Settings view - the dialog opened by the settings button.

The most common settings are shown here. Some values are applied to the
live services immediately (e.g. voice and speech speed); a persisted
settings system is added in a later phase.

API keys are deliberately NOT shown here - they live in the .env file.
"""

from __future__ import annotations

import flet as ft

from voice.text_to_speech import get_tts_service

_ACCENT = "#00e5ff"


class SettingsView(ft.AlertDialog):
    """A futuristic settings dialog."""

    def __init__(self, page: ft.Page, on_save, tts_service=None, database=None):
        self._page = page
        self._on_save = on_save
        self._tts = tts_service or get_tts_service()
        self._db = database

        self.assistant_name = ft.TextField(
            label="Assistant name",
            value="JARVIS",
            width=320,
            border_color=ft.Colors.with_opacity(0.4, _ACCENT),
        )
        self.wake_word = ft.TextField(
            label="Wake word (Phase 5)",
            value="hey jarvis",
            width=320,
            border_color=ft.Colors.with_opacity(0.4, _ACCENT),
        )

        # NOTE: the voice list is loaded lazily in refresh_voices() when the
        # dialog opens. Loading it here would initialise the speech engine
        # during startup and freeze the window for several seconds.
        self.tts_voice = ft.Dropdown(
            label="Voice",
            width=320,
            options=[],
            value=self._tts.voice_name or "",
            border_color=ft.Colors.with_opacity(0.4, _ACCENT),
        )

        self.tts_speed = ft.TextField(
            label="Speech speed (words/min)",
            value=str(self._tts.rate),
            width=320,
            keyboard_type=ft.KeyboardType.NUMBER,
            border_color=ft.Colors.with_opacity(0.4, _ACCENT),
        )

        self.tts_enabled = ft.Switch(
            label="Speak replies aloud",
            value=self._tts.enabled,
            active_color=_ACCENT,
        )

        self.wake_enabled = ft.Switch(
            label="Wake word listener",
            value=False,
            active_color=_ACCENT,
        )

        # Phase 36: after a spoken reply, keep listening for the next thing
        # to say so the user can have a back-and-forth hands-free chat.
        from config import settings

        self.continuous_enabled = ft.Switch(
            label="Continuous conversation (keep listening)",
            value=bool(getattr(settings, "continuous_conversation", False)),
            active_color=_ACCENT,
        )

        self.theme = ft.Dropdown(
            label="Theme",
            width=320,
            options=[
                ft.dropdown.Option("futuristic", "Futuristic"),
                ft.dropdown.Option("midnight", "Midnight"),
            ],
            value="futuristic",
            border_color=ft.Colors.with_opacity(0.4, _ACCENT),
        )

        note = ft.Text(
            "API keys are managed in the .env file and are never shown here.",
            size=11,
            italic=True,
            color=ft.Colors.with_opacity(0.6, "#9fb3d1"),
        )

        # --- Software updates (Phase 21) ---------------------------------
        self.update_status = ft.Text(
            "",
            size=12,
            color=ft.Colors.with_opacity(0.75, "#9fb3d1"),
        )
        self.check_updates_btn = ft.TextButton(
            "Check for updates",
            on_click=self._on_check_updates,
        )
        self.install_updates_btn = ft.ElevatedButton(
            "Download & install",
            on_click=self._on_install_update,
            disabled=True,
            bgcolor=_ACCENT,
            color="#0b1220",
        )
        self._pending_update = None  # set by _on_check_updates

        # --- Long-term memory manager (Phase 22) --------------------------
        self.memory_list = ft.ListView(spacing=4, padding=4, height=160)
        self.memory_status = ft.Text(
            "",
            size=11,
            color=ft.Colors.with_opacity(0.75, "#9fb3d1"),
        )
        self.refresh_memories_btn = ft.TextButton(
            "Refresh",
            on_click=self._on_refresh_memories,
        )

        # --- Permissions (Phase 25) ---------------------------------------
        self.unrestricted_enabled = ft.Switch(
            label="Unrestricted mode (no boundaries)",
            value=False,
            active_color=_ACCENT,
        )
        self.permissions_note = ft.Text(
            "When on, JARVIS runs tools (files, apps, URLs, screenshots, "
            "patches) without asking for approval first, and drops the "
            "ask-permission rules from its instructions.",
            size=11,
            italic=True,
            color=ft.Colors.with_opacity(0.6, "#9fb3d1"),
        )

        # --- Camera (Phase 31) ----------------------------------------------
        self.camera_enabled = ft.Switch(
            label="Camera fall detection (always-on)",
            value=True,
            active_color="#22c55e",
            inactive_thumb_color="#5a6b85",
        )
        self.camera_note = ft.Text(
            "When on, your webcam runs continuously to watch for falls. "
            "A detected fall starts a countdown before help is alerted.",
            size=11,
            italic=True,
            color=ft.Colors.with_opacity(0.6, "#9fb3d1"),
        )

        # --- Smart glasses / wearables (Phase 33) ----------------------------
        self.glasses_enabled = ft.Switch(
            label="Smart glasses link (wearables)",
            value=True,
            active_color="#22c55e",
            inactive_thumb_color="#5a6b85",
        )
        self.glasses_mirror = ft.Switch(
            label="Mirror JARVIS replies to glasses",
            value=False,
            active_color=_ACCENT,
            inactive_thumb_color="#5a6b85",
        )
        self.glasses_device = ft.TextField(
            label="Glasses name (optional)",
            hint_text="e.g. Ray-Ban, XREAL Air",
            border_radius=8,
            value="",
            filled=True,
        )
        self.glasses_note = ft.Text(
            "JARVIS talks to whatever Bluetooth wearable is paired - it "
            "cannot embed itself into the hardware. Notifications are "
            "shown as a toast and spoken aloud on audio-capable glasses.",
            size=11,
            italic=True,
            color=ft.Colors.with_opacity(0.6, "#9fb3d1"),
        )

        # --- Bedtime mode (Phase 37) ----------------------------------------
        # Quiet hours: dim the screen and keep replies text-only at night.
        from config import settings as _settings

        self.bedtime_schedule = ft.Switch(
            label="Quiet hours (schedule bedtime mode)",
            value=bool(getattr(_settings, "bedtime_schedule_enabled", False)),
            active_color="#7c4dff",
        )
        self.bedtime_start = ft.TextField(
            label="Start time (HH:MM)",
            value=getattr(_settings, "bedtime_start", "22:30"),
            width=160,
            border_color=ft.Colors.with_opacity(0.4, _ACCENT),
        )
        self.bedtime_end = ft.TextField(
            label="End time (HH:MM)",
            value=getattr(_settings, "bedtime_end", "06:30"),
            width=160,
            border_color=ft.Colors.with_opacity(0.4, _ACCENT),
        )
        self.bedtime_now = ft.Switch(
            label="Bedtime mode right now (dim + quiet)",
            value=False,
            active_color="#7c4dff",
        )
        self.bedtime_note = ft.Text(
            "When on, the screen dims and JARVIS replies are text-only "
            "during quiet hours (overnight windows supported).",
            size=11,
            italic=True,
            color=ft.Colors.with_opacity(0.6, "#9fb3d1"),
        )

        super().__init__(
            modal=True,
            title=ft.Text("SETTINGS", color=_ACCENT, weight=ft.FontWeight.BOLD),
            content=self._build_tabs(note),
            actions=[
                ft.TextButton("Cancel", on_click=self._close),
                ft.FilledButton("Save", on_click=self._save),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            bgcolor="#0d1424",
        )

    def _build_tabs(self, note: ft.Text) -> ft.Tabs:
        """Group the many settings into tabs so the dialog is not crowded."""
        voice_pane = self._pane(
            self.assistant_name,
            self.wake_word,
            self.tts_voice,
            self.tts_speed,
            self.tts_enabled,
            self.wake_enabled,
            self.continuous_enabled,
            self.theme,
            note,
        )
        updates_pane = self._pane(
            self.update_status,
            ft.Row(
                controls=[
                    self.check_updates_btn,
                    self.install_updates_btn,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
        )
        memory_pane = self._pane(
            self.memory_status,
            self.memory_list,
            ft.Row(
                controls=[self.refresh_memories_btn],
                alignment=ft.MainAxisAlignment.END,
            ),
        )
        permissions_pane = self._pane(
            self.unrestricted_enabled,
            self.permissions_note,
        )
        camera_pane = self._pane(
            self.camera_enabled,
            self.camera_note,
        )
        glasses_pane = self._pane(
            self.glasses_enabled,
            self.glasses_mirror,
            self.glasses_device,
            self.glasses_note,
        )
        bedtime_pane = self._pane(
            self.bedtime_schedule,
            ft.Row(
                controls=[self.bedtime_start, self.bedtime_end],
                spacing=12,
            ),
            self.bedtime_now,
            self.bedtime_note,
        )

        bar = ft.TabBar(
            tabs=[
                ft.Tab(label="Voice"),
                ft.Tab(label="Updates"),
                ft.Tab(label="Memory"),
                ft.Tab(label="Permissions"),
                ft.Tab(label="Camera"),
                ft.Tab(label="Glasses"),
                ft.Tab(label="Bedtime"),
            ],
            scrollable=True,
            indicator_color=_ACCENT,
            label_color=_ACCENT,
            unselected_label_color="#9fb3d1",
            divider_color=ft.Colors.with_opacity(0.25, "#9fb3d1"),
        )
        view = ft.TabBarView(
            controls=[
                voice_pane,
                updates_pane,
                memory_pane,
                permissions_pane,
                camera_pane,
                glasses_pane,
                bedtime_pane,
            ],
            expand=True,
        )
        return ft.Tabs(
            length=7,
            selected_index=0,
            content=ft.Column(
                height=400,
                spacing=0,
                controls=[bar, view],
            ),
        )

    @staticmethod
    def _pane(*controls) -> ft.Container:
        """A single tab pane: fills the bounded TabBarView, scrolls if long."""
        return ft.Container(
            content=ft.Column(
                controls=list(controls),
                spacing=14,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            ),
            width=440,
            expand=True,
            padding=ft.Padding.symmetric(horizontal=4, vertical=16),
        )

    def refresh_updates(self) -> None:
        """(Re)show the current version / update status when the dialog opens."""
        from updates.updater import can_self_update, current_version, manifest_url

        base = f"Current version: {current_version()}"
        if not manifest_url():
            self.update_status.value = (
                base + "  (updates not configured - set UPDATE_MANIFEST_URL)"
            )
        elif not can_self_update():
            self.update_status.value = base + "  (running from source)"
        else:
            self.update_status.value = base
        self._pending_update = None
        self.install_updates_btn.disabled = True

    def _on_check_updates(self, e) -> None:
        self.update_status.value = "Checking for updates...  "
        self._page.update()
        self._page.run_thread(self._do_check_updates)

    def _do_check_updates(self) -> None:
        """Run on a worker thread: query the manifest, then repaint."""
        from updates.updater import UpdateError, check_for_update

        try:
            update = check_for_update()
        except UpdateError as exc:
            self._pending_update = None
            self.update_status.value = f"Update check failed: {exc}"
        else:
            self._pending_update = update
            if update is None:
                from updates.updater import current_version

                self.update_status.value = (
                    f"You are running the latest version ({current_version()})."
                )
            else:
                notes = f"  {update.notes}" if update.notes else ""
                self.update_status.value = (
                    f"Version {update.version} available{notes}"
                )
        self.install_updates_btn.disabled = self._pending_update is None
        self._page.update()

    def _on_install_update(self, e) -> None:
        if self._pending_update is None:
            return
        self.update_status.value = "Downloading update...  "
        self.check_updates_btn.disabled = True
        self.install_updates_btn.disabled = True
        self._page.update()
        self._page.run_thread(self._do_install_update)

    def _do_install_update(self) -> None:
        """Download the update, then hand control to the settings opener so
        the app can close and let the swap script finish the job."""
        from updates.updater import UpdateError, stage_update

        info = self._pending_update
        try:
            staged = stage_update(info)
        except UpdateError as exc:
            self.update_status.value = f"Update failed: {exc}"
            self.check_updates_btn.disabled = False
            self._page.update()
            return
        self.update_status.value = (
            f"Update v{info.version} downloaded. Restarting...  "
        )
        self._page.update()
        # Swap script is launched; the app closes and relaunches.
        from updates.updater import apply_update

        try:
            apply_update()
        except UpdateError as exc:
            self.update_status.value = f"Update failed: {exc}"
            self.check_updates_btn.disabled = False
            self._page.update()
            return
        self.open = False
        if hasattr(self._page, "window"):
            self._page.window.destroy()

    def _close(self, e) -> None:
        self.open = False
        self._page.update()

    def _on_refresh_memories(self, e) -> None:
        self.refresh_memories()
        self._page.update()

    def refresh_memories(self) -> None:
        """Rebuild the long-term memory list from the database (Phase 22)."""
        if self._db is None:
            from memory.database import get_shared_database

            self._db = get_shared_database()

        self.memory_list.controls.clear()
        memories = self._db.list_memories(limit=50)
        if not memories:
            self.memory_list.controls.append(
                ft.Text(
                    "No saved memories yet. Say 'remember ...' to store one.",
                    size=12,
                    color=ft.Colors.with_opacity(0.7, "#9fb3d1"),
                )
            )
        else:
            for memory in memories:
                self.memory_list.controls.append(self._memory_row(memory))
        self.memory_status.value = f"{len(memories)} saved memories"
        try:
            self.memory_list.update()
        except RuntimeError:
            pass

    def _memory_row(self, memory: dict) -> ft.Container:
        created = (memory.get("created_at") or "")[:16]
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Text(
                        memory["content"],
                        size=12,
                        color="#e6f1ff",
                        expand=True,
                        max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        tooltip="Forget this",
                        icon_color="#ff6b6b",
                        icon_size=16,
                        style=ft.ButtonStyle(
                            overlay_color=ft.Colors.with_opacity(0.3, "#ff6b6b")
                        ),
                        on_click=lambda e, mid=memory["id"]: self._delete_memory(mid),
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.with_opacity(0.4, "#0b1220"),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.25, "#9fb3d1")),
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            tooltip=memory["content"],
        )

    def _delete_memory(self, memory_id: int) -> None:
        if self._db is not None:
            self._db.delete_memory(memory_id)
        self.refresh_memories()
        self._page.update()

    def _save(self, e) -> None:
        self._on_save(self)
        self.open = False
        self._page.update()

    def refresh_voices(self) -> None:
        """(Re)load the available voice names. Slow on very first call,
        so it is invoked only when the dialog opens - never at startup."""
        try:
            names = self._tts.list_voices()
        except Exception:  # noqa: BLE001
            names = []
        self.tts_voice.options = [ft.dropdown.Option(name) for name in names]
        if not self.tts_voice.value:
            self.tts_voice.value = (
                self._tts.voice_name if self._tts.voice_name in names else (names[0] if names else "")
            )
