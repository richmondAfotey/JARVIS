"""
Dashboard - the main screen layout.

Combines:
    * Top bar ......... title, status indicator, settings button
    * Centre ......... AI orb + chat view + input bar
    * Right .......... system monitor panel (placeholders until Phase 9)

The dashboard talks to the AI through `ai.brain.Brain` and never talks
to a specific provider directly.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import flet as ft

from ai.brain import Brain
from ai.providers.local_echo import LocalEchoProvider
from config import settings
from memory.database import Database
from ui.chat_view import ChatView
from ui.components.attachment_bar import AttachmentBar
from ui.components.orb import Orb
from ui.components.status_indicator import StatusIndicator
from ui.history_dialog import HistoryDialog
from ui.security_view import SecurityDashboard
from ui.settings_view import SettingsView
from ui.system_panel import SystemPanel
from utils.logger import get_logger
from voice.speech_to_text import SpeechToText
from voice.text_to_speech import get_tts_service
from voice.wake_word import WakeWordListener

_ACCENT = "#00e5ff"
_BG_TOP = "#0b1220"
_BG_BOTTOM = "#080c16"

log = get_logger(__name__)


class Dashboard(ft.Container):
    """The full futuristic command-centre layout."""

    def __init__(self, page: ft.Page):
        # NOTE: we store the page as self._page. The name "page" is a
        # read-only property provided by Flet controls, so it cannot be
        # used as a plain attribute on a control subclass.
        self._page = page

        # --- AI brain -----------------------------------------------------
        self.database = Database(settings.data_dir / "database" / "jarvis.db")
        # Phase 22: resume the most recent conversation instead of starting
        # a fresh empty one, so chat history survives a restart.
        self.database.resume_latest_conversation()
        # Reminder scheduler (Phase 11): polls for due reminders and
        # announces them. Started in `start()` so the UI is ready first.
        from memory.reminders import ReminderService
        from system.security import SecurityMonitor

        self.reminders = ReminderService(self.database, on_due=self._on_reminder_due)
        self.security = SecurityMonitor(self.database)
        # Phase 28: background threat scanner (observes + reports only).
        from security.monitor import ThreatMonitor

        self.threat_monitor = ThreatMonitor(
            database=self.database,
            interval_seconds=int(settings.threat_scan_interval),
        )
        # Phase 31: always-on camera fall detection. Started in `start()`
        # when enabled (default on), running on its own daemon thread.
        from camera.monitor import CameraFallMonitor

        self.camera_monitor = CameraFallMonitor(
            camera_index=settings.camera_fall_index,
            on_fall=self._on_fall_detected,
        )
        self._fall_active = False
        self._fall_cancelled = False

        # Phase 32: uploaded/pasted files land in <data_dir>/uploads.
        uploads_env = settings.uploads_dir.strip()
        self.uploads_dir = (
            Path(uploads_env).expanduser()
            if uploads_env
            else settings.data_dir / "uploads"
        )
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

        # Phase 32: file picker for attaching images/documents to a chat
        # message. In Flet >= 0.86 the picker is an async service - it no
        # longer needs to (or can) be attached to the page overlay.
        from ui.components.file_picker import FilePickHelper

        self.file_pick = FilePickHelper(self._page, on_pick=self._on_files_picked)
        self.attachment_bar = AttachmentBar(on_remove=self._on_attachment_remove)
        self._attachments_enabled = True

        self.brain = Brain(
            database=self.database,
            reminders=self.reminders,
            security=self.security,
        )
        self.busy = False  # guards against sending while a reply is streaming
        # Phase 22 fix: speech plays independently on its own thread so a
        # hung TTS engine can never freeze the chat flow. This counter
        # guards against stale speakers resetting a newer state.
        self._speaking_seq = 0

        # --- Voice (Phase 3: text-to-speech) ------------------------------
        self.tts = get_tts_service(settings)

        # --- Voice (Phase 4: speech recognition) --------------------------
        self.stt = SpeechToText(
            provider=settings.stt_provider,
            language=settings.stt_language,
        )

        # --- Voice (Phase 30: voice confirmation for sensitive actions) ---
        from tools.voice_confirm import wire_stt

        wire_stt(self.stt)

        # --- Voice (Phase 5: wake word) -----------------------------------
        # Listener starts paused; it only becomes active via the explicit
        # wake button (or WAKE_WORD_ENABLED=true in .env).
        self.wake_listener = WakeWordListener(
            wake_phrase=settings.wake_word,
            stt=self.stt,
            assistant_name=settings.assistant_name,
            on_wake=self._on_wake_detected,
        )

        self.status = StatusIndicator("idle")
        self.chat = ChatView(assistant_name="JARVIS")
        self.system = SystemPanel()
        # Phase 28: clicking the threat-status tile opens the dashboard.
        self.system.threats.on_click = self._on_open_security
        # Phase 31: clicking the camera tile toggles fall detection.
        self.system.camera.on_click = self._on_toggle_camera_monitor
        self.orb = Orb(size=140)

        # Phase 22: restore the saved conversation into both the UI and the
        # AI context so the assistant "remembers" the session after closing.
        self._restore_conversation()

        self.message_input = ft.TextField(
            hint_text="Message JARVIS...",
            border_radius=24,
            filled=True,
            bgcolor=ft.Colors.with_opacity(0.4, "#0d1424"),
            border_color=ft.Colors.with_opacity(0.35, _ACCENT),
            focused_border_color=_ACCENT,
            color="#e6f1ff",
            hint_style=ft.TextStyle(color=ft.Colors.with_opacity(0.5, "#9fb3d1")),
            expand=True,
            autofocus=True,
            on_submit=self._on_send,
        )

        self.mic_button = ft.IconButton(
            icon=ft.Icons.MIC,
            icon_size=22,
            tooltip="Hold to speak",
            icon_color=_ACCENT,
            style=ft.ButtonStyle(
                color=_ACCENT,
                shape=ft.CircleBorder(),
                bgcolor=ft.Colors.with_opacity(0.15, _ACCENT),
                overlay_color=ft.Colors.with_opacity(0.35, _ACCENT),
            ),
            on_click=self._on_mic,
        )

        self.wake_button = ft.IconButton(
            icon=ft.Icons.RECORD_VOICE_OVER,
            icon_size=20,
            tooltip="Enable wake word",
            icon_color="#5a6b85",
            style=ft.ButtonStyle(
                color="#5a6b85",
                shape=ft.CircleBorder(),
                overlay_color=ft.Colors.with_opacity(0.35, "#7c4dff"),
            ),
            on_click=self._on_toggle_wake,
        )

        self.send_button = ft.IconButton(
            icon=ft.Icons.SEND,
            icon_size=22,
            tooltip="Send",
            icon_color="#0b1220",
            style=ft.ButtonStyle(
                color="#0b1220",
                bgcolor=_ACCENT,
                shape=ft.CircleBorder(),
                overlay_color="#33e6ff",
            ),
            on_click=self._on_send,
        )

        self.speaker_button = ft.IconButton(
            icon=ft.Icons.VOLUME_UP if self.tts.enabled else ft.Icons.VOLUME_OFF,
            icon_size=20,
            tooltip="Toggle spoken replies",
            icon_color="#9fb3d1" if self.tts.enabled else "#5a6b85",
            style=ft.ButtonStyle(
                color="#9fb3d1",
                shape=ft.CircleBorder(),
                overlay_color=ft.Colors.with_opacity(0.35, "#9fb3d1"),
            ),
            on_click=self._on_toggle_tts,
        )

        # Restore voice/wake preferences saved in an earlier session (Phase 14).
        self._apply_saved_preferences()

        super().__init__(
            content=ft.Column(
                controls=[
                    self._build_top_bar(),
                    self._build_middle(),
                    self._build_input_bar(),
                ],
                spacing=0,
                expand=True,
            ),
            expand=True,
            gradient=ft.LinearGradient(
                begin=ft.Alignment(-1, -1),
                end=ft.Alignment(1, 1),
                colors=[_BG_TOP, _BG_BOTTOM],
            ),
            padding=ft.Padding.symmetric(horizontal=20, vertical=16),
        )

        self.settings_dialog = SettingsView(
            page, on_save=self._on_settings_save, tts_service=self.tts,
            database=self.database,
        )

        # Tell the user which mode we are running in.
        if not self.brain.is_online:
            self.chat.add_message(
                "assistant",
                "Running in OFFLINE MODE - no AI provider is configured. "
                "I can still help with basic local tasks (clock, calculations). "
                "To enable full conversations, add an API key to your .env file "
                "(see README.md) and restart.",
            )

        # Show how many tools the brain can call.
        if self.brain.tools_enabled:
            self.system.tools.set_value(f"{len(self.brain.tools)} ready")

    # -- Layout builders ----------------------------------------------------
    def _build_top_bar(self) -> ft.Container:
        title = ft.Row(
            controls=[
                ft.Icon(ft.Icons.AUTO_AWESOME, color=_ACCENT, size=20),
                ft.Text(
                    "JARVIS AI",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color="#e6f1ff",
                    font_family="Consolas",
                ),
            ],
            spacing=8,
        )

        status_row = ft.Row(
            controls=[
                ft.Icon(ft.Icons.RADAR, color=_ACCENT, size=16),
                self.status,
            ],
            spacing=8,
        )

        settings_btn = ft.IconButton(
            icon=ft.Icons.SETTINGS,
            tooltip="Settings",
            icon_color="#9fb3d1",
            style=ft.ButtonStyle(
                color="#9fb3d1",
                shape=ft.CircleBorder(),
                overlay_color=ft.Colors.with_opacity(0.35, "#9fb3d1"),
            ),
            on_click=self._on_settings,
        )

        history_btn = ft.IconButton(
            icon=ft.Icons.HISTORY,
            tooltip="Conversation history",
            icon_color="#9fb3d1",
            style=ft.ButtonStyle(
                color="#9fb3d1",
                shape=ft.CircleBorder(),
                overlay_color=ft.Colors.with_opacity(0.35, "#9fb3d1"),
            ),
            on_click=self._on_open_history,
        )

        new_chat_btn = ft.IconButton(
            icon=ft.Icons.NOTE_ADD,
            tooltip="New conversation",
            icon_color="#9fb3d1",
            style=ft.ButtonStyle(
                color="#9fb3d1",
                shape=ft.CircleBorder(),
                overlay_color=ft.Colors.with_opacity(0.35, "#9fb3d1"),
            ),
            on_click=self._on_new_conversation,
        )

        security_btn = ft.IconButton(
            icon=ft.Icons.SHIELD_OUTLINED,
            tooltip="Security dashboard",
            icon_color="#9fb3d1",
            style=ft.ButtonStyle(
                color="#9fb3d1",
                shape=ft.CircleBorder(),
                overlay_color=ft.Colors.with_opacity(0.35, "#22c55e"),
            ),
            on_click=self._on_open_security,
        )

        return ft.Container(
            content=ft.Row(
                controls=[
                    title,
                    ft.Container(expand=True),
                    status_row,
                    new_chat_btn,
                    history_btn,
                    security_btn,
                    settings_btn,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.only(bottom=12),
        )

    def _build_middle(self) -> ft.Container:
        orb_header = ft.Column(
            controls=[
                ft.Row(
                    controls=[self.orb],
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                ft.Text(
                    "ASSISTANT CORE",
                    size=11,
                    color=ft.Colors.with_opacity(0.6, "#9fb3d1"),
                    font_family="Consolas",
                ),
            ],
            spacing=4,
        )

        centre = ft.Container(
            content=ft.Column(
                controls=[
                    orb_header,
                    self.chat,
                ],
                spacing=12,
                expand=True,
            ),
            expand=True,
            padding=ft.Padding.only(right=16),
        )

        return ft.Container(
            content=ft.Row(
                controls=[centre, self.system],
                expand=True,
            ),
            expand=True,
        )

    def _build_input_bar(self) -> ft.Container:
        attach_btn = ft.IconButton(
            icon=ft.Icons.ATTACH_FILE,
            icon_size=20,
            tooltip="Attach an image or document",
            icon_color="#5a6b85",
            style=ft.ButtonStyle(
                color="#5a6b85",
                shape=ft.CircleBorder(),
                overlay_color=ft.Colors.with_opacity(0.25, "#7c4dff"),
            ),
            on_click=self._on_attach,
        )

        paste_btn = ft.IconButton(
            icon=ft.Icons.CONTENT_PASTE,
            icon_size=20,
            tooltip="Paste from clipboard",
            icon_color="#5a6b85",
            style=ft.ButtonStyle(
                color="#5a6b85",
                shape=ft.CircleBorder(),
                overlay_color=ft.Colors.with_opacity(0.25, "#7c4dff"),
            ),
            on_click=self._on_paste_clipboard,
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    self.attachment_bar,
                    ft.Row(
                        controls=[
                            self.mic_button,
                            self.wake_button,
                            attach_btn,
                            paste_btn,
                            self.message_input,
                            self.speaker_button,
                            self.send_button,
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=0,
            ),
            padding=ft.Padding.only(top=12),
        )

    # -- Event handlers ------------------------------------------------------
    def _on_send(self, e) -> None:
        text = (self.message_input.value or "").strip()
        if self.busy:
            return
        # An attachment alone is a valid message ("analyse this image").
        if not text and not self.attachment_bar.paths:
            return

        if text:
            self.chat.add_message("user", text)
        self.message_input.value = ""
        self.message_input.update()

        # Phase 32: lift the pending attachments now and clear the chip bar.
        attachments = list(self.attachment_bar.paths)
        self.attachment_bar.clear()
        if attachments:
            self.chat.add_message(
                "user",
                "Attached: " + ", ".join(Path(p).name for p in attachments),
            )

        # Phase 22: give the new conversation a readable title the first
        # time the user speaks to it.
        self._auto_title_conversation(text)

        # Run the AI in a background thread so the UI stays responsive.
        # `run_thread` gives us a worker that can still update controls.
        self._page.run_thread(
            self._process_message, text, attachments=attachments
        )

    def _process_message(
        self,
        user_text: str,
        emotion: str | None = None,
        attachments: list[str] | None = None,
    ) -> None:
        """Called on a worker thread: ask the brain, then speak the reply.

        ``emotion`` is an optional tone-of-voice hint (happy/sad/angry)
        detected from spoken audio; it is forwarded so JARVIS can respond
        empathetically.

        ``attachments`` is an optional list of file paths (Phase 32). Each
        one is analysed (image via vision, document via read_document) and
        its extracted content is folded into the user message so JARVIS
        answers *about* the attached files in the same turn.
        """
        # Phase 31: a typed "I'm ok / cancel" after a fall cancels the alarm.
        self._on_message_clears_fall(user_text)
        self.busy = True
        self.status.set_state("thinking")
        self.orb.set_mode("thinking")

        # Phase 17: animated "generating..." bubble until the first token.
        thinking = self.chat.thinking()
        bubble = None

        def on_token(chunk: str) -> None:
            nonlocal bubble
            if bubble is None:
                bubble = self.chat.begin_message("assistant")
                bubble.start_caret()
                thinking.remove()
            bubble.append(chunk)

        try:
            # Phase 32: analyse each attachment once and fold the extracted
            # text into the user message BEFORE the brain sees it, so the
            # reply is genuinely about the attached files.
            if attachments:
                from tools.attachments import build_user_message

                user_text = build_user_message(attachments, user_text)
            reply = self.brain.respond(
                user_text,
                on_token=on_token,
                on_tool=self._on_tool,
                emotion=emotion,
            )
            if bubble is None:
                bubble = self.chat.begin_message("assistant")
                thinking.remove()
                bubble.set_text(reply)
            else:
                bubble.finish()  # stop the blinking caret

            # Make sure the whole reply has been committed to the screen
            # (and painted) before it is read aloud, so the text finishes
            # appearing before the audio starts.
            self._page.update()
            time.sleep(0.1)

            # Speak the finished reply. Phase 22 fix: we must NOT block on
            # `tts.speak` here - pyttsx3's runAndWait() can hang after the
            # audio finishes on some SAPI5 setups, which left the status
            # stuck on "speaking" and `busy=True`, blocking follow-ups.
            # Instead the audio plays on its own daemon thread and the
            # chat flow resets to idle immediately.
            if reply.strip() and self.tts.enabled:
                # Phase 30: pass the detected tone so JARVIS speaks the
                # reply in a matching mood (slower for sad, brighter for
                # happy) when mood emphasis is enabled.
                self._start_reply_speaking(reply, emotion=emotion)

            # Phase 33: optionally mirror the reply to the smart glasses.
            if settings.glasses_enabled and settings.glasses_mirror_replies:
                self._mirror_to_glasses(reply)
            self.status.set_state("idle")
            self.orb.set_mode("idle")
        except Exception as exc:
            log.error("Brain failed for message %r: %s", user_text, exc)
            if bubble is None:
                bubble = self.chat.begin_message("assistant")
                thinking.remove()
            bubble.set_text(f"I hit a problem: {exc}")
            self.status.set_state("error")
            self.orb.set_mode("idle")
        finally:
            self.busy = False
            self._page.update()

    def _start_reply_speaking(self, reply: str, emotion: str | None = None) -> None:
        """Play a reply aloud without ever blocking the chat flow.

        Runs on a daemon thread with a sequence guard: only the newest
        speaker may flip the status back to idle, and only if the app is
        not already busy with something newer (thinking/listening).

        A hard time cap means even a wedged speech engine (pyttsx3's
        runAndWait() can hang after the audio finishes on some systems)
        cannot freeze the chat flow or leave the wake listener paused.

        ``emotion`` (happy/sad/angry) is passed to the TTS so the spoken
        reply can match the detected voice tone (Phase 30).
        """
        wake_was_running = self.wake_listener.running
        if wake_was_running:
            self.wake_listener.pause()

        self._speaking_seq += 1
        seq = self._speaking_seq
        # Generous cap: ~10s per full screen of text, minimum 20s.
        cap = max(20.0, (len(reply) / 80) * 10)

        def play() -> None:
            done = threading.Event()

            def _speak() -> None:
                try:
                    self.tts.speak(reply, emotion=emotion)
                finally:
                    done.set()

            speaker = threading.Thread(target=_speak, daemon=True)
            speaker.start()
            # Never wait forever on the engine - cap the wait and move on.
            speaker.join(timeout=cap)

            if wake_was_running:
                try:
                    self.wake_listener.resume()
                except Exception as exc:
                    log.error("Could not resume wake listener: %s", exc)
            # Only the newest speaker may settle the state, and only if
            # nothing newer (thinking/listening/error) has taken over.
            if seq == self._speaking_seq and not self.busy:
                self.status.set_state("idle")
                self.orb.set_mode("idle")
                try:
                    self._page.update()
                except RuntimeError:
                    pass

        threading.Thread(target=play, name="tts-speaker", daemon=True).start()

    def _on_wake_detected(self) -> None:
        """Called from the wake-word thread when the phrase is heard."""
        # Dispatch back to a page worker thread so UI updates are safe.
        self._page.run_thread(self._mic_flow)

    def _on_tool(self, name: str, args: dict, result: str) -> None:
        """Called (on a worker thread) when the brain runs a tool."""
        self.chat.add_message("assistant", f"[tool] {name} -> {result}")
        self.system.tools.set_value(name)
        # Phase 16: audit every executed tool call.
        self.security.record_tool(name, args, result)
        self._page.update()

    def _mirror_to_glasses(self, reply: str) -> None:
        """Phase 33: push a reply to the user's smart glasses (best-effort)."""
        try:
            from glasses.hub import GlassesHub
            from voice.text_to_speech import get_tts_service

            tts = get_tts_service(settings) if self.tts.enabled else None
            hub = GlassesHub(tts=tts)
            if settings.glasses_device:
                hub.select(settings.glasses_device)
            hub.notify(reply)
        except Exception as exc:  # noqa: BLE001 - mirroring must never block
            log.debug("Glasses mirror failed: %s", exc)

    def _on_toggle_tts(self, e) -> None:
        self.tts.set_enabled(not self.tts.enabled)
        self.speaker_button.icon = (
            ft.Icons.VOLUME_UP if self.tts.enabled else ft.Icons.VOLUME_OFF
        )
        self.speaker_button.icon_color = (
            "#9fb3d1" if self.tts.enabled else "#5a6b85"
        )
        self.speaker_button.update()
        self.database.set_preference(
            "tts_enabled", "true" if self.tts.enabled else "false"
        )

    def _on_mic(self, e) -> None:
        # Ignore while another task (or the microphone) is in use.
        if self.busy:
            return
        self._page.run_thread(self._mic_flow)

    def _microphone_note(self, emotion) -> str:
        """Short human-readable tone note to show under the spoken text."""
        if emotion is None or emotion.emotion == "neutral":
            return ""
        return f"\n(voice tone: {emotion.emotion})"

    def _mic_flow(self) -> None:
        """Worker thread: listen, transcribe, then hand the text to the brain."""
        self.busy = True
        # Keep the wake listener quiet while we actively listen.
        wake_was_running = self.wake_listener.running
        if wake_was_running:
            self.wake_listener.pause()
        try:
            if not self.stt.libraries_available:
                self.chat.add_message(
                    "assistant",
                    "Speech recognition libraries are not installed. "
                    "Run: pip install SpeechRecognition sounddevice",
                )
                return

            if not self.stt.mic_available():
                self.chat.add_message(
                    "assistant",
                    "No microphone was detected. Please connect one and try again.",
                )
                return

            self.status.set_state("listening")
            self.orb.set_mode("listening")
            self.chat.add_message(
                "assistant",
                "Listening... speak now. (Click the mic again to cancel.)",
            )
            if settings.tone_emotion_enabled:
                text, emotion = self.stt.listen_with_emotion()
            else:
                text = self.stt.listen()
                emotion = None
            if not text:
                self.chat.add_message("assistant", "I did not catch that. Please try again.")
                return
            # Phase 29: show the spoken words (and any tone hint) in the chat.
            self.chat.add_message("user", text + self._microphone_note(emotion))
            tone = emotion.emotion if emotion is not None else None
            # Phase 30: remember the detected tone so the mood_report tool
            # can spot trends over time (silently skipped for neutral).
            if emotion is not None and emotion.emotion not in ("neutral", ""):
                try:
                    from tools.mood import log_mood_emotion

                    log_mood_emotion(emotion.emotion, emotion.confidence)
                except Exception as exc:  # noqa: BLE001 - mood logging never breaks chat
                    log.debug("Mood log failed: %s", exc)
            self._process_message(text, emotion=tone)
        except Exception as exc:
            log.error("Mic flow failed: %s", exc)
            self.chat.add_message("assistant", str(exc))
            self.status.set_state("error")
            self.orb.set_mode("idle")
        finally:
            if wake_was_running:
                self.wake_listener.resume()
            self.busy = False
            self.orb.set_mode("idle")
            self._page.update()

    def _on_settings(self, e) -> None:
        if self.settings_dialog not in self._page.overlay:
            self._page.overlay.append(self.settings_dialog)
        self.settings_dialog.refresh_voices()
        self.settings_dialog.refresh_updates()
        self.settings_dialog.refresh_memories()
        self.settings_dialog.wake_enabled.value = self.wake_listener.running
        self.settings_dialog.unrestricted_enabled.value = self.brain.unrestricted_mode
        self.settings_dialog.camera_enabled.value = self.camera_monitor.running
        self.settings_dialog.glasses_enabled.value = settings.glasses_enabled
        self.settings_dialog.glasses_mirror.value = settings.glasses_mirror_replies
        self.settings_dialog.glasses_device.value = settings.glasses_device
        self.settings_dialog.open = True
        # A dialog inside the overlay only becomes "attached" to the page
        # after a full page.update(), so that is what we must call here.
        self._page.update()

    def _on_settings_save(self, view: SettingsView) -> None:
        # Apply TTS settings to the live service.
        self.tts.set_rate(view.tts_speed.value or 180)
        self.tts.set_voice(view.tts_voice.value or "")
        self.tts.set_enabled(view.tts_enabled.value)
        self.speaker_button.icon = (
            ft.Icons.VOLUME_UP if self.tts.enabled else ft.Icons.VOLUME_OFF
        )
        self.speaker_button.update()

        # Apply the wake-word toggle from settings.
        self._set_wake_running(view.wake_enabled.value)

        # Persist the choices so they survive a restart (Phase 14).
        self.database.set_preference(
            "tts_enabled", "true" if self.tts.enabled else "false"
        )
        self.database.set_preference("tts_voice", view.tts_voice.value or "")
        self.database.set_preference("tts_speed", str(view.tts_speed.value or 180))
        self.database.set_preference(
            "wake_word_enabled", "true" if view.wake_enabled.value else "false"
        )

        # Phase 25: apply + persist the no-boundaries mode live.
        self._set_unrestricted(view.unrestricted_enabled.value)

        # Phase 31: apply the camera fall-detection toggle live + persist it,
        # so "always-on camera" can be switched off from settings.
        self._set_camera_monitor_running(view.camera_enabled.value)
        self.database.set_preference(
            "camera_fall_enabled", "true" if view.camera_enabled.value else "false"
        )

        # Phase 33: persist the smart-glasses link choices.
        settings.glasses_enabled = bool(view.glasses_enabled.value)
        settings.glasses_mirror_replies = bool(view.glasses_mirror.value)
        settings.glasses_device = (view.glasses_device.value or "").strip()
        self.database.set_preference(
            "glasses_enabled", "true" if settings.glasses_enabled else "false"
        )
        self.database.set_preference(
            "glasses_mirror_replies", "true" if settings.glasses_mirror_replies else "false"
        )
        self.database.set_preference("glasses_device", settings.glasses_device)

        self.chat.add_message(
            "assistant",
            "Voice settings saved."
            f" Unrestricted mode: {'ON' if self.brain.unrestricted_mode else 'OFF'}."
            f" Camera fall detection: {'ON' if view.camera_enabled.value else 'OFF'}.",
        )

    def _apply_saved_preferences(self) -> None:
        """Restore voice/wake preferences saved in a previous session (Phase 14)."""
        try:
            prefs = self.database.all_preferences()
        except Exception:  # noqa: BLE001 - preferences must never block startup
            log.exception("Failed to load saved preferences")
            return
        if "tts_enabled" in prefs:
            self.tts.set_enabled(prefs["tts_enabled"].lower() in ("1", "true", "yes", "on"))
        if prefs.get("tts_voice"):
            self.tts.set_voice(prefs["tts_voice"])
        if "tts_speed" in prefs:
            try:
                self.tts.set_rate(int(prefs["tts_speed"]))
            except (TypeError, ValueError):
                pass
        self._wake_from_prefs = prefs.get("wake_word_enabled", "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        # Phase 25: restore the no-boundaries mode saved in a previous session.
        if "unrestricted_mode" in prefs:
            self._set_unrestricted(
                prefs["unrestricted_mode"].lower() in ("1", "true", "yes", "on")
            )
        # Phase 33: restore the smart-glasses link choices.
        if "glasses_enabled" in prefs:
            settings.glasses_enabled = prefs["glasses_enabled"].lower() in (
                "1", "true", "yes", "on"
            )
        if "glasses_mirror_replies" in prefs:
            settings.glasses_mirror_replies = prefs["glasses_mirror_replies"].lower() in (
                "1", "true", "yes", "on"
            )
        if prefs.get("glasses_device"):
            settings.glasses_device = prefs["glasses_device"]
        # Sync the speaker button with the restored TTS state. No .update()
        # here: the control is not on the page yet, and the first layout
        # pass renders the icon we set.
        self.speaker_button.icon = (
            ft.Icons.VOLUME_UP if self.tts.enabled else ft.Icons.VOLUME_OFF
        )
        self.speaker_button.icon_color = (
            "#9fb3d1" if self.tts.enabled else "#5a6b85"
        )

    def _set_unrestricted(self, enabled: bool) -> None:
        """Apply + persist the no-boundaries mode (Phase 25)."""
        self.brain.set_unrestricted(enabled)
        self.database.set_preference(
            "unrestricted_mode", "true" if enabled else "false"
        )
        log.info("Unrestricted mode %s", "ON" if enabled else "OFF")

    # -- Wake word -----------------------------------------------------------
    def _on_toggle_wake(self, e) -> None:
        self._set_wake_running(not self.wake_listener.running)

    def _set_wake_running(self, enable: bool) -> None:
        """Start or stop the wake-word listener and update its button."""
        if enable == self.wake_listener.running:
            return
        if enable:
            if not self.stt.libraries_available or not self.stt.mic_available():
                self.chat.add_message(
                    "assistant",
                    "Wake word needs a microphone and the speech recognition "
                    "libraries. Please connect a microphone and try again.",
                )
                return
            self.wake_listener.start()
            self.wake_button.icon = ft.Icons.EQUALIZER
            self.wake_button.icon_color = _ACCENT
            self.wake_button.tooltip = "Disable wake word"
            self.chat.add_message(
                "assistant",
                f"Wake word active. Say \"{settings.wake_word}\" and I will listen. "
                "The mic indicator is lit while this is enabled.",
            )
        else:
            self.wake_listener.stop()
            self.wake_button.icon = ft.Icons.RECORD_VOICE_OVER
            self.wake_button.icon_color = "#5a6b85"
            self.wake_button.tooltip = "Enable wake word"
            self.chat.add_message("assistant", "Wake word disabled.")
        self.wake_button.update()

    # -- Lifecycle ----------------------------------------------------------
    def start(self) -> None:
        """Start the orb animation and background monitor. Called after the
        page is ready."""
        self.orb.start()
        # Honour WAKE_WORD_ENABLED=true from .env, or the persisted setting
        # saved via Settings/voice (Phase 14) - both are explicit consent.
        if settings.wake_word_enabled or getattr(self, "_wake_from_prefs", False):
            self._set_wake_running(True)

        # Real-time system monitoring (Phase 9). A daemon thread repaints
        # the panel every couple of seconds; it dies with the process.
        self._monitor_stop = threading.Event()
        threading.Thread(
            target=self._monitor_loop,
            name="system-monitor",
            daemon=True,
        ).start()

        # Reminder scheduler (Phase 11).
        self.reminders.start()

        # Phase 28: start the background threat scanner.
        self.threat_monitor.start()
        self.system.threats.set_status(self.threat_monitor.status(), len(self.threat_monitor.alerts()))

        # Phase 31: always-on camera fall detection. Defaults to on via
        # CAMERA_FALL_ENABLED, but a saved Settings toggle wins: turning it
        # off there keeps the camera off until re-enabled.
        saved_prefs = self.database.all_preferences()
        camera_on = settings.camera_fall_enabled
        if "camera_fall_enabled" in saved_prefs:
            camera_on = saved_prefs["camera_fall_enabled"].lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
        if camera_on:
            self._set_camera_monitor_running(True)
        else:
            self.system.camera.set_status(False, "Camera fall detection is off.")
            self.chat.add_message(
                "assistant",
                "Camera fall detection is off - enable it any time in Settings "
                "or by clicking the camera tile.",
            )

        # Phase 30: push-to-talk global hotkey.
        if settings.ptt_enabled:
            from voice.ptt import PushToTalk

            self.ptt = PushToTalk(
                hotkey=settings.ptt_hotkey,
                on_trigger=self._on_mic,
            )
            if not self.ptt.start():
                self.chat.add_message(
                    "assistant",
                    "Push-to-talk is enabled but the 'keyboard' library is not "
                    "installed. Use the mic button instead, or run: "
                    "pip install keyboard",
                )
            else:
                self.chat.add_message(
                    "assistant",
                    f"Push-to-talk armed. Hold {settings.ptt_hotkey} and speak.",
                )

        # Phase 30: folder watcher (reports new/changed files).
        from system.folder_watcher import FolderWatcher

        self.folder_watcher = FolderWatcher(
            folder=settings.watch_folder or None,
            on_change=self._on_folder_changes,
        )
        if self.folder_watcher.start():
            log.info("Folder watcher watching %s", self.folder_watcher.folder)

        # Phase 30: focus-aware recap nudges after idle time.
        if settings.focus_recap_enabled:
            from system.focus_recap import FocusRecapService

            self.focus_recap = FocusRecapService(
                idle_minutes=settings.focus_recap_idle_minutes,
                on_idle=self._on_idle_recap,
            )
            if not self.focus_recap.start():
                self.chat.add_message(
                    "assistant",
                    "Focus recap is enabled but idle detection is unavailable "
                    "on this system.",
                )

        # Phase 30: optional morning briefing on startup.
        if settings.briefing_on_start:
            self._page.run_thread(self._run_briefing)

    # -- Chat history (Phase 22) -------------------------------------------
    def _restore_conversation(self) -> None:
        """Reload the saved conversation into the UI and the AI context.

        Called at startup. If the resumed conversation has no messages yet
        the default welcome bubble stays; otherwise the saved turns are
        shown and remembered.
        """
        messages = self.database.load_messages()
        self.brain.restore_history(messages)
        if not messages:
            return
        # Replace the welcome bubble with the restored history.
        self.chat.clear()
        for message in messages:
            if message["role"] in ("user", "assistant"):
                self.chat.add_message(message["role"], message["content"] or "")

    def _auto_title_conversation(self, user_text: str) -> None:
        """Title the conversation from the first user message (Phase 22)."""
        conversation_id = self.database.current_conversation_id()
        if conversation_id is None:
            return
        preview = self.database.conversation_preview(conversation_id)
        if preview and preview.get("message_count", 0) <= 1:
            title = (user_text.strip() or "Conversation")[:60]
            self.database.rename_conversation(conversation_id, title)

    def _on_new_conversation(self, e) -> None:
        """Start a brand-new conversation (history is kept in the database)."""
        self.database.start_conversation()
        self.brain.reset()
        self.chat.clear()
        self.chat.add_message(
            "assistant",
            "New conversation. Ask me anything - previous chats are saved "
            "in the history browser.",
        )
        self._page.update()

    def _on_open_history(self, e) -> None:
        """Show the saved-conversations browser dialog."""
        if not hasattr(self, "history_dialog"):
            self.history_dialog = HistoryDialog(self._page, self.database, self)
        self.history_dialog.refresh()
        if self.history_dialog not in self._page.overlay:
            self._page.overlay.append(self.history_dialog)
        self.history_dialog.open = True
        self._page.update()

    def _on_open_security(self, e) -> None:
        """Open the Phase 28 security dashboard."""
        if not hasattr(self, "security_dialog"):
            self.security_dialog = SecurityDashboard(self._page, self.threat_monitor)
        self.security_dialog.refresh()
        if self.security_dialog not in self._page.overlay:
            self._page.overlay.append(self.security_dialog)
        self.security_dialog.open = True
        self._page.update()

    def _open_conversation(self, conversation_id: int) -> None:
        """Load a conversation from the history browser into the view."""
        self.database.switch_conversation(conversation_id)
        messages = self.database.load_messages(conversation_id)
        self.brain.restore_history(messages)
        self.chat.clear()
        for message in messages:
            if message["role"] in ("user", "assistant"):
                self.chat.add_message(message["role"], message["content"] or "")
        self._page.update()

    def _delete_conversation(self, conversation_id: int) -> None:
        """Delete a conversation from the history browser."""
        self.database.delete_conversation(conversation_id)
        current = self.database.current_conversation_id()
        if current == conversation_id:
            # The active conversation was deleted - start fresh.
            self.database.resume_latest_conversation()
            messages = self.database.load_messages()
            self.brain.restore_history(messages)
            self.chat.clear()
            for message in messages:
                if message["role"] in ("user", "assistant"):
                    self.chat.add_message(message["role"], message["content"] or "")
        self._page.update()

    def _on_reminder_due(self, reminder: dict) -> None:
        """Called from the reminder thread when a reminder fires."""
        # Dispatch back to a page worker thread so UI updates are safe.
        self._page.run_thread(self._fire_reminder, reminder)

    def _fire_reminder(self, reminder: dict) -> None:
        """Show and speak a due reminder (runs on a page worker thread)."""
        text = reminder["text"]
        self.chat.add_message("assistant", f"REMINDER: {text}")
        if self.tts.enabled:
            # Speak via the same non-blocking path so a hung TTS engine
            # cannot freeze the reminder worker thread either (Phase 22).
            self._start_reply_speaking(f"Reminder. {text}")
        self._page.update()

    # -- Phase 30 background services --------------------------------------
    def _on_folder_changes(self, changed: list) -> None:
        """Folder watcher callback: show new/changed files in chat."""
        names = ", ".join(str(p.name) for p in changed)
        self._page.run_thread(
            self.chat.add_message,
            "assistant",
            f"Folder watcher: {len(changed)} file(s) changed - {names}",
        )
        self._page.run_thread(self._page.update)
        # Optionally feed the changed files into the local RAG index so
        # they can be queried later without re-indexing (Phase 30).
        if settings.watch_index_changes:
            try:
                from tools.rag import RagIndex

                RagIndex().index_files(list(changed))
            except Exception as exc:  # noqa: BLE001 - never let indexing break chat
                log.debug("Auto-index of changed files failed: %s", exc)
        log.info("Folder watcher detected %d change(s)", len(changed))

    def _on_idle_recap(self) -> None:
        """Focus recap callback: gently nudge the user back into focus."""
        self._page.run_thread(self._fire_idle_recap)

    def _fire_idle_recap(self) -> None:
        text = (
            "You have been away for a while. Take a breath - try "
            f"{settings.focus_recap_idle_minutes} focused minutes on your "
            "top task and I will keep your reminders in check."
        )
        self.chat.add_message("assistant", text)
        if self.tts.enabled:
            self._start_reply_speaking(text)
        self._page.update()

    def _run_briefing(self) -> None:
        """Run the morning briefing at startup (Phase 30)."""
        try:
            result = self.brain.tools.execute("morning_briefing", {})
        except Exception as exc:  # noqa: BLE001
            log.debug("Morning briefing failed: %s", exc)
            return
        self.chat.add_message("assistant", result)
        if self.tts.enabled:
            self._start_reply_speaking(result)
        self._page.update()

    # -- Phase 31: camera fall detection ------------------------------------
    def _on_toggle_camera_monitor(self, e) -> None:
        """Click the camera tile to start/stop fall detection."""
        self._set_camera_monitor_running(not self.camera_monitor.running)

    def _set_camera_monitor_running(self, enable: bool) -> None:
        if enable:
            if self.camera_monitor.running:
                return
            snapshot_dir = settings.data_dir / "camera" / "snapshots"
            if not self.camera_monitor.start(snapshot_dir=snapshot_dir):
                self.system.camera.set_status(
                    False,
                    "Camera unavailable: " + self.camera_monitor.status.replace("-", " "),
                )
                return
            self.system.camera.set_status(True)
            self.chat.add_message(
                "assistant",
                "Camera fall detection is on. If you fall, I will confirm "
                "with you, then alert your emergency contact and start a call.",
            )
        else:
            self.camera_monitor.stop()
            self.system.camera.set_status(False, "Camera fall detection is off.")
            self.chat.add_message("assistant", "Camera fall detection is off.")
        self._page.update()

    def _on_fall_detected(self, snapshot) -> None:
        """Camera monitor thread detected a fall - start the cancel countdown."""
        self._page.run_thread(self._fall_flow, snapshot)

    def _fall_flow(self, snapshot) -> None:
        """Ask the user to cancel a false alarm, else alert + call for help."""
        self._fall_active = True
        self._fall_cancelled = False
        cancel_seconds = max(3, int(settings.fall_countdown_seconds))
        message = (
            "I detected a possible fall. Say 'JARVIS I'm ok' or press the "
            f"camera tile to cancel - help will be alerted in {cancel_seconds} "
            "seconds."
        )
        self.chat.add_message("assistant", message)
        if self.tts.enabled:
            self._start_reply_speaking(
                "I think you may have fallen. Say cancel or press the camera "
                f"tile to stop me. I will call for help in {cancel_seconds} seconds."
            )
        self._page.update()
        # Persist the snapshot path so the security feed shows it.
        if snapshot is not None:
            try:
                self.security.record(
                    "fall", "detected", str(snapshot), level="critical"
                )
            except Exception:  # noqa: BLE001
                log.debug("Could not record fall event", exc_info=True)

        deadline = time.time() + cancel_seconds
        while time.time() < deadline and not self._stop.is_set():
            # Cancelled? The user either toggled the camera off or sent a
            # fresh "I'm ok" style message that clears the fall state.
            if not self.camera_monitor.running or getattr(self, "_fall_cancelled", False):
                self.chat.add_message(
                    "assistant", "Fall alert cancelled - glad you are ok."
                )
                self._fall_cancelled = False
                self._fall_active = False
                self._page.update()
                return
            time.sleep(0.25)

        # Countdown over: alert + call the emergency contact.
        self._fall_active = False
        self.chat.add_message(
            "assistant", "Alerting your emergency contact now - help is on the way."
        )
        self._page.update()
        self._raise_fall_alarm()

    def _raise_fall_alarm(self) -> None:
        """Send the emergency message + place the call (best effort)."""
        number = settings.fall_emergency_number
        email = settings.fall_emergency_email
        text = settings.fall_alert_message
        if not (number or email):
            self.chat.add_message(
                "assistant",
                "No emergency contact is configured. Set FALL_EMERGENCY_NUMBER "
                "or FALL_EMERGENCY_EMAIL in your .env file.",
            )
            self._page.update()
            return

        if number:
            try:
                self.brain.tools.execute(
                    "send_message",
                    {"recipient": number, "message": text, "channel": "whatsapp"},
                )
            except Exception as exc:  # noqa: BLE001 - keep trying the other channel
                log.warning("Fall SMS/WhatsApp failed: %s", exc)
            try:
                self.brain.tools.execute("make_call", {"number": number})
            except Exception as exc:  # noqa: BLE001
                log.warning("Fall call failed: %s", exc)
        if email:
            try:
                self.brain.tools.execute(
                    "send_message",
                    {"recipient": email, "message": text, "channel": "email"},
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("Fall email failed: %s", exc)
        self._page.update()

    def _on_message_clears_fall(self, text: str) -> None:
        """A user message with 'ok / fine / cancel' after a fall cancels it."""
        if not getattr(self, "_fall_active", False):
            return
        low = (text or "").lower()
        if any(k in low for k in ("i'm ok", "im ok", "i am ok", "cancel", "fine")):
            self._fall_cancelled = True

    # -- Phase 32: attachments -----------------------------------------------
    def _on_attach(self, e) -> None:
        """Open the file picker to attach images/documents to this message."""
        self._attachments_enabled = True
        self.file_pick.open_attach()

    def _on_files_picked(self, paths: list[str]) -> None:
        """Copy the chosen files into the uploads folder and show chips."""
        saved = []
        for raw in paths:
            try:
                dst = self._copy_into_uploads(raw)
            except OSError as exc:
                log.debug("Attachment import failed for %s: %s", raw, exc)
                continue
            if dst is not None:
                saved.append(dst)
        if not saved:
            self.chat.add_message(
                "assistant",
                "I could not import those files. Try a supported image or "
                "document format.",
            )
            self._page.update()
            return
        self.attachment_bar.add(saved)
        self._page.update()

    def _copy_into_uploads(self, raw: str) -> str | None:
        """Copy one picked/pasted file into the uploads folder (unique name)."""
        src = Path(raw)
        if not src.is_file():
            return None
        target = self.uploads_dir / src.name
        counter = 1
        while target.exists():
            target = self.uploads_dir / (
                f"{src.stem}_{counter}{src.suffix.lower()}"
            )
            counter += 1
        import shutil

        shutil.copy2(src, target)
        return str(target)

    def _on_paste_clipboard(self, e) -> None:
        """Paste an image or copied files from the clipboard into chat."""
        from utils.clipboard import paste_anything

        self._attachments_enabled = True
        try:
            saved = paste_anything(self.uploads_dir)
        except RuntimeError as exc:
            self.chat.add_message("assistant", str(exc))
            self._page.update()
            return
        if not saved:
            self.chat.add_message(
                "assistant",
                "The clipboard does not hold an image or files right now - "
                "copy one and click paste again.",
            )
            self._page.update()
            return
        self._on_files_picked([str(p) for p in saved])

    def _on_attachment_remove(self, path: str) -> None:
        """Remove one attachment chip (does not delete the saved file)."""
        self.attachment_bar.remove(path)
        self._page.update()

    def _monitor_loop(self) -> None:
        """Background loop that keeps the system panel up to date."""
        from system.monitor import collect

        while not self._monitor_stop.is_set():
            try:
                self.system.update_from(collect())
                # Phase 16: refresh the security feed too.
                summary = self.security.summary()
                self.system.security.set_summary(summary["feed"], summary["counts"])
                # Phase 28: keep the threat-status tile current.
                self.system.threats.set_status(
                    self.threat_monitor.status(),
                    len(self.threat_monitor.alerts()),
                )
            except Exception as exc:  # noqa: BLE001 - monitoring never crashes
                log.debug("Monitor update failed: %s", exc)
            self._monitor_stop.wait(2.0)

    def shutdown(self) -> None:
        """Orderly stop of every background thread/sensor before exit.

        Called when the window close button is pressed (see ui/app.py):
        the wake/mic listener, reminder poller, orb animation, monitor
        thread and speech synthesis are all torn down so none of them
        keep holding the process open mid-close.
        """
        log.info("Shutting down dashboard...")
        try:
            self.wake_listener.stop()
        except Exception as exc:  # noqa: BLE001
            log.debug("Wake listener stop failed: %s", exc)
        try:
            self.reminders.stop()
        except Exception as exc:  # noqa: BLE001
            log.debug("Reminder stop failed: %s", exc)
        try:
            self.orb.stop()
        except Exception as exc:  # noqa: BLE001
            log.debug("Orb stop failed: %s", exc)
        try:
            self._monitor_stop.set()
        except Exception as exc:  # noqa: BLE001
            log.debug("Monitor stop failed: %s", exc)
        try:
            self.threat_monitor.stop()
        except Exception as exc:  # noqa: BLE001
            log.debug("Threat monitor stop failed: %s", exc)
        try:
            if hasattr(self, "camera_monitor"):
                self.camera_monitor.stop()
        except Exception as exc:  # noqa: BLE001
            log.debug("Camera monitor stop failed: %s", exc)
        try:
            if hasattr(self, "ptt"):
                self.ptt.stop()
        except Exception as exc:  # noqa: BLE001
            log.debug("PTT stop failed: %s", exc)
        try:
            if hasattr(self, "folder_watcher"):
                self.folder_watcher.stop()
        except Exception as exc:  # noqa: BLE001
            log.debug("Folder watcher stop failed: %s", exc)
        try:
            if hasattr(self, "focus_recap"):
                self.focus_recap.stop()
        except Exception as exc:  # noqa: BLE001
            log.debug("Focus recap stop failed: %s", exc)
        try:
            self.chat.stop_caret()
        except Exception as exc:  # noqa: BLE001
            log.debug("Chat stop failed: %s", exc)
        try:
            self.tts.stop()
        except Exception as exc:  # noqa: BLE001
            log.debug("TTS stop failed: %s", exc)
