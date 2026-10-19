from __future__ import annotations

import hashlib
import inspect
import os
import stat
from collections.abc import Sequence
from pathlib import Path

import pytest

import sbc_imager.imaging_write as writer
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


def test_write_image_when_image_fits_writes_exact_bytes_hash_and_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    size = 8 * 1024 * 1024 + 12345
    data = (bytes(range(256)) * (size // 256 + 1))[:size]
    target = _target(tmp_path)
    runner = _runner(_UNMOUNT, _EJECT)
    reports: list[tuple[int, int]] = []
    real_write = os.write
    monkeypatch.setattr(os, "write", lambda fd, chunk: real_write(fd, chunk[:4096]))

    result = write_image(
        _image(tmp_path, data),
        _disk(size),
        runner,
        device_path=target,
        progress=lambda written, total: reports.append((written, total)),
    )

    assert target.read_bytes() == data
    assert (result.bytes_written, result.image_sha256, result.device) == (
        size,
        hashlib.sha256(data).hexdigest(),
        target,
    )
    assert reports[-1] == (size, size)
    assert runner.commands == [_UNMOUNT, _EJECT]


def test_write_image_when_not_root_refuses_with_sudo_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 501)
    image = _image(tmp_path, b"data")
    target = _target(tmp_path, size=4)
    runner = FakeRunner()

    with pytest.raises(SafetyError) as caught:
        write_image(image, _disk(1024), runner, device_path=target)

    assert (caught.value.exit_code, caught.value.hint) == (2, "sudo -E uv run sbc-imager image ...")
    assert (runner.calls, target.read_bytes()) == ([], b"\0\0\0\0")


def test_write_image_when_image_larger_than_disk_refuses(
    tmp_path: Path,
) -> None:
    image = _image(tmp_path, b"x" * 100)
    target = _target(tmp_path, size=100)
    runner = FakeRunner()

    with pytest.raises(SafetyError) as caught:
        write_image(image, _disk(99), runner, device_path=target, progress=lambda *_: None)

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
        write_image(image, _disk(1024), runner, device_path=target, progress=lambda *_: None)

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
        progress=lambda *_: None,
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
    assert all(fragment in stderr for fragment in ("partially written", "unusable", "re-flash"))
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
    assert (target.read_bytes(), runner.calls) == (b"\0" * 32, [])
    assert (result.bytes_written, result.image_sha256, result.device) == (
        0,
        hashlib.sha256(data).hexdigest(),
        target,
    )
    assert all(label in output for label in ("Device:", "Disk size:", "Image size:"))
    assert hashlib.sha256(data).hexdigest() in output.replace("\n", "")


@pytest.mark.parametrize(
    "device",
    [
        "/dev/disk9",
        "/dev/disk9s1",
        "/dev/rdisk",
        "/dev/../dev/disk9",
        "/DEV/disk9",
        "/Dev/disk9",
        "/deV/disk9",
        "//dev/disk9",
    ],
)
def test_write_image_when_device_is_not_a_safe_raw_path_refuses(
    tmp_path: Path, device: str
) -> None:
    with pytest.raises(SafetyError) as caught:
        write_image(
            _image(tmp_path, b"card"),
            _disk(1024),
            FakeRunner(),
            device_path=Path(device),
            dry_run=True,
        )

    assert "device_path override" in caught.value.message


def test_write_image_when_override_symlinks_to_dev_alias_refuses(tmp_path: Path) -> None:
    link = tmp_path / "alias"
    link.symlink_to("/DEV/disk9")

    with pytest.raises(SafetyError, match="device_path override"):
        write_image(
            _image(tmp_path, b"card"),
            _disk(1024),
            FakeRunner(),
            device_path=link,
            dry_run=True,
        )


def test_write_image_when_override_is_a_block_device_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path, size=4)
    monkeypatch.setattr(writer, "_stat_mode", lambda _path: stat.S_IFBLK | 0o600)

    with pytest.raises(SafetyError, match="regular file"):
        write_image(
            _image(tmp_path, b"card"),
            _disk(1024),
            FakeRunner(),
            device_path=target,
            dry_run=True,
        )


def test_write_image_when_override_differs_from_disk_never_opens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[object] = []
    monkeypatch.setattr(os, "open", lambda *args: opened.append(args))

    with pytest.raises(SafetyError, match="device_path override"):
        write_image(
            _image(tmp_path, b"card"),
            _disk(1024),
            _runner(_UNMOUNT),
            device_path=Path("/dev/rdisk12"),
        )

    assert opened == []


@pytest.mark.parametrize("identifier", ["disk9", "disk12"])
def test_write_image_when_default_raw_device_is_used_accepts_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], identifier: str
) -> None:
    result = write_image(
        _image(tmp_path, b"card"),
        _disk(1024, identifier=identifier),
        FakeRunner(),
        dry_run=True,
    )

    assert result.device == Path(f"/dev/r{identifier}")
    assert f"/dev/r{identifier}" in capsys.readouterr().out


def test_write_image_when_writing_never_uses_dd_or_a_shell(tmp_path: Path) -> None:
    image = _image(tmp_path, b"card")
    runner = _runner(_UNMOUNT, _EJECT)

    write_image(image, _disk(1024), runner, device_path=_target(tmp_path), progress=lambda *_: None)

    flat = [argument for command in runner.commands for argument in command]
    source = Path(inspect.getsourcefile(write_image) or "").read_text(encoding="utf-8")
    assert "dd" not in flat
    assert all(command[0] == "diskutil" for command in runner.commands)
    assert "shell=True" not in source
