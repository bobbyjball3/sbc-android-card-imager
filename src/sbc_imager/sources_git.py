"""Pinned git source resolution with an atomic, offline-capable cache."""

from __future__ import annotations

import json
import os
import shutil
import string
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from sbc_imager.config import SourceConfig
from sbc_imager.errors import ConfigError, SourceError
from sbc_imager.runner import Runner, redact_url

if TYPE_CHECKING:
    from sbc_imager.sources import ResolvedSource, SourceCache

_GIT_DIR: Final = "git"
_META_FILE: Final = "meta.json"
_SHA_LEN: Final = 40


@dataclass(frozen=True, slots=True)
class _GitSpec:
    entry_id: str
    url: str
    ref: str
    subdir: str
    key: str

    @property
    def is_commit(self) -> bool:
        return len(self.ref) == _SHA_LEN and all(char in string.hexdigits for char in self.ref)


def _git_spec(entry: SourceConfig, cache: SourceCache) -> _GitSpec:
    if entry.type != "git":
        raise ConfigError(f"source '{entry.id}' is not a git source")
    url = entry.url.strip()
    if not url:
        raise ConfigError(f"git source '{entry.id}' requires a non-empty url")
    ref = (entry.ref or "").strip()
    if not ref:
        raise ConfigError(f"git source '{entry.id}' requires a non-empty ref")
    subdir = entry.subdir or ""
    return _GitSpec(entry.id, url, ref, subdir, cache.key(url, ref, subdir))


