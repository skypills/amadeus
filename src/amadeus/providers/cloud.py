from __future__ import annotations

import json
import os
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


class CloudProvider(Provider):
    name = "cloud"

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        api_key_env: str = "AMADEUS_CLOUD_API_KEY",
        timeout: float = 120,
        temperature: float = 0.7,
        top_p: float = 0.9,
        max_tokens: int = 512,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env
        self.timeout = timeout
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens

    def api_key(self) -> str | None:
        key = os.environ.get(self.api_key_env, "").strip()
        return key or None

    def status(self) -> ProviderStatus:
        if not self.api_key():
            return ProviderStatus(
                False,
                f"Не задан ключ облачного провайдера. Установите переменную {self.api_key_env}.",
            )
        return ProviderStatus(
            True,
            f"Облачный провайдер настроен ({self.base_url}, модель «{self.model}»). "
            "Данные будут переданы в интернет.",
        )

    def chat(
        self,
        messages: Messages,
        stream: bool = True,
        on_chunk: ChunkCallback | None = None,
    ) -> str:
        key = self.api_key()
        if not key:
            raise ProviderError(
                f"Облачный режим включён, но ключ не найден. "
                f"Задайте переменную окружения {self.api_key_env}."
            )
        payload = {
            "model": self.model,
            "messages": list(messages),
            "stream": stream,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ProviderConnectionError(
                f"Облачный провайдер вернул HTTP {exc.code}: {body[:300]}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ProviderConnectionError(f"Облачный провайдер недоступен: {reason}") from exc

        if not stream:
            with response:
                try:
                    data = json.loads(response.read().decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise ProviderError("Облачный провайдер вернул некорректный JSON.") from exc
            if "error" in data:
                raise ProviderError(f"Облачный провайдер: {data['error']}")
            choices = data.get("choices") or []
            if not choices:
                return ""
            return str((choices[0].get("message") or {}).get("content") or "")

        parts: list[str] = []
        with response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    data = json.loads(chunk)
                except json.JSONDecodeError as exc:
                    raise ProviderError(
                        "Облачный провайдер вернул некорректный поток данных."
                    ) from exc
                if "error" in data:
                    raise ProviderError(f"Облачный провайдер: {data['error']}")
                choices = data.get("choices") or []
                if not choices:
                    continue
                content = str((choices[0].get("delta") or {}).get("content") or "")
                if content:
                    parts.append(content)
                    if on_chunk is not None:
                        on_chunk(content)
        return "".join(parts)
