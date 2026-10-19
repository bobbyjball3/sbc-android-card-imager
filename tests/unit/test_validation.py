from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

import pytest

from sbc_imager.config import Manifest, load_manifest
from sbc_imager.errors import ConfigError
from sbc_imager.validation import Destination, Warning, iter_destinations, validate_manifest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "validation"


def _touch(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _manifest(tmp_path: Path, body: str, files: tuple[str, ...] = ()) -> Manifest:
    for name in files:
        _touch(tmp_path / name)
    manifest_path = tmp_path / "imager.toml"
    manifest_path.write_text(body, encoding="utf-8")
    return load_manifest(manifest_path)


def _assert_error(manifest: Manifest, code: str) -> ConfigError:
    with pytest.raises(ConfigError) as caught:
        validate_manifest(manifest)
    assert caught.value.message.startswith(f"{code}:"), caught.value.message
    return caught.value


def _codes(manifest: Manifest) -> set[str]:
    return {warning.code for warning in validate_manifest(manifest)}


def _symlink_or_skip(target: Path, link: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")


def test_warning_when_created_keeps_fields() -> None:
    warning = Warning("overlay-non-png", "junk", 3)

    assert warning.code == "overlay-non-png"
    assert warning.message == "junk"
    assert warning.entry_index == 3


def test_destination_when_created_keeps_fields() -> None:
    destination = Destination(
        PurePosixPath("Cannoli/Overlays/GBA/demo.png"), 0, "overlay", Path("src")
    )

    assert destination.dest == PurePosixPath("Cannoli/Overlays/GBA/demo.png")
    assert destination.entry_index == 0
    assert destination.kind == "overlay"
    assert destination.source_root == Path("src")


def test_validate_manifest_when_unknown_platform_tag_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[overlay]]\nplatform = "NOPE"\npath = "overlays/demo.png"\n',
        ("overlays/demo.png",),
    )

    error = _assert_error(manifest, "unknown-platform")

    assert "NOPE" in error.message


def test_validate_manifest_when_tag_is_lowercase_accepts_and_canonicalizes(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[overlay]]\nplatform = "gba"\npath = "overlays/demo.png"\n',
        ("overlays/demo.png",),
    )

    assert validate_manifest(manifest) == []
    assert [destination.dest for destination in iter_destinations(manifest)] == [
        PurePosixPath("Cannoli/Overlays/GBA/demo.png")
    ]


def test_validate_manifest_when_overlay_source_is_unknown_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[overlay]]\nplatform = "GBA"\npath = "missing.png"\nsource = "nope"\n',
    )

    error = _assert_error(manifest, "unknown-source")

    assert "nope" in error.message


@pytest.mark.parametrize("field", ["license", "attribution"])
def test_validate_manifest_when_remote_source_metadata_missing_raises(
    tmp_path: Path, field: str
) -> None:
    metadata = {
        "license": 'license = "MIT"\n',
        "attribution": 'attribution = "Example"\n',
    }
    body = (
        '[[source]]\nid = "s"\ntype = "git"\nurl = "https://example.com/s.git"\n'
        + "".join(value for key, value in metadata.items() if key != field)
        + '[[overlay]]\nplatform = "GBA"\npath = "x.png"\nsource = "s"\n'
    )
    manifest = _manifest(tmp_path, body)

    error = _assert_error(manifest, "source-metadata")

    assert field in error.message


def test_validate_manifest_when_overlay_file_is_not_png_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[overlay]]\nplatform = "GBA"\npath = "overlay.txt"\n',
        ("overlay.txt",),
    )

    _assert_error(manifest, "overlay-extension")


def test_validate_manifest_when_shader_file_is_not_glslp_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[shader]]\npath = "shader.txt"\n',
        ("shader.txt",),
    )

    _assert_error(manifest, "shader-extension")


def test_validate_manifest_when_shader_dir_has_no_root_preset_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[shader]]\npath = "shaders"\n',
        ("shaders/nested/crt.glslp",),
    )

    _assert_error(manifest, "shader-root-preset")


def test_validate_manifest_when_apk_is_not_apk_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[apk]]\npath = "app.zip"\n',
        ("app.zip",),
    )

    _assert_error(manifest, "apk-extension")


