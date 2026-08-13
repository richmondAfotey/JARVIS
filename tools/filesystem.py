"""
File intelligence tools (Phase 8).

Let JARVIS inspect and work with files safely:
    * list_directory - list a folder's contents with sizes
    * read_file      - read the start of a text file (size-limited)
    * search_files   - find files by name inside a folder
    * file_info      - size, dates and type of a file or folder
    * write_file     - create or overwrite a text file (parents created)
    * create_folder  - create a folder and any missing parents (Phase 27)
    * write_project  - scaffold a whole project: many folders + files in one
                       call (Phase 27) - used when JARVIS codes for you

Safety rules:
    * Paths are validated to exist before reading.
    * Reads are size-limited so huge or binary files cannot flood the chat.
    * Binary files are detected and refused.
    * Writing is size-limited and never deletes anything.
    * Destructive operations (delete, move, rename) are intentionally
      excluded until a confirmation flow exists (later phase).
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.base import Tool, ToolError

_READ_LIMIT_CHARS = 4000
_MAX_ENTRIES = 100
_MAX_SEARCH_RESULTS = 50
_WRITE_LIMIT_CHARS = 100_000


def _resolve(path_raw: str) -> Path:
    """Expand env vars and ~, then return a Path."""
    return Path(os.path.expandvars(os.path.expanduser(str(path_raw))))


def _fmt_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{num} B"


def _is_text(raw: bytes) -> bool:
    """Best-effort check that bytes look like text."""
    try:
        raw.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


class ListDirectoryTool(Tool):
    name = "list_directory"
    description = (
        "Lists the files and folders inside a directory with their sizes. "
        "Leave path empty to list the current folder."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The directory to list, e.g. 'C:/Users/me/Documents' or '~'.",
            }
        },
    }

    def execute(self, args: dict[str, Any]) -> str:
        path_raw = self._arg(args, "path", "")
        folder = _resolve(path_raw) if path_raw else Path.cwd()
        if not folder.exists():
            raise ToolError(f"Path not found: {folder}")
        if not folder.is_dir():
            raise ToolError(f"Not a directory: {folder}")
        try:
            entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError as exc:
            raise ToolError(f"Permission denied: {folder}") from exc

        lines = [f"Contents of {folder}:"]
        shown = 0
        for entry in entries:
            if shown >= _MAX_ENTRIES:
                lines.append(f"... [{len(entries) - shown} more entries]")
                break
            if entry.is_dir():
                lines.append(f"[dir]   {entry.name}/")
            else:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                lines.append(f"{_fmt_size(size):>8}  {entry.name}")
            shown += 1
        if not entries:
            return f"{folder} is empty."
        return "\n".join(lines)


class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "Reads the beginning of a text file so you can answer questions about "
        "its contents. max_chars limits how much is read."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the text file."},
            "max_chars": {
                "type": "integer",
                "description": "Optional limit on characters to read.",
            },
        },
        "required": ["path"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        path_raw = self._arg(args, "path", "")
        max_chars = int(self._arg(args, "max_chars", 0) or 0)
        if max_chars <= 0:
            max_chars = _READ_LIMIT_CHARS
        path = _resolve(path_raw)
        if not path.exists():
            raise ToolError(f"File not found: {path}")
        if path.is_dir():
            raise ToolError(f"{path} is a directory, not a file.")
        try:
            raw = path.read_bytes()
        except (OSError, PermissionError) as exc:
            raise ToolError(f"Could not read {path}: {exc}") from exc
        if not _is_text(raw):
            raise ToolError(f"{path} does not appear to be a text file (binary or unknown encoding).")
        text = raw.decode("utf-8-sig")
        snippet = text[:max_chars]
        if len(text) > max_chars:
            snippet += f"\n... [truncated: showing {max_chars} of {len(text)} chars]"
        return snippet if snippet.strip() else f"{path} is empty."


class SearchFilesTool(Tool):
    name = "search_files"
    description = (
        "Searches a folder recursively for files whose name contains the query. "
        "Leave folder empty to search the current folder."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Part of the filename to look for."},
            "folder": {
                "type": "string",
                "description": "The folder to search inside (recursively).",
            },
        },
        "required": ["query"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        query = (self._arg(args, "query", "") or "").strip().lower()
        folder_raw = self._arg(args, "folder", "")
        folder = _resolve(folder_raw) if folder_raw else Path.cwd()
        if not query:
            raise ToolError("Provide a query to search for.")
        if not folder.exists() or not folder.is_dir():
            raise ToolError(f"Folder not found: {folder}")

        matches: list[str] = []
        try:
            for root, dirs, files in os.walk(folder):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for name in files:
                    if query in name.lower():
                        matches.append(str(Path(root) / name))
                        if len(matches) >= _MAX_SEARCH_RESULTS:
                            break
                if len(matches) >= _MAX_SEARCH_RESULTS:
                    break
        except PermissionError as exc:
            raise ToolError(f"Permission denied while searching: {exc}") from exc

        if not matches:
            return f"No files matching {query!r} in {folder}."
        return f"Found {len(matches)} file(s) matching {query!r}:\n" + "\n".join(matches)


class FileInfoTool(Tool):
    name = "file_info"
    description = "Returns size, dates and type for a file or folder."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file or folder."}
        },
        "required": ["path"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        path = _resolve(self._arg(args, "path", ""))
        if not path.exists():
            raise ToolError(f"Path not found: {path}")
        try:
            stat = path.stat()
        except (OSError, PermissionError) as exc:
            raise ToolError(f"Could not stat {path}: {exc}") from exc
        kind = "directory" if path.is_dir() else "file"
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        created = datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"{kind}: {path}\n"
            f"size: {_fmt_size(stat.st_size)}\n"
            f"modified: {modified}\n"
            f"created: {created}"
        )


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Creates or overwrites a text file with the given content. Parent "
        "folders are created automatically."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path of the file to write."},
            "content": {"type": "string", "description": "The text content to write."},
        },
        "required": ["path", "content"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        path = _resolve(self._arg(args, "path", ""))
        content = self._arg(args, "content", "")
        if not path.name:
            raise ToolError("Provide a filename to write to.")
        if len(content) > _WRITE_LIMIT_CHARS:
            raise ToolError(f"Content is too large ({len(content)} chars; max {_WRITE_LIMIT_CHARS}).")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except (OSError, PermissionError) as exc:
            raise ToolError(f"Could not write {path}: {exc}") from exc
        return f"Wrote {len(content)} chars to {path}."


class CreateFolderTool(Tool):
    name = "create_folder"
    description = (
        "Creates a folder (and any missing parent folders) on disk. Use this "
        "to make directories or scaffold a whole project tree, e.g. "
        "'C:/Users/me/Documents/myapp/src'. Safe to call if it already exists."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Full path of the folder to create."}
        },
        "required": ["path"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        path_raw = (self._arg(args, "path", "") or "").strip()
        if not path_raw:
            raise ToolError("Provide a folder path to create.")
        path = _resolve(path_raw)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as exc:
            raise ToolError(f"Could not create folder {path}: {exc}") from exc
        return f"Created folder: {path}"


class WriteProjectTool(Tool):
    name = "write_project"
    description = (
        "Writes a whole project from a list of files: creates every folder "
        "and every file at once. Use this when the user asks you to build or "
        "code a program, a website, a script or any multi-file project. "
        "Pass 'root' as the base folder and 'files' as a list of "
        "{'path': <relative or absolute path>, 'content': <file text>}."
    )
    parameters = {
        "type": "object",
        "properties": {
            "root": {
                "type": "string",
                "description": "Base folder for the project, e.g. 'C:/Users/me/Documents/myapp'. Create parents as needed.",
            },
            "files": {
                "type": "array",
                "description": "List of files to write. Each item has a 'path' (relative to root, or absolute) and its 'content'.",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path (relative to root)."},
                        "content": {"type": "string", "description": "The file's text content."},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        "required": ["root", "files"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        root_raw = (self._arg(args, "root", "") or "").strip()
        if not root_raw:
            raise ToolError("Provide a project root folder.")
        files = self._arg(args, "files", []) or []
        if not isinstance(files, list) or not files:
            raise ToolError("Provide at least one file in 'files'.")
        root = _resolve(root_raw)

        written = 0
        total_chars = 0
        errors: list[str] = []
        try:
            root.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as exc:
            raise ToolError(f"Could not create project root {root}: {exc}") from exc

        for item in files:
            if not isinstance(item, dict):
                errors.append("each file must be an object with 'path' and 'content'.")
                continue
            rel_path = (str(item.get("path", "")).strip())
            content = str(item.get("content", ""))
            if not rel_path:
                errors.append("a file entry is missing 'path'.")
                continue
            target = _resolve(rel_path) if os.path.isabs(rel_path) else root / rel_path
            if not target.name:
                errors.append(f"invalid path: {rel_path}.")
                continue
            if len(content) > _WRITE_LIMIT_CHARS:
                errors.append(f"{rel_path} is too large ({len(content)} chars).  Skipped.")
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                written += 1
                total_chars += len(content)
            except (OSError, PermissionError) as exc:
                errors.append(f"{rel_path}: {exc}")

        if written == 0:
            detail = " " + "; ".join(errors[:5]) if errors else ""
            raise ToolError(f"Could not write any files.{detail}")
        summary = f"Project created at {root}: {written}/{len(files)} file(s) written ({total_chars} chars)."
        if errors:
            summary += "\nIssues: " + "; ".join(errors[:5])
        return summary


def register_filesystem_tools(registry) -> None:
    """Register the Phase 8 file-intelligence tools on a registry."""
    registry.register(ListDirectoryTool())
    registry.register(ReadFileTool())
    registry.register(SearchFilesTool())
    registry.register(FileInfoTool())
    registry.register(WriteFileTool())
    registry.register(CreateFolderTool())
    registry.register(WriteProjectTool())
