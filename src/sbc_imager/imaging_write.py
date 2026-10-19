"""Write a verified image to a raw removable device with safety guards."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from sbc_imager.errors import SafetyError
from sbc_imager.fs import sha256_file
from sbc_imager.runner import Runner
from sbc_imager.sizes import format_size

if TYPE_CHECKING:
    from sbc_imager.imaging import DiskInfo

ProgressCallback = Callable[[int, int], None]

_CHUNK_SIZE: Final = 8 * 1024 * 1024
_DISK_IDENTIFIER: Final = re.compile(r"disk\d+")
_DEV_PREFIX: Final = re.compile(r"/+dev(?:/|$)")
_RAW_DEVICE: Final = re.compile(r"/dev/rdisk\d+")
_ROOT_HINT: Final = "sudo -E uv run sbc-imager image ..."


@dataclass(frozen=True, slots=True)
class WriteResult:
    """The outcome of a successful card write."""

    bytes_written: int
    duration_s: float
    avg_bytes_per_s: float
    image_sha256: str
    device: Path


def write_image(
    image_path: Path,
    disk: DiskInfo,
    runner: Runner,
    *,
    device_path: Path | None = None,
    dry_run: bool = False,
    progress: ProgressCallback | None = None,
) -> WriteResult:
    """Write ``image_path`` to ``disk``'s raw device after unmounting it.

    ``device_path`` is a test-only seam that accepts an existing regular file
    outside ``/dev``; production callers must leave it as ``None``.
    """
    image = Path(image_path)
    if not dry_run and os.geteuid() != 0:
        raise SafetyError("writing a card image requires root", hint=_ROOT_HINT)

    total = image.stat().st_size
    if total > disk.size:
        raise SafetyError(
            f"image is {total} bytes but {disk.identifier} is only {disk.size} bytes; "
            "it does not fit"
        )
    device = _resolve_device(disk, device_path)

    if dry_run:
        digest = sha256_file(image)
        _print_dry_run(Console(), image, disk, device, total, digest)
        return WriteResult(0, 0.0, 0.0, digest, device)

    _unmount(disk, runner)
    if progress is None:
        with _progress_bar(total) as reporter:
            result = _copy_to_device(image, device, total, reporter)
    else:
        result = _copy_to_device(image, device, total, progress)
    _eject(disk, runner)
    _print_summary(Console(), result)
    return result


def _resolve_device(disk: DiskInfo, override: Path | None) -> Path:
    if override is not None:
        return _resolve_test_device(override)

    if _DISK_IDENTIFIER.fullmatch(disk.identifier) is None:
        raise SafetyError(f"refusing unsafe disk identifier {disk.identifier!r}")
    device = Path(f"/dev/r{disk.identifier}")
    canonical = Path(os.path.realpath(device))
    folded = canonical.as_posix().casefold()
    mode = _stat_mode(canonical)
    if mode is not None and stat.S_ISBLK(mode) and _RAW_DEVICE.fullmatch(folded) is None:
        raise SafetyError(f"refusing to write to block device {device}")
    if _RAW_DEVICE.fullmatch(folded) is None:
        raise SafetyError(
            f"refusing to write to {device}; canonical path {canonical} is not an allowed "
            "/dev/rdisk<N> raw device"
        )
    if canonical.name.casefold() != device.name.casefold():
        raise SafetyError(
            f"refusing to write to {device}; canonical path {canonical} does not match the disk"
        )
    return device


def _resolve_test_device(override: Path) -> Path:
    device = Path(override)
    if not device.is_absolute():
        raise SafetyError(f"device_path must be absolute: {device}")
    canonical = Path(os.path.realpath(device))
    if _DEV_PREFIX.match(canonical.as_posix().casefold()) is not None:
        raise SafetyError(
            f"refusing device_path override {device}; overrides must be a regular file outside /dev"
        )
    mode = _stat_mode(canonical)
    if mode is None or not stat.S_ISREG(mode):
        raise SafetyError(
            f"refusing device_path override {device}; overrides must be a regular file outside /dev"
        )
    return device


def _stat_mode(path: Path) -> int | None:
    try:
        return os.stat(path).st_mode
    except OSError:
        return None


def _unmount(disk: DiskInfo, runner: Runner) -> None:
    target = f"/dev/{disk.identifier}"
    result = runner.run(["diskutil", "unmountDisk", target], check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        raise SafetyError(
            f"could not unmount {target}: {detail}",
            hint="Close any application using the card, then retry.",
        )


def _eject(disk: DiskInfo, runner: Runner) -> None:
    target = f"/dev/{disk.identifier}"
    result = runner.run(["diskutil", "eject", target], check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        Console(stderr=True).print(f"[yellow]Warning[/yellow]: could not eject {target}: {detail}")


def _copy_to_device(
    image: Path,
    device: Path,
    total: int,
    progress: ProgressCallback,
) -> WriteResult:
    started = time.monotonic()
    digest = hashlib.sha256()
    written = 0
    descriptor = os.open(device, os.O_WRONLY)
    try:
        try:
            with image.open("rb") as source:
                while chunk := source.read(_CHUNK_SIZE):
                    digest.update(chunk)
                    _write_all(descriptor, chunk)
                    written += len(chunk)
                    progress(written, total)
                if total == 0:
                    progress(0, 0)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except KeyboardInterrupt:
        _warn_partial(device)
        raise

    duration = time.monotonic() - started
    average = written / duration if duration > 0 else 0.0
    return WriteResult(written, duration, average, digest.hexdigest(), device)


def _write_all(descriptor: int, chunk: bytes) -> None:
    view = memoryview(chunk)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError(f"device write returned {written} bytes")
        view = view[written:]


def _warn_partial(device: Path) -> None:
    Console(stderr=True).print(
        f"[bold red]INTERRUPTED[/bold red]: the card at {device} is partially written and "
        "unusable; re-flash it before use."
    )


@contextmanager
def _progress_bar(total: int) -> Iterator[ProgressCallback]:
    columns = (
        TextColumn("[bold]Writing[/bold]"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
    )
    with Progress(*columns, transient=True) as bar:
        task = bar.add_task("write", total=total)
        yield lambda written, _total: bar.update(task, completed=written)


def _print_dry_run(
    console: Console,
    image: Path,
    disk: DiskInfo,
    device: Path,
    total: int,
    digest: str,
) -> None:
    console.print("[bold]Dry run[/bold]: no data will be written.")
    console.print(f"Device: {device}")
    console.print(f"Disk size: {disk.size} bytes ({format_size(disk.size)})")
    console.print(f"Image: {image}")
    console.print(f"Image size: {total} bytes ({format_size(total)})")
    console.print(f"Image SHA-256: {digest}")


def _print_summary(console: Console, result: WriteResult) -> None:
    console.print(
        f"Wrote {result.bytes_written} bytes ({format_size(result.bytes_written)}) "
        f"to {result.device} in {result.duration_s:.2f}s "
        f"({format_size(int(result.avg_bytes_per_s))}/s)"
    )
    console.print(f"Image SHA-256: {result.image_sha256}")
