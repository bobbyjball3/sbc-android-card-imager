"""Test doubles for the injectable system runner."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sbc_imager.errors import CommandError
from sbc_imager.runner import CommandResult


@dataclass(frozen=True, slots=True)
class RecordedCall:
    """A command invocation captured by FakeRunner."""

    args: tuple[str, ...]
    kind: Literal["run", "stream"]
    cwd: Path | str | None = None
    env: Mapping[str, str] | None = None
    stdin: str | None = None


class FakeRunner:
    """A Runner that records calls and replays scripted results and output."""

    def __init__(
        self,
        results: Sequence[CommandResult] | None = None,
        *,
        lines: Sequence[str] = (),
        returncode: int = 0,
    ) -> None:
        self.calls: list[RecordedCall] = []
        self._results: deque[CommandResult] = deque(results or ())
        self._lines = tuple(lines)
        self._returncode = returncode

    @property
    def commands(self) -> list[list[str]]:
        return [list(call.args) for call in self.calls]

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        check: bool = True,
    ) -> CommandResult:
        self.calls.append(RecordedCall(args=tuple(args), kind="run", cwd=cwd, env=env, stdin=stdin))
        if not self._results:
            raise AssertionError(f"FakeRunner has no scripted result for {list(args)!r}")
        result = self._results.popleft()
        if check and result.returncode != 0:
            raise CommandError(result.returncode, result.args, result.stderr)
        return result

    def stream(
        self,
        args: Sequence[str],
        *,
        on_line: Callable[[str], None],
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> int:
        self.calls.append(RecordedCall(args=tuple(args), kind="stream", cwd=cwd, env=env))
        for line in self._lines:
            on_line(line)
        if self._returncode != 0:
            raise CommandError(self._returncode, tuple(args), "")
        return self._returncode
