from __future__ import annotations

import pytest

from sbc_imager.mbr import build_mbr

MIB = 1024 * 1024
SECTOR = 512


def test_build_mbr_when_defaults_returns_512_byte_sector() -> None:
    mbr = build_mbr(partition_sectors=64 * MIB // SECTOR)

    assert len(mbr) == 512
    assert mbr[510:512] == b"\x55\xaa"
    assert mbr[:446] == bytes(446)


def test_build_mbr_when_defaults_writes_partition_entry() -> None:
    sectors = 64 * MIB // SECTOR

    mbr = build_mbr(partition_sectors=sectors)

    assert mbr[446] == 0x00
    assert mbr[447:450] == b"\xfe\xff\xff"
    assert mbr[450] == 0x07
    assert mbr[451:454] == b"\xfe\xff\xff"
    assert int.from_bytes(mbr[454:458], "little") == 2048
    assert int.from_bytes(mbr[458:462], "little") == sectors


def test_build_mbr_when_custom_start_and_type_writes_fields() -> None:
    mbr = build_mbr(partition_start_lba=4096, partition_sectors=8, type_=0x83)

    assert int.from_bytes(mbr[454:458], "little") == 4096
    assert int.from_bytes(mbr[458:462], "little") == 8
    assert mbr[450] == 0x83


@pytest.mark.parametrize("sectors", [0, -1, 0x1_0000_0000])
def test_build_mbr_when_sector_count_is_invalid_raises(sectors: int) -> None:
    with pytest.raises(ValueError):
        build_mbr(partition_sectors=sectors)


@pytest.mark.parametrize("start", [0, -1, 0x1_0000_0000])
def test_build_mbr_when_start_lba_is_invalid_raises(start: int) -> None:
    with pytest.raises(ValueError):
        build_mbr(partition_start_lba=start, partition_sectors=1)


@pytest.mark.parametrize("type_", [-1, 256])
def test_build_mbr_when_type_is_out_of_range_raises(type_: int) -> None:
    with pytest.raises(ValueError):
        build_mbr(partition_sectors=1, type_=type_)
