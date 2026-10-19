"""Shared progress events and human/JSON reporters."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass
from typing import IO, Final, Protocol

PREFIX: Final = "SBC_PROGRESS "


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """One progress update, optionally with a known current/total pair."""

    phase: str
    message: str
    current: int | None = None
    total: int | None = None
    done: bool = False


class ProgressReporter(Protocol):
    """The shared progress sink used by commands."""

    def emit(self, event: ProgressEvent) -> None: ...

    def close(self) -> None: ...


class NullReporter:
    """A reporter that discards every event."""

    def emit(self, event: ProgressEvent) -> None:
        del event

    def close(self) -> None:
        return


class TextReporter:
    """Write concise phase/count/elapsed lines to a text stream."""

    def __init__(self, stream: IO[str] | None = None) -> None:
        self.stream = stream if stream is not None else sys.stderr
        self._started: dict[str, float] = {}

    def emit(self, event: ProgressEvent) -> None:
        now = time.monotonic()
        started = self._started.setdefault(event.phase, now)
        if event.done:
            elapsed = max(0.0, now - started)
            self._started.pop(event.phase, None)
            suffix = f" ({elapsed:.1f}s)"
            if event.current is not None and event.total is not None:
                line = f"{event.phase}: {event.message} {event.current}/{event.total}{suffix}"
            else:
                line = f"{event.phase}: {event.message}{suffix}"
        elif event.current is not None and event.total is not None:
            line = f"{event.phase}: {event.message} {event.current}/{event.total}"
        else:
            line = f"{event.phase}: {event.message}"
        print(line, file=self.stream, flush=True)

    def close(self) -> None:
        self.stream.flush()


class JsonReporter:
    """Write one JSON object per progress event to a text stream."""

    def __init__(self, stream: IO[str] | None = None) -> None:
        self.stream = stream if stream is not None else sys.stderr

    def emit(self, event: ProgressEvent) -> None:
        payload = {"event": "progress", **asdict(event)}
        print(json.dumps(payload, sort_keys=True), file=self.stream, flush=True)

    def close(self) -> None:
        self.stream.flush()


def make_reporter(mode: str = "auto", stream: IO[str] | None = None) -> ProgressReporter:
    """Build a reporter for ``auto``, ``human``, ``json``, or ``none``."""
    selected = mode.casefold()
    if selected not in {"auto", "human", "json", "none"}:
        raise ValueError(f"unsupported progress mode {mode!r}")
    if selected == "none":
        return NullReporter()
    target = stream if stream is not None else sys.stderr
    if selected == "json":
        return JsonReporter(target)
    if selected == "human" or (selected == "auto" and target.isatty()):
        return TextReporter(target)
    return NullReporter()


def encode_progress_line(event: ProgressEvent) -> str:
    """Encode an event for the container-to-host line protocol."""
    return PREFIX + json.dumps(asdict(event), sort_keys=True)


def parse_progress_line(line: str) -> ProgressEvent | None:
    """Decode a container progress line, returning None for ordinary output."""
    if not line.startswith(PREFIX):
        return None
    try:
        payload = json.loads(line[len(PREFIX) :])
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    phase = payload.get("phase")
    message = payload.get("message")
    if not isinstance(phase, str) or not isinstance(message, str):
        return None
    current = payload.get("current")
    total = payload.get("total")
    done = payload.get("done", False)
    if current is not None and (not isinstance(current, int) or isinstance(current, bool)):
        return None
    if total is not None and (not isinstance(total, int) or isinstance(total, bool)):
        return None
    if not isinstance(done, bool):
        return None
    return ProgressEvent(phase, message, current, total, done)
