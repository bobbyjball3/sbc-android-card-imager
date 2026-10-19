"""Cannoli v1.9.1 platform registry and on-card path contract.

The platform tags below were extracted from the pinned Cannoli v1.9.1
``platforms.json`` asset.  There is deliberately no network access at runtime;
refresh the registry by fetching the pinned source and copying the tag/name
pairs into :data:`PLATFORM_TAGS`.

Pinned source:
https://raw.githubusercontent.com/CannoliHQ/cannoli/7755e376b6add0bbd25ea19104c368b7a40b979f/app/src/main/assets/platforms.json
Pinned commit: 7755e376b6add0bbd25ea19104c368b7a40b979f
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Final

from sbc_imager.errors import ConfigError

CANNOLI_VERSION: Final = "1.9.1"
CANNOLI_COMMIT: Final = "7755e376b6add0bbd25ea19104c368b7a40b979f"
CANNOLI_PLATFORMS_URL: Final = (
    "https://raw.githubusercontent.com/CannoliHQ/cannoli/"
    "7755e376b6add0bbd25ea19104c368b7a40b979f/app/src/main/assets/platforms.json"
)

PLATFORM_TAGS: Final[dict[str, str]] = {
    "GB": "Game Boy",
    "GBC": "Game Boy Color",
    "GBA": "Game Boy Advance",
    "NES": "Nintendo Entertainment System",
    "FDS": "Famicom Disk System",
    "SNES": "Super Nintendo Entertainment System",
    "N64": "Nintendo 64",
    "NDS": "Nintendo DS",
    "GG": "Game Gear",
    "SMS": "Master System",
    "MD": "Sega Genesis",
    "SG1000": "Sega SG-1000",
    "32X": "Sega 32X",
    "SEGACD": "Sega CD",
    "SATURN": "Sega Saturn",
    "PS": "PlayStation",
    "PSP": "PSP",
    "DC": "Dreamcast",
    "LYNX": "Atari Lynx",
    "JAGUAR": "Atari Jaguar",
    "ATARI2600": "Atari 2600",
    "ATARI5200": "Atari 5200",
    "ATARI7800": "Atari 7800",
    "PCE": "PC Engine",
    "PCFX": "PC-FX",
    "PICO8": "PICO-8",
    "NGP": "Neo Geo Pocket",
    "NGPC": "Neo Geo Pocket Color",
    "WS": "WonderSwan",
    "WSC": "WonderSwan Color",
    "NEOGEO": "Neo Geo",
    "MAME": "Arcade",
    "FBN": "Arcade",
    "VIRTUALBOY": "Virtual Boy",
    "POKEMINI": "Pokemon Mini",
    "COLECOVISION": "ColecoVision",
    "VECTREX": "Vectrex",
    "INTELLIVISION": "Intellivision",
    "SUPERGRAFX": "PC Engine SuperGrafx",
    "DOS": "DOS",
    "SCUMMVM": "ScummVM",
    "AMIGA": "Amiga",
    "PC": "PC",
    "PS2": "PlayStation 2",
    "GC": "GameCube",
    "WII": "Wii",
    "3DS": "Nintendo 3DS",
    "WIIU": "Wii U",
    "PSVITA": "PS Vita",
    "PS3": "PlayStation 3",
    "NSW": "Nintendo Switch",
}

PC_SHORTCUT_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".steam",
        ".steamappid",
        ".epic",
        ".gog",
        ".amazon",
        ".pcgame",
        ".localgameid",
        ".txt",
    }
)

HARD_REQUIRED_BIOS: Final[dict[str, tuple[str, ...]]] = {
    "SATURN": ("sega_101.bin", "mpr-17933.bin"),
    "PCFX": ("pcfx.rom",),
    "PSP": ("PPSSPP/ppge_atlas.zim",),
    "INTELLIVISION": ("exec.bin", "grom.bin"),
    "COLECOVISION": ("Databases/msxromdb.xml", "Machines/SharedRoms/MSX.rom"),
    "AMIGA": (
        "kick34005.A500",
        "kick40068.A1200",
        "kick40060.CD32",
        "kick40060.CD32.ext",
    ),
}

_CANNOLI_ROOT: Final = PurePosixPath("Cannoli")
_TAG_LOOKUP: Final[dict[str, str]] = {tag.casefold(): tag for tag in PLATFORM_TAGS}
_TOP_LEVEL_DIRS: Final[tuple[str, ...]] = (
    "Art",
    "BIOS",
    "Backup",
    "Cheats",
    "Config",
    "Guides",
    "Logs",
    "Media/Screenshots",
    "Media/Recordings",
    "Overlays",
    "Roms",
    "Save States",
    "Saves",
    "Shaders",
    "Wallpapers",
)


def cannoli_root() -> PurePosixPath:
    """Return the Cannoli data root relative to the card root."""
    return _CANNOLI_ROOT


def rom_dir(tag: str) -> PurePosixPath:
    """Return ``Cannoli/Roms/<TAG>`` for a platform tag."""
    return _CANNOLI_ROOT / "Roms" / validate_tag(tag)


def bios_dir(tag: str) -> PurePosixPath:
    """Return ``Cannoli/BIOS/<TAG>`` for a platform tag."""
    return _CANNOLI_ROOT / "BIOS" / validate_tag(tag)


def art_dir(tag: str) -> PurePosixPath:
    """Return ``Cannoli/Art/<TAG>`` for a platform tag."""
    return _CANNOLI_ROOT / "Art" / validate_tag(tag)


def overlays_dir(tag: str) -> PurePosixPath:
    """Return ``Cannoli/Overlays/<TAG>`` for a platform tag."""
    return _CANNOLI_ROOT / "Overlays" / validate_tag(tag)


def shaders_dir() -> PurePosixPath:
    """Return the shared ``Cannoli/Shaders`` directory."""
    return _CANNOLI_ROOT / "Shaders"


def saves_dir(tag: str) -> PurePosixPath:
    """Return ``Cannoli/Saves/<TAG>`` for a platform tag."""
    return _CANNOLI_ROOT / "Saves" / validate_tag(tag)


def save_states_dir(tag: str) -> PurePosixPath:
    """Return ``Cannoli/Save States/<TAG>`` for a platform tag."""
    return _CANNOLI_ROOT / "Save States" / validate_tag(tag)


def cheats_dir(tag: str) -> PurePosixPath:
    """Return ``Cannoli/Cheats/<TAG>`` for a platform tag."""
    return _CANNOLI_ROOT / "Cheats" / validate_tag(tag)


def guides_dir(tag: str) -> PurePosixPath:
    """Return ``Cannoli/Guides/<TAG>`` for a platform tag."""
    return _CANNOLI_ROOT / "Guides" / validate_tag(tag)


def media_screenshots_dir() -> PurePosixPath:
    """Return the shared ``Cannoli/Media/Screenshots`` directory."""
    return _CANNOLI_ROOT / "Media" / "Screenshots"


def media_recordings_dir() -> PurePosixPath:
    """Return the shared ``Cannoli/Media/Recordings`` directory."""
    return _CANNOLI_ROOT / "Media" / "Recordings"


def settings_path() -> PurePosixPath:
    """Return the Cannoli settings marker path."""
    return _CANNOLI_ROOT / "Config" / "settings.json"


def apks_dir() -> PurePosixPath:
    """Return the top-level ``APKs`` directory."""
    return PurePosixPath("APKs")


def credits_path() -> PurePosixPath:
    """Return the top-level attribution file path."""
    return PurePosixPath("CREDITS.md")


def normalize_tag(value: str) -> str:
    """Return the canonical uppercase tag for a case-insensitive input."""
    tag = _TAG_LOOKUP.get(value.strip().casefold())
    if tag is None:
        message = f"unknown Cannoli platform tag: {value!r}"
        hint = f"Use one of: {', '.join(PLATFORM_TAGS)}"
        raise ConfigError(message, hint)
    return tag


def validate_tag(value: str) -> str:
    """Validate a platform tag and return its canonical uppercase form."""
    return normalize_tag(value)


def required_dirs() -> tuple[PurePosixPath, ...]:
    """Return every directory the card must contain for Cannoli v1.9.1."""
    dirs: list[PurePosixPath] = [cannoli_root()]
    dirs.extend(_CANNOLI_ROOT / name for name in _TOP_LEVEL_DIRS)
    dirs.extend(rom_dir(tag) for tag in PLATFORM_TAGS)
    dirs.append(apks_dir())
    return tuple(dirs)


def render_markdown() -> str:
    """Render the deterministic platform reference document."""
    lines = [
        "# Cannoli platform tags",
        "",
        f"Pinned Cannoli version: **v{CANNOLI_VERSION}**  ",
        f"Pinned commit: `{CANNOLI_COMMIT}`  ",
        f"Source: <{CANNOLI_PLATFORMS_URL}>",
        "",
        "This registry contains all "
        f"{len(PLATFORM_TAGS)} platform tags shipped by the pinned Cannoli release. "
        "ROMs belong in `Cannoli/Roms/<TAG>/`; `APKs/` sits at the card root.",
        "",
        "| Tag | Platform | Notes |",
        "| --- | --- | --- |",
    ]
    for tag, name in PLATFORM_TAGS.items():
        notes = "shortcut files only" if tag == "PC" else ""
        lines.append(f"| {tag} | {name} | {notes} |")

    lines.extend(
        [
            "",
            "## Hard-required BIOS",
            "",
            "These platforms will not start without the listed BIOS files. Place them "
            "under `Cannoli/BIOS/<TAG>/`.",
            "",
            "| Tag | Required files |",
            "| --- | --- |",
        ]
    )
    for tag, files in HARD_REQUIRED_BIOS.items():
        rendered = ", ".join(f"`{name}`" for name in files)
        lines.append(f"| {tag} | {rendered} |")

    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Print the platform reference; no network access is performed."""
    parser = argparse.ArgumentParser(
        prog="python -m sbc_imager.cannoli",
        description="Show the pinned Cannoli platform registry.",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Print the platform reference as Markdown.",
    )
    args = parser.parse_args(argv)
    if args.markdown:
        print(render_markdown(), end="")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
