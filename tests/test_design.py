"""Tests for the Phase 23 graphic-design tools (local Pillow rendering)."""

from PIL import Image
from tools import build_default_registry
from tools.base import ToolError
from tools.design import (
    _DESIGN_DIR,
    _hex,
    CreatePosterTool,
    CreateSuitPrototypeTool,
    CreateWireframeTool,
)


def _read_image(path, tmp_path) -> Image.Image:
    return Image.open(tmp_path / path).convert("RGB")


# -- _hex colour parsing -----------------------------------------------------

def test_hex_parses_forms():
    assert _hex("#ff0000") == (255, 0, 0)
    assert _hex("ff0000") == (255, 0, 0)
    assert _hex((10, 20, 30)) == (10, 20, 30)
    assert _hex(None, "#00ff00") == (0, 255, 0)
    assert _hex("not-a-colour", "#010203") == (1, 2, 3)


# -- create_poster -----------------------------------------------------------

def test_poster_renders_each_style(monkeypatch, tmp_path):
    monkeypatch.setattr("tools.design._DESIGN_DIR", tmp_path)
    tool = CreatePosterTool()
    for style in ("minimal", "bold", "gradient", "grid", "neon"):
        out = tool.execute(
            {"title": "Hello", "subtitle": "World", "style": style,
             "filename": f"poster_{style}.png"}
        )
        assert f"Saved poster" in out
        img = _read_image(f"poster_{style}.png", tmp_path)
        assert img.size == (1080, 1350)


def test_poster_custom_size_and_palette(monkeypatch, tmp_path):
    monkeypatch.setattr("tools.design._DESIGN_DIR", tmp_path)
    out = CreatePosterTool().execute(
        {"title": "Ads", "width": 800, "height": 600,
         "palette": "#ff6b9d", "filename": "custom.png"}
    )
    assert "800x600px" in out
    assert _read_image("custom.png", tmp_path).size == (800, 600)


def test_poster_needs_title(tmp_path):
    try:
        CreatePosterTool().execute({"filename": "x.png"})
    except ToolError as exc:
        assert "title" in str(exc).lower()
        return
    raise AssertionError("Expected ToolError for missing title")


def test_poster_rejects_bad_style(monkeypatch, tmp_path):
    try:
        CreatePosterTool().execute({"title": "X", "style": "warp"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError for unknown style")


def test_poster_rejects_huge_canvas(monkeypatch, tmp_path):
    try:
        CreatePosterTool().execute({"title": "X", "width": 50000, "height": 50000})
    except ToolError:
        return
    raise AssertionError("Expected ToolError for oversized canvas")


# -- design_suit -------------------------------------------------------------

def test_suit_renders_variants(monkeypatch, tmp_path):
    monkeypatch.setattr("tools.design._DESIGN_DIR", tmp_path)
    tool = CreateSuitPrototypeTool()
    out = tool.execute({"suit_color": "#1a2e6c", "lapel": "peak", "buttons": 3,
                        "tie": "#b3001b", "filename": "suit.png"})
    assert "Saved suit prototype" in out
    img = _read_image("suit.png", tmp_path)
    assert img.size == (720, 960)


def test_suit_shawl_no_tie(monkeypatch, tmp_path):
    monkeypatch.setattr("tools.design._DESIGN_DIR", tmp_path)
    out = CreateSuitPrototypeTool().execute(
        {"suit_color": "darkgray", "lapel": "shawl", "buttons": 1,
         "tie": "", "background": "#111111", "filename": "suit2.png"}
    )
    assert "720x960px" in out
    assert _read_image("suit2.png", tmp_path).size == (720, 960)


def test_suit_defaults_no_args(monkeypatch, tmp_path):
    monkeypatch.setattr("tools.design._DESIGN_DIR", tmp_path)
    out = CreateSuitPrototypeTool().execute({})
    assert "Saved suit prototype" in out


def test_suit_rejects_bad_lapel(tmp_path):
    try:
        CreateSuitPrototypeTool().execute({"lapel": "zigzag"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError for unknown lapel")


# -- create_wireframe --------------------------------------------------------

def test_wireframe_mobile(monkeypatch, tmp_path):
    monkeypatch.setattr("tools.design._DESIGN_DIR", tmp_path)
    out = CreateWireframeTool().execute(
        {"device": "mobile", "app_name": "FashionApp", "screens": 2,
         "filename": "mobile.png"}
    )
    assert "Saved wireframe" in out
    img = _read_image("mobile.png", tmp_path)
    assert img.size[0] == 960  # 2 screens


def test_wireframe_desktop(monkeypatch, tmp_path):
    monkeypatch.setattr("tools.design._DESIGN_DIR", tmp_path)
    out = CreateWireframeTool().execute(
        {"device": "desktop", "app_name": "Store", "filename": "desktop.png"}
    )
    assert "1280x760px" in out
    assert _read_image("desktop.png", tmp_path).size == (1280, 760)


def test_wireframe_defaults_mobile(monkeypatch, tmp_path):
    monkeypatch.setattr("tools.design._DESIGN_DIR", tmp_path)
    out = CreateWireframeTool().execute({})
    assert "Saved wireframe" in out


def test_wireframe_rejects_bad_device(tmp_path):
    try:
        CreateWireframeTool().execute({"device": "watch"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError for unknown device")


# -- filename safety ---------------------------------------------------------

def test_invalid_filename_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr("tools.design._DESIGN_DIR", tmp_path)
    try:
        CreatePosterTool().execute({"title": "X", "filename": "bad/name!?.png"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError for unsafe filename")


# -- registry integration ----------------------------------------------------

def test_registry_has_design_tools():
    registry = build_default_registry()
    for name in ("create_poster", "design_suit", "create_wireframe"):
        assert registry.get(name) is not None
        assert name in registry.names()