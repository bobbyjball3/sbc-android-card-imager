from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import sbc_imager.cli as cli_module
from sbc_imager.cli import app
from sbc_imager.errors import ConfigError

runner = CliRunner()

SUBCOMMANDS = ("platforms", "plan", "fetch", "build", "verify", "image")


def test_platforms_json_when_requested_prints_parseable_registry() -> None:
    result = runner.invoke(app, ["platforms", "--json"])

    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert len(rows) == 51
    assert {"tag": "GBA", "platform": "Game Boy Advance"} in rows
    assert result.stderr == ""


def test_platforms_when_requested_renders_table_with_registry_tags() -> None:
    result = runner.invoke(app, ["platforms"])

    assert result.exit_code == 0
    assert "GBA" in result.stdout
    assert "Game Boy Advance" in result.stdout


@pytest.mark.parametrize("command", SUBCOMMANDS)
def test_subcommand_help_when_requested_exits_zero(command: str) -> None:
    result = runner.invoke(app, [command, "--help"])

    assert result.exit_code == 0
    assert command in result.stdout


def test_plan_when_invoked_reports_not_implemented_on_stderr() -> None:
    result = runner.invoke(app, ["plan"])

    assert result.exit_code == 2
    assert "not implemented" in result.stderr.lower()
    assert result.stdout == ""


def test_unknown_command_when_invoked_exits_two() -> None:
    result = runner.invoke(app, ["nope"])

    assert result.exit_code == 2
    assert "No such command" in result.stderr


def test_unknown_flag_when_passed_exits_two() -> None:
    result = runner.invoke(app, ["--definitely-not-a-flag"])

    assert result.exit_code == 2


def test_platforms_when_registry_raises_config_error_prints_hint_and_exits_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_config_error() -> list[dict[str, str]]:
        raise ConfigError("bad tag", "use a valid Cannoli tag")

    monkeypatch.setattr(cli_module, "_platform_rows", raise_config_error)

    result = runner.invoke(app, ["platforms", "--json"])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Error: bad tag" in result.stderr
    assert "Hint: use a valid Cannoli tag" in result.stderr
    assert "Traceback" not in result.stderr


def test_verbose_when_config_error_raised_prints_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_config_error() -> list[dict[str, str]]:
        raise ConfigError("bad tag", "use a valid Cannoli tag")

    monkeypatch.setattr(cli_module, "_platform_rows", raise_config_error)

    result = runner.invoke(app, ["--verbose", "platforms", "--json"])

    assert result.exit_code == 2
    assert "Traceback" in result.stderr


def test_version_when_requested_prints_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_help_when_requested_lists_every_subcommand() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in SUBCOMMANDS:
        assert command in result.stdout
