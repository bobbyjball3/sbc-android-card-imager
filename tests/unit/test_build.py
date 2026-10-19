from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

from sbc_imager import build as build_module
from sbc_imager.build import BuildOptions, Services, build_image
from sbc_imager.config import Manifest, load_manifest
from sbc_imager.errors import AssemblerError, SafetyError, VerificationError
from sbc_imager.planner import BuildPlan, Marker
from sbc_imager.progress import ProgressEvent, encode_progress_line
from sbc_imager.sources import ResolvedSource
from sbc_imager.staging import StageResult, StageTotals
from sbc_imager.validation import Warning
from sbc_imager.verify import VerifyReport

MIB = 1024 * 1024


@dataclass(frozen=True, slots=True)
class Recorded:
    name: str
    args: tuple[object, ...]
    kwargs: dict[str, object]


class RecordingReporter:
    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []
        self.closed = False

    def emit(self, event: ProgressEvent) -> None:
        self.events.append(event)

    def close(self) -> None:
        self.closed = True


def _plan(*, content_bytes: int = 10, warnings: tuple[Warning, ...] = ()) -> BuildPlan:
    return BuildPlan(
        entries=(),
        content_bytes=content_bytes,
        overhead_bytes=64 * MIB,
        reserve_bytes=0,
        partition_offset_bytes=MIB,
        partition_bytes=64 * MIB,
        image_bytes=65 * MIB,
        label="CANNOLI",
        required_dirs=(),
        settings_marker=Marker(PurePosixPath("Cannoli/Config/settings.json"), "{}\n"),
        credits_marker=Marker(PurePosixPath("CREDITS.md"), "# Credits\n"),
        warnings=warnings,
        sources=(),
    )


def _manifest(tmp_path: Path, *, output: str = "dist/card.img") -> Manifest:
    path = tmp_path / "imager.toml"
    path.write_text(
        f'[image]\nname = "demo"\nsize = "32MiB"\nreserve = "1MiB"\noutput = "{output}"\n',
        encoding="utf-8",
    )
    return load_manifest(path)


class FakeServices:
    def __init__(
        self,
        manifest: Manifest,
        plan: BuildPlan,
        *,
        verify_result: VerifyReport | None = None,
        verify_error: Exception | None = None,
        assemble_code: int = 0,
        image: bytes = b"IMAGE",
        frees: tuple[int, ...] = (10**12, 10**12),
        output_path: Path | None = None,
    ) -> None:
        self.manifest = manifest
        self.plan_value = plan
        self.verify_result = verify_result or VerifyReport(expected_files=1, actual_files=1)
        self.verify_error = verify_error
        self.assemble_code = assemble_code
        self.image = image
        self.frees = frees
        self.output_path = output_path
        self.output_at_verify: bytes | None = None
        self.calls: list[Recorded] = []
        self.work_dir: Path | None = None
        self.work_existed_at_stage = False
        self.staged: StageResult | None = None

    def _record(self, name: str, *args: object, **kwargs: object) -> None:
        self.calls.append(Recorded(name, args, kwargs))

    def load(self, path: Path) -> Manifest:
        self._record("load", path)
        return self.manifest

    def validate(self, manifest: Manifest) -> Sequence[Warning]:
        self._record("validate", manifest)
        return ()

    def resolve(
        self, manifest: Manifest, *, offline: bool, allow_branch: bool
    ) -> Mapping[str, ResolvedSource]:
        self._record("resolve", manifest, offline=offline, allow_branch=allow_branch)
        return {}

    def plan(
        self,
        manifest: Manifest,
        sources: Mapping[str, ResolvedSource],
        *,
        size: str | None,
        reserve: str | None,
    ) -> BuildPlan:
        self._record("plan", manifest, sources, size=size, reserve=reserve)
        return self.plan_value

    def disk_usage(self, path: Path) -> tuple[int, int, int]:
        index = sum(1 for call in self.calls if call.name == "disk_usage")
        free = self.frees[min(index, len(self.frees) - 1)]
        self._record("disk_usage", path)
        return (free, 0, free)

    def stage(self, plan: BuildPlan, work_dir: Path) -> StageResult:
        self._record("stage", plan, work_dir)
        self.work_dir = work_dir
        self.work_existed_at_stage = work_dir.is_dir()
        stage_dir = work_dir / "stage"
        stage_dir.mkdir(parents=True, exist_ok=True)
        self.staged = StageResult(
            stage_dir=stage_dir,
            stage_plan_path=work_dir / "stage-plan.json",
            entries=(),
            totals=StageTotals(entries=0, content_bytes=plan.content_bytes),
        )
        return self.staged

    def ensure_container(self) -> None:
        self._record("ensure_container")

    def preflight(self, on_line: build_module.Log) -> None:
        self._record("preflight", on_line)
        on_line("preflight ok")

    def assemble(
        self,
        plan: BuildPlan,
        staged: StageResult,
        out_dir: Path,
        name: str,
        on_line: build_module.Log,
    ) -> int:
        self._record("assemble", plan, staged, out_dir, name, on_line)
        if self.assemble_code == 0:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{name}.img").write_bytes(self.image)
        return self.assemble_code

    def verify(
        self,
        manifest_path: Path,
        image: Path,
        *,
        offline: bool,
        allow_branch: bool,
        on_line: build_module.Log,
    ) -> VerifyReport:
        self._record(
            "verify",
            manifest_path,
            image,
            offline=offline,
            allow_branch=allow_branch,
            on_line=on_line,
        )
        if self.output_path is not None and self.output_path.exists():
            self.output_at_verify = self.output_path.read_bytes()
        if self.verify_error is not None:
            raise self.verify_error
        return self.verify_result

    def close(self) -> None:
        self._record("close")


