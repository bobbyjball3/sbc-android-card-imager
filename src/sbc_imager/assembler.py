"""Assemble and verify a single-partition MBR+exFAT card image."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from sbc_imager import fs, mbr
from sbc_imager.assembler_report import (
    SCHEMA_VERSION,
    Report,
    expected_files,
    load_plan,
    report_bytes,
    tree_bytes,
    tree_sha256,
    validate_label,
)
from sbc_imager.assembler_steps import (
    MountState,
    attach_loop,
    check_filesystem,
    cleanup,
    detach_loop,
    make_filesystem,
    mount_filesystem,
    populate,
    unmount,
    verify,
)
from sbc_imager.errors import AssemblerError, SbcImagerError
from sbc_imager.runner import Runner, SubprocessRunner

Progress = Callable[[str, int, int], None]
_LOOP_RE = re.compile(r"/dev/loop\d+")


def _prepare_work(work: Path) -> tuple[Path, Path]:
    work.mkdir(parents=True, exist_ok=True)
    image = work / "image.img"
    mountpoint = work / "mnt"
    if mountpoint.exists():
        shutil.rmtree(mountpoint)
    mountpoint.mkdir(parents=True)
    return image, mountpoint


def _write_header(image: Path, partition_bytes: int) -> None:
    header = mbr.build_mbr(2048, partition_sectors=partition_bytes // 512)
    fs.write_at(image, 0, header)


def _publish(image: Path, out_path: Path) -> None:
    partial = Path(str(out_path) + ".partial")
    try:
        fs.copy_sparse(image, partial)
        with partial.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(partial, out_path)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def assemble(
    stage_dir: Path,
    stage_plan_path: Path,
    out_path: Path,
    work_dir: Path,
    runner: Runner,
    progress: Progress | None = None,
    *,
    label: str | None = None,
) -> Report:
    """Build, verify, and atomically publish an image from a stage plan."""
    stage = Path(stage_dir)
    if not stage.is_dir():
        raise AssemblerError(f"stage directory does not exist: {stage}")
    plan = load_plan(stage_plan_path)
    effective_label = plan.label if label is None else label
    validate_label(effective_label)

    work = Path(work_dir)
    image, mountpoint = _prepare_work(work)
    fs.create_sparse(image, plan.image_bytes)
    _write_header(image, plan.partition_bytes)
    expected_files(plan)

    loop: str | None = None
    mounted = False
    failure: BaseException | None = None
    try:
        loop = attach_loop(runner, image, plan.partition_offset_bytes, plan.partition_bytes)
        make_filesystem(runner, effective_label, loop)
        mount_filesystem(runner, loop, mountpoint, readonly=False)
        mounted = True
        populate(stage, mountpoint, plan, progress)
        os.sync()
        unmount(runner, mountpoint)
        mounted = False
        check_filesystem(runner, loop)
        mount_filesystem(runner, loop, mountpoint, readonly=True)
        mounted = True
        tree = verify(mountpoint, plan, progress)

        tree_path = work / "tree.json"
        tree_path.write_bytes(tree_bytes(tree))
        report = Report(
            schema_version=SCHEMA_VERSION,
            image_bytes=plan.image_bytes,
            partition_bytes=plan.partition_bytes,
            partition_offset_bytes=plan.partition_offset_bytes,
            content_files=plan.totals_entries,
            content_bytes=plan.totals_content_bytes,
            tree_sha256=tree_sha256(tree),
            fsck_ok=True,
            label=effective_label,
            tree=tree,
            tree_path=tree_path,
            report_path=work / "report.json",
        )
        report.report_path.write_bytes(report_bytes(report))

        unmount(runner, mountpoint)
        mounted = False
        detach_loop(runner, loop)
        loop = None
        _publish(image, Path(out_path))
        return report
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try:
            cleanup(runner, MountState(mountpoint, loop, mounted))
        except AssemblerError as cleanup_error:
            if failure is not None:
                raise cleanup_error from failure
            raise


def preflight(runner: Runner, *, filesystems_path: Path = Path("/proc/filesystems")) -> None:
    """Check that loop devices, exFAT tools, and kernel exFAT support exist."""
    required = ("losetup", "mkfs.exfat", "fsck.exfat")
    missing = [tool for tool in required if shutil.which(tool) is None]
    if missing:
        raise AssemblerError(
            f"preflight: missing required tools: {', '.join(missing)}",
            hint="install util-linux and exfatprogs",
        )
    result = runner.run(["losetup", "-f"], check=False)
    device = result.stdout.strip()
    if result.returncode != 0 or _LOOP_RE.fullmatch(device) is None:
        raise AssemblerError(
            "preflight: no usable loop device from 'losetup -f'",
            hint="run with --privileged (Docker) or enable loop devices on the host",
        )
    for tool in ("mkfs.exfat", "fsck.exfat"):
        probe = runner.run([tool, "--version"], check=False)
        output = f"{probe.stdout}\n{probe.stderr}".casefold()
        if probe.returncode != 0 and "exfatprogs" not in output:
            raise AssemblerError(
                f"preflight: {tool} failed to report a version",
                hint="install a working exfatprogs",
            )
    try:
        filesystems = Path(filesystems_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise AssemblerError(
            f"preflight: cannot read {filesystems_path}: {exc}",
            hint="the assembler requires a Linux kernel with exFAT support",
        ) from exc
    supported = any(line.split()[-1:] == ["exfat"] for line in filesystems.splitlines())
    if not supported:
        raise AssemblerError(
            "preflight: the kernel does not provide exFAT support",
            hint="load the exfat kernel module or use a kernel that includes it",
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m sbc_imager.assembler",
        description="Assemble and verify an MBR+exFAT card image.",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="check loop devices, exfatprogs, and kernel exFAT support",
    )
    commands = parser.add_subparsers(dest="command")
    assemble_parser = commands.add_parser("assemble", help="build a verified image")
    assemble_parser.add_argument("--stage", type=Path, required=True)
    assemble_parser.add_argument("--plan", type=Path, required=True)
    assemble_parser.add_argument("--out", type=Path, required=True)
    assemble_parser.add_argument("--work", type=Path, required=True)
    assemble_parser.add_argument("--label", help="override the exFAT volume label")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the assembler CLI, returning a process exit code."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.preflight:
            preflight(SubprocessRunner())
            print("preflight ok: loop devices, mkfs.exfat, fsck.exfat, and exfat are available")
            return 0
        if args.command != "assemble":
            parser.print_help()
            return 2
        report = assemble(
            args.stage,
            args.plan,
            args.out,
            args.work,
            SubprocessRunner(),
            label=args.label,
        )
        print(
            f"assembled {report.content_files} files ({report.content_bytes} bytes) into {args.out}"
        )
        return 0
    except SbcImagerError as error:
        print(f"Error: {error.message}", file=sys.stderr)
        if error.hint:
            print(f"Hint: {error.hint}", file=sys.stderr)
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
