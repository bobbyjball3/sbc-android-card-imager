"""Sparse-file and byte-range helpers for card images."""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
from pathlib import Path

_CHUNK = 8 * 1024 * 1024
_SEEK_UNSUPPORTED = frozenset(
    {errno.EINVAL, errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}
)


def create_sparse(path: Path, size: int) -> Path:
    if size < 0:
        raise ValueError(f"size must be non-negative, got {size}")
    target = Path(path)
    with target.open("wb") as handle:
        handle.truncate(size)
    return target


def copy_sparse(src: Path, dst: Path) -> Path:
    source = Path(src)
    target = Path(dst)
    if not _copy_data_holes(source, target):
        shutil.copyfile(source, target)
    return target


def _copy_data_holes(src: Path, dst: Path) -> bool:
    seek_data = getattr(os, "SEEK_DATA", None)
    seek_hole = getattr(os, "SEEK_HOLE", None)
    if seek_data is None or seek_hole is None:
        return False
    with src.open("rb") as source, dst.open("wb") as target:
        size = os.fstat(source.fileno()).st_size
        target.truncate(size)
        position = 0
        while position < size:
            try:
                data_at = os.lseek(source.fileno(), position, seek_data)
            except OSError as caught:
                if caught.errno == errno.ENXIO:
                    break
                if caught.errno in _SEEK_UNSUPPORTED:
                    return False
                raise
            try:
                hole_at = os.lseek(source.fileno(), data_at, seek_hole)
            except OSError as caught:
                if caught.errno in _SEEK_UNSUPPORTED:
                    return False
                raise
            end = min(hole_at, size)
            source.seek(data_at)
            target.seek(data_at)
            remaining = end - data_at
            while remaining:
                chunk = source.read(min(_CHUNK, remaining))
                if not chunk:
                    raise OSError(f"unexpected end of file while copying {src}")
                target.write(chunk)
                remaining -= len(chunk)
            position = end
        target.flush()
    return True


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_at(path: Path, offset: int, data: bytes) -> None:
    if offset < 0:
        raise ValueError(f"offset must be non-negative, got {offset}")
    target = Path(path)
    with target.open("r+b") as handle:
        size = os.fstat(handle.fileno()).st_size
        if offset + len(data) > size:
            raise ValueError(
                f"write of {len(data)} bytes at offset {offset} exceeds file size {size}"
            )
        if not data:
            return
        handle.seek(offset)
        view = memoryview(data)
        while view:
            written = handle.write(view)
            if written == 0:
                raise OSError(f"could not write to {target}")
            view = view[written:]
        handle.flush()
        os.fsync(handle.fileno())
