"""Injectable command execution with captured and streamed output."""

from __future__ import annotations

import contextlib
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sbc_imager.errors import CommandError

PathLike = Path | str


@dataclass(frozen=True, slots=True)
class CommandResult:
    """The captured outcome of a finished command."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_s: float


class Runner(Protocol):
    """The system-execution seam used by every component that spawns processes."""

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: PathLike | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        check: bool = True,
    ) -> CommandResult: ...

    def stream(
        self,
        args: Sequence[str],
        *,
        on_line: Callable[[str], None],
        cwd: PathLike | None = None,
        env: Mapping[str, str] | None = None,
    ) -> int: ...


class SubprocessRunner:
    """A Runner backed by the standard library subprocess module."""

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: PathLike | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        check: bool = True,
    ) -> CommandResult:
        command = [str(arg) for arg in args]
        started = time.monotonic()
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )
        result = CommandResult(
            args=tuple(command),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_s=time.monotonic() - started,
        )
        if check and result.returncode != 0:
            raise CommandError(result.returncode, result.args, result.stderr)
        return result

    def stream(
        self,
        args: Sequence[str],
        *,
        on_line: Callable[[str], None],
        cwd: PathLike | None = None,
        env: Mapping[str, str] | None = None,
    ) -> int:
        command = [str(arg) for arg in args]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=cwd,
            env=env,
        )
        try:
            assert process.stdout is not None
            for line in process.stdout:
                on_line(line.rstrip("\n"))
            returncode = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)
            process.kill()
            process.wait()
            raise
        if returncode != 0:
            raise CommandError(returncode, command, "")
        return returncode


def redact_url(url: str) -> str:
    """Remove userinfo from a URL so credentials never reach logs."""
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    authority_end = len(rest)
    for delimiter in "/?#":
        index = rest.find(delimiter)
        if index != -1:
            authority_end = min(authority_end, index)
    authority = rest[:authority_end]
    if "@" not in authority:
        return url
    host = authority.rsplit("@", 1)[1]
    return f"{scheme}://{host}{rest[authority_end:]}"
