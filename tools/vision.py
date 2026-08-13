"""
Screenshot and vision tools (Phase 13).

* `take_screenshot` - capture the screen (or a region) and save it as a PNG
* `analyze_image`   - ask the vision model (Google Gemini) a question about
                      an image file, returning its answer as text

Workflow: JARVIS takes a screenshot (visible tool, path shown in chat),
then calls `analyze_image` on the saved file to see it. Screenshots are
stored under `data/screenshots/`.

Safety:
    * Captures happen only when the tool is called - there is no
      background or hidden capture.
    * Image payloads are downscaled before being sent to the API, so a
      full-screen grab stays small and fast.
"""

from __future__ import annotations

import base64
import io
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from config import settings
from tools.base import Tool, ToolError

_SCREENSHOT_DIR = settings.data_dir / "screenshots"
_MAX_DIM_PX = 1280
_JPEG_QUALITY = 85
_TIMEOUT = 30
_IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


def _parse_region(region: Any) -> tuple[int, int, int, int] | None:
    """'x,y,width,height' (string or [x, y, w, h]) -> a grab bbox."""
    if region in (None, ""):
        return None
    if isinstance(region, (list, tuple)):
        values = list(region)
    elif isinstance(region, str):
        values = [p for p in re.split(r"[,\s]+", region.strip()) if p]
    else:
        raise ToolError("region must be 'x,y,width,height' or [x, y, width, height].")
    if len(values) != 4:
        raise ToolError("region needs exactly 4 numbers: x, y, width, height.")
    try:
        x, y, width, height = (int(v) for v in values)
    except (TypeError, ValueError):
        raise ToolError(f"Invalid region {region!r}. Use numbers like '0,0,800,600'.")
    if width <= 0 or height <= 0:
        raise ToolError("region width and height must be positive.")
    return (x, y, x + width, y + height)


class TakeScreenshotTool(Tool):
    name = "take_screenshot"
    description = (
        "Captures the screen and saves it as a PNG file. Use region like "
        "'0,0,800,600' to capture just part of the screen. Returns the saved path."
    )
    parameters = {
        "type": "object",
        "properties": {
            "region": {
                "type": "string",
                "description": "Optional 'x,y,width,height' of the area to capture.",
            },
            "filename": {
                "type": "string",
                "description": "Optional filename (letters, numbers, . _ -).",
            },
        },
    }

    def execute(self, args: dict[str, Any]) -> str:
        from PIL import Image, ImageGrab

        region = _parse_region(self._arg(args, "region", None))
        filename = (self._arg(args, "filename", "") or "").strip()

        if filename:
            if not re.fullmatch(r"[A-Za-z0-9._-]+", filename):
                raise ToolError("filename may only contain letters, numbers, '.', '_', '-'.")
            if not filename.lower().endswith(".png"):
                filename += ".png"

        folder = _SCREENSHOT_DIR
        try:
            folder.mkdir(parents=True, exist_ok=True)
            target = (
                folder / filename
                if filename
                else folder / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            )
            image = ImageGrab.grab(bbox=region, all_screens=True)
            image.save(target, "PNG")
        except (OSError, PermissionError) as exc:
            raise ToolError(f"Could not save screenshot: {exc}") from exc
        except Exception as exc:  # screen capture can fail for many reasons
            raise ToolError(f"Screenshot failed: {exc}") from exc

        try:
            size_kb = target.stat().st_size / 1024
        except OSError:
            size_kb = 0.0
        return (
            f"Saved screenshot to {target} "
            f"({image.width}x{image.height}px, {size_kb:.0f} KB)."
        )


def _encode_image(path: Path) -> tuple[str, str]:
    """Downscale and base64-encode an image for the vision API."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as raw:
            image = raw.convert("RGB")
            image.thumbnail((_MAX_DIM_PX, _MAX_DIM_PX))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=_JPEG_QUALITY)
    except (OSError, PermissionError, ValueError, UnidentifiedImageError) as exc:
        raise ToolError(f"Could not read image {path}: {exc}") from exc
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    return "image/jpeg", data


class AnalyzeImageTool(Tool):
    name = "analyze_image"
    description = (
        "Sends an image file to the vision model and asks it a question about "
        "what it shows. Use with a path from take_screenshot. Returns the "
        "model's answer as text."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the image file."},
            "question": {
                "type": "string",
                "description": "The question about the image.",
            },
        },
        "required": ["path"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        path = Path(str(self._arg(args, "path", "") or ""))
        question = (self._arg(args, "question", "") or "").strip()
        question = question or "Describe this image in detail."

        key = settings.google_api_key
        if not key:
            raise ToolError(
                "Vision is not configured: add GOOGLE_API_KEY to .env and restart "
                "(Gemini supports images)."
            )
        if not path.exists():
            raise ToolError(f"Image not found: {path}")
        if path.is_dir() or path.suffix.lower() not in _IMAGE_TYPES:
            raise ToolError(
                f"Unsupported image file. Supported types: {', '.join(_IMAGE_TYPES)}."
            )

        mime_type, data = _encode_image(path)
        model = settings.google_model or "gemini-flash-latest"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"inline_data": {"mime_type": mime_type, "data": data}},
                        {"text": question},
                    ]
                }
            ]
        }

        try:
            response = requests.post(
                _GEMINI_URL.format(model=model),
                params={"key": key},
                json=payload,
                timeout=_TIMEOUT,
            )
            body = response.json() if response.content else {}
            if response.status_code != 200:
                raise ToolError(self._error_message(body, response.status_code))
        except requests.RequestException as exc:
            raise ToolError(f"Vision request failed: {exc}") from exc

        text = self._extract_text(body)
        if text:
            return text

        block = (
            body.get("promptFeedback", {}).get("blockReason")
            or body.get("promptFeedback", {}).get("blockReasonMessage")
        )
        if block:
            raise ToolError(f"The vision model refused the request: {block}")
        raise ToolError("The vision model returned no response.")

    @staticmethod
    def _error_message(body: dict, status: int) -> str:
        error = body.get("error", {})
        message = error.get("message") or error.get("status") or "unknown error"
        return f"Vision request failed ({status}): {message}"

    @staticmethod
    def _extract_text(body: dict) -> str:
        texts: list[str] = []
        for candidate in body.get("candidates") or []:
            for part in candidate.get("content", {}).get("parts") or []:
                if part.get("text"):
                    texts.append(part["text"])
        return "\n".join(texts)


def register_vision_tools(registry) -> None:
    """Register the Phase 13 screenshot + vision tools on a registry."""
    registry.register(TakeScreenshotTool())
    registry.register(AnalyzeImageTool())