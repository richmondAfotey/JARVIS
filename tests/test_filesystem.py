"""Tests for the Phase 8 file-intelligence tools."""

from tools import build_default_registry
from tools.base import ToolError
from tools.filesystem import (
    CreateFolderTool,
    FileInfoTool,
    ListDirectoryTool,
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
    WriteProjectTool,
    _fmt_size,
)


def test_fmt_size():
    assert _fmt_size(0) == "0 B"
    assert _fmt_size(500) == "500 B"
    assert "KB" in _fmt_size(2048)


# -- list_directory --------------------------------------------------------

def test_list_directory(tmp_path):
    (tmp_path / "note.txt").write_text("hi")
    (tmp_path / "sub").mkdir()
    result = ListDirectoryTool().execute({"path": str(tmp_path)})
    assert "note.txt" in result
    assert "sub" in result


def test_list_directory_empty(tmp_path):
    result = ListDirectoryTool().execute({"path": str(tmp_path)})
    assert "empty" in result


def test_list_directory_missing_path():
    try:
        ListDirectoryTool().execute({"path": "C:\\Definitely_Not_A_Folder_XYZ"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


# -- read_file -------------------------------------------------------------

def test_read_file(tmp_path):
    target = tmp_path / "hello.txt"
    target.write_text("Hello world", encoding="utf-8")
    result = ReadFileTool().execute({"path": str(target)})
    assert "Hello world" in result


def test_read_file_missing():
    try:
        ReadFileTool().execute({"path": "C:\\No_Such_File_XYZ.txt"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


def test_read_file_rejects_directory(tmp_path):
    try:
        ReadFileTool().execute({"path": str(tmp_path)})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


def test_read_file_rejects_binary(tmp_path):
    target = tmp_path / "data.bin"
    target.write_bytes(b"\x00\x01\xff\xfe\xfd")
    try:
        ReadFileTool().execute({"path": str(target)})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


def test_read_file_truncates(tmp_path):
    target = tmp_path / "long.txt"
    target.write_text("a" * 10_000, encoding="utf-8")
    result = ReadFileTool().execute({"path": str(target), "max_chars": 50})
    assert len(result) < 200
    assert "truncated" in result


# -- search_files ----------------------------------------------------------

def test_search_files(tmp_path):
    (tmp_path / "report_final.txt").write_text("x")
    (tmp_path / "photo.jpg").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "annual_report.txt").write_text("x")
    result = SearchFilesTool().execute({"query": "report", "folder": str(tmp_path)})
    assert "report_final.txt" in result
    assert "annual_report.txt" in result
    assert "photo.jpg" not in result


def test_search_files_no_match(tmp_path):
    result = SearchFilesTool().execute({"query": "zzz", "folder": str(tmp_path)})
    assert "No files matching" in result


# -- file_info -------------------------------------------------------------

def test_file_info(tmp_path):
    target = tmp_path / "info.txt"
    target.write_text("hello", encoding="utf-8")
    result = FileInfoTool().execute({"path": str(target)})
    assert "file" in result
    assert "size" in result
    assert "modified" in result


# -- write_file ------------------------------------------------------------

def test_write_file(tmp_path):
    target = tmp_path / "out" / "nested" / "new.txt"
    result = WriteFileTool().execute({"path": str(target), "content": "line one\nline two"})
    assert "Wrote" in result
    assert target.read_text(encoding="utf-8") == "line one\nline two"


def test_write_file_overwrites(tmp_path):
    target = tmp_path / "over.txt"
    target.write_text("old", encoding="utf-8")
    WriteFileTool().execute({"path": str(target), "content": "new"})
    assert target.read_text(encoding="utf-8") == "new"


# -- create_folder ---------------------------------------------------------

def test_create_folder_nested(tmp_path):
    target = tmp_path / "a" / "b" / "c"
    result = CreateFolderTool().execute({"path": str(target)})
    assert "Created folder" in result
    assert target.is_dir()


def test_create_folder_idempotent(tmp_path):
    target = tmp_path / "exists"
    target.mkdir()
    result = CreateFolderTool().execute({"path": str(target)})
    assert "Created folder" in result
    assert target.is_dir()


def test_create_folder_blank():
    try:
        CreateFolderTool().execute({})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


# -- write_project ----------------------------------------------------------

def test_write_project_scaffolds_tree(tmp_path):
    root = tmp_path / "myapp"
    result = WriteProjectTool().execute(
        {
            "root": str(root),
            "files": [
                {"path": "src/main.py", "content": "print('hi')"},
                {"path": "src/utils/helper.py", "content": "def f():\n    return 1"},
                {"path": "README.md", "content": "# My App"},
            ],
        }
    )
    assert "3/3 file(s) written" in result
    assert (root / "src" / "main.py").read_text(encoding="utf-8") == "print('hi')"
    assert (root / "src" / "utils" / "helper.py").exists()
    assert (root / "README.md").read_text(encoding="utf-8") == "# My App"


def test_write_project_absolute_path_ignores_root(tmp_path):
    root = tmp_path / "elsewhere"
    absolute_target = tmp_path / "custom" / "x.txt"
    result = WriteProjectTool().execute(
        {
            "root": str(root),
            "files": [{"path": str(absolute_target), "content": "hi"}],
        }
    )
    assert "1/1 file(s) written" in result
    assert absolute_target.read_text(encoding="utf-8") == "hi"


def test_write_project_blank_root():
    try:
        WriteProjectTool().execute({"files": [{"path": "a.py", "content": ""}]})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


def test_write_project_no_files():
    try:
        WriteProjectTool().execute({"root": "C:/Temp/x", "files": []})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


def test_write_project_partial_failure_reports_issues(tmp_path):
    root = tmp_path / "p"
    result = WriteProjectTool().execute(
        {
            "root": str(root),
            "files": [
                {"path": "ok.txt", "content": "fine"},
                {"path": "", "content": "no path"},
            ],
        }
    )
    assert "1/2 file(s) written" in result
    assert "Issues" in result
    assert (root / "ok.txt").exists()


# -- registry integration --------------------------------------------------

def test_registry_has_filesystem_tools():
    registry = build_default_registry()
    for name in (
        "list_directory",
        "read_file",
        "search_files",
        "file_info",
        "write_file",
        "create_folder",
        "write_project",
    ):
        assert registry.get(name) is not None
