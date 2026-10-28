# Пакетирование

## Wheel/sdist

```bash
python -m build
pip install dist/amadeus-1.0.0-py3-none-any.whl
```

Wheel содержит Python-код и console scripts `amadeus`, `amadeus-gui`.
Шаблоны настроек создаются при первом запуске; `.desktop` и иконка лежат в
`packaging/` и устанавливаются отдельно (или через PKGBUILD).

## Arch/CachyOS (PKGBUILD)

```bash
cd packaging
makepkg -si
```

PKGBUILD собирает `amadeus-git` из GitHub и ставит `.desktop` и иконку.
Зависимости: `python`, `python-platformdirs`, `pyside6`, `python-ddgs`.
Если `python-ddgs` отсутствует в репозиториях, установите его из AUR или
`pipx`/venv.

## CI и релиз

- `.github/workflows/ci.yml` — lint, format, тесты и coverage на Python
  3.12–3.14, сборка wheel/sdist.
- `.github/workflows/release.yml` — по тегу `v*` собирает пакеты и создаёт
  GitHub Release.

Релиз:

```bash
git tag v1.0.0
git push origin v1.0.0
```
