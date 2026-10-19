"""Command-line interface for sbc-imager."""

from __future__ import annotations

from dataclasses import dataclass

import typer

from sbc_imager import __version__


@dataclass(frozen=True, slots=True)
class AppState:
    """Global state shared with subcommands through the Typer context."""

    verbose: bool


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


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
