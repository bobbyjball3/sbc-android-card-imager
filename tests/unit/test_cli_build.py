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
from sbc_imager.imaging import DiskAssessment, DiskInfo
from sbc_imager.validation import Warning
from sbc_imager.verify import VerifyReport

runner = CliRunner()
MIB = 1024 * 1024
DISK5_BYTES = 511_868_665_856


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


def _disk(identifier: str = "disk9", size: int = 64 * 1024**3) -> DiskInfo:
    return DiskInfo(
        identifier=identifier,
        size=size,
        label="SDCARD",
        model="SanDisk Ultra",
        protocol="USB",
        internal=False,
        removable=True,
        ejectable=True,
        whole=True,
        serial="0123456789AB",
    )


def _builtin_sd(identifier: str = "disk5") -> DiskInfo:
    return DiskInfo(
        identifier=identifier,
        size=DISK5_BYTES,
        label="",
        model="Built In SDXC Reader",
        protocol="Secure Digital",
        internal=True,
        removable=True,
        ejectable=True,
        whole=True,
    )


def _assessment(
    disk: DiskInfo,
    *,
    allowed: bool = True,
    reason: str = "external removable disk",
) -> DiskAssessment:
    return DiskAssessment(
        disk=disk,
        allowed=allowed,
        status="allowed" if allowed else "blocked",
        reason=reason,
    )


def _patch_assess(
    monkeypatch: pytest.MonkeyPatch,
    assessments: list[DiskAssessment],
) -> dict[str, bool]:
    seen: dict[str, bool] = {}

    def fake_assess(_runner: object, *, allow_builtin_sd: bool = False) -> list[DiskAssessment]:
        seen["allow_builtin_sd"] = allow_builtin_sd
        return list(assessments)

    monkeypatch.setattr(cli_module, "assess_disks", fake_assess)
    return seen


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
    assert options.progress == "auto"


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
        "--device",
        "--expand",
        "--allow-builtin-sd",
        "--progress",
        "--offline",
        "--force",
        "--keep-work",
        "--allow-branch",
        "--json",
    ):
        assert option in result.stdout


def test_build_when_progress_mode_given_forwards_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path)
    seen = _patch(monkeypatch, report=_report(tmp_path))

    result = runner.invoke(
        app,
        ["build", "--manifest", str(manifest), "--progress", "json"],
    )

    assert result.exit_code == 0, result.stderr
    assert seen["options"].progress == "json"


def test_build_when_progress_mode_is_invalid_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path)
    seen = _patch(monkeypatch, report=_report(tmp_path))

    result = runner.invoke(
        app,
        ["build", "--manifest", str(manifest), "--progress", "loud"],
    )

    assert result.exit_code == 2
    assert "unsupported progress mode" in result.stderr
    assert seen == {}


def test_build_when_progress_json_wraps_normal_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path)
    _patch(monkeypatch, report=_report(tmp_path), log_line="staged files")

    result = runner.invoke(
        app,
        ["build", "--manifest", str(manifest), "--progress", "json"],
    )

    assert result.exit_code == 0, result.stderr
    assert '"event": "log"' in result.stderr
    assert '"message": "staged files"' in result.stderr


