# Amadeus

[![CI](https://github.com/skypills/amadeus/actions/workflows/ci.yml/badge.svg)](https://github.com/skypills/amadeus/actions/workflows/ci.yml)

Локальный ИИ-ассистент для CachyOS, вдохновлённый Amadeus из «Врат Штейна».
Это **версия 1.2.0**: MVP по ТЗ завершён, добавлены умная память, системные
действия Wayland, упаковка/CI, Kurisu-inspired персона и фоновый режим с треем,
автозапуском и горячей клавишей.

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
- локальный голосовой ввод через whisper.cpp и озвучивание через Piper;
- запись по кнопке, отмена записи, остановка озвучивания;
- инструменты: системная информация, уведомления и запуск приложений из allowlist;
- вызов низкорисковых инструментов моделью и подтверждение запуска приложений;
- веб-поиск с реальными URL, выдержками и датой (если доступна);
- явное отделение интернет-данных от собственных знаний и защита от инъекций;
- `amadeus --diagnose`, `amadeus --benchmark`, ротация логов без секретов;
- сводки длинных сессий и автоматическое подключение сводки к контексту;
- редактирование сохранённых фактов;
- персоны `amadeus`/`kurisu` и голосовые профили с настройкой темпа, шума и тона;
- Kurisu-профиль и автоозвучивание включены по умолчанию;
- фоновый режим GUI: трей, скрытый запуск, `--toggle`, автозапуск;
- системные действия: буфер обмена, скриншоты, громкость, медиа, открытие URL;
- CI на Python 3.12–3.14, coverage, wheel/sdist, PKGBUILD и Makefile;
- инструкции установки, автозапуска и измерений производительности;
- allowlist инструментов и проверка рискованных действий (задел на этап 5);
- понятные ошибки при недоступности Ollama, модели или сети.

## Требования

- CachyOS / Arch Linux, Wayland или X11 (для CLI не важно);
- Python 3.12+;
- Ollama (локальный провайдер);
- по желанию: whisper.cpp и Piper для голоса;
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

Если Ollama установлена в домашний каталог без sudo, используйте пользовательский
systemd-сервис из `packaging/ollama-user.service`:

```bash
mkdir -p ~/.config/systemd/user
cp packaging/ollama-user.service ~/.config/systemd/user/ollama.service
systemctl --user daemon-reload
systemctl --user enable --now ollama.service
```

## Разработка, упаковка и CI

```bash
make install     # pip install -e ".[dev]"
make test        # offscreen pytest
make cov         # coverage (порог 60%)
make lint        # ruff check
make format      # ruff format
make build       # python -m build
make gui         # amadeus-gui
make diagnose    # amadeus --diagnose
```

Сборка и установка:

```bash
python -m build
pip install dist/amadeus-1.0.0-py3-none-any.whl
```

Arch/CachyOS: `cd packaging && makepkg -si` (`amadeus-git`).
CI: `.github/workflows/ci.yml`; релиз по тегу `v*` — `.github/workflows/release.yml`.
Подробнее — `packaging/README.md` и `CHANGELOG.md`.

## Диагностика, стабильность и установка

```bash
amadeus --diagnose
amadeus --benchmark
amadeus --benchmark --benchmark-out ~/amadeus-bench.json
```

`--diagnose` показывает железо, пути, статус модели/голоса и счётчики данных,
не выводя секреты. `--benchmark` измеряет первый токен, скорость генерации и
доступную RAM. Логи пишутся в `~/.local/state/amadeus/amadeus.log` с ротацией и
не содержат ключей и текстов диалогов.

- Подробная установка: `docs/installation.md`
- Диагностика и выбор модели: `docs/benchmark.md`
- Результаты реальной проверки: `docs/verification.md`
- Автозапуск GUI: `packaging/amadeus-autostart.desktop`
- Логи: `~/.local/state/amadeus/amadeus.log`

## Инструменты и безопасность

Разрешённые действия зарегистрированы в реестре. Модель может сама вызывать
только низкорисковые инструменты (`system_info`, `send_notification`).
Запуск приложений доступен лишь явно пользователем и требует подтверждения.

```toml
[tools]
model_calls = true       # разрешить модели вызывать низкорисковые инструменты

[search]
allow_model_calls = false  # модель не ищет в интернете без явной команды

[security]
allowed_apps = ["firefox", "kitty", "code", "thunar"]
confirm_app_launch = true
```

CLI:

```
/tools            список инструментов
/sysinfo          ОС, CPU, память, диск, GPU
/notify текст     уведомление на рабочем столе
/open firefox     запуск приложения из allowlist
/web CachyOS Hyprland   поиск в интернете и ответ по источникам
/copy                   скопировать последний ответ
/screenshot             скриншот экрана
/volume 50              громкость 50%
/media next             следующий трек
/openurl https://...    открыть ссылку в браузере
```

В GUI — меню «Инструменты», в том числе «Системные действия». Скриншот и
открытие URL требуют подтверждения; громкость и медиа — явные команды.
Буфер обмена использует `wl-copy`/`xclip`/`xsel`, скриншоты — `grim` или
аналоги, звук — `wpctl` (wireplumber), медиа — `playerctl`, ссылки — `xdg-open`. Уведомления используют `notify-send` (пакет
libnotify и работающий демон уведомлений). Произвольный shell и установка
пакетов недоступны. При облачном режиме результаты инструментов, как и запрос,
могут уйти провайдеру — облако включается только явно.

## Веб-поиск

Поиск запускается явно: `/web <запрос>` в CLI или «Инструменты → Веб-поиск…»
в GUI. Результаты — реальные URL, заголовки, выдержки и дата, если поисковик её
вернул. Список источников показывается отдельно, а модели передаётся блок с
пометкой «недоверенные данные»: она не должна выполнять инструкции со страниц
и выдумывать ссылки.

```toml
[search]
provider = "duckduckgo"
backend = "duckduckgo"
use_library = true          # ddgs, с резервным HTML-парсером
allow_model_calls = false   # разрешить модели самой вызывать web_search
base_url = "https://html.duckduckgo.com/html/"
timeout = 15
max_results = 5
```

По умолчанию модель не ходит в интернет сама: веб-поиск доступен только по
явной команде. Если включить `allow_model_calls = true`, низкорисковый
инструмент `web_search` появится в function calling. При недоступности
поисковика приложение сообщает об ошибке и продолжает локальный диалог.
Интернет-функции можно полностью отключить, не используя `/web` и оставив
`allow_model_calls = false`.

## Голос (опционально)

Голос работает полностью локально. Нужны две внешние программы и модели;
они не входят в Python-пакет.

### whisper.cpp (STT)

Проверьте пакет в репозиториях/AUR или соберите:

```bash
git clone https://github.com/ggml-org/whisper.cpp
cd whisper.cpp
cmake -B build
cmake --build build -j --config Release
install -Dm755 build/bin/whisper-cli ~/.local/bin/whisper-cli
```

Скачайте модель (для русского лучше `small`, если хватает памяти):

```bash
mkdir -p ~/.local/share/amadeus/models
curl -L -o ~/.local/share/amadeus/models/ggml-base.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin
# альтернатива:
# curl -L -o ~/.local/share/amadeus/models/ggml-small.bin \
#   https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
```

### Piper (TTS)

Установите `piper` (пакет AUR/`pipx install piper-tts` или сборка из
репозитория rhasspy/piper) и скачайте русский голос:

```bash
curl -L -o ~/.local/share/amadeus/models/ru_RU-irina-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx
curl -L -o ~/.local/share/amadeus/models/ru_RU-irina-medium.onnx.json \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json
```

Проверка:

```bash
whisper-cli --help
piper --help
amadeus
# в CLI: /voice
```

### Настройки голоса

```toml
[voice]
stt_command = "whisper-cli"
stt_model = "~/.local/share/amadeus/models/ggml-base.bin"
tts_command = "piper"
tts_model = "~/.local/share/amadeus/models/ru_RU-irina-medium.onnx"
language = "ru"
recorder_command = ""   # пусто = parecord / pw-record / arecord
player_command = ""     # пусто = pw-play / paplay / aplay / ffplay
auto_send = true        # отправлять распознанное сразу
auto_speak = false      # озвучивать ответы автоматически
```

В GUI кнопки «Записать», «Отменить запись», «Озвучить» и «Стоп TTS».
В CLI: `/listen 5`, `/say текст`, `/voice status`, `/voice stop`.

Записи удаляются сразу после распознавания. Озвучка сохраняется локально в
`~/.local/share/amadeus/voice/last-response.wav` и перезаписывается. Голосовые
данные не отправляются в облако.

## GUI

```bash
amadeus-gui                 # обычное окно
amadeus-gui --background    # скрыто в трее/фоне
amadeus-gui --toggle        # показать/скрыть уже запущенный экземпляр
amadeus-gui --new
amadeus-gui --session 3
```

В фоне работает один экземпляр: повторный `--toggle` не запускает второй
процесс, а показывает/скрывает окно. Закрытие окна сворачивает приложение в
трей (`[ui].close_to_tray = true`). Это фоновый GUI, а не постоянное
прослушивание микрофона: запись и голосовые команды запускаются явно.

Возможности окна:

- чат с потоковым ответом и кнопкой остановки;
- история сессий, поиск по истории, создание и удаление сессий;
- вкладка «Факты»: подтверждённые факты и предложения, которые можно принять,
  отклонить или изменить;
- кнопка «Сводка» для длинных сессий;
- настройки модели, провайдера, облака и характера;
- строка состояния: доступность модели, провайдер, микрофон и голос;
- голосовые кнопки: запись, отмена, озвучивание, остановка TTS;
- меню «Инструменты»: веб-поиск, системная информация, уведомление,
  запуск приложения, системные действия;
- экспорт данных и удаление всей истории через меню «Файл».

GUI и CLI используют один и тот же `Assistant`, базу и настройки.

### Горячий вызов и фон в Hyprland

Приложение не перехватывает клавиши глобально. Добавьте привязку и автозапуск
в `~/.config/hypr/hyprland.conf`:

```ini
exec-once = amadeus-gui --background
bind = SUPER, A, exec, amadeus-gui --toggle

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
| `/summarize` | создать сводку текущей сессии |
| `/summary [show\|clear]` | показать или удалить сводку |
| `/export [путь]` | экспорт истории, фактов и предложений в JSON |
| `/delete <id\|all>` | удалить сессию или все данные |
| `/remember <текст>` | предложить факт и подтвердить сохранение |
| `/fact add <текст>` | сохранить подтверждённый факт |
| `/facts` | список фактов |
| `/fact pending` | факты, ожидающие подтверждения |
| `/fact accept <id>` | подтвердить предложенный факт |
| `/fact reject <id>` | отклонить предложенный факт |
| `/fact edit <id> <текст>` | изменить факт |
| `/fact del <id>` | удалить факт |
| `/fact clear` | удалить все факты |
| `/model [имя]` | показать/сменить модель |
| `/provider [ollama\|cloud]` | показать/выбрать провайдера |
| `/cloud on\|off` | разрешить/запретить облако |
| `/stream on\|off` | потоковый вывод |
| `/voice [status\|stop\|profile <имя>]` | состояние голоса, стоп, профиль |
| `/listen [секунды]` | записать, распознать и отправить |
| `/say <текст>` | озвучить текст |
| `/tools` | список разрешённых инструментов |
| `/sysinfo` | системная информация |
| `/notify <текст>` | уведомление на рабочем столе |
| `/open <app> [аргументы]` | запуск приложения из allowlist |
| `/web <запрос>` | веб-поиск и ответ по реальным источникам |
| `/copy [текст]` | скопировать текст или последний ответ |
| `/screenshot` | сделать скриншот |
| `/volume [0-150]` | показать или изменить громкость |
| `/media <action>` | play-pause, next, previous, stop |
| `/openurl <url>` | открыть http/https ссылку |
| `/mood [настроение]` | `calm`, `friendly`, `technical`, `supportive` |
| `/tone <параметр> <0..1>` | familiarity, verbosity или initiative |
| `/character [reset]` | показать или сбросить характер |
| `/reset` | сбросить настроение и параметры стиля |
| `/persona [edit\|reset\|presets\|preset <имя>]` | персона и пресеты |
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
5. Факты можно редактировать: `/fact edit <id> <текст>` или кнопка «Изменить»
   в GUI.

Факты, история текущей сессии и найденные фрагменты прошлых диалогов
подмешиваются в системный промпт следующего запроса. После перезапуска
продолжается последняя сессия, а факты остаются доступны.

Для длинных диалогов: `/summarize` создаёт локальную сводку сессии. Когда
история не помещается в `history_limit`, сохранённая сводка автоматически
добавляется к контексту, чтобы старые договорённости не терялись. В GUI — кнопка
«Сводка» на вкладке истории. Сводка не отправляется в облако без
`privacy.send_history_to_cloud`.

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

## Персоны и голосовые профили

Доступны два пресета персоны:

```
/persona presets
/persona preset kurisu
/persona preset amadeus
```

`kurisu` — оригинальная интерпретация: уверенная учёная с язвительным
цундэре-характером. Это **не** копия официального персонажа, не клонирование
голоса сэйю и не использование защищённого арта. В обычном диалоге ассистент
держится роли, но честно отвечает, что он ИИ, если спросить прямо.

Голосовой профиль меняет темп, шум и тон открытого Piper-голоса:

```
/voice profile kurisu
/voice profile default
```

В GUI: «Настройки → Персона → Применить пресет» и «Профиль голоса».
Для профиля `kurisu` используется русский Piper-голос `irina` с ускорением,
лёгким сдвигом тона и большей вариативностью интонации. Это похожий по вайбу
голос, а не голос актрисы. Можно указать собственный легальный Piper-голос в
`[voice].tts_model`.

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
  ключ найден и `cloud_fallback = true`; пользователь получает уведомление;
- в облачном режиме результаты инструментов (например, `system_info` или
  `web_search`) могут уйти провайдеру вместе с запросом.

## Тесты

```bash
source .venv/bin/activate
pytest
```

Покрыты память, предложения и подтверждение фактов, экспорт, настройки,
характер, провайдеры, маршрутизация, приватность контекста, разрешения
инструментов, голосовые адаптеры, системные инструменты, вызов инструментов
моделью, веб-поиск (парсер, редиректы, ошибки), сводки сессий, системные
действия, benchmark, диагностика, приватность и GUI (offscreen-тесты PySide6).
Покрыты также персоны и голосовые профили. Coverage проверяется в CI (порог 60%).

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

**Нужно приложить диагностику к ошибке**

```bash
amadeus --diagnose > amadeus-diagnose.txt
tail -n 100 ~/.local/state/amadeus/amadeus.log
```

`--diagnose` не выводит API-ключи и тексты диалогов.

**Веб-поиск не работает**

Проверьте сеть и повторите запрос: провайдер может ограничивать частоту.
Можно отключить библиотечный режим (`use_library = false`) и использовать
HTML-резерв, либо увеличить `timeout`. Локальный диалог без `/web` работает
независимо от интернета.

**Уведомления не работают**

Нужен `notify-send` (libnotify) и демон уведомлений (например, dunst,
mako или встроенный в окружение). Проверьте вручную:
`notify-send "Amadeus" "тест"`.

**Голос не настроен**

Проверьте `/voice status` в CLI. Убедитесь, что `whisper-cli` и `piper` есть в
PATH, а файлы моделей существуют по путям из `[voice]`. Для русского языка
модель `ggml-base` может ошибаться чаще, чем `ggml-small`.

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
│   ├── tools/               # реестр, уведомления, приложения, system info, web
│   ├── storage/             # пути platformdirs
│   ├── ui/                  # PySide6: окно, чат, настройки
│   └── voice/               # запись, whisper.cpp STT, Piper TTS, плеер
├── packaging/               # .desktop, иконка, автозапуск, PKGBUILD
├── .github/workflows/       # CI и release
├── config/hyprland.conf.example
├── Makefile
├── CHANGELOG.md
├── LICENSE
├── tests/
└── docs/                    # architecture, security, installation, benchmark
```

## Этапы по ТЗ

- [x] Этап 1 — текстовое ядро: CLI, Ollama, промпт, SQLite, история, ошибки.
- [x] Этап 2 — память и личность: подтверждение фактов, экспорт, характер.
- [x] Этап 3 — GUI на PySide6: чат, история, настройки, статус, Hyprland.
- [x] Этап 4 — голос: запись, whisper.cpp STT, Piper TTS, остановка озвучки.
- [x] Этап 5 — инструменты: уведомления, приложения, system info, подтверждения.
- [x] Этап 6 — веб-поиск с источниками и безопасная интеграция с моделью.
- [x] Этап 7 — диагностика, benchmark, логи, тесты ошибок, установка, autostart.
- [x] Этап 8 — умная память: сводки сессий, редактирование фактов.
- [x] Этап 9 — системные действия Wayland.
- [x] Этап 10 — упаковка, CI и релиз.

MVP по ТЗ завершён; этапы 8–10 — развитие сверх ТЗ. Версия 1.2.0:
Kurisu-персона/голос по умолчанию и фоновый режим.

## Безопасность

Модель не получает произвольный shell и не сохраняет факты без подтверждения.
GUI и CLI используют общую политику памяти и приватности. Инструменты
выполняются только через реестр с allowlist и проверкой риска; запуск
приложений требует подтверждения, произвольный shell недоступен. Интернет-текст
считается недоверенным. Голосовые записи удаляются после распознавания, логи не
содержат ключей и диалогов. Подробнее — `docs/security.md`.
