from __future__ import annotations

import hashlib
import inspect
import os
from collections.abc import Sequence
from pathlib import Path

import pytest

from sbc_imager.errors import SafetyError
from sbc_imager.imaging import DiskInfo, write_image
from sbc_imager.runner import CommandResult
from tests.fakes import FakeRunner

_UNMOUNT = ["diskutil", "unmountDisk", "/dev/disk9"]
_EJECT = ["diskutil", "eject", "/dev/disk9"]


@pytest.fixture(autouse=True)
def _root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)


def _disk(size: int, identifier: str = "disk9") -> DiskInfo:
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


def _result(args: Sequence[str], returncode: int = 0, stderr: str = "") -> CommandResult:
    return CommandResult(tuple(args), returncode, "", stderr, 0.01)


def _runner(*args: Sequence[str]) -> FakeRunner:
    return FakeRunner(results=[_result(command) for command in args])


def _image(tmp_path: Path, data: bytes) -> Path:
    path = tmp_path / "card.img"
    path.write_bytes(data)
    return path


def _target(tmp_path: Path, *, size: int = 0) -> Path:
    path = tmp_path / "device"
    path.write_bytes(b"\0" * size)
    return path


def _noop_progress(_written: int, _total: int) -> None:
    return None


def test_write_image_when_image_fits_writes_exact_bytes_and_hash(tmp_path: Path) -> None:
    size = 8 * 1024 * 1024 + 12345
    data = (bytes(range(256)) * (size // 256 + 1))[:size]
    image = _image(tmp_path, data)
    target = _target(tmp_path)
    runner = _runner(_UNMOUNT, _EJECT)

    result = write_image(
        image,
        _disk(len(data)),
        runner,
        device_path=target,
        progress=_noop_progress,
    )

    assert target.read_bytes() == data
    assert result.bytes_written == len(data)
    assert result.image_sha256 == hashlib.sha256(data).hexdigest()
    assert result.device == target
    assert runner.commands == [_UNMOUNT, _EJECT]


def test_write_image_when_progress_callback_given_reports_final_total(
    tmp_path: Path,
) -> None:
    data = b"card" * 5000
    image = _image(tmp_path, data)
    reports: list[tuple[int, int]] = []

    write_image(
        image,
        _disk(len(data)),
        _runner(_UNMOUNT, _EJECT),
        device_path=_target(tmp_path),
        progress=lambda written, total: reports.append((written, total)),
    )

    assert reports
    assert reports[-1] == (len(data), len(data))
    assert all(total == len(data) for _written, total in reports)
    assert [written for written, _total in reports] == sorted(
        written for written, _total in reports
    )


def test_write_image_when_os_write_is_partial_still_writes_every_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = bytes(range(200))
    image = _image(tmp_path, data)
    target = _target(tmp_path)
    real_write = os.write
    calls: list[int] = []

    def short_write(fd: int, chunk: bytes) -> int:
        calls.append(fd)
        return real_write(fd, chunk[:7])

    monkeypatch.setattr(os, "write", short_write)

    result = write_image(
        image,
        _disk(len(data)),
        _runner(_UNMOUNT, _EJECT),
        device_path=target,
        progress=_noop_progress,
    )

    assert target.read_bytes() == data
    assert result.bytes_written == len(data)
    assert len(calls) > 1


def test_write_image_when_not_root_refuses_with_sudo_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 501)
    image = _image(tmp_path, b"data")
    target = _target(tmp_path, size=4)
    runner = FakeRunner()

    with pytest.raises(SafetyError) as caught:
        write_image(image, _disk(1024), runner, device_path=target)

    assert caught.value.exit_code == 2
    assert caught.value.hint == "sudo -E uv run sbc-imager image ..."
    assert runner.calls == []
    assert target.read_bytes() == b"\0\0\0\0"


def test_write_image_when_image_larger_than_disk_refuses(
    tmp_path: Path,
) -> None:
    image = _image(tmp_path, b"x" * 100)
    target = _target(tmp_path, size=100)
    runner = FakeRunner()

    with pytest.raises(SafetyError) as caught:
        write_image(image, _disk(99), runner, device_path=target, progress=_noop_progress)

    assert caught.value.exit_code == 2
    assert "does not fit" in caught.value.message
    assert runner.calls == []
    assert target.read_bytes() == b"\0" * 100


def test_write_image_when_unmount_fails_refuses_and_does_not_open_device(
    tmp_path: Path,
) -> None:
    data = b"card"
    image = _image(tmp_path, data)
    target = _target(tmp_path, size=len(data))
    runner = FakeRunner(results=[_result(_UNMOUNT, 1, "Resource busy")])

    with pytest.raises(SafetyError) as caught:
        write_image(image, _disk(1024), runner, device_path=target, progress=_noop_progress)

    assert caught.value.exit_code == 2
    assert "unmount" in caught.value.message.lower()
    assert runner.commands == [_UNMOUNT]
    assert target.read_bytes() == b"\0" * len(data)


def test_write_image_when_eject_fails_still_reports_the_successful_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = b"card"
    image = _image(tmp_path, data)
    target = _target(tmp_path)
    runner = FakeRunner(results=[_result(_UNMOUNT), _result(_EJECT, 1, "could not eject")])

    result = write_image(
        image,
        _disk(1024),
        runner,
        device_path=target,
        progress=_noop_progress,
    )

    assert target.read_bytes() == data
    assert result.bytes_written == len(data)
    assert "Warning" in capsys.readouterr().err
    assert runner.commands == [_UNMOUNT, _EJECT]


def test_write_image_when_interrupted_warns_loudly_and_reraises(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = b"x" * (8 * 1024 * 1024 + 1)
    image = _image(tmp_path, data)
    target = _target(tmp_path)
    runner = _runner(_UNMOUNT)

    def interrupt(_written: int, _total: int) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        write_image(
            image,
            _disk(len(data)),
            runner,
            device_path=target,
            progress=interrupt,
        )

    assert target.stat().st_size == 8 * 1024 * 1024
    stderr = capsys.readouterr().err
    assert "partially written" in stderr
    assert "unusable" in stderr
    assert "re-flash" in stderr
    assert runner.commands == [_UNMOUNT]


def test_write_image_when_dry_run_prints_summary_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 501)
    data = b"dry-run-image"
    image = _image(tmp_path, data)
    target = _target(tmp_path, size=32)
    runner = FakeRunner()

    result = write_image(
        image,
        _disk(4096),
        runner,
        device_path=target,
        dry_run=True,
    )

    output = capsys.readouterr().out
    assert target.read_bytes() == b"\0" * 32
    assert runner.calls == []
    assert result.bytes_written == 0
    assert result.image_sha256 == hashlib.sha256(data).hexdigest()
    assert result.device == target
    assert "Device:" in output
    assert "Disk size:" in output
    assert "Image size:" in output
    assert str(len(data)) in output
    assert hashlib.sha256(data).hexdigest() in output.replace("\n", "")


@pytest.mark.parametrize(
    "device",
    ["/dev/disk9", "/dev/disk9s1", "/dev/rdisk", "/dev/foo", "//dev/disk9", "/dev/../dev/disk9"],
)
def test_write_image_when_device_is_not_raw_rdisk_refuses(tmp_path: Path, device: str) -> None:
    image = _image(tmp_path, b"card")
    runner = FakeRunner()

    with pytest.raises(SafetyError) as caught:
        write_image(
            image,
            _disk(1024),
            runner,
            device_path=Path(device),
            dry_run=True,
        )

    assert caught.value.exit_code == 2
    assert "/dev/rdisk" in caught.value.message
    assert runner.calls == []


@pytest.mark.parametrize("override", [None, Path("/dev/rdisk9")])
def test_write_image_when_device_is_raw_rdisk_or_default_accepts_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], override: Path | None
) -> None:
    image = _image(tmp_path, b"card")

    result = write_image(
        image,
        _disk(1024),
        FakeRunner(),
        device_path=override,
        dry_run=True,
    )

    assert result.device == Path("/dev/rdisk9")
    assert "/dev/rdisk9" in capsys.readouterr().out


def test_write_image_when_writing_never_uses_dd_or_a_shell(tmp_path: Path) -> None:
    image = _image(tmp_path, b"card")
    runner = _runner(_UNMOUNT, _EJECT)

    write_image(image, _disk(1024), runner, device_path=_target(tmp_path), progress=_noop_progress)

    flat = [argument for command in runner.commands for argument in command]
    source = Path(inspect.getsourcefile(write_image) or "").read_text(encoding="utf-8")
    assert "dd" not in flat
    assert all(command[0] == "diskutil" for command in runner.commands)
    assert "shell=True" not in source
    assert "subprocess" not in source
