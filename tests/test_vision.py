"""Tests for the Phase 13 screenshot + vision tools (network mocked)."""

from io import BytesIO

import requests

from PIL import Image
from tools import build_default_registry
from tools.base import ToolError
from tools.vision import AnalyzeImageTool, TakeScreenshotTool, _encode_image, _parse_region


def _open_image() -> Image.Image:
    return Image.new("RGB", (300, 200), "navy")


def _png_bytes() -> bytes:
    buffer = BytesIO()
    _open_image().save(buffer, format="PNG")
    return buffer.getvalue()


# -- _parse_region ----------------------------------------------------------

def test_parse_region_forms():
    assert _parse_region("0,0,800,600") == (0, 0, 800, 600)
    assert _parse_region([0, 0, 800, 600]) == (0, 0, 800, 600)
    assert _parse_region((10, 20, 100, 50)) == (10, 20, 110, 70)
    assert _parse_region("") is None
    assert _parse_region(None) is None
    assert _parse_region("     10, 20 , 30,   40") == (10, 20, 40, 60)


def test_parse_region_invalid():
    for bad in ("0,0,800", "0,0,-5,600", "abc", ["a", "b"], "0, 0, 0, 100"):
        try:
            _parse_region(bad)
        except ToolError:
            continue
        raise AssertionError(f"Expected ToolError for {bad!r}")


# -- take_screenshot --------------------------------------------------------

def test_take_screenshot_full(monkeypatch, tmp_path):
    monkeypatch.setattr("PIL.ImageGrab.grab", lambda **kw: _open_image())
    monkeypatch.setattr("tools.vision._SCREENSHOT_DIR", tmp_path)
    out = TakeScreenshotTool().execute({})
    assert "Saved screenshot" in out
    assert "300x200" in out
    files = list(tmp_path.glob("screenshot_*.png"))
    assert len(files) == 1


def test_take_screenshot_region(monkeypatch, tmp_path):
    grabbed = {}

    def fake_grab(**kw):
        grabbed.update(kw)
        return _open_image()

    monkeypatch.setattr("PIL.ImageGrab.grab", fake_grab)
    monkeypatch.setattr("tools.vision._SCREENSHOT_DIR", tmp_path)
    TakeScreenshotTool().execute({"region": "0,0,100,50", "filename": "area.png"})
    assert grabbed["bbox"] == (0, 0, 100, 50)
    assert (tmp_path / "area.png").exists()


def test_take_screenshot_filename_extension(monkeypatch, tmp_path):
    monkeypatch.setattr("PIL.ImageGrab.grab", lambda **kw: _open_image())
    monkeypatch.setattr("tools.vision._SCREENSHOT_DIR", tmp_path)
    TakeScreenshotTool().execute({"filename": "shot"})
    assert (tmp_path / "shot.png").exists()


