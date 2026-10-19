"""Per-entry validation rules for manifests."""

from __future__ import annotations

from pathlib import PurePosixPath

from sbc_imager.cannoli import PC_SHORTCUT_EXTENSIONS
from sbc_imager.config import Manifest, OverlayEntry, ShaderEntry
from sbc_imager.validation_common import Warning, error, tag
from sbc_imager.validation_destinations import component, relative_dir, source_relative_path
from sbc_imager.validation_exfat import check_component, nfc
from sbc_imager.validation_local import IMAGE_SUFFIXES, check_local, entry_files, is_rom_junk


def check_overlay(entry: OverlayEntry, index: int, warnings: list[Warning]) -> int:
    where = f"overlay[{index}]"
    if entry.source is not None:
        relative = source_relative_path(entry.path, where)
        name = component(entry.as_, where) if entry.as_ else relative.name
        check_component(name)
        if relative.suffix and relative.suffix.casefold() != ".png":
            error("overlay-extension", f"{where} overlay {entry.path} is not a .png file")
        if relative.suffix.casefold() == ".png" and (
            PurePosixPath(name).suffix.casefold() != ".png"
        ):
            error("overlay-extension", f"{where} destination {name!r} is not a .png file")
        return 0
    check_local(where, entry.path)
    files = entry_files(entry.path)
    if entry.path.is_file():
        name = component(entry.as_, where) if entry.as_ else entry.path.name
        check_component(name)
        if PurePosixPath(name).suffix.casefold() != ".png":
            error("overlay-extension", f"{where} destination {name!r} is not a .png file")
        return entry.path.stat().st_size
    if entry.as_ is not None:
        component(entry.as_, where)
    for _, rel in files:
        if rel.suffix.casefold() != ".png":
            warnings.append(
                Warning("overlay-non-png", f"{where} skips non-PNG {rel.as_posix()}", index)
            )
    pngs = [(path, rel) for path, rel in files if rel.suffix.casefold() == ".png"]
    if not pngs:
        error("empty-entry", f"{where} produces no .png files")
    return sum(path.stat().st_size for path, _ in pngs)


def check_shader(entry: ShaderEntry, index: int) -> int:
    where = f"shader[{index}]"
    if entry.source is not None:
        relative = source_relative_path(entry.path, where)
        name = component(entry.as_, where) if entry.as_ else relative.name
        check_component(name)
        if relative.suffix and relative.suffix.casefold() != ".glslp":
            error("shader-extension", f"{where} shader {entry.path} is not a .glslp file")
        if relative.suffix.casefold() == ".glslp" and (
            PurePosixPath(name).suffix.casefold() != ".glslp"
        ):
            error("shader-extension", f"{where} destination {name!r} is not a .glslp file")
        return 0
    check_local(where, entry.path)
    files = entry_files(entry.path)
    if entry.path.is_file():
        name = component(entry.as_, where) if entry.as_ else entry.path.name
        check_component(name)
        if PurePosixPath(name).suffix.casefold() != ".glslp":
            error("shader-extension", f"{where} destination {name!r} is not a .glslp file")
    else:
        if entry.as_ is not None:
            component(entry.as_, where)
        if not any(
            child.is_file() and child.suffix.casefold() == ".glslp"
            for child in entry.path.iterdir()
        ):
            error("shader-root-preset", f"{where} directory {entry.path} has no root .glslp preset")
    if not files:
        error("empty-entry", f"{where} produces no files")
    return sum(path.stat().st_size for path, _ in files)


def check_roms(manifest: Manifest, warnings: list[Warning]) -> tuple[int, set[str]]:
    total = 0
    stems: set[str] = set()
    for index, entry in enumerate(manifest.roms):
        platform = tag(entry.platform, f"rom[{index}]")
        check_local(f"rom[{index}]", entry.path)
        files = entry_files(entry.path, entry.include, entry.exclude)
        usable = []
        for path, rel in files:
            if is_rom_junk(rel.name, platform):
                warnings.append(
                    Warning(
                        "junk-rom-file", f"rom[{index}] ignores junk file {rel.as_posix()}", index
                    )
                )
                continue
            usable.append((path, rel))
            if platform == "PC" and rel.suffix.casefold() not in PC_SHORTCUT_EXTENSIONS:
                error(
                    "pc-extension",
                    f"rom[{index}] PC file {rel.as_posix()} is not a supported shortcut file",
                )
            stems.add(nfc(rel.stem).casefold())
            total += path.stat().st_size
        if not usable:
            error("empty-entry", f"rom[{index}] produces no files")
    return total, stems


