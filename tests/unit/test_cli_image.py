from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

import sbc_imager.cli_image as cli_module
from sbc_imager.cli import app
from sbc_imager.imaging import DiskAssessment, DiskInfo
from sbc_imager.imaging_write import WriteResult
from sbc_imager.runner import Runner

runner = CliRunner()

_IMAGE_BYTES = b"fake-card-image-payload"
_SHA256 = hashlib.sha256(_IMAGE_BYTES).hexdigest()
_ROOT_HINT = "sudo -E uv run sbc-imager image ..."
_NO_DISKS = "no safe removable disks found; run `sbc-imager image --list` to inspect every disk"


@pytest.fixture(autouse=True)
def _root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)


def _disk(identifier: str = "disk9") -> DiskInfo:
    return DiskInfo(
        identifier=identifier,
        size=64 * 1024**3,
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
        size=511_868_665_856,
        label="",
        model="Built In SDXC Reader",
        protocol="Secure Digital",
        internal=True,
        removable=True,
        ejectable=True,
        whole=True,
        virtual_or_physical="Physical",
    )


def _internal(identifier: str = "disk0") -> DiskInfo:
    return DiskInfo(
        identifier=identifier,
        size=1_000_555_581_440,
        label="",
        model="APPLE SSD AP1024Z",
        protocol="Apple Fabric",
        internal=True,
        removable=False,
        ejectable=False,
        whole=True,
        virtual_or_physical="Unknown",
    )


def _virtual(identifier: str = "disk3") -> DiskInfo:
    return DiskInfo(
        identifier=identifier,
        size=994_662_584_320,
        label="",
        model="APPLE SSD AP1024Z",
        protocol="Apple Fabric",
        internal=True,
        removable=False,
        ejectable=False,
        whole=True,
        virtual_or_physical="Virtual",
    )


def _assessment(disk: DiskInfo, allowed: bool, reason: str) -> DiskAssessment:
    return DiskAssessment(disk, allowed, "allowed" if allowed else "blocked", reason)


def _image(tmp_path: Path) -> Path:
    path = tmp_path / "card.img"
    path.write_bytes(_IMAGE_BYTES)
    return path


def _result() -> WriteResult:
    return WriteResult(
        bytes_written=len(_IMAGE_BYTES),
        duration_s=0.5,
        avg_bytes_per_s=2 * len(_IMAGE_BYTES),
        image_sha256=_SHA256,
        device=Path("/dev/rdisk9"),
    )


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    disks: list[DiskInfo] | None = None,
    *,
    assessments: list[DiskAssessment] | None = None,
    interrupt: bool = False,
) -> list[tuple[Path, DiskInfo, Runner, bool]]:
    calls: list[tuple[Path, DiskInfo, Runner, bool]] = []

    def fake_enumerate(_runner: Runner, *, allow_builtin_sd: bool = False) -> list[DiskInfo]:
        return list(disks or [])

    def fake_assess(_runner: Runner, *, allow_builtin_sd: bool = False) -> list[DiskAssessment]:
        return list(assessments or [])

    def fake_write(
        image_path: Path,
        disk: DiskInfo,
        system_runner: Runner,
        *,
        allow_internal: bool = False,
    ) -> WriteResult:
        calls.append((image_path, disk, system_runner, allow_internal))
        if interrupt:
            raise KeyboardInterrupt
        return _result()

    monkeypatch.setattr(cli_module, "enumerate_disks", fake_enumerate)
    monkeypatch.setattr(cli_module, "assess_disks", fake_assess)
    monkeypatch.setattr(cli_module, "write_image", fake_write)
    return calls


def test_image_when_disk_and_confirmation_are_valid_writes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _image(tmp_path)
    calls = _patch(monkeypatch, [_disk()])

    result = runner.invoke(
        app,
        ["image", "--image", str(image)],
        input="1\nERASE disk9\n",
    )

    assert result.exit_code == 0, result.stderr
    assert len(calls) == 1
    assert calls[0][0] == image
    assert calls[0][1].identifier == "disk9"
    assert calls[0][3] is False
    assert "disk9" in result.stdout
    assert str(len(_IMAGE_BYTES)) in result.stdout
    assert _SHA256 in result.stdout
    assert "Duration" in result.stdout
    assert "Average speed" in result.stdout
    assert "/dev/rdisk9" in result.stdout


@pytest.mark.parametrize(
    "confirmation",
    [
        pytest.param("ERASE disk8", id="wrong-identifier"),
        pytest.param("", id="empty"),
        pytest.param("y", id="bare-y"),
        pytest.param("ERASE disk9 ", id="trailing-space"),
    ],
)
def test_image_when_confirmation_does_not_match_aborts_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    confirmation: str,
) -> None:
    image = _image(tmp_path)
    calls = _patch(monkeypatch, [_disk()])

    result = runner.invoke(
        app,
        ["image", "--image", str(image)],
        input=f"1\n{confirmation}\n",
    )

    assert result.exit_code == 2
    assert calls == []
    assert "Error:" in result.stderr
    assert "without writing" in result.stderr


