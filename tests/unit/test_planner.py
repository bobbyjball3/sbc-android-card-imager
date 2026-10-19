from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from sbc_imager.cannoli import CANNOLI_VERSION
from sbc_imager.config import Manifest, load_manifest
from sbc_imager.errors import ConfigError
from sbc_imager.planner import build_plan
from sbc_imager.sources import ResolvedSource

MIB = 1024 * 1024


def _touch(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _manifest(tmp_path: Path, body: str, files: tuple[str, ...] = ()) -> Manifest:
    for name in files:
        _touch(tmp_path / name)
    path = tmp_path / "imager.toml"
    path.write_text(body, encoding="utf-8")
    return load_manifest(path)


def _resolved(root: Path, source_id: str = "assets") -> dict[str, ResolvedSource]:
    return {
        source_id: ResolvedSource(
            id=source_id,
            root=root,
            kind="git",
            metadata={"url": "https://example.com/assets.git", "ref": "v1.0.0"},
        )
    }


MIXED = """
[image]
label = "CANNOLI"
size = "auto"
reserve = "8GiB"

[[source]]
id = "assets"
type = "git"
url = "https://example.com/assets.git"
ref = "v1.0.0"
license = "CC-BY-4.0"
attribution = "Example Assets"

[[overlay]]
platform = "GBA"
path = "overlays/bezel.png"

[[overlay]]
platform = "SNES"
path = "snes/overlay.png"
source = "assets"

[[shader]]
path = "shaders/crt"

[[shader]]
path = "presets/lcd.glslp"
source = "assets"

[[apk]]
path = "apps/retroarch.apk"

[[artifact]]
root = "card"
dest = "Guides"
path = "guides"
"""

MIXED_CONTENT = 7

MIXED_FILES = (
    "overlays/bezel.png",
    "shaders/crt/crt.glslp",
    "shaders/crt/pass.glsl",
    "apps/retroarch.apk",
    "guides/setup.md",
)


def _assets(tmp_path: Path) -> Path:
    root = tmp_path / "assets"
    _touch(root / "snes" / "overlay.png")
    _touch(root / "presets" / "lcd.glslp")
    return root


def test_build_plan_when_mixed_manifest_maps_every_destination(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, MIXED, MIXED_FILES)
    plan = build_plan(manifest, _resolved(_assets(tmp_path)))

    assert [entry.dest for entry in plan.entries] == [
        PurePosixPath("Cannoli/Overlays/GBA/bezel.png"),
        PurePosixPath("Cannoli/Overlays/SNES/overlay.png"),
        PurePosixPath("Cannoli/Shaders/crt/crt.glslp"),
        PurePosixPath("Cannoli/Shaders/crt/pass.glsl"),
        PurePosixPath("Cannoli/Shaders/lcd/lcd.glslp"),
        PurePosixPath("APKs/retroarch.apk"),
        PurePosixPath("Guides/setup.md"),
    ]
    assert [entry.kind for entry in plan.entries] == [
        "overlay",
        "overlay",
        "shader",
        "shader",
        "shader",
        "apk",
        "artifact",
    ]
    assert plan.entries[0].entry_index == 0
    assert plan.entries[0].size == 1
    assert plan.entries[1].source_id == "assets"
    assert plan.entries[4].source_id == "assets"
    assert plan.entries[5].source_id is None
    assert plan.entries[6].source_id is None
    assert all(entry.src.is_file() for entry in plan.entries)
    assert plan.content_bytes == sum(entry.size for entry in plan.entries)


def test_build_plan_when_source_overlay_is_a_directory_preserves_relative_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "assets"
    _touch(root / "gba" / "bezel.png")
    _touch(root / "gba" / "nested" / "frame.png")
    _touch(root / "gba" / "notes.txt")
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "assets"\ntype = "git"\nurl = "https://example.com/a.git"\n'
        'ref = "v1"\nlicense = "MIT"\nattribution = "Example"\n\n'
        '[[overlay]]\nplatform = "GBA"\npath = "gba"\nsource = "assets"\n',
    )

    plan = build_plan(manifest, _resolved(root))

    assert [entry.dest for entry in plan.entries] == [
        PurePosixPath("Cannoli/Overlays/GBA/gba/bezel.png"),
        PurePosixPath("Cannoli/Overlays/GBA/gba/nested/frame.png"),
    ]
    assert {entry.source_id for entry in plan.entries} == {"assets"}


