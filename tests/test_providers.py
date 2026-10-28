from __future__ import annotations

import json

import pytest

from amadeus.providers import (
    CloudProvider,
    OllamaProvider,
    ProviderConnectionError,
    ProviderError,
)
from amadeus.providers.base import ProviderStatus


class FakeResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode("utf-8") for line in lines]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self) -> bytes:
        return b"".join(self._lines)

    def close(self) -> None:
        return None

    def __iter__(self):
        return iter(self._lines)


def test_ollama_streaming_collects_chunks(monkeypatch):
    payloads = [
        json.dumps({"message": {"content": "При"}}),
        json.dumps({"message": {"content": "вет"}, "done": False}),
        json.dumps({"message": {"content": "!"}, "done": True}),
    ]
    provider = OllamaProvider(model="test:1b")
    monkeypatch.setattr(
        provider, "_request", lambda path, payload=None, **kwargs: FakeResponse(payloads)
    )
    chunks: list[str] = []
    answer = provider.chat([{"role": "user", "content": "hi"}], stream=True, on_chunk=chunks.append)
    assert answer == "Привет!"
    assert chunks == ["При", "вет", "!"]


def test_ollama_non_streaming(monkeypatch):
    body = [json.dumps({"message": {"content": "ответ"}})]
    provider = OllamaProvider()
    monkeypatch.setattr(
        provider, "_request", lambda path, payload=None, **kwargs: FakeResponse(body)
    )
    assert provider.chat([{"role": "user", "content": "hi"}], stream=False) == "ответ"


def test_ollama_reports_error_in_stream(monkeypatch):
    provider = OllamaProvider()
    monkeypatch.setattr(
        provider,
        "_request",
        lambda path, payload=None, **kwargs: FakeResponse([json.dumps({"error": "boom"})]),
    )
    with pytest.raises(ProviderError, match="boom"):
        provider.chat([{"role": "user", "content": "hi"}])


def test_ollama_status_missing_model(monkeypatch):
    body = [json.dumps({"models": [{"name": "other:1b"}]})]
    provider = OllamaProvider(model="test:1b")
    monkeypatch.setattr(
        provider, "_request", lambda path, payload=None, **kwargs: FakeResponse(body)
    )
    status = provider.status()
    assert status.ok
    assert "test:1b" in status.detail


def test_cloud_without_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("AMADEUS_TEST_KEY", raising=False)
    provider = CloudProvider(api_key_env="AMADEUS_TEST_KEY")
    status = provider.status()
    assert not status.ok
    assert "AMADEUS_TEST_KEY" in status.detail
    with pytest.raises(ProviderError, match="AMADEUS_TEST_KEY"):
        provider.chat([{"role": "user", "content": "hi"}])


def test_cloud_streaming_parses_sse(monkeypatch):
    monkeypatch.setenv("AMADEUS_TEST_KEY", "secret")
    payloads = [
        'data: {"choices": [{"delta": {"content": "об"}}]}',
        "",
        'data: {"choices": [{"delta": {"content": "лако"}}]}',
        "data: [DONE]",
    ]
    provider = CloudProvider(api_key_env="AMADEUS_TEST_KEY")

    class FakeUrlopen:
        def __call__(self, request, timeout):
            assert request.full_url.endswith("/chat/completions")
            assert request.get_header("Authorization") == "Bearer secret"
            return FakeResponse(payloads)

    monkeypatch.setattr("urllib.request.urlopen", FakeUrlopen())
    chunks: list[str] = []
    answer = provider.chat([{"role": "user", "content": "hi"}], stream=True, on_chunk=chunks.append)
    assert answer == "облако"
    assert chunks == ["об", "лако"]


def test_cloud_http_error(monkeypatch):
    import urllib.error

    monkeypatch.setenv("AMADEUS_TEST_KEY", "secret")
    provider = CloudProvider(api_key_env="AMADEUS_TEST_KEY")

    def fail(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {}, FakeResponse(["bad key"])
        )

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(ProviderConnectionError, match="401"):
        provider.chat([{"role": "user", "content": "hi"}])


def test_status_dataclass_defaults():
    status = ProviderStatus(True, "ok")
    assert status.models == ()
