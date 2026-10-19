from __future__ import annotations

import io
import json

from sbc_imager.progress import (
    JsonReporter,
    NullReporter,
    ProgressEvent,
    TextReporter,
    encode_progress_line,
    make_reporter,
    parse_progress_line,
)


def test_text_reporter_when_phase_has_counts_prints_progress_and_elapsed() -> None:
    stream = io.StringIO()
    reporter = TextReporter(stream)

    reporter.emit(ProgressEvent("copy", "Copying files", 0, 2))
    reporter.emit(ProgressEvent("copy", "Copying files", 1, 2))
    reporter.emit(ProgressEvent("copy", "Copied files", 2, 2, done=True))

    output = stream.getvalue()
    assert "copy: Copying files 0/2" in output
    assert "copy: Copying files 1/2" in output
    assert "copy: Copied files 2/2 (" in output


def test_text_reporter_when_phase_has_no_counts_reports_phase() -> None:
    stream = io.StringIO()
    reporter = TextReporter(stream)

    reporter.emit(ProgressEvent("fsck", "Checking filesystem"))
    reporter.emit(ProgressEvent("fsck", "Checked filesystem", done=True))

    output = stream.getvalue()
    assert "fsck: Checking filesystem" in output
    assert "fsck: Checked filesystem (" in output


def test_json_reporter_when_events_emitted_writes_json_lines() -> None:
    stream = io.StringIO()
    reporter = JsonReporter(stream)

    reporter.emit(ProgressEvent("stage", "Staging files", 1, 3))

    payload = json.loads(stream.getvalue())
    assert payload == {
        "current": 1,
        "done": False,
        "event": "progress",
        "message": "Staging files",
        "phase": "stage",
        "total": 3,
    }


def test_progress_line_round_trip() -> None:
    event = ProgressEvent("prepare", "Creating sparse image", 0, 4)

    assert parse_progress_line(encode_progress_line(event)) == event
    assert parse_progress_line("ordinary output") is None
    assert parse_progress_line("SBC_PROGRESS not-json") is None


def test_make_reporter_when_mode_selected() -> None:
    stream = io.StringIO()

    assert isinstance(make_reporter("none", stream), NullReporter)
    assert isinstance(make_reporter("human", stream), TextReporter)
    assert isinstance(make_reporter("json", stream), JsonReporter)
    assert isinstance(make_reporter("auto", stream), NullReporter)
