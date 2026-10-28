from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import (
    ChunkCallback,
    Messages,
    Provider,
    ProviderConnectionError,
    ProviderError,
    ProviderStatus,
)


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5:3b-instruct",
        timeout: float = 120,
        temperature: float = 0.7,
        top_p: float = 0.9,
        max_tokens: int = 512,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens

    def _request(
        self,
        path: str,
        payload: dict[str, object] | None = None,
        timeout: float | None = None,
    ):
        url = f"{self.base_url}{path}"
        data = None
        headers = {"Accept": "application/json"}
        method = "GET"
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
            method = "POST"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            return urllib.request.urlopen(request, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            hint = ""
            if exc.code == 404:
                hint = f" Модель «{self.model}» не найдена: выполните `ollama pull {self.model}`."
            raise ProviderConnectionError(
                f"Ollama вернула HTTP {exc.code}.{hint} {body[:300]}".strip()
            ) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ProviderConnectionError(
                f"Ollama недоступна по адресу {self.base_url}: {reason}. "
                "Запустите `ollama serve` или `systemctl --user start ollama`."
            ) from exc

    def status(self) -> ProviderStatus:
        try:
            with self._request("/api/tags", timeout=min(self.timeout, 5)) as response:
                data = json.loads(response.read().decode("utf-8"))
        except ProviderError as exc:
            return ProviderStatus(False, str(exc))
        models = tuple(
            str(item.get("name", "")) for item in data.get("models", []) if item.get("name")
        )
        if not models:
            return ProviderStatus(True, "Ollama запущена, но модели не установлены.", models)
        if self.model not in models:
            return ProviderStatus(
                True,
                f"Ollama запущена, но модели «{self.model}» нет. "
                f"Выполните `ollama pull {self.model}`.",
                models,
            )
        return ProviderStatus(True, f"Ollama доступна, модель «{self.model}» на месте.", models)

    def chat(
        self,
        messages: Messages,
        stream: bool = True,
        on_chunk: ChunkCallback | None = None,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": list(messages),
            "stream": stream,
            "options": {
                "temperature": self.temperature,
                "top_p": self.top_p,
                "num_predict": self.max_tokens,
            },
        }
        response = self._request("/api/chat", payload)
        if not stream:
            with response:
                try:
                    data = json.loads(response.read().decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise ProviderError("Ollama вернула некорректный JSON.") from exc
            if error := data.get("error"):
                raise ProviderError(f"Ollama: {error}")
            return str((data.get("message") or {}).get("content") or "")

        parts: list[str] = []
        with response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ProviderError("Ollama вернула некорректный поток данных.") from exc
                if error := data.get("error"):
                    raise ProviderError(f"Ollama: {error}")
                content = str((data.get("message") or {}).get("content") or "")
                if content:
                    parts.append(content)
                    if on_chunk is not None:
                        on_chunk(content)
                if data.get("done"):
                    break
        return "".join(parts)
