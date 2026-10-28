from __future__ import annotations

import tomllib
from pathlib import Path

from amadeus import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_consistent():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert project["version"] == __version__
    assert __version__ == "1.0.0"


def test_entry_points_defined():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        scripts = tomllib.load(handle)["project"]["scripts"]
    assert scripts["amadeus"] == "amadeus.cli:main"
    assert scripts["amadeus-gui"] == "amadeus.ui.window:main"


def test_makefile_has_core_targets():
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("install:", "test:", "lint:", "build:", "gui:", "diagnose:"):
        assert target in text


def test_pkgbuild_metadata():
    text = (ROOT / "packaging" / "PKGBUILD").read_text(encoding="utf-8")
    assert "pkgname=amadeus-git" in text
    assert "python-installer" in text
    assert "amadeus.desktop" in text


def test_ci_and_release_workflows_exist():
    assert (ROOT / ".github" / "workflows" / "ci.yml").exists()
    assert (ROOT / ".github" / "workflows" / "release.yml").exists()


def test_license_and_changelog_exist():
    assert "MIT License" in (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "## 1.0.0" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
