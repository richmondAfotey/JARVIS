"""Tests for the self-update service (Phase 21).

Everything is tested with fakes - no network and no real packaged build.
`sys.frozen` is monkeypatched so `updater.current_exe()` behaves like a
packaged install.
"""

import json
import sys
from pathlib import Path

import pytest

import updates.updater as updater


# -- version -------------------------------------------------------------------

@pytest.mark.parametrize(
    "remote,current,expected",
    [
        ("1.1.0", "1.0.0", True),
        ("1.2.3", "1.2.3", False),
        ("0.9.0", "1.0.0", False),
        ("1.0.0-beta", "1.0.0", False),
        ("2.0.0", "1.9.9", True),
        ("", "1.0.0", False),
    ],
)
def test_is_newer(remote, current, expected):
    assert updater.is_newer(remote, current) is expected


def test_parse_version_ignores_non_numeric():
    assert updater.parse_version("v1.2.3") == (1, 2, 3)
    assert updater.parse_version("1.2.3-beta") == (1, 2, 3)


def test_current_version_reads_settings():
    assert isinstance(updater.current_version(), str)
    assert updater.current_version().count(".") >= 1


# -- location ------------------------------------------------------------------

def test_source_mode_has_no_current_exe(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert updater.current_exe() is None
    assert updater.can_self_update() is False


def test_frozen_mode_locates_exe(monkeypatch, tmp_path):
    fake_exe = tmp_path / "JARVIS AI.exe"
    fake_exe.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    assert updater.current_exe() == fake_exe
    assert updater.can_self_update() is True
    assert updater.staged_exe_path() == tmp_path / "JARVIS AI.exe.new.exe"


# -- manifest ------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _RequestError(f"HTTP {self.status_code}")

    def json(self):
        return json.loads(self._payload)


class _RequestError(Exception):
    pass


class _FakeRequests:
    """Stand-in for the `requests` module used inside updater functions."""

    RequestException = _RequestError  # module-level attr the updater catches

    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self._exc is not None:
            raise self._exc
        return self._response


def _patch_requests(monkeypatch, fake):
    monkeypatch.setitem(sys.modules, "requests", fake)


def test_fetch_manifest_ok(monkeypatch):
    fake = _FakeRequests(_FakeResponse(json.dumps({"version": "1.1.0", "url": "https://x/exe"})))
    _patch_requests(monkeypatch, fake)
    info = updater.fetch_manifest("https://example.com/manifest.json")
    assert info.version == "1.1.0"
    assert info.url == "https://x/exe"
    assert fake.calls[0][0] == "https://example.com/manifest.json"


def test_fetch_manifest_missing_fields(monkeypatch):
    fake = _FakeRequests(_FakeResponse(json.dumps({"notes": "nope"})))
    _patch_requests(monkeypatch, fake)
    with pytest.raises(updater.UpdateError, match="missing"):
        updater.fetch_manifest("https://example.com/manifest.json")


def test_fetch_manifest_bad_json(monkeypatch):
    fake = _FakeRequests(_FakeResponse("not json"))
    _patch_requests(monkeypatch, fake)
    with pytest.raises(updater.UpdateError, match="not valid JSON"):
        updater.fetch_manifest("https://example.com/manifest.json")


def test_fetch_manifest_network_error(monkeypatch):
    fake = _FakeRequests(exc=_RequestError("boom"))
    _patch_requests(monkeypatch, fake)
    with pytest.raises(updater.UpdateError, match="reach the update server"):
        updater.fetch_manifest("https://example.com/manifest.json")


def test_check_for_update_returns_none_when_current(monkeypatch):
    monkeypatch.setattr(updater, "current_version", lambda: "1.1.0")
    fake = _FakeRequests(_FakeResponse(json.dumps({"version": "1.1.0", "url": "https://x/exe"})))
    _patch_requests(monkeypatch, fake)
    assert updater.check_for_update("https://example.com/manifest.json") is None


def test_check_for_update_returns_newer(monkeypatch):
    monkeypatch.setattr(updater, "current_version", lambda: "1.0.0")
    fake = _FakeRequests(_FakeResponse(json.dumps({"version": "1.1.0", "url": "https://x/exe", "notes": "fixes"})))
    _patch_requests(monkeypatch, fake)
    info = updater.check_for_update("https://example.com/manifest.json")
    assert info is not None
    assert info.version == "1.1.0"
    assert info.notes == "fixes"


def test_check_for_update_requires_url(monkeypatch):
    monkeypatch.setattr(updater, "manifest_url", lambda: "")
    with pytest.raises(updater.UpdateError, match="not configured"):
        updater.check_for_update()


# -- download / stage ----------------------------------------------------------

def test_sha256_of(tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(b"hello world")
    assert updater.sha256_of(p) == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def test_stage_update_downloads_and_verifies(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "current_exe", lambda: tmp_path / "JARVIS AI.exe")
    payload = b"exe-bytes"
    import hashlib

    expected = hashlib.sha256(payload).hexdigest()

    class _StreamCtx:
        def __init__(self):
            self.raised = False

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            if self.raised:
                raise _RequestError("HTTP 404")

        def iter_content(self, chunk_size=0):
            yield payload

    class _StreamRequests(_FakeRequests):
        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return _StreamCtx()

    fake = _StreamRequests()
    _patch_requests(monkeypatch, fake)

    info = updater.UpdateInfo(version="1.1.0", url="https://x/exe", sha256=expected)
    staged = updater.stage_update(info)
    assert staged == tmp_path / "JARVIS AI.exe.new.exe"
    assert staged.read_bytes() == payload


def test_stage_update_rejects_bad_checksum(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "current_exe", lambda: tmp_path / "JARVIS AI.exe")

    class _StreamCtx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=0):
            yield b"tampered-bytes"

    class _StreamRequests(_FakeRequests):
        def get(self, url, **kwargs):
            return _StreamCtx()

    _patch_requests(monkeypatch, _StreamRequests())

    info = updater.UpdateInfo(version="1.1.0", url="https://x/exe", sha256="0" * 64)
    with pytest.raises(updater.UpdateError, match="integrity check"):
        updater.stage_update(info)
    assert not (tmp_path / "JARVIS AI.exe.new.exe").exists()


def test_stage_update_refuses_in_source_mode(monkeypatch):
    monkeypatch.setattr(updater, "current_exe", lambda: None)
    with pytest.raises(updater.UpdateError, match="running from source"):
        updater.stage_update(updater.UpdateInfo("1.1.0", "https://x/exe"))


# -- swap script ---------------------------------------------------------------

def test_swap_script_references_correct_paths(monkeypatch, tmp_path):
    fake_exe = tmp_path / "JARVIS AI.exe"
    monkeypatch.setattr(updater, "current_exe", lambda: fake_exe)
    script = updater._swap_script()
    assert '"' + str(fake_exe) + '"' in script
    assert str(fake_exe.with_name("JARVIS AI.exe.new.exe")) in script
    assert "start" in script
    assert "move" in script


def test_apply_update_requires_a_staged_file(monkeypatch, tmp_path):
    fake_exe = tmp_path / "JARVIS AI.exe"
    fake_exe.touch()
    monkeypatch.setattr(updater, "current_exe", lambda: fake_exe)
    with pytest.raises(updater.UpdateError, match="No staged update"):
        updater.apply_update()


def test_apply_update_writes_script(monkeypatch, tmp_path, capsys):
    fake_exe = tmp_path / "JARVIS AI.exe"
    fake_exe.touch()
    staged = tmp_path / "JARVIS AI.exe.new.exe"
    staged.touch()
    monkeypatch.setattr(updater, "current_exe", lambda: fake_exe)

    launched = []

    class _Popen:
        def __init__(self, *a, **kw):
            launched.append((a, kw))

    monkeypatch.setattr(updater.subprocess, "Popen", _Popen)
    script = updater.apply_update()
    assert script == tmp_path / "_apply_update.cmd"
    assert script.exists()
    assert launched, "the swap script should have been launched"


# -- cleanup -------------------------------------------------------------------

def test_cleanup_removes_backup(monkeypatch, tmp_path):
    fake_exe = tmp_path / "JARVIS AI.exe"
    backup = tmp_path / "JARVIS AI.exe.old.exe"
    fake_exe.touch()
    backup.touch()
    monkeypatch.setattr(updater, "current_exe", lambda: fake_exe)
    updater.cleanup_after_launch()
    assert not backup.exists()
    assert fake_exe.exists()


def test_cleanup_noop_in_source_mode(monkeypatch):
    monkeypatch.setattr(updater, "current_exe", lambda: None)
    updater.cleanup_after_launch()  # should not raise