from __future__ import annotations

from amadeus.core.assistant import Assistant
from amadeus.core.events import EventBus
from amadeus.memory import Database
from amadeus.providers import ProviderError
from amadeus.providers.base import ProviderStatus, ToolCall, ToolChatResult
from amadeus.tools import Tool, ToolRegistry


class ToolProvider:
    name = "ollama"
    supports_tools = True

    def __init__(self, calls: list[ToolCall] | None = None, fail_tools: bool = False) -> None:
        self.calls = calls or []
        self.fail_tools = fail_tools
        self.rounds = 0
        self.messages: list[dict[str, object]] = []
        self.tool_specs: list[dict[str, object]] = []
        self.plain_used = False

    def status(self) -> ProviderStatus:
        return ProviderStatus(True, "ok")

    def chat(self, messages, stream=True, on_chunk=None) -> str:
        self.plain_used = True
        return "обычный ответ"

    def chat_tools(self, messages, tools, on_chunk=None) -> ToolChatResult:
        if self.fail_tools:
            raise ProviderError("model does not support tools")
        self.rounds += 1
        self.messages = list(messages)
        self.tool_specs = tools
        if self.rounds <= len(self.calls):
            return ToolChatResult("", (self.calls[self.rounds - 1],))
        return ToolChatResult("Готово", ())

    def format_tool_messages(self, result, executed):
        messages = [
            {
                "role": "assistant",
                "content": result.text,
                "tool_calls": [
                    {"function": {"name": call.name, "arguments": call.arguments}}
                    for call, _ in executed
                ],
            }
        ]
        messages.extend(
            {"role": "tool", "content": content, "tool_name": call.name}
            for call, content in executed
        )
        return messages


def make_assistant(tmp_path, settings, registry) -> Assistant:
    return Assistant(
        settings,
        db=Database(tmp_path / "assistant-tools.db"),
        events=EventBus(),
        persona_path=tmp_path / "persona.md",
        registry=registry,
    )


def test_low_risk_tool_is_executed_for_model(tmp_path, settings):
    executed: list[dict[str, object]] = []
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="system_info",
            description="info",
            risk="low",
            handler=lambda arguments: executed.append(arguments) or "SYS-INFO",
        )
    )
    assistant = make_assistant(tmp_path, settings, registry)
    provider = ToolProvider([ToolCall("1", "system_info", {})])
    assistant.router.selected = lambda: provider
    assistant.router.can_fallback = lambda: False
    events = []
    assistant.events.subscribe(events.append)

    answer = assistant.respond("Что с системой?")

    assert answer == "Готово"
    assert provider.rounds == 2
    assert executed == [{}]
    assert provider.tool_specs[0]["function"]["name"] == "system_info"
    tool_messages = [message for message in provider.messages if message.get("role") == "tool"]
    assert tool_messages[0]["content"] == "SYS-INFO"
    assert any(event.kind == "tool" for event in events)
    assistant.close()


def test_dangerous_tool_cannot_be_called_by_model(tmp_path, settings):
    executed: list[dict[str, object]] = []
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="launch_application",
            description="launch",
            risk="medium",
            handler=lambda arguments: executed.append(arguments) or "LAUNCHED",
            requires_confirmation=True,
        )
    )
    registry.register(
        Tool(name="system_info", description="info", risk="low", handler=lambda args: "SYS")
    )
    assistant = make_assistant(tmp_path, settings, registry)
    provider = ToolProvider([ToolCall("1", "launch_application", {"app": "firefox"})])
    assistant.router.selected = lambda: provider
    assistant.router.can_fallback = lambda: False

    answer = assistant.respond("Запусти firefox")

    assert answer == "Готово"
    assert executed == []
    assert [spec["function"]["name"] for spec in provider.tool_specs] == ["system_info"]
    tool_message = next(m for m in provider.messages if m.get("role") == "tool")
    assert "подтверждения" in str(tool_message["content"])
    assistant.close()


def test_tools_can_be_disabled(tmp_path, settings):
    settings.set("tools.model_calls", False)
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="system_info",
            description="info",
            risk="low",
            handler=lambda arguments: "SYS",
        )
    )
    assistant = make_assistant(tmp_path, settings, registry)
    provider = ToolProvider([ToolCall("1", "system_info", {})])
    assistant.router.selected = lambda: provider
    assistant.router.can_fallback = lambda: False

    assert assistant.respond("Привет") == "обычный ответ"
    assert provider.plain_used
    assert provider.rounds == 0
    assistant.close()


def test_provider_without_tool_support_falls_back_to_plain_chat(tmp_path, settings):
    registry = ToolRegistry()
    registry.register(
        Tool(name="system_info", description="info", risk="low", handler=lambda args: "SYS")
    )
    assistant = make_assistant(tmp_path, settings, registry)
    provider = ToolProvider(fail_tools=True)
    assistant.router.selected = lambda: provider
    assistant.router.can_fallback = lambda: False
    events = []
    assistant.events.subscribe(events.append)

    assert assistant.respond("Привет") == "обычный ответ"
    assert provider.plain_used
    assert any(event.kind == "tool" for event in events)
    assistant.close()
