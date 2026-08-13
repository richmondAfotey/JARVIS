"""Tests for the logging setup (Phase 18)."""

import logging
from unittest.mock import patch

from utils.logger import get_logger, setup_logging


def test_get_logger_names_forwarded():
    logger = get_logger("my.module")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "my.module"


def test_setup_logging_creates_file_handler(tmp_path, monkeypatch):
    # Point the app data dir at a temp folder so no real files are touched.
    fake_settings = type("S", (), {"data_dir": tmp_path / "data"})()
    monkeypatch.setattr("utils.logger.settings", fake_settings)
    (tmp_path / "data" / "logs").mkdir(parents=True, exist_ok=True)

    with patch("utils.logger.ensure_directories") as ensure:
        setup_logging(logging.DEBUG)

    root = logging.getLogger()
    assert any(type(h) is logging.StreamHandler for h in root.handlers)
    assert any(type(h).__name__ == "RotatingFileHandler" for h in root.handlers)
    ensure.assert_called_once()


def test_setup_logging_writes_to_log_file(tmp_path, monkeypatch):
    fake_settings = type("S", (), {"data_dir": tmp_path / "data"})()
    monkeypatch.setattr("utils.logger.settings", fake_settings)
    monkeypatch.setattr("utils.logger.ensure_directories", lambda: None)
    (tmp_path / "data" / "logs").mkdir(parents=True, exist_ok=True)

    setup_logging(logging.INFO)
    logger = get_logger("test_setup")
    logger.info("hello log file")

    log_file = tmp_path / "data" / "logs" / "jarvis.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "hello log file" in content