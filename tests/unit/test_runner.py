import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

import sbc_imager.runner as runner_module
from sbc_imager.errors import CommandError
from sbc_imager.runner import CommandResult, SubprocessRunner, redact_url
from tests.fakes import FakeRunner


def test_run_when_command_succeeds_returns_captured_output() -> None:
    result = SubprocessRunner().run([sys.executable, "-c", "print('ok')"])

    assert isinstance(result, CommandResult)
    assert result.returncode == 0
    assert result.stdout == "ok\n"
    assert result.stderr == ""
    assert result.args == (sys.executable, "-c", "print('ok')")
    assert result.duration_s >= 0


def test_run_when_command_fails_and_check_enabled_raises_command_error() -> None:
    with pytest.raises(CommandError) as caught:
        SubprocessRunner().run([sys.executable, "-c", "import sys; sys.exit(7)"])

    assert caught.value.returncode == 7
    assert caught.value.command[0] == sys.executable


def test_run_when_command_fails_and_check_disabled_returns_result() -> None:
    result = SubprocessRunner().run(
        [sys.executable, "-c", "import sys; sys.exit(7)"],
        check=False,
    )

    assert result.returncode == 7


def test_run_when_cwd_and_env_given_uses_them(tmp_path: Path) -> None:
    result = SubprocessRunner().run(
        [sys.executable, "-c", "import os; print(os.getcwd()); print(os.environ['QA_TOKEN'])"],
        cwd=tmp_path,
        env={"QA_TOKEN": "present"},
    )

    assert result.returncode == 0
    output_lines = result.stdout.splitlines()
    assert output_lines == [str(tmp_path), "present"]


def test_run_when_stdin_given_forwards_it() -> None:
    result = SubprocessRunner().run(
        [sys.executable, "-c", "import sys; print(sys.stdin.read().strip())"],
        stdin="hello\n",
    )

    assert result.returncode == 0
    assert result.stdout == "hello\n"


def test_stream_when_command_emits_lines_forwards_each_line() -> None:
    lines: list[str] = []

    returncode = SubprocessRunner().stream(
        [sys.executable, "-c", "print('one'); print('two')"],
        on_line=lines.append,
    )

    assert returncode == 0
    assert lines == ["one", "two"]


def test_stream_when_command_fails_raises_command_error() -> None:
    with pytest.raises(CommandError) as caught:
        SubprocessRunner().stream(
            [sys.executable, "-c", "import sys; sys.exit(3)"],
            on_line=lambda _line: None,
        )

    assert caught.value.returncode == 3


def test_stream_when_interrupted_terminates_then_kills_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions: list[str] = []

    class FakePopen:
        def __init__(self, args: list[str], **_kwargs: object) -> None:
            self.args = args
            self.stdout = self._output()

        def _output(self) -> Iterator[str]:
            yield "starting\n"
            raise KeyboardInterrupt

        def terminate(self) -> None:
            actions.append("terminate")

        def kill(self) -> None:
            actions.append("kill")

        def wait(self, timeout: float | None = None) -> int:
            actions.append(f"wait:{timeout}")
            if timeout is not None:
                raise subprocess.TimeoutExpired(self.args, timeout)
            return 0

    monkeypatch.setattr(runner_module.subprocess, "Popen", FakePopen)

    with pytest.raises(KeyboardInterrupt):
        SubprocessRunner().stream(["slow-command"], on_line=lambda _line: None)

    assert actions == ["terminate", "wait:5", "kill", "wait:None"]


def test_stream_when_popen_returns_nonzero_raises_and_reports_returncode() -> None:
    class FakePopen:
        def __init__(self, args: list[str], **_kwargs: object) -> None:
            self.args = args
            self.stdout = iter(["line\n"])

        def wait(self, timeout: float | None = None) -> int:
            assert timeout is None
            return 4

    import sbc_imager.runner as module

    original = module.subprocess.Popen
    module.subprocess.Popen = FakePopen
    try:
        with pytest.raises(CommandError) as caught:
            SubprocessRunner().stream(["bad"], on_line=lambda _line: None)
    finally:
        module.subprocess.Popen = original

    assert caught.value.returncode == 4


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://user:secret@example.com/repo.git", "https://example.com/repo.git"),
        ("https://token@example.com/path?q=1#frag", "https://example.com/path?q=1#frag"),
        ("https://example.com/repo.git", "https://example.com/repo.git"),
        ("git@example.com:owner/repo.git", "git@example.com:owner/repo.git"),
        ("ssh://git@example.com/repo.git", "ssh://example.com/repo.git"),
    ],
)
def test_redact_url_when_credentials_present_removes_userinfo(url: str, expected: str) -> None:
    assert redact_url(url) == expected


def test_redact_url_when_credentials_present_never_returns_them() -> None:
    assert "user:secret" not in redact_url("https://user:secret@example.com/x")


def test_fake_runner_when_run_records_exact_argv_and_returns_scripted_result() -> None:
    scripted = CommandResult(("tool", "arg"), 0, "out\n", "", 0.01)
    runner = FakeRunner(results=[scripted])

    result = runner.run(["tool", "arg"], cwd="/tmp", stdin="input")

    assert result is scripted
    assert runner.commands == [["tool", "arg"]]
    assert runner.calls[0].cwd == "/tmp"
    assert runner.calls[0].stdin == "input"
    assert runner.calls[0].kind == "run"


def test_fake_runner_when_stream_returns_scripted_lines_in_order() -> None:
    runner = FakeRunner(lines=["one", "two"])
    lines: list[str] = []

    returncode = runner.stream(["tool"], on_line=lines.append)

    assert returncode == 0
    assert lines == ["one", "two"]
    assert runner.commands == [["tool"]]
    assert runner.calls[0].kind == "stream"


def test_fake_runner_when_stream_returncode_nonzero_raises_command_error() -> None:
    runner = FakeRunner(lines=["oops"], returncode=9)

    with pytest.raises(CommandError) as caught:
        runner.stream(["tool"], on_line=lambda _line: None)

    assert caught.value.returncode == 9


def test_fake_runner_when_scripted_results_exhausted_raises_assertion_error() -> None:
    runner = FakeRunner()

    with pytest.raises(AssertionError):
        runner.run(["unscripted"])