def test_validate_manifest_when_local_path_is_missing_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[apk]]\npath = "missing"\n',
    )

    error = _assert_error(manifest, "missing-path")

    assert "missing" in error.message


def test_validate_manifest_when_local_tree_contains_symlink_raises(tmp_path: Path) -> None:
    target = _touch(tmp_path / "real.apk")
    _symlink_or_skip(target, tmp_path / "apps" / "link.apk")
    manifest = _manifest(tmp_path, '[[apk]]\npath = "apps"\n')

    _assert_error(manifest, "symlink")


def test_validate_manifest_when_local_tree_contains_special_file_raises(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFOs are unavailable on this platform")
    (tmp_path / "apps").mkdir()
    os.mkfifo(tmp_path / "apps" / "pipe.apk")
    manifest = _manifest(tmp_path, '[[apk]]\npath = "apps"\n')

    _assert_error(manifest, "special-file")


def test_validate_manifest_when_typed_entry_has_no_files_raises(tmp_path: Path) -> None:
    (tmp_path / "apps").mkdir()
    manifest = _manifest(tmp_path, '[[apk]]\npath = "apps"\n')

    _assert_error(manifest, "empty-entry")


def test_validate_manifest_when_destination_has_exfat_invalid_name_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[apk]]\npath = "apps"\n',
        ("apps/bad?.apk",),
    )

    _assert_error(manifest, "exfat-name")


def test_validate_manifest_when_destination_is_reserved_name_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[apk]]\npath = "app.apk"\nas = "CON.apk"\n',
        ("app.apk",),
    )

    _assert_error(manifest, "exfat-name")


def test_validate_manifest_when_destination_has_trailing_dot_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[apk]]\npath = "app.apk"\nas = "app.apk."\n',
        ("app.apk",),
    )

    _assert_error(manifest, "exfat-name")


def test_validate_manifest_when_destination_component_exceeds_255_raises(
    tmp_path: Path,
) -> None:
    long_name = f"{'a' * 256}.apk"
    manifest = _manifest(
        tmp_path,
        f'[[apk]]\npath = "app.apk"\nas = "{long_name}"\n',
        ("app.apk",),
    )

    _assert_error(manifest, "exfat-name")


def test_validate_manifest_when_destinations_collide_by_case_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[apk]]\npath = "a"\n\n[[apk]]\npath = "b"\n',
        ("a/demo.apk", "b/DEMO.APK"),
    )

    _assert_error(manifest, "destination-collision")


def test_validate_manifest_when_destinations_collide_after_nfc_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[artifact]]\nroot = "card"\ndest = "Guides"\npath = "a"\n\n'
        '[[artifact]]\nroot = "card"\ndest = "Guides"\npath = "b"\n',
        ("a/caf\u00e9.md", "b/cafe\u0301.md"),
    )

    with pytest.raises(ConfigError) as caught:
        validate_manifest(manifest)

    assert caught.value.message.startswith(("destination-collision:", "duplicate-destination:"))


def test_validate_manifest_when_destination_is_duplicated_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[artifact]]\nroot = "card"\ndest = "Guides"\npath = "a"\n\n'
        '[[artifact]]\nroot = "card"\ndest = "Guides"\npath = "b"\n',
        ("a/setup.md", "b/setup.md"),
    )

    _assert_error(manifest, "duplicate-destination")


def test_validate_manifest_when_settings_destination_is_reserved_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[artifact]]\nroot = "cannoli"\ndest = "Config"\npath = "files"\n',
        ("files/settings.json",),
    )

    _assert_error(manifest, "reserved-destination")


def test_validate_manifest_when_credits_destination_is_reserved_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[artifact]]\nroot = "card"\ndest = "."\npath = "file"\nas = "CREDITS.md"\n',
        ("file",),
    )

    _assert_error(manifest, "reserved-destination")


def test_validate_manifest_when_label_is_too_long_raises(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, '[image]\nlabel = "ABCDEFGHIJKL"\n')

    error = _assert_error(manifest, "label-too-long")

    assert "11" in error.message


@pytest.mark.parametrize("size", ["8GB", "-1GiB", "1.2345GiB", "many"])
def test_validate_manifest_when_size_is_invalid_raises(tmp_path: Path, size: str) -> None:
    manifest = _manifest(tmp_path, f'[image]\nsize = "{size}"\n')

    _assert_error(manifest, "invalid-size")


