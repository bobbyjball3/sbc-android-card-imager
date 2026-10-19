"""Loop-device lifecycle and content-copy steps for image assembly."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from pathlib import Path

from sbc_imager.assembler_report import (
    StagePlan,
    TreeEntry,
    expected_files,
    scan_tree,
    verify_tree,
)
from sbc_imager.errors import AssemblerError, VerificationError
from sbc_imager.runner import Runner

_CHUNK = 8 * 1024 * 1024
_LOOP_RE = re.compile(r"/dev/loop\d+")
Progress = Callable[[str, int, int], None]


def _run(runner: Runner, args: list[str], *, action: str) -> None:
    result = runner.run(args, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        raise AssemblerError(f"{action} failed with exit code {result.returncode}: {detail}")


def attach_loop(runner: Runner, image: Path, offset: int, size: int) -> str:
    result = runner.run(
        [
            "losetup",
            "--find",
            "--show",
            "--offset",
            str(offset),
            "--sizelimit",
            str(size),
            str(image),
        ],
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "no output"
        raise AssemblerError(f"losetup failed with exit code {result.returncode}: {detail}")
    device = result.stdout.strip()
    if _LOOP_RE.fullmatch(device) is None:
        raise AssemblerError(f"losetup returned an unexpected device: {device!r}")
    return device


def detach_loop(runner: Runner, loop: str) -> None:
    _run(runner, ["losetup", "-d", loop], action="losetup -d")


def make_filesystem(runner: Runner, label: str, loop: str) -> None:
    _run(runner, ["mkfs.exfat", "-L", label, loop], action="mkfs.exfat")


def mount_filesystem(runner: Runner, loop: str, mountpoint: Path, *, readonly: bool) -> None:
    args = ["mount", "-t", "exfat"]
    if readonly:
        args.append("-o")
        args.append("ro")
    args.extend([loop, str(mountpoint)])
    _run(runner, args, action="mount")


def unmount(runner: Runner, mountpoint: Path) -> None:
    _run(runner, ["umount", str(mountpoint)], action="umount")


def check_filesystem(runner: Runner, loop: str) -> None:
    _run(runner, ["fsck.exfat", "-n", loop], action="fsck.exfat")


def _copy_hashed(source: Path, target: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    status = source.stat()
    written = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as reader, target.open("wb") as writer:
        while chunk := reader.read(_CHUNK):
            digest.update(chunk)
            writer.write(chunk)
            written += len(chunk)
    os.utime(target, ns=(status.st_atime_ns, status.st_mtime_ns))
    return written, digest.hexdigest()


def _write_marker(mountpoint: Path, marker_path: str, content: str) -> None:
    data = content.encode("utf-8")
    target = mountpoint / marker_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def populate(stage_dir: Path, mountpoint: Path, plan: StagePlan, progress: Progress | None) -> None:
    """Create directories and markers, then copy and hash the staged files."""
    expected = expected_files(plan)
    staged = sorted(
        (path for path in Path(stage_dir).rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(stage_dir).as_posix(),
    )
    destinations = {path.relative_to(stage_dir).as_posix(): path for path in staged}
    planned = {entry.dest.as_posix() for entry in plan.entries}

    missing = sorted(planned - set(destinations))
    if missing:
        raise VerificationError(f"stage tree is missing files: {', '.join(missing)}")
    extra = sorted(set(destinations) - planned)
    if extra:
        raise VerificationError(f"stage tree contains unexpected files: {', '.join(extra)}")

    for directory in plan.required_dirs:
        (mountpoint / directory).mkdir(parents=True, exist_ok=True)

    total = len(plan.entries) + 2
    current = 0
    for dest in sorted(destinations):
        size, digest = _copy_hashed(destinations[dest], mountpoint / dest)
        expected_size, expected_digest = expected[dest]
        if size != expected_size or digest != expected_digest:
            raise VerificationError(f"staged file {dest!r} hash mismatch")
        current += 1
        if progress is not None:
            progress("copy", current, total)

    for marker in (plan.settings_marker, plan.credits_marker):
        _write_marker(mountpoint, marker.path.as_posix(), marker.content)
        current += 1
        if progress is not None:
            progress("copy", current, total)


def verify(mountpoint: Path, plan: StagePlan, progress: Progress | None) -> tuple[TreeEntry, ...]:
    """Hash the mounted tree, compare it to the plan, and report progress."""
    tree = scan_tree(mountpoint)
    verify_tree(expected_files(plan), tree)
    total = len(tree)
    if progress is not None:
        for current, _ in enumerate(tree, start=1):
            progress("verify", current, total)
    return tree
