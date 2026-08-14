"""
Capabilities pack (Phase 35) - everyday power tools that need no new
dependencies:

    * screen_ocr        - capture the screen (or a region) and extract the
                          text on it via the Gemini vision model
    * screen_time       - track which apps are in the foreground and report
                          how long each has been used (best-effort, local)
    * media_control     - play/pause/next/previous/volume media keys for the
                          active music or video app (Windows)
    * export_pdf        - render a text report into a real PDF file (pure
                          Python, no external libraries)

Screen OCR uses the existing screenshot + Gemini vision pipeline, so it
needs GOOGLE_API_KEY like the other vision tools. Everything else is fully
local.
"""

from __future__ import annotations

import ctypes
import os
import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from config import settings
from tools.base import Tool, ToolError

_PDF_PAGE_WIDTH = 612
_PDF_PAGE_HEIGHT = 792
_PDF_MARGIN = 50
_PDF_BODY_SIZE = 11
_PDF_LINE_HEIGHT = 15
_PDF_CHARS_PER_LINE = 92
_PDF_LINES_PER_PAGE = 45

#: Windows virtual-key codes for media control.
MEDIA_KEYS = {
    "play": 0xB3,        # VK_MEDIA_PLAY_PAUSE
    "pause": 0xB3,
    "play_pause": 0xB3,
    "next": 0xB0,        # VK_MEDIA_NEXT_TRACK
    "previous": 0xB1,    # VK_MEDIA_PREV_TRACK
    "stop": 0xB2,        # VK_MEDIA_STOP
    "volume_up": 0xAF,   # VK_VOLUME_UP
    "volume_down": 0xAE, # VK_VOLUME_DOWN
    "mute": 0xAD,        # VK_VOLUME_MUTE
    "unmute": 0xAD,
}

_KEYEVENTF_KEYUP = 0x0002


# -- screen_ocr ------------------------------------------------------------

class ScreenOcrTool(Tool):
    name = "screen_ocr"
    description = (
        "Reads text that is currently on the screen (or a screen region) and "
        "returns it as text. Uses a screenshot + the Gemini vision model, so "
        "GOOGLE_API_KEY must be set. Examples: region='0,0,800,600' to read "
        "just part of the screen."
    )
    parameters = {
        "type": "object",
        "properties": {
            "region": {
                "type": "string",
                "description": "Optional 'x,y,width,height' of the area to read.",
            },
            "question": {
                "type": "string",
                "description": "Optional instruction, defaults to 'extract all text verbatim'.",
            },
        },
    }

    _GEMINI_URL = (
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    )

    def execute(self, args: dict[str, Any]) -> str:
        from tools.vision import _encode_image, _parse_region

        key = settings.google_api_key
        if not key:
            raise ToolError(
                "Screen OCR needs GOOGLE_API_KEY (Gemini vision). Add it to .env and restart."
            )
        region = _parse_region(self._arg(args, "region", None))
        question = (
            self._arg(args, "question", "") or "Extract all visible text verbatim."
        )
        try:
            from PIL import Image, ImageGrab

            folder = settings.data_dir / "screenshots"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"ocr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            image = ImageGrab.grab(bbox=region, all_screens=True)
            image.save(target, "PNG")
        except Exception as exc:  # screen capture failures surface cleanly
            raise ToolError(f"Screen capture failed: {exc}") from exc

        mime_type, data = _encode_image(target)
        model = settings.google_model or "gemini-flash-latest"
        payload = {
            "contents": [
                {"parts": [
                    {"inline_data": {"mime_type": mime_type, "data": data}},
                    {"text": question},
                ]}
            ]
        }
        try:
            response = requests.post(
                self._GEMINI_URL.format(model=model),
                params={"key": key},
                json=payload,
                timeout=30,
            )
            body = response.json() if response.content else {}
            if response.status_code != 200:
                raise ToolError(f"Vision request failed: {body}")
        except requests.RequestException as exc:
            raise ToolError(f"Screen OCR failed: {exc}") from exc

        texts: list[str] = []
        for candidate in body.get("candidates") or []:
            for part in candidate.get("content", {}).get("parts") or []:
                if part.get("text"):
                    texts.append(part["text"])
        if texts:
            return "\n".join(texts).strip()
        raise ToolError("The vision model returned no text for this screen.")


# -- screen_time -----------------------------------------------------------

