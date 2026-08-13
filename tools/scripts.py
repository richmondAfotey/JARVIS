"""
Task script tools (Phase 15) - advanced automation.

A script is a named, ordered list of tool calls saved to the database.
The AI can build one for a recurring job and replay it any time:

    * create_script - save (or overwrite) a script by name
    * run_script    - run its steps in order, deterministically
    * list_scripts  - show saved scripts
    * delete_script - remove a script

Steps are validated on save: each must name a real tool (checked at run
time) with a JSON-style arguments object. Scripts run to the first
failure and cannot call the meta tools (run_script, create_script, ...).
"""

from __future__ import annotations

import json
from typing import Any

from config import settings
from system.scripts import FORBIDDEN_STEP_TOOLS, ScriptRunner
from tools.base import Tool, ToolError


def _get_db(db):
    if db is not None:
        return db
    from memory.database import get_shared_database

    return get_shared_database()


def _parse_steps(raw: Any, max_steps: int) -> list[dict]:
    """Accept a list or a JSON string; validate into tool-call steps."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            raise ToolError("steps must be a valid JSON array of tool calls.")
    if not isinstance(raw, list):
        raise ToolError("steps must be a valid JSON array of tool calls.")
    if not raw:
        raise ToolError("Provide at least one step for the script.")
    if len(raw) > max_steps:
        raise ToolError(f"Too many steps ({len(raw)}); the maximum is {max_steps}.")

    steps: list[dict] = []
    for index, step in enumerate(raw, 1):
        if not isinstance(step, dict):
            raise ToolError(f"Step {index} must be an object with a 'name'.")
        name = step.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ToolError(f"Step {index} is missing a tool 'name'.")
        name = name.strip()
        if name in FORBIDDEN_STEP_TOOLS:
            raise ToolError(f"Step {index} cannot call {name!r} inside a script.")
        arguments = step.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise ToolError(f"Step {index} 'arguments' must be an object.")
        steps.append({"name": name, "arguments": arguments})
    return steps


class CreateScriptTool(Tool):
    name = "create_script"
    description = (
        "Saves a reusable task script: a named, ordered list of tool-call "
        "steps. steps is a JSON array like "
        '[{"name": "calculate", "arguments": {"expression": "2+2"}}]. '
        "Later run it any time with run_script."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Unique script name."},
            "steps": {
                "type": "array",
                "description": "List of tool-call steps to run in order.",
            },
            "description": {
                "type": "string",
                "description": "Optional one-line description.",
            },
        },
        "required": ["name", "steps"],
    }

    def __init__(self, db=None, max_steps: int = 30) -> None:
        self._db = _get_db(db)
        self._max_steps = max_steps

    def execute(self, args: dict[str, Any]) -> str:
        name = (self._arg(args, "name", "") or "").strip()
        if not name:
            raise ToolError("Provide a name for the script.")
        description = (self._arg(args, "description", "") or "").strip()
        steps = _parse_steps(self._arg(args, "steps", None), self._max_steps)
        self._db.save_script(name, description, json.dumps(steps))
        return f'Saved script {name!r} with {len(steps)} step(s).'


class RunScriptTool(Tool):
    name = "run_script"
    description = (
        "Runs a saved task script by name, executing its steps in order. "
        "Returns a summary of each step's result. Use to execute a multi-step "
        "task you pre-built with create_script."
    )
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Script name."}},
        "required": ["name"],
    }

    def __init__(self, registry, db=None, max_steps: int = 30) -> None:
        self._db = _get_db(db)
        self._runner = ScriptRunner(registry, max_steps=max_steps)

    def execute(self, args: dict[str, Any]) -> str:
        name = (self._arg(args, "name", "") or "").strip()
        if not name:
            raise ToolError("Provide the name of the script to run.")
        script = self._db.get_script(name)
        if script is None:
            raise ToolError(f"No script named {name!r}.")
        return self._runner.run(script)


class ListScriptsTool(Tool):
    name = "list_scripts"
    description = "Lists all saved task scripts with their descriptions."
    parameters = {"type": "object", "properties": {}}

    def __init__(self, db=None) -> None:
        self._db = _get_db(db)

    def execute(self, args: dict[str, Any]) -> str:
        scripts = self._db.list_scripts()
        if not scripts:
            return "No scripts saved yet."
        lines = [f"{len(scripts)} script(s):"]
        for script in scripts:
            try:
                count = len(json.loads(script["steps"]))
            except (json.JSONDecodeError, TypeError):
                count = 0
            description = script["description"] or ""
            line = f"- {script['name']} ({count} step(s))"
            if description:
                line += f": {description}"
            lines.append(line)
        return "\n".join(lines)


class DeleteScriptTool(Tool):
    name = "delete_script"
    description = "Deletes a saved task script by its name."
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Script name."}},
        "required": ["name"],
    }

    def __init__(self, db=None) -> None:
        self._db = _get_db(db)

    def execute(self, args: dict[str, Any]) -> str:
        name = (self._arg(args, "name", "") or "").strip()
        if not name:
            raise ToolError("Provide the name of the script to delete.")
        if self._db.delete_script(name):
            return f"Deleted script {name!r}."
        raise ToolError(f"No script named {name!r}.")


def register_scripts_tools(registry, database=None) -> None:
    """Register the Phase 15 task-script tools on a registry."""
    max_steps = max(1, int(settings.script_max_steps))
    registry.register(CreateScriptTool(database, max_steps=max_steps))
    registry.register(RunScriptTool(registry, database, max_steps=max_steps))
    registry.register(ListScriptsTool(database))
    registry.register(DeleteScriptTool(database))