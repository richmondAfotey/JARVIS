"""
Coding agent tools (Phase 38) - JARVIS as your software engineer.

Lets JARVIS work on the user's own codebase:

    * repo_tree     - show the project layout (respects git/venv ignores)
    * repo_find     - search file contents with a regex
    * read_code     - read a source file with line numbers
    * edit_code     - apply an exact old->new patch (backed up; approval-gated)
    * run_tests     - run the test suite and report the outcome
    * git_status    - show the repo's working-tree state
    * code_query    - TF-IDF search over the codebase (code-aware RAG)
    * code_reindex  - rebuild the code search index
    * coding_agent  - run a full coding session (plan -> edit -> test -> report)

The agent itself (ai/coder.py) loops over these tools until a task is
done, re-running tests after each edit so failures feed back into the
next step. All the tools are local; only the agent's model calls go online.

Safety:
    * read-only tools never touch anything.
    * edit_code writes a ``<file>.bak`` backup and is approval-gated (it
      is listed in SENSITIVE_TOOLS) so the main Brain asks the user first.
    * run_tests only runs the configured test command under the project.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.base import Tool, ToolError
from utils.logger import get_logger

log = get_logger(__name__)

#: Directories that are never part of "the project" for the agent.
_IGNORED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    "dist", "build", "data", ".idea", ".vscode", ".mypy_cache", ".ruff_cache",
}

#: Extensions the coding tools treat as source code.
_SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".go", ".rb", ".php", ".sh", ".ps1", ".bat", ".sql", ".json",
    ".yaml", ".yml", ".toml", ".ini", ".md", ".rs", ".swift", ".kt", ".cfg",
}

_MAX_FILE_BYTES = 512_000
_READ_LIMIT_CHARS = 8_000
_FIND_MAX_RESULTS = 60
_FIND_MAX_FILES = 400
_PATCH_MAX_CHARS = 50_000
_TREE_MAX_ENTRIES = 150
_TREE_MAX_DEPTH = 2
_TEST_MAX_OUTPUT_CHARS = 12_000
_RUN_TIMEOUT = 240
_INDEX_MAX_FILES = 400
_CODE_CHUNK_WORDS = 200
_CODE_CHUNK_OVERLAP = 20


def _default_project_dir() -> Path:
    """The folder the coding agent works on (settings or the repo root)."""
    from config import PROJECT_ROOT, settings

    raw = (getattr(settings, "coder_project_dir", "") or "").strip()
    if raw:
        return Path(os.path.expandvars(os.path.expanduser(raw)))
    return PROJECT_ROOT


def _resolve(root: Path, path_raw: str) -> Path:
    """Resolve ``path_raw`` as an absolute path or relative to the project."""
    value = os.path.expandvars(os.path.expanduser(str(path_raw or ""))).strip()
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (root / value).resolve() if value else root


def _is_text(raw: bytes) -> bool:
    if b"\x00" in raw[:4096]:
        return False
    try:
        raw.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _iter_source_files(root: Path, max_files: int = _FIND_MAX_FILES) -> list[Path]:
    """Source files under the project, skipping ignored directories."""
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _IGNORED_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in _SOURCE_EXTENSIONS:
            continue
        files.append(path)
        if len(files) >= max_files:
            break
    return files


def _fmt_timeout(exc: subprocess.TimeoutExpired) -> str:
    return f"Command timed out after {exc.timeout}s."


# -- Project layout -----------------------------------------------------------

class RepoTreeTool(Tool):
    name = "repo_tree"
    description = (
        "Shows the project's layout as an indented tree (folders first), "
        "ignoring .git/.venv/build/data. Call this FIRST to understand the "
        "codebase before reading or editing anything."
    )
    parameters = {
        "type": "object",
        "properties": {
            "depth": {
                "type": "integer",
                "description": "How many folder levels to descend (default 2).",
            },
        },
    }

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = Path(project_dir) if project_dir else _default_project_dir()

    def execute(self, args: dict[str, Any]) -> str:
        depth = int(self._arg(args, "depth", _TREE_MAX_DEPTH) or _TREE_MAX_DEPTH)
        depth = max(0, min(6, depth))
        lines = [f"Project: {self.project_dir}"]
        lines.extend(_walk_tree(self.project_dir, "", depth, _TREE_MAX_ENTRIES))
        if len(lines) == 1:
            return f"{self.project_dir} is empty or unreadable."
        return "\n".join(lines)


def _walk_tree(
    folder: Path,
    prefix: str,
    max_depth: int,
    max_entries: int,
) -> list[str]:
    lines: list[str] = []
    try:
        entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return lines
    for entry in entries:
        if entry.name in _IGNORED_DIRS:
            continue
        if len(lines) >= max_entries:
            lines.append(f"{prefix}... (more entries truncated)")
            break
        if entry.is_dir():
            lines.append(f"{prefix}{entry.name}/")
            lines.extend(_walk_tree(entry, prefix + "    ", max_depth - 1, max_entries))
        elif entry.is_file():
            lines.append(f"{prefix}{entry.name}")
    return lines


# -- Search -------------------------------------------------------------------

class RepoFindTool(Tool):
    name = "repo_find"
    description = (
        "Searches the project's source files for a regex pattern and returns "
        "matching lines as file:line: text. Use before editing to locate the "
        "exact code involved."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex to search for (case-insensitive)."},
            "path": {"type": "string", "description": "Optional file or folder to search instead."},
        },
        "required": ["pattern"],
    }

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = Path(project_dir) if project_dir else _default_project_dir()

    def execute(self, args: dict[str, Any]) -> str:
        pattern = (self._arg(args, "pattern", "") or "").strip()
        if not pattern:
            raise ToolError("Provide a pattern to search for.")
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE)

        target = _resolve(self.project_dir, self._arg(args, "path", ""))
        if not target.exists():
            raise ToolError(f"Path not found: {target}")

        files = [target] if target.is_file() else [
            p for p in _iter_source_files(target) if p.suffix.lower() in _SOURCE_EXTENSIONS
        ]

        matches: list[str] = []
        for file in files:
            try:
                raw = file.read_bytes()
            except (OSError, PermissionError):
                continue
            if not _is_text(raw) or len(raw) > _MAX_FILE_BYTES:
                continue
            for idx, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
                if len(line) > 800 or not regex.search(line):
                    continue
                rel = file.relative_to(self.project_dir) if self._is_inside(file) else file
                matches.append(f"{rel}:{idx}: {line.strip()[:220]}")
                if len(matches) >= _FIND_MAX_RESULTS:
                    break
            if len(matches) >= _FIND_MAX_RESULTS:
                break

        if not matches:
            return f"No matches for {pattern!r} in {len(files)} file(s)."
        return f"Found {len(matches)} match(es) for {pattern!r}:\n" + "\n".join(matches)

    def _is_inside(self, path: Path) -> bool:
        try:
            path.relative_to(self.project_dir)
            return True
        except ValueError:
            return False


# -- Reading ------------------------------------------------------------------

class ReadCodeTool(Tool):
    name = "read_code"
    description = (
        "Reads a source file with line numbers so you can see the exact code "
        "before editing it. Use start_line/line_count to page through long files."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File to read (absolute or project-relative)."},
            "start_line": {"type": "integer", "description": "1-based first line (default 1)."},
            "line_count": {"type": "integer", "description": "How many lines to show (default 200)."},
        },
        "required": ["path"],
    }

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = Path(project_dir) if project_dir else _default_project_dir()

    def execute(self, args: dict[str, Any]) -> str:
        path = _resolve(self.project_dir, self._arg(args, "path", ""))
        if not path.exists() or path.is_dir():
            raise ToolError(f"File not found: {path}")
        try:
            raw = path.read_bytes()
        except (OSError, PermissionError) as exc:
            raise ToolError(f"Could not read {path}: {exc}") from exc
        if not _is_text(raw):
            raise ToolError(f"{path} does not appear to be a text file.")
        if len(raw) > _MAX_FILE_BYTES:
            raise ToolError(f"{path} is too large to read whole (>{_MAX_FILE_BYTES} bytes).")

        start = max(1, int(self._arg(args, "start_line", 1) or 1))
        count = max(1, min(500, int(self._arg(args, "line_count", 200) or 200)))
        lines = raw.decode("utf-8-sig").splitlines()
        end = min(len(lines), start + count - 1)
        if start > len(lines):
            raise ToolError(f"start_line {start} is past the end of {path} ({len(lines)} lines).")

        body = []
        width = len(str(end))
        for idx in range(start - 1, end):
            body.append(f"{idx + 1:>{width}} | {lines[idx]}")
        if start > 1:
            body.insert(0, f"... (lines 1-{start - 1} omitted; file has {len(lines)} lines)")
        if end < len(lines):
            body.append(f"... (lines {end + 1}-{len(lines)} omitted)")
        return f"{path}\n" + "\n".join(body)


# -- Editing ------------------------------------------------------------------

class EditCodeTool(Tool):
    name = "edit_code"
    description = (
        "Applies an exact text replacement to a source file. old must match "
        "exactly once; new replaces it. Writes a '<file>.bak' backup first. "
        "Requires user approval. Use read_code first to copy the exact text."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File to edit."},
            "old": {"type": "string", "description": "Exact existing text to replace."},
            "new": {"type": "string", "description": "Replacement text."},
        },
        "required": ["path", "old", "new"],
    }

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = Path(project_dir) if project_dir else _default_project_dir()

    def execute(self, args: dict[str, Any]) -> str:
        path = _resolve(self.project_dir, self._arg(args, "path", ""))
        old = self._arg(args, "old", "") or ""
        new = self._arg(args, "new", "") or ""
        if not path.exists() or path.is_dir():
            raise ToolError(f"File not found: {path}")
        if not old:
            raise ToolError("Provide the exact existing text to replace ('old').")
        if len(old) > _PATCH_MAX_CHARS or len(new) > _PATCH_MAX_CHARS:
            raise ToolError("Edit fragment too large.")

        try:
            raw = path.read_bytes()
        except (OSError, PermissionError) as exc:
            raise ToolError(f"Could not read {path}: {exc}") from exc
        if not _is_text(raw):
            raise ToolError(f"{path} does not appear to be a text file.")
        text = raw.decode("utf-8-sig")

        occurrences = text.count(old)
        if occurrences == 0:
            raise ToolError(
                "old text not found in the file. Use read_code to view the "
                "exact current source and copy it verbatim."
            )
        if occurrences > 1:
            raise ToolError(
                f"old text matches {occurrences} times; include more context in "
                "'old' so the edit is unambiguous."
            )

        patched = text.replace(old, new, 1)
        try:
            path.with_suffix(path.suffix + ".bak").write_bytes(raw)
        except (OSError, PermissionError) as exc:
            raise ToolError(f"Could not write backup: {exc}") from exc
        try:
            path.write_text(patched, encoding="utf-8")
        except (OSError, PermissionError) as exc:
            raise ToolError(f"Could not write file: {exc}") from exc
        changed_lines = new.count("\n") + 1
        return (
            f"Edited {path} ({occurrences} occurrence, ~{changed_lines} line(s) "
            f"new). Backup saved to {path.with_suffix(path.suffix + '.bak')}."
        )


# -- Tests --------------------------------------------------------------------

class RunTestsTool(Tool):
    name = "run_tests"
    description = (
        "Runs the project's test suite (the configured CODER_TEST_COMMAND, "
        "default 'python -m pytest') and returns the exit code plus the tail "
        "of the output. Call this after every edit_code to verify your change."
    )
    parameters = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Optional path to run instead of the whole suite.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 240).",
            },
        },
    }

    def __init__(self, project_dir: Path | None = None, test_command: str | None = None):
        self.project_dir = Path(project_dir) if project_dir else _default_project_dir()
        self.test_command = test_command

    def _command(self, target: str) -> list[str]:
        from config import settings

        base = self.test_command or getattr(settings, "coder_test_command", "") or ""
        parts = shlex.split(base) if base else ["python", "-m", "pytest"]
        if parts and parts[0] in ("python", "python3"):
            parts[0] = sys.executable
        if target:
            resolved = _resolve(self.project_dir, target)
            if not resolved.exists():
                raise ToolError(f"Test target not found: {resolved}")
            parts.append(str(resolved))
        return parts

    def execute(self, args: dict[str, Any]) -> str:
        target = (self._arg(args, "target", "") or "").strip()
        timeout = int(self._arg(args, "timeout", _RUN_TIMEOUT) or _RUN_TIMEOUT)
        try:
            parts = self._command(target)
        except ToolError:
            raise

        try:
            proc = subprocess.run(
                parts,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.project_dir),
            )
        except FileNotFoundError as exc:
            raise ToolError(f"Could not run {parts[0]} - not found on PATH.") from exc
        except subprocess.TimeoutExpired as exc:
            return _fmt_timeout(exc)
        except OSError as exc:
            raise ToolError(f"Could not run tests: {exc}") from exc

        combined = (proc.stdout or "") + (proc.stderr or "")
        tail = combined.strip()[-_TEST_MAX_OUTPUT_CHARS:]
        header = f"[exit code {proc.returncode}] {parts[0]} ..."
        if not tail:
            return f"{header}\n(no output)"
        return f"{header}\n{tail}"


# -- Git ----------------------------------------------------------------------

class GitStatusTool(Tool):
    name = "git_status"
    description = (
        "Shows the project's git state: changed/staged/untracked files and a "
        "diff --stat. Useful to understand what has been modified before "
        "working on the repo."
    )
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = Path(project_dir) if project_dir else _default_project_dir()

    def execute(self, args: dict[str, Any]) -> str:
        status = self._run(["git", "status", "--short"])
        if status is None:
            return f"{self.project_dir} is not a git repository (or git is unavailable)."
        diff = self._run(["git", "diff", "--stat"]) or ""
        log_lines = self._run(["git", "log", "--oneline", "-5"]) or ""
        lines = ["Git status (short):", status or "(clean)"]
        if diff:
            lines.append("\nDiff stat:")
            lines.append(diff)
        if log_lines:
            lines.append("\nRecent commits:")
            lines.append(log_lines)
        return "\n".join(lines)

    def _run(self, cmd: list[str]) -> str | None:
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=20, cwd=str(self.project_dir)
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.strip()


# -- Code RAG -----------------------------------------------------------------

class CodeIndex:
    """A TF-IDF index over the project's source files (code-aware RAG)."""

    def __init__(self, project_dir: Path, chunks: list[dict] | None = None):
        self.project_dir = Path(project_dir).resolve()
        self._index = None
        if chunks:
            from tools.rag import RagIndex

            index = RagIndex(root_dir=str(self.project_dir))
            index.chunks = chunks
            index._build()
            self._index = index

    @property
    def ready(self) -> bool:
        return self._index is not None and self._index._tfidf is not None

    def query(self, question: str, top_k: int = 5) -> list[dict]:
        if not self.ready:
            return []
        return self._index.query(question, top_k=top_k)

    def rebuild(self) -> dict:
        from tools.rag import _chunk_text, _safe_read, RagIndex

        files = _iter_source_files(self.project_dir, max_files=_INDEX_MAX_FILES)
        chunks: list[dict] = []
        for file in files:
            text = _safe_read(file)
            if not text:
                continue
            for chunk in _chunk_text(text, _CODE_CHUNK_WORDS, _CODE_CHUNK_OVERLAP):
                chunks.append({"id": len(chunks), "source": str(file), "text": chunk})
        index = RagIndex(root_dir=str(self.project_dir))
        index.chunks = chunks
        index._build()
        self._index = index
        return {"files": len(files), "chunks": len(chunks)}

    def save(self, path: Path) -> None:
        if self._index is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self._index.save(path)

    def load(self, path: Path) -> bool:
        if not path.exists():
            return False
        try:
            from tools.rag import RagIndex

            self._index = RagIndex.load(path)
            return True
        except Exception as exc:  # noqa: BLE001 - a stale cache must not crash
            log.debug("Could not load code index: %s", exc)
            return False


