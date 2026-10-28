from __future__ import annotations

import pytest

from amadeus.settings import Settings


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("AMADEUS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AMADEUS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AMADEUS_STATE_DIR", str(tmp_path / "state"))
    return tmp_path


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings.load(tmp_path / "settings.toml")
