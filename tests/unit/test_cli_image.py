from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

import sbc_imager.cli_image as cli_module
from sbc_imager.cli import app
from sbc_imager.imaging import DiskInfo
from sbc_imager.imaging_write import WriteResult
from sbc_imager.runner import Runner

runner = CliRunner()

_IMAGE_BYTES = b"fake-card-image-payload"
_SHA256 = hashlib.sha256(_IMAGE_BYTES).hexdigest()
_ROOT_HINT = "sudo -E uv run sbc-imager image ..."


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
    disks: list[DiskInfo],
    *,
    interrupt: bool = False,
) -> list[tuple[Path, DiskInfo, Runner]]:
    calls: list[tuple[Path, DiskInfo, Runner]] = []

    def fake_enumerate(_runner: Runner) -> list[DiskInfo]:
        return list(disks)

    def fake_write(image_path: Path, disk: DiskInfo, system_runner: Runner) -> WriteResult:
        calls.append((image_path, disk, system_runner))
        if interrupt:
            raise KeyboardInterrupt
        return _result()

    monkeypatch.setattr(cli_module, "enumerate_disks", fake_enumerate)
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
    assert "no safe removable disks found; connect a USB card reader" in result.stderr


def test_image_when_no_disks_and_not_root_reports_the_missing_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 501)
    image = _image(tmp_path)
    calls = _patch(monkeypatch, [])

    result = runner.invoke(app, ["image", "--image", str(image)])

    assert result.exit_code == 2
    assert calls == []
    assert "no safe removable disks found; connect a USB card reader" in result.stderr


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


def test_image_help_when_requested_has_only_the_safe_options() -> None:
    result = runner.invoke(app, ["image", "--help"])

    assert result.exit_code == 0
    assert "--image" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--device" not in result.stdout
    assert "--yes" not in result.stdout
