"""Semantic validation of manifests against Cannoli and exFAT rules.

The size parser here is intentionally small; todo 13 introduces ``sizes.py`` and
will consolidate the implementation.
"""

# allow: SIZE_OK - task 8 restricts its commit to this single module, so the
# Cannoli/exFAT rule set cannot be split across helper modules yet.

from __future__ import annotations

import fnmatch
import os
import re
import stat
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Never

from sbc_imager.cannoli import (
    HARD_REQUIRED_BIOS,
    PC_SHORTCUT_EXTENSIONS,
    apks_dir,
    art_dir,
    bios_dir,
    normalize_tag,
    overlays_dir,
    rom_dir,
    shaders_dir,
)
from sbc_imager.config import (
    ImageConfig,
    Manifest,
    OverlayEntry,
    ShaderEntry,
)
from sbc_imager.errors import ConfigError

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})
_ROM_JUNK_NAMES = frozenset({"thumbs.db", "desktop.ini"})
_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)
_EXFAT_FORBIDDEN = frozenset('\\:*?"<>|')
_RESERVED_DESTINATIONS = frozenset({("cannoli", "config", "settings.json"), ("credits.md",)})
_MIB = 1024 * 1024
_SIZE_RE = re.compile(r"^(\d+(?:\.\d{1,3})?)\s*([KMGT]iB|B|bytes?)?$", re.IGNORECASE)
_UNITS = {"kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4, "b": 1, "bytes": 1}


@dataclass(frozen=True, slots=True)
class Warning:
    code: str
    message: str
    entry_index: int | None = None


@dataclass(frozen=True, slots=True)
class Destination:
    dest: PurePosixPath
    entry_index: int
    kind: str
    source_root: Path | None = None


def _error(code: str, detail: str) -> Never:
    raise ConfigError(f"{code}: {detail}")


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _parse_size(value: str) -> int:
    match = _SIZE_RE.fullmatch(value.strip())
    if match is None:
        _error("invalid-size", f"unsupported size {value!r}")
    try:
        amount = Decimal(match.group(1)) * _UNITS[(match.group(2) or "B").casefold()]
    except (KeyError, InvalidOperation):
        _error("invalid-size", f"unsupported size {value!r}")
    if amount < 0 or amount != amount.to_integral_value():
        _error("invalid-size", f"size {value!r} must be a whole, non-negative number of bytes")
    return int(amount)


def _tag(value: str, where: str) -> str:
    try:
        return normalize_tag(value)
    except ConfigError as error:
        raise ConfigError(
            f"unknown-platform: {where} uses unknown platform tag {value!r}",
            error.hint,
        ) from error


def _is_hidden(name: str) -> bool:
    return name.startswith(".")


def _is_rom_junk(name: str, tag: str) -> bool:
    suffix = PurePosixPath(name).suffix.casefold()
    if name.casefold() in _ROM_JUNK_NAMES:
        return True
    return suffix == ".md" or suffix in _IMAGE_SUFFIXES or (suffix == ".txt" and tag != "PC")


def _matches(rel: PurePosixPath, pattern: str) -> bool:
    name = rel.as_posix()
    return fnmatch.fnmatchcase(name, pattern) or (
        pattern.startswith("**/") and fnmatch.fnmatchcase(name, pattern[3:])
    )


def _selected(rel: PurePosixPath, include: Iterable[str], exclude: Iterable[str]) -> bool:
    return any(_matches(rel, pattern) for pattern in include) and not any(
        _matches(rel, pattern) for pattern in exclude
    )


def _entry_files(
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
        dirnames[:] = [name for name in dirnames if not _is_hidden(name)]
        for name in filenames:
            if _is_hidden(name):
                continue
            path = Path(dirpath) / name
            rel = PurePosixPath(path.relative_to(root).as_posix())
            if _selected(rel, include, exclude):
                found.append((path, rel))
    found.sort(key=lambda item: item[1].as_posix())
    return found


def _walk_checked(root: Path, where: str) -> None:
    if root.is_symlink():
        _error("symlink", f"{where} is a symlink")
    try:
        mode = root.lstat().st_mode
    except OSError:
        _error("missing-path", f"{where} does not exist: {root}")
    if stat.S_ISREG(mode):
        return
    if not stat.S_ISDIR(mode):
        _error("special-file", f"{where} is not a regular file or directory: {root}")
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in (*dirnames, *filenames):
            path = Path(dirpath) / name
            if path.is_symlink():
                _error("symlink", f"{where} contains symlink {path}")
            child = path.lstat().st_mode
            if not (stat.S_ISREG(child) or stat.S_ISDIR(child)):
                _error("special-file", f"{where} contains special file {path}")


def _check_local(where: str, root: Path) -> None:
    _walk_checked(root, where)


def _source_relative(entry: OverlayEntry | ShaderEntry, where: str) -> PurePosixPath:
    relative = PurePosixPath(entry.path.as_posix())
    if relative.is_absolute() or ".." in relative.parts:
        _error("source-path", f"{where} source-relative path must stay inside the source")
    return relative


def _rom_destinations(manifest: Manifest) -> Iterator[Destination]:
    for index, entry in enumerate(manifest.roms):
        tag = _tag(entry.platform, f"rom[{index}]")
        for _, rel in _entry_files(entry.path, entry.include, entry.exclude):
            if not _is_rom_junk(rel.name, tag):
                yield Destination(rom_dir(tag) / rel, index, "rom", entry.path)


def _bios_destinations(manifest: Manifest) -> Iterator[Destination]:
    for index, entry in enumerate(manifest.bios):
        tag = _tag(entry.platform, f"bios[{index}]")
        for _, rel in _entry_files(entry.path):
            if entry.as_ is not None and entry.path.is_file():
                rel = PurePosixPath(entry.as_)
            yield Destination(bios_dir(tag) / rel, index, "bios", entry.path)


def _art_destinations(manifest: Manifest) -> Iterator[Destination]:
    for index, entry in enumerate(manifest.art):
        tag = _tag(entry.platform, f"art[{index}]")
        for _, rel in _entry_files(entry.path, entry.include, entry.exclude):
            yield Destination(art_dir(tag) / rel, index, "art", entry.path)


def _overlay_destinations(manifest: Manifest) -> Iterator[Destination]:
    for index, entry in enumerate(manifest.overlays):
        tag = _tag(entry.platform, f"overlay[{index}]")
        base = overlays_dir(tag)
        if entry.source is not None:
            yield Destination(
                base / (entry.as_ or _source_relative(entry, f"overlay[{index}]")),
                index,
                "overlay",
                entry.path,
            )
        elif entry.path.is_file():
            name = entry.as_ or entry.path.name
            if name.casefold().endswith(".png"):
                yield Destination(base / name, index, "overlay", entry.path)
        else:
            prefix = PurePosixPath(entry.as_) if entry.as_ else PurePosixPath()
            for _, rel in _entry_files(entry.path):
                if rel.suffix.casefold() == ".png":
                    yield Destination(base / prefix / rel, index, "overlay", entry.path)


def _shader_destinations(manifest: Manifest) -> Iterator[Destination]:
    for index, entry in enumerate(manifest.shaders):
        if entry.source is not None:
            yield Destination(
                shaders_dir() / (entry.as_ or _source_relative(entry, f"shader[{index}]")),
                index,
                "shader",
                entry.path,
            )
        elif entry.path.is_file():
            yield Destination(
                shaders_dir() / entry.path.stem / (entry.as_ or entry.path.name),
                index,
                "shader",
                entry.path,
            )
        else:
            preset = entry.as_ or entry.path.name
            for _, rel in _entry_files(entry.path):
                yield Destination(shaders_dir() / preset / rel, index, "shader", entry.path)


def _apk_destinations(manifest: Manifest) -> Iterator[Destination]:
    for index, entry in enumerate(manifest.apks):
        if entry.path.is_file():
            yield Destination(apks_dir() / (entry.as_ or entry.path.name), index, "apk", entry.path)
        else:
            prefix = PurePosixPath(entry.as_) if entry.as_ else PurePosixPath()
            for _, rel in _entry_files(entry.path):
                yield Destination(apks_dir() / prefix / rel, index, "apk", entry.path)


def _artifact_destinations(manifest: Manifest) -> Iterator[Destination]:
    for index, entry in enumerate(manifest.artifacts):
        root = entry.root.casefold()
        if root not in {"card", "cannoli"}:
            _error("artifact-root", f"artifact[{index}] root must be 'card' or 'cannoli'")
        base = (PurePosixPath("Cannoli") if root == "cannoli" else PurePosixPath()) / PurePosixPath(
            entry.dest
        )
        if entry.path.is_file():
            yield Destination(base / (entry.as_ or entry.path.name), index, "artifact", entry.path)
        else:
            for _, rel in _entry_files(entry.path):
                yield Destination(base / rel, index, "artifact", entry.path)


def iter_destinations(manifest: Manifest) -> Iterator[Destination]:
    """Yield every card-relative file destination produced by a manifest."""
    yield from _rom_destinations(manifest)
    yield from _bios_destinations(manifest)
    yield from _art_destinations(manifest)
    yield from _overlay_destinations(manifest)
    yield from _shader_destinations(manifest)
    yield from _apk_destinations(manifest)
    yield from _artifact_destinations(manifest)


def _check_component(part: str) -> None:
    if not part or part in {".", ".."}:
        _error("exfat-name", f"invalid destination component {part!r}")
    if any(character in _EXFAT_FORBIDDEN or ord(character) < 32 for character in part):
        _error(
            "exfat-name", f"destination component {part!r} contains an exFAT-forbidden character"
        )
    if part[-1] in ". ":
        _error("exfat-name", f"destination component {part!r} ends with a dot or space")
    stem = part.split(".")[0].upper()
    if stem in _RESERVED_NAMES or re.fullmatch(r"(?:COM|LPT)[1-9]", stem):
        _error("exfat-name", f"destination component {part!r} uses a reserved exFAT name")
    if len(part) > 255:
        _error("exfat-name", f"destination component {part!r} exceeds 255 characters")


def _check_destinations(destinations: list[Destination], warnings: list[Warning]) -> None:
    exact: dict[str, str] = {}
    normalized: dict[tuple[str, ...], str] = {}
    warned: set[str] = set()
    for destination in destinations:
        parts = destination.dest.parts
        for part in parts:
            _check_component(part)
            if _nfc(part) != part and part not in warned:
                warned.add(part)
                warnings.append(
                    Warning(
                        "non-nfc-name",
                        f"destination name {part!r} is not Unicode NFC",
                        destination.entry_index,
                    )
                )
        raw = destination.dest.as_posix()
        key = tuple(_nfc(part).casefold() for part in parts)
        owner = f"{destination.kind}[{destination.entry_index}]"
        if raw in exact:
            _error("duplicate-destination", f"{raw!r} is produced by {exact[raw]} and {owner}")
        if key in normalized:
            _error(
                "destination-collision",
                f"{raw!r} collides with {normalized[key]!r} after NFC and case folding",
            )
        if key in _RESERVED_DESTINATIONS:
            _error("reserved-destination", f"{raw!r} is reserved by Cannoli")
        exact[raw] = owner
        normalized[key] = raw


def _check_image(image: ImageConfig) -> int | None:
    if len(image.label) > 11:
        _error("label-too-long", f"image.label {image.label!r} exceeds the 11-character limit")
    pinned = None if image.size.strip().casefold() == "auto" else _parse_size(image.size)
    _parse_size(image.reserve)
    return pinned


def _check_overlay(entry: OverlayEntry, index: int, warnings: list[Warning]) -> int:
    where = f"overlay[{index}]"
    if entry.source is not None:
        suffix = _source_relative(entry, where).suffix.casefold()
        if suffix and suffix != ".png":
            _error("overlay-extension", f"{where} overlay {entry.path} is not a .png file")
        return 0
    _check_local(where, entry.path)
    files = _entry_files(entry.path)
    if entry.path.is_file():
        if entry.path.suffix.casefold() != ".png":
            _error("overlay-extension", f"{where} overlay {entry.path} is not a .png file")
        return entry.path.stat().st_size
    for _path, rel in files:
        if rel.suffix.casefold() != ".png":
            warnings.append(
                Warning("overlay-non-png", f"{where} skips non-PNG {rel.as_posix()}", index)
            )
    pngs = [(path, rel) for path, rel in files if rel.suffix.casefold() == ".png"]
    if not pngs:
        _error("empty-entry", f"{where} produces no .png files")
    return sum(path.stat().st_size for path, _ in pngs)


def _check_shader(entry: ShaderEntry, index: int) -> int:
    where = f"shader[{index}]"
    if entry.source is not None:
        suffix = _source_relative(entry, where).suffix.casefold()
        if suffix and suffix != ".glslp":
            _error("shader-extension", f"{where} shader {entry.path} is not a .glslp file")
        return 0
    _check_local(where, entry.path)
    files = _entry_files(entry.path)
    if entry.path.is_file():
        if entry.path.suffix.casefold() != ".glslp":
            _error("shader-extension", f"{where} shader {entry.path} is not a .glslp file")
    elif not any(
        child.is_file() and child.suffix.casefold() == ".glslp" for child in entry.path.iterdir()
    ):
        _error("shader-root-preset", f"{where} directory {entry.path} has no root .glslp preset")
    if not files:
        _error("empty-entry", f"{where} produces no files")
    return sum(path.stat().st_size for path, _ in files)


def _check_roms(manifest: Manifest, warnings: list[Warning]) -> tuple[int, set[str]]:
    total = 0
    stems: set[str] = set()
    for index, entry in enumerate(manifest.roms):
        tag = _tag(entry.platform, f"rom[{index}]")
        _check_local(f"rom[{index}]", entry.path)
        files = _entry_files(entry.path, entry.include, entry.exclude)
        usable = []
        for path, rel in files:
            if _is_rom_junk(rel.name, tag):
                warnings.append(
                    Warning(
                        "junk-rom-file", f"rom[{index}] ignores junk file {rel.as_posix()}", index
                    )
                )
                continue
            usable.append((path, rel))
            if tag == "PC" and rel.suffix.casefold() not in PC_SHORTCUT_EXTENSIONS:
                _error(
                    "pc-extension",
                    f"rom[{index}] PC file {rel.as_posix()} is not a supported shortcut file",
                )
            stems.add(_nfc(rel.stem).casefold())
            total += path.stat().st_size
        if not usable:
            _error("empty-entry", f"rom[{index}] produces no files")
    return total, stems


def _check_bios(manifest: Manifest) -> tuple[int, dict[str, set[str]], dict[str, int]]:
    total = 0
    relative: dict[str, set[str]] = {}
    indexes: dict[str, int] = {}
    for index, entry in enumerate(manifest.bios):
        tag = _tag(entry.platform, f"bios[{index}]")
        _check_local(f"bios[{index}]", entry.path)
        files = _entry_files(entry.path)
        if not files:
            _error("empty-entry", f"bios[{index}] produces no files")
        for path, rel in files:
            if entry.as_ is not None and entry.path.is_file():
                rel = PurePosixPath(entry.as_)
            relative.setdefault(tag, set()).add(rel.as_posix().casefold())
            total += path.stat().st_size
        indexes.setdefault(tag, index)
    return total, relative, indexes


def _check_art(manifest: Manifest, warnings: list[Warning], rom_stems: set[str]) -> int:
    total = 0
    for index, entry in enumerate(manifest.art):
        _tag(entry.platform, f"art[{index}]")
        _check_local(f"art[{index}]", entry.path)
        files = _entry_files(entry.path, entry.include, entry.exclude)
        for path, rel in files:
            if rel.suffix.casefold() not in _IMAGE_SUFFIXES:
                _error("art-extension", f"art[{index}] file {rel.as_posix()} is not an image")
            if _nfc(rel.stem).casefold() not in rom_stems:
                warnings.append(
                    Warning(
                        "art-no-rom",
                        f"art[{index}] {rel.as_posix()} has no matching ROM basename",
                        index,
                    )
                )
            total += path.stat().st_size
        if not files:
            _error("empty-entry", f"art[{index}] produces no files")
    return total


def _check_apks(manifest: Manifest) -> int:
    total = 0
    for index, entry in enumerate(manifest.apks):
        _check_local(f"apk[{index}]", entry.path)
        files = _entry_files(entry.path)
        for path, rel in files:
            if rel.suffix.casefold() != ".apk":
                _error("apk-extension", f"apk[{index}] file {rel.as_posix()} is not a .apk file")
            total += path.stat().st_size
        if not files:
            _error("empty-entry", f"apk[{index}] produces no files")
    return total


def _check_artifacts(manifest: Manifest, warnings: list[Warning]) -> int:
    total = 0
    for index, entry in enumerate(manifest.artifacts):
        root = entry.root.casefold()
        if root not in {"card", "cannoli"}:
            _error("artifact-root", f"artifact[{index}] root must be 'card' or 'cannoli'")
        _check_local(f"artifact[{index}]", entry.path)
        files = _entry_files(entry.path)
        if not files:
            _error("empty-entry", f"artifact[{index}] produces no files")
        parts = PurePosixPath(entry.dest).parts
        if parts and parts[0].casefold() == "config":
            warnings.append(
                Warning("artifact-config", f"artifact[{index}] writes into Config/", index)
            )
        total += sum(path.stat().st_size for path, _ in files)
    return total


def _check_sources(manifest: Manifest) -> tuple[dict[str, int], set[str]]:
    sources = {source.id: index for index, source in enumerate(manifest.sources)}
    referenced: set[str] = set()
    for index, source in enumerate(manifest.sources):
        if source.type.casefold() not in {"git", "http", "https", "url"}:
            continue
        missing = [name for name in ("license", "attribution") if not getattr(source, name)]
        if missing:
            _error(
                "source-metadata",
                f"source[{index}] '{source.id}' requires {', '.join(missing)}",
            )
    for kind, entries in (("overlay", manifest.overlays), ("shader", manifest.shaders)):
        for index, entry in enumerate(entries):
            if entry.source is None:
                continue
            if entry.source not in sources:
                _error(
                    "unknown-source",
                    f"{kind}[{index}] references unknown source {entry.source!r}",
                )
            referenced.add(entry.source)
    return sources, referenced


def validate_manifest(manifest: Manifest) -> list[Warning]:
    """Raise ``ConfigError`` for invalid manifests; return non-fatal warnings."""
    warnings: list[Warning] = []
    pinned_size = _check_image(manifest.image)
    sources, referenced = _check_sources(manifest)
    total = 0
    for index, entry in enumerate(manifest.overlays):
        total += _check_overlay(entry, index, warnings)
    for index, entry in enumerate(manifest.shaders):
        total += _check_shader(entry, index)
    rom_total, rom_stems = _check_roms(manifest, warnings)
    bios_total, bios_relative, bios_indexes = _check_bios(manifest)
    total += rom_total + bios_total
    total += _check_art(manifest, warnings, rom_stems)
    total += _check_apks(manifest)
    total += _check_artifacts(manifest, warnings)

    declared = {
        _tag(entry.platform, f"rom[{index}]"): index for index, entry in enumerate(manifest.roms)
    }
    for tag, index in declared.items():
        missing = [
            name
            for name in HARD_REQUIRED_BIOS.get(tag, ())
            if name.casefold() not in bios_relative.get(tag, set())
        ]
        if missing:
            warnings.append(
                Warning(
                    "missing-required-bios",
                    f"{tag} ROM requires BIOS {', '.join(missing)}; none is declared",
                    bios_indexes.get(tag, index),
                )
            )
    for source_id, index in sources.items():
        if source_id not in referenced:
            warnings.append(
                Warning("unused-source", f"source[{index}] '{source_id}' is not referenced", index)
            )

    destinations = list(iter_destinations(manifest))
    _check_destinations(destinations, warnings)
    if pinned_size is not None:
        overhead = max(64 * _MIB, (total + 99) // 100)
        if total + overhead > pinned_size:
            _error(
                "content-overflow",
                f"local content {total} + overhead {overhead} exceeds pinned size {pinned_size}",
            )
    return warnings
