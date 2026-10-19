"""Command-line interface for sbc-imager."""

from __future__ import annotations

import functools
import json
import sys
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import typer
from rich.console import Console
from rich.table import Table

from sbc_imager import __version__
from sbc_imager.cannoli import PLATFORM_TAGS
from sbc_imager.errors import ConfigError, SbcImagerError


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
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output.",
    ),
) -> None:
    """Build and flash Cannoli-ready SD card images for Android SBC devices.

    Set --verbose for detailed output. Run a command with --help for its usage.
    """
    ctx.obj = AppState(verbose=verbose)


@app.command()
@_handle_errors
def platforms(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print the platform registry as JSON.",
    ),
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
def plan(ctx: typer.Context) -> None:
    """Plan the card build from a manifest (not implemented yet)."""
    _not_implemented("plan", "todo 12")


@app.command()
@_handle_errors
def fetch(ctx: typer.Context) -> None:
    """Populate the source cache (not implemented yet)."""
    _not_implemented("fetch", "todo 12")


@app.command()
@_handle_errors
def build(ctx: typer.Context) -> None:
    """Build the card image (not implemented yet)."""
    _not_implemented("build", "todo 17")


@app.command()
@_handle_errors
def verify(ctx: typer.Context) -> None:
    """Verify a built image against a manifest (not implemented yet)."""
    _not_implemented("verify", "todo 16")


@app.command()
@_handle_errors
def image(ctx: typer.Context) -> None:
    """Flash a verified image to a removable card (not implemented yet)."""
    _not_implemented("image", "todo 21")
