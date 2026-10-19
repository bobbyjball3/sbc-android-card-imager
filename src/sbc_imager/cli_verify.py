"""Typer registration for the image verification command."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console

from sbc_imager.runner import SubprocessRunner
from sbc_imager.sources import SourceCache
from sbc_imager.verify import VerifyReport, verify_image

Handler = Callable[[Callable[..., object]], Callable[..., object]]


def _print_report(report: VerifyReport) -> None:
    console = Console()
    if report.ok:
        console.print(f"Verification passed: {report.actual_files} files match the manifest.")
        return
    console.print("Verification failed:")
    for label, items in (
        ("Missing files", report.missing),
        ("Unexpected files", report.extra),
        ("Hash mismatches", report.mismatched),
        ("Missing directories", report.missing_dirs),
    ):
        if items:
            console.print(f"  {label}: {', '.join(items)}")


def register(app: typer.Typer, handle_errors: Handler) -> None:
    """Register the ``verify`` command on the application."""

    @app.command()
    @handle_errors
    def verify(
        image_path: Annotated[
            Path, typer.Option("--image", exists=True, dir_okay=False, help="Image to verify.")
        ],
        manifest_path: Annotated[
            Path, typer.Option("--manifest", exists=True, dir_okay=False, help="Manifest path.")
        ],
        offline: bool = typer.Option(False, "--offline"),
        allow_branch: bool = typer.Option(False, "--allow-branch"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Verify an image's tree against the manifest without writing to it."""
        client = httpx.Client(follow_redirects=True, timeout=30.0)
        try:
            report = verify_image(
                manifest_path,
                image_path,
                SourceCache(),
                SubprocessRunner(),
                client,
                offline=offline,
                allow_branch=allow_branch,
                on_line=(lambda line: None) if json_output else typer.echo,
            )
        finally:
            client.close()
        if json_output:
            typer.echo(json.dumps(report.payload()))
        else:
            _print_report(report)
        if not report.ok:
            raise typer.Exit(1)