def test_build_expand_when_builtin_sd_forwards_exact_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path)
    seen = _patch(monkeypatch, report=_report(tmp_path))
    assessed = _patch_assess(monkeypatch, [_assessment(_builtin_sd())])

    result = runner.invoke(
        app,
        [
            "build",
            "--manifest",
            str(manifest),
            "--device",
            "/dev/disk5",
            "--allow-builtin-sd",
            "--expand",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert seen["options"].size == "488156MiB"
    assert assessed["allow_builtin_sd"] is True


@pytest.mark.parametrize("device", ["disk5", "/dev/disk5", "/dev/rdisk5"])
def test_build_expand_device_forms_normalize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, device: str
) -> None:
    manifest = _manifest(tmp_path)
    seen = _patch(monkeypatch, report=_report(tmp_path))
    _patch_assess(monkeypatch, [_assessment(_builtin_sd())])

    result = runner.invoke(
        app,
        [
            "build",
            "--manifest",
            str(manifest),
            "--device",
            device,
            "--allow-builtin-sd",
            "--expand",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert seen["options"].size == "488156MiB"


def test_build_expand_when_size_is_not_mib_aligned_rounds_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path)
    seen = _patch(monkeypatch, report=_report(tmp_path))
    _patch_assess(
        monkeypatch,
        [_assessment(_disk(size=100 * MIB + 12_345))],
    )

    result = runner.invoke(
        app,
        [
            "build",
            "--manifest",
            str(manifest),
            "--device",
            "disk9",
            "--expand",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert seen["options"].size == "100MiB"


@pytest.mark.parametrize(
    ("extra_args", "message"),
    [
        (["--expand"], "--expand requires --device"),
        (["--device", "/dev/disk9"], "--device is only valid with --expand"),
        (
            ["--size", "64MiB", "--device", "/dev/disk9", "--expand"],
            "--size cannot be combined with --expand",
        ),
        (["--allow-builtin-sd"], "--allow-builtin-sd requires --device"),
        (
            ["--expand", "--allow-builtin-sd"],
            "--allow-builtin-sd requires --device",
        ),
    ],
)
def test_build_expand_invalid_flag_combinations_exit_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_args: list[str],
    message: str,
) -> None:
    manifest = _manifest(tmp_path)
    seen = _patch(monkeypatch, report=_report(tmp_path))
    assessed = _patch_assess(monkeypatch, [_assessment(_disk())])

    result = runner.invoke(
        app,
        ["build", "--manifest", str(manifest), *extra_args],
    )

    assert result.exit_code == 2
    assert message in result.stderr
    assert seen == {}
    assert assessed == {}


@pytest.mark.parametrize(
    ("disk", "allow", "reason"),
    [
        (_disk("disk0"), True, "internal disk"),
        (_disk("disk4"), False, "virtual disk"),
        (_disk("disk10"), False, "boot disk"),
        (_builtin_sd("disk5"), False, "internal SD reader"),
    ],
)
def test_build_expand_when_disk_is_unsafe_exits_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    disk: DiskInfo,
    allow: bool,
    reason: str,
) -> None:
    manifest = _manifest(tmp_path)
    seen = _patch(monkeypatch, report=_report(tmp_path))
    _patch_assess(
        monkeypatch,
        [_assessment(disk, allowed=False, reason=reason)],
    )
    args = [
        "build",
        "--manifest",
        str(manifest),
        "--device",
        disk.identifier,
        "--expand",
    ]
    if allow:
        args.append("--allow-builtin-sd")

    result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert reason in result.stderr
    assert "image --list" in result.stderr
    assert seen == {}


def test_build_expand_when_device_is_unknown_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path)
    seen = _patch(monkeypatch, report=_report(tmp_path))
    _patch_assess(monkeypatch, [_assessment(_disk())])

    result = runner.invoke(
        app,
        [
            "build",
            "--manifest",
            str(manifest),
            "--device",
            "/dev/disk99",
            "--expand",
        ],
    )

    assert result.exit_code == 2
    assert "not a whole disk" in result.stderr
    assert "image --list" in result.stderr
    assert seen == {}


def test_build_expand_when_device_is_malformed_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path)
    seen = _patch(monkeypatch, report=_report(tmp_path))
    _patch_assess(monkeypatch, [_assessment(_disk())])

    result = runner.invoke(
        app,
        ["build", "--manifest", str(manifest), "--device", "rdisk5", "--expand"],
    )

    assert result.exit_code == 2
    assert "invalid device" in result.stderr
    assert seen == {}


def test_build_expand_when_disk_is_too_small_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path)
    seen = _patch(monkeypatch, report=_report(tmp_path))
    _patch_assess(monkeypatch, [_assessment(_disk(size=2 * MIB - 1))])

    result = runner.invoke(
        app,
        ["build", "--manifest", str(manifest), "--device", "disk9", "--expand"],
    )

    assert result.exit_code == 2
    assert "too small" in result.stderr
    assert seen == {}
