from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from sbc_imager import container
from sbc_imager.config import load_manifest
from sbc_imager.errors import VerificationError
from sbc_imager.planner import build_plan
from sbc_imager.sources import SourceCache
from sbc_imager.verify import (
    ActualTree,
    ExpectedTree,
    build_expected,
    compare,
    load_actual_tree,
    verify_image,
)
from tests.fakes import FakeRunner

SETTINGS = "Cannoli/Config/settings.json"
CREDITS = "CREDITS.md"
GBA_ROM = "Cannoli/Roms/GBA/demo.gba"
APK = "APKs/app.apk"

LOCAL = """
[image]
name = "demo"
reserve = "1MiB"

[[artifact]]
root = "cannoli"
dest = "Roms/GBA"
path = "roms"

[[apk]]
path = "apps/app.apk"
"""

LOCAL_FILES = {
    "roms/demo.gba": b"ROMDATA",
    "apps/app.apk": b"APK",
}


def _touch(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _manifest(tmp_path: Path) -> Path:
    for name, data in LOCAL_FILES.items():
        _touch(tmp_path / name, data)
    path = tmp_path / "imager.toml"
    path.write_text(LOCAL, encoding="utf-8")
    return path


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_actual(out_dir: Path, files: dict[str, str], dirs: tuple[str, ...]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = [
        {"dest": dest, "size": 1, "sha256": digest} for dest, digest in sorted(files.items())
    ]
    (out_dir / "tree.json").write_text(json.dumps(payload), encoding="utf-8")
    (out_dir / "tree.dirs.json").write_text(json.dumps(sorted(dirs)), encoding="utf-8")


def _expected(tmp_path: Path) -> tuple[Path, ExpectedTree]:
    manifest_path = _manifest(tmp_path)
    manifest = load_manifest(manifest_path)
    return manifest_path, build_expected(manifest, {})


def _exact(expected: ExpectedTree) -> ActualTree:
    return ActualTree(files=dict(expected.files), dirs=frozenset(expected.required_dirs))


def test_build_expected_when_local_manifest_hashes_files_and_markers(tmp_path: Path) -> None:
    manifest_path, expected = _expected(tmp_path)
    plan = build_plan(load_manifest(manifest_path), {})

    assert expected.files == {
        GBA_ROM: _sha(b"ROMDATA"),
        APK: _sha(b"APK"),
        SETTINGS: _sha(b"{}\n"),
        CREDITS: _sha(plan.credits_marker.content.encode()),
    }
    assert "Cannoli/Roms/GBA" in expected.required_dirs
    assert "Cannoli/Config" in expected.required_dirs
    assert "APKs" in expected.required_dirs
    assert expected.required_dirs == tuple(sorted(expected.required_dirs))


def test_compare_when_tree_is_exact_reports_ok(tmp_path: Path) -> None:
    _, expected = _expected(tmp_path)

    report = compare(expected, _exact(expected))

    assert report.ok is True
    assert report.missing == ()
    assert report.extra == ()
    assert report.mismatched == ()
    assert report.missing_dirs == ()
    assert report.expected_files == len(expected.files)
    assert report.actual_files == len(expected.files)


def test_compare_when_file_is_missing_reports_missing(tmp_path: Path) -> None:
    _, expected = _expected(tmp_path)
    files = dict(expected.files)
    del files[GBA_ROM]

    report = compare(expected, ActualTree(files, frozenset(expected.required_dirs)))

    assert report.ok is False
    assert report.missing == (GBA_ROM,)
    assert report.extra == ()
    assert report.mismatched == ()


def test_compare_when_file_is_extra_reports_extra(tmp_path: Path) -> None:
    _, expected = _expected(tmp_path)
    files = {**expected.files, "Cannoli/Roms/GBA/extra.gba": _sha(b"EXTRA")}

    report = compare(expected, ActualTree(files, frozenset(expected.required_dirs)))

    assert report.ok is False
    assert report.missing == ()
    assert report.extra == ("Cannoli/Roms/GBA/extra.gba",)
    assert report.mismatched == ()


def test_compare_when_hash_differs_reports_mismatched(tmp_path: Path) -> None:
    _, expected = _expected(tmp_path)
    files = {**expected.files, GBA_ROM: _sha(b"TAMPERED")}

    report = compare(expected, ActualTree(files, frozenset(expected.required_dirs)))

    assert report.ok is False
    assert report.missing == ()
    assert report.extra == ()
    assert report.mismatched == (GBA_ROM,)


def test_compare_when_required_dir_is_missing_reports_missing_dirs(tmp_path: Path) -> None:
    _, expected = _expected(tmp_path)
    dirs = frozenset(expected.required_dirs) - {"Cannoli/Roms/GBA"}

    report = compare(expected, ActualTree(dict(expected.files), dirs))

    assert report.ok is False
    assert report.missing_dirs == ("Cannoli/Roms/GBA",)


def test_compare_is_deterministic_and_ok_only_when_everything_matches(tmp_path: Path) -> None:
    _, expected = _expected(tmp_path)
    files = dict(expected.files)
    del files[APK]
    del files[GBA_ROM]
    files["z-extra"] = _sha(b"z")
    files["a-extra"] = _sha(b"a")
    dirs = frozenset(expected.required_dirs) - {"APKs", "Cannoli/Roms/GBA"}

    report = compare(expected, ActualTree(files, dirs))

    assert report.ok is False
    assert report.missing == (APK, GBA_ROM)
    assert report.extra == ("a-extra", "z-extra")
    assert report.missing_dirs == ("APKs", "Cannoli/Roms/GBA")


def test_load_actual_tree_when_files_and_dirs_exist_parses_them(tmp_path: Path) -> None:
    tree_path = tmp_path / "tree.json"
    dirs_path = tmp_path / "tree.dirs.json"
    tree_path.write_text(
        json.dumps(
            [
                {"dest": "b", "size": 2, "sha256": _sha(b"b")},
                {"dest": "a", "size": 1, "sha256": _sha(b"a")},
            ]
        ),
        encoding="utf-8",
    )
    dirs_path.write_text(json.dumps(["Cannoli", "APKs"]), encoding="utf-8")

    actual = load_actual_tree(tree_path, dirs_path)

    assert actual.files == {"a": _sha(b"a"), "b": _sha(b"b")}
    assert actual.dirs == frozenset({"Cannoli", "APKs"})


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        json.dumps({"dest": "a"}),
        json.dumps([{"dest": "a"}]),
        json.dumps([{"dest": "a", "size": 1, "sha256": "zz"}]),
        json.dumps(
            [
                {"dest": "a", "size": 1, "sha256": _sha(b"a")},
                {"dest": "a", "size": 1, "sha256": _sha(b"b")},
            ]
        ),
    ],
)
def test_load_actual_tree_when_tree_is_invalid_raises_verification_error(
    tmp_path: Path, payload: str
) -> None:
    tree_path = tmp_path / "tree.json"
    dirs_path = tmp_path / "tree.dirs.json"
    tree_path.write_text(payload, encoding="utf-8")
    dirs_path.write_text("[]", encoding="utf-8")

    with pytest.raises(VerificationError):
        load_actual_tree(tree_path, dirs_path)


