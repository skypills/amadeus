from __future__ import annotations

import json
import urllib.error

import pytest

from amadeus.diagnostics import (
    DiagnosticsError,
    format_benchmark,
    run_benchmark,
    save_benchmark,
)
from amadeus.logging_setup import configure_logging
from amadeus.storage import paths


class FakeResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode("utf-8") for line in lines]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, size: int = -1) -> bytes:
        data = b"".join(self._lines)
        return data[:size] if size >= 0 else data

    def close(self) -> None:
        return None

    def __iter__(self):
        return iter(self._lines)


def test_run_benchmark_measures_tokens(monkeypatch, settings):
    lines = [
        json.dumps({"message": {"content": "Ответ"}}),
        json.dumps({"message": {"content": " модели"}}),
        json.dumps(
            {
                "message": {"content": ""},
                "done": True,
                "eval_count": 10,
                "prompt_eval_count": 5,
                "eval_duration": 2_000_000_000,
            }
        ),
    ]
    monkeypatch.setattr(
        "amadeus.diagnostics.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(lines),
    )
    result = run_benchmark(settings, prompt="тест", max_tokens=16)
    assert result.model == settings.get("ollama.model")
    assert result.generated_tokens == 10
    assert result.prompt_tokens == 5
    assert result.tokens_per_second == 5.0
    assert result.first_token_ms >= 0
    assert result.total_ms >= 0
    text = format_benchmark(result)
    assert "ток/с" in text
    assert "Модель:" in text


def test_save_benchmark(monkeypatch, settings, tmp_path):
    lines = [
        json.dumps({"message": {"content": "x"}}),
        json.dumps({"message": {"content": ""}, "done": True, "eval_count": 1}),
    ]
    monkeypatch.setattr(
        "amadeus.diagnostics.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(lines),
    )
    result = run_benchmark(settings, prompt="x")
    target = save_benchmark(result, tmp_path / "bench" / "report.json")
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["model"] == result.model
    assert target.exists()


def test_benchmark_http_error(monkeypatch, settings):
    def fail(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 500, "Server Error", {}, FakeResponse(["boom"])
        )

    monkeypatch.setattr("amadeus.diagnostics.urllib.request.urlopen", fail)
    with pytest.raises(DiagnosticsError, match="HTTP 500"):
        run_benchmark(settings)


def test_diagnose_smoke(settings):
    from amadeus.diagnostics import diagnose

    settings.set("ollama.base_url", "http://127.0.0.1:9", save=False)
    text = diagnose(settings)
    assert "Amadeus:" in text
    assert "Python:" in text
    assert "Провайдер:" in text
    assert "Голос:" in text
    assert "Данные:" in text


def test_logging_writes_safe_file(settings):
    logger = configure_logging()
    logger.info("test-marker")
    for handler in logger.handlers:
        handler.flush()
    log_path = paths.state_dir() / "amadeus.log"
    assert log_path.exists()
    text = log_path.read_text(encoding="utf-8")
    assert "test-marker" in text
    assert "sk-" not in text
