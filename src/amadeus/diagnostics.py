from __future__ import annotations

import json
import platform
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .memory import Database, Facts, History, Proposals
from .providers import ProviderError
from .settings import Settings
from .storage import paths
from .tools import collect_system_info
from .voice import VoicePipeline


class DiagnosticsError(RuntimeError):
    pass


@dataclass(frozen=True)
class BenchmarkResult:
    model: str
    prompt: str
    first_token_ms: float
    total_ms: float
    generated_tokens: int
    prompt_tokens: int
    tokens_per_second: float
    ram_total: str
    ram_available: str
    timestamp: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _memory() -> tuple[str, str]:
    total = available = ""
    try:
        text = Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "неизвестно", "неизвестно"
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            total = line.split(":", 1)[1].strip()
        elif line.startswith("MemAvailable:"):
            available = line.split(":", 1)[1].strip()
    return total or "неизвестно", available or "неизвестно"


def run_benchmark(
    settings: Settings,
    prompt: str = "Кратко объясни, что такое Wayland.",
    max_tokens: int | None = None,
) -> BenchmarkResult:
    base_url = str(settings.get("ollama.base_url", "http://127.0.0.1:11434")).rstrip("/")
    model = str(settings.get("ollama.model", "qwen2.5:3b-instruct"))
    timeout = float(settings.get("ollama.timeout", 120))
    limit = int(max_tokens or settings.get("generation.max_tokens", 128))
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "options": {"temperature": 0.0, "num_predict": limit},
    }
    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/x-ndjson"},
        method="POST",
    )
    started = time.perf_counter()
    first_token: float | None = None
    generated = prompt_tokens = 0
    eval_duration_ns = 0
    text_parts: list[str] = []
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise DiagnosticsError("Ollama вернула некорректный поток.") from exc
                if error := data.get("error"):
                    raise DiagnosticsError(f"Ollama: {error}")
                content = str((data.get("message") or {}).get("content") or "")
                if content and first_token is None:
                    first_token = (time.perf_counter() - started) * 1000
                    text_parts.append(content)
                elif content:
                    text_parts.append(content)
                if data.get("done"):
                    generated = int(data.get("eval_count") or 0)
                    prompt_tokens = int(data.get("prompt_eval_count") or 0)
                    eval_duration_ns = int(data.get("eval_duration") or 0)
                    break
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise DiagnosticsError(f"Ollama вернула HTTP {exc.code}: {body[:300]}") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise DiagnosticsError(f"Ollama недоступна: {reason}. Запустите `ollama serve`.") from exc
    total = (time.perf_counter() - started) * 1000
    if first_token is None:
        raise DiagnosticsError("Ollama не вернула ни одного токена.")
    if not generated:
        generated = len("".join(text_parts).split())
    if eval_duration_ns > 0:
        tokens_per_second = generated / (eval_duration_ns / 1_000_000_000)
    else:
        tokens_per_second = generated / max(total / 1000, 0.001)
    ram_total, ram_available = _memory()
    return BenchmarkResult(
        model=model,
        prompt=prompt,
        first_token_ms=round(first_token, 1),
        total_ms=round(total, 1),
        generated_tokens=generated,
        prompt_tokens=prompt_tokens,
        tokens_per_second=round(tokens_per_second, 2),
        ram_total=ram_total,
        ram_available=ram_available,
        timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def format_benchmark(result: BenchmarkResult) -> str:
    return "\n".join(
        [
            "Amadeus benchmark",
            f"Модель: {result.model}",
            f"Первый токен: {result.first_token_ms:.1f} мс",
            f"Всего: {result.total_ms:.1f} мс",
            f"Токенов сгенерировано: {result.generated_tokens}",
            f"Токенов промпта: {result.prompt_tokens}",
            f"Скорость: {result.tokens_per_second:.2f} ток/с",
            f"RAM всего/доступно: {result.ram_total} / {result.ram_available}",
            f"Время: {result.timestamp}",
        ]
    )


def save_benchmark(result: BenchmarkResult, path: Path | str) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def diagnose(settings: Settings) -> str:
    lines = [
        f"Amadeus: {__version__}",
        f"Python: {sys.version.split()[0]} ({platform.python_implementation()})",
        collect_system_info({}),
        "",
        "Пути:",
        f"  Настройки: {settings.path}",
        f"  Персона:   {settings.persona_path}",
        f"  База:      {paths.database_path()}",
        f"  Данные:    {paths.data_dir()}",
        f"  Состояние: {paths.state_dir()}",
    ]

    from .core.router import Router

    try:
        provider, status = Router(settings).status()
        lines.append("")
        lines.append(f"Провайдер: {provider.name}")
        lines.append(("OK: " if status.ok else "Ошибка: ") + status.detail)
        if status.models:
            lines.append("Модели: " + ", ".join(status.models[:20]))
    except ProviderError as exc:
        lines.append("")
        lines.append(f"Провайдер: ошибка — {exc}")

    try:
        voice = VoicePipeline(settings)
        lines.append("")
        lines.append("Голос:")
        for key, (ok, detail) in voice.status().items():
            lines.append(f"  {key}: {'OK' if ok else 'нет'} — {detail}")
        voice.close()
    except Exception as exc:  # noqa: BLE001 - диагностика должна продолжаться
        lines.append(f"Голос: ошибка — {exc}")

    try:
        db = Database()
        history = History(db)
        facts = Facts(db)
        proposals = Proposals(db, facts)
        lines.append("")
        lines.append("Данные:")
        lines.append(f"  Сессий: {len(history.list_sessions(limit=1_000_000))}")
        lines.append(f"  Фактов: {len(facts.list(limit=1_000_000))}")
        lines.append(f"  Предложений: {proposals.count()}")
        db.close()
    except Exception as exc:  # noqa: BLE001
        lines.append(f"Данные: ошибка — {exc}")

    lines.append("")
    lines.append("Подробнее: docs/benchmark.md")
    return "\n".join(lines)
