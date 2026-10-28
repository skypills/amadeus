from __future__ import annotations

from ..providers import CloudProvider, OllamaProvider, Provider, ProviderError
from ..providers.base import ProviderStatus
from ..settings import Settings


class Router:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def local_provider(self) -> OllamaProvider:
        return OllamaProvider(
            base_url=str(self.settings.get("ollama.base_url", "http://127.0.0.1:11434")),
            model=str(self.settings.get("ollama.model", "qwen2.5:3b-instruct")),
            timeout=float(self.settings.get("ollama.timeout", 120)),
            temperature=float(self.settings.get("generation.temperature", 0.7)),
            top_p=float(self.settings.get("generation.top_p", 0.9)),
            max_tokens=int(self.settings.get("generation.max_tokens", 512)),
        )

    def cloud_provider(self) -> CloudProvider:
        api_key_env = str(self.settings.get("provider.cloud_api_key_env", "AMADEUS_CLOUD_API_KEY"))
        return CloudProvider(
            base_url=str(self.settings.get("provider.cloud_base_url", "https://api.openai.com/v1")),
            model=str(self.settings.get("provider.cloud_model", "gpt-4o-mini")),
            api_key_env=api_key_env,
            timeout=float(self.settings.get("ollama.timeout", 120)),
            temperature=float(self.settings.get("generation.temperature", 0.7)),
            top_p=float(self.settings.get("generation.top_p", 0.9)),
            max_tokens=int(self.settings.get("generation.max_tokens", 512)),
        )

    def cloud_allowed(self) -> bool:
        return bool(self.settings.get("provider.allow_cloud", False))

    def selected_name(self) -> str:
        name = str(self.settings.get("provider.name", "ollama")).lower()
        if name not in ("ollama", "cloud"):
            raise ProviderError(f"Неизвестный провайдер «{name}». Допустимо: ollama, cloud.")
        return name

    def selected(self) -> Provider:
        name = self.selected_name()
        if name == "cloud":
            if not self.cloud_allowed():
                raise ProviderError(
                    "Облачный провайдер отключён. Включите его командой /provider cloud "
                    "и подтвердите передачу данных."
                )
            return self.cloud_provider()
        return self.local_provider()

    def can_fallback(self) -> bool:
        if self.selected_name() != "ollama":
            return False
        if not self.cloud_allowed():
            return False
        if not bool(self.settings.get("provider.cloud_fallback", True)):
            return False
        return self.cloud_provider().status().ok

    def status(self) -> tuple[Provider, ProviderStatus]:
        provider = self.selected()
        return provider, provider.status()
