from __future__ import annotations

import pytest

from sbc_imager.errors import SafetyError
from sbc_imager.imaging import (
    DiskAssessment,
    DiskInfo,
    full_disk_image_size,
    resolve_explicit_disk,
)

MIB = 1024 * 1024
DISK5_BYTES = 511_868_665_856


def _disk(identifier: str = "disk9", size: int = 64 * 1024**3) -> DiskInfo:
    return DiskInfo(
        identifier=identifier,
        size=size,
        label="SDCARD",
        model="SanDisk Ultra",
        protocol="USB",
        internal=False,
        removable=True,
        ejectable=True,
        whole=True,
        serial="0123456789AB",
    )


def _assessment(
    disk: DiskInfo,
    *,
    allowed: bool = True,
    reason: str = "external removable disk",
) -> DiskAssessment:
    return DiskAssessment(
        disk=disk,
        allowed=allowed,
        status="allowed" if allowed else "blocked",
        reason=reason,
    )


def test_full_disk_image_size_when_disk5_uses_full_aligned_size() -> None:
    image_bytes = full_disk_image_size(DISK5_BYTES)

    assert image_bytes == DISK5_BYTES
    assert image_bytes // MIB == 488_156
    assert image_bytes - MIB == 511_867_617_280


def test_full_disk_image_size_when_size_is_not_mib_aligned_rounds_down() -> None:
    assert full_disk_image_size(100 * MIB + 12_345) == 100 * MIB


def test_full_disk_image_size_when_exactly_two_mib_is_allowed() -> None:
    assert full_disk_image_size(2 * MIB) == 2 * MIB


@pytest.mark.parametrize("disk_size", [0, 1, MIB, 2 * MIB - 1])
def test_full_disk_image_size_when_too_small_raises(disk_size: int) -> None:
    with pytest.raises(SafetyError, match="too small"):
        full_disk_image_size(disk_size)


def test_resolve_explicit_disk_when_allowed_returns_disk() -> None:
    disk = _disk()

    resolved = resolve_explicit_disk([_assessment(disk)], "/dev/rdisk9")

    assert resolved == disk


def test_resolve_explicit_disk_when_blocked_raises_reason_and_hint() -> None:
    disk = _disk("disk5")
    assessment = _assessment(
        disk,
        allowed=False,
        reason="internal SD reader; re-run with --allow-builtin-sd",
    )

    with pytest.raises(SafetyError) as caught:
        resolve_explicit_disk([assessment], "disk5")

    assert "internal SD reader" in caught.value.message
    assert caught.value.hint is not None
    assert "image --list" in caught.value.hint


def test_resolve_explicit_disk_when_not_whole_raises_hint() -> None:
    with pytest.raises(SafetyError) as caught:
        resolve_explicit_disk([], "/dev/disk99")

    assert "not a whole disk" in caught.value.message
    assert caught.value.hint is not None
    assert "image --list" in caught.value.hint


def test_resolve_explicit_disk_when_device_is_malformed_raises() -> None:
    with pytest.raises(SafetyError, match="invalid device"):
        resolve_explicit_disk([], "rdisk5")