def test_validate_manifest_when_reserve_is_invalid_raises(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, '[image]\nreserve = "-8GiB"\n')

    _assert_error(manifest, "invalid-size")


def test_validate_manifest_when_local_content_overflows_pinned_size_raises(
    tmp_path: Path,
) -> None:
    manifest = _manifest(
        tmp_path,
        '[image]\nsize = "64MiB"\n\n[[artifact]]\nroot = "card"\ndest = "Guides"\npath = "files"\n',
        ("files/setup.md",),
    )

    _assert_error(manifest, "content-overflow")


def test_validate_manifest_when_remote_entries_reference_existing_source_does_not_check_files(
    tmp_path: Path,
) -> None:
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "s"\ntype = "git"\nurl = "https://example.com/s.git"\n'
        'license = "MIT"\nattribution = "Example"\n\n'
        '[[overlay]]\nplatform = "GBA"\npath = "overlay.png"\nsource = "s"\n\n'
        '[[shader]]\npath = "crt/crt.glslp"\nsource = "s"\n',
    )

    assert validate_manifest(manifest) == []


def test_validate_manifest_when_filename_is_not_nfc_warns(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[apk]]\npath = "app.apk"\nas = "cafe\u0301.apk"\n',
        ("app.apk",),
    )

    assert "non-nfc-name" in _codes(manifest)


def test_validate_manifest_when_source_is_unused_warns(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "spare"\ntype = "url"\nurl = "https://example.com/x"\n'
        'license = "MIT"\nattribution = "Example"\n',
    )

    assert "unused-source" in _codes(manifest)


def test_validate_manifest_when_artifact_targets_config_warns(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[artifact]]\nroot = "cannoli"\ndest = "Config"\npath = "files"\n',
        ("files/notes.txt",),
    )

    assert "artifact-config" in _codes(manifest)


def test_validate_manifest_when_overlay_dir_has_non_png_warns(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[overlay]]\nplatform = "GBA"\npath = "overlays"\n',
        ("overlays/demo.png", "overlays/notes.txt"),
    )

    warnings = validate_manifest(manifest)

    assert [warning.code for warning in warnings] == ["overlay-non-png"]


def test_validate_manifest_when_valid_fixture_returns_only_expected_warnings() -> None:
    manifest = load_manifest(FIXTURES / "valid.toml")

    warnings = validate_manifest(manifest)

    assert {warning.code for warning in warnings} == {
        "overlay-non-png",
        "unused-source",
    }


def test_validate_manifest_when_static_missing_path_raises() -> None:
    manifest = load_manifest(FIXTURES / "missing-path.toml")

    _assert_error(manifest, "missing-path")


def test_iter_destinations_when_overlay_dir_walks_and_preserves_subdirs(
    tmp_path: Path,
) -> None:
    manifest = _manifest(
        tmp_path,
        '[[overlay]]\nplatform = "GBA"\npath = "overlays"\n',
        ("overlays/demo.png", "overlays/sub/deep.png"),
    )

    destinations = list(iter_destinations(manifest))

    assert [destination.dest for destination in destinations] == [
        PurePosixPath("Cannoli/Overlays/GBA/demo.png"),
        PurePosixPath("Cannoli/Overlays/GBA/sub/deep.png"),
    ]
    assert {destination.kind for destination in destinations} == {"overlay"}
    assert {destination.entry_index for destination in destinations} == {0}
    assert all(destination.source_root == manifest.overlays[0].path for destination in destinations)


def test_iter_destinations_when_hidden_files_are_skipped(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[artifact]]\nroot = "card"\ndest = "Guides"\npath = "guides"\n',
        (
            "guides/setup.md",
            "guides/.DS_Store",
            "guides/.hidden.md",
        ),
    )

    assert [destination.dest.name for destination in iter_destinations(manifest)] == ["setup.md"]


def test_iter_destinations_when_overlay_file_uses_as(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[overlay]]\nplatform = "GBA"\npath = "overlay.png"\nas = "renamed.png"\n',
        ("overlay.png",),
    )

    assert [destination.dest for destination in iter_destinations(manifest)] == [
        PurePosixPath("Cannoli/Overlays/GBA/renamed.png")
    ]


