from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path

import pytest

from sbc_imager.fs import copy_sparse, create_sparse, sha256_file, write_at

MIB = 1024 * 1024


def test_create_sparse_when_size_given_returns_zeros(tmp_path: Path) -> None:
    path = tmp_path / "card.img"

    result = create_sparse(path, 16 * MIB)

    assert result == path
    assert path.stat().st_size == 16 * MIB
    with path.open("rb") as handle:
        assert handle.read(4096) == bytes(4096)
        handle.seek(-4096, os.SEEK_END)
        assert handle.read(4096) == bytes(4096)


def test_create_sparse_when_size_negative_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_sparse(tmp_path / "card.img", -1)


def test_write_at_when_in_bounds_writes_exact_bytes(tmp_path: Path) -> None:
    path = create_sparse(tmp_path / "card.img", 4096)

    write_at(path, 10, b"hello")

    assert path.stat().st_size == 4096
    with path.open("rb") as handle:
        handle.seek(10)
        assert handle.read(5) == b"hello"


@pytest.mark.parametrize("offset", [-1, 4092])
def test_write_at_when_out_of_bounds_raises(tmp_path: Path, offset: int) -> None:
    path = create_sparse(tmp_path / "card.img", 4096)

    with pytest.raises(ValueError):
        write_at(path, offset, b"12345")

    assert path.read_bytes() == bytes(4096)


def test_sha256_file_when_content_known_returns_digest(tmp_path: Path) -> None:
    path = tmp_path / "data.bin"
    path.write_bytes(b"abc")

    assert sha256_file(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_sha256_file_when_larger_than_one_chunk_returns_digest(tmp_path: Path) -> None:
    data = b"a" * (8 * MIB + 1)
    path = tmp_path / "data.bin"
    path.write_bytes(data)

    assert sha256_file(path) == hashlib.sha256(data).hexdigest()


def _hole_reporting(path: Path) -> bool:
    if not hasattr(os, "SEEK_DATA") or not hasattr(os, "SEEK_HOLE"):
        return False
    with path.open("rb") as handle:
        try:
            return os.lseek(handle.fileno(), 0, os.SEEK_HOLE) < path.stat().st_size
        except OSError:
            return False


def _holey_file(path: Path) -> Path:
    create_sparse(path, 16 * MIB)
    write_at(path, 0, b"start")
    write_at(path, 8 * MIB, b"middle")
    write_at(path, 16 * MIB - 5, b"end!!")
    return path


def test_copy_sparse_when_holes_present_preserves_content(tmp_path: Path) -> None:
    src = _holey_file(tmp_path / "src.img")
    dst = tmp_path / "dst.img"

    result = copy_sparse(src, dst)

    assert result == dst
    assert dst.stat().st_size == 16 * MIB
    with dst.open("rb") as handle:
        assert handle.read(5) == b"start"
        handle.seek(8 * MIB)
        assert handle.read(6) == b"middle"
        handle.seek(8 * MIB + 6)
        assert handle.read(1024) == bytes(1024)
        handle.seek(-5, os.SEEK_END)
        assert handle.read() == b"end!!"


def test_copy_sparse_when_seek_data_reports_extents_writes_at_same_offsets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extents = ((0, 5), (8 * MIB, 8 * MIB + 6), (16 * MIB - 5, 16 * MIB))
    src = create_sparse(tmp_path / "src.img", 16 * MIB)
    write_at(src, 0, b"hello")
    write_at(src, 8 * MIB, b"world!")
    write_at(src, 16 * MIB - 5, b"end!!")
    dst = tmp_path / "dst.img"
    seek_data = getattr(os, "SEEK_DATA", 0x1001)
    seek_hole = getattr(os, "SEEK_HOLE", 0x1002)
    real_lseek = os.lseek

    def synthetic_lseek(fd: int, offset: int, whence: int) -> int:
        if whence == seek_data:
            for start, _ in extents:
                if start >= offset:
                    return start
            raise OSError(errno.ENXIO, "no more data")
        if whence == seek_hole:
            for start, end in extents:
                if start <= offset < end:
                    return end
            return offset
        return real_lseek(fd, offset, whence)

    monkeypatch.setattr(os, "SEEK_DATA", seek_data, raising=False)
    monkeypatch.setattr(os, "SEEK_HOLE", seek_hole, raising=False)
    monkeypatch.setattr(os, "lseek", synthetic_lseek)

    copy_sparse(src, dst)

    assert dst.stat().st_size == 16 * MIB
    with dst.open("rb") as handle:
        assert handle.read(5) == b"hello"
        handle.seek(8 * MIB)
        assert handle.read(6) == b"world!"
        handle.seek(16 * MIB - 5)
        assert handle.read(5) == b"end!!"
        handle.seek(8 * MIB + 6)
        assert handle.read(16) == bytes(16)
    assert sha256_file(dst) == sha256_file(src)


def test_copy_sparse_when_filesystem_reports_holes_allocates_less(tmp_path: Path) -> None:
    src = _holey_file(tmp_path / "src.img")
    dst = tmp_path / "dst.img"

    copy_sparse(src, dst)

    if not _hole_reporting(src):
        pytest.skip("filesystem does not report sparse holes")
    assert dst.stat().st_blocks * 512 < dst.stat().st_size


def test_copy_sparse_when_seek_data_unavailable_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _holey_file(tmp_path / "src.img")
    dst = tmp_path / "dst.img"
    monkeypatch.delattr(os, "SEEK_DATA", raising=False)

    copy_sparse(src, dst)

    assert dst.stat().st_size == src.stat().st_size
    assert sha256_file(dst) == sha256_file(src)
