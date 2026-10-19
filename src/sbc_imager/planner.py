"""Resolve manifest destinations, size the image, and describe the card plan."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from sbc_imager.cannoli import (
    CANNOLI_COMMIT,
    CANNOLI_VERSION,
    credits_path,
    required_dirs,
    settings_path,
)
from sbc_imager.config import Manifest
from sbc_imager.errors import ConfigError
from sbc_imager.runner import redact_url
from sbc_imager.sizes import parse_size
from sbc_imager.sources import ResolvedSource
from sbc_imager.validation import Destination, Warning, iter_destinations, validate_manifest
from sbc_imager.validation_destinations import source_relative_path
from sbc_imager.validation_local import entry_files

MIB = 1024 * 1024
_REMOTE_TYPES = frozenset({"git", "http", "https", "url"})
_SETTINGS = "{}\n"


@dataclass(frozen=True, slots=True)
class PlannedEntry:
    dest: PurePosixPath
    src: Path
    kind: str
    size: int
    entry_index: int
    source_id: str | None


@dataclass(frozen=True, slots=True)
class Marker:
    path: PurePosixPath
    content: str


@dataclass(frozen=True, slots=True)
class BuildPlan:
    entries: tuple[PlannedEntry, ...]
    content_bytes: int
    overhead_bytes: int
    reserve_bytes: int
    partition_offset_bytes: int
    partition_bytes: int
    image_bytes: int
    label: str
    required_dirs: tuple[PurePosixPath, ...]
    settings_marker: Marker
    credits_marker: Marker
    warnings: tuple[Warning, ...]
    sources: tuple[ResolvedSource, ...]


def _align_up(value: int, unit: int) -> int:
    return (value + unit - 1) // unit * unit


def _planned(
    dest: PurePosixPath, src: Path, kind: str, index: int, source_id: str | None
) -> PlannedEntry:
    size = src.stat().st_size
    return PlannedEntry(dest, src, kind, size, index, source_id)


def _source_path(root: Path, entry_path: Path, source_id: str) -> Path:
    if root.is_file():
        return root
    relative = source_relative_path(entry_path, f"source '{source_id}'")
    candidate = Path(root, *relative.parts).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ConfigError(f"source-path: source '{source_id}' path escapes its root")
    if not candidate.exists():
        raise ConfigError(
            f"missing-source-path: source '{source_id}' has no path {relative.as_posix()!r}"
        )
    return candidate


def _source_entries(
    destination: Destination, root: Path, source_id: str, entry_path: Path
) -> list[PlannedEntry]:
    candidate = _source_path(root, entry_path, source_id)
    if candidate.is_file():
        return [
            _planned(
                destination.dest,
                candidate,
                destination.kind,
                destination.entry_index,
                source_id,
            )
        ]
    result: list[PlannedEntry] = []
    for path, relative in entry_files(candidate):
        if destination.kind == "overlay" and relative.suffix.casefold() != ".png":
            continue
        result.append(
            _planned(
                destination.dest / relative,
                path,
                destination.kind,
                destination.entry_index,
                source_id,
            )
        )
    if not result:
        where = f"{destination.kind}[{destination.entry_index}]"
        raise ConfigError(f"empty-entry: {where} produces no files")
    return result


def _expand(
    destination: Destination,
    manifest: Manifest,
    resolved_sources: Mapping[str, ResolvedSource],
) -> list[PlannedEntry]:
    if destination.src is not None:
        return [
            _planned(
                destination.dest,
                destination.src,
                destination.kind,
                destination.entry_index,
                None,
            )
        ]
    entries = manifest.overlays if destination.kind == "overlay" else manifest.shaders
    entry = entries[destination.entry_index]
    source_id = entry.source
    if not isinstance(source_id, str):
        raise ConfigError(f"unmapped-destination: {destination.dest.as_posix()!r}")
    resolved = resolved_sources.get(source_id)
    if resolved is None:
        raise ConfigError(
            f"missing-source-resolution: {destination.kind}[{destination.entry_index}] "
            f"references source '{source_id}'"
        )
    return _source_entries(destination, resolved.root, source_id, entry.path)


def _ordered_sources(
    manifest: Manifest, resolved_sources: Mapping[str, ResolvedSource]
) -> tuple[ResolvedSource, ...]:
    ordered = [
        resolved_sources[source.id] for source in manifest.sources if source.id in resolved_sources
    ]
    known = {source.id for source in manifest.sources}
    ordered.extend(resolved_sources[key] for key in sorted(resolved_sources) if key not in known)
    return tuple(ordered)


def source_rows(sources: tuple[ResolvedSource, ...]) -> list[dict[str, str]]:
    return [{"id": source.id, "type": source.kind, "root": str(source.root)} for source in sources]


def plan_payload(plan: BuildPlan) -> dict[str, object]:
    sizes = {
        name: getattr(plan, name)
        for name in (
            "content_bytes",
            "overhead_bytes",
            "reserve_bytes",
            "partition_offset_bytes",
            "partition_bytes",
            "image_bytes",
        )
    }
    entries = [
        {
            "dest": entry.dest.as_posix(),
            "kind": entry.kind,
            "size": entry.size,
            "source": entry.source_id,
        }
        for entry in plan.entries
    ]
    warnings = [
        {"code": warning.code, "message": warning.message, "entry_index": warning.entry_index}
        for warning in plan.warnings
    ]
    return {
        "sizes": sizes,
        "entries": entries,
        "warnings": warnings,
        "sources": source_rows(plan.sources),
    }


def _sizes(
    manifest: Manifest, content_bytes: int, *, size: str | None, reserve: str | None
) -> tuple[int, int, int, int]:
    overhead = max(64 * MIB, (content_bytes + 99) // 100)
    reserve_bytes = parse_size(manifest.image.reserve if reserve is None else reserve)
    pinned = size if size is not None else manifest.image.size
    if pinned.strip().casefold() == "auto":
        partition_bytes = _align_up(content_bytes + overhead + reserve_bytes, MIB)
        image_bytes = MIB + partition_bytes
    else:
        image_bytes = parse_size(pinned)
        if (image_bytes - MIB) % MIB != 0:
            raise ConfigError(
                f"pinned-size: image size {pinned!r} must leave a 1 MiB aligned partition"
            )
        required = MIB + content_bytes + overhead
        if image_bytes < required:
            raise ConfigError(
                f"content-overflow: pinned image {image_bytes} bytes cannot hold "
                f"{content_bytes} bytes of content plus {overhead} bytes overhead "
                f"and a {MIB} byte offset"
            )
        partition_bytes = image_bytes - MIB
    return overhead, reserve_bytes, partition_bytes, image_bytes


def _credits(manifest: Manifest) -> str:
    remote = [source for source in manifest.sources if source.type.casefold() in _REMOTE_TYPES]
    blocks = "\n".join(
        f"### {source.id}\n\n- URL: {redact_url(source.url)}\n"
        f"- Ref: {source.ref or 'n/a'}\n- License: {source.license or 'n/a'}\n"
        f"- Attribution: {source.attribution or 'n/a'}\n"
        for source in remote
    )
    return (
        "# Credits\n\nGenerated by sbc-imager.\n\n## Cannoli\n\n"
        f"- Cannoli v{CANNOLI_VERSION} (commit {CANNOLI_COMMIT})\n"
        "- License: GPL-3.0\n- https://github.com/CannoliHQ/cannoli\n\n"
        "## Third-party sources\n\n" + (blocks or "No remote sources were declared.\n")
    )


def build_plan(
    manifest: Manifest,
    resolved_sources: Mapping[str, ResolvedSource],
    *,
    size: str | None = None,
    reserve: str | None = None,
) -> BuildPlan:
    """Map every entry to a card path and compute the image size contract."""
    effective = manifest
    if size is not None:
        effective = replace(manifest, image=replace(manifest.image, size=size))
    warnings = validate_manifest(effective)
    entries = [
        planned
        for destination in iter_destinations(manifest)
        for planned in _expand(destination, manifest, resolved_sources)
    ]
    if not entries:
        raise ConfigError("empty-plan: the manifest produces no files to stage")
    content_bytes = sum(entry.size for entry in entries)
    overhead, reserve_bytes, partition_bytes, image_bytes = _sizes(
        manifest, content_bytes, size=size, reserve=reserve
    )
    return BuildPlan(
        entries=tuple(entries),
        content_bytes=content_bytes,
        overhead_bytes=overhead,
        reserve_bytes=reserve_bytes,
        partition_offset_bytes=MIB,
        partition_bytes=partition_bytes,
        image_bytes=image_bytes,
        label=manifest.image.label,
        required_dirs=required_dirs(),
        settings_marker=Marker(settings_path(), _SETTINGS),
        credits_marker=Marker(credits_path(), _credits(manifest)),
        warnings=tuple(warnings),
        sources=_ordered_sources(manifest, resolved_sources),
    )
