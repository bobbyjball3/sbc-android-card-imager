from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError
from pathlib import Path

import platformdirs
import pytest

from sbc_imager import sources
from sbc_imager.errors import SourceError
from sbc_imager.sources import ResolvedSource, SourceCache, resolve_local


def test_source_cache_when_env_override_is_set_uses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "custom-cache"
    monkeypatch.setenv("SBC_IMAGER_CACHE_DIR", str(override))

    cache = SourceCache()

    assert cache.root == override.resolve()


def test_source_cache_when_no_override_uses_platform_cache_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SBC_IMAGER_CACHE_DIR", raising=False)

    cache = SourceCache()

    assert cache.root == Path(platformdirs.user_cache_dir("sbc-imager")).resolve()


def test_source_cache_when_explicit_root_uses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SBC_IMAGER_CACHE_DIR", str(tmp_path / "ignored"))

    cache = SourceCache(tmp_path / "explicit")

    assert cache.root == (tmp_path / "explicit").resolve()


def test_key_is_nul_joined_sha256_and_stable() -> None:
    cache = SourceCache()

    expected = hashlib.sha256(b"alpha\x00beta").hexdigest()

    assert cache.key("alpha", "beta") == expected
    assert cache.key("alpha", "beta") == cache.key("alpha", "beta")


def test_key_changes_when_any_part_changes() -> None:
    cache = SourceCache()

    baseline = cache.key("url", "ref", "subdir")

    assert cache.key("url", "ref", "other") != baseline
    assert cache.key("url", "other", "subdir") != baseline
    assert cache.key("other", "ref", "subdir") != baseline
    assert cache.key("url", "ref") != baseline


def test_path_for_when_parts_given_joins_under_key(tmp_path: Path) -> None:
    cache = SourceCache(tmp_path)

    assert cache.path_for("abc123", "nested", "file.bin") == (
        tmp_path.resolve() / "abc123" / "nested" / "file.bin"
    )


def test_write_atomic_when_target_new_writes_exact_bytes_and_no_temp(
    tmp_path: Path,
) -> None:
    cache = SourceCache(tmp_path)
    target = cache.path_for(cache.key("blob"), "blob.bin")
    data = b"\x00exact bytes\xff"

    result = cache.write_atomic(target, data)

    assert result == target
    assert target.read_bytes() == data
    assert list(target.parent.iterdir()) == [target]


def test_write_atomic_when_replace_fails_cleans_temp_and_keeps_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = SourceCache(tmp_path)
    target = cache.path_for(cache.key("blob"), "blob.bin")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"original")

    def fail_replace(_src: Path, _dst: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(sources.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        cache.write_atomic(target, b"replacement")

    assert target.read_bytes() == b"original"
    assert list(target.parent.iterdir()) == [target]


def test_resolve_local_when_file_returns_resolved_file(tmp_path: Path) -> None:
    source_file = tmp_path / "rom.gba"
    source_file.write_bytes(b"rom")

    resolved = resolve_local(source_file)

    assert resolved == ResolvedSource("local", source_file.resolve(), "file", {})
    assert resolved.id == "local"
    assert resolved.kind == "file"
    assert resolved.metadata == {}


def test_resolve_local_when_directory_returns_resolved_directory(tmp_path: Path) -> None:
    source_dir = tmp_path / "roms"
    source_dir.mkdir()

    resolved = resolve_local(source_dir, source_id="assets")

    assert resolved.id == "assets"
    assert resolved.root == source_dir.resolve()
    assert resolved.kind == "directory"


def test_resolve_local_when_missing_raises_source_error_naming_path(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    with pytest.raises(SourceError, match="does-not-exist"):
        resolve_local(missing, source_id="roms")


def test_resolved_source_is_frozen_and_keeps_metadata() -> None:
    resolved = ResolvedSource("id", Path("/tmp/root"), "file", {"license": "CC-BY-4.0"})

    assert resolved.metadata == {"license": "CC-BY-4.0"}
    with pytest.raises(FrozenInstanceError):
        resolved.kind = "directory"  # type: ignore[misc]
