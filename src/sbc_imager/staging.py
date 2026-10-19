"""Copy a build plan into a verified staging tree with a stage-plan manifest."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sbc_imager.cannoli import CANNOLI_VERSION
from sbc_imager.errors import ConfigError
from sbc_imager.planner import BuildPlan

_CHUNK = 8 * 1024 * 1024
_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class StagedEntry:
    dest: PurePosixPath
    src: Path
    kind: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class StageTotals:
    entries: int
    content_bytes: int


@dataclass(frozen=True, slots=True)
class StageResult:
    stage_dir: Path
    stage_plan_path: Path
    entries: tuple[StagedEntry, ...]
    totals: StageTotals


def _copy_hashed(source: Path, target: Path) -> str:
    digest = hashlib.sha256()
    status = source.stat()
    with source.open("rb") as reader, target.open("wb") as writer:
        while chunk := reader.read(_CHUNK):
            digest.update(chunk)
            writer.write(chunk)
    os.utime(target, ns=(status.st_atime_ns, status.st_mtime_ns))
    return digest.hexdigest()


def _collision_key(dest: PurePosixPath) -> tuple[str, ...]:
    return tuple(unicodedata.normalize("NFC", part).casefold() for part in dest.parts)


def _stage_plan(plan: BuildPlan, entries: tuple[StagedEntry, ...]) -> dict[str, object]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "cannoli_version": CANNOLI_VERSION,
        "image_bytes": plan.image_bytes,
        "partition_bytes": plan.partition_bytes,
        "partition_offset_bytes": plan.partition_offset_bytes,
        "label": plan.label,
        "required_dirs": [path.as_posix() for path in plan.required_dirs],
        "settings_marker": {
            "path": plan.settings_marker.path.as_posix(),
            "content": plan.settings_marker.content,
        },
        "credits_marker": {
            "path": plan.credits_marker.path.as_posix(),
            "content": plan.credits_marker.content,
        },
        "entries": [
            {
                "dest": entry.dest.as_posix(),
                "src": str(entry.src),
                "kind": entry.kind,
                "size": entry.size,
                "sha256": entry.sha256,
            }
            for entry in entries
        ],
        "totals": {
            "entries": len(entries),
            "content_bytes": sum(entry.size for entry in entries),
        },
    }


def stage(plan: BuildPlan, work_dir: Path) -> StageResult:
    """Copy every planned file into ``work_dir/stage`` and write ``stage-plan.json``."""
    work = Path(work_dir)
    stage_dir = work / "stage"
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)

    exact: dict[str, str] = {}
    normalized: dict[tuple[str, ...], str] = {}
    staged: list[StagedEntry] = []
    for entry in plan.entries:
        raw = entry.dest.as_posix()
        key = _collision_key(entry.dest)
        if raw in exact:
            raise ConfigError(f"duplicate-destination: {raw!r} is staged twice")
        if key in normalized:
            raise ConfigError(
                f"destination-collision: {raw!r} collides with {normalized[key]!r} "
                "after NFC and case folding"
            )
        target = stage_dir.joinpath(*entry.dest.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = _copy_hashed(entry.src, target)
        if target.stat().st_size != entry.size:
            raise ConfigError(f"stage-size-mismatch: {raw!r} changed while staging")
        exact[raw] = raw
        normalized[key] = raw
        staged.append(StagedEntry(entry.dest, entry.src, entry.kind, entry.size, digest))

    entries = tuple(staged)
    totals = StageTotals(entries=len(entries), content_bytes=sum(e.size for e in entries))
    stage_plan_path = work / "stage-plan.json"
    payload = _stage_plan(plan, entries)
    stage_plan_path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return StageResult(
        stage_dir=stage_dir.resolve(),
        stage_plan_path=stage_plan_path.resolve(),
        entries=entries,
        totals=totals,
    )
