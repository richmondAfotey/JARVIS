"""Tests for the Phase 10 web-information tools (network calls mocked)."""

import requests

from tools import build_default_registry
from tools.base import ToolError
from tools.web import GetWeatherTool, WebSearchTool

PAYLOAD_KEY = "api_key"


def _fake_post(*, payload=None, exc=None):
    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    def fake_post(url, json=None, timeout=None):
        assert url
        assert json[PAYLOAD_KEY]
        if exc:
            raise exc
        return FakeResponse(payload)

    return fake_post


def _fake_get(*, payload=None, status=200, exc=None):
    class FakeResponse:
        _status = status

        @property
        def status_code(self):
            return self._status

        def raise_for_status(self):
            if self._status >= 400:
                raise requests.HTTPError(f"HTTP {self._status}")

        def json(self):
            return payload

    def fake_get(url, params=None, timeout=None):
        assert url
        assert params.get("q")
        assert params.get("appid")
        if exc:
            raise exc
        return FakeResponse()

    return fake_get


# -- web_search ------------------------------------------------------------

def test_web_search_formats_results(monkeypatch):
    results = [
        {"title": "Sky News", "url": "https://sky.com", "content": "Headline about rain"},
        {"title": "BBC", "url": "https://bbc.com", "content": "More news"},
    ]
    monkeypatch.setattr("tools.web.requests.post", _fake_post(payload={"results": results}))
    monkeypatch.setattr("tools.web.settings.tavily_api_key", "test-key")
    out = WebSearchTool().execute({"query": "weather in London"})
    assert "Sky News" in out
    assert "https://sky.com" in out
    assert "Headline about rain" in out
    assert "BBC" in out


def test_web_search_truncates_long_snippets(monkeypatch):
    results = [{"title": "T", "url": "https://x.com", "content": "x" * 5000}]
    monkeypatch.setattr("tools.web.requests.post", _fake_post(payload={"results": results}))
    monkeypatch.setattr("tools.web.settings.tavily_api_key", "test-key")
    out = WebSearchTool().execute({"query": "q"})
    assert "..." in out
    assert len(out) < 1000


def test_web_search_no_results(monkeypatch):
    monkeypatch.setattr("tools.web.requests.post", _fake_post(payload={"results": []}))
    monkeypatch.setattr("tools.web.settings.tavily_api_key", "test-key")
    out = WebSearchTool().execute({"query": "zzz"})
    assert "No web results" in out


def test_web_search_missing_key(monkeypatch):
    monkeypatch.setattr("tools.web.settings.tavily_api_key", "")
    try:
        WebSearchTool().execute({"query": "q"})
    except ToolError as exc:
        assert "TAVILY_API_KEY" in str(exc)
        return
    raise AssertionError("Expected ToolError")


def test_web_search_blank_query():
    try:
        WebSearchTool().execute({})
    except ToolError as exc:
        assert "query" in str(exc)
        return
    raise AssertionError("Expected ToolError")


def test_web_search_network_error(monkeypatch):
    monkeypatch.setattr(
        "tools.web.requests.post",
        _fake_post(exc=requests.ConnectionError("boom")),
    )
    monkeypatch.setattr("tools.web.settings.tavily_api_key", "test-key")
    try:
        WebSearchTool().execute({"query": "q"})
    except ToolError as exc:
        assert "Web search failed" in str(exc)
        return
    raise AssertionError("Expected ToolError")


# -- get_weather -----------------------------------------------------------

def test_get_weather_formats(monkeypatch):
    payload = {
        "name": "Accra",
        "main": {"temp": 27.6, "humidity": 74},
        "weather": [{"description": "light rain"}],
        "wind": {"speed": 4.2},
    }
    monkeypatch.setattr("tools.web.requests.get", _fake_get(payload=payload))
    monkeypatch.setattr("tools.web.settings.openweathermap_api_key", "test-key")
    out = GetWeatherTool().execute({"city": "Accra"})
    assert "Accra" in out
    assert "27.6" in out
    assert "light rain" in out
    assert "74%" in out


def test_get_weather_missing_key(monkeypatch):
    monkeypatch.setattr("tools.web.settings.openweathermap_api_key", "")
    try:
        GetWeatherTool().execute({"city": "Accra"})
    except ToolError as exc:
        assert "OPENWEATHERMAP_API_KEY" in str(exc)
        return
    raise AssertionError("Expected ToolError")


def test_get_weather_city_not_found(monkeypatch):
    monkeypatch.setattr(
        "tools.web.requests.get",
        _fake_get(payload={}, status=404),
    )
    monkeypatch.setattr("tools.web.settings.openweathermap_api_key", "test-key")
    try:
        GetWeatherTool().execute({"city": "Atlantis"})
    except ToolError as exc:
        assert "City not found" in str(exc)
        return
    raise AssertionError("Expected ToolError")


def test_get_weather_rejected_key(monkeypatch):
    monkeypatch.setattr(
        "tools.web.requests.get",
        _fake_get(payload={}, status=401),
    )
    monkeypatch.setattr("tools.web.settings.openweathermap_api_key", "bad-key")
    try:
        GetWeatherTool().execute({"city": "Accra"})
    except ToolError as exc:
        assert "OPENWEATHERMAP_API_KEY" in str(exc)
        return
    raise AssertionError("Expected ToolError")


def test_get_weather_blank_city():
    try:
        GetWeatherTool().execute({})
    except ToolError as exc:
        assert "city" in str(exc)
        return
    raise AssertionError("Expected ToolError")


# -- registry integration --------------------------------------------------

def test_registry_has_web_tools():
    registry = build_default_registry()
    for name in ("web_search", "get_weather"):
        assert registry.get(name) is not None