"""Packaging contract tests for the installed distribution."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

import sbc_imager
from sbc_imager.cli import app

DISTRIBUTION_NAME = "sbc-android-card-imager"
ENTRY_POINT_NAME = "sbc-imager"


def test_version_when_installed_metadata_matches_package_version() -> None:
    assert importlib.metadata.version(DISTRIBUTION_NAME) == sbc_imager.__version__


def test_metadata_when_installed_uses_distribution_name() -> None:
    metadata = importlib.metadata.metadata(DISTRIBUTION_NAME)

    assert metadata["Name"] == DISTRIBUTION_NAME
    assert metadata["Version"] == sbc_imager.__version__


def test_console_script_when_installed_targets_cli_app() -> None:
    entry_points = {
        entry_point.name: entry_point
        for entry_point in importlib.metadata.entry_points(group="console_scripts")
    }
    entry_point = entry_points.get(ENTRY_POINT_NAME)

    assert entry_point is not None
    assert entry_point.value == "sbc_imager.cli:app"
    assert entry_point.load() is app


def test_py_typed_when_installed_ships_with_package() -> None:
    package_dir = Path(sbc_imager.__file__).parent

    assert (package_dir / "py.typed").is_file()
