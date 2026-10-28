from __future__ import annotations

import os
from pathlib import Path

from platformdirs import PlatformDirs

APP_NAME = "amadeus"
APP_AUTHOR = "amadeus"

_dirs = PlatformDirs(APP_NAME, APP_AUTHOR)


def config_dir() -> Path:
    return Path(os.environ.get("AMADEUS_CONFIG_DIR", _dirs.user_config_dir))


def data_dir() -> Path:
    return Path(os.environ.get("AMADEUS_DATA_DIR", _dirs.user_data_dir))


def state_dir() -> Path:
    return Path(os.environ.get("AMADEUS_STATE_DIR", _dirs.user_state_dir))


def settings_path() -> Path:
    return config_dir() / "settings.toml"


def persona_path() -> Path:
    return config_dir() / "persona.md"


def database_path() -> Path:
    return data_dir() / "amadeus.db"


def mood_path() -> Path:
    return state_dir() / "mood.json"


def ensure_dirs() -> None:
    for path in (config_dir(), data_dir(), state_dir()):
        path.mkdir(parents=True, exist_ok=True)
