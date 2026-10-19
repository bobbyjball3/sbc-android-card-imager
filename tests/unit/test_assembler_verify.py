from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from sbc_imager import assembler_steps, mbr
from sbc_imager.assembler_verify import dirs_path_for, parse_partition, verify_image
from sbc_imager.errors import AssemblerError
from sbc_imager.runner import CommandResult
from tests.fakes import FakeRunner

MIB = 1024 * 1024
SECTOR = 512
START_LBA = 2048
SECTORS = 2048
LOOP = "/dev/loop9"


def _ok(*, stdout: str = "") -> CommandResult:
    return CommandResult((), 0, stdout, "", 0.0)


def _fail(returncode: int = 1, *, stderr: str = "boom") -> CommandResult:
    return CommandResult((), returncode, "", stderr, 0.0)


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _image(
    tmp_path: Path,
    *,
    start_lba: int = START_LBA,
    sectors: int = SECTORS,
    valid_mbr: bool = True,
    size: int | None = None,
) -> Path:
    header = bytearray(mbr.build_mbr(start_lba, partition_sectors=sectors))
    if not valid_mbr:
        header[510:512] = b"\x00\x00"
    image = tmp_path / "card.img"
    with image.open("wb") as handle:
        handle.write(header)
        handle.truncate(start_lba * SECTOR + sectors * SECTOR if size is None else size)
    return image


class _MountingRunner(FakeRunner):
    """Populate the mountpoint when the read-only mount command runs."""

    def __init__(self, results: Sequence[CommandResult], mountpoint: Path) -> None:
        super().__init__(results)
        self._mountpoint = mountpoint

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        check: bool = True,
    ) -> CommandResult:
        result = super().run(args, cwd=cwd, env=env, stdin=stdin, check=check)
        if list(args)[:5] == ["mount", "-t", "exfat", "-o", "ro"]:
            _write(self._mountpoint / "Cannoli/Roms/GBA/demo.gba", b"ROMDATA")
            _write(self._mountpoint / "CREDITS.md", b"credits")
        return result


def _success_results() -> list[CommandResult]:
    return [_ok(stdout=LOOP + "\n"), _ok(), _ok(), _ok(), _ok()]


def test_verify_image_when_valid_mounts_read_only_hashes_and_cleans_up(tmp_path: Path) -> None:
    image = _image(tmp_path)
    before = image.read_bytes()
    work = tmp_path / "work"
    out = tmp_path / "out" / "tree.json"
    runner = _MountingRunner(_success_results(), work / "verify-mnt")

    tree = verify_image(image, out, work, runner)

    assert runner.commands == [
        [
            "losetup",
            "--find",
            "--show",
            "--offset",
            str(START_LBA * SECTOR),
            "--sizelimit",
            str(SECTORS * SECTOR),
            str(image),
        ],
        ["fsck.exfat", "-n", LOOP],
        ["mount", "-t", "exfat", "-o", "ro", LOOP, str(work / "verify-mnt")],
        ["umount", str(work / "verify-mnt")],
        ["losetup", "-d", LOOP],
    ]
    assert image.read_bytes() == before
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload == [
        {
            "dest": "CREDITS.md",
            "size": 7,
            "sha256": hashlib.sha256(b"credits").hexdigest(),
        },
        {
            "dest": "Cannoli/Roms/GBA/demo.gba",
            "size": 7,
            "sha256": hashlib.sha256(b"ROMDATA").hexdigest(),
        },
    ]
    assert [item.dest for item in tree] == [item["dest"] for item in payload]
    dirs = json.loads(dirs_path_for(out).read_text(encoding="utf-8"))
    assert dirs == ["Cannoli", "Cannoli/Roms", "Cannoli/Roms/GBA"]


def test_verify_image_when_mbr_signature_is_invalid_raises_before_commands(
    tmp_path: Path,
) -> None:
    image = _image(tmp_path, valid_mbr=False)
    runner = FakeRunner([])

    with pytest.raises(AssemblerError, match="MBR"):
        verify_image(image, tmp_path / "tree.json", tmp_path / "work", runner)

    assert runner.calls == []


