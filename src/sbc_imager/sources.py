"""Content-addressed cache and local source resolution."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import platformdirs

from sbc_imager.errors import SourceError

CACHE_ENV = "SBC_IMAGER_CACHE_DIR"
APP_NAME = "sbc-imager"


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
