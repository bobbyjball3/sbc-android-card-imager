"""Stage-plan parsing, tree scanning, and report serialization for the assembler."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sbc_imager.errors import AssemblerError, VerificationError
from sbc_imager.fs import sha256_file

SCHEMA_VERSION = 1
MIB = 1024 * 1024
_SHA_LENGTH = 64
_MAX_SECTORS = 0xFFFFFFFF


@dataclass(frozen=True, slots=True)
class Entry:
    """A staged file that must appear in the image."""

    dest: PurePosixPath
    src: Path
    kind: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Marker:
    """A generated file written by the assembler itself."""

    path: PurePosixPath
    content: str


@dataclass(frozen=True, slots=True)
class StagePlan:
    """The validated ``stage-plan.json`` contract."""

    schema_version: int
    label: str
    image_bytes: int
    partition_offset_bytes: int
    partition_bytes: int
    required_dirs: tuple[PurePosixPath, ...]
    settings_marker: Marker
    credits_marker: Marker
    entries: tuple[Entry, ...]
    totals_entries: int
    totals_content_bytes: int


@dataclass(frozen=True, slots=True)
class TreeEntry:
    """One verified file in the image tree."""

    dest: str
    size: int
    sha256: str

    def payload(self) -> dict[str, object]:
        return {"dest": self.dest, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class Report:
    """The outcome of a completed assembly."""

    schema_version: int
    image_bytes: int
    partition_bytes: int
    partition_offset_bytes: int
    content_files: int
    content_bytes: int
    tree_sha256: str
    fsck_ok: bool
    label: str
    tree: tuple[TreeEntry, ...]
    tree_path: Path
    report_path: Path


def _mapping(value: object, where: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise AssemblerError(f"stage-plan: {where} must be an object")
    return value


def _string(source: Mapping[str, object], key: str, where: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise AssemblerError(f"stage-plan: {where}.{key} must be a non-empty string")
    return value


def _integer(source: Mapping[str, object], key: str, where: str) -> int:
    value = source.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AssemblerError(f"stage-plan: {where}.{key} must be a non-negative integer")
    return value


def _relative(value: str, where: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise AssemblerError(f"stage-plan: {where} must be a relative path without '..'")
    return path


def _path(source: Mapping[str, object], key: str, where: str) -> PurePosixPath:
    return _relative(_string(source, key, where), f"{where}.{key}")


def _sha(source: Mapping[str, object], where: str) -> str:
    value = _string(source, "sha256", where)
    if len(value) != _SHA_LENGTH or any(ch not in "0123456789abcdefABCDEF" for ch in value):
        raise AssemblerError(f"stage-plan: {where}.sha256 must be a 64-character hex digest")
    return value.casefold()


def _marker(source: Mapping[str, object], key: str) -> Marker:
    value = _mapping(source.get(key), key)
    return Marker(_path(value, "path", key), _string(value, "content", key))


def _entry(value: object, index: int) -> Entry:
    where = f"entries[{index}]"
    source = _mapping(value, where)
    return Entry(
        dest=_path(source, "dest", where),
        src=Path(_string(source, "src", where)),
        kind=_string(source, "kind", where),
        size=_integer(source, "size", where),
        sha256=_sha(source, where),
    )


def validate_label(label: str) -> None:
    if not 1 <= len(label) <= 11:
        raise AssemblerError(f"stage-plan: label {label!r} must be 1-11 characters")


def _validate_sizes(raw: Mapping[str, object]) -> tuple[int, int, int]:
    image_bytes = _integer(raw, "image_bytes", "plan")
    offset = _integer(raw, "partition_offset_bytes", "plan")
    partition = _integer(raw, "partition_bytes", "plan")
    if offset != MIB:
        raise AssemblerError(f"stage-plan: partition_offset_bytes must be {MIB}, got {offset}")
    if partition == 0 or partition % 512:
        raise AssemblerError(
            f"stage-plan: partition_bytes must be a positive multiple of 512, got {partition}"
        )
    if partition // 512 > _MAX_SECTORS:
        raise AssemblerError("stage-plan: partition_bytes exceeds the MBR sector limit")
    if image_bytes != offset + partition:
        raise AssemblerError(
            "stage-plan: image_bytes must equal partition_offset_bytes + partition_bytes "
            f"({image_bytes} != {offset + partition})"
        )
    return image_bytes, offset, partition


def _validate_totals(raw: Mapping[str, object], entries: tuple[Entry, ...]) -> tuple[int, int]:
    totals = _mapping(raw.get("totals"), "totals")
    count = _integer(totals, "entries", "totals")
    content_bytes = _integer(totals, "content_bytes", "totals")
    expected_bytes = sum(entry.size for entry in entries)
    if count != len(entries):
        raise AssemblerError(
            f"stage-plan: totals.entries is {count}, but {len(entries)} entries were listed"
        )
    if content_bytes != expected_bytes:
        raise AssemblerError(
            "stage-plan: totals.content_bytes is "
            f"{content_bytes}, but the entries total {expected_bytes}"
        )
    return count, content_bytes


def load_plan(path: Path) -> StagePlan:
    """Load and validate a stage plan, rejecting inconsistent totals or sizes."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise AssemblerError(f"stage-plan: cannot read {path}: {exc}") from exc
    except ValueError as exc:
        raise AssemblerError(f"stage-plan: invalid JSON in {path}: {exc}") from exc

    source = _mapping(raw, "root")
    schema_version = _integer(source, "schema_version", "plan")
    if schema_version != SCHEMA_VERSION:
        raise AssemblerError(
            f"stage-plan: unsupported schema_version {schema_version}, expected {SCHEMA_VERSION}"
        )
    label = _string(source, "label", "plan")
    validate_label(label)
    image_bytes, offset, partition = _validate_sizes(source)

    dirs_raw = source.get("required_dirs")
    if not isinstance(dirs_raw, list):
        raise AssemblerError("stage-plan: required_dirs must be a list")
    required_dirs = tuple(
        _relative(value, f"required_dirs[{index}]")
        for index, value in enumerate(dirs_raw)
        if isinstance(value, str)
    )
    if len(required_dirs) != len(dirs_raw):
        raise AssemblerError("stage-plan: required_dirs entries must be strings")

    entries_raw = source.get("entries")
    if not isinstance(entries_raw, list):
        raise AssemblerError("stage-plan: entries must be a list")
    entries = tuple(_entry(value, index) for index, value in enumerate(entries_raw))
    count, content_bytes = _validate_totals(source, entries)

    return StagePlan(
        schema_version=schema_version,
        label=label,
        image_bytes=image_bytes,
        partition_offset_bytes=offset,
        partition_bytes=partition,
        required_dirs=required_dirs,
        settings_marker=_marker(source, "settings_marker"),
        credits_marker=_marker(source, "credits_marker"),
        entries=entries,
        totals_entries=count,
        totals_content_bytes=content_bytes,
    )


