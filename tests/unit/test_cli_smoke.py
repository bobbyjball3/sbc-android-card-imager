from typer.testing import CliRunner

from sbc_imager.cli import app

runner = CliRunner()


def test_version_when_requested_exits_zero_and_prints_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_help_when_requested_exits_zero() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0


def test_unknown_flag_when_passed_exits_two() -> None:
    result = runner.invoke(app, ["--definitely-not-a-flag"])

    assert result.exit_code == 2
