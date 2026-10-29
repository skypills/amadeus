# Установка Amadeus на CachyOS

Пошаговая инструкция для чистого окружения. Все команды выполняются от
обычного пользователя; root не нужен.

## 1. Проверка оборудования

```bash
free -h
lscpu | grep -E 'Model name|CPU\(s\)'
lspci | grep -Ei 'VGA|3D|Display'
```

Ориентиры для 16 ГБ ОЗУ:

- 3B–4B в квантовании — безопасный старт;
- 7B–8B — только если после запуска ОС и браузера остаётся достаточно памяти;
- не запускайте несколько тяжёлых моделей одновременно.

## 2. Ollama и модель

```bash
pacman -Ss ollama
sudo pacman -S ollama
sudo systemctl enable --now ollama
# или пользовательский сервис, если так настроен пакет:
# systemctl --user enable --now ollama
ollama pull qwen2.5:3b-instruct
amadeus --status
```

Для NVIDIA/AMD проверьте варианты пакета (`ollama-cuda`, `ollama-rocm`) и
убедитесь, что `ollama ps` показывает загрузку на GPU.

Если sudo недоступен, можно распаковать официальный `ollama-linux-amd64.tar.zst`
в `~/.local/ollama`, поставить бинарник в `~/.local/bin` и запустить
пользовательский сервис `packaging/ollama-user.service`.

## 3. Python-окружение

```bash
cd ~/amadeus
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

PySide6 и `ddgs` устанавливаются как зависимости. Проверка:

```bash
amadeus --version
amadeus-gui --version
```

## 4. Первый запуск

```bash
amadeus
# или
amadeus-gui
```

Создаются:

```
~/.config/amadeus/settings.toml
~/.config/amadeus/persona.md
~/.local/share/amadeus/amadeus.db
~/.local/state/amadeus/amadeus.log
```

## 5. Голос (опционально)

Установите whisper.cpp, Piper и модели, затем проверьте:

```bash
amadeus
# в CLI:
/voice
```

Подробные команды и ссылки на модели — в разделе «Голос» в `README.md`.
Голос не обязателен: без него работают чат, память, инструменты и веб-поиск.

## 5.1. Системные действия (опционально)

Для действий из GUI/CLI установите по необходимости:

```bash
sudo pacman -S wl-clipboard grim wireplumber playerctl xdg-utils
```

- `wl-copy` — буфер обмена Wayland;
- `grim` — скриншоты Wayland (альтернативы: spectacle, gnome-screenshot, scrot);
- `wpctl` — громкость (wireplumber);
- `playerctl` — управление медиаплеером;
- `xdg-open` — открытие ссылок.

Скриншоты сохраняются в `~/.local/share/amadeus/screenshots/` и требуют
подтверждения. Скриншот и открытие URL не вызываются моделью автоматически.

## 6. Горячий вызов и автозапуск GUI

Hyprland:

```ini
# ~/.config/hypr/hyprland.conf
bind = SUPER, A, exec, amadeus-gui
```

Ярлык в меню:

```bash
install -Dm644 packaging/amadeus.desktop ~/.local/share/applications/amadeus.desktop
install -Dm644 packaging/amadeus.svg \
  ~/.local/share/icons/hicolor/scalable/apps/amadeus.svg
update-desktop-database ~/.local/share/applications 2>/dev/null || true
```

Автозапуск GUI после входа в сессию (необязательно):

```bash
install -Dm644 packaging/amadeus-autostart.desktop \
  ~/.config/autostart/amadeus.desktop
```

Файл запускает `amadeus-gui --background`: окно скрыто, приложение живёт в трее.
Горячая клавиша `amadeus-gui --toggle` показывает или скрывает его.

Отключить автозапуск: удалить `~/.config/autostart/amadeus.desktop`.
В Hyprland аналог — `exec-once = amadeus-gui` в `hyprland.conf`.

## 6.1. Фоновый режим

```bash
amadeus-gui --background   # скрытый запуск
amadeus-gui --toggle       # показать/скрыть
```

Второй экземпляр не создаётся: `--toggle` общается с уже запущенным процессом.
Закрытие окна сворачивает в трей, если доступен `QSystemTrayIcon`; иначе
приложение завершается. Постоянного прослушивания микрофона нет — запись
запускается явно.

## 7. Диагностика и benchmark

```bash
amadeus --diagnose
amadeus --benchmark
amadeus --benchmark --benchmark-out ~/amadeus-bench.json
```

`--diagnose` печатает железо, пути, статус модели, голоса и счётчики данных;
секреты не выводятся. `--benchmark` измеряет первый токен и скорость генерации.
Подробнее — `docs/benchmark.md`.

## 8. Логи

```
~/.local/state/amadeus/amadeus.log
```

Лог ротируется, не содержит API-ключей и текстов диалогов. Для диагностики
приложите вывод `amadeus --diagnose` и хвост лога.

## 8.1. Установка из пакета

```bash
python -m build
pip install dist/amadeus-1.3.0-py3-none-any.whl
```

Arch/CachyOS:

```bash
cd packaging
makepkg -si
```

PKGBUILD ставит `amadeus-git`, `.desktop` и иконку. Зависимости перечислены в
`packaging/README.md`.

## 9. Обновление и удаление

```bash
cd ~/amadeus
git pull
source .venv/bin/activate
pip install -e ".[dev]"
```

Удаление приложения: удалить каталог проекта и venv. Пользовательские данные
удаляются отдельно:

```bash
rm -rf ~/.config/amadeus ~/.local/share/amadeus ~/.local/state/amadeus
```

Перед удалением истории сделайте экспорт: `/export` в CLI или
«Файл → Экспорт данных» в GUI.
