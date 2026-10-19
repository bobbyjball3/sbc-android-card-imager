"""Content-addressed cache and local/git/http source resolution."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import IO
from urllib.parse import unquote, urlsplit

import httpx
import platformdirs

from sbc_imager.config import SourceConfig
from sbc_imager.errors import ConfigError, SourceError
from sbc_imager.runner import redact_url
from sbc_imager.sources_git import resolve_git as resolve_git

CACHE_ENV = "SBC_IMAGER_CACHE_DIR"
APP_NAME = "sbc-imager"
_HTTP_DIR = "http"
_CHUNK_SIZE = 8 * 1024 * 1024
_SHA256_HEX = frozenset("0123456789abcdef")
_SHA256_LENGTH = 64


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    """A source root ready for planning, with stable provenance metadata."""

    id: str
    root: Path
    kind: str
    metadata: dict[str, str]


class SourceCache:
    """Cache rooted under the platform cache dir, overridable by environment."""

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            override = os.environ.get(CACHE_ENV)
            base = Path(override) if override else Path(platformdirs.user_cache_dir(APP_NAME))
            self.root = base.expanduser().resolve()
        else:
            self.root = Path(root).expanduser().resolve()

    def key(self, *parts: str) -> str:
        """Return a SHA-256 hex digest of NUL-joined UTF-8 parts."""
        return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()

    def path_for(self, key: str, *parts: str) -> Path:
        """Return a path under the cache key, creating no directories."""
        return self.root.joinpath(key, *parts)

    def write_atomic(self, path: Path, data: bytes) -> Path:
        """Write bytes via a same-directory temp file and atomic replace."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, target)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise
        return target


@dataclass(frozen=True, slots=True)
class _HttpSpec:
    entry_id: str
    url: str
    sha256: str
    filename: str


def _http_spec(entry: SourceConfig) -> _HttpSpec:
    if entry.type != "url":
        raise ConfigError(f"source '{entry.id}' is not a url source")
    url = (entry.url or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ConfigError(f"http source '{entry.id}' requires an http(s) url with a host")
    sha256 = entry.sha256 or ""
    if len(sha256) != _SHA256_LENGTH or any(char not in _SHA256_HEX for char in sha256):
        raise ConfigError(
            f"http source '{entry.id}' requires a 64-character lowercase hex sha256",
            hint="add the pinned sha256 of the downloaded file to the source entry",
        )
    raw_filename = entry.filename if entry.filename is not None else parts.path.rsplit("/", 1)[-1]
    filename = unquote(raw_filename)
    if filename in {"", ".", ".."} or any(char in filename for char in "/\\\x00"):
        raise ConfigError(
            f"http source '{entry.id}' has an unsafe filename {filename!r}",
            hint="set 'filename' to a plain file name without path separators",
        )
    return _HttpSpec(entry.id, url, sha256, filename)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_matches(destination: Path, spec: _HttpSpec) -> bool:
    return destination.is_file() and _file_sha256(destination) == spec.sha256


def _stream_to(spec: _HttpSpec, client: httpx.Client, handle: IO[bytes]) -> str:
    digest = hashlib.sha256()
    try:
        with client.stream("GET", spec.url) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes(_CHUNK_SIZE):
                digest.update(chunk)
                handle.write(chunk)
    except httpx.HTTPStatusError as error:
        raise SourceError(
            f"http source '{spec.entry_id}' request to {redact_url(spec.url)} "
            f"failed with status {error.response.status_code}"
        ) from error
    except httpx.RequestError as error:
        raise SourceError(
            f"http source '{spec.entry_id}' request to {redact_url(spec.url)} "
            f"failed: {type(error).__name__}"
        ) from error
    return digest.hexdigest()


def _download(spec: _HttpSpec, client: httpx.Client, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            actual = _stream_to(spec, client, handle)
            handle.flush()
            os.fsync(handle.fileno())
        if actual != spec.sha256:
            raise SourceError(
                f"http source '{spec.entry_id}' checksum mismatch: "
                f"expected {spec.sha256}, got {actual}"
            )
        os.replace(temp_path, destination)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _resolved_http(spec: _HttpSpec, root: Path) -> ResolvedSource:
    return ResolvedSource(
        id=spec.entry_id,
        root=root,
        kind="url",
        metadata={
            "url": redact_url(spec.url),
            "sha256": spec.sha256,
            "filename": spec.filename,
        },
    )


def resolve_http(
    entry: SourceConfig,
    cache: SourceCache,
    client: httpx.Client,
    *,
    offline: bool = False,
) -> ResolvedSource:
    """Resolve a checksummed HTTP source into the cache, honoring offline mode."""
    spec = _http_spec(entry)
    destination = cache.path_for(_HTTP_DIR, spec.sha256, spec.filename)
    if offline:
        if _cache_matches(destination, spec):
            return _resolved_http(spec, destination)
        raise SourceError(
            f"http source '{entry.id}' is not cached for offline use: "
            f"sha256 {spec.sha256} at {destination}"
        )
    _download(spec, client, destination)
    return _resolved_http(spec, destination)


def resolve_local(path: Path, source_id: str = "local") -> ResolvedSource:
    """Resolve an existing local file or directory without copying or hashing it."""
    candidate = Path(path)
    if not candidate.exists():
        raise SourceError(f"local source '{source_id}' path does not exist: {candidate}")
    root = candidate.resolve()
    if root.is_file():
        kind = "file"
    elif root.is_dir():
        kind = "directory"
    else:
        raise SourceError(f"local source '{source_id}' is not a file or directory: {candidate}")
    return ResolvedSource(id=source_id, root=root, kind=kind, metadata={})
