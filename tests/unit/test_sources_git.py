from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from sbc_imager.config import SourceConfig
from sbc_imager.errors import CommandError, ConfigError, SourceError
from sbc_imager.runner import CommandResult, SubprocessRunner
from sbc_imager.sources import SourceCache, resolve_git
from tests.fakes import FakeRunner


@dataclass(frozen=True, slots=True)
class BareRepo:
    path: Path
    commit: str


@pytest.fixture(autouse=True)
def _isolate_git_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def bare_repo(tmp_path: Path) -> BareRepo:
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.email", "tests@example.com")
    _git(work, "config", "user.name", "Tests")
    (work / "sub").mkdir()
    (work / "sub" / "asset.txt").write_text("asset", encoding="utf-8")
    (work / "README.md").write_text("hello", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "initial")
    commit = _git(work, "rev-parse", "HEAD")
    _git(work, "tag", "v1")
    _git(work, "branch", "dev")
    bare = tmp_path / "repo.git"
    _git(tmp_path, "clone", "--bare", "-q", str(work), str(bare))
    return BareRepo(bare, commit)


def _entry(
    url: str,
    *,
    ref: str = "v1",
    subdir: str | None = None,
    source_type: str = "git",
) -> SourceConfig:
    return SourceConfig("src", source_type, url, ref, subdir, None, None, None, None)


def _cache(tmp_path: Path) -> SourceCache:
    return SourceCache(tmp_path / "cache")


def test_resolve_git_when_tag_resolves_to_tagged_commit(
    tmp_path: Path, bare_repo: BareRepo
) -> None:
    cache = _cache(tmp_path)

    resolved = resolve_git(_entry(str(bare_repo.path)), cache, SubprocessRunner())

    assert resolved.kind == "git"
    assert resolved.root.is_dir()
    assert resolved.metadata["ref_kind"] == "tag"
    assert resolved.metadata["resolved_commit"] == bare_repo.commit
    assert resolved.metadata["url"] == str(bare_repo.path)
    key = cache.key(str(bare_repo.path), "v1", "")
    assert resolved.root == (cache.root / "git" / key).resolve()


def test_resolve_git_when_commit_ref_resolves(tmp_path: Path, bare_repo: BareRepo) -> None:
    cache = _cache(tmp_path)

    resolved = resolve_git(
        _entry(str(bare_repo.path), ref=bare_repo.commit), cache, SubprocessRunner()
    )

    assert resolved.root.is_dir()
    assert resolved.metadata["ref_kind"] == "commit"
    assert resolved.metadata["resolved_commit"] == bare_repo.commit


def test_resolve_git_when_branch_without_allow_raises_config_error(
    tmp_path: Path, bare_repo: BareRepo
) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(ConfigError, match="branch"):
        resolve_git(_entry(str(bare_repo.path), ref="dev"), cache, SubprocessRunner())


def test_resolve_git_when_branch_allowed_records_warning(
    tmp_path: Path, bare_repo: BareRepo
) -> None:
    cache = _cache(tmp_path)

    resolved = resolve_git(
        _entry(str(bare_repo.path), ref="dev"), cache, SubprocessRunner(), allow_branch=True
    )

    assert resolved.metadata["ref_kind"] == "branch"
    assert "allow-branch" in resolved.metadata["warning"]


def test_resolve_git_when_offline_and_cached_uses_cache(
    tmp_path: Path, bare_repo: BareRepo
) -> None:
    cache = _cache(tmp_path)
    entry = _entry(str(bare_repo.path))
    first = resolve_git(entry, cache, SubprocessRunner())
    bare_repo.path.rename(bare_repo.path.with_name("moved.git"))

    second = resolve_git(entry, cache, SubprocessRunner(), offline=True)

    assert second.root == first.root
    assert second.metadata["resolved_commit"] == first.metadata["resolved_commit"]


def test_resolve_git_when_offline_and_uncached_raises_source_error_naming_key(
    tmp_path: Path, bare_repo: BareRepo
) -> None:
    cache = _cache(tmp_path)
    key = cache.key(str(bare_repo.path), "v1", "")

    with pytest.raises(SourceError, match=key):
        resolve_git(_entry(str(bare_repo.path)), cache, SubprocessRunner(), offline=True)


