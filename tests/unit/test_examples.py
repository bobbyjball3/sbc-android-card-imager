from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import pytest

from sbc_imager.cannoli import required_dirs
from sbc_imager.config import load_manifest
from sbc_imager.errors import ConfigError
from sbc_imager.planner import build_plan
from sbc_imager.sources import ResolvedSource
from sbc_imager.validation import iter_destinations, validate_manifest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "rg477m"
MANIFEST = EXAMPLE / "rg477m.toml"
TAILSCALE = EXAMPLE / "obtainium-tailscale.json"

OBTAINIUM_SIZE = 27_194_505
PACK_SIZE = 78_201
TAILSCALE_SIZE = 383
EXPECTED_CONTENT_BYTES = OBTAINIUM_SIZE + PACK_SIZE + TAILSCALE_SIZE

EXPECTED_DESTINATIONS = [
    PurePosixPath("APKs/Obtainium.apk"),
    PurePosixPath("Obtainium/obtainium-emulation-pack-v8.0.1.json"),
    PurePosixPath("Obtainium/tailscale.json"),
]


def _manifest():
    return load_manifest(MANIFEST)


def _resolved(tmp_path: Path) -> dict[str, ResolvedSource]:
    apk = tmp_path / "Obtainium.apk"
    apk.write_bytes(b"apk")
    pack = tmp_path / "obtainium-emulation-pack-v8.0.1.json"
    pack.write_bytes(b"{}")
    return {
        "obtainium": ResolvedSource(
            id="obtainium",
            root=apk,
            kind="github",
            metadata={
                "repo": "ImranR98/Obtainium",
                "tag": "v1.7.1",
                "asset": "app-arm64-v8a-release.apk",
                "license": "GPL-3.0",
                "attribution": "ImranR98/Obtainium (release v1.7.1)",
                "sha256": "04dfd02c56dae8d5271d2d402977e1b07c8eeffb313df054a13e71b75b8b8a26",
            },
        ),
        "emulation-pack": ResolvedSource(
            id="emulation-pack",
            root=pack,
            kind="github",
            metadata={
                "repo": "RJNY/Obtainium-Emulation-Pack",
                "tag": "v8.0.1",
                "asset": "obtainium-emulation-pack-v8.0.1.json",
                "license": "Unlicense",
                "attribution": "RJNY/Obtainium-Emulation-Pack (release v8.0.1)",
                "sha256": "c2170687b07881f5891fe9751903c13c31b80de506bd41b718f99abb45592169",
            },
        ),
    }


def test_rg477m_manifest_when_loaded_validates_without_warnings() -> None:
    manifest = _manifest()

    assert validate_manifest(manifest) == []
    assert manifest.image.name == "rg477m"
    assert manifest.image.label == "CANNOLI"
    assert manifest.image.size == "auto"
    assert manifest.image.reserve == "8GiB"
    assert manifest.artifacts[0].source == "emulation-pack"
    assert manifest.artifacts[0].path is None
    assert manifest.artifacts[1].source is None
    assert manifest.artifacts[1].path == EXAMPLE / "obtainium-tailscale.json"


def test_rg477m_manifest_when_planned_has_three_payload_destinations(tmp_path: Path) -> None:
    plan = build_plan(_manifest(), _resolved(tmp_path))

    assert [entry.dest for entry in iter_destinations(_manifest())] == EXPECTED_DESTINATIONS
    assert [entry.dest for entry in plan.entries] == EXPECTED_DESTINATIONS
    assert [entry.kind for entry in plan.entries] == ["apk", "artifact", "artifact"]
    assert [entry.source_id for entry in plan.entries] == [
        "obtainium",
        "emulation-pack",
        None,
    ]
    assert plan.warnings == ()
    assert plan.entries[2].size == TAILSCALE_SIZE
    assert plan.content_bytes == plan.entries[0].size + plan.entries[1].size + TAILSCALE_SIZE


def test_rg477m_manifest_when_loaded_pins_the_expected_releases() -> None:
    manifest = _manifest()
    sources = {source.id: source for source in manifest.sources}

    assert (sources["obtainium"].repo, sources["obtainium"].tag) == (
        "ImranR98/Obtainium",
        "v1.7.1",
    )
    assert sources["obtainium"].asset == "app-arm64-v8a-release.apk"
    assert (sources["emulation-pack"].repo, sources["emulation-pack"].tag) == (
        "RJNY/Obtainium-Emulation-Pack",
        "v8.0.1",
    )
    assert sources["emulation-pack"].asset == "obtainium-emulation-pack-v8.0.1.json"


def test_rg477m_tailscale_import_when_parsed_has_required_shape() -> None:
    raw = TAILSCALE.read_bytes()

    assert raw.endswith(b"\n")
    assert len(raw) == TAILSCALE_SIZE
    data = json.loads(raw)
    assert data["settings"] is None
    assert len(data["apps"]) == 1
    app = data["apps"][0]
    assert app["id"] == "com.tailscale.ipn"
    assert app["url"] == "https://github.com/tailscale/tailscale-android"
    assert app["author"] == "tailscale"
    assert app["name"] == "Tailscale"
    settings = json.loads(app["additionalSettings"])
    assert settings == {
        "includePrereleases": False,
        "fallbackToOlderReleases": True,
        "verifyLatestTag": False,
        "sortMethodChoice": "date",
        "autoApkFilterByArch": True,
    }


def test_rg477m_manifest_when_combined_with_pins_has_expected_content_bytes() -> None:
    assert len(TAILSCALE.read_bytes()) == TAILSCALE_SIZE
    assert EXPECTED_CONTENT_BYTES == 27_273_089


def test_cannoli_required_dirs_when_counted_has_51_rom_tags_and_68_dirs() -> None:
    dirs = required_dirs()
    rom_tags = {path.name for path in dirs if path.parent == PurePosixPath("Cannoli/Roms")}

    assert len(rom_tags) == 51
    assert len(dirs) == 68
    assert {"GB", "GBC", "GBA", "GG", "NGPC", "NES", "SNES", "MD", "PS", "N64"} <= rom_tags


def test_rg477m_credits_when_built_include_both_licenses(tmp_path: Path) -> None:
    credits = build_plan(_manifest(), _resolved(tmp_path)).credits_marker.content

    assert "GPL-3.0" in credits
    assert "Unlicense" in credits
    assert "ImranR98/Obtainium" in credits
    assert "RJNY/Obtainium-Emulation-Pack" in credits


def test_rg477m_manifest_when_retired_table_is_added_fails(tmp_path: Path) -> None:
    body = MANIFEST.read_text(encoding="utf-8") + '\n[[rom]]\nplatform = "GBA"\npath = "roms"\n'
    path = tmp_path / "rg477m.toml"
    path.write_text(body, encoding="utf-8")

    with pytest.raises(ConfigError) as caught:
        load_manifest(path)

    assert "[[rom]]" in caught.value.message
