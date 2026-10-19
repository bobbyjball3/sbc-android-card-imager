"""Parse, format, and align binary sizes, and check image size rules."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from sbc_imager.config import ImageConfig
from sbc_imager.validation_common import error

_SIZE_RE = re.compile(r"^(\d+(?:\.\d{1,3})?)\s*([KMGT]iB|B|bytes?)?$", re.IGNORECASE)
_UNITS = {
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
    "b": 1,
    "byte": 1,
    "bytes": 1,
}
_FORMAT_UNITS = (("TiB", 1024**4), ("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024))
_DECIMALS = 1000


def parse_size(value: str) -> int:
    match = _SIZE_RE.fullmatch(value.strip())
    if match is None:
        error("invalid-size", f"unsupported size {value!r}")
    try:
        amount = Decimal(match.group(1)) * _UNITS[(match.group(2) or "B").casefold()]
    except (KeyError, InvalidOperation):
        error("invalid-size", f"unsupported size {value!r}")
    if amount < 0 or amount != amount.to_integral_value():
        error("invalid-size", f"size {value!r} must be a whole, non-negative number of bytes")
    return int(amount)


def format_size(value: int) -> str:
    if value < 0:
        raise ValueError(f"size must be non-negative, got {value}")
    for unit, factor in _FORMAT_UNITS:
        if value < factor:
            continue
        whole, remainder = divmod(value, factor)
        fraction = (remainder * _DECIMALS + factor // 2) // factor
        if fraction == _DECIMALS:
            whole += 1
            fraction = 0
        if fraction:
            digits = f"{fraction:03d}".rstrip("0")
            return f"{whole}.{digits}{unit}"
        return f"{whole}{unit}"
    return f"{value}B"


def align_up(value: int, alignment: int) -> int:
    if alignment <= 0:
        raise ValueError(f"alignment must be positive, got {alignment}")
    return -(-value // alignment) * alignment


def check_image(image: ImageConfig) -> int | None:
    if len(image.label) > 11:
        error("label-too-long", f"image.label {image.label!r} exceeds the 11-character limit")
    pinned = None if image.size.strip().casefold() == "auto" else parse_size(image.size)
    parse_size(image.reserve)
    return pinned