#: Rolling records of (unix_ts, app_name) kept in memory.
_SCREEN_SAMPLES: deque[tuple[float, str]] = deque(maxlen=6000)
_SAMPLE_LOCK = threading.Lock()
_SAMPLER_ENABLED = True
_SAMPLER_INTERVAL = 5.0
_sampler_thread: threading.Thread | None = None


def _foreground_app() -> str:
    """Best-effort name of the focused app (Windows only)."""
    if os.name != "nt":
        return ""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        import psutil

        proc = psutil.Process(pid.value)
        names = [proc.name()]
        try:
            parent = proc.parent()
            if parent is not None:
                names.append(parent.name())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return "\\".join(sorted(set(names)))
    except Exception:
        return ""


def record_sample() -> None:
    """Append one (time, app) observation. Safe to call from any thread."""
    app = _foreground_app()
    if not app:
        return
    with _SAMPLE_LOCK:
        _SCREEN_SAMPLES.append((time.time(), app))


def _sampler_loop() -> None:
    while _SAMPLER_ENABLED:
        try:
            record_sample()
        except Exception:
            pass
        time.sleep(_SAMPLER_INTERVAL)


def _ensure_sampler() -> None:
    global _sampler_thread
    if _sampler_thread is None and _SAMPLER_ENABLED:
        _sampler_thread = threading.Thread(target=_sampler_loop, daemon=True)
        _sampler_thread.start()


def summarize_screen_time(window_minutes: float = 60.0) -> str:
    """Aggregate recorded foreground-app samples over a time window."""
    cutoff = time.time() - window_minutes * 60
    counts: dict[str, float] = {}
    with _SAMPLE_LOCK:
        samples = [(t, a) for t, a in _SCREEN_SAMPLES if t >= cutoff]
    if not samples:
        return f"No screen-time data yet for the last {window_minutes:.0f} minutes."
    for _, app in samples:
        counts[app] = counts.get(app, 0) + 1
    total = len(samples) * _SAMPLER_INTERVAL / 60.0
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    minutes = total / 60.0
    lines = [
        f"Screen time tracker (sampled every {_SAMPLER_INTERVAL:.0f}s):",
        f"~{minutes:.1f} hours tracked over the window, top apps:",
    ]
    for app, count in ranked[:8]:
        share_pct = count / len(samples) * 100
        lines.append(f"- {app}: {share_pct:.1f}% of the window")
    return "\n".join(lines)


class ScreenTimeTool(Tool):
    name = "screen_time"
    description = (
        "Reports which applications have been in the foreground recently and "
        "the share of time each was used. Uses a small local background "
        "sampler; nothing is sent anywhere."
    )
    parameters = {
        "type": "object",
        "properties": {
            "window_minutes": {
                "type": "number",
                "description": "Minutes to look back over (default 60).",
            }
        },
    }

    def execute(self, args: dict[str, Any]) -> str:
        _ensure_sampler()
        window = max(1.0, float(self._arg(args, "window_minutes", 60)))
        return summarize_screen_time(window)


# -- media_control ---------------------------------------------------------

