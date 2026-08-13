"""
JARVIS AI - application entry point.

Run with:

    python main.py

First run may take a moment while Flet downloads its desktop runtime.
"""

from __future__ import annotations

import logging

from utils.logger import get_logger, setup_logging

setup_logging()
log = get_logger("main")

try:
    from ui.app import run
except Exception as exc:  # noqa: BLE001
    log.exception("Failed to import UI: %s", exc)
    raise


def main() -> None:
    log.info("JARVIS AI starting...")
    try:
        run()
    except KeyboardInterrupt:
        log.info("Shutdown requested.")
    except Exception as exc:  # noqa: BLE001
        log.exception("Unhandled error: %s", exc)
        raise


if __name__ == "__main__":
    main()