def expected_files(plan: StagePlan) -> dict[str, tuple[int, str]]:
    """Return the exact ``{dest: (size, sha256)}`` tree the image must contain."""
    expected: dict[str, tuple[int, str]] = {}
    for entry in plan.entries:
        dest = entry.dest.as_posix()
        if dest in expected:
            raise AssemblerError(f"stage-plan: duplicate destination {dest!r}")
        expected[dest] = (entry.size, entry.sha256)
    for marker in (plan.settings_marker, plan.credits_marker):
        dest = marker.path.as_posix()
        if dest in expected:
            raise AssemblerError(f"stage-plan: marker collides with destination {dest!r}")
        data = marker.content.encode("utf-8")
        expected[dest] = (len(data), hashlib.sha256(data).hexdigest())
    return expected


def scan_tree(root: Path) -> tuple[TreeEntry, ...]:
    """Hash every regular file below ``root``, sorted by destination."""
    base = Path(root)
    entries = [
        TreeEntry(
            dest=path.relative_to(base).as_posix(),
            size=path.stat().st_size,
            sha256=sha256_file(path),
        )
        for path in base.rglob("*")
        if path.is_file()
    ]
    return tuple(sorted(entries, key=lambda item: item.dest))


def verify_tree(expected: Mapping[str, tuple[int, str]], actual: tuple[TreeEntry, ...]) -> None:
    """Raise when the mounted tree differs from the expected tree."""
    found = {item.dest: (item.size, item.sha256) for item in actual}
    missing = sorted(set(expected) - set(found))
    extra = sorted(set(found) - set(expected))
    mismatched = sorted(
        dest for dest in set(expected) & set(found) if expected[dest] != found[dest]
    )
    problems: list[str] = []
    if missing:
        problems.append(f"missing files: {', '.join(missing)}")
    if extra:
        problems.append(f"unexpected files: {', '.join(extra)}")
    if mismatched:
        problems.append(f"hash mismatch: {', '.join(mismatched)}")
    if problems:
        raise VerificationError("image verification failed: " + "; ".join(problems))


def tree_bytes(tree: tuple[TreeEntry, ...]) -> bytes:
    payload = [item.payload() for item in tree]
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def tree_sha256(tree: tuple[TreeEntry, ...]) -> str:
    return hashlib.sha256(tree_bytes(tree)).hexdigest()


def report_bytes(report: Report) -> bytes:
    payload = {
        "schema_version": report.schema_version,
        "image_bytes": report.image_bytes,
        "partition_bytes": report.partition_bytes,
        "partition_offset_bytes": report.partition_offset_bytes,
        "content_files": report.content_files,
        "content_bytes": report.content_bytes,
        "tree_sha256": report.tree_sha256,
        "fsck_ok": report.fsck_ok,
        "label": report.label,
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
