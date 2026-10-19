"""Verify an existing MBR+exFAT image with a read-only mount."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from sbc_imager.assembler_report import TreeEntry, scan_tree, tree_bytes
from sbc_imager.assembler_steps import (
    MountState,
    attach_loop,
    check_filesystem,
    cleanup,
    mount_filesystem,
)
from sbc_imager.errors import AssemblerError
from sbc_imager.runner import Runner

_MBR_BYTES = 512
_SECTOR_SIZE = 512
_SIGNATURE = b"\x55\xaa"


@dataclass(frozen=True, slots=True)
class Partition:
    """The first partition entry of an MBR."""

    start_lba: int
    sectors: int
    type_: int

    @property
    def offset_bytes(self) -> int:
        return self.start_lba * _SECTOR_SIZE

    @property
    def size_bytes(self) -> int:
        return self.sectors * _SECTOR_SIZE


def parse_partition(header: bytes) -> Partition:
    """Parse and validate the first partition entry of a 512-byte MBR."""
    if len(header) < _MBR_BYTES:
        raise ValueError(f"MBR must be at least {_MBR_BYTES} bytes, got {len(header)}")
    if header[510:512] != _SIGNATURE:
        raise ValueError("MBR is missing the 0x55aa boot signature")
    type_ = header[450]
    start_lba = int.from_bytes(header[454:458], "little")
    sectors = int.from_bytes(header[458:462], "little")
    if type_ == 0:
        raise ValueError("first partition entry is empty")
    if start_lba == 0:
        raise ValueError("first partition start LBA must be positive")
    if sectors == 0:
        raise ValueError("first partition sector count must be positive")
    return Partition(start_lba=start_lba, sectors=sectors, type_=type_)


def dirs_path_for(out_path: Path) -> Path:
    """Return the directory-listing sidecar path for a tree JSON path."""
    target = Path(out_path)
    return target.with_name(f"{target.stem}.dirs.json")


def scan_dirs(root: Path) -> tuple[str, ...]:
    """Return every directory below ``root`` as a sorted relative POSIX path."""
    base = Path(root)
    dirs = (path.relative_to(base).as_posix() for path in base.rglob("*") if path.is_dir())
    return tuple(sorted(dirs))


def dirs_bytes(dirs: tuple[str, ...]) -> bytes:
    """Serialize a directory listing deterministically."""
    return (json.dumps(list(dirs), indent=2) + "\n").encode("utf-8")


def _read_header(image: Path) -> bytes:
    try:
        with image.open("rb") as handle:
            header = handle.read(_MBR_BYTES)
    except OSError as exc:
        raise AssemblerError(f"cannot read image {image}: {exc}") from exc
    if len(header) < _MBR_BYTES:
        raise AssemblerError(f"image {image} is smaller than the 512-byte MBR")
    return header


def _partition(image: Path, header: bytes) -> Partition:
    try:
        partition = parse_partition(header)
    except ValueError as exc:
        raise AssemblerError(f"invalid MBR in {image}: {exc}") from exc
    if partition.offset_bytes + partition.size_bytes > image.stat().st_size:
        raise AssemblerError(
            f"invalid MBR in {image}: the first partition extends beyond the image"
        )
    return partition


def _prepare_mountpoint(work: Path) -> Path:
    mountpoint = Path(work) / "verify-mnt"
    if mountpoint.exists():
        if os.path.ismount(mountpoint):
            raise AssemblerError(
                f"cleanup incomplete: {mountpoint} is already mounted",
                hint="unmount the path before verifying another image",
            )
        shutil.rmtree(mountpoint)
    mountpoint.mkdir(parents=True)
    return mountpoint


def verify_image(
    image_path: Path,
    out_path: Path,
    work_dir: Path,
    runner: Runner,
) -> tuple[TreeEntry, ...]:
    """Mount ``image_path`` read-only, hash every file, and write ``tree.json``."""
    image = Path(image_path)
    if not image.is_file():
        raise AssemblerError(f"image does not exist: {image}")
    partition = _partition(image, _read_header(image))
    mountpoint = _prepare_mountpoint(Path(work_dir))

    loop: str | None = None
    mounted = False
    failure: BaseException | None = None
    try:
        loop = attach_loop(runner, image, partition.offset_bytes, partition.size_bytes)
        check_filesystem(runner, loop)
        mount_filesystem(runner, loop, mountpoint, readonly=True)
        mounted = True

        tree = scan_tree(mountpoint)
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(tree_bytes(tree))
        dirs_path_for(out).write_bytes(dirs_bytes(scan_dirs(mountpoint)))
        return tree
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try:
            cleanup(runner, MountState(mountpoint, loop, mounted))
        except AssemblerError as cleanup_error:
            if failure is not None:
                raise cleanup_error from failure
            raise
