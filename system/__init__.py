"""System module - real-time machine metrics (Phase 9)."""

from __future__ import annotations

from system.monitor import SystemSnapshot, collect, format_uptime

__all__ = ["SystemSnapshot", "collect", "format_uptime"]
