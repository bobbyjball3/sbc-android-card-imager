from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath

import pytest

from sbc_imager.config import Manifest, load_manifest
from sbc_imager.errors import ConfigError
from sbc_imager.planner import (
    BuildPlan,
    Marker,
    PlannedEntry,
    build_plan,
)
from sbc_imager.staging import StageResult, stage

MIB = 1024 * 1024


def _touch(path: Path, data: bytes = b"x", mtime: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mtime is not None:
        os.utime(path, ns=(mtime, mtime))
    return path


def _manifest(tmp_path: Path, body: str, files: dict[str, bytes]) -> Manifest:
    for name, data in files.items():
        _touch(tmp_path / name, data)
    path = tmp_path / "imager.toml"
    path.write_text(body, encoding="utf-8")
    return load_manifest(path)


def _plan(tmp_path: Path) -> BuildPlan:
    manifest = _manifest(
        tmp_path,
        '[[artifact]]\nroot = "cannoli"\ndest = "Roms/GBA"\npath = "roms"\n\n'
        '[[artifact]]\nroot = "card"\ndest = "Guides"\npath = "guides"\n',
        {
            "roms/demo.gba": b"ROMDATA",
            "roms/sub/deep.gba": b"DEEP",
            "guides/setup.md": b"# setup\n",
        },
    )
    return build_plan(manifest, {})


def _manual_plan(entries: tuple[PlannedEntry, ...]) -> BuildPlan:
    return BuildPlan(
        entries=entries,
        content_bytes=sum(entry.size for entry in entries),
        overhead_bytes=64 * MIB,
        reserve_bytes=0,
        partition_offset_bytes=MIB,
        partition_bytes=64 * MIB,
        image_bytes=65 * MIB,
        label="CANNOLI",
        required_dirs=(PurePosixPath("Cannoli"),),
        settings_marker=Marker(PurePosixPath("Cannoli/Config/settings.json"), "{}\n"),
        credits_marker=Marker(PurePosixPath("CREDITS.md"), "# Credits\n"),
        warnings=(),
        sources=(),
    )


def test_stage_when_file_is_copied_preserves_bytes_mtime_and_hash(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    mtime = 1_700_000_000_123_456_789
    source = plan.entries[0].src
    os.utime(source, ns=(mtime, mtime))
    plan = build_plan(load_manifest(tmp_path / "imager.toml"), {})

    result = stage(plan, tmp_path / "work")

    target = result.stage_dir / plan.entries[0].dest
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_mtime_ns == mtime
    assert result.entries[0].sha256 == hashlib.sha256(source.read_bytes()).hexdigest()


def test_stage_when_nested_destination_creates_parent_directories(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    result = stage(plan, tmp_path / "work")

    assert (result.stage_dir / "Cannoli/Roms/GBA/sub/deep.gba").is_file()
    assert (result.stage_dir / "Guides/setup.md").is_file()


def test_stage_when_duplicate_destinations_are_detected_again(tmp_path: Path) -> None:
    source = _touch(tmp_path / "a.bin", b"a")
    dest = PurePosixPath("Cannoli/Roms/GBA/demo.gba")
    entry = PlannedEntry(dest, source, "artifact", 1, 0, None)
    plan = _manual_plan((entry, entry))

    with pytest.raises(ConfigError, match="duplicate-destination"):
        stage(plan, tmp_path / "work")


def test_stage_when_case_collisions_are_detected_again(tmp_path: Path) -> None:
    source = _touch(tmp_path / "a.bin", b"a")
    first = PlannedEntry(PurePosixPath("Cannoli/Roms/GBA/Demo.gba"), source, "artifact", 1, 0, None)
    second = PlannedEntry(
        PurePosixPath("Cannoli/Roms/GBA/demo.gba"), source, "artifact", 1, 1, None
    )
    plan = _manual_plan((first, second))

    with pytest.raises(ConfigError, match="destination-collision"):
        stage(plan, tmp_path / "work")


def test_stage_when_markers_are_present_does_not_copy_them(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    result = stage(plan, tmp_path / "work")

    assert not (result.stage_dir / "Cannoli/Config/settings.json").exists()
    assert not (result.stage_dir / "CREDITS.md").exists()
    payload = json.loads(result.stage_plan_path.read_text(encoding="utf-8"))
    assert payload["settings_marker"] == {
        "path": "Cannoli/Config/settings.json",
        "content": "{}\n",
    }
    assert payload["credits_marker"] == {
        "path": "CREDITS.md",
        "content": plan.credits_marker.content,
    }


def test_stage_when_work_dir_is_written_uses_stage_plan_schema(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    result = stage(plan, tmp_path / "work")

    payload = json.loads(result.stage_plan_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["cannoli_version"] == "1.9.1"
    assert payload["image_bytes"] == plan.image_bytes
    assert payload["partition_bytes"] == plan.partition_bytes
    assert payload["partition_offset_bytes"] == plan.partition_offset_bytes
    assert payload["label"] == plan.label
    assert all(isinstance(path, str) for path in payload["required_dirs"])
    assert payload["totals"] == {
        "entries": len(plan.entries),
        "content_bytes": plan.content_bytes,
    }
    for entry, planned in zip(payload["entries"], plan.entries, strict=True):
        assert entry["dest"] == planned.dest.as_posix()
        assert entry["src"] == str(planned.src)
        assert entry["kind"] == planned.kind
        assert entry["size"] == planned.size
        assert len(entry["sha256"]) == 64
        assert entry["sha256"] == hashlib.sha256(planned.src.read_bytes()).hexdigest()


def test_stage_when_complete_returns_result_with_totals(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    result = stage(plan, tmp_path / "work")

    assert isinstance(result, StageResult)
    assert result.stage_dir == (tmp_path / "work" / "stage").resolve()
    assert result.stage_plan_path == (tmp_path / "work" / "stage-plan.json").resolve()
    assert result.totals.entries == len(plan.entries)
    assert result.totals.content_bytes == sum(entry.size for entry in plan.entries)
    assert len(result.entries) == len(plan.entries)


def test_stage_when_called_twice_replaces_the_stage_tree(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    stage(plan, tmp_path / "work")
    _touch(tmp_path / "work" / "stage" / "stale.bin", b"stale")

    result = stage(plan, tmp_path / "work")

    assert not (result.stage_dir / "stale.bin").exists()
