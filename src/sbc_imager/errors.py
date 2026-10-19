"""Typed exceptions with stable process exit codes."""

from __future__ import annotations

import shlex
from collections.abc import Sequence


class SbcImagerError(Exception):
    """Base class for every expected sbc-imager failure."""

    exit_code: int = 1

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class ConfigError(SbcImagerError):
    """Invalid configuration, manifest, or command usage."""

    exit_code = 2


class SafetyError(SbcImagerError):
    """A destructive operation was refused."""

    exit_code = 2


class SourceError(SbcImagerError):
    """A source could not be resolved, fetched, or verified."""

    exit_code = 1


class AssemblerError(SbcImagerError):
    """The card image could not be assembled."""

    exit_code = 1


class VerificationError(SbcImagerError):
    """A built artifact failed verification."""

    exit_code = 1


class CommandError(SbcImagerError):
    """An external command exited unsuccessfully."""

    exit_code = 1

    def __init__(self, returncode: int, args: Sequence[str], stderr: str) -> None:
        from sbc_imager.runner import redact_url

        self.returncode = returncode
        self.command = tuple(redact_url(str(arg)) for arg in args)
        self.stderr = stderr
        message = f"command failed with exit code {returncode}: {shlex.join(self.command)}"
        super().__init__(message)
