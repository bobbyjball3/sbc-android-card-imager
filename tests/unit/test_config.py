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
    assert manifest.apks[0].path is not None
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


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "imager.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_load_manifest_when_github_source_parses_without_url(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[[source]]\nid = "obtainium"\ntype = "github"\n'
        'repo = "ImranR98/Obtainium"\ntag = "v1.7.1"\n'
        'asset = "app-arm64-v8a-release.apk"\n',
    )

    manifest = load_manifest(path)

    source = manifest.sources[0]
    assert source.type == "github"
    assert source.url is None
    assert source.repo == "ImranR98/Obtainium"
    assert source.tag == "v1.7.1"
    assert source.asset == "app-arm64-v8a-release.apk"
    assert source.sha256 is None
    assert source.license is None
    assert source.attribution is None


@pytest.mark.parametrize("key", ["repo", "tag", "asset"])
def test_load_manifest_when_github_source_missing_required_key_raises(
    tmp_path: Path, key: str
) -> None:
    values = {
        "repo": 'repo = "Owner/Name"\n',
        "tag": 'tag = "v1"\n',
        "asset": 'asset = "app.apk"\n',
    }
    body = '[[source]]\nid = "s"\ntype = "github"\n' + "".join(
        value for name, value in values.items() if name != key
    )
    path = _write(tmp_path, body)

    with pytest.raises(ConfigError) as caught:
        load_manifest(path)

    assert key in caught.value.message


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("url", '"https://example.com/app.apk"'),
        ("ref", '"v1"'),
        ("subdir", '"nested"'),
        ("filename", '"app.apk"'),
    ],
)
def test_load_manifest_when_github_source_has_unsupported_key_raises(
    tmp_path: Path, key: str, value: str
) -> None:
    path = _write(
        tmp_path,
        '[[source]]\nid = "s"\ntype = "github"\n'
        'repo = "Owner/Name"\ntag = "v1"\nasset = "app.apk"\n'
        f"{key} = {value}\n",
    )

    with pytest.raises(ConfigError) as caught:
        load_manifest(path)

    assert key in caught.value.message


@pytest.mark.parametrize("key", ["repo", "tag", "asset"])
def test_load_manifest_when_non_github_source_has_github_key_raises(
    tmp_path: Path, key: str
) -> None:
    values = {
        "repo": 'repo = "Owner/Name"\n',
        "tag": 'tag = "v1"\n',
        "asset": 'asset = "app.apk"\n',
    }
    path = _write(
        tmp_path,
        '[[source]]\nid = "s"\ntype = "url"\nurl = "https://example.com/app.apk"\n' + values[key],
    )

    with pytest.raises(ConfigError) as caught:
        load_manifest(path)

    assert key in caught.value.message


@pytest.mark.parametrize("asset", ["../escape.apk", "nested/app.apk", "bad\\name.apk"])
def test_load_manifest_when_github_asset_is_not_a_plain_name_raises(
    tmp_path: Path, asset: str
) -> None:
    path = _write(
        tmp_path,
        '[[source]]\nid = "s"\ntype = "github"\n'
        'repo = "Owner/Name"\ntag = "v1"\n'
        f"asset = '{asset}'\n",
    )

    with pytest.raises(ConfigError) as caught:
        load_manifest(path)

    assert "asset" in caught.value.message


def test_load_manifest_when_apk_source_parses_without_path(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[[apk]]\nsource = "obtainium"\nas = "Obtainium.apk"\n',
    )

    manifest = load_manifest(path)

    assert manifest.apks[0].path is None
    assert manifest.apks[0].source == "obtainium"
    assert manifest.apks[0].as_ == "Obtainium.apk"


def test_load_manifest_when_apk_has_source_and_path_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[[apk]]\nsource = "obtainium"\npath = "app.apk"\nas = "Obtainium.apk"\n',
    )

    with pytest.raises(ConfigError) as caught:
        load_manifest(path)

    assert "path" in caught.value.message
    assert "source" in caught.value.message


def test_load_manifest_when_apk_source_has_no_as_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, '[[apk]]\nsource = "obtainium"\n')

    with pytest.raises(ConfigError) as caught:
        load_manifest(path)

    assert "as" in caught.value.message
