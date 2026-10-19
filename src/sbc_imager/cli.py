"""Command-line interface for sbc-imager."""

from __future__ import annotations

import functools
import json
import sys
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.table import Table

from sbc_imager import __version__
from sbc_imager.build import BuildOptions, build_image
from sbc_imager.cannoli import PLATFORM_TAGS
from sbc_imager.cli_image import register as register_image
from sbc_imager.cli_verify import register as register_verify
from sbc_imager.config import Manifest, load_manifest
from sbc_imager.errors import ConfigError, SbcImagerError
from sbc_imager.planner import (
    BuildPlan,
    build_plan,
    plan_payload,
    source_rows,
    source_warnings,
)
from sbc_imager.runner import SubprocessRunner
from sbc_imager.sizes import format_size
from sbc_imager.sources import ResolvedSource, SourceCache, resolve_git, resolve_http, resolve_local
from sbc_imager.validation import Warning


@dataclass(frozen=True, slots=True)
class AppState:
    verbose: bool


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


def _verbose_from[**P](*args: P.args, **kwargs: P.kwargs) -> bool:
    for value in (*args, *kwargs.values()):
        state = getattr(value, "obj", None)
        if isinstance(state, AppState):
            return state.verbose
    return False


def _report_error(error: SbcImagerError, *, verbose: bool) -> None:
    typer.echo(f"Error: {error.message}", err=True)
    if error.hint:
        typer.echo(f"Hint: {error.hint}", err=True)
    if verbose:
        traceback.print_exc(file=sys.stderr)


def _handle_errors[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except SbcImagerError as error:
            _report_error(error, verbose=_verbose_from(*args, **kwargs))
            raise typer.Exit(error.exit_code) from None

    return wrapper


def _platform_rows() -> list[dict[str, str]]:
    return [{"tag": tag, "platform": platform} for tag, platform in PLATFORM_TAGS.items()]


def _resolve_sources(
    manifest: Manifest,
    client: httpx.Client,
    *,
    referenced_only: bool,
    offline: bool,
    allow_branch: bool,
) -> dict[str, ResolvedSource]:
    cache, runner = SourceCache(), SubprocessRunner()
    entries = (*manifest.overlays, *manifest.shaders)
    wanted = (
        {entry.source for entry in entries if entry.source is not None}
        if referenced_only
        else {source.id for source in manifest.sources}
    )
    resolved: dict[str, ResolvedSource] = {}
    for source in manifest.sources:
        if source.id not in wanted:
            continue
        kind = source.type.casefold()
        if kind == "git":
            resolved[source.id] = resolve_git(
                source, cache, runner, offline=offline, allow_branch=allow_branch
            )
        elif kind in {"http", "https", "url"}:
            resolved[source.id] = resolve_http(source, cache, client, offline=offline)
        elif kind == "local":
            path = Path(source.url).expanduser()
            local = path if path.is_absolute() else manifest.base_dir / path
            resolved[source.id] = resolve_local(local, source.id)
        else:
            raise ConfigError(f"unsupported source type '{source.type}' for '{source.id}'")
    return resolved


def _with_sources(
    manifest: Manifest, *, referenced_only: bool, offline: bool, allow_branch: bool
) -> dict[str, ResolvedSource]:
    client = httpx.Client(follow_redirects=True, timeout=30.0)
    try:
        return _resolve_sources(
            manifest,
            client,
            referenced_only=referenced_only,
            offline=offline,
            allow_branch=allow_branch,
        )
    finally:
        client.close()


def _warning_text(warning: Warning) -> str:
    where = "" if warning.entry_index is None else f" [{warning.entry_index}]"
    return f"Warning{where}: {warning.code}: {warning.message}"


def _print_plan(plan: BuildPlan) -> None:
    console = Console()
    table = Table("Destination", "Kind", "Size")
    for entry in plan.entries:
        table.add_row(entry.dest.as_posix(), entry.kind, format_size(entry.size))
    console.print(table)
    console.print(
        f"Content: {format_size(plan.content_bytes)}  "
        f"Overhead: {format_size(plan.overhead_bytes)}  "
        f"Reserve: {format_size(plan.reserve_bytes)}\n"
        f"Partition: {format_size(plan.partition_bytes)} at offset "
        f"{format_size(plan.partition_offset_bytes)}  "
        f"Image: {format_size(plan.image_bytes)}"
    )
    for warning in plan.warnings:
        console.print(_warning_text(warning))


app = typer.Typer(
    name="sbc-imager",
    help="Build and flash Cannoli-ready SD card images for Android SBC devices.",
    add_completion=False,
    no_args_is_help=True,
)


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the version and exit.",
        is_eager=True,
        callback=_version_callback,
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output."),
) -> None:
    """Build and flash Cannoli-ready SD card images for Android SBC devices."""
    ctx.obj = AppState(verbose=verbose)