def _wire(fake: FakeServices) -> Services:
    return Services(
        load=fake.load,
        validate=fake.validate,
        resolve=fake.resolve,
        plan=fake.plan,
        stage=fake.stage,
        disk_usage=fake.disk_usage,
        ensure_container=fake.ensure_container,
        preflight=fake.preflight,
        assemble=fake.assemble,
        verify=fake.verify,
        close=fake.close,
    )


@pytest.fixture(autouse=True)
def work_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "work"

    def fake_mkdtemp(*args: object, **kwargs: object) -> str:
        del args, kwargs
        root.mkdir(parents=True, exist_ok=True)
        return str(root)

    monkeypatch.setattr(build_module.tempfile, "mkdtemp", fake_mkdtemp)
    yield root


def _options(
    manifest: Manifest,
    tmp_path: Path,
    *,
    output: Path | None = None,
    size: str | None = None,
    reserve: str | None = None,
    offline: bool = False,
    force: bool = False,
    keep_work: bool = False,
    allow_branch: bool = False,
) -> BuildOptions:
    del manifest
    return BuildOptions(
        manifest_path=tmp_path / "imager.toml",
        output=output,
        size=size,
        reserve=reserve,
        offline=offline,
        force=force,
        keep_work=keep_work,
        allow_branch=allow_branch,
    )


def _call(services: FakeServices, name: str) -> Recorded:
    return next(call for call in services.calls if call.name == name)


def test_build_when_pipeline_succeeds_runs_in_order_and_publishes(
    tmp_path: Path, work_root: Path
) -> None:
    manifest = _manifest(tmp_path)
    plan = _plan()
    services = FakeServices(manifest, plan, output_path=manifest.image.output)
    lines: list[str] = []

    report = build_image(_options(manifest, tmp_path), _wire(services), log=lines.append)

    assert [call.name for call in services.calls] == [
        "load",
        "validate",
        "resolve",
        "plan",
        "disk_usage",
        "disk_usage",
        "stage",
        "ensure_container",
        "preflight",
        "assemble",
        "verify",
        "close",
    ]
    assert _call(services, "load").args == (tmp_path / "imager.toml",)
    assert _call(services, "validate").args == (manifest,)
    assert _call(services, "resolve").kwargs == {"offline": False, "allow_branch": False}
    assert _call(services, "plan").args == (manifest, {})
    assert _call(services, "plan").kwargs == {"size": None, "reserve": None}
    assert _call(services, "disk_usage").args == (work_root,)
    assert _call(services, "preflight").args == (lines.append,)
    staged = services.staged
    assert staged is not None
    stream_line = _call(services, "assemble").args[4]
    assert callable(stream_line)
    assert _call(services, "assemble").args == (
        plan,
        staged,
        work_root / "out",
        "card",
        stream_line,
    )
    stream_line("visible line")
    stream_line(encode_progress_line(ProgressEvent("copy", "hidden progress", 1, 2)))
    assert "visible line" in lines
    assert "hidden progress" not in lines
    verify_call = _call(services, "verify")
    assert verify_call.args == (tmp_path / "imager.toml", work_root / "out" / "card.img")
    assert verify_call.kwargs == {
        "offline": True,
        "allow_branch": False,
        "on_line": stream_line,
    }
    assert services.work_existed_at_stage is True
    assert report.image == str(manifest.image.output)
    assert report.sha256 == hashlib.sha256(b"IMAGE").hexdigest()
    assert manifest.image.output.read_bytes() == b"IMAGE"
    assert not manifest.image.output.with_name("card.img.partial").exists()
    assert work_root.exists() is False
    assert any("Wrote" in line for line in lines)

    payload = json.loads(
        manifest.image.output.with_name("card.img.report.json").read_text(encoding="utf-8")
    )
    assert payload["schema_version"] == 1
    assert payload["manifest"] == str(tmp_path / "imager.toml")
    assert payload["image"] == str(manifest.image.output)
    assert payload["image_bytes"] == plan.image_bytes
    assert payload["partition_bytes"] == plan.partition_bytes
    assert payload["offset"] == plan.partition_offset_bytes
    assert payload["content_files"] == 0
    assert payload["content_bytes"] == plan.content_bytes
    assert payload["sha256"] == report.sha256
    assert payload["verify"] == report.verify.payload()
    assert payload["sources"] == []
    assert payload["warnings"] == []


