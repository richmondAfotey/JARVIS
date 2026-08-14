"""Tests for the Phase 34 ethical-hacking security-lab tools."""

import pytest

from config import settings
from system.security import is_sensitive
from tools import build_default_registry
from tools.base import ToolError
from tools.security_lab import (
    CveLookupTool,
    HashIdentifyTool,
    LearnSecurityTool,
    NetworkScanTool,
    PasswordAuditTool,
    WebReconTool,
    _identify_hash,
    load_security_notes,
    security_knowledge_block,
)


class FakeResponse:
    def __init__(self, status_code=200, headers=None, text="", payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


# -- hash_identify ---------------------------------------------------------

def test_hash_identify_common_algorithms():
    assert "MD5" in _identify_hash("d41d8cd98f00b204e9800998ecf8427e")
    assert "SHA-1" in _identify_hash("a" * 40)
    assert "SHA-256" in _identify_hash("a" * 64)
    assert "SHA-384" in _identify_hash("a" * 96)
    assert "SHA-512" in _identify_hash("a" * 128)


def test_hash_identify_modular_prefixes():
    assert _identify_hash("$2b$12$" + "x" * 50) == ["bcrypt"]
    assert any("sha512-crypt" in x for x in _identify_hash("$6$" + "x" * 60))
    assert any("sha256-crypt" in x for x in _identify_hash("$5$" + "x" * 50))
    assert any("WordPress" in x for x in _identify_hash("$P$" + "x" * 30))
    assert any("argon2" in x for x in _identify_hash("$argon2id$" + "x" * 60))


def test_hash_identify_unknown_returns_empty():
    assert _identify_hash("zzz-not-a-hash") == []


def test_hash_identify_tool_requires_arg():
    with pytest.raises(ToolError, match="hash"):
        HashIdentifyTool().execute({})


# -- network_scan ----------------------------------------------------------

def test_network_scan_requires_host():
    with pytest.raises(ToolError, match="host"):
        NetworkScanTool().execute({})


def test_network_scan_rejects_bad_port():
    with pytest.raises(ToolError):
        NetworkScanTool().execute({"host": "127.0.0.1", "ports": "not-a-port"})


def test_network_scan_single_host(monkeypatch):
    monkeypatch.setattr("tools.security_lab._ping_alive", lambda host: True)
    monkeypatch.setattr(
        "tools.security_lab._tcp_open",
        lambda host, port, timeout=1.0: port in (22, 80),
    )
    result = NetworkScanTool().execute({"host": "127.0.0.1", "ports": "22,80,443"})
    assert "alive" in result
    assert "22, 80" in result
    assert "443" not in result.split("open ports:")[1]


def test_network_scan_subnet_sweep(monkeypatch):
    monkeypatch.setattr("tools.security_lab._ping_alive", lambda host: True)
    monkeypatch.setattr("tools.security_lab._tcp_open", lambda *a, **k: False)
    result = NetworkScanTool().execute({"host": "127.0.0.0/30"})
    assert result.count("alive") == 2


# -- web_recon -------------------------------------------------------------

def test_web_recon_reports_missing_headers(monkeypatch):
    monkeypatch.setattr(
        WebReconTool, "_tls", staticmethod(lambda netloc: "TLS: n/a")
    )

    def fake_get(url, timeout=0, allow_redirects=True, headers=None):
        if "robots" in url:
            return FakeResponse(200, {}, "Disallow: /admin\n")
        return FakeResponse(200, {"server": "nginx", "content-type": "text/html"}, "")

    monkeypatch.setattr("tools.security_lab.requests.get", fake_get)
    result = WebReconTool().execute({"url": "https://example.com"})
    assert "status: 200" in result
    assert "nginx" in result
    assert "Strict-Transport-Security" in result  # reported missing
    assert "robots.txt disallows: /admin" in result


def test_web_recon_rejects_bad_scheme(monkeypatch):
    monkeypatch.setattr("tools.security_lab.requests.get", lambda *a, **k: FakeResponse())
    with pytest.raises(ToolError):
        WebReconTool().execute({"url": "ftp://example.com"})


# -- cve_lookup ------------------------------------------------------------

def test_cve_lookup_returns_matches(monkeypatch):
    payload = [
        {"id": "CVE-2021-23017", "cvss": 8.1, "summary": "Nginx resolver bug."},
        {"id": "CVE-2019-9511", "cvss": 7.5, "summary": "HTTP/2 data dribble."},
    ]
    monkeypatch.setattr(
        "tools.security_lab.requests.get",
        lambda url, timeout=0, headers=None: FakeResponse(200, payload=payload),
    )
    result = CveLookupTool().execute({"query": "nginx 1.18"})
    assert "CVE-2021-23017" in result
    assert "8.1" in result


def test_cve_lookup_empty(monkeypatch):
    monkeypatch.setattr(
        "tools.security_lab.requests.get",
        lambda url, timeout=0, headers=None: FakeResponse(200, payload=[]),
    )
    result = CveLookupTool().execute({"query": "nothing-here 99"})
    assert "No public CVEs" in result


# -- password_audit --------------------------------------------------------

def _hibp_fake(known_suffix: str | None):
    def fake_get(url, timeout=0, headers=None):
        lines = [f"{known_suffix}:7"] if known_suffix else []
        return FakeResponse(200, {}, "\n".join(lines))
    return fake_get


def test_password_audit_strength_and_no_echo(monkeypatch):
    import hashlib

    password = "CorrectHorseBatteryStaple!9"
    sha1 = hashlib.sha1(password.encode()).hexdigest().upper()
    monkeypatch.setattr(
        "tools.security_lab.requests.get", _hibp_fake(sha1[5:])
    )
    result = PasswordAuditTool().execute({"password": password})
    assert "length: 27" in result
    assert "strong" in result.lower()
    assert "found in 7 public breach" in result
    assert password not in result  # never echoed back


def test_password_audit_not_in_breaches(monkeypatch):
    monkeypatch.setattr("tools.security_lab.requests.get", _hibp_fake(None))
    result = PasswordAuditTool().execute({"password": "xY9#qW2!z"})
    assert "not found in known public breaches" in result


def test_password_audit_requires_password():
    with pytest.raises(ToolError):
        PasswordAuditTool().execute({})


# -- learn_security --------------------------------------------------------

@pytest.fixture(autouse=True)
def tmp_notes(tmp_path, monkeypatch):
    target = tmp_path / "security_notes.json"
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr("tools.security_lab._security_notes_file", lambda: target)
    if target.exists():
        target.unlink()
    yield target


def test_learn_security_persists(tmp_notes):
    result = LearnSecurityTool().execute(
        {"topic": "csrf", "notes": "Always use SameSite cookies plus a token."}
    )
    assert "Learned" in result
    notes = load_security_notes()
    assert "csrf" in notes
    assert "SameSite" in notes["csrf"]


def test_security_knowledge_block_includes_owasp_seed(tmp_notes):
    block = security_knowledge_block()
    assert "sql injection" in block
    assert "security knowledge" in block.lower()


def test_learn_security_requires_both_args(tmp_notes):
    with pytest.raises(ToolError):
        LearnSecurityTool().execute({"topic": "only-topic"})


# -- Registry + approval gating -------------------------------------------

def test_security_lab_registered():
    registry = build_default_registry()
    for name in ("network_scan", "web_recon", "cve_lookup", "hash_identify",
                 "password_audit", "learn_security"):
        assert registry.get(name) is not None, name


def test_scanning_and_audit_tools_require_approval():
    assert is_sensitive("network_scan")
    assert is_sensitive("web_recon")
    assert is_sensitive("password_audit")


def test_analysis_and_knowledge_tools_are_not_sensitive():
    assert not is_sensitive("cve_lookup")
    assert not is_sensitive("hash_identify")
    assert not is_sensitive("learn_security")