_code_index_cache: dict[str, CodeIndex] = {}


def _get_code_index(project_dir: Path, force_rebuild: bool = False) -> CodeIndex:
    key = str(Path(project_dir).resolve())
    cached = _code_index_cache.get(key)
    if cached is not None and not force_rebuild:
        return cached
    from config import settings

    cache_dir = (
        Path(settings.rag_index_dir) if settings.rag_index_dir else settings.data_dir / "rag_index"
    )
    cache_file = cache_dir / "code_index.json"
    index = CodeIndex(project_dir)
    # Only reuse a cached index that was built for THIS project.
    if not force_rebuild and _cached_root_matches(cache_file, key) and index.load(cache_file):
        _code_index_cache[key] = index
        return index
    index.rebuild()
    index.save(cache_file)
    _code_index_cache[key] = index
    return index


def _cached_root_matches(cache_file: Path, project_key: str) -> bool:
    try:
        import json

        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        return payload.get("root_dir") == project_key
    except Exception:  # noqa: BLE001 - a bad cache just gets rebuilt
        return False


class CodeQueryTool(Tool):
    name = "code_query"
    description = (
        "Searches the codebase for the passages most relevant to a coding "
        "question (a code-aware index). Returns file paths and code snippets. "
        "Use for 'where is X handled?' questions before reading files."
    )
    parameters = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "What you want to find in the code."},
            "top_k": {"type": "integer", "description": "How many passages (default 5)."},
        },
        "required": ["question"],
    }

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = Path(project_dir) if project_dir else _default_project_dir()

    def execute(self, args: dict[str, Any]) -> str:
        question = (self._arg(args, "question", "") or "").strip()
        if not question:
            raise ToolError("Provide a question to search the code for.")
        top_k = int(self._arg(args, "top_k", 5) or 5)
        results = _get_code_index(self.project_dir).query(question, top_k=top_k)
        if not results:
            return (
                f"No relevant code found for {question!r}. Try repo_find with "
                "a specific term, or run code_reindex first."
            )
        lines = [f"Relevant code for: {question}"]
        for result in results:
            lines.append(f"\n[{result['source']}] (score {result['score']})")
            lines.append(result["text"][:1500])
        return "\n".join(lines)