def test_iter_destinations_when_overlay_dir_only_yields_png(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[overlay]]\nplatform = "GBA"\npath = "overlays"\n',
        ("overlays/demo.png", "overlays/notes.txt"),
    )

    assert [destination.dest for destination in iter_destinations(manifest)] == [
        PurePosixPath("Cannoli/Overlays/GBA/demo.png")
    ]


def test_iter_destinations_when_shader_dir_becomes_preset(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[shader]]\npath = "crt"\n',
        ("crt/crt.glslp", "crt/pass.glsl"),
    )

    assert [destination.dest for destination in iter_destinations(manifest)] == [
        PurePosixPath("Cannoli/Shaders/crt/crt.glslp"),
        PurePosixPath("Cannoli/Shaders/crt/pass.glsl"),
    ]


def test_iter_destinations_when_shader_file_becomes_preset(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[shader]]\npath = "crt.glslp"\n',
        ("crt.glslp",),
    )

    assert [destination.dest for destination in iter_destinations(manifest)] == [
        PurePosixPath("Cannoli/Shaders/crt/crt.glslp")
    ]


def test_iter_destinations_when_shader_file_uses_as(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[shader]]\npath = "crt.glslp"\nas = "custom.glslp"\n',
        ("crt.glslp",),
    )

    assert [destination.dest for destination in iter_destinations(manifest)] == [
        PurePosixPath("Cannoli/Shaders/crt/custom.glslp")
    ]


def test_iter_destinations_when_overlay_and_shader_are_source_relative(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "s"\ntype = "git"\nurl = "https://example.com/s.git"\n'
        'license = "MIT"\nattribution = "Example"\n\n'
        '[[overlay]]\nplatform = "GBA"\npath = "gba/overlay.png"\nsource = "s"\n\n'
        '[[shader]]\npath = "preset/crt.glslp"\nsource = "s"\n',
    )

    destinations = list(iter_destinations(manifest))

    assert [destination.dest for destination in destinations] == [
        PurePosixPath("Cannoli/Overlays/GBA/overlay.png"),
        PurePosixPath("Cannoli/Shaders/crt/crt.glslp"),
    ]
    assert destinations[0].source_root == manifest.overlays[0].path
    assert destinations[1].source_root == manifest.shaders[0].path


def test_iter_destinations_when_source_overlay_uses_basename_and_as(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "s"\ntype = "git"\nurl = "https://example.com/s.git"\n'
        'license = "MIT"\nattribution = "Example"\n\n'
        '[[overlay]]\nplatform = "GBA"\npath = "gba/bezel.png"\nsource = "s"\n\n'
        '[[overlay]]\nplatform = "GBA"\npath = "gba/other.png"\nsource = "s"\nas = "custom.png"\n',
    )

    assert [destination.dest for destination in iter_destinations(manifest)] == [
        PurePosixPath("Cannoli/Overlays/GBA/bezel.png"),
        PurePosixPath("Cannoli/Overlays/GBA/custom.png"),
    ]


def test_iter_destinations_when_source_overlay_directory_uses_root_name(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "s"\ntype = "git"\nurl = "https://example.com/s.git"\n'
        'license = "MIT"\nattribution = "Example"\n\n'
        '[[overlay]]\nplatform = "GBA"\npath = "gba"\nsource = "s"\n',
    )

    assert [destination.dest for destination in iter_destinations(manifest)] == [
        PurePosixPath("Cannoli/Overlays/GBA/gba")
    ]


def test_iter_destinations_when_source_shader_uses_preset_stem_and_as(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "s"\ntype = "git"\nurl = "https://example.com/s.git"\n'
        'license = "MIT"\nattribution = "Example"\n\n'
        '[[shader]]\npath = "preset/crt.glslp"\nsource = "s"\n\n'
        '[[shader]]\npath = "preset/lcd.glslp"\nsource = "s"\nas = "custom.glslp"\n',
    )

    assert [destination.dest for destination in iter_destinations(manifest)] == [
        PurePosixPath("Cannoli/Shaders/crt/crt.glslp"),
        PurePosixPath("Cannoli/Shaders/custom/custom.glslp"),
    ]


