"""
Code security audit tools (Phase 24).

Lets JARVIS review software the user has built for common security
weaknesses, propose fixes, and apply them:

    * audit_code    - scan a folder or file for weakness patterns (hardcoded
                      secrets, SQL/command injection, unsafe eval/pickle,
                      path traversal, weak crypto, and more)
    * suggest_patch - extract the exact lines around a finding so a fix can
                      be authored for that code
    * apply_patch   - apply an exact old->new text patch, creating a
                      ``<file>.bak`` backup first

This is a local, defensive code reviewer like a lightweight Bandit/Semgrep.
It only reads/writes files the user points it at; writes (apply_patch) are
approval-gated and always backed up.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from tools.base import Tool, ToolError

_MAX_FILES = 200
_MAX_FILE_BYTES = 512_000
_SNIPPET_LINES = 5
_PATCH_MAX_CHARS = 50_000
_IGNORED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    "dist", "build", "data", ".idea", ".vscode",
}
_SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".go", ".rb", ".php", ".sh", ".ps1", ".bat", ".sql", ".json",
    ".yaml", ".yml", ".toml", ".ini", ".env", ".rb", ".rs", ".swift", ".kt",
}

#: (id, severity, label, regex, fix_advice). `fix_advice` is shown to the
#: model so it can author a patch via apply_patch.
WEAKNESS_RULES: list[tuple[str, str, str, re.Pattern, str]] = [
    (
        "hardcoded-secret",
        "HIGH",
        "Hardcoded secret or API key",
        re.compile(
            r"(?:api[_-]?key|secret|password|passwd|token|credential|client[_-]?secret)"
            r"\s*[:=]\s*['\"][A-Za-z0-9_./+\-=]{12,}['\"]",
            re.IGNORECASE,
        ),
        "Move the value to an environment variable (e.g. os.getenv('API_KEY')) "
        "or a secrets manager; never commit real credentials.",
    ),
    (
        "sql-injection",
        "HIGH",
        "Possible SQL injection (string-built query)",
        re.compile(
            r"(?:execute|executemany|query|raw|run)\s*[=(]\s*(?:f|r)?['\"]?.*"
            r"SELECT|INSERT|UPDATE|DELETE[^'\"]*[\"']|\%s|"
            r"\bf[\"'][^\"']*(?:SELECT|INSERT|UPDATE|DELETE)[^\"']*\{",
            re.IGNORECASE,
        ),
        "Use parameterised queries / prepared statements with placeholders "
        "instead of concatenating or interpolating user input into SQL.",
    ),
    (
        "command-injection",
        "HIGH",
        "Possible shell / command injection",
        re.compile(
            r"os\.system\(|subprocess\.[a-z]+\(.*shell\s*=\s*True|"
            r"os\.popen\(|commands\.getoutput\(",
        ),
        "Prefer subprocess with a list of arguments and shell=False; never "
        "pass unsanitised user input into a shell string.",
    ),
    (
        "unsafe-eval",
        "HIGH",
        "Unsafe eval/exec of dynamic code",
        re.compile(r"(?<!ast\.)\beval\(|\bexec\(|compile\(.*eval"),
        "Avoid eval/exec on input strings; use safe parsers (ast.literal_eval, "
        "json.loads) when possible.",
    ),
    (
        "unsafe-pickle",
        "HIGH",
        "Unsafe deserialisation with pickle",
        re.compile(r"pickle\.(loads|load)|marshal\.loads?\b|cPickle\.loads?"),
        "pickle can execute arbitrary code; prefer JSON/msgpack for untrusted data.",
    ),
    (
        "path-traversal",
        "MEDIUM",
        "Possible path traversal",
        re.compile(r"open\(.*\.\./|os\.path\.join\(.*\.\.|Path\(.*\.\./|\.\.\/\w+"),
        "Sanitise user-supplied paths and reject '..' segments; resolve and "
        "confine to a base directory.",
    ),
    (
        "weak-crypto",
        "MEDIUM",
        "Weak or deprecated cryptography",
        re.compile(r"hashlib\.(md5|sha1)\(|MD5\(|SHA1\("),
        "Use a strong hash (SHA-256+) or a password KDF (bcrypt/argon2) for "
        "sensitive data.",
    ),
    (
        "plaintext-password",
        "HIGH",
        "Password handled/stored in plaintext",
        re.compile(
            r"password\s*(?:=|:).*(?:write|save|log|store|send|pass).*|"
            r"(?:write|save|log|store)[^;]*password",
            re.IGNORECASE,
        ),
        "Never store or transmit passwords in plaintext; hash with a KDF and "
        "log nothing about them.",
    ),
    (
        "insecure-tls",
        "MEDIUM",
        "TLS verification disabled",
        re.compile(r"verify\s*=\s*False|verify=False|ssl\._create_unverified_context"),
        "Keep TLS verification on; disable it only in throwaway test code.",
    ),
    (
        "debug-prod",
        "LOW",
        "Debug mode left enabled",
        re.compile(r"DEBUG\s*=\s*True|debug\s*=\s*True\b|FLASK_DEBUG\s*=\s*1"),
        "Disable debug mode for production deployments.",
    ),
    (
        "broad-except",
        "LOW",
        "Bare/overly broad exception handler",
        re.compile(r"except\s*:\s*$|except\s+Exception\s*:\s*$|except.*pass|except:\s+pass"),
        "Catch specific exceptions and handle them explicitly.",
    ),
]


def _resolve(path_raw: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(path_raw))))


def _is_text(raw: bytes) -> bool:
    """Best-effort check that bytes look like a text file."""
    if b"\x00" in raw[:4096]:
        return False
    try:
        raw.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _scan_file(path: Path) -> list[dict]:
    """Return findings [{line, severity, rule, label, snippet, fix}] for a file."""
    findings: list[dict] = []
    try:
        raw = path.read_bytes()
    except (OSError, PermissionError):
        return findings
    if not _is_text(raw) or len(raw) > _MAX_FILE_BYTES:
        return findings

    lines = raw.decode("utf-8-sig").splitlines()
    for rule_id, severity, label, pattern, fix in WEAKNESS_RULES:
        found_any = False
        for idx, line in enumerate(lines, start=1):
            if len(line) > 800 or not pattern.search(line):
                continue
            # Only report each rule once per nearby line to avoid spam.
            if found_any and any(
                f["rule"] == rule_id and abs(f["line"] - idx) < 8
                for f in findings
            ):
                continue
            found_any = True
            findings.append(
                {
                    "line": idx,
                    "severity": severity,
                    "rule": rule_id,
                    "label": label,
                    "snippet": line.strip()[:220],
                    "fix": fix,
                }
            )
    return findings


class AuditCodeTool(Tool):
    name = "audit_code"
    description = (
        "Security review of the user's own software. Scans a source file or "
        "a folder (recursively) for common weaknesses (hardcoded secrets, "
        "SQL/command injection, unsafe eval/pickle, path traversal, weak "
        "crypto, debug mode left on...). Returns findings with severity, "
        "line numbers and fix advice. Use suggest_patch to grab the exact "
        "lines, then apply_patch to fix."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File or folder to audit."},
        },
        "required": ["path"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        path = _resolve(self._arg(args, "path", ""))
        if not path.exists():
            raise ToolError(f"Path not found: {path}")

        files: list[Path] = []
        if path.is_file():
            if path.suffix.lower() in _SOURCE_EXTENSIONS:
                files = [path]
            else:
                raise ToolError(
                    f"{path} is not a supported source file "
                    f"(extensions: {sorted(_SOURCE_EXTENSIONS)[:8]}...)."
                )
        else:
            files = [
                p
                for p in path.rglob("*")
                if p.is_file()
                and p.suffix.lower() in _SOURCE_EXTENSIONS
                and not any(part in _IGNORED_DIRS for part in p.parts)
            ]
            files = files[:_MAX_FILES]

        all_findings = []
        for f in files:
            all_findings.extend(
                {"file": str(f), **finding} for finding in _scan_file(f)
            )

        if not all_findings:
            return f"Audit of {path}: no weakness patterns found in {len(files)} file(s)."

        counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for f in all_findings:
            counts[f["severity"]] += 1

        lines = [
            f"Audit of {path}: {len(all_findings)} potential issue(s) in "
            f"{len(files)} file(s) "
            f"(HIGH {counts['HIGH']} · MEDIUM {counts['MEDIUM']} · LOW {counts['LOW']})."
        ]
        for i, f in enumerate(all_findings, start=1):
            lines.append(
                f"#{i} [{f['severity']}] {f['rule']}: {f['label']}  "
                f"({Path(f['file']).name}:{f['line']})"
            )
            lines.append(f"   {f['snippet']}")
            lines.append(f"   fix: {f['fix']}")
        lines.append(
            "To fix issue #N, call suggest_patch(path, line) for the exact "
            "source, then apply_patch(path, old, new)."
        )
        return "\n".join(lines)


class SuggestPatchTool(Tool):
    name = "suggest_patch"
    description = (
        "Extracts the exact source lines around a finding (from audit_code) "
        "so a corrective patch can be written. Returns a window of context "
        "centred on the given line number."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The audited source file."},
            "line": {"type": "integer", "description": "1-based line number of the finding."},
        },
        "required": ["path", "line"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        path = _resolve(self._arg(args, "path", ""))
        line_num = int(self._arg(args, "line", 0) or 0)
        if not path.exists() or path.is_dir():
            raise ToolError(f"File not found: {path}")
        if line_num < 1:
            raise ToolError("Provide a positive 1-based line number.")
        try:
            raw = path.read_bytes()
        except (OSError, PermissionError) as exc:
            raise ToolError(f"Could not read {path}: {exc}") from exc
        if not _is_text(raw):
            raise ToolError(f"{path} does not appear to be a text file.")
        lines = raw.decode("utf-8-sig").splitlines()
        if line_num > len(lines):
            raise ToolError(
                f"Line {line_num} is past the end of {path} "
                f"(has {len(lines)} lines)."
            )

        start = max(0, line_num - _SNIPPET_LINES)
        end = min(len(lines), line_num + _SNIPPET_LINES)
        context = []
        for idx in range(start, end):
            marker = ">>>" if idx + 1 == line_num else "   "
            context.append(f"{marker} {idx + 1:5d} | {lines[idx]}")
        return (
            f"Context around {path}:{line_num}:\n"
            + "\n".join(context)
            + "\nProvide apply_patch arguments (old, new) covering the "
            "weakness exactly, preserving surrounding code."
        )


class ApplyPatchTool(Tool):
    name = "apply_patch"
    description = (
        "Applies an exact text replacement to a source file (the user's own "
        "software). Writes a \"<file>.bak\" backup of the original first. "
        "Requires the full old text to match exactly; new is what replaces it."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File to patch."},
            "old": {"type": "string", "description": "Exact existing text to replace."},
            "new": {"type": "string", "description": "Replacement text."},
        },
        "required": ["path", "old", "new"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        path = _resolve(self._arg(args, "path", ""))
        old = self._arg(args, "old", "") or ""
        new = self._arg(args, "new", "") or ""
        if not path.exists() or path.is_dir():
            raise ToolError(f"File not found: {path}")
        if not old.strip():
            raise ToolError("Provide the exact existing text to replace ('old').")
        if len(old) > _PATCH_MAX_CHARS or len(new) > _PATCH_MAX_CHARS:
            raise ToolError("Patch fragment too large.")

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
                "old text not found in the file. Use suggest_patch to view "
                "the exact current source and copy it verbatim."
            )
        if occurrences > 1:
            raise ToolError(
                f"old text matches {occurrences} times; include more context "
                "in 'old' so the patch is unambiguous."
            )

        patched = text.replace(old, new, 1)
        try:
            path.with_suffix(path.suffix + ".bak").write_bytes(raw)
        except (OSError, PermissionError) as exc:
            raise ToolError(f"Could not write backup: {exc}") from exc
        try:
            path.write_text(patched, encoding="utf-8")
        except (OSError, PermissionError) as exc:
            raise ToolError(f"Could not write patched file: {exc}") from exc

        return (
            f"Patched {path} ({occurrences} occurrence). "
            f"Backup saved to {path.with_suffix(path.suffix + '.bak')}."
        )


def register_codeaudit_tools(registry) -> None:
    """Register the Phase 24 code-security audit tools on a registry."""
    registry.register(AuditCodeTool())
    registry.register(SuggestPatchTool())
    registry.register(ApplyPatchTool())