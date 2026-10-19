from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import sbc_imager.cli_verify as cli_verify_module
from sbc_imager.cli import app
from sbc_imager.errors import ConfigError
from sbc_imager.verify import VerifyReport

runner = CliRunner()


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    image = tmp_path / "card.img"
    image.write_bytes(b"image")
    manifest = tmp_path / "imager.toml"
    manifest.write_text('[image]\nname = "demo"\n', encoding="utf-8")
    return image, manifest


def _invoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    report: VerifyReport | None = None,
    error: Exception | None = None,
    extra: tuple[str, ...] = (),
):
    image, manifest = _paths(tmp_path)

    def fake(*args: object, **kwargs: object) -> VerifyReport:
        del args, kwargs
        if error is not None:
            raise error
        assert report is not None
        return report

    monkeypatch.setattr(cli_verify_module, "verify_image", fake)
    return runner.invoke(
        app,
        ["verify", "--image", str(image), "--manifest", str(manifest), *extra],
    )


def _ok_report() -> VerifyReport:
    return VerifyReport(expected_files=3, actual_files=3)


def _fail_report() -> VerifyReport:
    return VerifyReport(
        expected_files=3,
        actual_files=2,
        missing=("Cannoli/Roms/GBA/demo.gba",),
    )


def test_verify_when_image_matches_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _invoke(tmp_path, monkeypatch, report=_ok_report())

    assert result.exit_code == 0
    assert "passed" in result.stdout.lower()
    assert "Cannoli/Roms/GBA/demo.gba" not in result.stdout


def test_verify_when_image_mismatches_exits_one_and_lists_problems(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _invoke(tmp_path, monkeypatch, report=_fail_report())

    assert result.exit_code == 1
    assert "failed" in result.stdout.lower()
    assert "Cannoli/Roms/GBA/demo.gba" in result.stdout


def test_verify_when_config_error_raised_exits_two_with_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _invoke(
        tmp_path,
        monkeypatch,
        error=ConfigError("bad manifest", "fix the tag"),
    )

    assert result.exit_code == 2
    assert "Error: bad manifest" in result.stderr
    assert "Hint: fix the tag" in result.stderr


def test_verify_when_json_requested_prints_only_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _invoke(tmp_path, monkeypatch, report=_ok_report(), extra=("--json",))

    assert result.exit_code == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload == {
        "ok": True,
        "expected_files": 3,
        "actual_files": 3,
        "missing": [],
        "extra": [],
        "mismatched": [],
        "missing_dirs": [],
    }


def test_verify_when_json_and_mismatch_still_exits_one_with_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _invoke(tmp_path, monkeypatch, report=_fail_report(), extra=("--json",))

    assert result.exit_code == 1
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["missing"] == ["Cannoli/Roms/GBA/demo.gba"]


@pytest.mark.parametrize("missing", ["--image", "--manifest"])
def test_verify_when_required_option_is_missing_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    image, manifest = _paths(tmp_path)
    options = {
        "--image": str(image),
        "--manifest": str(manifest),
    }
    del options[missing]

    result = runner.invoke(
        app,
        ["verify", *[part for pair in options.items() for part in pair]],
    )

    assert result.exit_code == 2
    assert missing in result.stderr


def test_verify_help_when_requested_exits_zero() -> None:
    result = runner.invoke(app, ["verify", "--help"])

    assert result.exit_code == 0
    for option in ("--image", "--manifest", "--offline", "--allow-branch", "--json"):
        assert option in result.stdout
