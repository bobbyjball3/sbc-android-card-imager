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

    assert [apk.path for apk in manifest.apks] == [
        FIXTURES / "apks" / "retroarch.apk",
        (Path.home() / "apks" / "local.apk").resolve(),
    ]
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
    assert manifest.overlays[0].path == FIXTURES / "overlays" / "n64"
    assert manifest.apks[0].path == FIXTURES / "apps" / "app.apk"


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

    assert "overlay[0]" in caught.value.message
    assert "platform" in caught.value.message
    assert str(FIXTURES / "missing-required.toml") in caught.value.message


def test_load_manifest_when_as_is_not_a_string_raises(tmp_path: Path) -> None:
    manifest_path = tmp_path / "wrong-type.toml"
    manifest_path.write_text(
        '[image]\n\n[[apk]]\npath = "app.apk"\nas = 7\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as caught:
        load_manifest(manifest_path)

    assert "apk[0].as" in caught.value.message
    assert str(manifest_path) in caught.value.message


def test_load_manifest_when_local_path_uses_tilde_expands_home() -> None:
    manifest = _load("minimal.toml")

    tilde_path = manifest.apks[1].path

    assert str(tilde_path).startswith(str(Path.home()))
    assert "~" not in str(tilde_path)


@pytest.mark.parametrize("target_kind", ["file", "directory"])
def test_load_manifest_when_typed_root_is_symlink_raises(tmp_path: Path, target_kind: str) -> None:
    target = tmp_path / "real"
    if target_kind == "directory":
        target.mkdir()
        (target / "demo.apk").write_bytes(b"apk")
    else:
        target.write_bytes(b"apk")
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=target_kind == "directory")
    manifest_path = tmp_path / "symlink.toml"
    manifest_path.write_text(f'[[apk]]\npath = "{link.name}"\n', encoding="utf-8")

    with pytest.raises(ConfigError) as caught:
        load_manifest(manifest_path)

    assert "symlink: apk[0]" in caught.value.message


def test_load_manifest_when_typed_path_parent_is_symlink_allows(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    (real / "apps").mkdir(parents=True)
    (real / "apps" / "demo.apk").write_bytes(b"apk")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    manifest_path = tmp_path / "parent-symlink.toml"
    manifest_path.write_text('[[apk]]\npath = "link/apps/demo.apk"\n', encoding="utf-8")

    manifest = load_manifest(manifest_path)

    assert manifest.apks[0].path == (real / "apps" / "demo.apk").resolve()
    assert not manifest.apks[0].path.is_symlink()


def test_load_manifest_when_targets_do_not_exist_still_loads() -> None:
    missing_guides = FIXTURES / "guides"
    assert not missing_guides.exists()

    manifest = _load("minimal.toml")

    assert manifest.artifacts[0].path == missing_guides


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ("rom", "`[[rom]]` is no longer supported; Cannoli/RomM supplies ROM content."),
        ("bios", "`[[bios]]` is no longer supported; Cannoli/RomM supplies BIOS content."),
        ("art", "`[[art]]` is no longer supported; Cannoli/RomM supplies box art."),
    ],
)
def test_load_manifest_when_retired_table_is_present_raises(
    tmp_path: Path, table: str, message: str
) -> None:
    manifest_path = tmp_path / "retired.toml"
    manifest_path.write_text(f'[[{table}]]\npath = "files"\n', encoding="utf-8")

    with pytest.raises(ConfigError) as caught:
        load_manifest(manifest_path)

    assert message in caught.value.message
    assert str(manifest_path) in caught.value.message
