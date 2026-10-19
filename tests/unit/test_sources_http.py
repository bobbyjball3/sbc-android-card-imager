from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest

from sbc_imager.config import SourceConfig
from sbc_imager.errors import ConfigError, SourceError
from sbc_imager.sources import ResolvedSource, SourceCache, resolve_http

PAYLOAD = b"Cannoli ROM payload \x00\xff" * 3
SHA = hashlib.sha256(PAYLOAD).hexdigest()
URL = "https://example.com/files/rom.gba"


def _entry(
    url: str = URL,
    *,
    sha256: str | None = SHA,
    filename: str | None = None,
    source_type: str = "url",
    entry_id: str = "roms",
) -> SourceConfig:
    return SourceConfig(entry_id, source_type, url, None, None, filename, sha256, None, None)


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    )


def _cache(tmp_path: Path) -> SourceCache:
    return SourceCache(tmp_path / "cache")


def _cached(cache: SourceCache, sha: str = SHA, filename: str = "rom.gba") -> Path:
    return cache.root / "http" / sha / filename


def _files(cache: SourceCache) -> list[Path]:
    return [path for path in cache.root.rglob("*") if path.is_file()]


def _network_forbidden(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected network request to {request.url}")


def test_resolve_http_when_success_streams_exact_bytes_to_cache(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=PAYLOAD)

    cache = _cache(tmp_path)

    resolved = resolve_http(_entry(), cache, _client(handler))

    expected = ResolvedSource(
        id="roms",
        root=_cached(cache),
        kind="url",
        metadata={"url": URL, "sha256": SHA, "filename": "rom.gba"},
    )
    assert resolved == expected
    assert resolved.root.read_bytes() == PAYLOAD
    assert [str(request.url) for request in seen] == [URL]
    assert [path.name for path in _cached(cache).parent.iterdir()] == ["rom.gba"]


def test_resolve_http_when_filename_configured_uses_it(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    resolved = resolve_http(
        _entry(filename="renamed.gba"),
        cache,
        _client(lambda _request: httpx.Response(200, content=PAYLOAD)),
    )

    assert resolved.root == _cached(cache, filename="renamed.gba")
    assert resolved.metadata["filename"] == "renamed.gba"


def test_resolve_http_when_filename_missing_uses_url_path_basename(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    resolved = resolve_http(
        _entry(url="https://example.com/downloads/rom.gba?token=secret"),
        cache,
        _client(lambda _request: httpx.Response(200, content=PAYLOAD)),
    )

    assert resolved.root == _cached(cache)
    assert resolved.metadata["filename"] == "rom.gba"


def test_resolve_http_when_checksum_mismatch_raises_and_leaves_no_files(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(SourceError, match="checksum"):
        resolve_http(
            _entry(),
            cache,
            _client(lambda _request: httpx.Response(200, content=b"tampered")),
        )

    assert _files(cache) == []
    assert not _cached(cache).exists()


def test_resolve_http_when_status_error_mentions_status(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(SourceError, match="404"):
        resolve_http(_entry(), cache, _client(lambda _request: httpx.Response(404)))

    assert _files(cache) == []


def test_resolve_http_when_redirect_followed_resolves_final_body(tmp_path: Path) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/files/rom.gba":
            return httpx.Response(302, headers={"Location": "https://example.com/final/rom.gba"})
        return httpx.Response(200, content=PAYLOAD)

    cache = _cache(tmp_path)

    resolved = resolve_http(_entry(), cache, _client(handler))

    assert resolved.root.read_bytes() == PAYLOAD
    assert seen == ["/files/rom.gba", "/final/rom.gba"]


def test_resolve_http_when_offline_and_cached_does_not_call_client(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    online = resolve_http(
        _entry(),
        cache,
        _client(lambda _request: httpx.Response(200, content=PAYLOAD)),
    )

    offline = resolve_http(_entry(), cache, _client(_network_forbidden), offline=True)

    assert offline == online


def test_resolve_http_when_offline_and_missing_raises_naming_checksum(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(SourceError, match=SHA):
        resolve_http(_entry(), cache, _client(_network_forbidden), offline=True)


def test_resolve_http_when_offline_and_cache_corrupt_raises_naming_checksum(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    resolved = resolve_http(
        _entry(),
        cache,
        _client(lambda _request: httpx.Response(200, content=PAYLOAD)),
    )
    resolved.root.write_bytes(b"corrupted")

    with pytest.raises(SourceError, match=SHA):
        resolve_http(_entry(), cache, _client(_network_forbidden), offline=True)


@pytest.mark.parametrize(
    "filename",
    ["", ".", "..", "a/b.gba", "a\\b.gba", "bad\x00name.gba", "%2e%2e"],
)
def test_resolve_http_when_filename_unsafe_raises_config_error(
    tmp_path: Path, filename: str
) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(ConfigError, match="filename"):
        resolve_http(
            _entry(filename=filename),
            cache,
            _client(lambda _request: httpx.Response(200, content=PAYLOAD)),
        )


def test_resolve_http_when_url_has_no_basename_raises_config_error(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(ConfigError, match="filename"):
        resolve_http(
            _entry(url="https://example.com/"),
            cache,
            _client(lambda _request: httpx.Response(200, content=PAYLOAD)),
        )


@pytest.mark.parametrize(
    "sha256",
    [None, "", "abc123", SHA.upper(), "g" * 64, SHA[:-1]],
)
def test_resolve_http_when_sha256_invalid_raises_config_error(
    tmp_path: Path, sha256: str | None
) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(ConfigError, match="sha256"):
        resolve_http(
            _entry(sha256=sha256),
            cache,
            _client(lambda _request: httpx.Response(200, content=PAYLOAD)),
        )


@pytest.mark.parametrize(
    "url",
    ["ftp://example.com/rom.gba", "file:///tmp/rom.gba", "https:///rom.gba", "example.com/rom.gba"],
)
def test_resolve_http_when_url_not_http_raises_config_error(tmp_path: Path, url: str) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(ConfigError, match="url"):
        resolve_http(
            _entry(url=url),
            cache,
            _client(lambda _request: httpx.Response(200, content=PAYLOAD)),
        )


def test_resolve_http_when_type_is_not_url_raises_config_error(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(ConfigError, match="url"):
        resolve_http(
            _entry(source_type="git"),
            cache,
            _client(lambda _request: httpx.Response(200, content=PAYLOAD)),
        )


def test_resolve_http_when_request_error_redacts_credentials(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    url = "https://user:secret@example.com/files/rom.gba"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(SourceError) as excinfo:
        resolve_http(_entry(url=url), cache, _client(handler))

    message = str(excinfo.value)
    assert "secret" not in message
    assert "example.com/files/rom.gba" in message


def test_resolve_http_when_success_redacts_credentials_in_metadata(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    resolved = resolve_http(
        _entry(url="https://user:secret@example.com/files/rom.gba"),
        cache,
        _client(lambda _request: httpx.Response(200, content=PAYLOAD)),
    )

    assert resolved.metadata["url"] == URL
    assert "secret" not in str(resolved.metadata)


class _ChunkStream(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        yield from self._chunks

    def close(self) -> None:
        self.closed = True


def test_resolve_http_when_body_arrives_in_chunks_streams_each_chunk(tmp_path: Path) -> None:
    stream = _ChunkStream([PAYLOAD[:10], PAYLOAD[10:]])
    cache = _cache(tmp_path)

    resolved = resolve_http(
        _entry(),
        cache,
        _client(lambda _request: httpx.Response(200, stream=stream)),
    )

    assert resolved.root.read_bytes() == PAYLOAD
    assert stream.closed
