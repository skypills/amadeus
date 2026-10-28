from __future__ import annotations

import urllib.error
from urllib.parse import parse_qs

import pytest

from amadeus.tools import (
    SearchResult,
    WebSearch,
    WebSearchError,
    build_registry,
    parse_ddg_html,
    render_results,
    render_sources,
    web_search_tool,
)

HTML = """
<html><body>
<div class="result results_links">
  <h2><a rel="nofollow" class="result__a"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&amp;rut=abc">
     Example &amp; Title</a></h2>
  <a class="result__snippet" href="x">Snippet with <b>bold</b> text</a>
  <span class="result__timestamp">2024-01-02</span>
</div>
<div class="result">
  <a class="result__a" href="https://direct.example.org/x">Direct result</a>
  <div class="result__snippet">Direct snippet</div>
</div>
<a class="result__a" href="https://example.com/page">Duplicate URL</a>
<a class="result__a" href="javascript:alert(1)">Bad URL</a>
</body></html>
"""


class Headers:
    def get_content_charset(self):
        return "utf-8"


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.headers = Headers()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, size: int = -1) -> bytes:
        return self.body[:size] if size >= 0 else self.body


def test_parse_ddg_html_resolves_and_deduplicates():
    results = parse_ddg_html(HTML, limit=5)
    assert [item.url for item in results] == [
        "https://example.com/page",
        "https://direct.example.org/x",
    ]
    assert results[0].title == "Example & Title"
    assert "bold" in results[0].snippet
    assert results[0].date == "2024-01-02"
    assert results[1].date == ""


def test_parse_limit():
    results = parse_ddg_html(HTML, limit=1)
    assert len(results) == 1


def test_web_search_posts_query(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["data"] = request.data
        captured["timeout"] = timeout
        return FakeResponse(HTML.encode("utf-8"))

    monkeypatch.setattr("amadeus.tools.web_search.urlopen", fake_urlopen)
    search = WebSearch(timeout=3, max_results=2, use_library=False)
    results = search.search("CachyOS Hyprland")
    assert len(results) == 2
    assert captured["method"] == "POST"
    assert parse_qs(captured["data"].decode())["q"] == ["CachyOS Hyprland"]
    assert captured["timeout"] == 3


def test_web_search_http_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many", {}, None)

    monkeypatch.setattr("amadeus.tools.web_search.urlopen", fake_urlopen)
    with pytest.raises(WebSearchError, match="HTTP 429"):
        WebSearch(use_library=False).search("test")


def test_web_search_rejects_empty_and_unknown_provider():
    with pytest.raises(WebSearchError, match="пуст"):
        WebSearch(use_library=False).search("   ")
    with pytest.raises(WebSearchError, match="провайдер"):
        WebSearch(provider="other", use_library=False).search("test")


def test_render_contains_real_urls_and_untrusted_note():
    results = [SearchResult("T", "https://example.com", "S", "2024")]
    rendered = render_results(results)
    assert "https://example.com" in rendered
    assert "НЕДОВЕРЕННЫЕ" in rendered
    assert "https://example.com" in render_sources(results)


def test_web_search_uses_ddgs_library(monkeypatch):
    class FakeDDGS:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def text(self, query, max_results, backend):
            return [
                {
                    "title": "Результат",
                    "href": "https://example.net/page",
                    "body": "Описание",
                    "date": "2025-01-01",
                }
            ]

    monkeypatch.setattr("amadeus.tools.web_search.DDGS", FakeDDGS)
    results = WebSearch(use_library=True).search("запрос")
    assert results[0].url == "https://example.net/page"
    assert results[0].snippet == "Описание"


def test_web_search_tool_returns_sources(monkeypatch):
    def fake_search(self, query):
        assert query == "запрос"
        return [SearchResult("Заголовок", "https://example.org/a", "Выдержка", "")]

    monkeypatch.setattr("amadeus.tools.web_search.WebSearch.search", fake_search)
    tool = web_search_tool()
    result = tool.handler({"query": "запрос"})
    assert "https://example.org/a" in result
    assert "Заголовок" in result


def test_web_search_is_not_exposed_to_model_by_default(settings):
    registry = build_registry(settings)
    names = [tool.name for tool in registry.model_tools()]
    assert "web_search" not in names


def test_web_search_can_be_exposed_to_model(settings):
    settings.set("search.allow_model_calls", True)
    registry = build_registry(settings)
    names = [tool.name for tool in registry.model_tools()]
    assert "web_search" in names
