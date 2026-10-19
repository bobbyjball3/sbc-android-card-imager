"""Compare a manifest's expected card tree with an image's verified tree."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx

from sbc_imager import container
from sbc_imager.assembler_verify import dirs_path_for
from sbc_imager.config import Manifest, load_manifest
from sbc_imager.errors import ConfigError, VerificationError
from sbc_imager.fs import sha256_file
from sbc_imager.planner import build_plan
from sbc_imager.runner import Runner
from sbc_imager.sources import (
    ResolvedSource,
    SourceCache,
    resolve_git,
    resolve_http,
    resolve_local,
)
from sbc_imager.sources_github import resolve_github
from sbc_imager.validation import validate_manifest

_SHA_LENGTH = 64
_HEX = frozenset("0123456789abcdef")
Log = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class ExpectedTree:
    """The files and directories the manifest promises on the card."""

    files: Mapping[str, str]
    required_dirs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ActualTree:
    """The files and directories the assembler found in the image."""

    files: Mapping[str, str]
    dirs: frozenset[str]


@dataclass(frozen=True, slots=True)
class VerifyReport:
    """The host-side comparison of the expected and actual trees."""

    expected_files: int = 0
    actual_files: int = 0
    missing: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()
    mismatched: tuple[str, ...] = ()
    missing_dirs: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not (self.missing or self.extra or self.mismatched or self.missing_dirs)

    def payload(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "expected_files": self.expected_files,
            "actual_files": self.actual_files,
            "missing": list(self.missing),
            "extra": list(self.extra),
            "mismatched": list(self.mismatched),
            "missing_dirs": list(self.missing_dirs),
        }


def _resolve_sources(
    manifest: Manifest,
    cache: SourceCache,
    runner: Runner,
    client: httpx.Client,
    *,
    offline: bool,
    allow_branch: bool,
) -> dict[str, ResolvedSource]:
    entries = (*manifest.overlays, *manifest.shaders, *manifest.apks)
    wanted = {entry.source for entry in entries if isinstance(entry.source, str)}
    resolved: dict[str, ResolvedSource] = {}
    for source in manifest.sources:
        if source.id not in wanted:
            continue
        kind = source.type.casefold()
        if kind == "git":
            resolved[source.id] = resolve_git(
                source,
                cache,
                runner,
                offline=offline,
                allow_branch=allow_branch,
            )
        elif kind == "github":
            resolved[source.id] = resolve_github(source, cache, client, offline=offline)
        elif kind in {"http", "https", "url"}:
            resolved[source.id] = resolve_http(source, cache, client, offline=offline)
        elif kind == "local":
            path = Path(source.url or "").expanduser()
            resolved[source.id] = resolve_local(
                path if path.is_absolute() else manifest.base_dir / path, source.id
            )
        else:
            raise ConfigError(f"unsupported source type '{source.type}' for '{source.id}'")
    return resolved


def _marker_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def build_expected(
    manifest: Manifest,
    resolved_sources: Mapping[str, ResolvedSource],
) -> ExpectedTree:
    """Hash every planned file and generated marker into the expected tree."""
    plan = build_plan(manifest, resolved_sources)
    files: dict[str, str] = {}
    for entry in plan.entries:
        dest = entry.dest.as_posix()
        if dest in files:
            raise ConfigError(f"duplicate-destination: {dest!r} is planned twice")
        files[dest] = sha256_file(entry.src)
    for marker in (plan.settings_marker, plan.credits_marker):
        dest = marker.path.as_posix()
        if dest in files:
            raise ConfigError(f"marker-collision: {dest!r} collides with a planned file")
        files[dest] = _marker_sha256(marker.content)
    dirs = tuple(sorted({path.as_posix() for path in plan.required_dirs}))
    return ExpectedTree(files=files, required_dirs=dirs)


def _load_json(path: Path, what: str) -> object:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise VerificationError(f"cannot read {what} {path}: {exc}") from exc
    except ValueError as exc:
        raise VerificationError(f"invalid JSON in {what} {path}: {exc}") from exc
    return raw


def _file_entry(value: object, index: int) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise VerificationError(f"tree.json entry {index} must be an object")
    dest = value.get("dest")
    size = value.get("size")
    sha256 = value.get("sha256")
    if not isinstance(dest, str) or not dest:
        raise VerificationError(f"tree.json entry {index} has an invalid dest")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise VerificationError(f"tree.json entry {index} has an invalid size")
    if not isinstance(sha256, str) or len(sha256) != _SHA_LENGTH:
        raise VerificationError(f"tree.json entry {index} has an invalid sha256")
    digest = sha256.casefold()
    if any(char not in _HEX for char in digest):
        raise VerificationError(f"tree.json entry {index} has an invalid sha256")
    return dest, digest


def load_actual_tree(tree_path: Path, dirs_path: Path) -> ActualTree:
    """Load the container's file and directory listings."""
    raw = _load_json(tree_path, "tree")
    if not isinstance(raw, list):
        raise VerificationError(f"tree.json {tree_path} must be a list")
    files: dict[str, str] = {}
    for index, item in enumerate(raw):
        dest, digest = _file_entry(item, index)
        if dest in files:
            raise VerificationError(f"tree.json lists {dest!r} more than once")
        files[dest] = digest

    dirs_raw = _load_json(dirs_path, "directory listing")
    if not isinstance(dirs_raw, list) or not all(isinstance(item, str) for item in dirs_raw):
        raise VerificationError(f"directory listing {dirs_path} must be a list of strings")
    return ActualTree(files=files, dirs=frozenset(dirs_raw))


