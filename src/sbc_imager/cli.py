"""Command-line interface for sbc-imager."""

from __future__ import annotations

import functools
import json
import sys
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.table import Table

from sbc_imager import __version__
from sbc_imager.cannoli import PLATFORM_TAGS
from sbc_imager.cli_verify import register as register_verify
from sbc_imager.config import Manifest, load_manifest
from sbc_imager.errors import ConfigError, SbcImagerError
from sbc_imager.planner import BuildPlan, build_plan, plan_payload, source_rows
from sbc_imager.runner import SubprocessRunner
from sbc_imager.sources import (
    ResolvedSource,
    SourceCache,
    resolve_git,
    resolve_http,
    resolve_local,
)


@dataclass(frozen=True, slots=True)
class AppState:
    """Global state shared with subcommands through the Typer context."""

    verbose: bool


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


def _verbose_from(args: tuple[object, ...], kwargs: Mapping[str, object]) -> bool:
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
    """Turn expected failures into stable stderr output and exit codes."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except SbcImagerError as error:
            _report_error(error, verbose=_verbose_from(args, kwargs))
            raise typer.Exit(error.exit_code) from None

    return wrapper


def _platform_rows() -> list[dict[str, str]]:
    return [{"tag": tag, "platform": platform} for tag, platform in PLATFORM_TAGS.items()]


def _not_implemented(command: str, target: str) -> None:
    raise ConfigError(
        f"{command} is not implemented yet",
        hint=f"See {target} for the implementation.",
    )


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


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
    git_options = {"offline": offline, "allow_branch": allow_branch}
    resolved: dict[str, ResolvedSource] = {}
    for source in manifest.sources:
        if source.id not in wanted:
            continue
        kind = source.type.casefold()
        if kind == "git":
            resolved[source.id] = resolve_git(source, cache, runner, **git_options)
        elif kind in {"http", "https", "url"}:
            resolved[source.id] = resolve_http(source, cache, client, offline=offline)
        elif kind == "local":
            path = Path(source.url).expanduser()
            resolved[source.id] = resolve_local(
                path if path.is_absolute() else manifest.base_dir / path, source.id
            )
        else:
            raise ConfigError(f"unsupported source type '{source.type}' for '{source.id}'")
    return resolved


def _print_plan(plan: BuildPlan) -> None:
    console = Console()
    table = Table("Destination", "Kind", "Size")
    for entry in plan.entries:
        table.add_row(entry.dest.as_posix(), entry.kind, _human_size(entry.size))
    console.print(table)
    console.print(
        f"Content: {_human_size(plan.content_bytes)}  "
        f"Overhead: {_human_size(plan.overhead_bytes)}  "
        f"Reserve: {_human_size(plan.reserve_bytes)}"
    )
    console.print(
        f"Partition: {_human_size(plan.partition_bytes)} at offset "
        f"{_human_size(plan.partition_offset_bytes)}  "
        f"Image: {_human_size(plan.image_bytes)}"
    )
    for warning in plan.warnings:
        where = "" if warning.entry_index is None else f" [{warning.entry_index}]"
        console.print(f"Warning{where}: {warning.code}: {warning.message}")


def _print_sources(sources: tuple[ResolvedSource, ...]) -> None:
    table = Table("ID", "Type", "Root")
    for source in sources:
        table.add_row(source.id, source.kind, str(source.root))
    Console().print(table)


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
    """Build and flash Cannoli-ready SD card images for Android SBC devices.

    Set --verbose for detailed output. Run a command with --help for its usage.
    """
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
    client = httpx.Client(follow_redirects=True, timeout=30.0)
    try:
        resolved = _resolve_sources(
            manifest,
            client,
            referenced_only=True,
            offline=offline,
            allow_branch=allow_branch,
        )
    finally:
        client.close()
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
    client = httpx.Client(follow_redirects=True, timeout=30.0)
    try:
        resolved = _resolve_sources(
            manifest,
            client,
            referenced_only=False,
            offline=offline,
            allow_branch=allow_branch,
        )
    finally:
        client.close()
    sources = tuple(resolved[source.id] for source in manifest.sources if source.id in resolved)
    if json_output:
        typer.echo(json.dumps(source_rows(sources)))
        return
    _print_sources(sources)


@app.command()
@_handle_errors
def build(ctx: typer.Context) -> None:
    """Build the card image (not implemented yet)."""
    _not_implemented("build", "todo 17")


@app.command()
@_handle_errors
def image(ctx: typer.Context) -> None:
    """Flash a verified image to a removable card (not implemented yet)."""
    _not_implemented("image", "todo 21")


register_verify(app, _handle_errors)
