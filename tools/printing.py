"""
Print documents (Phase 37).

Sends a local file to the default Windows printer using the shell's
"print" verb (no extra dependencies, no driver code). Approval-gated
because it sends a file to a printer. Only a safe allow-list of common
printable file types is accepted.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from tools.base import Tool, ToolError

#: Extensions JARVIS will hand to the printer (shell print verb).
PRINTABLE_EXTENSIONS = {
    ".txt",
    ".md",
    ".pdf",
    ".docx",
    ".doc",
    ".rtf",
    ".png",
    ".jpg",
    ".jpeg",
}


class PrintTool(Tool):
    name = "print_document"
    description = (
        "Sends a local file to the default Windows printer (shell 'print' "
        "verb). Args: path (absolute path to a .txt, .md, .pdf, .docx or "
        "image). Requires your approval."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the file to print.",
            }
        },
        "required": ["path"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        raw = (self._arg(args, "path", "") or "").strip()
        if not raw:
            raise ToolError("Provide the path of the file to print.")
        target = Path(raw).expanduser()
        if not target.is_file():
            raise ToolError(f"File not found: {target}")
        if target.suffix.lower() not in PRINTABLE_EXTENSIONS:
            raise ToolError(
                "I can only print: "
                + ", ".join(sorted(PRINTABLE_EXTENSIONS))
            )
        if os.name != "nt":
            raise ToolError("Printing is only supported on Windows.")
        try:
            os.startfile(str(target), "print")  # noqa: S606 - explicit user request
        except OSError as exc:
            raise ToolError(f"Could not print {target.name}: {exc}") from exc
        return f"Sent {target.name} to the default printer."


def register_printing_tools(registry) -> None:
    """Register the Phase 37 print tool on a registry."""
    registry.register(PrintTool())