def test_build_plan_when_source_shader_directory_uses_preset_root(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    _touch(root / "preset" / "crt.glslp")
    _touch(root / "preset" / "shaders" / "pass.glsl")
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "assets"\ntype = "git"\nurl = "https://example.com/a.git"\n'
        'ref = "v1"\nlicense = "MIT"\nattribution = "Example"\n\n'
        '[[shader]]\npath = "preset"\nsource = "assets"\n',
    )

    plan = build_plan(manifest, _resolved(root))

    assert [entry.dest for entry in plan.entries] == [
        PurePosixPath("Cannoli/Shaders/preset/crt.glslp"),
        PurePosixPath("Cannoli/Shaders/preset/shaders/pass.glsl"),
    ]


def test_build_plan_when_source_path_is_a_file_uses_basename_and_as(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    _touch(root / "gba" / "bezel.png")
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "assets"\ntype = "git"\nurl = "https://example.com/a.git"\n'
        'ref = "v1"\nlicense = "MIT"\nattribution = "Example"\n\n'
        '[[overlay]]\nplatform = "GBA"\npath = "gba/bezel.png"\nsource = "assets"\n'
        'as = "custom.png"\n',
    )

    plan = build_plan(manifest, _resolved(root))

    assert [entry.dest for entry in plan.entries] == [
        PurePosixPath("Cannoli/Overlays/GBA/custom.png")
    ]
    assert plan.entries[0].src == (root / "gba" / "bezel.png").resolve()


def test_build_plan_when_empty_manifest_raises(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, '[image]\nname = "empty"\n')

    with pytest.raises(ConfigError, match="empty-plan"):
        build_plan(manifest, {})


def test_build_plan_when_source_is_not_resolved_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "assets"\ntype = "git"\nurl = "https://example.com/a.git"\n'
        'ref = "v1"\nlicense = "MIT"\nattribution = "Example"\n\n'
        '[[shader]]\npath = "crt.glslp"\nsource = "assets"\n',
    )

    with pytest.raises(ConfigError, match="missing-source-resolution"):
        build_plan(manifest, {})


def test_build_plan_when_source_path_is_missing_raises(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    root.mkdir()
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "assets"\ntype = "git"\nurl = "https://example.com/a.git"\n'
        'ref = "v1"\nlicense = "MIT"\nattribution = "Example"\n\n'
        '[[shader]]\npath = "nope.glslp"\nsource = "assets"\n',
    )

    with pytest.raises(ConfigError, match="missing-source-path"):
        build_plan(manifest, _resolved(root))


