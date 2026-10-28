from __future__ import annotations

from types import SimpleNamespace

import pytest

from amadeus.security import PermissionDenied
from amadeus.settings import Settings
from amadeus.tools import (
    ToolError,
    build_registry,
    copy_to_clipboard,
    get_volume,
    media_control,
    open_url,
    set_volume,
    take_screenshot,
)


def which_only(name: str):
    def fake(name_to_check):
        return f"/bin/{name}" if name_to_check == name else None

    return fake


def test_copy_to_clipboard(monkeypatch):
    captured = {}

    def fake_run(command, timeout=10, input_text=None):
        captured["command"] = command
        captured["text"] = input_text
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("amadeus.tools.system_actions.shutil.which", which_only("wl-copy"))
    monkeypatch.setattr("amadeus.tools.system_actions._run", fake_run)
    result = copy_to_clipboard({"text": "привет"})
    assert "Скопировано" in result
    assert captured["command"] == ["/bin/wl-copy"]
    assert captured["text"] == "привет"


def test_copy_to_clipboard_missing(monkeypatch):
    monkeypatch.setattr("amadeus.tools.system_actions.shutil.which", lambda _: None)
    with pytest.raises(ToolError, match="буфер"):
        copy_to_clipboard({"text": "x"})


def test_take_screenshot(monkeypatch):
    def fake_run(command, timeout=10, input_text=None):
        from pathlib import Path

        Path(command[-1]).write_bytes(b"png")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("amadeus.tools.system_actions.shutil.which", which_only("grim"))
    monkeypatch.setattr("amadeus.tools.system_actions._run", fake_run)
    result = take_screenshot({})
    assert "Скриншот сохранён" in result


def test_volume_get_set(monkeypatch):
    commands = []

    def fake_run(command, timeout=10, input_text=None):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="Volume: 0.50\n", stderr="")

    monkeypatch.setattr("amadeus.tools.system_actions.shutil.which", which_only("wpctl"))
    monkeypatch.setattr("amadeus.tools.system_actions._run", fake_run)
    assert "Volume" in get_volume({})
    assert "50%" in set_volume({"percent": 50})
    assert commands[-1][-1] == "50%"
    with pytest.raises(ToolError, match="0 до 150"):
        set_volume({"percent": 200})
    with pytest.raises(ToolError, match="целым"):
        set_volume({"percent": "abc"})


def test_media_control(monkeypatch):
    commands = []

    def fake_run(command, timeout=10, input_text=None):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("amadeus.tools.system_actions.shutil.which", which_only("playerctl"))
    monkeypatch.setattr("amadeus.tools.system_actions._run", fake_run)
    assert "next" in media_control({"action": "next"})
    assert commands[-1] == ["/bin/playerctl", "next"]
    with pytest.raises(ToolError, match="Действие"):
        media_control({"action": "explode"})


def test_open_url(monkeypatch):
    captured = {}

    class FakePopen:
        def __init__(self, command, **kwargs):
            captured["command"] = command

    monkeypatch.setattr("amadeus.tools.system_actions.shutil.which", which_only("xdg-open"))
    monkeypatch.setattr("amadeus.tools.system_actions.subprocess.Popen", FakePopen)
    assert "Открываю" in open_url({"url": "https://example.com"})
    assert captured["command"] == ["/bin/xdg-open", "https://example.com"]
    with pytest.raises(ToolError, match="http"):
        open_url({"url": "file:///etc/passwd"})
    with pytest.raises(ToolError, match="Некорректный"):
        open_url({"url": "https://example.com/\nbad"})


def test_new_tools_registry_exposure(tmp_path):
    settings = Settings.load(tmp_path / "settings.toml")
    registry = build_registry(settings)
    names = set(registry.names())
    assert {
        "copy_clipboard",
        "screenshot",
        "get_volume",
        "set_volume",
        "media_control",
        "open_url",
    } <= names
    model_names = {tool.name for tool in registry.model_tools()}
    assert "get_volume" in model_names
    assert "screenshot" not in model_names
    assert "set_volume" not in model_names
    assert "open_url" not in model_names
    assert "copy_clipboard" not in model_names
    with pytest.raises(PermissionDenied):
        registry.execute("screenshot", {})
    with pytest.raises(PermissionDenied):
        registry.execute("open_url", {"url": "https://example.com"})