def test_take_screenshot_bad_filename(monkeypatch, tmp_path):
    monkeypatch.setattr("tools.vision._SCREENSHOT_DIR", tmp_path)
    try:
        TakeScreenshotTool().execute({"filename": "my file!.png"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


def test_take_screenshot_grab_failure(monkeypatch, tmp_path):
    def fake_grab(**kw):
        raise PermissionError("no screen access")

    monkeypatch.setattr("PIL.ImageGrab.grab", fake_grab)
    monkeypatch.setattr("tools.vision._SCREENSHOT_DIR", tmp_path)
    try:
        TakeScreenshotTool().execute({})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


# -- analyze_image ----------------------------------------------------------

def test_encode_image_returns_jpeg(tmp_path):
    target = tmp_path / "img.png"
    target.write_bytes(_png_bytes())
    mime, data = _encode_image(target)
    assert mime == "image/jpeg"
    assert data


def test_analyze_image_success(monkeypatch, tmp_path):
    target = tmp_path / "img.png"
    target.write_bytes(_png_bytes())
    captured = {}

    class FakeResponse:
        def __init__(self, body):
            self.content = b"{}"
            self.body = body
            self.status_code = 200

        def json(self):
            return self.body

    def fake_post(url, params=None, json=None, timeout=None):
        captured.update(url=url, params=params, payload=json)
        return FakeResponse(
            {"candidates": [{"content": {"parts": [{"text": "It is a blue square."}]}}]}
        )

    monkeypatch.setattr("tools.vision.requests.post", fake_post)
    monkeypatch.setattr("tools.vision.settings.google_api_key", "test-key")
    out = AnalyzeImageTool().execute({"path": str(target), "question": "What is this?"})
    assert "blue square" in out
    assert "gemini" in captured["url"]
    assert captured["params"]["key"] == "test-key"
    assert captured["payload"]["contents"][0]["parts"][1]["text"] == "What is this?"


def test_analyze_image_missing_key(monkeypatch, tmp_path):
    monkeypatch.setattr("tools.vision.settings.google_api_key", "")
    target = tmp_path / "img.png"
    target.write_bytes(_png_bytes())
    try:
        AnalyzeImageTool().execute({"path": str(target)})
    except ToolError as exc:
        assert "GOOGLE_API_KEY" in str(exc)
        return
    raise AssertionError("Expected ToolError")


def test_analyze_image_missing_file(tmp_path):
    try:
        AnalyzeImageTool().execute({"path": str(tmp_path / "nope.png")})
    except ToolError as exc:
        assert "Image not found" in str(exc)
        return
    raise AssertionError("Expected ToolError")


def test_analyze_image_unsupported_type(tmp_path):
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"%PDF")
    try:
        AnalyzeImageTool().execute({"path": str(target)})
    except ToolError as exc:
        assert "Unsupported image file" in str(exc)
        return
    raise AssertionError("Expected ToolError")


def test_analyze_image_http_error(monkeypatch, tmp_path):
    target = tmp_path / "img.png"
    target.write_bytes(_png_bytes())

    class FakeErrorResponse:
        status_code = 400
        content = b"{}"

        def json(self):
            return {"error": {"message": "API key invalid"}}

    def fake_post(url, params=None, json=None, timeout=None):
        return FakeErrorResponse()

    monkeypatch.setattr("tools.vision.requests.post", fake_post)
    monkeypatch.setattr("tools.vision.settings.google_api_key", "bad")
    try:
        AnalyzeImageTool().execute({"path": str(target)})
    except ToolError as exc:
        assert "API key invalid" in str(exc)
        return
    raise AssertionError("Expected ToolError")


def test_analyze_image_network_error(monkeypatch, tmp_path):
    target = tmp_path / "img.png"
    target.write_bytes(_png_bytes())

    def fake_post(url, params=None, json=None, timeout=None):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr("tools.vision.requests.post", fake_post)
    monkeypatch.setattr("tools.vision.settings.google_api_key", "test-key")
    try:
        AnalyzeImageTool().execute({"path": str(target)})
    except ToolError as exc:
        assert "Vision request failed" in str(exc)
        return
    raise AssertionError("Expected ToolError")


def test_analyze_image_blocked(monkeypatch, tmp_path):
    target = tmp_path / "img.png"
    target.write_bytes(_png_bytes())

    class FakeResponse:
        status_code = 200
        content = b"{}"

        def json(self):
            return {"promptFeedback": {"blockReason": "SAFETY"}}

    def fake_post(url, params=None, json=None, timeout=None):
        return FakeResponse()

    monkeypatch.setattr("tools.vision.requests.post", fake_post)
    monkeypatch.setattr("tools.vision.settings.google_api_key", "test-key")
    try:
        AnalyzeImageTool().execute({"path": str(target)})
    except ToolError as exc:
        assert "refused" in str(exc)
        return
    raise AssertionError("Expected ToolError")


# -- registry integration --------------------------------------------------

def test_registry_has_vision_tools():
    registry = build_default_registry()
    assert registry.get("take_screenshot") is not None
    assert registry.get("analyze_image") is not None