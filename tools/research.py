"""
Research tool (Phase 26): JARVIS learns about a topic on its own.

Flow when the model calls `research_topic`:
    1. search the web (Tavily when TAVILY_API_KEY is set, otherwise the
       free DuckDuckGo HTML endpoint - so research works with no key),
    2. fetch the top results' pages and extract readable text,
    3. return a compact digest (title, url, key content per source) that
       the model turns into a real, sourced answer.

This is read-only internet access: JARVIS learns, it does not modify
anything on your machine.
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import requests

from config import settings
from tools.base import Tool, ToolError

_TAVILY_API = "https://api.tavily.com/search"
_DUCKDUCKGO_API = "https://html.duckduckgo.com/html/"
_SEARCH_TIMEOUT = 20
_FETCH_TIMEOUT = 15
_MAX_RESULTS = 5
_MAX_SNIPPET = 220
_MAX_PAGE_TEXT = 1500  # per source, enough for an LLM to reason over
_MAX_TOTAL = 8000  # cap the whole digest so it stays in the context window
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JARVIS-AI/1.0"


def _search(query: str, limit: int) -> list[dict[str, str]]:
    """Search the web; prefer Tavily, fall back to DuckDuckGo."""
    if settings.tavily_api_key:
        return _search_tavily(query, limit)
    return _search_duckduckgo(query, limit)


def _search_tavily(query: str, limit: int) -> list[dict[str, str]]:
    response = requests.post(
        _TAVILY_API,
        json={"api_key": settings.tavily_api_key, "query": query, "max_results": limit},
        timeout=_SEARCH_TIMEOUT,
    )
    response.raise_for_status()
    results = response.json().get("results") or []
    return [
        {
            "title": (r.get("title") or "Untitled").strip(),
            "url": (r.get("url") or "").strip(),
            "snippet": (r.get("content") or "").strip(),
        }
        for r in results[:limit]
    ]


def _clean_url(raw: str, lstrip: str = "//") -> str:
    """Normalise a DuckDuckGo href. It returns either the direct target or
    a redirect link `//duckduckgo.com/l/?uddg=<encoded real url>`; decode
    the `uddg` parameter when present so we fetch the actual page."""
    raw = (raw or "").strip()
    if raw.startswith("//duckduckgo.com/l/"):
        parsed = urlparse("https:" + raw if not raw.startswith("http") else raw)
        target = ""
        for name, values in parse_qs(parsed.query).items():
            if name.lower() == "uddg" and values:
                target = values[0]
        if target:
            return unquote(target)
    return raw.lstrip(lstrip)


def _search_duckduckgo(query: str, limit: int) -> list[dict[str, str]]:
    response = requests.get(
        _DUCKDUCKGO_API,
        params={"q": query},
        headers={"User-Agent": _USER_AGENT},
        timeout=_SEARCH_TIMEOUT,
    )
    response.raise_for_status()
    page = response.text
    found: list[dict[str, str]] = []
    pattern = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
        r"(.*?)(?=<a[^>]*class=\"result__a\"|$)",
        re.S,
    )
    for match in pattern.finditer(page):
        url, title_html, rest = match.groups()
        title = html.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
        snippet = ""
        snippet_match = re.search(
            r'class="result__snippet"[^>]*rel="nofollow"[^>]*>(.*?)</a>', rest, re.S
        )
        if not snippet_match:
            snippet_match = re.search(
                r'class="result__snippet"[^>]*>(.*?)</a>', rest, re.S
            )
        if snippet_match:
            snippet = html.unescape(
                re.sub(r"<[^>]+>", "", snippet_match.group(1))
            ).strip()
        if title and url:
            found.append(
                {"title": title, "url": _clean_url(url), "snippet": snippet}
            )
        if len(found) >= limit:
            break
    return found


def _fetch_text(url: str, limit: int = _MAX_PAGE_TEXT) -> str:
    """GET a page and return its readable text (safe, capped)."""
    if not url.startswith(("http://", "https://")):
        return ""
    response = requests.get(
        url,
        headers={"User-Agent": _USER_AGENT},
        timeout=_FETCH_TIMEOUT,
    )
    response.raise_for_status()
    raw = response.content
    if response.encoding:
        text = raw.decode(response.encoding, errors="replace")
    else:
        text = raw.decode("utf-8", errors="replace")
    return _html_to_text(text, limit)


def _html_to_text(page: str, limit: int) -> str:
    """Strip scripts/styles/tags and collapse whitespace into plain text."""
    page = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?i)<br\s*/?>", "\n", page)
    page = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)>", "\n", page)
    page = re.sub(r"<[^>]+>", " ", page)
    page = html.unescape(page)
    lines = [re.sub(r"\s+", " ", line).strip() for line in page.splitlines()]
    text = "\n".join(line for line in lines if line)
    if len(text) > limit:
        text = text[: limit].rstrip() + "..."
    return text


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) > limit:
        text = text[: limit].rstrip() + "..."
    return text


class ResearchTool(Tool):
    name = "research_topic"
    description = (
        "Researches a topic by searching the web and reading the top pages. "
        "Use this to learn about a subject, verify a fact, or answer "
        "anything current that you do not already know. Returns a digest of "
        "the best sources so you can give a real answer with citations."
    )
    parameters = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "The topic or question to research, e.g. 'latest advances in fusion energy'.",
            },
            "max_sources": {
                "type": "integer",
                "description": "How many sources to read (default 3, max 5).",
            },
        },
        "required": ["topic"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        topic = (self._arg(args, "topic", "") or "").strip()
        if not topic:
            raise ToolError("Provide a topic to research.")
        limit = max(1, min(int(self._arg(args, "max_sources", 3)), _MAX_RESULTS))

        try:
            results = _search(topic, limit)
        except requests.RequestException as exc:
            raise ToolError(f"Research search failed: {exc}") from exc
        if not results:
            return f"Research found no sources for {topic!r}."

        parts = [f"Research digest for {topic!r}:"]
        used = 0
        for result in results:
            snippet = _clip(result.get("snippet", ""), _MAX_SNIPPET)
            try:
                body = _fetch_text(result.get("url", ""))
            except requests.RequestException as exc:
                body = ""
            if not snippet and not body:
                continue
            entry = [f"## {result.get('title', 'Untitled')}", result.get("url", "")]
            if snippet:
                entry.append(f"Snippet: {snippet}")
            if body:
                body = _clip(body, _MAX_PAGE_TEXT)
                entry.append(f"Content: {body}")
            block = "\n".join(entry)
            if used + len(block) > _MAX_TOTAL:
                break
            parts.append(block)
            used += len(block)

        if len(parts) == 1:  # nothing usable was fetched
            return f"Research found sources for {topic!r} but could not read them."

        digest = "\n\n".join(parts)
        digest += (
            "\n\nUse the information above to answer the user's question "
            "accurately and mention the sources."
        )
        return digest


def register_research_tools(registry) -> None:
    """Register the Phase 26 research tool on a registry."""
    registry.register(ResearchTool())