from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from sbc_imager.config import SourceConfig
from sbc_imager.errors import ConfigError, SourceError
from sbc_imager.sources import ResolvedSource, SourceCache
from sbc_imager.sources_github import resolve_github

REPO = "ImranR98/Obtainium"
TAG = "v1.7.1"
ASSET = "app-arm64-v8a-release.apk"
PAYLOAD = b"pinned Obtainium APK payload \x00\xff" * 4
SHA = hashlib.sha256(PAYLOAD).hexdigest()
ASSET_URL = f"https://github.com/{REPO}/releases/download/{TAG}/{ASSET}"
RELEASE_URL = f"https://github.com/{REPO}/releases/tag/{TAG}"
RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}"
REPO_API = f"https://api.github.com/repos/{REPO}"
LICENSE = "GPL-3.0"


@pytest.fixture(autouse=True)
def _no_github_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


def _entry(
    *,
    sha256: str | None = None,
    license: str | None = None,
    attribution: str | None = None,
    repo: str | None = REPO,
    tag: str | None = TAG,
    asset: str | None = ASSET,
    source_type: str = "github",
) -> SourceConfig:
    return SourceConfig(
        "obtainium",
        source_type,
        None,
        None,
        None,
        None,
        sha256,
        license,
        attribution,
        repo,
        tag,
        asset,
    )


def _asset(
    *,
    name: str = ASSET,
    digest: str | None = f"sha256:{SHA}",
    size: int | None = len(PAYLOAD),
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "browser_download_url": ASSET_URL,
    }
    if digest is not None:
        payload["digest"] = digest
    if size is not None:
        payload["size"] = size
    return payload


def _handler(
    *,
    assets: list[dict[str, object]] | None = None,
    spdx: str | None = LICENSE,
    seen: list[httpx.Request] | None = None,
    payload: bytes = PAYLOAD,
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        url = str(request.url)
        if url == RELEASE_API:
            return httpx.Response(
                200,
                json={
                    "tag_name": TAG,
                    "html_url": RELEASE_URL,
                    "assets": assets if assets is not None else [_asset()],
                },
            )
        if url == REPO_API:
            license_value = None if spdx is None else {"spdx_id": spdx}
            return httpx.Response(200, json={"license": license_value})
        if url == ASSET_URL:
            return httpx.Response(200, content=payload)
        return httpx.Response(404)

    return handler


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    )


