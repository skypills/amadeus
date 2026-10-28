from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

from . import __version__
from .core.assistant import Assistant, AssistantError
from .core.events import Event
from .diagnostics import (
    DiagnosticsError,
    format_benchmark,
    run_benchmark,
    save_benchmark,
)
from .logging_setup import configure_logging
from .memory import Database, FactProposal
from .personality import MOODS, load_mood, reset_mood, set_mood, set_parameter
from .providers import OllamaProvider
from .security import PermissionDenied
from .settings import DEFAULT_PERSONA, ConfigError, Settings, dump_toml
from .storage import paths
from .tools import ToolError, WebSearch, WebSearchError, render_results, render_sources
from .voice import VoiceError, VoicePipeline

try:
    import readline  # noqa: F401
except ImportError:
    readline = None


HELP_TEXT = """\
Команды:
  /help                     показать эту справку
  /exit, /quit              выйти из диалога
  /new                      начать новую сессию
  /sessions [N]             список последних сессий
  /resume <id>              продолжить сессию по id
  /history [N]              показать последние N сообщений текущей сессии
  /search <запрос>          поиск по всей истории
  /summarize                создать сводку текущей сессии
  /summary [show|clear]     показать или удалить сохранённую сводку
  /export [путь]            экспорт истории, фактов и предложений в JSON
  /delete <id|all>          удалить сессию или все данные
  /remember <текст>         предложить факт и подтвердить сохранение
  /fact add <текст>         сохранить подтверждённый факт о пользователе
  /facts                    список сохранённых фактов
  /fact pending             факты, ожидающие подтверждения
  /fact accept <id>         подтвердить предложенный факт
  /fact reject <id>         отклонить предложенный факт
  /fact edit <id> <текст>   изменить факт
  /fact del <id>            удалить факт
  /fact clear               удалить все факты
  /model [имя]              показать или сменить модель Ollama
  /provider [ollama|cloud]  показать или выбрать провайдера
  /cloud on|off             разрешить или запретить облачный режим
  /stream on|off            включить или выключить потоковый вывод
  /mood [настроение]        показать или сменить настроение
  /tone <параметр> <0..1>   familiarity, verbosity или initiative
  /voice [status|stop]      состояние голосовых компонентов / стоп озвучки
  /listen [секунды]         записать, распознать и отправить (если auto_send)
  /say <текст>              озвучить текст локальным TTS
  /tools                    список разрешённых инструментов
  /sysinfo                  системная информация
  /notify <текст>           отправить уведомление
  /open <app> [аргументы]   запустить приложение из allowlist
  /copy [текст]             скопировать текст или последний ответ
  /screenshot               сделать скриншот экрана
  /volume [0-150]           показать или изменить громкость
  /media <action>           play-pause, next, previous, stop
  /openurl <url>            открыть http/https ссылку
  /web <запрос>             поиск в интернете и ответ по источникам
  /character [reset]        показать или сбросить характер
  /reset                    сбросить настроение и параметры стиля
  /persona [edit|reset]     показать, изменить или сбросить persona.md
  /settings                 показать текущие настройки
  /status                   проверить доступность модели
  /config                   показать пути конфигурации и данных
  /clear                    очистить экран
"""


def _print_event(event: Event) -> None:
    stream = sys.stderr
    if event.kind in ("cloud", "fallback", "tool"):
        print(f"\n[Amadeus] {event.message}", file=stream, flush=True)


