"""exFAT filename and destination-collision checks."""

from __future__ import annotations

import re
import unicodedata

from sbc_imager.validation_common import Warning, error
from sbc_imager.validation_destinations import Destination

_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)
_FORBIDDEN = frozenset('\\:*?"<>|')
_RESERVED_DESTINATIONS = frozenset({("cannoli", "config", "settings.json"), ("credits.md",)})


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def check_component(part: str) -> None:
    if not part or part in {".", ".."}:
        error("exfat-name", f"invalid destination component {part!r}")
    if any(character in _FORBIDDEN or ord(character) < 32 for character in part):
        error("exfat-name", f"destination component {part!r} contains an exFAT-forbidden character")
    if part[-1] in ". ":
        error("exfat-name", f"destination component {part!r} ends with a dot or space")
    stem = part.split(".")[0].upper()
    if stem in _RESERVED_NAMES or re.fullmatch(r"(?:COM|LPT)[1-9]", stem):
        error("exfat-name", f"destination component {part!r} uses a reserved exFAT name")
    if len(part) > 255:
        error("exfat-name", f"destination component {part!r} exceeds 255 characters")


def check_destinations(destinations: list[Destination], warnings: list[Warning]) -> None:
    exact: dict[str, str] = {}
    normalized: dict[tuple[str, ...], str] = {}
    warned: set[str] = set()
    for destination in destinations:
        parts = destination.dest.parts
        for part in parts:
            check_component(part)
            if nfc(part) != part and part not in warned:
                warned.add(part)
                warnings.append(
                    Warning(
                        "non-nfc-name",
                        f"destination name {part!r} is not Unicode NFC",
                        destination.entry_index,
                    )
                )
        raw = destination.dest.as_posix()
        key = tuple(nfc(part).casefold() for part in parts)
        owner = f"{destination.kind}[{destination.entry_index}]"
        if raw in exact:
            error("duplicate-destination", f"{raw!r} is produced by {exact[raw]} and {owner}")
        if key in normalized:
            error(
                "destination-collision",
                f"{raw!r} collides with {normalized[key]!r} after NFC and case folding",
            )
        if key in _RESERVED_DESTINATIONS:
            error("reserved-destination", f"{raw!r} is reserved by Cannoli")
        exact[raw] = owner
        normalized[key] = raw
