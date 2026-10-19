"""Typer registration for the macOS image command."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Annotated, Final

import typer
from rich.console import Console

from sbc_imager.errors import ConfigError, SafetyError
from sbc_imager.fs import sha256_file
from sbc_imager.imaging import (
    DiskAssessment,
    DiskInfo,
    assess_disks,
    enumerate_disks,
    normalize_disk_identifier,
    render_assessment_table,
    render_table,
    write_image,
)
from sbc_imager.imaging_write import WriteResult, validate_target
from sbc_imager.runner import SubprocessRunner
from sbc_imager.sizes import format_size

Handler = Callable[[Callable[..., object]], Callable[..., object]]

_ROOT_HINT: Final = "sudo -E uv run sbc-imager image ..."
_NO_DISKS: Final = (
    "no safe removable disks found; run `sbc-imager image --list` to inspect every disk"
)
_LIST_HINT: Final = "run `sbc-imager image --list` to inspect every whole disk and its reason"


def _prompt_line(message: str) -> str:
    try:
        value = typer.prompt(message, default="", show_default=False)
    except typer.Abort:
        return ""
    return str(value)


def _select_disk(disks: Sequence[DiskInfo]) -> DiskInfo:
    raw = _prompt_line(f"Select a disk [1-{len(disks)}]").strip()
    if not raw:
        raise SafetyError("no disk selected; aborting without writing")
    try:
        number = int(raw)
    except ValueError:
        raise SafetyError(f"invalid disk selection {raw!r}; aborting without writing") from None
    if not 1 <= number <= len(disks):
        raise SafetyError(
            f"disk selection {number} is out of range 1-{len(disks)}; aborting without writing"
        )
    return disks[number - 1]


def _select_explicit_device(assessments: Sequence[DiskAssessment], raw: str) -> DiskInfo:
    identifier = normalize_disk_identifier(raw)
    for assessment in assessments:
        if assessment.disk.identifier != identifier:
            continue
        if not assessment.allowed:
            raise SafetyError(
                f"refusing {raw}; {identifier} is not a safe target: {assessment.reason}",
                hint=_LIST_HINT,
            )
        return assessment.disk
    raise SafetyError(
        f"refusing {raw}; {identifier} is not a whole disk reported by diskutil",
        hint=_LIST_HINT,
    )


def _render_warning(console: Console, disk: DiskInfo) -> None:
    console.print(
        "[bold red]DESTRUCTIVE OPERATION[/bold red]: "
        "every byte on the selected card will be overwritten."
    )
    console.print(f"Device: {disk.identifier} (/dev/r{disk.identifier})")
    if disk.label:
        console.print(f"Label: {disk.label}")
    if disk.model:
        console.print(f"Model: {disk.model}")
    console.print(f"Size: {disk.size} bytes ({format_size(disk.size)})")
    if disk.protocol:
        console.print(f"Protocol: {disk.protocol}")
    if disk.serial:
        console.print(f"Serial: {disk.serial}")


def _require_confirmation(disk: DiskInfo) -> None:
    expected = f"ERASE {disk.identifier}"
    typed = _prompt_line(f"Type exactly '{expected}' to continue")
    if typed != expected:
        raise SafetyError(
            "confirmation did not match; aborting without writing",
            hint=f"Nothing was written. Re-run and type exactly: {expected}",
        )


def _print_dry_run(console: Console, image_path: Path, disk: DiskInfo) -> None:
    total = image_path.stat().st_size
    digest = sha256_file(image_path)
    console.print("[bold]Dry run[/bold]: no data will be written.")
    console.print(f"Device: {disk.identifier} (/dev/r{disk.identifier})")
    if disk.model:
        console.print(f"Model: {disk.model}")
    console.print(f"Disk size: {disk.size} bytes ({format_size(disk.size)})")
    console.print(f"Image: {image_path}")
    console.print(f"Image size: {total} bytes ({format_size(total)})")
    console.print(f"Image SHA-256: {digest}")


def _print_write_summary(console: Console, result: WriteResult) -> None:
    console.print(f"Device: {result.device}")
    console.print(f"Bytes written: {result.bytes_written} ({format_size(result.bytes_written)})")
    console.print(f"Duration: {result.duration_s:.2f}s")
    console.print(f"Average speed: {format_size(int(result.avg_bytes_per_s))}/s")
    console.print(f"Image SHA-256: {result.image_sha256}")


def register(app: typer.Typer, handle_errors: Handler) -> None:
    """Register the ``image`` command on the application."""

    @app.command()
    @handle_errors
    def image(
        ctx: typer.Context,
        image_path: Annotated[
            Path | None,
            typer.Option("--image", exists=True, dir_okay=False, help="Image to flash."),
        ] = None,
        list_disks: bool = typer.Option(
            False,
            "--list",
            help="List every whole disk with its safety status and reason; writes nothing.",
        ),
        device: Annotated[
            str | None,
            typer.Option(
                "--device",
                help="Explicit target: diskN, /dev/diskN, or /dev/rdiskN.",
            ),
        ] = None,
        allow_builtin_sd: bool = typer.Option(
            False,
            "--allow-builtin-sd",
            help="Permit an internal removable SD reader with --device (or --list).",
        ),
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Show the target and image details without writing."
        ),
    ) -> None:
        """Flash a verified image to a removable card after typed confirmation."""
        runner = SubprocessRunner()
        console = Console()

        if list_disks:
            assessments = assess_disks(runner, allow_builtin_sd=allow_builtin_sd)
            list_console = Console(width=max(console.width, 160))
            render_assessment_table(list_console, assessments)
            return

        if image_path is None:
            raise ConfigError(
                "--image is required unless --list is used",
                hint="run `sbc-imager image --list` to inspect disk targets first",
            )
        if allow_builtin_sd and device is None:
            raise SafetyError(
                "--allow-builtin-sd requires an explicit --device",
                hint=(
                    "select a target with --device /dev/diskN; use --list with "
                    "--allow-builtin-sd to inspect statuses"
                ),
            )

        if device is not None:
            assessments = assess_disks(runner, allow_builtin_sd=allow_builtin_sd)
            disk = _select_explicit_device(assessments, device)
            if not dry_run and os.geteuid() != 0:
                raise SafetyError("writing a card image requires root", hint=_ROOT_HINT)
        else:
            disks = enumerate_disks(runner)
            if not disks:
                raise SafetyError(_NO_DISKS, hint=_LIST_HINT)
            if not dry_run and os.geteuid() != 0:
                raise SafetyError("writing a card image requires root", hint=_ROOT_HINT)
            render_table(console, disks)
            disk = _select_disk(disks)

        if dry_run:
            validate_target(disk, allow_internal=allow_builtin_sd)
            _print_dry_run(console, image_path, disk)
            return

        _render_warning(console, disk)
        _require_confirmation(disk)
        try:
            result = write_image(
                image_path,
                disk,
                runner,
                allow_internal=allow_builtin_sd,
            )
        except KeyboardInterrupt:
            raise typer.Exit(130) from None
        _print_write_summary(console, result)
