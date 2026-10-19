"""Build and run the privileged assembler container."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sbc_imager.errors import AssemblerError, CommandError
from sbc_imager.runner import CommandResult, Runner

DEFAULT_TAG = "sbc-imager-assembler:local"
DOCKER_HINT = "install Docker Desktop or Colima and ensure 'docker' is on PATH"
PRIVILEGE_HINT = (
    "grant the container loop-device access with --privileged; on macOS enable "
    "Colima's privileged/loop support"
)
_DAEMON_MARKERS = (
    "cannot connect to the docker daemon",
    "is the docker daemon running",
    "error during connect",
    "connection refused",
)


def _validate_tag(tag: str) -> None:
    last_component = tag.rsplit("/", 1)[-1]
    _, separator, version = last_component.rpartition(":")
    if not separator or not version or version == "latest":
        raise AssemblerError(
            "refusing to use the mutable ':latest' tag",
            hint=f"use an explicit tag such as {DEFAULT_TAG}",
        )


def _docker(runner: Runner, args: list[str]) -> CommandResult:
    try:
        return runner.run(args, check=False)
    except OSError as error:
        raise AssemblerError(f"docker is not available: {error}", hint=DOCKER_HINT) from error


def _daemon_unavailable(stderr: str) -> bool:
    text = stderr.casefold()
    return any(marker in text for marker in _DAEMON_MARKERS)


def _preflight_error(returncode: int) -> AssemblerError:
    return AssemblerError(
        f"assembler preflight failed with exit code {returncode}",
        hint=PRIVILEGE_HINT,
    )


def ensure_container(
    runner: Runner,
    tag: str = DEFAULT_TAG,
    context: Path = Path("."),
) -> None:
    """Ensure the tagged assembler image exists, building it if necessary."""
    _validate_tag(tag)
    inspected = _docker(runner, ["docker", "image", "inspect", tag])
    if inspected.returncode == 0:
        return
    if _daemon_unavailable(inspected.stderr):
        raise AssemblerError(
            "docker is not available: the daemon is unreachable",
            hint=DOCKER_HINT,
        )
    built = _docker(runner, ["docker", "build", "-t", tag, str(Path(context))])
    if built.returncode != 0:
        detail = built.stderr.strip() or f"exit code {built.returncode}"
        raise AssemblerError(
            f"docker build failed for {tag}: {detail}",
            hint=DOCKER_HINT,
        )


def preflight(
    runner: Runner,
    tag: str = DEFAULT_TAG,
    *,
    on_line: Callable[[str], None] = print,
) -> None:
    """Run the assembler's privileged preflight and raise on failure."""
    _validate_tag(tag)
    args = [
        "docker",
        "run",
        "--rm",
        "--privileged",
        "--network",
        "none",
        tag,
        "python",
        "-m",
        "sbc_imager.assembler",
        "--preflight",
    ]
    try:
        returncode = runner.stream(args, on_line=on_line)
    except OSError as error:
        raise AssemblerError(f"docker is not available: {error}", hint=DOCKER_HINT) from error
    except CommandError as error:
        raise _preflight_error(error.returncode) from error
    if returncode != 0:
        raise _preflight_error(returncode)


def run_assembler(
    runner: Runner,
    tag: str = DEFAULT_TAG,
    *,
    stage_dir: Path,
    stage_plan_path: Path,
    out_dir: Path,
    name: str,
    label: str,
    work_dir: Path,
    on_line: Callable[[str], None] = print,
) -> int:
    """Assemble an image in the container, streaming logs and returning its exit code."""
    _validate_tag(tag)
    plan_dir = Path(work_dir).resolve()
    stage = Path(stage_dir).resolve()
    output = Path(out_dir).resolve()
    plan_name = Path(stage_plan_path).name
    args = [
        "docker",
        "run",
        "--rm",
        "--privileged",
        "--network",
        "none",
        "-v",
        f"{plan_dir}:/plan:ro",
        "-v",
        f"{stage}:/stage:ro",
        "-v",
        f"{output}:/out",
        tag,
        "python",
        "-m",
        "sbc_imager.assembler",
        "assemble",
        "--stage",
        "/stage",
        "--plan",
        f"/plan/{plan_name}",
        "--out",
        f"/out/{name}.img",
        "--work",
        "/tmp/assemble",
        "--label",
        label,
    ]
    try:
        return runner.stream(args, on_line=on_line)
    except OSError as error:
        raise AssemblerError(f"docker is not available: {error}", hint=DOCKER_HINT) from error


def verify_image(
    runner: Runner,
    tag: str,
    image_path: Path,
    out_dir: Path,
    name: str,
    *,
    on_line: Callable[[str], None] = print,
) -> int:
    """Verify an existing image in the container, streaming logs and returning its exit code."""
    _validate_tag(tag)
    image = Path(image_path).resolve()
    if not image.is_file():
        raise AssemblerError(f"image does not exist: {image}")
    output = Path(out_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    args = [
        "docker",
        "run",
        "--rm",
        "--privileged",
        "--network",
        "none",
        "-v",
        f"{image.parent}:/image:ro",
        "-v",
        f"{output}:/out",
        tag,
        "python",
        "-m",
        "sbc_imager.assembler",
        "verify",
        "--image",
        f"/image/{name}",
        "--out",
        "/out/tree.json",
    ]
    try:
        return runner.stream(args, on_line=on_line)
    except OSError as error:
        raise AssemblerError(f"docker is not available: {error}", hint=DOCKER_HINT) from error
