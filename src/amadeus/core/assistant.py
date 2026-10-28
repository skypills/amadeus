from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ..memory import (
    Database,
    Fact,
    FactProposal,
    Facts,
    History,
    MemoryContext,
    Proposals,
    Retrieval,
    detect_remember_request,
    export_json,
)
from ..memory.history import Message
from ..personality import build_system_prompt, load_mood, load_persona
from ..providers import ChunkCallback, ProviderError
from ..providers.base import Provider, ProviderStatus, ToolCall
from ..settings import Settings
from ..storage import paths
from ..tools import ToolRegistry, build_registry
from .context import build_messages
from .events import EventBus
from .router import Router


class AssistantError(RuntimeError):
    pass


class Assistant:
    def __init__(
        self,
        settings: Settings,
        db: Database | None = None,
        events: EventBus | None = None,
        persona_path: Path | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.db = db or Database()
        self.events = events or EventBus()
        self.history = History(self.db)
        self.facts = Facts(self.db)
        self.proposals = Proposals(self.db, self.facts)
        self.retrieval = Retrieval(self.history, self.facts)
        self.router = Router(settings)
        self.tools = registry or build_registry(settings)
        self.persona_path = persona_path or paths.persona_path()
        self._session_id: int | None = None

    @property
    def session_id(self) -> int:
        if self._session_id is None:
            latest = self.history.latest_session()
            self._session_id = int(latest["id"]) if latest else self.history.create_session()
        return self._session_id

    def new_session(self) -> int:
        self._session_id = self.history.create_session()
        return self._session_id

    def resume(self, session_id: int) -> bool:
        if self.history.get_session(session_id) is None:
            return False
        self._session_id = session_id
        return True

    def detach_session(self) -> None:
        self._session_id = None

    def propose_fact(self, content: str, source: str = "user_request") -> FactProposal:
        return self.proposals.propose(content, source=source)

    def propose_from_text(self, text: str) -> FactProposal | None:
        content = detect_remember_request(text)
        if content is None:
            return None
        return self.proposals.propose(content, source="user_request")

    def accept_proposal(self, proposal_id: int) -> Fact | None:
        return self.proposals.accept(proposal_id)

    def reject_proposal(self, proposal_id: int) -> bool:
        return self.proposals.reject(proposal_id)

    def export(self, path: Path | str | None = None) -> Path:
        if path is None:
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            path = paths.data_dir() / "exports" / f"amadeus-{stamp}.json"
        return export_json(self.history, self.facts, self.proposals, path)

    def provider_status(self) -> ProviderStatus:
        try:
            provider = self.router.selected()
        except ProviderError as exc:
            return ProviderStatus(False, str(exc))
        return provider.status()

    def _memory_context(
        self, user_text: str, provider_name: str
    ) -> tuple[list[Message], MemoryContext]:
        session_id = self.session_id
        limit = int(self.settings.get("generation.history_limit", 20))
        memory_limit = int(self.settings.get("generation.memory_limit", 5))
        include_history = True
        include_facts = True
        if provider_name == "cloud":
            include_history = bool(self.settings.get("privacy.send_history_to_cloud", False))
            include_facts = bool(self.settings.get("privacy.send_facts_to_cloud", False))
        history = self.history.messages(session_id, limit=limit if include_history else 1)
        context = MemoryContext()
        if include_history or include_facts:
            gathered = self.retrieval.gather(
                user_text,
                limit=memory_limit,
                exclude_session=session_id,
                include_facts=include_facts,
            )
            context = MemoryContext(
                facts=gathered.facts if include_facts else (),
                messages=gathered.messages if include_history else (),
            )
        return history, context

    def _build_request(
        self, user_text: str, provider_name: str, external_context: str = ""
    ) -> list[dict[str, str]]:
        history, memory = self._memory_context(user_text, provider_name)
        mood = load_mood(self.settings)
        persona = load_persona(self.persona_path)
        memory_block = self.retrieval.render(memory)
        system_prompt = build_system_prompt(
            self.settings,
            persona,
            mood=mood,
            cloud=provider_name == "cloud",
        )
        return build_messages(
            system_prompt,
            history,
            memory_block=memory_block,
            external_context=external_context,
        )

    def _execute_tool_call(self, call: ToolCall) -> str:
        try:
            tool = self.tools.get(call.name)
            if not tool.allow_model:
                return (
                    f"Ошибка безопасности: инструмент «{call.name}» не разрешён "
                    "для автоматического вызова моделью."
                )
            if tool.risk != "low" or tool.requires_confirmation:
                return (
                    f"Ошибка безопасности: инструмент «{call.name}» требует "
                    "явного подтверждения пользователя."
                )
            output = self.tools.execute(call.name, call.arguments, confirmed=False)
            self.events.emit("tool", f"Инструмент {call.name}: {output}")
            return output
        except Exception as exc:  # noqa: BLE001 - результат уходит модели
            self.events.emit("tool", f"Инструмент {call.name}: ошибка: {exc}")
            return f"Ошибка инструмента «{call.name}»: {exc}"

    def _chat(
        self,
        provider: Provider,
        messages: list[dict[str, str]],
        stream: bool,
        on_chunk: ChunkCallback | None,
    ) -> str:
        specs = self.tools.model_specs()
        enabled = bool(self.settings.get("tools.model_calls", True))
        if not enabled or not specs or not getattr(provider, "supports_tools", False):
            return provider.chat(messages, stream=stream, on_chunk=on_chunk)
        working: list[dict[str, object]] = list(messages)
        for round_index in range(3):
            try:
                result = provider.chat_tools(working, specs, on_chunk=on_chunk)
            except ProviderError as exc:
                message = str(exc).lower()
                if round_index == 0 and ("tool" in message or "function" in message):
                    self.events.emit(
                        "tool",
                        "Модель не поддерживает вызов инструментов, продолжаю без них.",
                    )
                    return provider.chat(messages, stream=stream, on_chunk=on_chunk)
                raise
            if not result.tool_calls:
                return result.text
            executed = [(call, self._execute_tool_call(call)) for call in result.tool_calls]
            working.extend(provider.format_tool_messages(result, executed))
        raise AssistantError("Модель слишком много раз вызывала инструменты.")

    def respond(
        self,
        user_text: str,
        stream: bool = True,
        on_chunk: ChunkCallback | None = None,
        external_context: str = "",
    ) -> str:
        user_text = user_text.strip()
        if not user_text:
            raise AssistantError("Пустое сообщение.")
        try:
            provider = self.router.selected()
        except ProviderError as exc:
            raise AssistantError(str(exc)) from exc

        session_id = self.session_id
        self.history.add_message(session_id, "user", user_text)

        if provider.name == "cloud":
            self._notify_cloud()

        messages = self._build_request(user_text, provider.name, external_context)
        produced: list[str] = []

        def emit(chunk: str) -> None:
            produced.append(chunk)
            if on_chunk is not None:
                on_chunk(chunk)

        try:
            answer = self._chat(provider, messages, stream, emit)
        except ProviderError as exc:
            if provider.name == "ollama" and not produced and self.router.can_fallback():
                self.events.emit(
                    "fallback",
                    "Локальная модель недоступна, переключаюсь на облачный резерв. "
                    "Запрос будет отправлен в интернет.",
                )
                cloud = self.router.cloud_provider()
                self._notify_cloud()
                cloud_messages = self._build_request(user_text, "cloud", external_context)
                try:
                    answer = self._chat(cloud, cloud_messages, stream, emit)
                except ProviderError as cloud_exc:
                    raise AssistantError(
                        f"Локальная модель недоступна: {exc}. "
                        f"Облачный резерв тоже не сработал: {cloud_exc}"
                    ) from cloud_exc
            else:
                raise AssistantError(str(exc)) from exc

        if not answer.strip():
            raise AssistantError("Модель вернула пустой ответ.")
        self.history.add_message(session_id, "assistant", answer)
        return answer

    def _notify_cloud(self) -> None:
        self.events.emit(
            "cloud",
            "Облачный режим: запрос и разрешённый контекст отправляются в интернет.",
        )

    def close(self) -> None:
        self.db.close()
