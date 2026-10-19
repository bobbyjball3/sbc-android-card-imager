from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from sbc_imager.container import DEFAULT_TAG, ensure_container, preflight, run_assembler
from sbc_imager.errors import AssemblerError, CommandError
from sbc_imager.runner import CommandResult
from tests.fakes import FakeRunner


def _completed(*, returncode: int = 0, stderr: str = "") -> CommandResult:
    return CommandResult((), returncode, "", stderr, 0.0)


class MissingDockerRunner:
    """A Runner whose executable is absent from PATH."""

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        check: bool = True,
    ) -> CommandResult:
        del cwd, env, stdin, check
        raise FileNotFoundError(2, "No such file or directory", str(args[0]))

    def stream(
        self,
        args: Sequence[str],
        *,
        on_line: Callable[[str], None],
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> int:
        del on_line, cwd, env
        raise FileNotFoundError(2, "No such file or directory", str(args[0]))


def test_default_tag_when_referenced_is_local_and_not_latest() -> None:
    assert DEFAULT_TAG == "sbc-imager-assembler:local"
    assert not DEFAULT_TAG.endswith(":latest")


def test_ensure_container_when_image_exists_does_not_build(tmp_path: Path) -> None:
    runner = FakeRunner([_completed()])

    ensure_container(runner, context=tmp_path)

    assert runner.commands == [["docker", "image", "inspect", DEFAULT_TAG]]
    assert all(call.kind == "run" for call in runner.calls)


def test_ensure_container_when_image_missing_builds_context(tmp_path: Path) -> None:
    runner = FakeRunner([_completed(returncode=1), _completed()])

    ensure_container(runner, context=tmp_path)

    assert runner.commands == [
        ["docker", "image", "inspect", DEFAULT_TAG],
        ["docker", "build", "-t", DEFAULT_TAG, str(tmp_path)],
    ]


def test_ensure_container_when_docker_missing_raises_with_install_hint(
    tmp_path: Path,
) -> None:
    with pytest.raises(AssemblerError) as caught:
        ensure_container(MissingDockerRunner(), context=tmp_path)

    assert "docker" in caught.value.message.casefold()
    assert caught.value.hint is not None
    assert "install" in caught.value.hint.casefold()
    assert "path" in caught.value.hint.casefold()


def test_ensure_container_when_daemon_unreachable_does_not_build(tmp_path: Path) -> None:
    runner = FakeRunner(
        [_completed(returncode=1, stderr="Cannot connect to the Docker daemon at unix:///x")]
    )

    with pytest.raises(AssemblerError) as caught:
        ensure_container(runner, context=tmp_path)

    assert runner.commands == [["docker", "image", "inspect", DEFAULT_TAG]]
    assert caught.value.hint is not None


def test_ensure_container_when_build_fails_raises_assembler_error(tmp_path: Path) -> None:
    runner = FakeRunner(
        [_completed(returncode=1), _completed(returncode=1, stderr="build exploded")]
    )

    with pytest.raises(AssemblerError) as caught:
        ensure_container(runner, context=tmp_path)

    assert "build" in caught.value.message.casefold()
    assert "build exploded" in caught.value.message


def test_preflight_when_ok_streams_exact_privileged_command() -> None:
    lines = ["preflight ok: loop devices, mkfs.exfat, fsck.exfat, and exfat are available"]
    runner = FakeRunner(lines=lines)

    seen: list[str] = []
    preflight(runner, on_line=seen.append)

    assert runner.commands == [
        [
            "docker",
            "run",
            "--rm",
            "--privileged",
            "--network",
            "none",
            DEFAULT_TAG,
            "python",
            "-m",
            "sbc_imager.assembler",
            "--preflight",
        ]
    ]
    assert runner.calls[0].kind == "stream"
    assert seen == lines


def test_preflight_when_container_fails_raises_assembler_error_with_privilege_hint() -> None:
    runner = FakeRunner(returncode=3)

    with pytest.raises(AssemblerError) as caught:
        preflight(runner)

    assert "preflight" in caught.value.message.casefold()
    assert caught.value.hint is not None
    assert "--privileged" in caught.value.hint
    assert "Colima" in caught.value.hint


def test_preflight_when_docker_missing_raises_with_install_hint() -> None:
    with pytest.raises(AssemblerError) as caught:
        preflight(MissingDockerRunner())

    assert "docker" in caught.value.message.casefold()
    assert caught.value.hint is not None
    assert "install" in caught.value.hint.casefold()


def test_run_assembler_streams_exact_command_and_mounts(tmp_path: Path) -> None:
    stage_dir = tmp_path / "stage"
    work_dir = tmp_path / "work"
    out_dir = tmp_path / "out"
    stage_plan = work_dir / "stage-plan.json"
    lines = ["assembled 3 files (12 bytes) into /out/card.img"]
    runner = FakeRunner(lines=lines)

    seen: list[str] = []
    returncode = run_assembler(
        runner,
        tag=DEFAULT_TAG,
        stage_dir=stage_dir,
        stage_plan_path=stage_plan,
        out_dir=out_dir,
        name="card",
        label="CANNOLI",
        work_dir=work_dir,
        on_line=seen.append,
    )

    assert returncode == 0
    assert runner.commands == [
        [
            "docker",
            "run",
            "--rm",
            "--privileged",
            "--network",
            "none",
            "-v",
            f"{work_dir.resolve()}:/plan:ro",
            "-v",
            f"{stage_dir.resolve()}:/stage:ro",
            "-v",
            f"{out_dir.resolve()}:/out",
            DEFAULT_TAG,
            "python",
            "-m",
            "sbc_imager.assembler",
            "assemble",
            "--stage",
            "/stage",
            "--plan",
            "/plan/stage-plan.json",
            "--out",
            "/out/card.img",
            "--work",
            "/tmp/assemble",
            "--label",
            "CANNOLI",
        ]
    ]
    assert runner.calls[0].kind == "stream"
    assert seen == lines


def test_run_assembler_when_container_exits_nonzero_propagates_exit_code(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(returncode=7)

    with pytest.raises(CommandError) as caught:
        run_assembler(
            runner,
            tag=DEFAULT_TAG,
            stage_dir=tmp_path / "stage",
            stage_plan_path=tmp_path / "work" / "stage-plan.json",
            out_dir=tmp_path / "out",
            name="card",
            label="CANNOLI",
            work_dir=tmp_path / "work",
        )

    assert caught.value.returncode == 7


def test_run_assembler_when_docker_missing_raises_with_install_hint(tmp_path: Path) -> None:
    with pytest.raises(AssemblerError) as caught:
        run_assembler(
            MissingDockerRunner(),
            tag=DEFAULT_TAG,
            stage_dir=tmp_path / "stage",
            stage_plan_path=tmp_path / "work" / "stage-plan.json",
            out_dir=tmp_path / "out",
            name="card",
            label="CANNOLI",
            work_dir=tmp_path / "work",
        )

    assert "docker" in caught.value.message.casefold()
    assert caught.value.hint is not None
    assert "install" in caught.value.hint.casefold()


class ReturningNonzeroRunner:
    """A Runner that reports a nonzero exit without raising."""

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        check: bool = True,
    ) -> CommandResult:
        del args, cwd, env, stdin, check
        return _completed()

    def stream(
        self,
        args: Sequence[str],
        *,
        on_line: Callable[[str], None],
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> int:
        del args, on_line, cwd, env
        return 4


def test_preflight_when_stream_returns_nonzero_without_raising_still_fails() -> None:
    with pytest.raises(AssemblerError, match="exit code 4"):
        preflight(ReturningNonzeroRunner())


@pytest.mark.parametrize("tag", ["sbc-imager-assembler:latest", "sbc-imager-assembler"])
def test_container_operations_when_tag_is_implicitly_latest_are_refused(
    tag: str, tmp_path: Path
) -> None:
    runner = FakeRunner()

    with pytest.raises(AssemblerError, match="latest"):
        ensure_container(runner, tag=tag, context=tmp_path)

    assert runner.calls == []


@pytest.mark.parametrize("function", ["ensure", "preflight", "run"])
def test_container_operations_when_tag_is_latest_are_refused(function: str, tmp_path: Path) -> None:
    runner = FakeRunner()
    tag = "sbc-imager-assembler:latest"

    with pytest.raises(AssemblerError, match="latest"):
        if function == "ensure":
            ensure_container(runner, tag=tag, context=tmp_path)
        elif function == "preflight":
            preflight(runner, tag=tag)
        else:
            run_assembler(
                runner,
                tag=tag,
                stage_dir=tmp_path / "stage",
                stage_plan_path=tmp_path / "work" / "stage-plan.json",
                out_dir=tmp_path / "out",
                name="card",
                label="CANNOLI",
                work_dir=tmp_path / "work",
            )

    assert runner.calls == []
