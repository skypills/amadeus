from __future__ import annotations

import pytest

from amadeus.security import PermissionDenied, PermissionPolicy
from amadeus.settings import Settings
from amadeus.tools import (
    ToolError,
    ToolRegistry,
    build_registry,
    collect_system_info,
    launch_application,
    send_notification,
)


class FakeProcess:
    def __init__(self, returncode: int = 0, stderr: str = "", stdout: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


def test_send_notification_success(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return FakeProcess()

    monkeypatch.setattr("amadeus.tools.notifications.shutil.which", lambda _: "/bin/notify-send")
    monkeypatch.setattr("amadeus.tools.notifications.subprocess.run", fake_run)
    result = send_notification({"title": "Amadeus", "text": "Готово"})
    assert "отправлено" in result
    assert captured["command"][-2:] == ["Amadeus", "Готово"]


def test_send_notification_validation(monkeypatch):
    monkeypatch.setattr("amadeus.tools.notifications.shutil.which", lambda _: "/bin/notify-send")
    with pytest.raises(ToolError, match="пустым"):
        send_notification({"text": "   "})
    monkeypatch.setattr("amadeus.tools.notifications.shutil.which", lambda _: None)
    with pytest.raises(ToolError, match="notify-send"):
        send_notification({"text": "x"})


def test_launch_application_allowlist(monkeypatch):
    policy = PermissionPolicy(allowed_apps=frozenset({"firefox"}))
    captured = {}

    class FakePopen:
        def __init__(self, command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs

    monkeypatch.setattr("amadeus.tools.applications.shutil.which", lambda _: "/bin/firefox")
    monkeypatch.setattr("amadeus.tools.applications.subprocess.Popen", FakePopen)
    result = launch_application({"app": "firefox", "args": ["--new-window"]}, policy)
    assert "firefox" in result
    assert captured["command"] == ["/bin/firefox", "--new-window"]
    assert captured["kwargs"]["start_new_session"] is True

    with pytest.raises(PermissionDenied):
        launch_application({"app": "rm", "args": []}, policy)
    with pytest.raises(ToolError, match="[Аа]ргументы"):
        launch_application({"app": "firefox", "args": "not-a-list"}, policy)
    with pytest.raises(ToolError, match="Недопустимые"):
        launch_application({"app": "firefox", "args": ["a\nb"]}, policy)


def test_registry_never_auto_executes_confirmed_tool(settings):
    registry = build_registry(settings)
    with pytest.raises(PermissionDenied):
        registry.execute("launch_application", {"app": "firefox"})
    assert "launch_application" not in [tool.name for tool in registry.model_tools()]
    assert "system_info" in [tool.name for tool in registry.model_tools()]


def test_registry_respects_application_settings(tmp_path):
    settings = Settings.load(tmp_path / "settings.toml")
    settings.set("security.allowed_apps", ["firefox"], save=False)
    settings.set("security.confirm_app_launch", False)
    settings.save()
    registry = build_registry(settings)
    assert registry.policy.allowed_apps == frozenset({"firefox"})
    tool = registry.get("launch_application")
    assert tool.requires_confirmation is False


def test_system_info_contains_expected_fields():
    text = collect_system_info({})
    assert "ОС:" in text
    assert "CPU:" in text
    assert "Память:" in text
    assert "Диск:" in text


def test_unknown_tool_rejected():
    registry = ToolRegistry()
    with pytest.raises(ToolError, match="не зарегистрирован"):
        registry.execute("shell", {})