def test_verify_image_when_partition_exceeds_image_raises_before_commands(
    tmp_path: Path,
) -> None:
    image = _image(tmp_path, size=START_LBA * SECTOR)
    runner = FakeRunner([])

    with pytest.raises(AssemblerError, match="beyond"):
        verify_image(image, tmp_path / "tree.json", tmp_path / "work", runner)

    assert runner.calls == []


def test_verify_image_when_fsck_fails_detaches_and_writes_no_tree(tmp_path: Path) -> None:
    image = _image(tmp_path)
    out = tmp_path / "tree.json"
    runner = FakeRunner([_ok(stdout=LOOP + "\n"), _fail(stderr="fsck exploded"), _ok()])

    with pytest.raises(AssemblerError, match="fsck"):
        verify_image(image, out, tmp_path / "work", runner)

    assert runner.commands[-1] == ["losetup", "-d", LOOP]
    assert not out.exists()
    assert not dirs_path_for(out).exists()


def test_verify_image_when_mount_fails_detaches_and_writes_no_tree(tmp_path: Path) -> None:
    image = _image(tmp_path)
    out = tmp_path / "tree.json"
    runner = FakeRunner([_ok(stdout=LOOP + "\n"), _ok(), _fail(stderr="mount denied"), _ok()])

    with pytest.raises(AssemblerError, match="mount"):
        verify_image(image, out, tmp_path / "work", runner)

    assert runner.commands[-1] == ["losetup", "-d", LOOP]
    assert ["umount", str(tmp_path / "work" / "verify-mnt")] not in runner.commands
    assert not out.exists()


def test_verify_image_when_unmount_persists_never_detaches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _image(tmp_path)
    work = tmp_path / "work"
    monkeypatch.setattr(assembler_steps.os.path, "ismount", lambda path: True)
    runner = _MountingRunner(
        [
            _ok(stdout=LOOP + "\n"),
            _ok(),
            _ok(),
            _fail(stderr="target is busy"),
            _fail(stderr="lazy target is busy"),
        ],
        work / "verify-mnt",
    )

    with pytest.raises(AssemblerError, match="cleanup incomplete"):
        verify_image(image, tmp_path / "tree.json", work, runner)

    assert ["losetup", "-d", LOOP] not in runner.commands


def test_parse_partition_when_valid_returns_geometry() -> None:
    header = mbr.build_mbr(4096, partition_sectors=8, type_=0x07)

    partition = parse_partition(header)

    assert partition.start_lba == 4096
    assert partition.sectors == 8
    assert partition.type_ == 0x07
    assert partition.offset_bytes == 4096 * SECTOR
    assert partition.size_bytes == 8 * SECTOR


def test_parse_partition_when_signature_is_missing_raises() -> None:
    header = bytearray(mbr.build_mbr(partition_sectors=8))
    header[510:512] = b"\x00\x00"

    with pytest.raises(ValueError, match="signature"):
        parse_partition(bytes(header))


def test_parse_partition_when_entry_is_empty_raises() -> None:
    header = bytearray(mbr.build_mbr(partition_sectors=8))
    header[450] = 0

    with pytest.raises(ValueError, match="empty"):
        parse_partition(bytes(header))


@pytest.mark.parametrize(
    ("field", "message"),
    [(slice(454, 458), "start LBA"), (slice(458, 462), "sector count")],
)
def test_parse_partition_when_geometry_is_zero_raises(field: slice, message: str) -> None:
    header = bytearray(mbr.build_mbr(partition_sectors=8))
    header[field] = bytes(4)

    with pytest.raises(ValueError, match=message):
        parse_partition(bytes(header))


def test_parse_partition_when_header_is_too_short_raises() -> None:
    with pytest.raises(ValueError, match="512"):
        parse_partition(b"\x55\xaa")