def test_image_when_no_safe_disks_exist_aborts_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _image(tmp_path)
    calls = _patch(monkeypatch, [])

    result = runner.invoke(app, ["image", "--image", str(image)])

    assert result.exit_code == 2
    assert calls == []
    assert _NO_DISKS in result.stderr
    assert "image --list" in result.stderr


def test_image_when_no_disks_and_not_root_reports_the_missing_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 501)
    image = _image(tmp_path)
    calls = _patch(monkeypatch, [])

    result = runner.invoke(app, ["image", "--image", str(image)])

    assert result.exit_code == 2
    assert calls == []
    assert _NO_DISKS in result.stderr


@pytest.mark.parametrize("selection", ["0", "2", "abc", ""])
def test_image_when_disk_selection_is_invalid_aborts_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selection: str
) -> None:
    image = _image(tmp_path)
    calls = _patch(monkeypatch, [_disk()])

    result = runner.invoke(
        app,
        ["image", "--image", str(image)],
        input=f"{selection}\nERASE disk9\n",
    )

    assert result.exit_code == 2
    assert calls == []


def test_image_when_dry_run_prints_details_and_never_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _image(tmp_path)
    calls = _patch(monkeypatch, [_disk()])

    result = runner.invoke(
        app,
        ["image", "--image", str(image), "--dry-run"],
        input="1\n",
    )

    assert result.exit_code == 0, result.stderr
    assert calls == []
    assert "Dry run" in result.stdout
    assert "disk9" in result.stdout
    assert str(len(_IMAGE_BYTES)) in result.stdout
    assert _SHA256 in result.stdout
    assert "/dev/rdisk9" in result.stdout


def test_image_when_not_root_and_not_dry_run_refuses_with_sudo_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 501)
    image = _image(tmp_path)
    calls = _patch(monkeypatch, [_disk()])

    result = runner.invoke(app, ["image", "--image", str(image)])

    assert result.exit_code == 2
    assert calls == []
    assert _ROOT_HINT in result.stderr
    assert "requires root" in result.stderr


def test_image_when_not_root_but_dry_run_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 501)
    image = _image(tmp_path)
    calls = _patch(monkeypatch, [_disk()])

    result = runner.invoke(
        app,
        ["image", "--image", str(image), "--dry-run"],
        input="1\n",
    )

    assert result.exit_code == 0, result.stderr
    assert calls == []


def test_image_when_interrupted_exits_one_hundred_thirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _image(tmp_path)
    calls = _patch(monkeypatch, [_disk()], interrupt=True)

    result = runner.invoke(
        app,
        ["image", "--image", str(image)],
        input="1\nERASE disk9\n",
    )

    assert result.exit_code == 130
    assert len(calls) == 1


def test_image_list_when_called_without_image_or_root_shows_statuses_and_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 501)
    assessments = [
        _assessment(_internal(), False, "internal disk"),
        _assessment(_virtual(), False, "virtual disk"),
        _assessment(_builtin_sd(), False, "internal SD reader; re-run with --allow-builtin-sd"),
    ]
    calls = _patch(monkeypatch, assessments=assessments)

    result = runner.invoke(app, ["image", "--list"])

    assert result.exit_code == 0, result.stderr
    assert calls == []
    assert "disk0" in result.stdout
    assert "internal disk" in result.stdout
    assert "disk3" in result.stdout
    assert "virtual disk" in result.stdout
    assert "disk5" in result.stdout
    assert "--allow-builtin-sd" in result.stdout
    assert "blocked" in result.stdout


def test_image_list_with_allow_builtin_sd_shows_disk5_as_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 501)
    assessments = [
        _assessment(_internal(), False, "internal disk"),
        _assessment(_builtin_sd(), True, "internal SD reader (--allow-builtin-sd)"),
    ]
    calls = _patch(monkeypatch, assessments=assessments)

    result = runner.invoke(app, ["image", "--list", "--allow-builtin-sd"])

    assert result.exit_code == 0, result.stderr
    assert calls == []
    assert "disk5" in result.stdout
    assert "allowed" in result.stdout
    assert "internal SD reader" in result.stdout


@pytest.mark.parametrize("device", ["disk9", "/dev/disk9", "/dev/rdisk9"])
def test_image_explicit_device_when_safe_writes_once_and_skips_the_menu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, device: str
) -> None:
    image = _image(tmp_path)
    calls = _patch(
        monkeypatch,
        assessments=[_assessment(_disk(), True, "external removable disk")],
    )

    result = runner.invoke(
        app,
        ["image", "--image", str(image), "--device", device],
        input="ERASE disk9\n",
    )

    assert result.exit_code == 0, result.stderr
    assert len(calls) == 1
    assert calls[0][1].identifier == "disk9"
    assert calls[0][3] is False
    assert "Select a disk" not in result.stdout


