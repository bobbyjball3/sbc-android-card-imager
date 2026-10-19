"""Safe enumeration, assessment, and presentation of macOS disks."""

from __future__ import annotations

import plistlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final
from xml.parsers.expat import ExpatError

from rich.console import Console
from rich.table import Table

from sbc_imager.errors import SafetyError
from sbc_imager.imaging_write import WriteResult as WriteResult
from sbc_imager.imaging_write import write_image as write_image
from sbc_imager.runner import Runner
from sbc_imager.sizes import format_size

_SD_PROTOCOLS: Final[frozenset[str]] = frozenset({"Secure Digital", "SD Card"})
_REMOVABLE_PROTOCOLS: Final[frozenset[str]] = frozenset({"USB"}) | _SD_PROTOCOLS
_DISK_DEVICE: Final = re.compile(r"(?:/dev/r?)?(disk\d+)")


@dataclass(frozen=True, slots=True)
class DiskInfo:
    """A whole physical disk reported by ``diskutil``."""

    identifier: str
    size: int
    label: str
    model: str
    protocol: str
    internal: bool
    removable: bool
    ejectable: bool
    whole: bool
    serial: str | None = None
    virtual_or_physical: str = "Physical"
    boot: bool = False

    @property
    def is_builtin_sd(self) -> bool:
        """Return whether this is an internal, removable SD-card reader."""
        return (
            self.whole
            and self.internal
            and self.virtual_or_physical == "Physical"
            and (self.removable or self.ejectable)
            and self.protocol in _SD_PROTOCOLS
        )


@dataclass(frozen=True, slots=True)
class DiskAssessment:
    """A whole disk plus whether it may be used and why."""

    disk: DiskInfo
    allowed: bool
    status: str
    reason: str


def normalize_disk_identifier(raw: str) -> str:
    """Normalize ``diskN``, ``/dev/diskN``, or ``/dev/rdiskN`` to ``diskN``."""
    value = raw.strip()
    match = _DISK_DEVICE.fullmatch(value)
    if match is None:
        raise SafetyError(
            f"invalid device {raw!r}; expected diskN, /dev/diskN, or /dev/rdiskN",
            hint="run `sbc-imager image --list` to see the available whole disks",
        )
    return match.group(1)


def enumerate_disks(runner: Runner, *, allow_builtin_sd: bool = False) -> list[DiskInfo]:
    """Return safe whole disks, including internal SD readers when opted in."""
    return [
        assessment.disk
        for assessment in assess_disks(runner, allow_builtin_sd=allow_builtin_sd)
        if assessment.allowed
    ]


def assess_disks(runner: Runner, *, allow_builtin_sd: bool = False) -> list[DiskAssessment]:
    """Return every whole disk with its safety status and reason."""
    listing = _load_plist(
        runner.run(["diskutil", "list", "-plist"]).stdout,
        "diskutil list",
    )
    identifiers = _whole_identifiers(listing)
    if not identifiers:
        return []

    root = _load_plist(
        runner.run(["diskutil", "info", "-plist", "/"]).stdout,
        "diskutil info /",
    )
    boot_identifier = _required_string(root, "ParentWholeDisk", "diskutil info /")

    assessments: list[DiskAssessment] = []
    for identifier in identifiers:
        where = f"diskutil info {identifier}"
        info = _load_plist(
            runner.run(["diskutil", "info", "-plist", f"/dev/{identifier}"]).stdout,
            where,
        )
        disk = _parse_disk(
            info,
            boot_identifier=boot_identifier,
            where=where,
        )
        assessments.append(_assess_disk(disk, allow_builtin_sd=allow_builtin_sd))
    return assessments


def render_table(console: Console, disks: Sequence[DiskInfo]) -> None:
    """Print the candidate disks as a Rich table, including serial when known."""
    include_serial = any(disk.serial is not None for disk in disks)
    table = Table("Identifier", "Label", "Size", "Model", "Protocol")
    if include_serial:
        table.add_column("Serial")
    for disk in disks:
        row = [
            disk.identifier,
            disk.label or "-",
            format_size(disk.size),
            disk.model or "-",
            disk.protocol or "-",
        ]
        if include_serial:
            row.append(disk.serial or "-")
        table.add_row(*row)
    console.print(table)


def render_assessment_table(console: Console, assessments: Sequence[DiskAssessment]) -> None:
    """Print every whole disk with its status and the reason for that status."""
    table = Table("Identifier", "Label", "Size", "Model", "Protocol", "Status", "Reason")
    for assessment in assessments:
        disk = assessment.disk
        table.add_row(
            disk.identifier,
            disk.label or "-",
            format_size(disk.size),
            disk.model or "-",
            disk.protocol or "-",
            assessment.status,
            assessment.reason,
        )
    console.print(table)