def test_build_plan_when_auto_size_uses_reserve_and_alignment(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, MIXED, MIXED_FILES)
    plan = build_plan(manifest, _resolved(_assets(tmp_path)), reserve="16MiB")

    content = MIXED_CONTENT
    overhead = 64 * MIB
    expected_partition = ((content + overhead + 16 * MIB + MIB - 1) // MIB) * MIB
    assert plan.content_bytes == content
    assert plan.overhead_bytes == overhead
    assert plan.reserve_bytes == 16 * MIB
    assert plan.partition_offset_bytes == MIB
    assert plan.partition_bytes == expected_partition
    assert plan.image_bytes == MIB + expected_partition


def test_build_plan_when_auto_size_defaults_to_eight_gib_reserve(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, MIXED, MIXED_FILES)
    plan = build_plan(manifest, _resolved(_assets(tmp_path)))

    assert plan.reserve_bytes == 8 * 1024 * MIB


def test_build_plan_when_manifest_reserve_is_used(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        MIXED.replace('reserve = "8GiB"', 'reserve = "20MiB"'),
        MIXED_FILES,
    )
    plan = build_plan(manifest, _resolved(_assets(tmp_path)))

    assert plan.reserve_bytes == 20 * MIB


def test_build_plan_when_pinned_size_uses_exact_image_bytes(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, MIXED, MIXED_FILES)
    plan = build_plan(manifest, _resolved(_assets(tmp_path)), size="128MiB")

    assert plan.image_bytes == 128 * MIB
    assert plan.partition_bytes == 127 * MIB
    assert plan.partition_offset_bytes == MIB


def test_build_plan_when_size_override_pins_auto_manifest(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, MIXED, MIXED_FILES)
    plan = build_plan(manifest, _resolved(_assets(tmp_path)), size="256MiB")

    assert plan.image_bytes == 256 * MIB
    assert plan.partition_bytes == 255 * MIB


def test_build_plan_when_pinned_size_overflows_raises(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, MIXED, MIXED_FILES)

    with pytest.raises(ConfigError, match="content-overflow"):
        build_plan(manifest, _resolved(_assets(tmp_path)), size="1MiB")


def test_build_plan_when_size_override_beats_a_small_pinned_manifest(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, MIXED.replace('size = "auto"', 'size = "1MiB"'), MIXED_FILES)

    plan = build_plan(manifest, _resolved(_assets(tmp_path)), size="128MiB")

    assert plan.image_bytes == 128 * MIB


def test_build_plan_when_pinned_size_is_not_partition_aligned_raises(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, MIXED, MIXED_FILES)

    with pytest.raises(ConfigError, match="pinned-size"):
        build_plan(manifest, _resolved(_assets(tmp_path)), size="65.5MiB")


def test_build_plan_when_overhead_is_one_percent_above_64_mib(tmp_path: Path) -> None:
    body = '[image]\nsize = "auto"\n\n[[artifact]]\nroot = "card"\ndest = "."\npath = "big"\n'
    size = 8 * 1024 * MIB
    (tmp_path / "big").mkdir()
    with (tmp_path / "big" / "blob.bin").open("wb") as handle:
        handle.truncate(size)
    manifest = _manifest(tmp_path, body)

    plan = build_plan(manifest, {})

    assert plan.overhead_bytes == (size + 99) // 100
    assert plan.overhead_bytes > 64 * MIB


def test_build_plan_when_required_dirs_and_markers_are_present(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, MIXED, MIXED_FILES)
    plan = build_plan(manifest, _resolved(_assets(tmp_path)))

    rom_dirs = [
        path
        for path in plan.required_dirs
        if path.parts[:2] == ("Cannoli", "Roms") and len(path.parts) == 3
    ]
    assert len(rom_dirs) == 51
    assert PurePosixPath("Cannoli/Config/settings.json") == plan.settings_marker.path
    assert plan.settings_marker.content == "{}\n"
    assert PurePosixPath("Cannoli/Config") in plan.required_dirs
    assert plan.credits_marker.path == PurePosixPath("CREDITS.md")
    assert plan.settings_marker.path not in {entry.dest for entry in plan.entries}


def test_build_plan_when_credits_include_cannoli_and_redacted_sources(tmp_path: Path) -> None:
    body = (
        '[[source]]\nid = "assets"\ntype = "git"\n'
        'url = "https://user:secret@example.com/assets.git"\nref = "v1.0.0"\n'
        'license = "CC-BY-4.0"\nattribution = "Example Assets"\n\n'
        '[[shader]]\npath = "crt.glslp"\nsource = "assets"\n'
    )
    _touch(tmp_path / "assets" / "crt.glslp")
    manifest = _manifest(tmp_path, body)

    plan = build_plan(manifest, _resolved(tmp_path / "assets"))

    credits = plan.credits_marker.content
    assert "Generated by sbc-imager." in credits
    assert f"Cannoli v{CANNOLI_VERSION}" in credits
    assert "GPL-3.0" in credits
    assert "assets" in credits
    assert "https://example.com/assets.git" in credits
    assert "v1.0.0" in credits
    assert "CC-BY-4.0" in credits
    assert "Example Assets" in credits
    assert "secret" not in credits


def test_build_plan_when_local_file_sizes_are_summed(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[artifact]]\nroot = "card"\ndest = "Guides"\npath = "guides"\n',
        (),
    )
    _touch(tmp_path / "guides" / "a.md", b"abc")
    _touch(tmp_path / "guides" / "b.md", b"defgh")

    plan = build_plan(manifest, {})

    assert plan.content_bytes == 8
    assert [entry.size for entry in plan.entries] == [3, 5]