def _confirm(prompt: str) -> bool:
    try:
        answer = input(f"{prompt} [да/нет]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("да", "д", "yes", "y")


def _truncate(text: str, limit: int = 800) -> str:
    flat = text.replace("\r", "")
    if len(flat) <= limit:
        return flat
    return flat[: limit - 3] + "..."


def _role_label(role: str) -> str:
    return {"user": "Вы", "assistant": "Amadeus", "system": "Система", "tool": "Инструмент"}.get(
        role, role
    )


class ChatCLI:
    def __init__(self, assistant: Assistant, settings: Settings) -> None:
        self.assistant = assistant
        self.settings = settings
        self.events = assistant.events
        self.events.subscribe(_print_event)
        self.running = True
        self.voice = VoicePipeline(settings)
        self.web = WebSearch.from_settings(settings)

    def run(self) -> int:
        self._print_banner()
        try:
            return self._loop()
        finally:
            self.voice.close()

    def _loop(self) -> int:
        while self.running:
            try:
                raw = input("Вы: ")
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print("\nВыход: Ctrl+D или /exit.")
                continue
            line = raw.strip()
            if not line:
                continue
            if line.startswith("/"):
                self._handle_command(line)
            else:
                self._handle_message(line)
        return 0

    def _print_banner(self) -> None:
        session = self.assistant.history.get_session(self.assistant.session_id)
        count = len(self.assistant.history.messages(self.assistant.session_id))
        title = session["title"] if session is not None else ""
        suffix = f" — «{title}»" if title else ""
        print(f"Amadeus {__version__} — локальный ассистент. /help для команд.")
        print(f"Сессия #{self.assistant.session_id}{suffix}, сообщений: {count}.")
        pending = self.assistant.proposals.count()
        if pending:
            print(f"Ожидают подтверждения фактов: {pending}. Список: /fact pending")
        print()

    def _handle_message(self, text: str, external_context: str = "") -> str | None:
        stream = bool(self.settings.get("ollama.stream", True))
        printed = False

        def on_chunk(chunk: str) -> None:
            nonlocal printed
            if not printed:
                print("Amadeus: ", end="", flush=True)
                printed = True
            print(chunk, end="", flush=True)

        try:
            answer = self.assistant.respond(
                text,
                stream=stream,
                on_chunk=on_chunk,
                external_context=external_context,
            )
        except AssistantError as exc:
            if printed:
                print()
            print(f"Ошибка: {exc}", file=sys.stderr)
            return None
        except KeyboardInterrupt:
            if printed:
                print()
            print("Генерация прервана.", file=sys.stderr)
            return None

        if printed:
            print()
        else:
            print(f"Amadeus: {answer}")
        print()
        self._maybe_propose_from_text(text)
        if bool(self.settings.get("voice.auto_speak", False)):
            try:
                self.voice.speak(answer)
                print("Озвучиваю ответ. Остановить: /voice stop", file=sys.stderr)
            except VoiceError as exc:
                print(f"Озвучивание: {exc}", file=sys.stderr)
        return answer

    def _maybe_propose_from_text(self, text: str) -> None:
        try:
            proposal = self.assistant.propose_from_text(text)
        except ValueError as exc:
            print(f"Память: {exc}", file=sys.stderr)
            return
        if proposal is not None:
            self._review_proposal(proposal)

    def _review_proposal(self, proposal: FactProposal) -> None:
        print(f"[Память] Предлагаю сохранить факт:\n  {proposal.content}")
        try:
            answer = input("Сохранить? [да/нет/позже]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            print("Предложение оставлено в ожидании. Список: /fact pending")
            return
        if answer in ("да", "д", "yes", "y"):
            fact = self.assistant.accept_proposal(proposal.id)
            if fact is None:
                print("Предложение уже не найдено.")
            else:
                print(f"Сохранён факт #{fact.id}.")
        elif answer in ("нет", "н", "no", "n"):
            self.assistant.reject_proposal(proposal.id)
            print("Предложение отклонено.")
        else:
            print("Предложение оставлено в ожидании. Список: /fact pending")
        print()

    def _handle_command(self, line: str) -> None:
        try:
            parts = shlex.split(line)
        except ValueError:
            parts = line.split()
        command = parts[0].lower()
        args = parts[1:]

        handlers = {
            "/help": self._cmd_help,
            "/exit": self._cmd_exit,
            "/quit": self._cmd_exit,
            "/q": self._cmd_exit,
            "/new": self._cmd_new,
            "/sessions": self._cmd_sessions,
            "/resume": self._cmd_resume,
            "/history": self._cmd_history,
            "/search": self._cmd_search,
            "/summarize": self._cmd_summarize,
            "/summary": self._cmd_summary,
            "/export": self._cmd_export,
            "/delete": self._cmd_delete,
            "/remember": self._cmd_remember,
            "/facts": self._cmd_facts,
            "/fact": self._cmd_fact,
            "/model": self._cmd_model,
            "/provider": self._cmd_provider,
            "/cloud": self._cmd_cloud,
            "/stream": self._cmd_stream,
            "/mood": self._cmd_mood,
            "/tone": self._cmd_tone,
            "/character": self._cmd_character,
            "/voice": self._cmd_voice,
            "/listen": self._cmd_listen,
            "/say": self._cmd_say,
            "/tools": self._cmd_tools,
            "/sysinfo": self._cmd_sysinfo,
            "/notify": self._cmd_notify,
            "/open": self._cmd_open,
            "/copy": self._cmd_copy,
            "/screenshot": self._cmd_screenshot,
            "/volume": self._cmd_volume,
            "/media": self._cmd_media,
            "/openurl": self._cmd_openurl,
            "/web": self._cmd_web,
            "/reset": self._cmd_reset,
            "/persona": self._cmd_persona,
            "/settings": self._cmd_settings,
            "/status": self._cmd_status,
            "/config": self._cmd_config,
            "/clear": self._cmd_clear,
        }
        handler = handlers.get(command)
        if handler is None:
            print(f"Неизвестная команда: {command}. Введите /help.")
            return
        try:
            handler(args)
        except (ValueError, ConfigError, ToolError, PermissionDenied, OSError) as exc:
            print(f"Ошибка: {exc}", file=sys.stderr)

    def _cmd_help(self, args: list[str]) -> None:
        print(HELP_TEXT)

    def _cmd_exit(self, args: list[str]) -> None:
        self.running = False

    def _cmd_new(self, args: list[str]) -> None:
        session_id = self.assistant.new_session()
        print(f"Начата сессия #{session_id}.")

    def _cmd_sessions(self, args: list[str]) -> None:
        limit = int(args[0]) if args and args[0].isdigit() else 20
        sessions = self.assistant.history.list_sessions(limit=limit)
        if not sessions:
            print("История пуста.")
            return
        current = self.assistant.session_id
        for row in sessions:
            mark = "*" if row["id"] == current else " "
            title = row["title"] or "(без названия)"
            print(
                f"{mark} #{row['id']:<5} {row['updated_at'][:19]}  "
                f"сообщений: {row['message_count']:<4} {title}"
            )

    def _cmd_resume(self, args: list[str]) -> None:
        if not args or not args[0].isdigit():
            raise ValueError("Использование: /resume <id>")
        session_id = int(args[0])
        if not self.assistant.resume(session_id):
            raise ValueError(f"Сессия #{session_id} не найдена.")
        count = len(self.assistant.history.messages(session_id))
        print(f"Продолжаю сессию #{session_id}, сообщений: {count}.")

    def _cmd_history(self, args: list[str]) -> None:
        limit = int(args[0]) if args and args[0].isdigit() else 20
        messages = self.assistant.history.messages(self.assistant.session_id, limit=limit)
        if not messages:
            print("В текущей сессии пока нет сообщений.")
            return
        for message in messages:
            print(f"[{message.created_at[:19]}] {_role_label(message.role)}:")
            print(_truncate(message.content))
            print()

    def _cmd_search(self, args: list[str]) -> None:
        query = " ".join(args).strip()
        if not query:
            raise ValueError("Использование: /search <запрос>")
        hits = self.assistant.history.search(query, limit=20)
        if not hits:
            print("Ничего не найдено.")
            return
        for hit in hits:
            title = hit.session_title or "(без названия)"
            print(f"#{hit.session_id} [{hit.created_at[:19]}] {_role_label(hit.role)} ({title}):")
            print(_truncate(hit.content, 500))
            print()

    def _cmd_summarize(self, args: list[str]) -> None:
        print("Создаю сводку сессии…", flush=True)
        try:
            summary = self.assistant.summarize_session()
        except AssistantError as exc:
            print(f"Сводка: {exc}", file=sys.stderr)
            return
        print(
            f"Сводка сохранена (по сообщение #{summary.through_message_id}, "
            f"{summary.updated_at[:19]}):"
        )
        print(summary.content)

    def _cmd_summary(self, args: list[str]) -> None:
        action = args[0].lower() if args else "show"
        if action == "clear":
            if not _confirm("Удалить сохранённую сводку текущей сессии?"):
                print("Отменено.")
                return
            self.assistant.summaries.delete(self.assistant.session_id)
            print("Сводка удалена.")
            return
        if action != "show":
            raise ValueError("Использование: /summary [show|clear]")
        summary = self.assistant.summaries.get(self.assistant.session_id)
        if summary is None:
            print("Сводки нет. Создать: /summarize")
            return
        print(f"Сводка по сообщение #{summary.through_message_id} ({summary.updated_at[:19]}):")
        print(summary.content)

    def _cmd_export(self, args: list[str]) -> None:
        path = " ".join(args).strip() or None
        target = self.assistant.export(path)
        print(f"Экспортировано: {target}")

    def _cmd_delete(self, args: list[str]) -> None:
        if not args:
            raise ValueError("Использование: /delete <id|all>")
        target = args[0].lower()
        if target == "all":
            if not _confirm("Удалить всю историю, факты и предложения фактов безвозвратно?"):
                print("Отменено.")
                return
            self.assistant.history.delete_all()
            self.assistant.detach_session()
            print("История, факты и предложения удалены.")
            return
        if not target.isdigit():
            raise ValueError("Использование: /delete <id|all>")
        session_id = int(target)
        if self.assistant.history.get_session(session_id) is None:
            raise ValueError(f"Сессия #{session_id} не найдена.")
        if not _confirm(f"Удалить сессию #{session_id}?"):
            print("Отменено.")
            return
        self.assistant.history.delete_session(session_id)
        if session_id == self.assistant.session_id:
            self.assistant.detach_session()
        print(f"Сессия #{session_id} удалена.")

    def _cmd_remember(self, args: list[str]) -> None:
        text = " ".join(args).strip()
        if not text:
            raise ValueError("Использование: /remember <текст>")
        proposal = self.assistant.propose_fact(text, source="user_request")
        self._review_proposal(proposal)

    def _cmd_facts(self, args: list[str]) -> None:
        facts = self.assistant.facts.list()
        if not facts:
            print("Сохранённых фактов нет. /fact add <текст> или /remember <текст>")
        else:
            for fact in facts:
                print(f"#{fact.id:<4} {fact.content}  ({fact.created_at[:19]})")
        pending = self.assistant.proposals.count()
        if pending:
            print(f"\nОжидают подтверждения: {pending}. Список: /fact pending")

    def _cmd_fact(self, args: list[str]) -> None:
        if not args:
            raise ValueError(
                "Использование: /fact add <текст> | edit <id> <текст> | pending | "
                "accept <id> | reject <id> | del <id> | clear"
            )
        action = args[0].lower()
        if action == "add":
            text = " ".join(args[1:]).strip()
            if not text:
                raise ValueError("Использование: /fact add <текст>")
            existing = self.assistant.facts.find_exact(text)
            if existing is not None:
                raise ValueError(f"Факт уже сохранён под #{existing.id}.")
            fact = self.assistant.facts.add(text, source="user_confirmed")
            print(f"Сохранён факт #{fact.id}.")
        elif action == "pending":
            proposals = self.assistant.proposals.pending()
            if not proposals:
                print("Нет фактов, ожидающих подтверждения.")
                return
            for proposal in proposals:
                print(f"#{proposal.id:<4} {proposal.content}  ({proposal.source})")
            print("\n/fact accept <id> или /fact reject <id>")
        elif action == "accept":
            if len(args) < 2 or not args[1].isdigit():
                raise ValueError("Использование: /fact accept <id>")
            proposal_id = int(args[1])
            fact = self.assistant.accept_proposal(proposal_id)
            if fact is None:
                raise ValueError(f"Предложение #{proposal_id} не найдено.")
            print(f"Сохранён факт #{fact.id}: {fact.content}")
        elif action == "reject":
            if len(args) < 2 or not args[1].isdigit():
                raise ValueError("Использование: /fact reject <id>")
            proposal_id = int(args[1])
            if not self.assistant.reject_proposal(proposal_id):
                raise ValueError(f"Предложение #{proposal_id} не найдено.")
            print(f"Предложение #{proposal_id} отклонено.")
        elif action == "edit":
            if len(args) < 3 or not args[1].isdigit():
                raise ValueError("Использование: /fact edit <id> <текст>")
            fact_id = int(args[1])
            fact = self.assistant.facts.update(fact_id, " ".join(args[2:]))
            if fact is None:
                raise ValueError(f"Факт #{fact_id} не найден.")
            print(f"Факт #{fact.id} обновлён: {fact.content}")
        elif action in ("del", "delete"):
            if len(args) < 2 or not args[1].isdigit():
                raise ValueError("Использование: /fact del <id>")
            fact_id = int(args[1])
            if not self.assistant.facts.delete(fact_id):
                raise ValueError(f"Факт #{fact_id} не найден.")
            print(f"Факт #{fact_id} удалён.")
        elif action in ("clear", "delete-all"):
            if not _confirm("Удалить все сохранённые факты?"):
                print("Отменено.")
                return
            self.assistant.facts.delete_all()
            print("Все факты удалены.")
        else:
            raise ValueError(
                "Использование: /fact add <текст> | edit <id> <текст> | pending | "
                "accept <id> | reject <id> | del <id> | clear"
            )

    def _cmd_model(self, args: list[str]) -> None:
        if not args:
            print(f"Модель: {self.settings.get('ollama.model')}")
            return
        model = args[0].strip()
        if not model:
            raise ValueError("Имя модели не может быть пустым.")
        self.settings.set("ollama.model", model)
        print(f"Модель изменена на «{model}».")
        provider = OllamaProvider(
            base_url=str(self.settings.get("ollama.base_url")),
            model=model,
            timeout=float(self.settings.get("ollama.timeout", 120)),
        )
        status = provider.status()
        print(("OK: " if status.ok else "Ошибка: ") + status.detail)

    def _cmd_provider(self, args: list[str]) -> None:
        if not args:
            allowed = "да" if self.settings.get("provider.allow_cloud") else "нет"
            print(f"Провайдер: {self.settings.get('provider.name')} (облако разрешено: {allowed})")
            return
        name = args[0].lower()
        if name == "ollama":
            self.settings.set("provider.name", "ollama")
            print("Выбран локальный провайдер Ollama.")
        elif name == "cloud":
            if not self.settings.get("provider.allow_cloud"):
                if not _confirm(
                    "Облачный режим отправит запросы и разрешённый контекст в интернет. Включить?"
                ):
                    print("Отменено.")
                    return
                self.settings.set("provider.allow_cloud", True, save=False)
            self.settings.set("provider.name", "cloud")
            print(
                "Выбран облачный провайдер. Память и история не отправляются без явного разрешения."
            )
        else:
            raise ValueError("Использование: /provider [ollama|cloud]")

    def _cmd_cloud(self, args: list[str]) -> None:
        if not args:
            state = "включён" if self.settings.get("provider.allow_cloud") else "выключен"
            print(f"Облачный режим {state}.")
            return
        state = args[0].lower()
        if state in ("on", "вкл", "1", "true"):
            if not self.settings.get("provider.allow_cloud"):
                if not _confirm(
                    "Разрешить отправку запросов в интернет при включении облачного режима?"
                ):
                    print("Отменено.")
                    return
            self.settings.set("provider.allow_cloud", True)
            print("Облачный режим разрешён.")
        elif state in ("off", "выкл", "0", "false"):
            self.settings.set("provider.allow_cloud", False, save=False)
            if self.settings.get("provider.name") == "cloud":
                self.settings.set("provider.name", "ollama", save=False)
            self.settings.save()
            print("Облачный режим запрещён, выбран локальный провайдер.")
        else:
            raise ValueError("Использование: /cloud on|off")

    def _cmd_stream(self, args: list[str]) -> None:
        if not args:
            state = "включён" if self.settings.get("ollama.stream") else "выключен"
            print(f"Потоковый вывод {state}.")
            return
        state = args[0].lower()
        if state in ("on", "вкл", "1", "true"):
            self.settings.set("ollama.stream", True)
            print("Потоковый вывод включён.")
        elif state in ("off", "выкл", "0", "false"):
            self.settings.set("ollama.stream", False)
            print("Потоковый вывод выключен.")
        else:
            raise ValueError("Использование: /stream on|off")

    def _cmd_mood(self, args: list[str]) -> None:
        if not args:
            mood = load_mood(self.settings)
            print(
                f"Настроение: {mood.mood} — {mood.description}\n"
                f"familiarity={mood.familiarity:.1f}, verbosity={mood.verbosity:.1f}, "
                f"initiative={mood.initiative:.1f}\n"
                f"Доступно: {', '.join(MOODS)}"
            )
            return
        mood = set_mood(self.settings, args[0])
        print(f"Настроение: {mood.mood} — {mood.description}")

    def _cmd_tone(self, args: list[str]) -> None:
        if len(args) != 2:
            raise ValueError("Использование: /tone <familiarity|verbosity|initiative> <0..1>")
        name = args[0].lower()
        if name not in ("familiarity", "verbosity", "initiative"):
            raise ValueError("Доступные параметры: familiarity, verbosity, initiative.")
        try:
            value = float(args[1].replace(",", "."))
        except ValueError as exc:
            raise ValueError("Значение должно быть числом от 0 до 1.") from exc
        if not 0.0 <= value <= 1.0:
            raise ValueError("Значение должно быть от 0 до 1.")
        mood = set_parameter(self.settings, name, value)
        print(f"{name}={getattr(mood, name):.1f}, настроение={mood.mood}. Изменение сохранено.")

    def _cmd_character(self, args: list[str]) -> None:
        if args and args[0].lower() == "reset":
            mood = reset_mood(self.settings)
            print(f"Характер сброшен: {mood.mood}, параметры по умолчанию.")
            return
        if args:
            raise ValueError("Использование: /character [reset]")
        mood = load_mood(self.settings)
        print(f"Настроение: {mood.mood} — {mood.description}")
        print(
            f"familiarity={mood.familiarity:.1f}, verbosity={mood.verbosity:.1f}, "
            f"initiative={mood.initiative:.1f}"
        )
        print(f"Персона: {self.assistant.persona_path}")
        print("Изменить: /mood <имя>, /tone <параметр> <0..1>, /persona edit")

    def _cmd_tools(self, args: list[str]) -> None:
        for tool in self.assistant.tools.all():
            confirm = " (нужно подтверждение)" if tool.requires_confirmation else ""
            print(f"{tool.name:<20} риск={tool.risk:<6}{confirm} — {tool.description}")

    def _cmd_sysinfo(self, args: list[str]) -> None:
        print(self.assistant.tools.execute("system_info", {}, confirmed=True))

    def _cmd_notify(self, args: list[str]) -> None:
        text = " ".join(args).strip()
        if not text:
            raise ValueError("Использование: /notify <текст>")
        result = self.assistant.tools.execute(
            "send_notification",
            {"title": "Amadeus", "text": text},
            confirmed=True,
        )
        print(result)

    def _cmd_open(self, args: list[str]) -> None:
        if not args:
            raise ValueError("Использование: /open <app> [аргументы]")
        app = args[0]
        tool = self.assistant.tools.get("launch_application")
        if tool.requires_confirmation and not _confirm(f"Запустить «{app}»?"):
            print("Отменено.")
            return
        result = self.assistant.tools.execute(
            "launch_application",
            {"app": app, "args": args[1:]},
            confirmed=True,
        )
        print(result)

    def _last_assistant_text(self) -> str | None:
        messages = self.assistant.history.messages(self.assistant.session_id, limit=50)
        return next(
            (message.content for message in reversed(messages) if message.role == "assistant"),
            None,
        )

    def _cmd_copy(self, args: list[str]) -> None:
        text = " ".join(args).strip() or (self._last_assistant_text() or "")
        if not text:
            raise ValueError("Нечего копировать: в сессии ещё нет ответа.")
        print(self.assistant.tools.execute("copy_clipboard", {"text": text}, confirmed=True))

    def _cmd_screenshot(self, args: list[str]) -> None:
        if not _confirm("Сделать скриншот экрана?"):
            print("Отменено.")
            return
        print(self.assistant.tools.execute("screenshot", {}, confirmed=True))

    def _cmd_volume(self, args: list[str]) -> None:
        if not args:
            print(self.assistant.tools.execute("get_volume", {}, confirmed=True))
            return
        try:
            percent = int(args[0])
        except ValueError as exc:
            raise ValueError("Использование: /volume [0-150]") from exc
        print(self.assistant.tools.execute("set_volume", {"percent": percent}, confirmed=True))

    def _cmd_media(self, args: list[str]) -> None:
        if not args:
            raise ValueError("Использование: /media <play-pause|next|previous|stop>")
        print(self.assistant.tools.execute("media_control", {"action": args[0]}, confirmed=True))

    def _cmd_openurl(self, args: list[str]) -> None:
        url = " ".join(args).strip()
        if not url:
            raise ValueError("Использование: /openurl <url>")
        if not _confirm(f"Открыть в браузере {url}?"):
            print("Отменено.")
            return
        print(self.assistant.tools.execute("open_url", {"url": url}, confirmed=True))

    def _cmd_web(self, args: list[str]) -> None:
        query = " ".join(args).strip()
        if not query:
            raise ValueError("Использование: /web <запрос>")
        print("Ищу в интернете…", flush=True)
        try:
            results = self.web.search(query)
        except WebSearchError as exc:
            print(f"Веб-поиск: {exc}", file=sys.stderr)
            return
        print(render_sources(results))
        print()
        self._handle_message(query, external_context=render_results(results))

    def _cmd_voice(self, args: list[str]) -> None:
        action = args[0].lower() if args else "status"
        if action == "stop":
            self.voice.stop_speaking()
            print("Озвучивание остановлено.")
            return
        if action != "status":
            raise ValueError("Использование: /voice [status|stop]")
        labels = {
            "recorder": "Запись",
            "stt": "Распознавание",
            "tts": "Синтез",
            "player": "Воспроизведение",
        }
        for key, (ok, detail) in self.voice.status().items():
            mark = "OK" if ok else "нет"
            print(f"{labels.get(key, key)}: {mark} — {detail}")

    def _cmd_listen(self, args: list[str]) -> None:
        try:
            seconds = float(args[0].replace(",", ".")) if args else 5.0
        except ValueError as exc:
            raise ValueError("Использование: /listen [секунды]") from exc
        if not 0.5 <= seconds <= 60:
            raise ValueError("Длительность записи должна быть от 0.5 до 60 секунд.")
        print(f"Запись {seconds:g} с… Ctrl+C — отмена.", flush=True)
        try:
            text = self.voice.record_for(seconds)
        except KeyboardInterrupt:
            print("Запись отменена.")
            return
        except VoiceError as exc:
            print(f"Голос: {exc}", file=sys.stderr)
            return
        print(f"Распознано: {text}")
        if bool(self.settings.get("voice.auto_send", True)):
            self._handle_message(text)

    def _cmd_say(self, args: list[str]) -> None:
        text = " ".join(args).strip()
        if not text:
            raise ValueError("Использование: /say <текст>")
        try:
            self.voice.speak(text)
        except VoiceError as exc:
            print(f"Голос: {exc}", file=sys.stderr)
            return
        print("Озвучиваю. Остановить: /voice stop")

    def _cmd_reset(self, args: list[str]) -> None:
        mood = reset_mood(self.settings)
        print(f"Характер сброшен: {mood.mood}.")

    def _cmd_persona(self, args: list[str]) -> None:
        path = self.assistant.persona_path
        if not args:
            try:
                print(path.read_text(encoding="utf-8"))
            except OSError as exc:
                raise ValueError(f"Не удалось прочитать {path}: {exc}") from exc
            print(f"\nФайл: {path}")
            return
        action = args[0].lower()
        if action == "reset":
            if not _confirm("Вернуть стандартную персону? Текущий текст будет перезаписан."):
                print("Отменено.")
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(DEFAULT_PERSONA, encoding="utf-8")
            print("Персона сброшена к стандартной.")
            return
        if action != "edit":
            raise ValueError("Использование: /persona [edit|reset]")
        editor = os.environ.get("EDITOR", "nano")
        command = shlex.split(editor) or ["nano"]
        try:
            subprocess.run([*command, str(path)], check=False)
        except FileNotFoundError as exc:
            raise ValueError(f"Редактор «{editor}» не найден. Задайте $EDITOR.") from exc
        print("Персона обновлена и будет использована в следующих ответах.")

    def _cmd_settings(self, args: list[str]) -> None:
        print(dump_toml(self.settings.as_dict()))

    def _cmd_status(self, args: list[str]) -> None:
        status = self.assistant.provider_status()
        print(("OK: " if status.ok else "Ошибка: ") + status.detail)
        if status.models:
            print("Доступные модели: " + ", ".join(status.models[:20]))

    def _cmd_config(self, args: list[str]) -> None:
        print(f"Настройки: {self.settings.path}")
        print(f"Персона:   {self.assistant.persona_path}")
        print(f"База:      {paths.database_path()}")
        print(f"Данные:    {paths.data_dir()}")
        print(f"Состояние: {paths.state_dir()}")

    def _cmd_clear(self, args: list[str]) -> None:
        print("\033[2J\033[H", end="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amadeus",
        description="Amadeus — локальный ИИ-ассистент для CachyOS (текстовое ядро и CLI).",
    )
    parser.add_argument("--config", type=Path, help="путь к альтернативному settings.toml")
    parser.add_argument("--model", help="переопределить модель Ollama для этого запуска")
    parser.add_argument("--session", type=int, help="продолжить сессию по id")
    parser.add_argument("--new", action="store_true", help="начать новую сессию")
    parser.add_argument("--once", metavar="ТЕКСТ", help="отправить одно сообщение и выйти")
    parser.add_argument("--no-stream", action="store_true", help="отключить потоковый вывод")
    parser.add_argument("--status", action="store_true", help="проверить доступность провайдера")
    parser.add_argument("--diagnose", action="store_true", help="диагностика системы и настроек")
    parser.add_argument("--benchmark", action="store_true", help="замерить скорость модели")
    parser.add_argument(
        "--benchmark-prompt",
        default="Кратко объясни, что такое Wayland.",
        help="промпт для benchmark",
    )
    parser.add_argument("--benchmark-out", type=Path, help="сохранить benchmark в JSON")
    parser.add_argument("--version", action="version", version=f"Amadeus {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger = configure_logging()
    logger.info("CLI start version=%s", __version__)
    try:
        settings = Settings.load(args.config)
    except ConfigError as exc:
        logger.error("config error: %s", exc)
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return 2

    if args.diagnose:
        from .diagnostics import diagnose

        print(diagnose(settings))
        return 0

    if args.benchmark:
        try:
            result = run_benchmark(settings, prompt=args.benchmark_prompt)
        except DiagnosticsError as exc:
            logger.error("benchmark error: %s", exc)
            print(f"Ошибка benchmark: {exc}", file=sys.stderr)
            return 1
        print(format_benchmark(result))
        if args.benchmark_out:
            target = save_benchmark(result, args.benchmark_out)
            print(f"Сохранено: {target}")
        return 0

    if args.model:
        settings.set("ollama.model", args.model)
    if args.no_stream:
        settings.set("ollama.stream", False)

    try:
        db = Database()
    except Exception as exc:  # noqa: BLE001 - понятное сообщение вместо трейса
        print(f"Не удалось открыть базу данных: {exc}", file=sys.stderr)
        return 2

    assistant = Assistant(settings, db=db, persona_path=settings.persona_path)
    try:
        if args.status:
            status = assistant.provider_status()
            print(("OK: " if status.ok else "Ошибка: ") + status.detail)
            if status.models:
                print("Доступные модели: " + ", ".join(status.models[:20]))
            return 0 if status.ok else 1

        if args.new:
            assistant.new_session()
        elif args.session is not None:
            if not assistant.resume(args.session):
                print(f"Сессия #{args.session} не найдена.", file=sys.stderr)
                return 2

        if args.once:
            assistant.events.subscribe(_print_event)
            stream = bool(settings.get("ollama.stream", True)) and not args.no_stream
            printed = False

            def on_chunk(chunk: str) -> None:
                nonlocal printed
                if not printed:
                    print("Amadeus: ", end="", flush=True)
                    printed = True
                print(chunk, end="", flush=True)

            try:
                answer = assistant.respond(args.once, stream=stream, on_chunk=on_chunk)
            except AssistantError as exc:
                if printed:
                    print()
                print(f"Ошибка: {exc}", file=sys.stderr)
                return 1
            except KeyboardInterrupt:
                if printed:
                    print()
                print("Генерация прервана.", file=sys.stderr)
                return 130
            if printed:
                print()
            else:
                print(answer)
            return 0

        return ChatCLI(assistant, settings).run()
    finally:
        assistant.close()


if __name__ == "__main__":
    raise SystemExit(main())
