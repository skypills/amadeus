from __future__ import annotations

import pytest

from amadeus.settings import ConfigError, Settings, dump_toml


def test_defaults_are_written_and_persona_created(settings):
    assert settings.path.exists()
    assert settings.persona_path.exists()
    assert settings.get("provider.name") == "ollama"
    assert settings.get("ollama.model")
    assert settings.get("personality.preset") == "kurisu"
    assert settings.get("voice.profile") == "kurisu"
    assert settings.get("voice.auto_speak") is True
    assert "Курису" in settings.persona_path.read_text(encoding="utf-8")


def test_settings_change_persists(settings):
    settings.set("ollama.model", "custom:4b")
    settings.set("generation.temperature", 0.2)
    reloaded = Settings.load(settings.path)
    assert reloaded.get("ollama.model") == "custom:4b"
    assert reloaded.get("generation.temperature") == 0.2


def test_invalid_toml_reports_config_error(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("this is = not [valid", encoding="utf-8")
    with pytest.raises(ConfigError, match="Не удалось прочитать"):
        Settings.load(path)


def test_dump_toml_roundtrip(settings, tmp_path):
    text = dump_toml(settings.as_dict())
    assert "[provider]" in text
    assert "true" in text
    assert "false" in text
    copy = tmp_path / "copy.toml"
    copy.write_text(text, encoding="utf-8")
    loaded = Settings.load(copy)
    assert loaded.get("provider.allow_cloud") is False
    assert loaded.get("generation.history_limit") == 20