GITHUB_APK = """
[image]
name = "obtainium"
size = "auto"
reserve = "1MiB"

[[source]]
id = "obtainium"
type = "github"
repo = "ImranR98/Obtainium"
tag = "v1.7.1"
asset = "app-arm64-v8a-release.apk"

[[apk]]
source = "obtainium"
as = "Obtainium.apk"
"""


def _github_resolved(root: Path) -> dict[str, ResolvedSource]:
    return {
        "obtainium": ResolvedSource(
            id="obtainium",
            root=root,
            kind="github",
            metadata={
                "repo": "ImranR98/Obtainium",
                "tag": "v1.7.1",
                "asset": "app-arm64-v8a-release.apk",
                "sha256": "04dfd02c56dae8d5271d2d402977e1b07c8eeffb313df054a13e71b75b8b8a26",
                "size": "5",
                "license": "GPL-3.0",
                "attribution": "ImranR98/Obtainium "
                "(https://github.com/ImranR98/Obtainium/releases/tag/v1.7.1)",
                "release_url": "https://github.com/ImranR98/Obtainium/releases/tag/v1.7.1",
            },
        )
    }


def test_build_plan_when_apk_source_is_a_file_plans_apks_destination(tmp_path: Path) -> None:
    source = _touch(tmp_path / "cache" / "Obtainium.apk", b"apk!!")
    manifest = _manifest(tmp_path, GITHUB_APK)

    plan = build_plan(manifest, _github_resolved(source))

    assert [entry.dest for entry in plan.entries] == [PurePosixPath("APKs/Obtainium.apk")]
    assert plan.entries[0].kind == "apk"
    assert plan.entries[0].src == source
    assert plan.entries[0].size == 5
    assert plan.entries[0].source_id == "obtainium"
    assert plan.content_bytes == 5


def test_build_plan_when_apk_source_is_a_directory_raises(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    (root / "Obtainium.apk").parent.mkdir(parents=True)
    (root / "Obtainium.apk").write_bytes(b"apk")
    manifest = _manifest(tmp_path, GITHUB_APK)

    with pytest.raises(ConfigError, match="apk-source-directory"):
        build_plan(manifest, _github_resolved(root))


def test_build_plan_when_apk_source_is_not_resolved_raises(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, GITHUB_APK)

    with pytest.raises(ConfigError, match="missing-source-resolution"):
        build_plan(manifest, {})


def test_build_plan_when_github_credits_include_release_provenance(tmp_path: Path) -> None:
    source = _touch(tmp_path / "cache" / "Obtainium.apk", b"apk!!")
    manifest = _manifest(tmp_path, GITHUB_APK)

    plan = build_plan(manifest, _github_resolved(source))

    credits = plan.credits_marker.content
    assert "obtainium" in credits
    assert "ImranR98/Obtainium" in credits
    assert "v1.7.1" in credits
    assert "app-arm64-v8a-release.apk" in credits
    assert "04dfd02c56dae8d5271d2d402977e1b07c8eeffb313df054a13e71b75b8b8a26" in credits
    assert "GPL-3.0" in credits
    release = "https://github.com/ImranR98/Obtainium/releases/tag/v1.7.1"
    assert f"ImranR98/Obtainium ({release})" in credits
    assert release in credits
