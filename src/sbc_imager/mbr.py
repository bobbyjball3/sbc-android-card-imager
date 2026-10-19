"""Build the 512-byte MBR that describes the single exFAT partition."""

from __future__ import annotations

_MAX_U32 = 0xFFFFFFFF
_CHS = b"\xfe\xff\xff"
_SIGNATURE = b"\x55\xaa"


def _check_u32(name: str, value: int, *, minimum: int) -> None:
    if value < minimum or value > _MAX_U32:
        raise ValueError(f"{name} must be between {minimum} and {_MAX_U32}, got {value}")


def build_mbr(
    partition_start_lba: int = 2048,
    *,
    partition_sectors: int,
    type_: int = 0x07,
) -> bytes:
    _check_u32("partition_start_lba", partition_start_lba, minimum=1)
    _check_u32("partition_sectors", partition_sectors, minimum=1)
    if not 0 <= type_ <= 0xFF:
        raise ValueError(f"type_ must be between 0 and 255, got {type_}")
    mbr = bytearray(512)
    mbr[446] = 0x00
    mbr[447:450] = _CHS
    mbr[450] = type_
    mbr[451:454] = _CHS
    mbr[454:458] = partition_start_lba.to_bytes(4, "little")
    mbr[458:462] = partition_sectors.to_bytes(4, "little")
    mbr[510:512] = _SIGNATURE
    return bytes(mbr)
