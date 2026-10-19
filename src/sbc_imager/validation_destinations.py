"""Card-relative destination computation for every manifest entry kind."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sbc_imager.cannoli import (
    apks_dir,
    art_dir,
    bios_dir,
    overlays_dir,
    rom_dir,
    shaders_dir,
)
from sbc_imager.config import Manifest
from sbc_imager.validation_common import error, tag
from sbc_imager.validation_local import entry_files, is_rom_junk


@dataclass(frozen=True, slots=True)
class Destination:
    dest: PurePosixPath
    entry_index: int
    kind: str
    source_root: Path | None = None


def component(value: str, where: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or len(path.parts) != 1
        or path.parts[0] in {".", ".."}
        or "\\" in value
        or any(part == "" for part in value.split("/"))
    ):
        error("invalid-as", f"{where} 'as' must be a single relative filename: {value!r}")
    return path.parts[0]


def relative_dir(value: str, where: str) -> PurePosixPath:
    if not value or any(part == "" for part in value.split("/")):
        error("invalid-dest", f"{where} destination must be a non-empty relative directory")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        error("invalid-dest", f"{where} destination must stay inside the card: {value!r}")
    return path


def source_relative_path(path: Path, where: str) -> PurePosixPath:
    raw = path.as_posix()
    relative = PurePosixPath(raw)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or any(part == "" for part in raw.split("/"))
    ):
        error("source-path", f"{where} source-relative path must stay inside the source")
    return relative


def _rom_destinations(manifest: Manifest) -> Iterator[Destination]:
    for index, entry in enumerate(manifest.roms):
        platform = tag(entry.platform, f"rom[{index}]")
        for _, rel in entry_files(entry.path, entry.include, entry.exclude):
            if not is_rom_junk(rel.name, platform):
                yield Destination(rom_dir(platform) / rel, index, "rom", entry.path)


def _bios_destinations(manifest: Manifest) -> Iterator[Destination]:
    for index, entry in enumerate(manifest.bios):
        platform = tag(entry.platform, f"bios[{index}]")
        if entry.path.is_file():
            name = component(entry.as_, f"bios[{index}]") if entry.as_ else entry.path.name
            yield Destination(bios_dir(platform) / name, index, "bios", entry.path)
        else:
            if entry.as_ is not None:
                component(entry.as_, f"bios[{index}]")
            for _, rel in entry_files(entry.path):
                yield Destination(bios_dir(platform) / rel, index, "bios", entry.path)


def _art_destinations(manifest: Manifest) -> Iterator[Destination]:
    for index, entry in enumerate(manifest.art):
        platform = tag(entry.platform, f"art[{index}]")
        for _, rel in entry_files(entry.path, entry.include, entry.exclude):
            yield Destination(art_dir(platform) / rel, index, "art", entry.path)


def _overlay_destinations(manifest: Manifest) -> Iterator[Destination]:
    for index, entry in enumerate(manifest.overlays):
        platform = tag(entry.platform, f"overlay[{index}]")
        base = overlays_dir(platform)
        where = f"overlay[{index}]"
        if entry.source is not None:
            relative = source_relative_path(entry.path, where)
            name = component(entry.as_, where) if entry.as_ else relative.name
            yield Destination(base / name, index, "overlay", entry.path)
        elif entry.path.is_file():
            name = component(entry.as_, where) if entry.as_ else entry.path.name
            yield Destination(base / name, index, "overlay", entry.path)
        else:
            prefix = PurePosixPath(component(entry.as_, where)) if entry.as_ else PurePosixPath()
            for _, rel in entry_files(entry.path):
                if rel.suffix.casefold() == ".png":
                    yield Destination(base / prefix / rel, index, "overlay", entry.path)


def _shader_destinations(manifest: Manifest) -> Iterator[Destination]:
    for index, entry in enumerate(manifest.shaders):
        where = f"shader[{index}]"
        if entry.source is not None:
            relative = source_relative_path(entry.path, where)
            name = component(entry.as_, where) if entry.as_ else relative.name
            if relative.suffix.casefold() == ".glslp":
                yield Destination(
                    shaders_dir() / PurePosixPath(name).stem / name, index, "shader", entry.path
                )
            else:
                yield Destination(shaders_dir() / name, index, "shader", entry.path)
        elif entry.path.is_file():
            name = component(entry.as_, where) if entry.as_ else entry.path.name
            yield Destination(shaders_dir() / entry.path.stem / name, index, "shader", entry.path)
        else:
            preset = component(entry.as_, where) if entry.as_ else entry.path.name
            for _, rel in entry_files(entry.path):
                yield Destination(shaders_dir() / preset / rel, index, "shader", entry.path)


def _apk_destinations(manifest: Manifest) -> Iterator[Destination]:
    for index, entry in enumerate(manifest.apks):
        where = f"apk[{index}]"
        if entry.path.is_file():
            name = component(entry.as_, where) if entry.as_ else entry.path.name
            yield Destination(apks_dir() / name, index, "apk", entry.path)
        else:
            prefix = PurePosixPath(component(entry.as_, where)) if entry.as_ else PurePosixPath()
            for _, rel in entry_files(entry.path):
                yield Destination(apks_dir() / prefix / rel, index, "apk", entry.path)


def _artifact_destinations(manifest: Manifest) -> Iterator[Destination]:
    for index, entry in enumerate(manifest.artifacts):
        where = f"artifact[{index}]"
        root = entry.root.casefold()
        if root not in {"card", "cannoli"}:
            error("artifact-root", f"{where} root must be 'card' or 'cannoli'")
        base = (PurePosixPath("Cannoli") if root == "cannoli" else PurePosixPath()) / relative_dir(
            entry.dest, where
        )
        if entry.path.is_file():
            name = component(entry.as_, where) if entry.as_ else entry.path.name
            yield Destination(base / name, index, "artifact", entry.path)
        else:
            if entry.as_ is not None:
                component(entry.as_, where)
            for _, rel in entry_files(entry.path):
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
