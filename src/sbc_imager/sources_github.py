"""Pinned GitHub release asset resolution with an offline-capable cache."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final
from urllib.parse import quote

import httpx

from sbc_imager.config import SourceConfig
from sbc_imager.errors import ConfigError, SourceError
from sbc_imager.runner import redact_url

if TYPE_CHECKING:
    from sbc_imager.sources import ResolvedSource, SourceCache

_API: Final = "https://api.github.com"
_META_FILE: Final = "source.json"
_CHUNK_SIZE: Final = 8 * 1024 * 1024
_SHA256_LENGTH: Final = 64
_REPO_PATTERN: Final = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_HEX_PATTERN: Final = re.compile(r"[0-9a-fA-F]{64}")
_REQUIRED_METADATA: Final = (
    "repo",
    "tag",
    "asset",
    "url",
    "sha256",
    "size",
    "license",
    "attribution",
    "release_url",
)


@dataclass(frozen=True, slots=True)
class _GithubSpec:
    entry_id: str
    repo: str
    tag: str
    asset: str
    key: str


def _github_spec(entry: SourceConfig, cache: SourceCache) -> _GithubSpec:
    if entry.type.casefold() != "github":
        raise ConfigError(f"source '{entry.id}' is not a github source")
    for key, value in (
        ("url", entry.url),
        ("ref", entry.ref),
        ("subdir", entry.subdir),
        ("filename", entry.filename),
    ):
        if value is not None:
            raise ConfigError(f"github source '{entry.id}' does not accept '{key}'")
    repo = (entry.repo or "").strip()
    tag = (entry.tag or "").strip()
    asset = entry.asset or ""
    if not repo:
        raise ConfigError(f"github source '{entry.id}' requires a non-empty repo")
    if _REPO_PATTERN.fullmatch(repo) is None:
        raise ConfigError(f"github source '{entry.id}' repo must be 'owner/name': {repo!r}")
    if not tag:
        raise ConfigError(f"github source '{entry.id}' requires a non-empty tag")
    if not asset:
        raise ConfigError(f"github source '{entry.id}' requires a non-empty asset")
    if asset in {".", ".."} or any(char in asset for char in "/\\\x00"):
        raise ConfigError(f"github source '{entry.id}' asset must be a plain file name: {asset!r}")
    return _GithubSpec(entry.id, repo, tag, asset, cache.key("github", repo, tag, asset))


def _override_sha256(entry: SourceConfig) -> str | None:
    raw = entry.sha256
    if raw is None:
        return None
    value = raw.strip()
    if len(value) != _SHA256_LENGTH or _HEX_PATTERN.fullmatch(value) is None:
        raise ConfigError(f"github source '{entry.id}' sha256 must be 64 hexadecimal characters")
    return value.casefold()


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "sbc-imager",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _status_error(spec: _GithubSpec, what: str, url: str, status: int) -> SourceError:
    hint = "set GITHUB_TOKEN to authenticate with the GitHub API" if status in {403, 429} else None
    return SourceError(
        f"github source '{spec.entry_id}' {what} request to {redact_url(url)} "
        f"failed with status {status}",
        hint=hint,
    )


def _request_json(client: httpx.Client, spec: _GithubSpec, what: str, url: str) -> object:
    try:
        response = client.get(url, headers=_headers())
    except httpx.RequestError as error:
        raise SourceError(
            f"github source '{spec.entry_id}' {what} request to {redact_url(url)} "
            f"failed: {type(error).__name__}"
        ) from error
    if response.status_code >= 400:
        raise _status_error(spec, what, url, response.status_code)
    try:
        return response.json()
    except ValueError as error:
        raise SourceError(
            f"github source '{spec.entry_id}' {what} response from "
            f"{redact_url(url)} was not valid JSON"
        ) from error


def _release_url(spec: _GithubSpec) -> str:
    repo = quote(spec.repo, safe="/")
    return f"{_API}/repos/{repo}/releases/tags/{quote(spec.tag, safe='')}"


def _repo_url(spec: _GithubSpec) -> str:
    return f"{_API}/repos/{quote(spec.repo, safe='/')}"


def _release(
    client: httpx.Client, spec: _GithubSpec
) -> tuple[dict[str, object], dict[str, object]]:
    raw = _request_json(client, spec, "release", _release_url(spec))
    if not isinstance(raw, dict):
        raise SourceError(f"github source '{spec.entry_id}' release response is malformed")
    assets_raw = raw.get("assets")
    if not isinstance(assets_raw, list):
        raise SourceError(f"github source '{spec.entry_id}' release response has no assets")
    assets = [asset for asset in assets_raw if isinstance(asset, dict)]
    names = sorted(name for asset in assets if isinstance(name := asset.get("name"), str))
    selected = next((asset for asset in assets if asset.get("name") == spec.asset), None)
    if selected is None:
        available = ", ".join(names) if names else "(none)"
        raise SourceError(
            f"github source '{spec.entry_id}' release tag '{spec.tag}' has no asset "
            f"named '{spec.asset}'; available assets: {available}"
        )
    html_url = raw.get("html_url")
    if not isinstance(html_url, str) or not html_url:
        raise SourceError(f"github source '{spec.entry_id}' release response has no html_url")
    asset_url = selected.get("browser_download_url")
    if not isinstance(asset_url, str) or not asset_url:
        raise SourceError(
            f"github source '{spec.entry_id}' asset '{spec.asset}' has no download URL"
        )
    return selected, {"url": asset_url, "html_url": html_url}


def _asset_size(asset: dict[str, object], spec: _GithubSpec) -> int | None:
    raw = asset.get("size")
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise SourceError(
            f"github source '{spec.entry_id}' asset '{spec.asset}' has an invalid size"
        )
    return raw


def _asset_digest(asset: dict[str, object], spec: _GithubSpec) -> str | None:
    raw = asset.get("digest")
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.casefold().startswith("sha256:"):
        raise SourceError(
            f"github source '{spec.entry_id}' asset '{spec.asset}' has an invalid digest"
        )
    value = raw.split(":", 1)[1]
    if len(value) != _SHA256_LENGTH or _HEX_PATTERN.fullmatch(value) is None:
        raise SourceError(
            f"github source '{spec.entry_id}' asset '{spec.asset}' has an invalid digest"
        )
    return value.casefold()


def _expected_sha256(
    asset: dict[str, object], entry: SourceConfig, spec: _GithubSpec
) -> str | None:
    from_api = _asset_digest(asset, spec)
    override = _override_sha256(entry)
    if from_api is not None and override is not None and from_api != override:
        raise SourceError(
            f"github source '{entry.id}' sha256 override {override} "
            f"disagrees with the release digest {from_api}"
        )
    return from_api if from_api is not None else override


def _license(client: httpx.Client, entry: SourceConfig, spec: _GithubSpec) -> str:
    override = entry.license.strip() if entry.license and entry.license.strip() else None
    if override is not None:
        return override
    raw = _request_json(client, spec, "repository", _repo_url(spec))
    if not isinstance(raw, dict):
        raise SourceError(f"github source '{entry.id}' repository response is malformed")
    license_raw = raw.get("license")
    if license_raw is None:
        detected = None
    elif not isinstance(license_raw, dict):
        raise SourceError(f"github source '{entry.id}' repository license is malformed")
    else:
        spdx = license_raw.get("spdx_id")
        detected = spdx if isinstance(spdx, str) else None
    if not detected or detected.strip().casefold() == "noassertion":
        raise SourceError(
            f"github source '{entry.id}' could not detect a license from the repository",
            hint="set 'license' (and optional 'attribution') on the source entry",
        )
    return detected


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cached(destination: Path, expected: str | None, expected_size: int | None) -> bool:
    if expected is None or not destination.is_file():
        return False
    if expected_size is not None and destination.stat().st_size != expected_size:
        return False
    return _sha256_file(destination) == expected


def _download(
    client: httpx.Client,
    spec: _GithubSpec,
    url: str,
    destination: Path,
    expected: str | None,
    expected_size: int | None,
) -> tuple[str, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temp_path = Path(temp_name)
    digest = hashlib.sha256()
    actual_size = 0
    try:
        with os.fdopen(descriptor, "wb") as handle:
            try:
                with client.stream("GET", url, headers=_headers()) as response:
                    if response.status_code >= 400:
                        raise _status_error(spec, "asset", url, response.status_code)
                    for chunk in response.iter_bytes(_CHUNK_SIZE):
                        digest.update(chunk)
                        handle.write(chunk)
                        actual_size += len(chunk)
            except httpx.RequestError as error:
                raise SourceError(
                    f"github source '{spec.entry_id}' asset request to "
                    f"{redact_url(url)} failed: {type(error).__name__}"
                ) from error
            handle.flush()
            os.fsync(handle.fileno())
        actual = digest.hexdigest()
        if expected is not None and actual != expected:
            raise SourceError(
                f"github source '{spec.entry_id}' checksum mismatch: "
                f"expected {expected}, got {actual}"
            )
        if expected_size is not None and actual_size != expected_size:
            raise SourceError(
                f"github source '{spec.entry_id}' asset '{spec.asset}' size mismatch: "
                f"expected {expected_size}, got {actual_size}"
            )
        os.replace(temp_path, destination)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return digest.hexdigest(), actual_size


def _metadata(
    spec: _GithubSpec,
    *,
    url: str,
    sha256: str,
    size: int,
    license_name: str,
    attribution: str,
    release_url: str,
) -> dict[str, str]:
    return {
        "repo": spec.repo,
        "tag": spec.tag,
        "asset": spec.asset,
        "url": url,
        "sha256": sha256,
        "size": str(size),
        "license": license_name,
        "attribution": attribution,
        "release_url": release_url,
    }


def _metadata_text(value: object, *, allow_int: bool = False) -> str | None:
    if isinstance(value, str) and value:
        return value
    if allow_int and isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return str(value)
    return None


def _read_metadata(path: Path, spec: _GithubSpec) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SourceError(
            f"github source '{spec.entry_id}' has no readable cache metadata "
            f"at {path} for offline use"
        ) from error
    if not isinstance(raw, dict):
        raise SourceError(f"github source '{spec.entry_id}' cache metadata at {path} is corrupt")
    values = {
        key: _metadata_text(raw.get(key), allow_int=key == "size") for key in _REQUIRED_METADATA
    }
    missing = [key for key, value in values.items() if value is None]
    if missing:
        raise SourceError(
            f"github source '{spec.entry_id}' cache metadata at {path} is corrupt: "
            f"missing {', '.join(missing)}"
        )
    data = {key: value for key, value in values.items() if value is not None}
    if data["repo"] != spec.repo or data["tag"] != spec.tag or data["asset"] != spec.asset:
        raise SourceError(
            f"github source '{spec.entry_id}' cache metadata at {path} does not match the manifest"
        )
    sha256 = data["sha256"]
    if len(sha256) != _SHA256_LENGTH or _HEX_PATTERN.fullmatch(sha256) is None:
        raise SourceError(f"github source '{spec.entry_id}' cache metadata has an invalid sha256")
    try:
        int(data["size"])
    except ValueError as error:
        raise SourceError(
            f"github source '{spec.entry_id}' cache metadata has an invalid size"
        ) from error
    return data


def _resolved(spec: _GithubSpec, root: Path, metadata: dict[str, str]) -> ResolvedSource:
    from sbc_imager.sources import ResolvedSource

    return ResolvedSource(id=spec.entry_id, root=root, kind="github", metadata=metadata)


def _resolve_offline(entry: SourceConfig, spec: _GithubSpec, cache: SourceCache) -> ResolvedSource:
    meta_path = cache.path_for(spec.key, _META_FILE)
    destination = cache.path_for(spec.key, "files", spec.asset)
    meta = _read_metadata(meta_path, spec)
    if not destination.is_file():
        raise SourceError(
            f"github source '{entry.id}' asset is missing from the cache at {destination}"
        )
    actual = _sha256_file(destination)
    if actual != meta["sha256"]:
        raise SourceError(
            f"github source '{entry.id}' cached asset is corrupt: "
            f"expected {meta['sha256']}, got {actual}"
        )
    override = _override_sha256(entry)
    if override is not None and override != actual:
        raise SourceError(
            f"github source '{entry.id}' sha256 override {override} "
            f"does not match the cached asset {actual}"
        )
    size = destination.stat().st_size
    if str(size) != meta["size"]:
        raise SourceError(
            f"github source '{entry.id}' cached asset size does not match its metadata"
        )
    license_name = (
        entry.license.strip() if entry.license and entry.license.strip() else meta["license"]
    )
    attribution = (
        entry.attribution.strip()
        if entry.attribution and entry.attribution.strip()
        else meta["attribution"]
    )
    return _resolved(
        spec,
        destination,
        _metadata(
            spec,
            url=meta["url"],
            sha256=actual,
            size=size,
            license_name=license_name,
            attribution=attribution,
            release_url=meta["release_url"],
        ),
    )


def resolve_github(
    entry: SourceConfig,
    cache: SourceCache,
    client: httpx.Client,
    *,
    offline: bool = False,
) -> ResolvedSource:
    """Resolve an exact pinned GitHub release asset, honoring offline mode."""
    spec = _github_spec(entry, cache)
    if offline:
        return _resolve_offline(entry, spec, cache)

    asset, release = _release(client, spec)
    license_name = _license(client, entry, spec)
    raw_attribution = entry.attribution.strip() if entry.attribution else None
    attribution = raw_attribution if raw_attribution else f"{spec.repo} ({release['html_url']})"
    expected = _expected_sha256(asset, entry, spec)
    expected_size = _asset_size(asset, spec)

    destination = cache.path_for(spec.key, "files", spec.asset)
    if _cached(destination, expected, expected_size):
        actual = expected or ""
        actual_size = destination.stat().st_size
    else:
        actual, actual_size = _download(
            client,
            spec,
            str(release["url"]),
            destination,
            expected,
            expected_size,
        )

    metadata = _metadata(
        spec,
        url=str(release["url"]),
        sha256=actual,
        size=actual_size,
        license_name=license_name,
        attribution=attribution,
        release_url=str(release["html_url"]),
    )
    cache.write_atomic(
        cache.path_for(spec.key, _META_FILE),
        json.dumps(metadata, indent=2, sort_keys=True).encode("utf-8") + b"\n",
    )
    return _resolved(spec, destination, metadata)