def test_build_when_output_option_given_overrides_manifest(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    services = FakeServices(manifest, _plan())
    target = tmp_path / "cli.img"

    report = build_image(
        _options(manifest, tmp_path, output=target), _wire(services), log=lambda line: None
    )

    assert report.image == str(target.resolve())
    assert target.read_bytes() == b"IMAGE"
    assert not (tmp_path / "dist" / "card.img").exists()


def test_build_when_output_option_absent_uses_manifest_output(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    services = FakeServices(manifest, _plan())

    report = build_image(_options(manifest, tmp_path), _wire(services), log=lambda line: None)

    assert report.image == str(manifest.image.output)


@pytest.mark.parametrize(("size", "reserve"), [(None, None), ("64MiB", "2MiB")])
def test_build_when_cli_size_and_reserve_given_are_forwarded(
    tmp_path: Path, size: str | None, reserve: str | None
) -> None:
    manifest = _manifest(tmp_path)
    services = FakeServices(manifest, _plan())

    build_image(
        _options(manifest, tmp_path, size=size, reserve=reserve),
        _wire(services),
        log=lambda line: None,
    )

    assert _call(services, "plan").kwargs == {"size": size, "reserve": reserve}


@pytest.mark.parametrize(("offline", "allow_branch"), [(True, True), (False, False)])
def test_build_when_offline_and_allow_branch_given_propagate(
    tmp_path: Path, offline: bool, allow_branch: bool
) -> None:
    manifest = _manifest(tmp_path)
    services = FakeServices(manifest, _plan())

    build_image(
        _options(manifest, tmp_path, offline=offline, allow_branch=allow_branch),
        _wire(services),
        log=lambda line: None,
    )

    assert _call(services, "resolve").kwargs == {
        "offline": offline,
        "allow_branch": allow_branch,
    }


def test_build_when_output_exists_without_force_refuses_and_keeps_it(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)
    target = tmp_path / "card.img"
    target.write_bytes(b"OLD")
    services = FakeServices(manifest, _plan())

    with pytest.raises(SafetyError) as caught:
        build_image(
            _options(manifest, tmp_path, output=target),
            _wire(services),
            log=lambda line: None,
        )

    assert caught.value.exit_code == 2
    assert target.read_bytes() == b"OLD"
    assert not target.with_name("card.img.partial").exists()
    assert [call.name for call in services.calls] == ["load", "validate", "close"]


def test_build_when_force_replaces_only_after_verification(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    target = tmp_path / "card.img"
    target.write_bytes(b"OLD")
    plan = _plan()
    services = FakeServices(manifest, plan, image=b"NEW", output_path=target)

    build_image(
        _options(manifest, tmp_path, output=target, force=True),
        _wire(services),
        log=lambda line: None,
    )

    assert services.output_at_verify == b"OLD"
    assert target.read_bytes() == b"NEW"
    assert not target.with_name("card.img.partial").exists()


def test_build_when_verification_fails_keeps_old_output_and_no_partial(
    tmp_path: Path, work_root: Path
) -> None:
    manifest = _manifest(tmp_path)
    target = tmp_path / "card.img"
    target.write_bytes(b"OLD")
    failed = VerifyReport(expected_files=2, actual_files=1, missing=("CREDITS.md",))
    services = FakeServices(manifest, _plan(), verify_result=failed, output_path=target)
    lines: list[str] = []

    with pytest.raises(VerificationError, match=r"CREDITS\.md"):
        build_image(
            _options(manifest, tmp_path, output=target, force=True),
            _wire(services),
            log=lines.append,
        )

    assert target.read_bytes() == b"OLD"
    assert not target.with_name("card.img.partial").exists()
    assert work_root.exists()
    assert f"Work directory kept at {work_root}" in lines


@pytest.mark.parametrize("failing", [0, 1])
def test_build_when_free_space_is_insufficient_fails_before_staging(
    tmp_path: Path, work_root: Path, failing: int
) -> None:
    manifest = _manifest(tmp_path)
    plan = _plan(content_bytes=10)
    required = plan.content_bytes + plan.overhead_bytes + MIB
    frees = (required - 1, 10**12) if failing == 0 else (10**12, required - 1)
    services = FakeServices(manifest, plan, frees=frees)
    lines: list[str] = []

    with pytest.raises(AssemblerError, match="insufficient free space"):
        build_image(_options(manifest, tmp_path), _wire(services), log=lines.append)

    names = [call.name for call in services.calls]
    assert "stage" not in names
    assert "assemble" not in names
    assert work_root.exists()
    assert f"Work directory kept at {work_root}" in lines


def test_build_when_keep_work_is_set_keeps_the_work_directory(
    tmp_path: Path, work_root: Path
) -> None:
    manifest = _manifest(tmp_path)
    services = FakeServices(manifest, _plan())
    lines: list[str] = []

    build_image(_options(manifest, tmp_path, keep_work=True), _wire(services), log=lines.append)

    assert work_root.exists()
    assert f"Work directory kept at {work_root}" in lines


def test_build_when_success_without_keep_work_removes_the_work_directory(
    tmp_path: Path, work_root: Path
) -> None:
    manifest = _manifest(tmp_path)
    services = FakeServices(manifest, _plan())

    build_image(_options(manifest, tmp_path), _wire(services), log=lambda line: None)

    assert work_root.exists() is False


def test_build_when_assembler_fails_keeps_work_and_leaves_no_partial(
    tmp_path: Path, work_root: Path
) -> None:
    manifest = _manifest(tmp_path)
    target = tmp_path / "card.img"
    services = FakeServices(manifest, _plan(), assemble_code=7, output_path=target)
    lines: list[str] = []

    with pytest.raises(AssemblerError, match="exit code 7"):
        build_image(_options(manifest, tmp_path, output=target), _wire(services), log=lines.append)

    assert not target.exists()
    assert not target.with_name("card.img.partial").exists()
    assert work_root.exists()
    assert f"Work directory kept at {work_root}" in lines


def test_build_report_when_warnings_and_sources_exist_serializes_them(
    tmp_path: Path,
) -> None:
    warning = Warning("unused-source", "source 'x' is unused", 0)
    manifest = _manifest(tmp_path)
    plan = _plan(warnings=(warning,))
    services = FakeServices(manifest, plan)

    report = build_image(_options(manifest, tmp_path), _wire(services), log=lambda line: None)

    payload = report.payload()
    assert payload["warnings"] == [
        {"code": "unused-source", "message": "source 'x' is unused", "entry_index": 0}
    ]
    assert payload["sources"] == []


def test_build_when_default_services_are_used_builds_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path)
    services = FakeServices(manifest, _plan())
    monkeypatch.setattr(build_module, "default_services", lambda: _wire(services))

    build_image(_options(manifest, tmp_path), log=lambda line: None)

    assert services.calls[0].name == "load"
    assert services.calls[-1].name == "close"


def test_build_when_progress_reporter_provided_emits_phases(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    plan = _plan()
    services = FakeServices(manifest, plan, output_path=manifest.image.output)
    reporter = RecordingReporter()

    build_image(
        _options(manifest, tmp_path),
        _wire(services),
        log=lambda _line: None,
        progress=reporter,
    )

    phases = {event.phase for event in reporter.events}
    assert {
        "load",
        "resolve",
        "stage",
        "container",
        "assemble",
        "verify-image",
        "publish-output",
    } <= phases
    assert reporter.closed is True
