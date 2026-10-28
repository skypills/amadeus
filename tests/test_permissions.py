from __future__ import annotations

import pytest

from amadeus.security import RISK_HIGH, RISK_LOW, PermissionDenied, PermissionPolicy
from amadeus.tools import Tool, ToolError, ToolRegistry


def test_allowed_and_denied_apps():
    policy = PermissionPolicy()
    policy.check_app("firefox")
    with pytest.raises(PermissionDenied):
        policy.check_app("rm")


def test_high_risk_requires_confirmation_and_policy():
    policy = PermissionPolicy()
    with pytest.raises(PermissionDenied):
        policy.check_risk(RISK_HIGH, "delete_files", confirmed=True)
    with pytest.raises(PermissionDenied):
        policy.check_risk("medium", "install_packages", confirmed=False)
    policy.check_risk(RISK_LOW, "system_info", confirmed=True)


def test_registry_rejects_unregistered_tool():
    registry = ToolRegistry()
    with pytest.raises(ToolError, match="не зарегистрирован"):
        registry.execute("shell", {"cmd": "rm -rf /"})


def test_registry_requires_confirmation_for_risky_tool():
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="delete_files",
            description="удалить файлы",
            risk=RISK_HIGH,
            handler=lambda arguments: "deleted",
            requires_confirmation=True,
        )
    )
    with pytest.raises(PermissionDenied):
        registry.execute("delete_files", {"path": "/tmp/x"})
    with pytest.raises(PermissionDenied):
        registry.execute("delete_files", {"path": "/tmp/x"}, confirmed=True)


def test_registry_runs_low_risk_tool():
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="system_info",
            description="информация",
            risk=RISK_LOW,
            handler=lambda arguments: f"os={arguments['os']}",
        )
    )
    assert registry.execute("system_info", {"os": "CachyOS"}) == "os=CachyOS"
    assert registry.names() == ["system_info"]