def compare(expected: ExpectedTree, actual_tree: ActualTree) -> VerifyReport:
    """Report missing, extra, mismatched, and missing-directory entries deterministically."""
    expected_paths = set(expected.files)
    actual_paths = set(actual_tree.files)
    missing = tuple(sorted(expected_paths - actual_paths))
    extra = tuple(sorted(actual_paths - expected_paths))
    mismatched = tuple(
        sorted(
            dest
            for dest in expected_paths & actual_paths
            if expected.files[dest] != actual_tree.files[dest]
        )
    )
    missing_dirs = tuple(sorted(set(expected.required_dirs) - actual_tree.dirs))
    return VerifyReport(
        expected_files=len(expected.files),
        actual_files=len(actual_tree.files),
        missing=missing,
        extra=extra,
        mismatched=mismatched,
        missing_dirs=missing_dirs,
    )


def verify_image(
    manifest_path: str | Path,
    image_path: str | Path,
    cache: SourceCache,
    runner: Runner,
    client: httpx.Client,
    offline: bool = False,
    allow_branch: bool = False,
    *,
    on_line: Log = print,
    tag: str = container.DEFAULT_TAG,
) -> VerifyReport:
    """Resolve the manifest, verify the image in the container, and compare trees."""
    manifest = load_manifest(manifest_path)
    resolved = _resolve_sources(
        manifest,
        cache,
        runner,
        client,
        offline=offline,
        allow_branch=allow_branch,
    )
    validate_manifest(manifest)
    expected = build_expected(manifest, resolved)

    image = Path(image_path)
    if not image.is_file():
        raise ConfigError(f"image does not exist: {image}")
    with tempfile.TemporaryDirectory(prefix=".sbc-verify-", dir=image.parent) as scratch:
        out_dir = Path(scratch)
        returncode = container.verify_image(
            runner,
            tag,
            image,
            out_dir,
            image.name,
            on_line=on_line,
        )
        if returncode != 0:
            raise VerificationError(f"container verification failed with exit code {returncode}")
        tree_path = out_dir / "tree.json"
        if not tree_path.is_file():
            raise VerificationError(f"container produced no tree.json in {out_dir}")
        actual = load_actual_tree(tree_path, dirs_path_for(tree_path))
    return compare(expected, actual)