def test_iter_destinations_when_artifact_file_uses_as(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[artifact]]\nroot = "cannoli"\ndest = "Guides"\npath = "file"\nas = "renamed.md"\n',
        ("file",),
    )

    assert [destination.dest for destination in iter_destinations(manifest)] == [
        PurePosixPath("Cannoli/Guides/renamed.md")
    ]


@pytest.mark.parametrize(
    ("body", "files", "code"),
    [
        (
            '[[overlay]]\nplatform = "GBA"\npath = "a.png"\nas = "/evil.png"\n',
            ("a.png",),
            "invalid-as",
        ),
        ('[[apk]]\npath = "a.apk"\nas = "/evil.apk"\n', ("a.apk",), "invalid-as"),
        (
            '[[overlay]]\nplatform = "GBA"\npath = "a.png"\nas = "dir/evil.png"\n',
            ("a.png",),
            "invalid-as",
        ),
        ('[[apk]]\npath = "a.apk"\nas = "../evil.apk"\n', ("a.apk",), "invalid-as"),
        ('[[shader]]\npath = "a.glslp"\nas = "dir/"\n', ("a.glslp",), "invalid-as"),
        (
            '[[artifact]]\nroot = "card"\ndest = "/evil"\npath = "files"\n',
            ("files/setup.md",),
            "invalid-dest",
        ),
        (
            '[[artifact]]\nroot = "card"\ndest = "a/../evil"\npath = "files"\n',
            ("files/setup.md",),
            "invalid-dest",
        ),
        (
            '[[artifact]]\nroot = "card"\ndest = "a//evil"\npath = "files"\n',
            ("files/setup.md",),
            "invalid-dest",
        ),
    ],
)
def test_validate_manifest_when_as_or_dest_escapes_card_raises(
    tmp_path: Path, body: str, files: tuple[str, ...], code: str
) -> None:
    manifest = _manifest(tmp_path, body, files)

    _assert_error(manifest, code)


@pytest.mark.parametrize(
    ("body", "files", "code"),
    [
        (
            '[[overlay]]\nplatform = "GBA"\npath = "a.png"\nas = "a.txt"\n',
            ("a.png",),
            "overlay-extension",
        ),
        ('[[shader]]\npath = "a.glslp"\nas = "a.txt"\n', ("a.glslp",), "shader-extension"),
        ('[[apk]]\npath = "a.apk"\nas = "a.txt"\n', ("a.apk",), "apk-extension"),
    ],
)
def test_validate_manifest_when_as_bypasses_extension_raises(
    tmp_path: Path, body: str, files: tuple[str, ...], code: str
) -> None:
    manifest = _manifest(tmp_path, body, files)

    _assert_error(manifest, code)


def test_validate_manifest_when_typed_entry_yields_no_destinations_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[overlay]]\nplatform = "GBA"\npath = "overlays"\n',
        ("overlays/notes.txt",),
    )

    _assert_error(manifest, "empty-entry")


def test_iter_destinations_when_apk_file_uses_as(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[apk]]\npath = "app.apk"\nas = "retroarch.apk"\n',
        ("app.apk",),
    )

    assert [destination.dest for destination in iter_destinations(manifest)] == [
        PurePosixPath("APKs/retroarch.apk")
    ]


@pytest.mark.parametrize(
    ("root", "dest", "expected"),
    [
        ("card", "Guides", "Guides/setup.md"),
        ("cannoli", "Guides", "Cannoli/Guides/setup.md"),
    ],
)
def test_iter_destinations_when_artifact_uses_root_prefix(
    tmp_path: Path, root: str, dest: str, expected: str
) -> None:
    manifest = _manifest(
        tmp_path,
        f'[[artifact]]\nroot = "{root}"\ndest = "{dest}"\npath = "files"\n',
        ("files/setup.md",),
    )

    assert [destination.dest for destination in iter_destinations(manifest)] == [
        PurePosixPath(expected)
    ]


def test_validate_manifest_when_apk_source_is_referenced_no_unused_warning(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "obtainium"\ntype = "github"\n'
        'repo = "ImranR98/Obtainium"\ntag = "v1.7.1"\n'
        'asset = "app-arm64-v8a-release.apk"\n\n'
        '[[apk]]\nsource = "obtainium"\nas = "Obtainium.apk"\n',
    )

    assert validate_manifest(manifest) == []


