"""Per-entry validation rules for manifests."""

from __future__ import annotations

from pathlib import PurePosixPath

from sbc_imager.config import Manifest, OverlayEntry, ShaderEntry
from sbc_imager.validation_common import Warning, error
from sbc_imager.validation_destinations import component, relative_dir, source_relative_path
from sbc_imager.validation_exfat import check_component
from sbc_imager.validation_local import check_local, entry_files


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


def check_apks(manifest: Manifest) -> int:
    total = 0
    for index, entry in enumerate(manifest.apks):
        where = f"apk[{index}]"
        if entry.source is not None:
            name = component(entry.as_ or "", where)
            check_component(name)
            if PurePosixPath(name).suffix.casefold() != ".apk":
                error("apk-extension", f"{where} destination {name!r} is not a .apk file")
            continue
        path = entry.path
        if path is None:
            error("missing-path", f"{where} has no local path")
        check_local(where, path)
        files = entry_files(path)
        if path.is_file():
            name = component(entry.as_, where) if entry.as_ else path.name
            check_component(name)
            if PurePosixPath(name).suffix.casefold() != ".apk":
                error("apk-extension", f"{where} destination {name!r} is not a .apk file")
        elif entry.as_ is not None:
            component(entry.as_, where)
        for child, rel in files:
            if not path.is_file() and rel.suffix.casefold() != ".apk":
                error("apk-extension", f"{where} file {rel.as_posix()} is not a .apk file")
            total += child.stat().st_size
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
        parts = PurePosixPath(entry.dest).parts
        if parts and parts[0].casefold() == "config":
            warnings.append(Warning("artifact-config", f"{where} writes into Config/", index))
        if entry.source is not None:
            component(entry.as_ or "", where)
            continue
        path = entry.path
        if path is None:
            error("missing-path", f"{where} has no local path")
        if entry.as_ is not None:
            component(entry.as_, where)
        check_local(where, path)
        files = entry_files(path)
        if not files:
            error("empty-entry", f"{where} produces no files")
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
    entries = (
        ("overlay", manifest.overlays),
        ("shader", manifest.shaders),
        ("apk", manifest.apks),
        ("artifact", manifest.artifacts),
    )
    for kind, typed in entries:
        for index, entry in enumerate(typed):
            if entry.source is None:
                continue
            if entry.source not in sources:
                error(
                    "unknown-source",
                    f"{kind}[{index}] references unknown source {entry.source!r}",
                )
            referenced.add(entry.source)
    return sources, referenced
