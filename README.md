# Amadeus

Локальный ИИ-ассистент для CachyOS, вдохновлённый Amadeus из «Врат Штейна».
Это **этап 3** по ТЗ: CLI, долговременная память с подтверждением фактов,
настраиваемый характер и GUI на PySide6 с общим ядром. Голос, инструменты и
веб-поиск появятся на следующих этапах.

## Что уже работает

- диалог с локальной моделью Ollama на русском языке;
- потоковый вывод ответа;
- история диалогов в SQLite, переживает перезапуск;
- поиск по истории (SQLite FTS5, с fallback на `LIKE`);
- долговременные факты о пользователе: предложение → явное подтверждение → сохранение;
- очередь предложенных фактов, которую можно подтвердить позже;
- экспорт истории, фактов и предложений в JSON;
- редактируемая персона, настроение и параметры стиля (`familiarity`, `verbosity`, `initiative`);
- опциональный облачный провайдер (OpenAI-совместимый API) с явным включением;
- автоматический резерв на облако только при разрешении и только с уведомлением;
- фильтрация контекста для облака (история и факты не отправляются без разрешения);
- GUI на PySide6: чат с потоковым выводом, история и поиск, факты и предложения,
  настройки, состояние модели, экспорт и удаление данных;
- горячий вызов GUI через конфигурацию Hyprland;
- allowlist инструментов и проверка рискованных действий (задел на этап 5);
- понятные ошибки при недоступности Ollama, модели или сети.

## Требования

- CachyOS / Arch Linux, Wayland или X11 (для CLI не важно);
- Python 3.12+;
- Ollama (локальный провайдер);
- 8–16 ГБ ОЗУ; для 16 ГБ начните с модели 3B–4B в квантовании.

## Установка

### 1. Ollama и модель

Проверьте пакет в репозиториях и установите удобным способом:

```bash
pacman -Ss ollama
sudo pacman -S ollama          # или ollama-cuda / ollama-rocm, если есть GPU
sudo systemctl enable --now ollama
# вариант без systemd:
# ollama serve
```

Скачайте instruct-модель (пример для 16 ГБ):

```bash
ollama pull qwen2.5:3b-instruct
ollama list
```

Если у вас больше свободной памяти, можно попробовать 7B–8B:

```bash
ollama pull qwen2.5:7b-instruct
amadeus --model qwen2.5:7b-instruct
```

### 2. Виртуальное окружение

```bash
cd ~/amadeus
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

### 3. Запуск

```bash
amadeus
# или без активации venv:
./.venv/bin/amadeus
```

При первом запуске создаются:

```
~/.config/amadeus/settings.toml
~/.config/amadeus/persona.md
~/.local/share/amadeus/amadeus.db
~/.local/state/amadeus/
```

Проверка окружения:

```bash
amadeus --status
amadeus --once "Привет, проверка связи"
```

## GUI

```bash
amadeus-gui
amadeus-gui --new
amadeus-gui --session 3
amadeus-gui --model qwen2.5:7b-instruct
```

Возможности окна:

- чат с потоковым ответом и кнопкой остановки;
- история сессий, поиск по истории, создание и удаление сессий;
- вкладка «Факты»: подтверждённые факты и предложения, которые можно принять
  или отклонить;
- настройки модели, провайдера, облака и характера;
- строка состояния: доступность модели, выбранный провайдер, статус микрофона
  (голос — этап 4);
- экспорт данных и удаление всей истории через меню «Файл».

GUI и CLI используют один и тот же `Assistant`, базу и настройки.

### Горячий вызов в Hyprland

Приложение не перехватывает клавиши глобально. Добавьте привязку в
`~/.config/hypr/hyprland.conf`:

```ini
bind = SUPER, A, exec, amadeus-gui

windowrule = float, class:^(amadeus)$
windowrule = size 1080 760, class:^(amadeus)$
windowrule = center, class:^(amadeus)$
```

Готовый пример: `config/hyprland.conf.example`. В старых версиях Hyprland
используйте `windowrulev2` вместо `windowrule`.

### Ярлык в меню приложений

```bash
install -Dm644 packaging/amadeus.desktop ~/.local/share/applications/amadeus.desktop
install -Dm644 packaging/amadeus.svg \
  ~/.local/share/icons/hicolor/scalable/apps/amadeus.svg