class CodeReindexTool(Tool):
    name = "code_reindex"
    description = (
        "Rebuilds the code search index from scratch. Call this after big "
        "structural changes so code_query reflects the new code."
    )
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = Path(project_dir) if project_dir else _default_project_dir()

    def execute(self, args: dict[str, Any]) -> str:
        result = _get_code_index(self.project_dir, force_rebuild=True).rebuild()
        return (
            f"Rebuilt the code index from {result['files']} file(s) into "
            f"{result['chunks']} chunk(s)."
        )


# -- Full coding session ------------------------------------------------------

class CodingAgentTool(Tool):
    name = "coding_agent"
    description = (
        "Runs a full coding session on the project: JARVIS becomes a software "
        "engineer that explores the code, edits files with edit_code, runs the "
        "tests and iterates on failures until done. Use for real coding tasks "
        "('fix the bug in voice/speech_to_text.py', 'add a tool that ...'). "
        "The request is handed to a dedicated coding model. Requires user "
        "approval because it edits files."
    )
    parameters = {
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": "The coding task, described like a ticket.",
            },
        },
        "required": ["request"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        request = (self._arg(args, "request", "") or "").strip()
        if not request:
            raise ToolError("Describe the coding task in 'request'.")
        from ai.coder import CodingAgent

        return CodingAgent().run(request)


# -- Registries ---------------------------------------------------------------

def build_coding_registry(
    project_dir: Path | str | None = None,
    test_command: str | None = None,
) -> ToolRegistry:
    """A registry with just the coding tools (used by the agent's loop).

    Deliberately excludes `coding_agent` to prevent recursion.
    """
    from tools.registry import ToolRegistry

    root = Path(project_dir) if project_dir else _default_project_dir()
    registry = ToolRegistry()
    registry.register(RepoTreeTool(root))
    registry.register(RepoFindTool(root))
    registry.register(ReadCodeTool(root))
    registry.register(EditCodeTool(root))
    registry.register(RunTestsTool(root, test_command=test_command))
    registry.register(GitStatusTool(root))
    registry.register(CodeQueryTool(root))
    registry.register(CodeReindexTool(root))
    return registry


def register_coding_tools(registry) -> None:
    """Register the coding tools (including coding_agent) on a main registry."""
    registry.register(RepoTreeTool())
    registry.register(RepoFindTool())
    registry.register(ReadCodeTool())
    registry.register(EditCodeTool())
    registry.register(RunTestsTool())
    registry.register(GitStatusTool())
    registry.register(CodeQueryTool())
    registry.register(CodeReindexTool())
    registry.register(CodingAgentTool())
