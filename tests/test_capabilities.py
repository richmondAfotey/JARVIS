"""Tests for the Phase 35 capabilities pack (screen OCR, screen time,
media control, PDF export)."""

from pathlib import Path

import pytest

from config import settings
from system.security import is_sensitive
from tools import build_default_registry
from tools.base import ToolError
from tools.capabilities import (
    MEDIA_KEYS,
    ExportPdfTool,
    MediaControlTool,
    ScreenOcrTool,
    ScreenTimeTool,
    build_pdf_bytes,
    record_sample,
    summarize_screen_time,
)
from tools.capabilities import _SCREEN_SAMPLES, _foreground_app


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text
        self.content = b"{}"

    def json(self):
        return {
            "candidates": [
                {"content": {"parts": [{"text": "HELLO FROM THE SCREEN"}]}}
            ]
        }


# -- screen_ocr ------------------------------------------------------------

def test_screen_ocr_extracts_text(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "google_api_key", "test-key")
    grabbed = []

    class FakeImage:
        width, height = 800, 600

        def save(self, path, fmt=None):
            Path(path).write_bytes(b"png")

    def fake_grab(bbox=None, all_screens=True):
        grabbed.append(bbox)
        return FakeImage()

    monkeypatch.setattr("PIL.ImageGrab.grab", staticmethod(fake_grab))
    monkeypatch.setattr(
        "tools.vision._encode_image", lambda path: ("image/jpeg", "QUJD")
    )
    monkeypatch.setattr("tools.capabilities.requests.post", lambda *a, **k: FakeResponse())
    result = ScreenOcrTool().execute({"region": "0,0,800,600"})
    assert "HELLO FROM THE SCREEN" in result
    assert grabbed == [(0, 0, 800, 600)]


def test_screen_ocr_requires_key(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "google_api_key", "")
    with pytest.raises(ToolError, match="GOOGLE_API_KEY"):
        ScreenOcrTool().execute({})


# -- screen_time -----------------------------------------------------------

@pytest.fixture(autouse=True)
def isolation_for_screen_time():
    _SCREEN_SAMPLES.clear()
    yield
    _SCREEN_SAMPLES.clear()


def test_record_and_summarize(monkeypatch):
    monkeypatch.setattr("tools.capabilities._foreground_app", lambda: "chrome.exe")
    record_sample()
    record_sample()
    monkeypatch.setattr("tools.capabilities._foreground_app", lambda: "notepad.exe")
    record_sample()
    summary = summarize_screen_time(60)
    assert "chrome.exe" in summary
    assert "notepad.exe" in summary
    assert "66.7%" in summary  # 2/3 samples


def test_screen_time_empty():
    summary = summarize_screen_time(60)
    assert "No screen-time data" in summary


def test_foreground_app_returns_string():
    assert isinstance(_foreground_app(), str)


# -- media_control ---------------------------------------------------------

def test_media_control_unknown_action():
    with pytest.raises(ToolError, match="Unknown action"):
        MediaControlTool().execute({"action": "spin-around"})


def test_media_control_sends_key(monkeypatch):
    pressed = []
    monkeypatch.setattr(
        "tools.capabilities._send_media_key", lambda code: pressed.append(code)
    )
    result = MediaControlTool().execute({"action": "play_pause"})
    assert pressed == [MEDIA_KEYS["play_pause"]]
    assert "play_pause" in result


def test_media_keys_map_cover_actions():
    for action in ("play", "pause", "next", "previous", "stop",
                   "volume_up", "volume_down", "mute"):
        assert action in MEDIA_KEYS


# -- export_pdf ------------------------------------------------------------

def test_build_pdf_bytes_is_valid_header():
    pdf = build_pdf_bytes("Test Report", "Hello world. " * 40)
    assert pdf.startswith(b"%PDF-1.4")
    assert b"%%EOF" in pdf
    assert b"/Font" in pdf


def test_export_pdf_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    result = ExportPdfTool().execute({"title": "Daily Briefing", "content": "Body text" * 30})
    assert "PDF report" in result
    pdfs = sorted((tmp_path / "exports").glob("*.pdf"))
    assert len(pdfs) == 1
    assert pdfs[0].read_bytes().startswith(b"%PDF")


def test_export_pdf_requires_content(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    with pytest.raises(ToolError, match="content"):
        ExportPdfTool().execute({"title": "X", "content": ""})


def test_export_pdf_multipage():
    pdf = build_pdf_bytes("Big", "\n".join("line %d - " % i + "x" * 90 for i in range(200)))
    assert pdf.count(b"endstream") >= 4  # multiple pages


# -- Registry + approval gating -------------------------------------------

def test_capability_tools_registered():
    registry = build_default_registry()
    for name in ("screen_ocr", "screen_time", "media_control", "export_pdf"):
        assert registry.get(name) is not None, name


def test_system_affecting_tools_require_approval():
    assert is_sensitive("media_control")
    assert is_sensitive("export_pdf")


def test_observation_tools_are_not_sensitive():
    assert not is_sensitive("screen_ocr")
    assert not is_sensitive("screen_time")