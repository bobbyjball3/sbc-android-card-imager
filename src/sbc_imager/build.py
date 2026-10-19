"""Orchestrate fetch, stage, assemble, verify, and atomic image publication."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from sbc_imager import container
from sbc_imager import verify as verification
from sbc_imager.config import Manifest, load_manifest
from sbc_imager.errors import AssemblerError, SafetyError, VerificationError
from sbc_imager.fs import copy_sparse, sha256_file
from sbc_imager.planner import BuildPlan, build_plan, source_rows
from sbc_imager.runner import SubprocessRunner
from sbc_imager.sizes import format_size
from sbc_imager.sources import ResolvedSource, SourceCache
from sbc_imager.staging import StageResult, stage
from sbc_imager.validation import Warning, validate_manifest
from sbc_imager.verify import VerifyReport

Log = Callable[[str], None]
DiskUsage = Callable[[Path], tuple[int, int, int]]
_MIB = 1024 * 1024


@dataclass(frozen=True, slots=True)
class BuildOptions:
    manifest_path: Path
    output: Path | None = None
    size: str | None = None
    reserve: str | None = None
    offline: bool = False
    force: bool = False
    keep_work: bool = False
    allow_branch: bool = False


@dataclass(frozen=True, slots=True)
class BuildReport:
    manifest: str
    image: str
    image_bytes: int
    partition_bytes: int
    offset: int
    content_files: int
    content_bytes: int
    sha256: str
    verify: VerifyReport
    sources: tuple[ResolvedSource, ...]
    warnings: tuple[Warning, ...]
    schema_version: int = 1

    def payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["verify"] = self.verify.payload()
        payload["sources"] = source_rows(self.sources)
        payload["warnings"] = [asdict(warning) for warning in self.warnings]
        return payload


@dataclass(frozen=True, slots=True)
class Services:
    load: Callable[[Path], Manifest]
    validate: Callable[[Manifest], Sequence[Warning]]
    resolve: Callable[..., Mapping[str, ResolvedSource]]
    plan: Callable[..., BuildPlan]
    stage: Callable[[BuildPlan, Path], StageResult]
    disk_usage: DiskUsage
    ensure_container: Callable[[], None]
    preflight: Callable[[Log], None]
    assemble: Callable[..., int]
    verify: Callable[..., VerifyReport]
    close: Callable[[], None]


def default_services() -> Services:
    cache = SourceCache()
    runner = SubprocessRunner()
    client = httpx.Client(follow_redirects=True, timeout=30.0)

    def resolve(
        manifest: Manifest, *, offline: bool, allow_branch: bool
    ) -> Mapping[str, ResolvedSource]:
        return verification._resolve_sources(
            manifest,
            cache,
            runner,
            client,
            offline=offline,
            allow_branch=allow_branch,
        )

    def assemble(
        plan: BuildPlan, staged: StageResult, out_dir: Path, name: str, on_line: Log
    ) -> int:
        return container.run_assembler(
            runner,
            stage_dir=staged.stage_dir,
            stage_plan_path=staged.stage_plan_path,
            out_dir=out_dir,
            name=name,
            label=plan.label,
            work_dir=staged.stage_plan_path.parent,
            on_line=on_line,
        )

    def verify(
        manifest_path: Path,
        image: Path,
        *,
        offline: bool,
        allow_branch: bool,
        on_line: Log,
    ) -> VerifyReport:
        return verification.verify_image(
            manifest_path,
            image,
            cache,
            runner,
            client,
            offline=offline,
            allow_branch=allow_branch,
            on_line=on_line,
        )

    return Services(
        load=load_manifest,
        validate=validate_manifest,
        resolve=resolve,
        plan=build_plan,
        stage=stage,
        disk_usage=shutil.disk_usage,
        ensure_container=lambda: container.ensure_container(runner),
        preflight=lambda on_line: container.preflight(runner, on_line=on_line),
        assemble=assemble,
        verify=verify,
        close=client.close,
    )


def _target(manifest: Manifest, output: Path | None) -> Path:
    return manifest.image.output if output is None else Path(output).expanduser().resolve()


def _refuse_existing(target: Path, force: bool) -> None:
    if not force and os.path.lexists(target):
        raise SafetyError(
            f"refusing to overwrite existing image {target}",
            hint="pass --force to replace it after the new image verifies",
        )


def _parent(target: Path) -> Path:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise AssemblerError(f"cannot create output directory {target.parent}: {error}") from error
    return target.parent


def _check_space(disk_usage: DiskUsage, work: Path, output_dir: Path, plan: BuildPlan) -> None:
    required = plan.content_bytes + plan.overhead_bytes + _MIB
    for label, path in (("work", work), ("output", output_dir)):
        try:
            _, _, free = disk_usage(path)
        except OSError as error:
            raise AssemblerError(
                f"cannot measure free space for the {label} filesystem {path}: {error}"
            ) from error
        if free < required:
            raise AssemblerError(
                f"insufficient free space on the {label} filesystem {path}: "
                f"need {format_size(required)}, have {format_size(free)}",
                hint="free space or choose an output on another volume",
            )


def _publish(image: Path, target: Path) -> None:
    partial = target.with_name(f"{target.name}.partial")
    try:
        copy_sparse(image, partial)
        with partial.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(partial, target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _describe(report: VerifyReport) -> str:
    for label, items in (
        ("missing", report.missing),
        ("extra", report.extra),
        ("mismatched", report.mismatched),
        ("missing dirs", report.missing_dirs),
    ):
        if items:
            return f"image verification failed: {label}: {', '.join(items)}"
    return "image verification failed: tree did not match"


def build_image(
    options: BuildOptions,
    services: Services | None = None,
    *,
    log: Log = print,
) -> BuildReport:
    active = services if services is not None else default_services()
    work: Path | None = None
    failure: BaseException | None = None
    try:
        manifest = active.load(options.manifest_path)
        active.validate(manifest)
        target = _target(manifest, options.output)
        _refuse_existing(target, options.force)
        sources = active.resolve(
            manifest, offline=options.offline, allow_branch=options.allow_branch
        )
        plan = active.plan(manifest, sources, size=options.size, reserve=options.reserve)
        output_dir = _parent(target)
        work = Path(tempfile.mkdtemp(prefix="sbc-build-"))
        _check_space(active.disk_usage, work, output_dir, plan)
        staged = active.stage(plan, work)
        log(f"Staged {len(plan.entries)} files in {work}")
        active.ensure_container()
        active.preflight(log)
        out_dir = work / "out"
        out_dir.mkdir()
        name = target.stem
        returncode = active.assemble(plan, staged, out_dir, name, log)
        if returncode != 0:
            raise AssemblerError(f"assembler failed with exit code {returncode}")
        image = out_dir / f"{name}.img"
        if not image.is_file():
            raise AssemblerError(f"assembler produced no image at {image}")
        verified = active.verify(
            options.manifest_path,
            image,
            offline=True,
            allow_branch=options.allow_branch,
            on_line=log,
        )
        if not verified.ok:
            raise VerificationError(_describe(verified))
        _publish(image, target)
        report = BuildReport(
            manifest=str(options.manifest_path),
            image=str(target),
            image_bytes=plan.image_bytes,
            partition_bytes=plan.partition_bytes,
            offset=plan.partition_offset_bytes,
            content_files=len(plan.entries),
            content_bytes=plan.content_bytes,
            sha256=sha256_file(target),
            verify=verified,
            sources=plan.sources,
            warnings=plan.warnings,
        )
        target.with_name(f"{target.name}.report.json").write_text(
            json.dumps(report.payload(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        log(f"Wrote {target} ({format_size(plan.image_bytes)})")
        return report
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            if work is not None:
                if failure is not None or options.keep_work:
                    log(f"Work directory kept at {work}")
                else:
                    shutil.rmtree(work, ignore_errors=True)
        finally:
            active.close()