def check_bios(manifest: Manifest) -> tuple[int, dict[str, set[str]], dict[str, int]]:
    total = 0
    relative: dict[str, set[str]] = {}
    indexes: dict[str, int] = {}
    for index, entry in enumerate(manifest.bios):
        platform = tag(entry.platform, f"bios[{index}]")
        where = f"bios[{index}]"
        check_local(where, entry.path)
        files = entry_files(entry.path)
        if not files:
            error("empty-entry", f"{where} produces no files")
        as_name = component(entry.as_, where) if entry.as_ is not None else None
        for path, rel in files:
            if entry.path.is_file() and as_name is not None:
                rel = PurePosixPath(as_name)
            relative.setdefault(platform, set()).add(rel.as_posix().casefold())
            total += path.stat().st_size
        indexes.setdefault(platform, index)
    return total, relative, indexes


def check_art(manifest: Manifest, warnings: list[Warning], rom_stems: set[str]) -> int:
    total = 0
    for index, entry in enumerate(manifest.art):
        tag(entry.platform, f"art[{index}]")
        check_local(f"art[{index}]", entry.path)
        files = entry_files(entry.path, entry.include, entry.exclude)
        for path, rel in files:
            if rel.suffix.casefold() not in IMAGE_SUFFIXES:
                error("art-extension", f"art[{index}] file {rel.as_posix()} is not an image")
            if nfc(rel.stem).casefold() not in rom_stems:
                warnings.append(
                    Warning(
                        "art-no-rom",
                        f"art[{index}] {rel.as_posix()} has no matching ROM basename",
                        index,
                    )
                )
            total += path.stat().st_size
        if not files:
            error("empty-entry", f"art[{index}] produces no files")
    return total


def check_apks(manifest: Manifest) -> int:
    total = 0
    for index, entry in enumerate(manifest.apks):
        where = f"apk[{index}]"
        check_local(where, entry.path)
        files = entry_files(entry.path)
        if entry.path.is_file():
            name = component(entry.as_, where) if entry.as_ else entry.path.name
            check_component(name)
            if PurePosixPath(name).suffix.casefold() != ".apk":
                error("apk-extension", f"{where} destination {name!r} is not a .apk file")
        elif entry.as_ is not None:
            component(entry.as_, where)
        for path, rel in files:
            if not entry.path.is_file() and rel.suffix.casefold() != ".apk":
                error("apk-extension", f"{where} file {rel.as_posix()} is not a .apk file")
            total += path.stat().st_size
        if not files:
            error("empty-entry", f"{where} produces no files")
    return total


def check_artifacts(manifest: Manifest, warnings: list[Warning]) -> int:
    total = 0
    for index, entry in enumerate(manifest.artifacts):
        where = f"artifact[{index}]"
        root = entry.root.casefold()
        if root not in {"card", "cannoli"}:
            error("artifact-root", f"{where} root must be 'card' or 'cannoli'")
        relative_dir(entry.dest, where)
        if entry.as_ is not None:
            component(entry.as_, where)
        check_local(where, entry.path)
        files = entry_files(entry.path)
        if not files:
            error("empty-entry", f"{where} produces no files")
        parts = PurePosixPath(entry.dest).parts
        if parts and parts[0].casefold() == "config":
            warnings.append(Warning("artifact-config", f"{where} writes into Config/", index))
        total += sum(path.stat().st_size for path, _ in files)
    return total


def check_sources(manifest: Manifest) -> tuple[dict[str, int], set[str]]:
    sources = {source.id: index for index, source in enumerate(manifest.sources)}
    referenced: set[str] = set()
    for index, source in enumerate(manifest.sources):
        if source.type.casefold() not in {"git", "http", "https", "url"}:
            continue
        missing = [name for name in ("license", "attribution") if not getattr(source, name)]
        if missing:
            error("source-metadata", f"source[{index}] '{source.id}' requires {', '.join(missing)}")
    for kind, entries in (("overlay", manifest.overlays), ("shader", manifest.shaders)):
        for index, entry in enumerate(entries):
            if entry.source is None:
                continue
            if entry.source not in sources:
                error(
                    "unknown-source",
                    f"{kind}[{index}] references unknown source {entry.source!r}",
                )
            referenced.add(entry.source)
    return sources, referenced
