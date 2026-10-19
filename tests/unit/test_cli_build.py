from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import sbc_imager.cli as cli_module
from sbc_imager import build as build_module
from sbc_imager.build import BuildOptions, BuildReport
from sbc_imager.cli import app
from sbc_imager.errors import (
    AssemblerError,
    ConfigError,
    SafetyError,
    SbcImagerError,
    VerificationError,
)
from sbc_imager.validation import Warning
from sbc_imager.verify import VerifyReport

runner = CliRunner()


def _manifest(tmp_path: Path) -> Path:
    path = tmp_path / "imager.toml"
    path.write_text('[image]\nname = "demo"\n', encoding="utf-8")
    return path


def _report(tmp_path: Path) -> BuildReport:
    return BuildReport(
        manifest=str(tmp_path / "imager.toml"),
        image=str((tmp_path / "card.img").resolve()),
        image_bytes=65 * 1024 * 1024,
        partition_bytes=64 * 1024 * 1024,
        offset=1024 * 1024,
        content_files=2,
        content_bytes=10,
        sha256="a" * 64,
        verify=VerifyReport(expected_files=2, actual_files=2),
        sources=(),
        warnings=(Warning("unused-source", "source 'x' is unused", 0),),
    )


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    report: BuildReport | None = None,
    error: SbcImagerError | None = None,
    log_line: str | None = None,
) -> dict[str, BuildOptions]:
    seen: dict[str, BuildOptions] = {}

    def fake(options: BuildOptions, *, log: build_module.Log = print) -> BuildReport:
        seen["options"] = options
        if log_line is not None:
            log(log_line)
        if error is not None:
            raise error
        assert report is not None
        return report

    monkeypatch.setattr(cli_module, "build_image", fake)
    return seen


def test_build_when_options_given_forwards_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path)
    report = _report(tmp_path)
    seen = _patch(monkeypatch, report=report)
    output = tmp_path / "out.img"

    result = runner.invoke(
        app,
        [
            "build",
            "--manifest",
            str(manifest),
            "--output",
            str(output),
            "--size",
            "64MiB",
            "--reserve",
            "2MiB",
            "--offline",
            "--force",
            "--keep-work",
            "--allow-branch",
        ],
    )

    assert result.exit_code == 0, result.stderr
    options = seen["options"]
    assert options.manifest_path == manifest
    assert options.output == output
    assert options.size == "64MiB"
    assert options.reserve == "2MiB"
    assert options.offline is True
    assert options.force is True
    assert options.keep_work is True
    assert options.allow_branch is True


def test_build_when_options_absent_passes_none_and_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path)
    seen = _patch(monkeypatch, report=_report(tmp_path))

    result = runner.invoke(app, ["build", "--manifest", str(manifest)])

    assert result.exit_code == 0, result.stderr
    options = seen["options"]
    assert options.output is None
    assert options.size is None
    assert options.reserve is None
    assert options.offline is False
    assert options.force is False
    assert options.keep_work is False
    assert options.allow_branch is False


def test_build_when_json_requested_prints_only_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path)
    report = _report(tmp_path)
    _patch(monkeypatch, report=report, log_line="staged files")

    result = runner.invoke(app, ["build", "--manifest", str(manifest), "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == report.payload()
    assert "staged files" in result.stderr


def test_build_when_human_output_requested_prints_summary_to_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path)
    report = _report(tmp_path)
    _patch(monkeypatch, report=report, log_line="staged files")

    result = runner.invoke(app, ["build", "--manifest", str(manifest)])

    assert result.exit_code == 0
    assert report.image in result.stdout
    assert "Verified" in result.stdout
    assert "staged files" in result.stderr


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ConfigError("bad manifest"), 2),
        (SafetyError("refusing to overwrite"), 2),
        (AssemblerError("docker failed"), 1),
        (VerificationError("tree mismatch"), 1),
    ],
)
def test_build_when_pipeline_error_uses_stable_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: SbcImagerError, code: int
) -> None:
    manifest = _manifest(tmp_path)
    _patch(monkeypatch, error=error)

    result = runner.invoke(app, ["build", "--manifest", str(manifest)])

    assert result.exit_code == code
    assert f"Error: {error.message}" in result.stderr


def test_build_when_manifest_is_missing_exits_two() -> None:
    result = runner.invoke(app, ["build", "--manifest", "does-not-exist.toml"])

    assert result.exit_code == 2


def test_build_help_when_requested_lists_every_option() -> None:
    result = runner.invoke(app, ["build", "--help"])

    assert result.exit_code == 0
    for option in (
        "--manifest",
        "--output",
        "--size",
        "--reserve",
        "--offline",
        "--force",
        "--keep-work",
        "--allow-branch",
        "--json",
    ):
        assert option in result.stdout
