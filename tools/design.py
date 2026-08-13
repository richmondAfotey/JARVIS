"""
Design tools - local graphic design, fashion suit prototypes and UI
wireframes (Phase 23).

Everything is rendered locally with Pillow (no API keys, no internet), so
JARVIS can produce real image files for any design request:

    * create_poster    - poster / banner / social-card graphics in several
                         styles (minimal, bold, gradient, grid, neon)
    * design_suit      - fashion "suit prototype": a suit on a silhouette
                         with configurable colour, lapel, buttons and tie
    * create_wireframe - UI "suite" mockups: wireframe blueprints for a
                         mobile app or a desktop website

All images are saved under ``settings.data_dir / "designs"`` as PNG files
and the saved path is returned so the model (and the user) knows where the
design lives.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from config import settings
from tools.base import Tool, ToolError

_DESIGN_DIR = settings.data_dir / "designs"
_MAX_DIM_PX = 4096
_FILENAME_RE = re.compile(r"[A-Za-z0-9._-]+")
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/calibri.ttf",
    "C:/Windows/Fonts/impact.ttf",
]
_BASE_PALETTES = {
    "ocean": ["#0f2a47", "#00e5ff", "#e6f1ff"],
    "sunset": ["#2d1b4e", "#ff6b9d", "#ffd166"],
    "forest": ["#153717", "#7cb342", "#e8f5e9"],
    "midnight": ["#0b1220", "#9fb3d1", "#e6f1ff"],
    "crimson": ["#3b0d11", "#e63946", "#ffd166"],
}


def _filename(args: dict[str, Any], prefix: str) -> str:
    """Sanitise the optional filename argument."""
    raw = (args.get("filename") or "").strip()
    if raw and not _FILENAME_RE.fullmatch(raw):
        raise ToolError("filename may only contain letters, numbers, '.', '_', '-'.")
    if raw:
        return raw if raw.lower().endswith(".png") else f"{raw}.png"
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"


def _save(image: Any, filename: str) -> tuple[Path, float]:
    """Save an image into the designs folder; returns (path, size_kb)."""
    folder = _DESIGN_DIR
    try:
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / filename
        image.save(target, "PNG")
    except (OSError, PermissionError) as exc:
        raise ToolError(f"Could not save design: {exc}") from exc
    size_kb = 0.0
    try:
        size_kb = target.stat().st_size / 1024
    except OSError:
        pass
    return target, size_kb


def _font(size: int, bold: bool = True):
    """Load the best available system font (falling back to Pillow's default)."""
    from PIL import ImageFont

    candidates = _FONT_CANDIDATES if bold else _FONT_CANDIDATES[1:]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, Exception):  # noqa: BLE001
            continue
    return ImageFont.load_default()


def _gradient(size: tuple[int, int], top: tuple, bottom: tuple) -> Any:
    """Build a vertical gradient background using a 1px image resize."""
    from PIL import Image

    grad = Image.new("RGB", (1, 2))
    grad.putdata([tuple(top), tuple(bottom)])
    return grad.resize(size)


def _hex(value: Any, default: str = "#0f2a47") -> tuple:
    """Parse '#rrggbb' (or an RGB tuple) into an RGB triplet."""
    from PIL import ImageColor

    def _parse(spec: str) -> tuple | None:
        try:
            return tuple(ImageColor.getrgb(spec))
        except ValueError:
            return None

    if isinstance(value, (tuple, list)) and len(value) >= 3:
        try:
            return (int(value[0]), int(value[1]), int(value[2]))
        except (TypeError, ValueError):
            pass
    if isinstance(value, str) and value.strip():
        parsed = _parse(value.strip())
        if parsed:
            return parsed
        if not value.startswith("#"):
            parsed = _parse(f"#{value.strip()}")
            if parsed:
                return parsed
    parsed = _parse(default)
    return parsed or (15, 42, 71)


def _centered_text(draw, mid_x: float, y: float, text: str, font, fill) -> float:
    """Draw text horizontally centred at mid_x; returns the baseline Y."""
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    draw.text((mid_x - width / 2, y), text, font=font, fill=fill)
    return y + (bbox[3] - bbox[1])