def _read_meta(repo: Path) -> dict[str, str] | None:
    try:
        raw = json.loads((repo / _META_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    return {str(key): str(value) for key, value in raw.items() if isinstance(value, str)}


def _cached_commit(runner: Runner, spec: _GitSpec, repo: Path) -> tuple[dict[str, str], str] | None:
    if not repo.is_dir():
        return None
    meta = _read_meta(repo)
    if meta is None:
        return None
    commit = meta.get("resolved_commit", "")
    if len(commit) != _SHA_LEN:
        return None
    if spec.is_commit and commit.lower() != spec.ref.lower():
        return None
    result = runner.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=False)
    if result.returncode != 0 or result.stdout.strip().lower() != commit.lower():
        return None
    return meta, commit


def _remote_has(runner: Runner, spec: _GitSpec, kind: str) -> bool:
    result = runner.run(["git", "ls-remote", f"--{kind}s", spec.url, spec.ref])
    wanted = f"refs/{kind}s/{spec.ref}"
    for line in result.stdout.splitlines():
        _, _, name = line.partition("\t")
        if name == wanted:
            return True
    return False


def _classify(runner: Runner, spec: _GitSpec) -> str:
    if spec.is_commit:
        return "commit"
    if _remote_has(runner, spec, "tag"):
        return "tag"
    if _remote_has(runner, spec, "head"):
        return "branch"
    raise ConfigError(
        f"git source '{spec.entry_id}' ref '{spec.ref}' is neither a tag nor a branch"
    )


def _branch_warning(spec: _GitSpec, kind: str, allow_branch: bool) -> str | None:
    if kind != "branch":
        return None
    if not allow_branch:
        raise ConfigError(
            f"git source '{spec.entry_id}' ref '{spec.ref}' is a branch; "
            "pass --allow-branch to use it"
        )
    return "branch ref accepted because --allow-branch was set"


def _metadata(spec: _GitSpec, kind: str, commit: str, warning: str | None) -> dict[str, str]:
    metadata = {
        "url": redact_url(spec.url),
        "ref": spec.ref,
        "ref_kind": kind,
        "resolved_commit": commit,
        "subdir": spec.subdir,
    }
    if warning is not None:
        metadata["warning"] = warning
    return metadata


def _resolve_subdir(repo: Path, spec: _GitSpec) -> Path:
    if not spec.subdir:
        return repo
    candidate = Path(spec.subdir)
    if candidate.is_absolute():
        raise ConfigError(f"git source '{spec.entry_id}' subdir must be relative: {spec.subdir}")
    base = repo.resolve()
    root = (base / candidate).resolve()
    if not root.is_relative_to(base):
        raise ConfigError(f"git source '{spec.entry_id}' subdir escapes the repo: {spec.subdir}")
    if not root.exists():
        raise SourceError(f"git source '{spec.entry_id}' subdir does not exist: {spec.subdir}")
    return root


def _fetch_commit(runner: Runner, spec: _GitSpec, temp: Path) -> str:
    runner.run(["git", "init", "-q", str(temp)])
    runner.run(["git", "-C", str(temp), "remote", "add", "origin", spec.url])
    fetched = runner.run(
        ["git", "-C", str(temp), "fetch", "--depth", "1", "origin", spec.ref],
        check=False,
    )
    if fetched.returncode != 0:
        if not spec.is_commit:
            raise SourceError(
                f"git source '{spec.entry_id}' could not fetch ref '{spec.ref}' "
                f"from {redact_url(spec.url)}"
            )
        runner.run(["git", "-C", str(temp), "fetch", "origin"])
        runner.run(["git", "-C", str(temp), "checkout", "--detach", spec.ref])
    else:
        runner.run(["git", "-C", str(temp), "checkout", "--detach", "FETCH_HEAD"])
    head = runner.run(["git", "-C", str(temp), "rev-parse", "HEAD"]).stdout.strip().lower()
    if len(head) != _SHA_LEN:
        raise SourceError(f"git source '{spec.entry_id}' did not check out a commit")
    if spec.is_commit and head != spec.ref.lower():
        raise SourceError(
            f"git source '{spec.entry_id}' resolved {head}, expected {spec.ref.lower()}"
        )
    runner.run(["git", "-C", str(temp), "remote", "remove", "origin"])
    return head


def _fetch_cached(runner: Runner, cache: SourceCache, spec: _GitSpec, kind: str) -> str:
    repo = cache.root / _GIT_DIR / spec.key
    cache.root.mkdir(parents=True, exist_ok=True)
    repo.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="git-", dir=cache.root))
    try:
        commit = _fetch_commit(runner, spec, temp)
        fetched_at = datetime.now(UTC).isoformat()
        meta = _metadata(spec, kind, commit, None) | {"fetched_at": fetched_at}
        cache.write_atomic(temp / _META_FILE, json.dumps(meta).encode("utf-8"))
        if repo.exists():
            raced = _cached_commit(runner, spec, repo)
            if raced is not None:
                shutil.rmtree(temp)
                return raced[1]
            shutil.rmtree(repo)
        os.replace(temp, repo)
        return commit
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def resolve_git(
    entry: SourceConfig,
    cache: SourceCache,
    runner: Runner,
    *,
    offline: bool = False,
    allow_branch: bool = False,
) -> ResolvedSource:
    """Resolve a pinned git ref into a cached checkout, honoring offline mode."""
    from sbc_imager.sources import ResolvedSource

    spec = _git_spec(entry, cache)
    repo = cache.root / _GIT_DIR / spec.key
    meta = _read_meta(repo)
    cached = _cached_commit(runner, spec, repo)
    kind = "" if cached is None else cached[0].get("ref_kind", "")
    if cached is not None and kind:
        warning = _branch_warning(spec, kind, allow_branch)
        commit = cached[1]
    elif offline:
        reason = "is not cached" if meta is None else "cache is stale"
        raise SourceError(f"git source '{entry.id}' {reason} for offline use: cache key {spec.key}")
    else:
        kind = _classify(runner, spec)
        warning = _branch_warning(spec, kind, allow_branch)
        commit = _fetch_cached(runner, cache, spec, kind)
    return ResolvedSource(
        id=entry.id,
        root=_resolve_subdir(repo, spec),
        kind="git",
        metadata=_metadata(spec, kind, commit, warning),
    )
