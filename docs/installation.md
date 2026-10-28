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

Отключить автозапуск: удалить `~/.config/autostart/amadeus.desktop`.
В Hyprland аналог — `exec-once = amadeus-gui` в `hyprland.conf`.

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
