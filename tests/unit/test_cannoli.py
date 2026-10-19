from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath

import pytest

import sbc_imager.cannoli as cannoli_module
from sbc_imager.cannoli import (
    CANNOLI_COMMIT,
    CANNOLI_PLATFORMS_URL,
    CANNOLI_VERSION,
    HARD_REQUIRED_BIOS,
    PC_SHORTCUT_EXTENSIONS,
    PLATFORM_TAGS,
    apks_dir,
    art_dir,
    bios_dir,
    cannoli_root,
    cheats_dir,
    credits_path,
    guides_dir,
    media_recordings_dir,
    media_screenshots_dir,
    normalize_tag,
    overlays_dir,
    render_markdown,
    required_dirs,
    rom_dir,
    save_states_dir,
    saves_dir,
    settings_path,
    shaders_dir,
    validate_tag,
)
from sbc_imager.errors import ConfigError

DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "cannoli-platform-tags.md"

PINNED_ORDER = (
    "GB",
    "GBC",
    "GBA",
    "NES",
    "FDS",
    "SNES",
    "N64",
    "NDS",
    "GG",
    "SMS",
    "MD",
    "SG1000",
    "32X",
    "SEGACD",
    "SATURN",
    "PS",
    "PSP",
    "DC",
    "LYNX",
    "JAGUAR",
    "ATARI2600",
    "ATARI5200",
    "ATARI7800",
    "PCE",
    "PCFX",
    "PICO8",
    "NGP",
    "NGPC",
    "WS",
    "WSC",
    "NEOGEO",
    "MAME",
    "FBN",
    "VIRTUALBOY",
    "POKEMINI",
    "COLECOVISION",
    "VECTREX",
    "INTELLIVISION",
    "SUPERGRAFX",
    "DOS",
    "SCUMMVM",
    "AMIGA",
    "PC",
    "PS2",
    "GC",
    "WII",
    "3DS",
    "WIIU",
    "PSVITA",
    "PS3",
    "NSW",
)


def test_platform_tags_when_loaded_has_51_unique_uppercase_tags() -> None:
    assert len(PLATFORM_TAGS) == 51
    assert len(set(PLATFORM_TAGS)) == 51
    assert all(tag == tag.upper() and tag.isascii() for tag in PLATFORM_TAGS)
    assert all(PLATFORM_TAGS.values())


def test_platform_tags_when_loaded_preserves_pinned_registry_order() -> None:
    assert tuple(PLATFORM_TAGS) == PINNED_ORDER


def test_platform_tags_when_loaded_maps_tags_to_display_names() -> None:
    assert PLATFORM_TAGS["GBA"] == "Game Boy Advance"
    assert PLATFORM_TAGS["MD"] == "Sega Genesis"
    assert PLATFORM_TAGS["PC"] == "PC"
    assert PLATFORM_TAGS["NSW"] == "Nintendo Switch"
    assert PLATFORM_TAGS["MAME"] == "Arcade"
    assert PLATFORM_TAGS["FBN"] == "Arcade"


def test_constants_when_loaded_pin_cannoli_v191_source() -> None:
    assert CANNOLI_VERSION == "1.9.1"
    assert CANNOLI_COMMIT == "7755e376b6add0bbd25ea19104c368b7a40b979f"
    assert CANNOLI_PLATFORMS_URL.endswith(
        "/7755e376b6add0bbd25ea19104c368b7a40b979f/app/src/main/assets/platforms.json"
    )


@pytest.mark.parametrize(
    ("builder", "expected"),
    [
        (cannoli_root, "Cannoli"),
        (shaders_dir, "Cannoli/Shaders"),
        (media_screenshots_dir, "Cannoli/Media/Screenshots"),
        (media_recordings_dir, "Cannoli/Media/Recordings"),
        (settings_path, "Cannoli/Config/settings.json"),
        (apks_dir, "APKs"),
        (credits_path, "CREDITS.md"),
    ],
)
def test_path_builder_when_called_returns_pure_posix_path(
    builder: Callable[[], PurePosixPath], expected: str
) -> None:
    result = builder()

    assert isinstance(result, PurePosixPath)
    assert result == PurePosixPath(expected)


@pytest.mark.parametrize(
    ("builder", "tag", "expected"),
    [
        (rom_dir, "gba", "Cannoli/Roms/GBA"),
        (bios_dir, "GBA", "Cannoli/BIOS/GBA"),
        (art_dir, "saturn", "Cannoli/Art/SATURN"),
        (overlays_dir, "AMIGA", "Cannoli/Overlays/AMIGA"),
        (saves_dir, "PC", "Cannoli/Saves/PC"),
        (save_states_dir, "pc", "Cannoli/Save States/PC"),
        (cheats_dir, "NES", "Cannoli/Cheats/NES"),
        (guides_dir, "nsw", "Cannoli/Guides/NSW"),
    ],
)
def test_tag_path_builder_when_called_returns_canonical_path(
    builder: Callable[[str], PurePosixPath], tag: str, expected: str
) -> None:
    result = builder(tag)

    assert isinstance(result, PurePosixPath)
    assert result == PurePosixPath(expected)