def test_load_actual_tree_when_dirs_are_invalid_raises_verification_error(tmp_path: Path) -> None:
    tree_path = tmp_path / "tree.json"
    dirs_path = tmp_path / "tree.dirs.json"
    tree_path.write_text("[]", encoding="utf-8")
    dirs_path.write_text(json.dumps(["Cannoli", 7]), encoding="utf-8")

    with pytest.raises(VerificationError, match="directory"):
        load_actual_tree(tree_path, dirs_path)


def _fake_container(expected: ExpectedTree, *, returncode: int = 0, extra: bool = False):
    def fake(
        runner: object,
        tag: str,
        image_path: Path,
        out_dir: Path,
        name: str,
        *,
        on_line: object = print,
    ) -> int:
        del runner, tag, image_path, name, on_line
        files = dict(expected.files)
        if extra:
            files["unexpected.txt"] = _sha(b"unexpected")
        _write_actual(out_dir, files, expected.required_dirs)
        return returncode

    return fake


def _run_pipeline(tmp_path: Path):
    manifest_path = tmp_path / "imager.toml"
    image = _touch(tmp_path / "card.img", b"image")
    with httpx.Client() as client:
        return verify_image(
            manifest_path,
            image,
            SourceCache(tmp_path / "cache"),
            FakeRunner(),
            client,
            offline=True,
            allow_branch=False,
            on_line=lambda line: None,
        )


def test_verify_image_when_host_tree_matches_returns_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, expected = _expected(tmp_path)
    monkeypatch.setattr(container, "verify_image", _fake_container(expected))

    report = _run_pipeline(tmp_path)

    assert report.ok is True


def test_verify_image_when_container_tree_has_extra_file_returns_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, expected = _expected(tmp_path)
    monkeypatch.setattr(container, "verify_image", _fake_container(expected, extra=True))

    report = _run_pipeline(tmp_path)

    assert report.ok is False
    assert report.extra == ("unexpected.txt",)


def test_verify_image_when_container_exits_nonzero_raises_verification_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, expected = _expected(tmp_path)
    monkeypatch.setattr(container, "verify_image", _fake_container(expected, returncode=7))

    with pytest.raises(VerificationError, match="exit code 7"):
        _run_pipeline(tmp_path)


def test_verify_image_when_dirs_listing_is_missing_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _manifest(tmp_path)

    def fake(
        runner: object,
        tag: str,
        image_path: Path,
        out_dir: Path,
        name: str,
        *,
        on_line: object = print,
    ) -> int:
        del runner, tag, image_path, name, on_line
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "tree.json").write_text("[]", encoding="utf-8")
        return 0

    monkeypatch.setattr(container, "verify_image", fake)

    with pytest.raises(VerificationError, match="directory"):
        _run_pipeline(tmp_path)
