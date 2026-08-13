"""Tests for the Phase 24 code security audit + patch tools."""

from pathlib import Path

import pytest

from tools import build_default_registry
from tools.base import ToolError
from tools.codeaudit import (
    WEAKNESS_RULES,
    ApplyPatchTool,
    AuditCodeTool,
    SuggestPatchTool,
)

VULNERABLE = '''import os
import subprocess
import hashlib
import pickle

API_KEY = "sk-abc123def456ghi789jkl012"

def query(stmt):
    cursor = db.execute(f"SELECT * FROM users WHERE name = {stmt}")
    # param placeholders are safer:
    ok = db.execute("SELECT * FROM users WHERE id = ?", (id,))
    return cursor

def run_cmd(cmd):
    os.system(cmd)
    subprocess.run(cmd, shell=True)

def run_code(code):
    return eval(code)

def load_data(blob):
    return pickle.loads(blob)

def open_file(name):
    f = open("files/" + name + "/../config.txt")
    return f

def store_pass(p):
    print("password stored:", p)

def debug_mode():
    DEBUG = True
    return DEBUG
'''


def _write(tmp_path, content=VULNERABLE) -> Path:
    target = tmp_path / "app.py"
    target.write_text(content, encoding="utf-8")
    return target


def test_audit_finds_multiple_issues(tmp_path):
    target = _write(tmp_path)
    out = AuditCodeTool().execute({"path": str(target)})
    assert "potential issue(s)" in out
    for rule in ("hardcoded-secret", "sql-injection", "command-injection",
                 "unsafe-eval", "unsafe-pickle", "path-traversal",
                 "debug-prod"):
        assert rule in out, f"expected rule {rule} in audit output"
    assert "HIGH" in out


def test_audit_folder_recursively(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "util.py").write_text(
        'TOKEN = "averylongsecrettokenvalue123"', encoding="utf-8"
    )
    out = AuditCodeTool().execute({"path": str(tmp_path)})
    assert "hardcoded-secret" in out


def test_audit_ignores_venv_and_supports_binary(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "dep.py").write_text(
        'PASSWORD = "shouldnotbeaudited123456789"', encoding="utf-8"
    )
    (tmp_path / "img.bin").write_bytes(b"\x00\x01\x02\xff")
    audit = AuditCodeTool().execute({"path": str(tmp_path)})
    assert "shouldnotbeaudited" not in audit  # .venv skipped


def test_audit_missing_path_raises(tmp_path):
    try:
        AuditCodeTool().execute({"path": str(tmp_path / "nope")})
    except ToolError:
        return
    raise AssertionError("Expected ToolError for missing path")


def test_audit_clean_file_reports_none(tmp_path):
    target = tmp_path / "clean.py"
    target.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    out = AuditCodeTool().execute({"path": str(target)})
    assert "no weakness patterns" in out


def test_audit_rejects_unsupported_extension(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("plain text", encoding="utf-8")
    try:
        AuditCodeTool().execute({"path": str(target)})
    except ToolError:
        return
    raise AssertionError("Expected ToolError for unsupported extension")


def test_suggest_patch_returns_context(tmp_path):
    target = _write(tmp_path)
    out = SuggestPatchTool().execute({"path": str(target), "line": 7})
    assert ">>>" in out  # the marker on the target line
    assert "API_KEY" in out
    assert "app.py:" in out


def test_suggest_patch_bad_line(tmp_path):
    target = _write(tmp_path)
    for bad in (0, -4, 100000):
        try:
            SuggestPatchTool().execute({"path": str(target), "line": bad})
        except ToolError:
            continue
        raise AssertionError(f"Expected ToolError for line {bad}")


def test_apply_patch_replace_and_backup(tmp_path):
    target = _write(tmp_path)
    out = ApplyPatchTool().execute(
        {
            "path": str(target),
            "old": 'API_KEY = "sk-abc123def456ghi789jkl012"',
            "new": "API_KEY = os.getenv(\"API_KEY\", \"\")",
        }
    )
    assert "Patched" in out
    assert ".bak" in out
    assert "os.getenv" in target.read_text(encoding="utf-8-sig")
    backup = target.with_suffix(".py.bak")
    assert backup.exists()
    assert "sk-abc123def456ghi789jkl012" in backup.read_text(encoding="utf-8-sig")


def test_apply_patch_old_not_found(tmp_path):
    target = _write(tmp_path)
    try:
        ApplyPatchTool().execute({"path": str(target), "old": "zzz missing", "new": "x"})
    except ToolError as exc:
        assert "not found" in str(exc)
        return
    raise AssertionError("Expected ToolError")


def test_apply_patch_ambiguous_old_requires_context(tmp_path):
    target = _write(tmp_path)
    try:
        # "return cursor" only appears once, but use a fragment present twice:
        ApplyPatchTool().execute({"path": str(target), "old": "return", "new": "pass"})
    except ToolError as exc:
        assert "matches" in str(exc)
        return
    raise AssertionError("Expected ToolError for ambiguous patch")


def test_apply_patch_missing_path(tmp_path):
    try:
        ApplyPatchTool().execute({"path": str(tmp_path / "gone.py"), "old": "a", "new": "b"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError for missing file")


def test_apply_patch_rejects_empty_old(tmp_path):
    target = _write(tmp_path)
    try:
        ApplyPatchTool().execute({"path": str(target), "old": "  ", "new": "b"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError for empty old text")


def test_apply_patch_binary_file_rejected(tmp_path):
    target = tmp_path / "blob.bin"
    target.write_bytes(b"\x00\x01\x02")
    try:
        ApplyPatchTool().execute({"path": str(target), "old": "x", "new": "y"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError for binary file")


def test_rules_are_well_formed():
    for rule_id, severity, label, pattern, fix in WEAKNESS_RULES:
        assert rule_id and label and fix
        assert severity in ("HIGH", "MEDIUM", "LOW")
        assert pattern.pattern  # compiled regex present


def test_security_gates_apply_patch(monkeypatch):
    from system.security import SENSITIVE_TOOLS

    assert "apply_patch" in SENSITIVE_TOOLS
    # read-only review tools should NOT be approval-gated
    assert "audit_code" not in SENSITIVE_TOOLS
    assert "suggest_patch" not in SENSITIVE_TOOLS


def test_registry_has_codeaudit_tools():
    registry = build_default_registry()
    for name in ("audit_code", "suggest_patch", "apply_patch"):
        assert registry.get(name) is not None
        assert name in registry.names()