@app.command()
@_handle_errors
def platforms(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Print the platform registry as JSON."),
) -> None:
    """List every Cannoli platform tag and its display name."""
    rows = _platform_rows()

    if json_output:
        typer.echo(json.dumps(rows))
        return

    table = Table("Tag", "Platform")
    for row in rows:
        table.add_row(row["tag"], row["platform"])
    Console().print(table)


@app.command()
@_handle_errors
def plan(
    ctx: typer.Context,
    manifest_path: Annotated[
        Path, typer.Option("--manifest", exists=True, dir_okay=False, help="Manifest path.")
    ],
    offline: bool = typer.Option(False, "--offline"),
    strict: bool = typer.Option(False, "--strict"),
    json_output: bool = typer.Option(False, "--json"),
    allow_branch: bool = typer.Option(False, "--allow-branch"),
) -> None:
    """Resolve sources, size the image, and print the planned card tree."""
    manifest = load_manifest(manifest_path)
    resolved = _with_sources(
        manifest, referenced_only=True, offline=offline, allow_branch=allow_branch
    )
    build = build_plan(manifest, resolved)
    if strict and build.warnings:
        first = build.warnings[0]
        raise ConfigError(
            f"strict-warnings: {len(build.warnings)} warning(s); "
            f"first is {first.code}: {first.message}"
        )
    if json_output:
        typer.echo(json.dumps(plan_payload(build)))
        return
    _print_plan(build)


@app.command()
@_handle_errors
def fetch(
    ctx: typer.Context,
    manifest_path: Annotated[
        Path, typer.Option("--manifest", exists=True, dir_okay=False, help="Manifest path.")
    ],
    offline: bool = typer.Option(False, "--offline"),
    json_output: bool = typer.Option(False, "--json"),
    allow_branch: bool = typer.Option(False, "--allow-branch"),
) -> None:
    """Populate the source cache from every declared source."""
    manifest = load_manifest(manifest_path)
    resolved = _with_sources(
        manifest, referenced_only=False, offline=offline, allow_branch=allow_branch
    )
    sources = tuple(resolved[source.id] for source in manifest.sources if source.id in resolved)
    warnings = source_warnings(manifest, resolved)
    if json_output:
        rows = source_rows(sources)
        by_id = {source.id: row for source, row in zip(sources, rows, strict=True)}
        for warning in warnings:
            if warning.entry_index is None:
                continue
            source_id = manifest.sources[warning.entry_index].id
            by_id[source_id]["warnings"] = [asdict(warning)]
        typer.echo(json.dumps(rows))
        return
    for source in sources:
        typer.echo(f"{source.id}\t{source.kind}\t{source.root}")
    for warning in warnings:
        typer.echo(_warning_text(warning))


@app.command()
@_handle_errors
def build(
    ctx: typer.Context,
    manifest_path: Annotated[
        Path, typer.Option("--manifest", exists=True, dir_okay=False, help="Manifest path.")
    ],
    output: Annotated[Path | None, typer.Option("--output", help="Output image path.")] = None,
    size: Annotated[str | None, typer.Option("--size", help="Image size or auto.")] = None,
    reserve: Annotated[str | None, typer.Option("--reserve", help="Free space reserve.")] = None,
    offline: bool = typer.Option(False, "--offline"),
    force: bool = typer.Option(False, "--force"),
    keep_work: bool = typer.Option(False, "--keep-work"),
    allow_branch: bool = typer.Option(False, "--allow-branch"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Build, verify, and atomically publish a card image."""

    def log(line: str) -> None:
        typer.echo(line, err=True)

    options = BuildOptions(
        manifest_path=manifest_path,
        output=output,
        size=size,
        reserve=reserve,
        offline=offline,
        force=force,
        keep_work=keep_work,
        allow_branch=allow_branch,
    )
    report = build_image(options, log=log)
    if json_output:
        typer.echo(json.dumps(report.payload()))
        return
    typer.echo(f"Image: {report.image}")
    typer.echo(
        f"Size: {format_size(report.image_bytes)}  SHA-256: {report.sha256}  "
        f"Verified files: {report.verify.actual_files}"
    )
    for warning in report.warnings:
        typer.echo(f"Warning: {warning.code}: {warning.message}")


register_image(app, _handle_errors)
register_verify(app, _handle_errors)
