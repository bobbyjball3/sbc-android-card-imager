"""Temporary size parsing used until todo 13 introduces ``sizes.py``."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from sbc_imager.config import ImageConfig
from sbc_imager.validation_common import error

_SIZE_RE = re.compile(r"^(\d+(?:\.\d{1,3})?)\s*([KMGT]iB|B|bytes?)?$", re.IGNORECASE)
_UNITS = {"kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4, "b": 1, "bytes": 1}


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


def check_image(image: ImageConfig) -> int | None:
    if len(image.label) > 11:
        error("label-too-long", f"image.label {image.label!r} exceeds the 11-character limit")
    pinned = None if image.size.strip().casefold() == "auto" else parse_size(image.size)
    parse_size(image.reserve)
    return pinned