def test_resolve_git_when_subdir_resolves_inside_repo(tmp_path: Path, bare_repo: BareRepo) -> None:
    cache = _cache(tmp_path)

    resolved = resolve_git(_entry(str(bare_repo.path), subdir="sub"), cache, SubprocessRunner())

    assert resolved.root.name == "sub"
    assert (resolved.root / "asset.txt").is_file()
    assert resolved.metadata["subdir"] == "sub"


@pytest.mark.parametrize("subdir", ["../escape", "/absolute"])
def test_resolve_git_when_subdir_escapes_raises_config_error(
    tmp_path: Path, bare_repo: BareRepo, subdir: str
) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(ConfigError):
        resolve_git(_entry(str(bare_repo.path), subdir=subdir), cache, SubprocessRunner())


def test_resolve_git_when_subdir_missing_raises_source_error(
    tmp_path: Path, bare_repo: BareRepo
) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(SourceError, match="nope"):
        resolve_git(_entry(str(bare_repo.path), subdir="nope"), cache, SubprocessRunner())


def test_resolve_git_when_cached_redacts_credentials_in_metadata_and_commands(
    tmp_path: Path,
) -> None:
    cache = _cache(tmp_path)
    url = "https://user:secret@example.com/repo.git"
    commit = "a" * 40
    key = cache.key(url, "v1", "")
    repo = cache.root / "git" / key
    repo.mkdir(parents=True)
    (repo / "meta.json").write_text(
        json.dumps(
            {
                "url": url,
                "ref": "v1",
                "ref_kind": "tag",
                "resolved_commit": commit,
                "subdir": "",
                "fetched_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    runner = FakeRunner([CommandResult(("git",), 0, f"{commit}\n", "", 0.0)])

    resolved = resolve_git(_entry(url), cache, runner, offline=True)

    assert resolved.metadata["url"] == "https://example.com/repo.git"
    assert "secret" not in json.dumps(resolved.metadata)
    assert all("secret" not in " ".join(call.args) for call in runner.calls)


def test_resolve_git_when_remote_probe_fails_redacts_credentials(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    url = "https://user:secret@example.com/repo.git"
    runner = FakeRunner(
        [CommandResult(("git", "ls-remote", "--tags", url, "v1"), 1, "", "fatal: auth", 0.0)]
    )

    with pytest.raises(CommandError) as excinfo:
        resolve_git(_entry(url), cache, runner)

    assert "secret" not in str(excinfo.value)
    assert "example.com/repo.git" in str(excinfo.value)


def test_resolve_git_when_online_cache_head_mismatch_refetches(
    tmp_path: Path, bare_repo: BareRepo
) -> None:
    cache = _cache(tmp_path)
    entry = _entry(str(bare_repo.path))
    first = resolve_git(entry, cache, SubprocessRunner())
    meta_path = first.root / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["resolved_commit"] = "0" * 40
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    second = resolve_git(entry, cache, SubprocessRunner())

    assert second.root == first.root
    assert second.metadata["resolved_commit"] == bare_repo.commit


def test_resolve_git_when_offline_and_cache_head_mismatch_raises(
    tmp_path: Path, bare_repo: BareRepo
) -> None:
    cache = _cache(tmp_path)
    entry = _entry(str(bare_repo.path))
    first = resolve_git(entry, cache, SubprocessRunner())
    meta_path = first.root / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["resolved_commit"] = "0" * 40
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(SourceError, match="stale"):
        resolve_git(entry, cache, SubprocessRunner(), offline=True)


def test_resolve_git_when_ref_is_neither_tag_nor_branch_raises_config_error(
    tmp_path: Path, bare_repo: BareRepo
) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(ConfigError, match="neither"):
        resolve_git(_entry(str(bare_repo.path), ref="does-not-exist"), cache, SubprocessRunner())


def test_resolve_git_when_type_is_not_git_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not a git"):
        resolve_git(
            _entry("https://example.com/repo.git", source_type="http"),
            _cache(tmp_path),
            FakeRunner(),
        )


def test_resolve_git_when_url_is_empty_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="url"):
        resolve_git(_entry(""), _cache(tmp_path), FakeRunner())


def test_resolve_git_when_ref_is_empty_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="ref"):
        resolve_git(_entry("https://example.com/repo.git", ref=""), _cache(tmp_path), FakeRunner())