def test_validate_manifest_when_apk_source_is_unknown_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[apk]]\nsource = "nope"\nas = "Obtainium.apk"\n',
    )

    error = _assert_error(manifest, "unknown-source")

    assert "nope" in error.message


def test_validate_manifest_when_apk_source_destination_is_not_apk_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "obtainium"\ntype = "github"\n'
        'repo = "ImranR98/Obtainium"\ntag = "v1.7.1"\n'
        'asset = "app-arm64-v8a-release.apk"\n\n'
        '[[apk]]\nsource = "obtainium"\nas = "Obtainium.zip"\n',
    )

    _assert_error(manifest, "apk-extension")


def test_iter_destinations_when_apk_source_yields_apks_destination(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[apk]]\nsource = "obtainium"\nas = "Obtainium.apk"\n',
    )

    destinations = list(iter_destinations(manifest))

    assert [destination.dest for destination in destinations] == [
        PurePosixPath("APKs/Obtainium.apk")
    ]
    assert destinations[0].kind == "apk"
    assert destinations[0].src is None


def test_validate_manifest_when_artifact_source_is_referenced_no_unused_warning(
    tmp_path: Path,
) -> None:
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "pack"\ntype = "github"\n'
        'repo = "RJNY/Obtainium-Emulation-Pack"\ntag = "v8.0.1"\n'
        'asset = "obtainium-emulation-pack-v8.0.1.json"\n\n'
        '[[artifact]]\nroot = "card"\ndest = "Obtainium"\n'
        'source = "pack"\nas = "obtainium-emulation-pack-v8.0.1.json"\n',
    )

    assert validate_manifest(manifest) == []


def test_validate_manifest_when_artifact_source_is_unknown_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[artifact]]\nroot = "card"\ndest = "Obtainium"\nsource = "nope"\nas = "pack.json"\n',
    )

    error = _assert_error(manifest, "unknown-source")

    assert "nope" in error.message
    assert "artifact[0]" in error.message


def test_validate_manifest_when_artifact_source_as_is_invalid_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "pack"\ntype = "github"\n'
        'repo = "RJNY/Obtainium-Emulation-Pack"\ntag = "v8.0.1"\n'
        'asset = "pack.json"\n\n'
        '[[artifact]]\nroot = "card"\ndest = "Obtainium"\nsource = "pack"\n'
        'as = "nested/pack.json"\n',
    )

    _assert_error(manifest, "invalid-as")


def test_validate_manifest_when_artifact_source_dest_is_invalid_raises(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "pack"\ntype = "github"\n'
        'repo = "RJNY/Obtainium-Emulation-Pack"\ntag = "v8.0.1"\n'
        'asset = "pack.json"\n\n'
        '[[artifact]]\nroot = "card"\ndest = "../escape"\nsource = "pack"\nas = "pack.json"\n',
    )

    _assert_error(manifest, "invalid-dest")


@pytest.mark.parametrize(
    ("root", "expected"),
    [
        ("card", "Obtainium/pack.json"),
        ("cannoli", "Cannoli/Obtainium/pack.json"),
    ],
)
def test_iter_destinations_when_artifact_source_yields_root_dest_as(
    tmp_path: Path, root: str, expected: str
) -> None:
    manifest = _manifest(
        tmp_path,
        f'[[source]]\nid = "pack"\ntype = "github"\n'
        'repo = "RJNY/Obtainium-Emulation-Pack"\ntag = "v8.0.1"\n'
        'asset = "pack.json"\n\n'
        f'[[artifact]]\nroot = "{root}"\ndest = "Obtainium"\nsource = "pack"\n'
        'as = "pack.json"\n',
    )

    destinations = list(iter_destinations(manifest))

    assert [destination.dest for destination in destinations] == [PurePosixPath(expected)]
    assert destinations[0].kind == "artifact"
    assert destinations[0].src is None
    assert destinations[0].source_root is None


def test_validate_manifest_when_artifact_source_targets_config_warns(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "pack"\ntype = "github"\n'
        'repo = "RJNY/Obtainium-Emulation-Pack"\ntag = "v8.0.1"\n'
        'asset = "pack.json"\n\n'
        '[[artifact]]\nroot = "cannoli"\ndest = "Config"\nsource = "pack"\nas = "pack.json"\n',
    )

    assert "artifact-config" in _codes(manifest)
