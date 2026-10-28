from __future__ import annotations

import pytest

from amadeus.core.router import Router
from amadeus.providers import ProviderError


def test_default_provider_is_local(settings):
    router = Router(settings)
    assert router.selected_name() == "ollama"
    assert router.selected().name == "ollama"


def test_unknown_provider_rejected(settings):
    settings.set("provider.name", "magic")
    with pytest.raises(ProviderError, match="Неизвестный провайдер"):
        Router(settings).selected()


def test_cloud_requires_explicit_permission(settings):
    settings.set("provider.name", "cloud")
    with pytest.raises(ProviderError, match="отключён"):
        Router(settings).selected()


def test_cloud_selected_when_allowed(settings, monkeypatch):
    monkeypatch.setenv("AMADEUS_CLOUD_API_KEY", "test-key")
    settings.set("provider.allow_cloud", True)
    settings.set("provider.name", "cloud")
    provider = Router(settings).selected()
    assert provider.name == "cloud"


def test_fallback_requires_cloud_key(settings, monkeypatch):
    monkeypatch.delenv("AMADEUS_CLOUD_API_KEY", raising=False)
    router = Router(settings)
    settings.set("provider.allow_cloud", True)
    assert router.can_fallback() is False
    monkeypatch.setenv("AMADEUS_CLOUD_API_KEY", "test-key")
    assert router.can_fallback() is True


def test_fallback_disabled_by_setting(settings, monkeypatch):
    monkeypatch.setenv("AMADEUS_CLOUD_API_KEY", "test-key")
    settings.set("provider.allow_cloud", True)
    settings.set("provider.cloud_fallback", False)
    assert Router(settings).can_fallback() is False