def _network_forbidden(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected network request to {request.url}")


def _cache(tmp_path: Path) -> SourceCache:
    return SourceCache(tmp_path / "cache")


def _key(cache: SourceCache) -> str:
    return cache.key("github", REPO, TAG, ASSET)


def _asset_path(cache: SourceCache) -> Path:
    return cache.root / _key(cache) / "files" / ASSET


def _meta_path(cache: SourceCache) -> Path:
    return cache.root / _key(cache) / "source.json"


def _files(cache: SourceCache) -> list[Path]:
    return [path for path in cache.root.rglob("*") if path.is_file()]


def test_resolve_github_when_pinned_asset_uses_api_digest_and_license(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    cache = _cache(tmp_path)

    resolved = resolve_github(_entry(), cache, _client(_handler(seen=seen)))

    expected = ResolvedSource(
        id="obtainium",
        root=_asset_path(cache),
        kind="github",
        metadata={
            "repo": REPO,
            "tag": TAG,
            "asset": ASSET,
            "url": ASSET_URL,
            "sha256": SHA,
            "size": str(len(PAYLOAD)),
            "license": LICENSE,
            "attribution": f"{REPO} ({RELEASE_URL})",
            "release_url": RELEASE_URL,
        },
    )
    assert resolved == expected
    assert resolved.root.read_bytes() == PAYLOAD
    assert json.loads(_meta_path(cache).read_text(encoding="utf-8")) == resolved.metadata
    assert [str(request.url) for request in seen] == [RELEASE_API, REPO_API, ASSET_URL]
    for request in seen:
        assert request.headers["Accept"] == "application/vnd.github+json"
        assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
        assert request.headers["User-Agent"] == "sbc-imager"
        assert "Authorization" not in request.headers


def test_resolve_github_when_api_has_no_digest_downloads_and_computes(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    seen: list[httpx.Request] = []

    resolved = resolve_github(
        _entry(),
        cache,
        _client(_handler(assets=[_asset(digest=None)], seen=seen)),
    )

    assert resolved.metadata["sha256"] == SHA
    assert [str(request.url) for request in seen] == [RELEASE_API, REPO_API, ASSET_URL]


def test_resolve_github_when_digest_mismatch_raises_and_leaves_no_asset(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    wrong = "0" * 64

    with pytest.raises(SourceError, match="checksum mismatch"):
        resolve_github(
            _entry(),
            cache,
            _client(_handler(assets=[_asset(digest=f"sha256:{wrong}")])),
        )

    assert _files(cache) == []
    assert not _asset_path(cache).exists()
    assert not _meta_path(cache).exists()


def test_resolve_github_when_asset_name_missing_lists_available_names(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(SourceError) as caught:
        resolve_github(
            _entry(asset="missing.apk"),
            cache,
            _client(_handler(assets=[_asset(name="other-apk.apk")])),
        )

    message = str(caught.value)
    assert "missing.apk" in message
    assert "other-apk.apk" in message


def test_resolve_github_when_license_is_noassertion_without_override_raises(
    tmp_path: Path,
) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(SourceError, match="license") as caught:
        resolve_github(_entry(), cache, _client(_handler(spdx="NOASSERTION")))

    assert caught.value.hint is not None
    assert "license" in caught.value.hint


def test_resolve_github_when_license_override_skips_repository_request(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    seen: list[httpx.Request] = []

    resolved = resolve_github(
        _entry(license="MIT"),
        cache,
        _client(_handler(spdx="NOASSERTION", seen=seen)),
    )

    assert resolved.metadata["license"] == "MIT"
    assert [str(request.url) for request in seen] == [RELEASE_API, ASSET_URL]


def test_resolve_github_when_attribution_override_wins(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    resolved = resolve_github(
        _entry(attribution="Obtainium by ImranR98"),
        cache,
        _client(_handler()),
    )

    assert resolved.metadata["attribution"] == "Obtainium by ImranR98"


def test_resolve_github_when_cached_offline_never_calls_network(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    online = resolve_github(_entry(), cache, _client(_handler()))

    offline = resolve_github(_entry(), cache, _client(_network_forbidden), offline=True)

    assert offline == online
    assert offline.root.read_bytes() == PAYLOAD


def test_resolve_github_when_offline_and_missing_cache_raises(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(SourceError, match="offline"):
        resolve_github(_entry(), cache, _client(_network_forbidden), offline=True)


def test_resolve_github_when_offline_and_asset_corrupt_raises(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    resolved = resolve_github(_entry(), cache, _client(_handler()))
    resolved.root.write_bytes(b"tampered")

    with pytest.raises(SourceError, match="corrupt"):
        resolve_github(_entry(), cache, _client(_network_forbidden), offline=True)


def test_resolve_github_when_manifest_sha256_disagrees_with_api_raises(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    seen: list[httpx.Request] = []

    with pytest.raises(SourceError, match="disagrees"):
        resolve_github(
            _entry(sha256="1" * 64),
            cache,
            _client(_handler(seen=seen)),
        )

    assert [str(request.url) for request in seen] == [RELEASE_API, REPO_API]


def test_resolve_github_when_manifest_sha256_matches_api_succeeds(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    resolved = resolve_github(_entry(sha256=SHA.upper()), cache, _client(_handler()))

    assert resolved.metadata["sha256"] == SHA


def test_resolve_github_when_offline_sha256_override_disagrees_raises(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    resolve_github(_entry(), cache, _client(_handler()))

    with pytest.raises(SourceError, match="does not match the cached asset"):
        resolve_github(
            _entry(sha256="2" * 64),
            cache,
            _client(_network_forbidden),
            offline=True,
        )


def test_resolve_github_when_release_is_404_mentions_status(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(SourceError, match="404") as caught:
        resolve_github(
            _entry(),
            cache,
            _client(lambda _request: httpx.Response(404)),
        )

    assert caught.value.hint is None


@pytest.mark.parametrize("status", [403, 429])
def test_resolve_github_when_rate_limited_hints_at_github_token(
    tmp_path: Path, status: int
) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(SourceError, match=str(status)) as caught:
        resolve_github(
            _entry(),
            cache,
            _client(lambda _request: httpx.Response(status)),
        )

    assert caught.value.hint is not None
    assert "GITHUB_TOKEN" in caught.value.hint


def test_resolve_github_when_token_is_set_sends_bearer_without_leaking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "super-secret-token")
    cache = _cache(tmp_path)
    seen: list[httpx.Request] = []

    resolved = resolve_github(_entry(), cache, _client(_handler(seen=seen)))

    assert seen
    assert all(request.headers["Authorization"] == "Bearer super-secret-token" for request in seen)
    assert "super-secret-token" not in str(resolved.metadata)
    assert "super-secret-token" not in _meta_path(cache).read_text(encoding="utf-8")


def test_resolve_github_when_payload_is_not_json_raises(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(SourceError, match="valid JSON"):
        resolve_github(
            _entry(),
            cache,
            _client(lambda _request: httpx.Response(200, content=b"not json")),
        )


def test_resolve_github_when_request_error_raises(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(SourceError, match="ConnectError"):
        resolve_github(_entry(), cache, _client(handler))


def test_resolve_github_when_size_mismatch_raises(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(SourceError, match="size mismatch"):
        resolve_github(
            _entry(),
            cache,
            _client(_handler(assets=[_asset(size=len(PAYLOAD) + 1)])),
        )


def test_resolve_github_when_cached_asset_is_valid_reuses_without_download(
    tmp_path: Path,
) -> None:
    cache = _cache(tmp_path)
    resolve_github(_entry(), cache, _client(_handler()))
    seen: list[httpx.Request] = []

    resolved = resolve_github(_entry(), cache, _client(_handler(seen=seen)))

    assert resolved.root == _asset_path(cache)
    assert [str(request.url) for request in seen] == [RELEASE_API, REPO_API]


def test_resolve_github_when_type_is_not_github_raises(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(ConfigError, match="not a github"):
        resolve_github(
            _entry(source_type="git"),
            cache,
            _client(_network_forbidden),
        )


@pytest.mark.parametrize(
    ("repo", "tag", "asset"),
    [
        (None, TAG, ASSET),
        (REPO, None, ASSET),
        (REPO, TAG, None),
        ("no-slash", TAG, ASSET),
        ("owner/", TAG, ASSET),
        (REPO, TAG, "../escape.apk"),
        (REPO, TAG, "nested/asset.apk"),
    ],
)
def test_resolve_github_when_spec_is_invalid_raises_config_error(
    tmp_path: Path, repo: str | None, tag: str | None, asset: str | None
) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(ConfigError):
        resolve_github(
            _entry(repo=repo, tag=tag, asset=asset),
            cache,
            _client(_network_forbidden),
        )