def _assess_disk(disk: DiskInfo, *, allow_builtin_sd: bool) -> DiskAssessment:
    if not disk.whole:
        return DiskAssessment(disk, False, "blocked", "not a whole disk")
    if disk.virtual_or_physical == "Virtual":
        return DiskAssessment(disk, False, "blocked", "virtual disk")
    if disk.boot:
        return DiskAssessment(disk, False, "blocked", "boot disk")
    if disk.internal:
        if disk.virtual_or_physical != "Physical":
            return DiskAssessment(disk, False, "blocked", "internal disk")
        if disk.is_builtin_sd:
            if allow_builtin_sd:
                return DiskAssessment(
                    disk, True, "allowed", "internal SD reader (--allow-builtin-sd)"
                )
            return DiskAssessment(
                disk,
                False,
                "blocked",
                "internal SD reader; re-run with --allow-builtin-sd",
            )
        return DiskAssessment(disk, False, "blocked", "internal disk")
    if disk.virtual_or_physical != "Physical":
        detail = disk.virtual_or_physical or "unknown"
        return DiskAssessment(disk, False, "blocked", f"non-physical disk ({detail})")
    if not (disk.removable or disk.ejectable or disk.protocol in _REMOVABLE_PROTOCOLS):
        return DiskAssessment(disk, False, "blocked", "not removable")
    return DiskAssessment(disk, True, "allowed", "external removable disk")


def _whole_identifiers(listing: Mapping[str, object]) -> list[str]:
    entries = listing.get("AllDisksAndPartitions")
    if not isinstance(entries, list):
        raise SafetyError("diskutil list: missing required key 'AllDisksAndPartitions'")
    identifiers: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        where = f"diskutil list: AllDisksAndPartitions[{index}]"
        mapping = _as_mapping(entry, where)
        identifier = _required_string(mapping, "DeviceIdentifier", where)
        if identifier not in seen:
            seen.add(identifier)
            identifiers.append(identifier)
    return identifiers


def _parse_disk(info: Mapping[str, object], *, boot_identifier: str, where: str) -> DiskInfo:
    identifier = _required_string(info, "DeviceIdentifier", where)
    label = _optional_string(info, "VolumeName", where) or ""
    model = _optional_string(info, "MediaName", where) or _optional_string(info, "Model", where)
    return DiskInfo(
        identifier=identifier,
        size=_required_size(info, where),
        label=label,
        model=model or "",
        protocol=_optional_string(info, "BusProtocol", where) or "",
        internal=_required_bool(info, "Internal", where),
        removable=_optional_bool(info, "RemovableMedia", where),
        ejectable=_optional_bool(info, "Ejectable", where),
        whole=_whole_flag(info, where),
        serial=_optional_string(info, "SerialNumber", where),
        virtual_or_physical=_required_string(info, "VirtualOrPhysical", where),
        boot=identifier == boot_identifier,
    )


def _load_plist(text: str, where: str) -> Mapping[str, object]:
    try:
        parsed: object = plistlib.loads(text.encode("utf-8"))
    except (plistlib.InvalidFileException, ExpatError, ValueError) as error:
        raise SafetyError(f"{where}: invalid plist output") from error
    return _as_mapping(parsed, where)


def _as_mapping(value: object, where: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise SafetyError(f"{where}: expected a plist dictionary")
    mapping: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise SafetyError(f"{where}: expected string plist keys")
        mapping[key] = item
    return mapping


def _whole_flag(mapping: Mapping[str, object], where: str) -> bool:
    for key in ("Whole", "WholeDisk"):
        if key in mapping:
            return _required_bool(mapping, key, where)
    raise SafetyError(f"{where}: missing required key 'Whole'")


def _required_bool(mapping: Mapping[str, object], key: str, where: str) -> bool:
    if key not in mapping:
        raise SafetyError(f"{where}: missing required key '{key}'")
    value = mapping[key]
    if not isinstance(value, bool):
        raise SafetyError(f"{where}: required key '{key}' must be a boolean")
    return value


def _optional_bool(mapping: Mapping[str, object], key: str, where: str) -> bool:
    value = mapping.get(key)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise SafetyError(f"{where}: key '{key}' must be a boolean")
    return value


def _required_string(mapping: Mapping[str, object], key: str, where: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise SafetyError(f"{where}: missing required key '{key}'")
    return value


def _optional_string(mapping: Mapping[str, object], key: str, where: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SafetyError(f"{where}: key '{key}' must be a string")
    return value or None


def _required_size(mapping: Mapping[str, object], where: str) -> int:
    for key in ("Size", "TotalSize"):
        if key not in mapping:
            continue
        value = mapping[key]
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        raise SafetyError(f"{where}: required key '{key}' must be a non-negative integer")
    raise SafetyError(f"{where}: missing required key 'Size'")
