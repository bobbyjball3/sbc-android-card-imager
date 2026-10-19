from __future__ import annotations

from pathlib import Path

import pytest

from sbc_imager.config import Manifest, load_manifest
from sbc_imager.errors import ConfigError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _load(name: str) -> Manifest:
    return load_manifest(FIXTURES / name)


def test_load_manifest_when_minimal_applies_image_defaults() -> None:
    manifest = _load("minimal.toml")

    assert isinstance(manifest, Manifest)
    assert manifest.base_dir == FIXTURES
    assert manifest.image.name == "minimal"
    assert manifest.image.label == "CANNOLI"
    assert manifest.image.size == "auto"
    assert manifest.image.reserve == "8GiB"
    assert manifest.image.output == FIXTURES / "dist" / "minimal.img"


def test_load_manifest_when_minimal_parses_every_section() -> None:
    manifest = _load("minimal.toml")

    assert [source.id for source in manifest.sources] == ["assets"]
    source = manifest.sources[0]
    assert source.type == "git"
    assert source.url == "https://example.com/assets.git"
    assert source.ref == "v1.0.0"
    assert source.subdir == "pack"
    assert source.filename is None
    assert source.sha256 is None
    assert source.license == "CC-BY-4.0"
    assert source.attribution == "Example Assets"

    assert [rom.platform for rom in manifest.roms] == ["GBA", "N64"]
    assert manifest.roms[0].path == FIXTURES / "roms" / "gba"
    assert manifest.roms[0].include == ("**/*",)
    assert manifest.roms[0].exclude == ()

    assert [bios.platform for bios in manifest.bios] == ["GBA"]
    assert manifest.bios[0].path == FIXTURES / "bios" / "gba"
    assert manifest.bios[0].as_ is None

    assert [art.platform for art in manifest.art] == ["GBA"]
    assert manifest.art[0].path == FIXTURES / "art" / "gba"
    assert manifest.art[0].include == ("**/*",)
    assert manifest.art[0].exclude == ()

    assert [overlay.platform for overlay in manifest.overlays] == ["GBA", "SNES"]
    assert manifest.overlays[0].path == FIXTURES / "overlays" / "gba"
    assert manifest.overlays[1].path == Path("overlays/snes")
    assert not manifest.overlays[1].path.is_absolute()
    assert manifest.overlays[1].source == "assets"

    assert [shader.path for shader in manifest.shaders] == [
        FIXTURES / "shaders" / "crt.glslp",
        Path("shaders/lcd.glslp"),
    ]
    assert manifest.shaders[1].source == "assets"

    assert [apk.path for apk in manifest.apks] == [FIXTURES / "apks" / "retroarch.apk"]
    assert manifest.apks[0].as_ is None

    assert [artifact.dest for artifact in manifest.artifacts] == ["Cannoli/Guides"]
    assert manifest.artifacts[0].root == "cannoli"
    assert manifest.artifacts[0].path == FIXTURES / "guides"
    assert manifest.artifacts[0].as_ is None


def test_load_manifest_when_relative_paths_resolves_against_fixture_dir() -> None:
    manifest = _load("relative-path.toml")

    assert manifest.base_dir == FIXTURES
    assert manifest.image.name == "relative"
    assert manifest.image.output == FIXTURES / "out" / "card.img"
    assert manifest.roms[0].path == FIXTURES / "roms" / "n64"
    assert manifest.roms[0].include == ("**/*.z64", "**/*.n64")
    assert manifest.roms[0].exclude == ("*.tmp",)


def test_load_manifest_when_unknown_section_key_raises_with_key_and_path() -> None:
    with pytest.raises(ConfigError) as caught:
        _load("unknown-key.toml")

    assert "image.nope" in caught.value.message
    assert str(FIXTURES / "unknown-key.toml") in caught.value.message


def test_load_manifest_when_duplicate_source_id_raises() -> None:
    with pytest.raises(ConfigError) as caught:
        _load("duplicate-source.toml")

    assert "duplicate source id" in caught.value.message
    assert "'x'" in caught.value.message
    assert str(FIXTURES / "duplicate-source.toml") in caught.value.message


def test_load_manifest_when_required_field_missing_includes_entry_index() -> None:
    with pytest.raises(ConfigError) as caught:
        _load("missing-required.toml")

    assert "rom[0]" in caught.value.message
    assert "platform" in caught.value.message
    assert str(FIXTURES / "missing-required.toml") in caught.value.message


def test_load_manifest_when_include_is_not_a_list_of_strings_raises(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "wrong-type.toml"
    manifest_path.write_text(
        '[image]\n\n[[rom]]\nplatform = "GBA"\npath = "roms"\ninclude = "*.gba"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as caught:
        load_manifest(manifest_path)

    assert "rom[0].include" in caught.value.message
    assert str(manifest_path) in caught.value.message


def test_load_manifest_when_local_path_uses_tilde_expands_home() -> None:
    manifest = _load("minimal.toml")

    tilde_path = manifest.roms[1].path

    assert str(tilde_path).startswith(str(Path.home()))
    assert "~" not in str(tilde_path)


def test_load_manifest_when_targets_do_not_exist_still_loads() -> None:
    missing_rom = FIXTURES / "roms" / "gba"
    assert not missing_rom.exists()

    manifest = _load("minimal.toml")

    assert manifest.roms[0].path == missing_rom