class MediaControlTool(Tool):
    name = "media_control"
    description = (
        "Controls the media playing on this computer (Windows): actions are "
        "'play', 'pause', 'next', 'previous', 'stop', 'volume_up', "
        "'volume_down', 'mute'. Presses the standard media keys, so it works "
        "with whatever music/video app is playing. Requires your approval."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "One of: play, pause, next, previous, stop, volume_up, "
                    "volume_down, mute."
                ),
            }
        },
        "required": ["action"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        action = (self._arg(args, "action", "") or "").strip().lower()
        if action not in MEDIA_KEYS:
            raise ToolError(
                f"Unknown action {action!r}. Use one of: "
                + ", ".join(sorted(set(MEDIA_KEYS)))
            )
        if os.name != "nt":
            raise ToolError("Media keys are only supported on Windows.")
        _send_media_key(MEDIA_KEYS[action])
        return f"Sent media key: {action}."


def _send_media_key(vk_code: int) -> None:
    """Press and release a media virtual key (Windows)."""
    user32 = ctypes.windll.user32
    user32.keybd_event(vk_code, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(vk_code, 0, _KEYEVENTF_KEYUP, 0)


# -- export_pdf ------------------------------------------------------------

def _pdf_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _wrap_text(content: str) -> list[str]:
    """Break a block of text into PDF lines of a safe width."""
    lines: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip() or " "
        while len(line) > _PDF_CHARS_PER_LINE:
            split_at = line.rfind(" ", 0, _PDF_CHARS_PER_LINE)
            if split_at < _PDF_CHARS_PER_LINE // 2:
                split_at = _PDF_CHARS_PER_LINE
            lines.append(line[:split_at].rstrip())
            line = line[split_at:].lstrip()
        lines.append(line)
    return lines


def _paged_lines(body_lines: list[str], title: str) -> list[list[str]]:
    """Group body lines into pages, leaving room for the title on page 1."""
    title_room = 2 if title else 0
    pages: list[list[str]] = []
    page: list[str] = []
    available = _PDF_LINES_PER_PAGE - title_room
    for line in body_lines:
        if len(page) >= available:
            pages.append(page)
            page = []
            available = _PDF_LINES_PER_PAGE
        page.append(line)
    if page or not pages:
        pages.append(page)
    return pages


def build_pdf_bytes(title: str, content: str) -> bytes:
    """Render title + body text into a minimal, dependency-free PDF file."""
    title = (title or "JARVIS report").strip()
    body_lines = _wrap_text(content or "")
    pages = _paged_lines(body_lines, title)

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    # The font is added after pages are known; we build text streams first
    # and the page objects with a placeholder index fixed below.
    streams: list[bytes] = []
    for page_lines in pages:
        stream_lines = ["BT", "/F1 %d Tf %d %d Td" % (_PDF_BODY_SIZE, _PDF_MARGIN, _PDF_PAGE_HEIGHT - _PDF_MARGIN)]
        if title:
            stream_lines.append("/F2 16 Tf 0 -2 Td")
            stream_lines.append(f"({title}) Tj")
            stream_lines.append("/F1 %d Tf 0 -%d Td" % (_PDF_BODY_SIZE, _PDF_LINE_HEIGHT))
        for text_line in page_lines:
            stream_lines.append(f"({_pdf_escape(text_line)}) Tj")
            stream_lines.append(f"0 -{_PDF_LINE_HEIGHT} Td")
        stream_lines.append("0 0 Td")
        stream_lines.append("ET")
        stream_data = "\n".join(stream_lines).encode("latin-1", "replace")
        streams.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream_data), stream_data))

    # Fixed indexes: page objects and content streams interleave.
    page_count = len(pages)
    font_f1 = 3 + page_count * 2
    font_f2 = font_f1 + 1
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(page_count))

    objects.append(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids.encode(), page_count))
    for i in range(page_count):
        page_obj = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PDF_PAGE_WIDTH} {_PDF_PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 {font_f1} 0 R /F2 {font_f2} 0 R >> >> "
            f"/Contents {4 + i * 2} 0 R >>"
        ).encode()
        objects.append(page_obj)
        objects.append(streams[i])
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    return _assemble_pdf(objects)


def _assemble_pdf(objects: list[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{index} 0 obj\n".encode())
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode())
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return bytes(out)


class ExportPdfTool(Tool):
    name = "export_pdf"
    description = (
        "Renders text into a formatted PDF file and saves it under "
        "data/exports/. Args: title (short heading) and content (the report "
        "body). Returns the saved path. Requires your approval."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "The report title."},
            "content": {"type": "string", "description": "The report body text."},
        },
        "required": ["title", "content"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        title = (self._arg(args, "title", "") or "JARVIS report").strip()
        content = (self._arg(args, "content", "") or "").strip()
        if not content:
            raise ToolError("Provide some content to export.")
        if len(content) > 200_000:
            raise ToolError("Content is too large to export as a PDF.")

        folder = settings.data_dir / "exports"
        folder.mkdir(parents=True, exist_ok=True)
        safe_title = re.sub(r"[^A-Za-z0-9 _-]", "", title)[:40].strip() or "JARVIS_report"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = folder / f"{safe_title.replace(' ', '_')}_{stamp}.pdf"
        try:
            target.write_bytes(build_pdf_bytes(title, content))
        except OSError as exc:
            raise ToolError(f"Could not write PDF: {exc}") from exc
        return f"Saved PDF report to {target} ({target.stat().st_size // 1024} KB)."


# -- Registration ----------------------------------------------------------

def register_capability_tools(registry) -> None:
    """Register the Phase 35 capability tools on a registry."""
    registry.register(ScreenOcrTool())
    registry.register(ScreenTimeTool())
    registry.register(MediaControlTool())
    registry.register(ExportPdfTool())