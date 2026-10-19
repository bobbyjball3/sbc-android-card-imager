"""Shared validation primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Never

from sbc_imager.cannoli import normalize_tag
from sbc_imager.errors import ConfigError


@dataclass(frozen=True, slots=True)
class Warning:
    code: str
    message: str
    entry_index: int | None = None


def error(code: str, detail: str) -> Never:
    raise ConfigError(f"{code}: {detail}")


def tag(value: str, where: str) -> str:
    try:
        return normalize_tag(value)
    except ConfigError as caught:
        raise ConfigError(
            f"unknown-platform: {where} uses unknown platform tag {value!r}",
            caught.hint,
        ) from caught
