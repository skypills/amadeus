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
from .memory import Database
from .personality import MOODS, load_mood, reset_mood, set_mood
from .providers import OllamaProvider
from .settings import ConfigError, Settings, dump_toml
from .storage import paths

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
  /delete <id|all>          удалить сессию или всю историю и факты
  /fact add <текст>         сохранить подтверждённый факт о пользователе
  /facts                    список сохранённых фактов
  /fact del <id>            удалить факт
  /fact clear               удалить все факты
  /model [имя]              показать или сменить модель Ollama
  /provider [ollama|cloud]  показать или выбрать провайдера
  /cloud on|off             разрешить или запретить облачный режим
  /stream on|off            включить или выключить потоковый вывод
  /mood [настроение]        показать или сменить настроение
  /reset                    сбросить настройки характера
  /persona [edit]           показать или отредактировать persona.md
  /settings                 показать текущие настройки
  /status                   проверить доступность модели
  /config                   показать пути конфигурации и данных
  /clear                    очистить экран
"""


def _print_event(event: Event) -> None:
    stream = sys.stderr
    if event.kind in ("cloud", "fallback"):
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

    def run(self) -> int:
        self._print_banner()
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
        print()

    def _handle_message(self, text: str) -> None:
        stream = bool(self.settings.get("ollama.stream", True))
        printed = False

        def on_chunk(chunk: str) -> None:
            nonlocal printed
            if not printed:
                print("Amadeus: ", end="", flush=True)
                printed = True
            print(chunk, end="", flush=True)

        try:
            answer = self.assistant.respond(text, stream=stream, on_chunk=on_chunk)
        except AssistantError as exc:
            if printed:
                print()
            print(f"Ошибка: {exc}", file=sys.stderr)
            return
        except KeyboardInterrupt:
            if printed:
                print()
            print("Генерация прервана.", file=sys.stderr)
            return

        if printed:
            print()
        else:
            print(f"Amadeus: {answer}")
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
            "/delete": self._cmd_delete,
            "/facts": self._cmd_facts,
            "/fact": self._cmd_fact,
            "/model": self._cmd_model,
            "/provider": self._cmd_provider,
            "/cloud": self._cmd_cloud,
            "/stream": self._cmd_stream,
            "/mood": self._cmd_mood,
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
        except (ValueError, ConfigError) as exc:
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

    def _cmd_delete(self, args: list[str]) -> None:
        if not args:
            raise ValueError("Использование: /delete <id|all>")
        target = args[0].lower()
        if target == "all":
            if not _confirm("Удалить всю историю и все факты безвозвратно?"):
                print("Отменено.")
                return
            self.assistant.history.delete_all()
            self.assistant.detach_session()
            print("История и факты удалены.")
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

    def _cmd_facts(self, args: list[str]) -> None:
        facts = self.assistant.facts.list()
        if not facts:
            print("Сохранённых фактов нет. /fact add <текст>")
            return
        for fact in facts:
            print(f"#{fact.id:<4} {fact.content}  ({fact.created_at[:19]})")

    def _cmd_fact(self, args: list[str]) -> None:
        if not args:
            raise ValueError("Использование: /fact add <текст> | del <id> | clear")
        action = args[0].lower()
        if action == "add":
            text = " ".join(args[1:]).strip()
            if not text:
                raise ValueError("Использование: /fact add <текст>")
            fact = self.assistant.facts.add(text, source="user_confirmed")
            print(f"Сохранён факт #{fact.id}.")
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
            raise ValueError("Использование: /fact add <текст> | del <id> | clear")

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
        if args[0].lower() != "edit":
            raise ValueError("Использование: /persona [edit]")
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
    parser.add_argument("--version", action="version", version=f"Amadeus {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.load(args.config)
    except ConfigError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return 2

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
