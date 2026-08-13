"""Tests for Phase 32: clipboard paste + attachment auto-analysis."""

import tempfile
from pathlib import Path

import pytest

from tools.attachments import (
    build_user_message,
    classify,
    attachment_context,
)
from tools.base import ToolError


# -- classify ---------------------------------------------------------------

def test_classify_image():
    assert classify("x.png") == "image"
    assert classify("x.JPG") == "image"
    assert classify("x.webp") == "image"


def test_classify_document():
    assert classify("report.pdf") == "document"
    assert classify("notes.docx") == "document"
    assert classify("data.csv") == "document"


def test_classify_other():
    assert classify("movie.mp4") == "other"
    assert classify("app.exe") == "other"


# -- attachment_context -----------------------------------------------------

def test_document_context_reads_text(tmp_path):
    doc = tmp_path / "hello.txt"
    doc.write_text("Hello JARVIS, this is a test note.")
    assert "test note" in attachment_context(doc, "")


def test_document_missing_returns_error_text(tmp_path):
    assert "not found" in attachment_context(tmp_path / "gone.pdf", "").lower()


def test_image_context_without_vision(tmp_path, monkeypatch):
    # No GOOGLE_API_KEY -> vision tool raises ToolError, which we surface
    # as a friendly string instead of crashing.
    import tools.vision as vision_mod

    monkeypatch.setattr(vision_mod.settings, "google_api_key", "")
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    ctx = attachment_context(img, "what is here?")
    assert "not configured" in ctx or "vision" in ctx.lower()


# -- build_user_message -----------------------------------------------------

def test_build_message_without_attachments():
    assert build_user_message([], "hello") == "hello"


def test_build_message_folds_document_content(tmp_path):
    doc = tmp_path / "notes.txt"
    doc.write_text("Coffee is best served hot.")
    msg = build_user_message([str(doc)], "summarise this")
    assert "Coffee is best served hot" in msg
    assert "notes.txt" in msg


def test_build_message_empty_text_with_attachment(tmp_path):
    doc = tmp_path / "a.txt"
    doc.write_text("content here")
    msg = build_user_message([str(doc)], "")
    assert "content here" in msg


def test_build_message_truncates_giant_documents(tmp_path):
    big = tmp_path / "big.txt"
    big.write_text("x" * 50_000)
    msg = build_user_message([str(big)], "")
    assert "truncated" in msg
    assert len(msg) < 10_000


# -- clipboard --------------------------------------------------------------

def test_paste_image_from_pil_image(monkeypatch, tmp_path):
    import sys
    import types

    class FakePILImage:
        def convert(self, mode):
            return self

        def save(self, path, fmt):
            Path(path).write_bytes(b"fake")

    grab = types.ModuleType("PIL.ImageGrab")
    grab.grabclipboard = staticmethod(lambda: FakePILImage())
    monkeypatch.setitem(sys.modules, "PIL.ImageGrab", grab)
    if "PIL" not in sys.modules:
        monkeypatch.setitem(sys.modules, "PIL", types.ModuleType("PIL"))

    import utils.clipboard as cb

    saved = cb.paste_image(tmp_path)
    assert saved is not None
    assert saved.exists()


def test_paste_image_clipboard_empty_returns_none(monkeypatch, tmp_path):
    import sys
    import types

    grab = types.ModuleType("PIL.ImageGrab")
    grab.grabclipboard = staticmethod(lambda: None)
    monkeypatch.setitem(sys.modules, "PIL.ImageGrab", grab)

    import utils.clipboard as cb

    assert cb.paste_image(tmp_path) is None


def test_paste_files_empty_clipboard(monkeypatch, tmp_path):
    import sys
    import types

    class FakeWin32:
        CF_HDROP = 15

        @staticmethod
        def OpenClipboard():
            return True

        @staticmethod
        def CloseClipboard():
            return True

        @staticmethod
        def IsClipboardFormatAvailable(_fmt):
            return False

        @staticmethod
        def GetClipboardData(_fmt):
            return None

    monkeypatch.setitem(sys.modules, "win32clipboard", FakeWin32())

    import utils.clipboard as cb

    assert cb.paste_files(tmp_path) == []


def test_paste_files_copies_copied_file(monkeypatch, tmp_path):
    import sys
    import types

    source = tmp_path / "report.txt"
    source.write_text("hi")

    class FakeWin32:
        CF_HDROP = 15

        @staticmethod
        def OpenClipboard():
            return True

        @staticmethod
        def CloseClipboard():
            return True

        @staticmethod
        def IsClipboardFormatAvailable(_fmt):
            return True

        @staticmethod
        def GetClipboardData(_fmt):
            return [str(source)]

    monkeypatch.setitem(sys.modules, "win32clipboard", FakeWin32())

    import utils.clipboard as cb

    saved = cb.paste_files(tmp_path)
    assert saved and saved[0].read_text() == "hi"