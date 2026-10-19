"""Local source-tree walking, filtering, and safety checks."""

from __future__ import annotations

import fnmatch
import os
import stat
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from sbc_imager.validation_common import error

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})
_ROM_JUNK_NAMES = frozenset({"thumbs.db", "desktop.ini"})


def is_hidden(name: str) -> bool:
    return name.startswith(".")


def is_rom_junk(name: str, tag: str) -> bool:
    suffix = PurePosixPath(name).suffix.casefold()
    if name.casefold() in _ROM_JUNK_NAMES:
        return True
    return suffix == ".md" or suffix in IMAGE_SUFFIXES or (suffix == ".txt" and tag != "PC")


def _matches(rel: PurePosixPath, pattern: str) -> bool:
    name = rel.as_posix()
    return fnmatch.fnmatchcase(name, pattern) or (
        pattern.startswith("**/") and fnmatch.fnmatchcase(name, pattern[3:])
    )


def _selected(rel: PurePosixPath, include: Iterable[str], exclude: Iterable[str]) -> bool:
    return any(_matches(rel, pattern) for pattern in include) and not any(
        _matches(rel, pattern) for pattern in exclude
    )


def entry_files(
    root: Path, include: Iterable[str] = ("**/*",), exclude: Iterable[str] = ()
) -> list[tuple[Path, PurePosixPath]]:
    include = tuple(include)
    exclude = tuple(exclude)
    if root.is_file():
        rel = PurePosixPath(root.name)
        return [(root, rel)] if _selected(rel, include, exclude) else []
    if not root.is_dir():
        return []
    found: list[tuple[Path, PurePosixPath]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if not is_hidden(name)]
        for name in filenames:
            if is_hidden(name):
                continue
            path = Path(dirpath) / name
            rel = PurePosixPath(path.relative_to(root).as_posix())
            if _selected(rel, include, exclude):
                found.append((path, rel))
    found.sort(key=lambda item: item[1].as_posix())
    return found


def check_local(where: str, root: Path) -> None:
    if root.is_symlink():
        error("symlink", f"{where} is a symlink")
    try:
        mode = root.lstat().st_mode
    except OSError:
        error("missing-path", f"{where} does not exist: {root}")
    if stat.S_ISREG(mode):
        return
    if not stat.S_ISDIR(mode):
        error("special-file", f"{where} is not a regular file or directory: {root}")
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in (*dirnames, *filenames):
            path = Path(dirpath) / name
            if path.is_symlink():
                error("symlink", f"{where} contains symlink {path}")
            child = path.lstat().st_mode
            if not (stat.S_ISREG(child) or stat.S_ISDIR(child)):
                error("special-file", f"{where} contains special file {path}")
