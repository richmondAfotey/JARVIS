"""
JARVIS AI - Logging setup.

Python's built-in `logging` module is used so we get:
    * Timestamps on every message
    * Different severity levels (INFO, WARNING, ERROR, ...)
    * Messages written to both the console AND a log file

Any module can log with:

    from utils.logger import get_logger
    log = get_logger(__name__)
    log.info("hello")
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from config import settings, ensure_directories

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root logger once. Safe to call multiple times."""
    ensure_directories()

    root = logging.getLogger()
    # Remove existing handlers so we never double-log after a reload.
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    root.setLevel(level)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Console handler - shows everything while developing.
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # File handler - keeps a history, rotates at 1 MB per file.
    log_path = settings.data_dir / "logs" / "jarvis.log"
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a logger for a module. Use `__name__` as the argument."""
    return logging.getLogger(name)
