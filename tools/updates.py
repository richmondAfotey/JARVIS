"""
Self-update tool (Phase 21).

Lets JARVIS check whether a newer build of itself is available (and
optionally download it). The tool never installs without an explicit user
action - it only reports what the update manifest advertises.

Typical dialogue:
    User: "is there a new version of you?"
    JARVIS: checks the manifest, reports the latest version and notes.
"""

from __future__ import annotations

from typing import Any

from tools.base import Tool, ToolError


class CheckForUpdatesTool(Tool):
    name = "check_for_updates"
    description = (
        "Checks whether a newer version of this application is available "
        "and reports the latest version and its release notes. It does not "
        "install anything."
    )
    parameters = {"type": "object", "properties": {}}

    def execute(self, args: dict[str, Any]) -> str:
        from updates.updater import (
            UpdateError,
            check_for_update,
            current_version,
        )

        try:
            update = check_for_update()
        except UpdateError as exc:
            return f"Could not check for updates: {exc}"
        if update is None:
            return f"You are running the latest version ({current_version()})."
        notes = f"\nWhat's new: {update.notes}" if update.notes else ""
        return (
            f"Version {update.version} is available "
            f"(you have {current_version()}).{notes} "
            "Tell the user to open Settings > Software Updates to install it."
        )


def register_update_tools(registry) -> None:
    """Register the self-update tools."""
    registry.register(CheckForUpdatesTool())