# ---------------------------------------------------------------------------
# Poster / banner graphics
# ---------------------------------------------------------------------------


class CreatePosterTool(Tool):
    name = "create_poster"
    description = (
        "Generates a graphic-design poster, banner or social card and saves it "
        "as a PNG. Choose a style (minimal, bold, gradient, grid, neon) and "
        "palette (ocean, sunset, forest, midnight, crimson or custom hex like "
        "'#ff6b9d'). Returns the saved file path."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Main headline text."},
            "subtitle": {"type": "string", "description": "Smaller supporting text (optional)."},
            "style": {
                "type": "string",
                "description": "poster style: minimal, bold, gradient, grid, neon.",
            },
            "palette": {
                "type": "string",
                "description": "named palette or '#RRGGBB' accent colour.",
            },
            "width": {"type": "integer", "description": "Canvas width in px (default 1080)."},
            "height": {"type": "integer", "description": "Canvas height in px (default 1350)."},
            "filename": {"type": "string", "description": "Optional file name."},
        },
        "required": ["title"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        from PIL import Image, ImageDraw

        title = (self._arg(args, "title", "") or "").strip()
        subtitle = (self._arg(args, "subtitle", "") or "").strip()
        style = (self._arg(args, "style", "minimal") or "minimal").lower()
        palette_key = (self._arg(args, "palette", "ocean") or "").lower()
        width = int(self._arg(args, "width", 1080) or 1080)
        height = int(self._arg(args, "height", 1350) or 1350)
        if not title:
            raise ToolError("Provide a title to put on the poster.")
        if not (200 <= width <= _MAX_DIM_PX and 200 <= height <= _MAX_DIM_PX):
            raise ToolError("Width/height must be between 200 and 4096 px.")
        if style not in ("minimal", "bold", "gradient", "grid", "neon"):
            raise ToolError("style must be one of: minimal, bold, gradient, grid, neon.")

        if palette_key in _BASE_PALETTES:
            bg, accent, fg = (_hex(c) for c in _BASE_PALETTES[palette_key])
        else:
            bg, accent, fg = _hex(palette_key, "#0f2a47"), _hex("#00e5ff"), (230, 241, 255)

        font_size = max(28, int(height / 8))
        font = _font(font_size)
        sub_font = _font(max(18, int(height / 22)), bold=False)
        small_font = _font(max(14, int(height / 45)), bold=False)

        if style == "gradient":
            image = _gradient((width, height), bg, accent)
        else:
            image = Image.new("RGB", (width, height), tuple(bg))
        draw = ImageDraw.Draw(image)

        # Style decorations.
        if style == "bold":
            radius = int(min(width, height) * 0.45)
            draw.ellipse(
                [width - radius, -(radius // 4), width + radius, height - radius // 3],
                fill=tuple(accent),
            )
            draw.ellipse([-radius // 2, height - radius, radius, height + radius // 2],
                         fill=tuple(accent))
        elif style == "grid":
            step = max(40, min(width, height) // 12)
            for x in range(0, width, step):
                draw.line([(x, 0), (x, height)], fill=(*fg, 40), width=1)
            for y in range(0, height, step):
                draw.line([(0, y), (width, y)], fill=(*fg, 40), width=1)
        elif style == "neon":
            draw.rectangle([0, int(height * 0.72), width, int(height * 0.74) + 2],
                           fill=tuple(accent))
            draw.rectangle([0, int(height * 0.26) - 2, width, int(height * 0.26)],
                           fill=tuple(accent))
        elif style == "gradient":
            pass
        else:  # minimal
            draw.line([(width * 0.12, height * 0.5), (width * 0.88, height * 0.5)],
                      fill=tuple(accent), width=4)

# Neon glow = layered text shadow.
        text_color = tuple(fg)
        glow_color = tuple(accent)
        sx = 6
        if style == "neon":
            for dx in (-sx, sx):
                for dy in (-sx, sx):
                    _centered_text(draw, width / 2 + dx, height * 0.30 + dy,
                                   title, font, glow_color)
        y = _centered_text(draw, width / 2, height * 0.30, title, font, text_color)
        if subtitle:
            y = _centered_text(draw, width / 2, y + height * 0.03, subtitle,
                               sub_font, tuple(accent))
        _centered_text(draw, width / 2, height * 0.94,
                       f"{style.upper()}  ·  JARVIS DESIGN", small_font,
                       tuple(accent))

        target, size_kb = _save(image, _filename(args, "poster"))
        return f"Saved poster to {target} ({width}x{height}px, {size_kb:.0f} KB)."


# ---------------------------------------------------------------------------
# Fashion suit prototype
# ---------------------------------------------------------------------------


class CreateSuitPrototypeTool(Tool):
    name = "design_suit"
    description = (
        "Draws a fashion suit prototype: a suit on a front-facing silhouette "
        "with a configurable colour, lapel style (notch/peak/shawl), number of "
        "buttons, optional tie, and background. Save it as a PNG and return the "
        "path. Great for picky fashion design sketches."
    )
    parameters = {
        "type": "object",
        "properties": {
            "suit_color": {"type": "string", "description": "Suit colour, e.g. '#1a2e6c' or 'navy'."},
            "lapel": {"type": "string", "description": "Lapel style: notch, peak or shawl."},
            "buttons": {"type": "integer", "description": "Number of jacket buttons: 1, 2 or 3."},
            "tie": {"type": "string", "description": "Tie colour (e.g. '#b3001b'); omit for no tie."},
            "background": {"type": "string", "description": "Background colour hex."},
            "filename": {"type": "string", "description": "Optional file name."},
        },
        "required": [],
    }

    def _draw_figure(self, draw, size, suit_rgb, shirt_rgb, lapel_rgb, tie_rgb,
                     buttons: int, lapel_style: str):
        """Paint a stylised suit on a torso silhouette."""
        w, h = size
        cx = w / 2
        # head + neck
        draw.ellipse([cx - 60, 40, cx + 60, 190], fill=(230, 220, 200))
        draw.rectangle([cx - 18, 185, cx + 18, 235], fill=(230, 220, 200))
        # shoulders + arms
        draw.polygon([(cx - 150, 245), (cx - 70, 235), (cx + 70, 235), (cx + 150, 245),
                      (cx + 150, 300), (cx + 70, 290), (cx - 70, 290), (cx - 150, 300)],
                     fill=tuple(suit_rgb))
        # torso (jacket)
        draw.rounded_rectangle([cx - 120, 235, cx + 120, 520], radius=28,
                               fill=tuple(suit_rgb))
        # arms as rounded capsules from shoulders down
        draw.rounded_rectangle([cx - 165, 245, cx - 95, 610], radius=26, fill=tuple(suit_rgb))
        draw.rounded_rectangle([cx + 95, 245, cx + 165, 610], radius=26, fill=tuple(suit_rgb))
        # hands
        draw.ellipse([cx - 170, 600, cx - 90, 650], fill=(230, 220, 200))
        draw.ellipse([cx + 90, 600, cx + 170, 650], fill=(230, 220, 200))
        # lapels: triangle band from the neck down the chest
        if lapel_style == "shawl":
            lapel = [(cx - 26, 250), (cx - 78, 310), (cx - 60, 470), (cx - 18, 400)]
            lapel_r = [(cx + 26, 250), (cx + 78, 310), (cx + 60, 470), (cx + 18, 400)]
        else:
            lapel = [(cx - 30, 250), (cx - 88, 330), (cx - 62, 470), (cx - 6, 400)]
            lapel_r = [(cx + 30, 250), (cx + 88, 330), (cx + 62, 470), (cx + 6, 400)]
        draw.polygon(lapel, fill=tuple(lapel_rgb))
        draw.polygon(lapel_r, fill=tuple(lapel_rgb))
        # shirt V opening
        draw.polygon([(cx - 30, 250), (cx + 30, 250), (cx + 24, 430), (cx, 470), (cx - 24, 430)],
                     fill=tuple(shirt_rgb))
        # tie
        if tie_rgb:
            draw.polygon([(cx - 14, 265), (cx + 14, 265), (cx + 14, 400), (cx, 470),
                          (cx - 14, 400)], fill=tuple(tie_rgb))
        # buttons
        n = max(1, min(3, buttons or 2))
        start_y, spacing = 340, 34
        for i in range(n):
            by = start_y + i * spacing
            draw.ellipse([cx - 8, by, cx + 8, by + 16], fill=tuple(shirt_rgb))
        # pocket square
        draw.polygon([(cx + 40, 380), (cx + 72, 380), (cx + 68, 404), (cx + 40, 404)],
                     fill=tuple(shirt_rgb))

    def execute(self, args: dict[str, Any]) -> str:
        from PIL import Image, ImageDraw

        suit_color = (self._arg(args, "suit_color", "#1a2e6c") or "#1a2e6c")
        lapel_style = (self._arg(args, "lapel", "notch") or "notch").lower()
        buttons = int(self._arg(args, "buttons", 2) or 2)
        tie = (self._arg(args, "tie", "#b3001b") or "").strip()
        background = (self._arg(args, "background", "#3c4350") or "#3c4350")
        if lapel_style not in ("notch", "peak", "shawl"):
            raise ToolError("lapel must be one of: notch, peak, shawl.")

        suit_rgb = _hex(suit_color, "#1a2e6c")
        lapel_rgb = tuple(int(c * 0.82) for c in suit_rgb)  # darker lapel
        shirt_rgb = (245, 245, 250)
        tie_rgb = _hex(tie, "#b3001b") if tie else None
        bg_rgb = _hex(background, "#3c4350")

        image = _gradient((720, 960), bg_rgb, tuple(int(c * 0.72) for c in bg_rgb))
        draw = ImageDraw.Draw(image)
        self._draw_figure(draw, image.size, suit_rgb, shirt_rgb, lapel_rgb,
                          tie_rgb, buttons, lapel_style)

        draw.text((36, 24), "SUIT PROTOTYPE", font=_font(26), fill=(255, 255, 255))
        swatch_x, swatch_y = 36, 900
        draw.rounded_rectangle([swatch_x, swatch_y, swatch_x + 50, swatch_y + 50],
                               radius=8, fill=suit_rgb, outline=(255, 255, 255), width=2)
        draw.text((swatch_x + 62, swatch_y + 4),
                  f"suit {suit_color}\nlapel {lapel_style}  ·  {'tie' if tie else 'no tie'}",
                  font=_font(22, bold=False), fill=(235, 235, 245))

        target, size_kb = _save(image, _filename(args, "suit"))
        return f"Saved suit prototype to {target} (720x960px, {size_kb:.0f} KB)."


# ---------------------------------------------------------------------------
# UI wireframe (app / website "suite") mockups
# ---------------------------------------------------------------------------


class CreateWireframeTool(Tool):
    name = "create_wireframe"
    description = (
        "Builds a UI wireframe mockup (blueprint) for a mobile app or a desktop "
        "website 'suite' of screens. Draws a clean grey-box wireframe and saves "
        "it as a PNG. Use device 'mobile' or 'desktop'. Returns the file path."
    )
    parameters = {
        "type": "object",
        "properties": {
            "device": {"type": "string", "description": "'mobile' or 'desktop'."},
            "app_name": {"type": "string", "description": "App/site name used in the wireframe."},
            "screens": {"type": "integer", "description": "Number of mobile screens to mock (1-3)."},
            "filename": {"type": "string", "description": "Optional file name."},
        },
        "required": [],
    }

    def _box(self, draw, x, y, x2, y2, label="", outline=(150, 160, 180)):
        """Grey wireframe box with an optional centred label."""
        draw.rounded_rectangle([x, y, x2, y2], radius=10, outline=outline,
                               width=2, fill=(238, 240, 244))
        if label:
            bbox = draw.textbbox((0, 0), label, font=_font(16, bold=False))
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.text((x + (x2 - x) / 2 - tw / 2, y + (y2 - y) / 2 - th / 2),
                      label, font=_font(16, bold=False), fill=(120, 130, 150))

    def _mobile_frame(self, draw, x, y, size, label):
        """One phone-sized wireframe screen."""
        w, h = size
        # status bar
        draw.rectangle([x + 34, y + 12, x + w - 34, y + 22], fill=(150, 160, 180))
        # header
        self._box(draw, x + 34, y + 36, x + w - 34, y + 72, f"{label} header")
        # body: content blocks
        self._box(draw, x + 34, y + 84, x + w - 34, y + 120, "search")
        for i in range(3):
            cy = y + 132 + i * 44
            self._box(draw, x + 34, cy, x + w - 34, cy + 34, f"card {i + 1}")
        # bottom nav
        nav_y = y + h - 58
        for i in range(4):
            nx = x + 40 + i * ((w - 80) // 4)
            draw.rounded_rectangle([nx, nav_y, nx + (w - 80) // 4 - 8, nav_y + 40],
                                   radius=6, outline=(150, 160, 180), width=2)
        # phone outline
        draw.rounded_rectangle([x, y, x + w, y + h], radius=28,
                               outline=(70, 80, 100), width=4)

    def _desktop_frame(self, draw, x, y, size, label):
        """One desktop-sized wireframe browser window + landing page."""
        w, h = size
        # window chrome
        draw.rounded_rectangle([x, y, x + w, y + h], radius=12,
                               outline=(70, 80, 100), width=4)
        draw.rectangle([x + 8, y + 8, x + w - 8, y + 34], fill=(150, 160, 180))
        # top nav
        self._box(draw, x + 20, y + 50, x + w - 20, y + 82, f"{label} nav")
        # hero
        self._box(draw, x + 20, y + 94, x + int(w * 0.7), y + h - 90, "hero")
        # cards
        cw = int((w - 80 - int(w * 0.7)) / 2)
        for i in range(2):
            self._box(draw, x + int(w * 0.7) + 30, y + 94 + i * 90,
                      x + int(w * 0.7) + 30 + cw, y + 94 + i * 90 + 64,
                      f"block {i + 1}")
        # footer
        self._box(draw, x + 20, y + h - 60, x + w - 20, y + h - 20, "footer")

    def execute(self, args: dict[str, Any]) -> str:
        from PIL import Image, ImageDraw

        device = (self._arg(args, "device", "mobile") or "mobile").lower()
        app_name = (self._arg(args, "app_name", "JARVIS") or "").strip() or "JARVIS"
        screens = int(self._arg(args, "screens", 1) or 1)
        if device not in ("mobile", "desktop"):
            raise ToolError("device must be 'mobile' or 'desktop'.")
        screens = max(1, min(screens, 3) if device == "mobile" else 1)

        title_font = _font(30)
        if device == "mobile":
            width = 400 * screens + 80 * (screens - 1) + 80
            height = 880
        else:
            width, height = 1280, 760

        image = Image.new("RGB", (width, height), (250, 251, 253))
        draw = ImageDraw.Draw(image)
        draw.text((40, 30), f"{app_name.upper()}  —  WIREFRAME  ({device.upper()})",
                  font=title_font, fill=(40, 50, 70))

        if device == "mobile":
            for i in range(screens):
                x = 80 + i * 480
                self._mobile_frame(draw, x, 130, (360, 700), f"{app_name} {i + 1}")
        else:
            self._desktop_frame(draw, 40, 120, (1200, 600), app_name)

        target, size_kb = _save(image, _filename(args, "wireframe"))
        return f"Saved wireframe to {target} ({width}x{height}px, {size_kb:.0f} KB)."


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_design_tools(registry) -> None:
    """Register the Phase 23 graphic-design tools on a registry."""
    registry.register(CreatePosterTool())
    registry.register(CreateSuitPrototypeTool())
    registry.register(CreateWireframeTool())