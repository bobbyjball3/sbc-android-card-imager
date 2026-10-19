from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sbc_imager.cli import app

runner = CliRunner()


def _touch(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _manifest(tmp_path: Path, body: str, files: tuple[str, ...] = ()) -> Path:
    for name in files:
        _touch(tmp_path / name)
    path = tmp_path / "imager.toml"
    path.write_text(body, encoding="utf-8")
    return path


LOCAL = """
[image]
label = "CANNOLI"

[[rom]]
platform = "GBA"
path = "roms"

[[bios]]
platform = "GBA"
path = "bios.bin"

[[overlay]]
platform = "GBA"
path = "overlays/bezel.png"

[[shader]]
path = "shaders/crt"

[[apk]]
path = "apps/app.apk"

[[artifact]]
root = "card"
dest = "Guides"
path = "guides"
"""

LOCAL_FILES = (
    "roms/demo.gba",
    "bios.bin",
    "overlays/bezel.png",
    "shaders/crt/crt.glslp",
    "shaders/crt/pass.glsl",
    "apps/app.apk",
    "guides/setup.md",
)


@pytest.fixture(autouse=True)
def _cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache = tmp_path / "cache"
    monkeypatch.setenv("SBC_IMAGER_CACHE_DIR", str(cache))
    return cache


def test_plan_when_json_requested_prints_only_json(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, LOCAL, LOCAL_FILES)

    result = runner.invoke(app, ["plan", "--manifest", str(manifest), "--json"])

    assert result.exit_code == 0, result.stderr
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert set(payload) == {"sizes", "entries", "warnings", "sources"}
    assert payload["sizes"]["partition_offset_bytes"] == 1024 * 1024
    assert payload["sizes"]["image_bytes"] > payload["sizes"]["partition_bytes"]
    assert [entry["dest"] for entry in payload["entries"]] == [
        "Cannoli/Roms/GBA/demo.gba",
        "Cannoli/BIOS/GBA/bios.bin",
        "Cannoli/Overlays/GBA/bezel.png",
        "Cannoli/Shaders/crt/crt.glslp",
        "Cannoli/Shaders/crt/pass.glsl",
        "APKs/app.apk",
        "Guides/setup.md",
    ]
    assert payload["warnings"] == []
    assert payload["sources"] == []


def test_plan_when_table_requested_prints_dest_kind_and_totals(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, LOCAL, LOCAL_FILES)

    result = runner.invoke(app, ["plan", "--manifest", str(manifest)])

    assert result.exit_code == 0, result.stderr
    assert "Cannoli/Roms/GBA/demo.gba" in result.stdout
    assert "rom" in result.stdout
    assert "content" in result.stdout.lower()
    assert "image" in result.stdout.lower()


def test_plan_when_strict_and_warning_exists_exits_two(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        '[[rom]]\nplatform = "SATURN"\npath = "roms"\n',
        ("roms/demo.cue",),
    )

    result = runner.invoke(app, ["plan", "--manifest", str(manifest), "--strict"])

    assert result.exit_code == 2
    assert "strict" in result.stderr.lower()
    assert "missing-required-bios" in result.stderr


def test_plan_when_invoked_writes_no_stage_or_image(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, LOCAL, LOCAL_FILES)

    result = runner.invoke(app, ["plan", "--manifest", str(manifest), "--json"])

    assert result.exit_code == 0
    assert not (tmp_path / "work").exists()
    assert not (tmp_path / "stage").exists()
    assert not (tmp_path / "stage-plan.json").exists()
    assert not list(tmp_path.glob("*.img"))


def test_fetch_when_manifest_has_no_sources_prints_empty_json(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, '[image]\nname = "empty"\n')

    result = runner.invoke(app, ["fetch", "--manifest", str(manifest), "--json"])

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == []


def test_fetch_when_local_git_source_populates_the_cache(tmp_path: Path, _cache: Path) -> None:
    bare, commit = _bare_repo(tmp_path)
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "assets"\ntype = "git"\n'
        f'url = "{bare}"\nref = "{commit}"\n'
        'license = "MIT"\nattribution = "Tests"\n',
    )

    result = runner.invoke(app, ["fetch", "--manifest", str(manifest), "--json"])

    assert result.exit_code == 0, result.stderr
    rows = json.loads(result.stdout)
    assert rows[0]["id"] == "assets"
    assert rows[0]["type"] == "git"
    assert rows[0]["root"].startswith(str(_cache))
    repos = list((_cache / "git").glob("*/meta.json"))
    assert len(repos) == 1
    meta = json.loads(repos[0].read_text(encoding="utf-8"))
    assert meta["resolved_commit"] == commit
    assert meta["url"] == str(bare)


