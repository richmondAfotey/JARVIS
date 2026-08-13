"""
Script runner (Phase 15).

Executes a saved task script: an ordered list of tool calls that run
deterministically against the tool registry - no LLM needed mid-run.

Safety:
    * Runs are serialized (a mutex), so two scripts cannot collide.
    * A script stops at the first failing step, so a bad script cannot
      keep making changes.
    * Meta tools (run_script/create_script/...) are forbidden inside
      steps, so scripts cannot spawn recursive or self-editing runs.
    * A global step budget caps runaway scripts, and the result summary
      is truncated so a huge output cannot flood the chat.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from tools.base import ToolError
from utils.logger import get_logger

log = get_logger(__name__)

#: Tools a script step may NOT call (prevents recursion / self-editing).
FORBIDDEN_STEP_TOOLS = {
    "run_script",
    "create_script",
    "delete_script",
    "list_scripts",
}

_RESULT_LIMIT_CHARS = 5000


class ScriptRunner:
    def __init__(self, registry, max_steps: int = 30) -> None:
        self._registry = registry
        self._max_steps = int(max_steps)
        self._lock = threading.Lock()

    def run(self, script: dict[str, Any]) -> str:
        """Run a script dict (from the database) and return a summary."""
        name = script.get("name") or "script"
        try:
            steps = json.loads(script.get("steps") or "[]")
        except (json.JSONDecodeError, TypeError):
            steps = []
        if not isinstance(steps, list):
            steps = []
        if not steps:
            return f'Script {name!r} has no steps.'

        with self._lock:  # one script at a time
            outcomes: list[str] = []
            for index, step in enumerate(steps[: self._max_steps], 1):
                tool_name = step.get("name", "") if isinstance(step, dict) else ""
                arguments = (
                    step.get("arguments", {})
                    if isinstance(step, dict) and isinstance(step.get("arguments"), dict)
                    else {}
                )
                if isinstance(tool_name, str):
                    tool_name = tool_name.strip()
                if not tool_name:
                    outcomes.append(f"{index}. <missing tool name> -> error: malformed step")
                    return self._finish(name, outcomes)
                try:
                    result = self._registry.execute(tool_name, arguments)
                except ToolError as exc:
                    outcomes.append(f"{index}. {tool_name} -> error: {exc}")
                    return self._finish(name, outcomes)
                except Exception as exc:  # noqa: BLE001 - a buggy tool must not
                    log.exception("Script tool %s crashed", tool_name)
                    outcomes.append(f"{index}. {tool_name} -> error: {exc}")
                    return self._finish(name, outcomes)
                outcomes.append(f"{index}. {tool_name} -> {result}")

            if len(steps) > self._max_steps:
                outcomes.append(
                    f"... stopped: step limit of {self._max_steps} reached "
                    f"({len(steps)} steps in the script)."
                )

        return self._finish(name, outcomes)

    @staticmethod
    def _finish(name: str, outcomes: list[str]) -> str:
        summary = f'Script {name!r} finished ({len(outcomes)} step(s)):\n' + "\n".join(
            outcomes
        )
        if len(summary) > _RESULT_LIMIT_CHARS:
            summary = summary[:_RESULT_LIMIT_CHARS].rstrip() + "\n... [result truncated]"
        return summary