update-desktop-database ~/.local/share/applications 2>/dev/null || true
```

## Команды CLI

| Команда | Назначение |
|---|---|
| `/help` | справка |
| `/exit`, `/quit` | выход |
| `/new` | новая сессия |
| `/sessions [N]` | список сессий |
| `/resume <id>` | продолжить сессию |
| `/history [N]` | сообщения текущей сессии |
| `/search <запрос>` | поиск по всей истории |
| `/export [путь]` | экспорт истории, фактов и предложений в JSON |
| `/delete <id\|all>` | удалить сессию или все данные |
| `/remember <текст>` | предложить факт и подтвердить сохранение |
| `/fact add <текст>` | сохранить подтверждённый факт |
| `/facts` | список фактов |
| `/fact pending` | факты, ожидающие подтверждения |
| `/fact accept <id>` | подтвердить предложенный факт |
| `/fact reject <id>` | отклонить предложенный факт |
| `/fact del <id>` | удалить факт |
| `/fact clear` | удалить все факты |
| `/model [имя]` | показать/сменить модель |
| `/provider [ollama\|cloud]` | показать/выбрать провайдера |
| `/cloud on\|off` | разрешить/запретить облако |
| `/stream on\|off` | потоковый вывод |
| `/mood [настроение]` | `calm`, `friendly`, `technical`, `supportive` |
| `/tone <параметр> <0..1>` | familiarity, verbosity или initiative |
| `/character [reset]` | показать или сбросить характер |
| `/reset` | сбросить настроение и параметры стиля |
| `/persona [edit\|reset]` | показать, изменить или сбросить персону |
| `/settings` | текущие настройки |
| `/status` | доступность провайдера |
| `/config` | пути конфигурации и данных |
| `/clear` | очистить экран |

Примеры запуска:

```bash
amadeus --new
amadeus --session 3
amadeus --once "Объясни, что такое Wayland"
amadeus --model qwen2.5:7b-instruct --no-stream
amadeus --config /path/to/settings.toml
```

## Настройки

Основной файл — `~/.config/amadeus/settings.toml`. Он создаётся из шаблона
`config/settings.toml`. Менять можно вручную или командами CLI.

Ключевые параметры:

```toml
[provider]
name = "ollama"            # ollama | cloud
allow_cloud = false        # облако по умолчанию запрещено
cloud_fallback = true      # резерв при недоступности Ollama (если разрешён)

[ollama]
base_url = "http://127.0.0.1:11434"
model = "qwen2.5:3b-instruct"
timeout = 120
stream = true

[generation]
temperature = 0.7
top_p = 0.9
max_tokens = 512
history_limit = 20
memory_limit = 5