def _git_manifest(bare: Path, ref: str) -> str:
    return (
        '[[source]]\nid = "assets"\ntype = "git"\n'
        f'url = "{bare}"\nref = "{ref}"\n'
        'license = "MIT"\nattribution = "Tests"\n\n'
        '[[overlay]]\nplatform = "GBA"\npath = "gba/bezel.png"\nsource = "assets"\n'
    )


def test_plan_when_branch_ref_allowed_prints_warning(tmp_path: Path, _cache: Path) -> None:
    bare, _ = _bare_repo(tmp_path)
    manifest = _manifest(tmp_path, _git_manifest(bare, "main"))

    result = runner.invoke(app, ["plan", "--manifest", str(manifest), "--allow-branch"])

    assert result.exit_code == 0, result.stderr
    assert "branch-ref" in result.stdout
    assert "allow-branch" in result.stdout


def test_plan_when_branch_ref_allowed_includes_json_warning(tmp_path: Path, _cache: Path) -> None:
    bare, _ = _bare_repo(tmp_path)
    manifest = _manifest(tmp_path, _git_manifest(bare, "main"))

    result = runner.invoke(app, ["plan", "--manifest", str(manifest), "--allow-branch", "--json"])

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [warning["code"] for warning in payload["warnings"]] == ["branch-ref"]
    assert "allow-branch" in payload["warnings"][0]["message"]


def test_fetch_when_branch_ref_allowed_prints_warning(tmp_path: Path, _cache: Path) -> None:
    bare, _ = _bare_repo(tmp_path)
    manifest = _manifest(tmp_path, _git_manifest(bare, "main"))

    result = runner.invoke(app, ["fetch", "--manifest", str(manifest), "--allow-branch"])

    assert result.exit_code == 0, result.stderr
    assert "branch-ref" in result.stdout
    assert "allow-branch" in result.stdout


def test_fetch_when_branch_ref_allowed_includes_json_warning(tmp_path: Path, _cache: Path) -> None:
    bare, _ = _bare_repo(tmp_path)
    manifest = _manifest(tmp_path, _git_manifest(bare, "main"))

    result = runner.invoke(app, ["fetch", "--manifest", str(manifest), "--allow-branch", "--json"])

    assert result.exit_code == 0, result.stderr
    rows = json.loads(result.stdout)
    assert [warning["code"] for warning in rows[0]["warnings"]] == ["branch-ref"]
    assert "allow-branch" in rows[0]["warnings"][0]["message"]


def test_plan_and_fetch_when_pinned_commit_emit_no_branch_warning(
    tmp_path: Path, _cache: Path
) -> None:
    bare, commit = _bare_repo(tmp_path)
    manifest = _manifest(tmp_path, _git_manifest(bare, commit))

    planned = runner.invoke(app, ["plan", "--manifest", str(manifest), "--json"])
    fetched = runner.invoke(app, ["fetch", "--manifest", str(manifest), "--json"])

    assert planned.exit_code == 0, planned.stderr
    assert fetched.exit_code == 0, fetched.stderr
    assert json.loads(planned.stdout)["warnings"] == []
    assert "warnings" not in json.loads(fetched.stdout)[0]


def test_fetch_when_cache_is_warm_offline_hits(tmp_path: Path, _cache: Path) -> None:
    bare, commit = _bare_repo(tmp_path)
    manifest = _manifest(
        tmp_path,
        '[[source]]\nid = "assets"\ntype = "git"\n'
        f'url = "{bare}"\nref = "{commit}"\n'
        'license = "MIT"\nattribution = "Tests"\n',
    )
    assert runner.invoke(app, ["fetch", "--manifest", str(manifest)]).exit_code == 0
    bare.rename(bare.with_name("moved.git"))

    result = runner.invoke(app, ["fetch", "--manifest", str(manifest), "--offline", "--json"])

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)[0]["id"] == "assets"


@pytest.mark.parametrize("command", ["plan", "fetch"])
def test_help_when_requested_exits_zero(command: str) -> None:
    result = runner.invoke(app, [command, "--help"])

    assert result.exit_code == 0
    assert command in result.stdout


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    return result.stdout.strip()


def _bare_repo(tmp_path: Path) -> tuple[Path, str]:
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.email", "tests@example.com")
    _git(work, "config", "user.name", "Tests")
    (work / "gba").mkdir()
    (work / "gba" / "bezel.png").write_bytes(b"overlay")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "initial")
    commit = _git(work, "rev-parse", "HEAD")
    bare = tmp_path / "repo.git"
    _git(tmp_path, "clone", "--bare", "-q", str(work), str(bare))
    return bare, commit
