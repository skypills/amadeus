# Changelog

## 1.2.0 — 2026-10-29

- Kurisu-персона и голосовой профиль включены по умолчанию.
- Автоозвучивание ответов по умолчанию.
- Фоновый режим GUI: трей, `--background`, `--toggle`, единственный экземпляр.
- Закрытие окна сворачивает в трей; автозапуск через `.desktop`.
- Горячая клавиша Hyprland обновлена на `amadeus-gui --toggle`.

## 1.1.0 — 2026-10-29

- Персоны `amadeus` и `kurisu` (оригинальная интерпретация, не копия).
- Голосовые профили: темп, noise_scale, noise_w и сдвиг тона через ffmpeg.
- Переключение в CLI (`/persona preset`, `/voice profile`) и GUI.
- Исправлен parecord: позиционный путь к WAV.
- Реальная проверка Ollama, whisper.cpp, Piper, Wayland GUI и PKGBUILD.

## 1.0.0 — 2026-10-28

Первый стабильный релиз Amadeus.

- CLI и PySide6 GUI на общем ядре.
- Ollama, потоковый вывод, облачный резерв с явным включением.
- SQLite-история, FTS5-поиск, подтверждаемые факты, сводки сессий.
- Характер: настроение, familiarity, verbosity, initiative, persona.md.
- Локальный голос: whisper.cpp STT, Piper TTS, запись и остановка озвучки.
- Инструменты: system info, уведомления, allowlist приложений, веб-поиск.
- Системные действия Wayland: буфер обмена, скриншоты, громкость, медиа, URL.
- Диагностика, benchmark, логи с ротацией, autostart и документация установки.
- CI на Python 3.12–3.14, сборка wheel/sdist, PKGBUILD и release workflow.