def test_normalize_tag_when_lowercase_returns_canonical_uppercase() -> None:
    assert normalize_tag("gba") == "GBA"


def test_normalize_tag_when_whitespace_and_mixed_case_returns_canonical() -> None:
    assert normalize_tag("  sAtUrN \n") == "SATURN"


def test_normalize_tag_when_unknown_raises_config_error_with_hint() -> None:
    with pytest.raises(ConfigError) as caught:
        normalize_tag("NOPE")

    assert "NOPE" in caught.value.message
    assert caught.value.hint is not None
    assert "GBA" in caught.value.hint


def test_validate_tag_when_unknown_raises_config_error_not_key_error() -> None:
    with pytest.raises(ConfigError):
        validate_tag("NOPE")


def test_validate_tag_when_lowercase_returns_canonical_uppercase() -> None:
    assert validate_tag("gba") == "GBA"


def test_pc_shortcut_extensions_when_loaded_match_cannoli_contract() -> None:
    assert {
        ".steam",
        ".steamappid",
        ".epic",
        ".gog",
        ".amazon",
        ".pcgame",
        ".localgameid",
        ".txt",
    } == PC_SHORTCUT_EXTENSIONS


def test_hard_required_bios_when_loaded_matches_cannoli_contract() -> None:
    assert HARD_REQUIRED_BIOS == {
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


def test_required_dirs_when_called_contains_full_cannoli_tree() -> None:
    dirs = required_dirs()

    assert isinstance(dirs, tuple)
    assert all(isinstance(path, PurePosixPath) for path in dirs)
    assert len(dirs) == len(set(dirs)) == 68
    assert dirs[0] == PurePosixPath("Cannoli")
    assert dirs[-1] == PurePosixPath("APKs")
    assert {
        PurePosixPath("Cannoli"),
        PurePosixPath("Cannoli/Art"),
        PurePosixPath("Cannoli/BIOS"),
        PurePosixPath("Cannoli/Backup"),
        PurePosixPath("Cannoli/Cheats"),
        PurePosixPath("Cannoli/Config"),
        PurePosixPath("Cannoli/Guides"),
        PurePosixPath("Cannoli/Logs"),
        PurePosixPath("Cannoli/Media/Screenshots"),
        PurePosixPath("Cannoli/Media/Recordings"),
        PurePosixPath("Cannoli/Overlays"),
        PurePosixPath("Cannoli/Roms"),
        PurePosixPath("Cannoli/Save States"),
        PurePosixPath("Cannoli/Saves"),
        PurePosixPath("Cannoli/Shaders"),
        PurePosixPath("Cannoli/Wallpapers"),
        PurePosixPath("APKs"),
    }.issubset(dirs)
    assert {PurePosixPath("Cannoli/Roms") / tag for tag in PLATFORM_TAGS}.issubset(dirs)


def test_required_dirs_when_called_is_deterministic() -> None:
    assert required_dirs() == required_dirs()


def test_render_markdown_when_called_is_deterministic() -> None:
    assert render_markdown() == render_markdown()
    assert render_markdown().endswith("\n")


def test_render_markdown_when_called_pins_version_commit_and_source() -> None:
    markdown = render_markdown()

    assert "v1.9.1" in markdown
    assert CANNOLI_COMMIT in markdown
    assert CANNOLI_PLATFORMS_URL in markdown


def test_render_markdown_when_called_has_one_row_per_platform() -> None:
    markdown = render_markdown()
    main_table = markdown.split("## Hard-required BIOS", 1)[0]
    rows = [
        line
        for line in main_table.splitlines()
        if line.startswith("| ") and not line.startswith(("| Tag |", "| ---"))
    ]

    assert len(rows) == 51
    assert "| GBA | Game Boy Advance |  |" in rows
    assert "| PC | PC | shortcut files only |" in rows


def test_render_markdown_when_called_lists_hard_required_bios() -> None:
    markdown = render_markdown()

    assert "## Hard-required BIOS" in markdown
    for tag, files in HARD_REQUIRED_BIOS.items():
        assert f"| {tag} |" in markdown
        for filename in files:
            assert filename in markdown


def test_doc_when_compared_to_registry_is_current() -> None:
    assert DOC_PATH.read_text(encoding="utf-8") == render_markdown()


def test_module_when_imported_has_no_runtime_network_client() -> None:
    source = Path(str(cannoli_module.__file__)).read_text(encoding="utf-8")

    assert "httpx" not in source
    assert "requests" not in source
    assert "urllib" not in source
    assert "urlopen" not in source
    assert "socket" not in source
