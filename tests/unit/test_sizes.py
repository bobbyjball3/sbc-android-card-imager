from __future__ import annotations

import pytest

from sbc_imager.errors import ConfigError
from sbc_imager.sizes import align_up, format_size, parse_size

KIB = 1024
MIB = 1024**2
GIB = 1024**3
TIB = 1024**4


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", 0),
        ("512", 512),
        ("512B", 512),
        ("512 byte", 512),
        ("512 bytes", 512),
        ("1KiB", KIB),
        ("1MiB", MIB),
        ("8GiB", 8 * GIB),
        ("1TiB", TIB),
        ("0.5KiB", 512),
        ("1.5MiB", 1536 * KIB),
        ("2.25GiB", 9 * GIB // 4),
        (" 8GiB ", 8 * GIB),
        ("1kib", KIB),
    ],
)
def test_parse_size_when_valid_returns_bytes(value: str, expected: int) -> None:
    assert parse_size(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", " ", "-1", "-1GiB", "8GB", "8M", "1.2345GiB", "many", "1.2.3MiB", "GiB"],
)
def test_parse_size_when_invalid_raises(value: str) -> None:
    with pytest.raises(ConfigError):
        parse_size(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0B"),
        (512, "512B"),
        (1023, "1023B"),
        (KIB, "1KiB"),
        (1536, "1.5KiB"),
        (1025, "1.001KiB"),
        (MIB, "1MiB"),
        (3 * MIB // 2, "1.5MiB"),
        (GIB, "1GiB"),
        (TIB, "1TiB"),
    ],
)
def test_format_size_when_non_negative_returns_short_form(value: int, expected: str) -> None:
    assert format_size(value) == expected


def test_format_size_when_negative_raises() -> None:
    with pytest.raises(ValueError):
        format_size(-1)


@pytest.mark.parametrize(
    ("value", "alignment", "expected"),
    [
        (0, 512, 0),
        (1, 512, 512),
        (512, 512, 512),
        (513, 512, 1024),
        (1024 * MIB, MIB, 1024 * MIB),
        (1024 * MIB + 1, MIB, 1025 * MIB),
    ],
)
def test_align_up_when_alignment_positive_rounds_up(
    value: int, alignment: int, expected: int
) -> None:
    assert align_up(value, alignment) == expected


@pytest.mark.parametrize("alignment", [0, -1])
def test_align_up_when_alignment_not_positive_raises(alignment: int) -> None:
    with pytest.raises(ValueError):
        align_up(1, alignment)
