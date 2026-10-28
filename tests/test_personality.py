from __future__ import annotations

import pytest

from amadeus.personality import (
    build_system_prompt,
    load_mood,
    reset_mood,
    set_mood,
    set_parameter,
)


def test_set_mood_and_tone_persist(settings):
    set_mood(settings, "friendly")
    set_parameter(settings, "verbosity", 0.9)
    reloaded = type(settings).load(settings.path)
    mood = load_mood(reloaded)
    assert mood.mood == "friendly"
    assert mood.verbosity == 0.9


def test_set_parameter_clamps(settings):
    assert set_parameter(settings, "familiarity", 2.0).familiarity == 1.0
    assert set_parameter(settings, "initiative", -1).initiative == 0.0


def test_unknown_mood_rejected(settings):
    with pytest.raises(ValueError, match="Неизвестное настроение"):
        set_mood(settings, "angry")


def test_reset_restores_defaults(settings):
    set_mood(settings, "technical")
    set_parameter(settings, "verbosity", 1.0)
    mood = reset_mood(settings)
    assert mood.mood == "calm"
    assert mood.verbosity == 0.5


def test_prompt_contains_persona_and_style(settings, tmp_path):
    persona = tmp_path / "persona.md"
    persona.write_text("Ты — тестовый Amadeus.", encoding="utf-8")
    mood = set_mood(settings, "technical")
    prompt = build_system_prompt(settings, persona.read_text(), mood=mood)
    assert "тестовый Amadeus" in prompt
    assert "technical" in prompt
    assert "настроение" in prompt