@pytest.mark.parametrize("device", ["disk5", "/dev/disk5", "/dev/rdisk5"])
def test_image_explicit_builtin_sd_when_allowed_normalizes_the_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, device: str
) -> None:
    image = _image(tmp_path)
    calls = _patch(
        monkeypatch,
        assessments=[_assessment(_builtin_sd(), True, "internal SD reader (--allow-builtin-sd)")],
    )

    result = runner.invoke(
        app,
        ["image", "--image", str(image), "--device", device, "--allow-builtin-sd"],
        input="ERASE disk5\n",
    )

    assert result.exit_code == 0, result.stderr
    assert len(calls) == 1
    assert calls[0][1].identifier == "disk5"
    assert calls[0][3] is True


def test_image_explicit_disk5_without_allow_builtin_sd_is_rejected_with_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _image(tmp_path)
    reason = "internal SD reader; re-run with --allow-builtin-sd"
    calls = _patch(
        monkeypatch,
        assessments=[_assessment(_builtin_sd(), False, reason)],
    )

    result = runner.invoke(
        app,
        ["image", "--image", str(image), "--device", "/dev/disk5"],
        input="ERASE disk5\n",
    )

    assert result.exit_code == 2
    assert calls == []
    assert "internal SD reader" in result.stderr
    assert "image --list" in result.stderr


def test_image_explicit_internal_non_sd_is_rejected_even_with_allow_builtin_sd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _image(tmp_path)
    calls = _patch(
        monkeypatch,
        assessments=[_assessment(_internal(), False, "internal disk")],
    )

    result = runner.invoke(
        app,
        ["image", "--image", str(image), "--device", "/dev/disk0", "--allow-builtin-sd"],
        input="ERASE disk0\n",
    )

    assert result.exit_code == 2
    assert calls == []
    assert "internal disk" in result.stderr
    assert "image --list" in result.stderr


@pytest.mark.parametrize(
    ("disk", "reason"),
    [
        (_disk("disk10"), "boot disk"),
        (_internal("disk0"), "internal disk"),
    ],
)
def test_image_explicit_boot_or_internal_disk_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    disk: DiskInfo,
    reason: str,
) -> None:
    image = _image(tmp_path)
    calls = _patch(
        monkeypatch,
        assessments=[_assessment(disk, False, reason)],
    )

    result = runner.invoke(
        app,
        ["image", "--image", str(image), "--device", f"/dev/{disk.identifier}"],
        input=f"ERASE {disk.identifier}\n",
    )

    assert result.exit_code == 2
    assert calls == []
    assert reason in result.stderr


def test_image_allow_builtin_sd_without_device_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _image(tmp_path)
    calls = _patch(monkeypatch, [_disk()])

    result = runner.invoke(
        app,
        ["image", "--image", str(image), "--allow-builtin-sd"],
        input="1\nERASE disk9\n",
    )

    assert result.exit_code == 2
    assert calls == []
    assert "--allow-builtin-sd requires an explicit --device" in result.stderr


def test_image_dry_run_with_disk5_and_allow_builtin_sd_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 501)
    image = _image(tmp_path)
    calls = _patch(
        monkeypatch,
        assessments=[_assessment(_builtin_sd(), True, "internal SD reader (--allow-builtin-sd)")],
    )

    result = runner.invoke(
        app,
        [
            "image",
            "--image",
            str(image),
            "--device",
            "/dev/disk5",
            "--allow-builtin-sd",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert calls == []
    assert "Dry run" in result.stdout
    assert "disk5" in result.stdout
    assert "Built In SDXC Reader" in result.stdout
    assert "/dev/rdisk5" in result.stdout


def test_image_dry_run_revalidates_the_device_even_if_enumeration_allowed_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _image(tmp_path)
    calls = _patch(
        monkeypatch,
        assessments=[_assessment(_internal(), True, "internal disk")],
    )

    result = runner.invoke(
        app,
        [
            "image",
            "--image",
            str(image),
            "--device",
            "/dev/disk0",
            "--allow-builtin-sd",
            "--dry-run",
        ],
    )

    assert result.exit_code == 2
    assert calls == []
    assert "not a removable SD reader" in result.stderr


def test_image_help_when_requested_has_the_safe_options() -> None:
    result = runner.invoke(app, ["image", "--help"])

    assert result.exit_code == 0
    assert "--image" in result.stdout
    assert "--list" in result.stdout
    assert "--device" in result.stdout
    assert "--allow-builtin-sd" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--yes" not in result.stdout