[privacy]
send_history_to_cloud = false
send_facts_to_cloud = false
```

Персона хранится в `~/.config/amadeus/persona.md` и подмешивается в системный
промпт. Изменения применяются со следующего ответа.

## Память и характер

Долговременная память отделена от сырой истории. Факт не сохраняется, пока
пользователь его не подтвердит:

1. Сообщение «Запомни, что я люблю чай» или команда `/remember я люблю чай`
   создаёт **предложение** факта.
2. CLI спрашивает `[да/нет/позже]`.
3. Только после «да» факт попадает в таблицу `facts` с источником
   `user_confirmed`; «позже» оставляет его в `/fact pending`.
4. Модель не получает права сохранять факты сама и не должна утверждать, что
   уже сохранила их.

Факты, история текущей сессии и найденные фрагменты прошлых диалогов
подмешиваются в системный промпт следующего запроса. После перезапуска
продолжается последняя сессия, а факты остаются доступны.

Экспорт:

```
/export
/export ~/amadeus-backup.json
```

В JSON попадают сессии, сообщения, сохранённые факты и ожидающие предложения.
Секреты и настройки туда не включаются.

Характер задаётся персоной и четырьмя параметрами: `mood` (calm, friendly,
technical, supportive), `familiarity`, `verbosity`, `initiative` (0..1).
Команды: `/mood`, `/tone`, `/character`, `/reset`, `/persona edit`,
`/persona reset`.

## Облачный резерв (опционально)

По умолчанию всё работает локально. Облако включается только явно:

```bash
export AMADEUS_CLOUD_API_KEY="..."   # или положите в .env своего shell
```

Затем в CLI:

```
/provider cloud
```

Или в `settings.toml`:

```toml
[provider]
name = "cloud"
allow_cloud = true
cloud_base_url = "https://api.openai.com/v1"
cloud_model = "gpt-4o-mini"
cloud_api_key_env = "AMADEUS_CLOUD_API_KEY"
```

Важно:

- ключ не хранится в репозитории и не пишется в логи;
- при выборе облака CLI сообщает о передаче данных;
- история и факты не уходят в облако, пока не включены
  `privacy.send_history_to_cloud` и `privacy.send_facts_to_cloud`;
- при ошибке локальной модели резерв срабатывает только если облако разрешено,
  ключ найден и `cloud_fallback = true`; пользователь получает уведомление.

## Тесты

```bash
source .venv/bin/activate
pytest
```

Покрыты память, предложения и подтверждение фактов, экспорт, настройки,
характер, провайдеры, маршрутизация, приватность контекста, разрешения
инструментов и GUI (offscreen-тесты PySide6).

## Диагностика оборудования

Перед выбором модели полезно собрать данные:

```bash
free -h
lscpu | grep -E 'Model name|CPU\(s\)'
lspci | grep -Ei 'VGA|3D|Display'
```

## Типичные проблемы

**`Connection refused` / Ollama недоступна**

```bash
systemctl status ollama
sudo systemctl start ollama
# или вручную:
ollama serve
amadeus --status
```

**Модель не найдена**

```bash
ollama pull qwen2.5:3b-instruct
# имя должно совпадать с [ollama].model
ollama list
```

**Не хватает памяти**

Уменьшите модель (3B вместо 7B), `max_tokens` и `history_limit`; закройте
тяжёлые приложения. Не запускайте несколько LLM одновременно.

**Нет русского голоса/микрофона**

Голосовой этап ещё не реализован (этап 4). Сейчас GUI честно показывает
«Микрофон: не подключён».

**Где лежат данные**

```
amadeus --config  # покажет актуальные пути
```

Удалить историю, факты и предложения: `/delete all`. Удалить только факты:
`/fact clear`. Экспорт перед удалением: `/export`

## Структура проекта

```
amadeus/
├── pyproject.toml
├── config/                  # шаблоны settings.toml и persona.md
├── src/amadeus/
│   ├── cli.py               # интерфейс командной строки
│   ├── core/                # ядро, маршрутизация, события, контекст
│   ├── providers/           # Ollama и облачный OpenAI-совместимый провайдер
│   ├── memory/              # SQLite, история, факты, предложения, экспорт, retrieval
│   ├── personality/         # промпт, настроение
│   ├── security/            # политика разрешений
│   ├── tools/               # реестр allowlist-инструментов
│   ├── storage/             # пути platformdirs
│   ├── ui/                  # PySide6: окно, чат, настройки
│   └── voice/               # задел на этап 4
├── packaging/               # .desktop и иконка
├── config/hyprland.conf.example
├── tests/
└── docs/
```

## Этапы по ТЗ

- [x] Этап 1 — текстовое ядро: CLI, Ollama, промпт, SQLite, история, ошибки.
- [x] Этап 2 — память и личность: подтверждение фактов, экспорт, характер.
- [x] Этап 3 — GUI на PySide6: чат, история, настройки, статус, Hyprland.
- [ ] Этап 4 — голос (STT/TTS).
- [ ] Этап 5 — системные инструменты и подтверждения.
- [ ] Этап 6 — веб-поиск и облачный резерв.
- [ ] Этап 7 — стабилизация и документация установки.

Следующий шаг — этап 4: локальные STT/TTS, запись по кнопке и озвучивание.
Часть заделов этапов 5 и 6 уже заложена в коде (allowlist, облачный
провайдер), но полноценные интерфейсы появятся позже.

## Безопасность

Модель не получает произвольный shell и не сохраняет факты без подтверждения.
GUI и CLI используют общую политику памяти и приватности. Инструменты
выполняются только через реестр с allowlist и проверкой риска; опасные
действия требуют подтверждения. Подробнее — `docs/security.md`.
