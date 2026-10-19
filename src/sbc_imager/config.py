"""Typed, strict loading of TOML card manifests."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Never

from sbc_imager.errors import ConfigError

type _Table = Mapping[str, object]

_KEYS: Final[dict[str, frozenset[str]]] = {
    "image": frozenset({"name", "label", "size", "reserve", "output"}),
    "source": frozenset(
        {
            "id",
            "type",
            "url",
            "ref",
            "subdir",
            "filename",
            "sha256",
            "license",
            "attribution",
            "repo",
            "tag",
            "asset",
        }
    ),
    "overlay": frozenset({"platform", "path", "source", "as"}),
    "shader": frozenset({"path", "source", "as"}),
    "apk": frozenset({"path", "source", "as"}),
    "artifact": frozenset({"root", "dest", "path", "source", "as"}),
}

_RETIRED_TABLES: Final[dict[str, str]] = {
    "rom": "`[[rom]]` is no longer supported; Cannoli/RomM supplies ROM content.",
    "bios": "`[[bios]]` is no longer supported; Cannoli/RomM supplies BIOS content.",
    "art": "`[[art]]` is no longer supported; Cannoli/RomM supplies box art.",
}


def _fail(message: str) -> Never:
    raise ConfigError(message)


def _default(value: str | None, fallback: str) -> str:
    return fallback if value is None else value


@dataclass(frozen=True, slots=True)
class ImageConfig:
    name: str
    label: str
    size: str
    reserve: str
    output: Path


@dataclass(frozen=True, slots=True)
class SourceConfig:
    id: str
    type: str
    url: str | None
    ref: str | None
    subdir: str | None
    filename: str | None
    sha256: str | None
    license: str | None
    attribution: str | None
    repo: str | None = None
    tag: str | None = None
    asset: str | None = None


@dataclass(frozen=True, slots=True)
class OverlayEntry:
    platform: str
    path: Path
    source: str | None
    as_: str | None


@dataclass(frozen=True, slots=True)
class ShaderEntry:
    path: Path
    source: str | None
    as_: str | None


@dataclass(frozen=True, slots=True)
class ApkEntry:
    path: Path | None
    source: str | None
    as_: str | None


@dataclass(frozen=True, slots=True)
class ArtifactEntry:
    root: str
    dest: str
    path: Path | None
    source: str | None
    as_: str | None


@dataclass(frozen=True, slots=True)
class Manifest:
    image: ImageConfig
    sources: tuple[SourceConfig, ...]
    overlays: tuple[OverlayEntry, ...]
    shaders: tuple[ShaderEntry, ...]
    apks: tuple[ApkEntry, ...]
    artifacts: tuple[ArtifactEntry, ...]
    base_dir: Path


class _ManifestParser:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.base_dir = path.parent

    def parse(self) -> Manifest:
        data = self._read_toml()
        for table, message in _RETIRED_TABLES.items():
            if table in data:
                _fail(f"{message} Remove `[[{table}]]` from manifest {self.path}.")
        if unknown := sorted(set(data) - _KEYS.keys()):
            _fail(f"unknown key '{unknown[0]}' in manifest {self.path}")
        image = self._image(self._table(data.get("image", {}), "image", _KEYS["image"]))
        sources = self._sources(self._tables(data, "source"))
        overlays = tuple(self._overlay(t, i) for i, t in enumerate(self._tables(data, "overlay")))
        shaders = tuple(self._shader(t, i) for i, t in enumerate(self._tables(data, "shader")))
        apks = tuple(self._apk(t, i) for i, t in enumerate(self._tables(data, "apk")))
        artifact_tables = self._tables(data, "artifact")
        artifacts = tuple(self._artifact(t, i) for i, t in enumerate(artifact_tables))
        return Manifest(image, sources, overlays, shaders, apks, artifacts, self.base_dir)

    def _read_toml(self) -> dict[str, object]:
        try:
            data: dict[str, object] = tomllib.loads(self.path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            _fail(f"cannot load manifest {self.path}: {error}")
        return data

    def _table(self, value: object, where: str, allowed: frozenset[str]) -> _Table:
        if not isinstance(value, dict):
            _fail(f"{where} must be a table in manifest {self.path}")
        unknown = sorted(key for key in value if key not in allowed)
        if unknown:
            _fail(f"unknown key '{where}.{unknown[0]}' in manifest {self.path}")
        return value

    def _tables(self, data: _Table, key: str) -> list[_Table]:
        value = data.get(key, [])
        if not isinstance(value, list):
            _fail(f"'{key}' must be an array of tables in manifest {self.path}")
        return [
            self._table(entry, f"{key}[{index}]", _KEYS[key]) for index, entry in enumerate(value)
        ]

    def _text(self, table: _Table, key: str, where: str) -> str | None:
        value = table.get(key)
        if value is not None and not isinstance(value, str):
            _fail(f"{where}.{key} must be a string in manifest {self.path}")
        return value

    def _required_text(self, table: _Table, key: str, where: str) -> str:
        value = self._text(table, key, where)
        if value is None:
            _fail(f"{where} is missing required key '{key}' in manifest {self.path}")
        return value

    def _local_path(self, table: _Table, key: str, where: str) -> Path:
        path = Path(self._required_text(table, key, where)).expanduser()
        if not path.is_absolute():
            path = self.base_dir / path
        if path.is_symlink():
            _fail(f"symlink: {where} is a symlink: {path}")
        return path.resolve()

    def _asset_path(self, table: _Table, where: str) -> Path:
        if self._text(table, "source", where) is None:
            return self._local_path(table, "path", where)
        return Path(self._required_text(table, "path", where)).expanduser()

    def _image(self, table: _Table) -> ImageConfig:
        name = _default(self._text(table, "name", "image"), self.path.stem)
        label = _default(self._text(table, "label", "image"), "CANNOLI")
        size = _default(self._text(table, "size", "image"), "auto")
        reserve = _default(self._text(table, "reserve", "image"), "8GiB")
        raw = _default(self._text(table, "output", "image"), f"dist/{name}.img")
        output = Path(raw).expanduser()
        if not output.is_absolute():
            output = (self.base_dir / output).resolve()
        return ImageConfig(name, label, size, reserve, output)

    def _sources(self, tables: list[_Table]) -> tuple[SourceConfig, ...]:
        sources: list[SourceConfig] = []
        seen: set[str] = set()
        for index, table in enumerate(tables):
            source = self._source(table, index)
            if source.id in seen:
                _fail(f"duplicate source id '{source.id}' in manifest {self.path}")
            seen.add(source.id)
            sources.append(source)
        return tuple(sources)

    def _source(self, table: _Table, index: int) -> SourceConfig:
        where = f"source[{index}]"
        entry_id = self._required_text(table, "id", where)
        kind = self._required_text(table, "type", where)
        url = self._text(table, "url", where)
        ref = self._text(table, "ref", where)
        subdir = self._text(table, "subdir", where)
        filename = self._text(table, "filename", where)
        repo = self._text(table, "repo", where)
        tag = self._text(table, "tag", where)
        asset = self._text(table, "asset", where)
        if kind.casefold() == "github":
            for key, value in (
                ("url", url),
                ("ref", ref),
                ("subdir", subdir),
                ("filename", filename),
            ):
                if value is not None:
                    _fail(
                        f"github source '{entry_id}' does not accept '{key}' "
                        f"in manifest {self.path}"
                    )
            if not repo:
                _fail(f"github source '{entry_id}' is missing required key 'repo'")
            if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) is None:
                _fail(
                    f"github source '{entry_id}' repo must be 'owner/name' in manifest {self.path}"
                )
            if not tag:
                _fail(f"github source '{entry_id}' is missing required key 'tag'")
            if not asset:
                _fail(f"github source '{entry_id}' is missing required key 'asset'")
            if asset in {".", ".."} or any(char in asset for char in "/\\\x00"):
                _fail(
                    f"github source '{entry_id}' asset must be a plain file name "
                    f"in manifest {self.path}"
                )
        else:
            if any(value is not None for value in (repo, tag, asset)):
                _fail(
                    f"source '{entry_id}' of type '{kind}' does not accept "
                    f"repo/tag/asset in manifest {self.path}"
                )
            if url is None:
                _fail(f"{where} is missing required key 'url' in manifest {self.path}")
        return SourceConfig(
            entry_id,
            kind,
            url,
            ref,
            subdir,
            filename,
            self._text(table, "sha256", where),
            self._text(table, "license", where),
            self._text(table, "attribution", where),
            repo,
            tag,
            asset,
        )

    def _overlay(self, table: _Table, index: int) -> OverlayEntry:
        where = f"overlay[{index}]"
        return OverlayEntry(
            self._required_text(table, "platform", where),
            self._asset_path(table, where),
            self._text(table, "source", where),
            self._text(table, "as", where),
        )

    def _shader(self, table: _Table, index: int) -> ShaderEntry:
        where = f"shader[{index}]"
        return ShaderEntry(
            self._asset_path(table, where),
            self._text(table, "source", where),
            self._text(table, "as", where),
        )

    def _apk(self, table: _Table, index: int) -> ApkEntry:
        where = f"apk[{index}]"
        source = self._text(table, "source", where)
        if source is not None:
            if self._text(table, "path", where) is not None:
                _fail(f"{where} cannot set both 'path' and 'source' in manifest {self.path}")
            as_ = self._required_text(table, "as", where)
            if not as_:
                _fail(f"{where} requires a non-empty 'as' in manifest {self.path}")
            return ApkEntry(None, source, as_)
        return ApkEntry(
            self._local_path(table, "path", where),
            None,
            self._text(table, "as", where),
        )

    def _artifact(self, table: _Table, index: int) -> ArtifactEntry:
        where = f"artifact[{index}]"
        source = self._text(table, "source", where)
        if source is not None:
            if self._text(table, "path", where) is not None:
                _fail(f"{where} cannot set both 'path' and 'source' in manifest {self.path}")
            as_ = self._required_text(table, "as", where)
            if not as_:
                _fail(f"{where} requires a non-empty 'as' in manifest {self.path}")
            return ArtifactEntry(
                _default(self._text(table, "root", where), "cannoli"),
                self._required_text(table, "dest", where),
                None,
                source,
                as_,
            )
        return ArtifactEntry(
            _default(self._text(table, "root", where), "cannoli"),
            self._required_text(table, "dest", where),
            self._local_path(table, "path", where),
            None,
            self._text(table, "as", where),
        )


def load_manifest(path: str | Path) -> Manifest:
    """Load and parse a TOML manifest without touching the files it references."""
    manifest_path = Path(path).expanduser().resolve()
    return _ManifestParser(manifest_path).parse()
