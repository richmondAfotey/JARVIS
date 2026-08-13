"""
Web information tools (Phase 10).

Let JARVIS answer questions about the outside world:
    * web_search  - live web results via Tavily (title, url, snippet)
    * get_weather - current conditions for a city via OpenWeatherMap

API keys (no credit card needed):
    * TAVILY_API_KEY          -> https://tavily.com       (free: ~1000 searches/mo)
    * OPENWEATHERMAP_API_KEY  -> https://openweathermap.org/api (free plan)

Both tools fail with a clear message when their key is missing so the AI
never pretends it searched or fetched weather it did not.
"""

from __future__ import annotations

from typing import Any

import requests

from config import settings
from tools.base import Tool, ToolError

_TAVILY_API = "https://api.tavily.com/search"
_WEATHER_API = "https://api.openweathermap.org/data/2.5/weather"
_MAX_SNIPPET = 300
_MAX_RESULTS = 5
_TIMEOUT = 20


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Searches the web and returns the top results (title, url, short "
        "snippet). Use for current events, news, facts, prices or anything "
        "you do not already know."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query, e.g. 'latest iPhone release date'.",
            }
        },
        "required": ["query"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        query = (self._arg(args, "query", "") or "").strip()
        if not query:
            raise ToolError("Provide a query to search for.")
        key = settings.tavily_api_key
        if not key:
            raise ToolError(
                "Web search is not configured: add TAVILY_API_KEY to .env and restart."
            )
        try:
            response = requests.post(
                _TAVILY_API,
                json={"api_key": key, "query": query, "max_results": _MAX_RESULTS},
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise ToolError(f"Web search failed: {exc}") from exc

        results = data.get("results") or []
        if not results:
            return f"No web results for {query!r}."
        lines = [f"Top results for {query!r}:"]
        for result in results[: _MAX_RESULTS]:
            title = (result.get("title") or "Untitled").strip()
            url = (result.get("url") or "").strip()
            snippet = (result.get("content") or "").strip()
            if len(snippet) > _MAX_SNIPPET:
                snippet = snippet[: _MAX_SNIPPET].rstrip() + "..."
            lines.append(f"- {title}\n  {url}\n  {snippet}" if snippet else f"- {title}\n  {url}")
        return "\n\n".join(lines)


class GetWeatherTool(Tool):
    name = "get_weather"
    description = (
        "Returns the current weather in a city: temperature, conditions, "
        "humidity and wind speed."
    )
    parameters = {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name, optionally with country code, e.g. 'Accra' or 'London,UK'.",
            }
        },
        "required": ["city"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        city = (self._arg(args, "city", "") or "").strip()
        if not city:
            raise ToolError("Provide a city name.")
        key = settings.openweathermap_api_key
        if not key:
            raise ToolError(
                "Weather is not configured: add OPENWEATHERMAP_API_KEY to .env and restart."
            )
        try:
            response = requests.get(
                _WEATHER_API,
                params={"q": city, "appid": key, "units": "metric"},
                timeout=_TIMEOUT,
            )
            if response.status_code == 404:
                raise ToolError(f"City not found: {city}")
            if response.status_code == 401:
                raise ToolError(
                    "Weather is not configured correctly: OpenWeatherMap rejected "
                    "the OPENWEATHERMAP_API_KEY. Verify the key in .env is exact and "
                    "that your account is activated (click the link in the "
                    "OpenWeatherMap signup email)."
                )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            if isinstance(exc, ToolError):
                raise
            raise ToolError(f"Weather lookup failed: {exc}") from exc

        name = data.get("name") or city
        main = data.get("main") or {}
        weather = (data.get("weather") or [{}])[0]
        wind = data.get("wind") or {}
        temp = main.get("temp")
        desc = (weather.get("description") or "unknown").strip()
        humidity = main.get("humidity")
        wind_speed = wind.get("speed")
        parts = [name, f"{temp:.1f} C" if temp is not None else "no temperature data", desc]
        if humidity is not None:
            parts.append(f"humidity {humidity}%")
        if wind_speed is not None:
            parts.append(f"wind {wind_speed:.1f} m/s")
        return ", ".join(parts)


def register_web_tools(registry) -> None:
    """Register the Phase 10 web-information tools on a registry."""
    registry.register(WebSearchTool())
    registry.register(GetWeatherTool())