"""Tests for the Phase 26 research tool (network calls mocked)."""

import requests

from tools import build_default_registry
from tools.base import ToolError
from tools.research import (
    ResearchTool,
    _fetch_text,
    _html_to_text,
    _search,
    _search_duckduckgo,
    _search_tavily,
)


# -- search functions -------------------------------------------------------

def test_search_tavily_formats_results(monkeypatch):
    payload = {
        "results": [
            {"title": "Fusion News", "url": "https://fusion.org", "content": "Breakthrough"},
            {"title": "Second", "url": "https://second.org", "content": "More"},
        ]
    }
    called = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    def fake_post(url, json=None, timeout=None):
        called["key"] = json["api_key"]
        return FakeResponse()

    monkeypatch.setattr("tools.research.requests.post", fake_post)
    monkeypatch.setattr("tools.research.settings.tavily_api_key", "tkey")
    out = _search_tavily("fusion", 2)
    assert called["key"] == "tkey"
    assert out[0]["title"] == "Fusion News"
    assert out[0]["url"] == "https://fusion.org"


def test_search_duckduckgo_parses_results(monkeypatch):
    page = (
        '<div><a class="result__a" href="//example.com/a">Title A</a>'
        '<a class="result__snippet">Snippet A</a></div>'
        '<div><a class="result__a" href="//example.com/b">Title B</a>'
        '<a class="result__snippet">Snippet B</a></div>'
    )

    class FakeResponse:
        def raise_for_status(self):
            pass

        @property
        def text(self):
            return page

    def fake_get(url, params=None, headers=None, timeout=None):
        assert params["q"]
        return FakeResponse()

    monkeypatch.setattr("tools.research.requests.get", fake_get)
    out = _search_duckduckgo("query", 3)
    assert out[0]["title"] == "Title A"
    assert out[0]["url"].endswith("example.com/a")
    assert len(out) == 2


def test_search_falls_back_to_duckduckgo_when_no_key(monkeypatch):
    called = {}
    monkeypatch.setattr("tools.research.settings.tavily_api_key", "")

    class FakeResponse:
        def raise_for_status(self):
            pass

        @property
        def text(self):
            return ""

    def fake_get(url, params=None, headers=None, timeout=None):
        called["url"] = url
        return FakeResponse()

    monkeypatch.setattr("tools.research.requests.get", fake_get)
    _search("topic", 3)
    assert "duckduckgo" in called["url"]


# -- text extraction --------------------------------------------------------

def test_html_to_text_strips_markup():
    out = _html_to_text("<html><script>var x=1;</script><h1>Hello</h1><p>World<br>line</p></html>", 5000)
    assert "Hello" in out
    assert "World" in out
    assert "script" not in out.lower()


def test_html_to_text_caps_length():
    out = _html_to_text("<p>" + "x" * 9000 + "</p>", 500)
    assert len(out) <= 520


def test_fetch_text_skips_non_http():
    assert _fetch_text("file:///etc/passwd") == ""


def test_fetch_text_reads_page(monkeypatch):
    class FakeResponse:
        @property
        def encoding(self):
            return "utf-8"

        @property
        def content(self):
            return b"<html><p>Actual researched content here</p></html>"

        def raise_for_status(self):
            pass

    def fake_get(url, headers=None, timeout=None):
        assert url.startswith("https://")
        return FakeResponse()

    monkeypatch.setattr("tools.research.requests.get", fake_get)
    out = _fetch_text("https://example.com/page")
    assert "Actual researched content" in out


# -- ResearchTool -----------------------------------------------------------

def test_research_tool_end_to_end(monkeypatch):
    results = [
        {"title": "Src", "url": "https://example.com/a", "snippet": "A snippet"},
    ]

    def fake_search(query, limit):
        assert query == "fusion energy"
        return results

    class FakePage:
        @property
        def encoding(self):
            return "utf-8"

        @property
        def content(self):
            return b"<html><p>Deep researched body text.</p></html>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr("tools.research._search", fake_search)
    monkeypatch.setattr("tools.research.requests.get", lambda *a, **k: FakePage())

    out = ResearchTool().execute({"topic": "fusion energy"})
    assert "Research digest for 'fusion energy':" in out
    assert "https://example.com/a" in out
    assert "Deep researched body text" in out
    assert "mention the sources" in out


def test_research_tool_blank_topic():
    try:
        ResearchTool().execute({})
    except ToolError as exc:
        assert "topic" in str(exc)
        return
    raise AssertionError("Expected ToolError")


def test_research_tool_search_error(monkeypatch):
    def fake_search(query, limit):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr("tools.research._search", fake_search)
    try:
        ResearchTool().execute({"topic": "anything"})
    except ToolError as exc:
        assert "Research search failed" in str(exc)
        return
    raise AssertionError("Expected ToolError")


def test_research_tool_no_results(monkeypatch):
    monkeypatch.setattr("tools.research._search", lambda q, l: [])
    out = ResearchTool().execute({"topic": "zzz"})
    assert "no sources" in out


# -- registry integration --------------------------------------------------

def test_registry_has_research_tool():
    registry = build_default_registry()
    assert registry.get("research_topic") is not None
