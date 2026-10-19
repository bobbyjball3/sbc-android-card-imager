from __future__ import annotations

import re
from pathlib import Path

import typer

from sbc_imager.cannoli import render_markdown
from sbc_imager.cli import app
from sbc_imager.config import load_manifest

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
MANIFEST_DOC = ROOT / "docs" / "manifest.md"
TAG_DOC = ROOT / "docs" / "cannoli-platform-tags.md"

_VALID_BLOCK = re.compile(r"<!-- valid-manifest -->\s*```toml\n(.*?)```", re.DOTALL)
_INLINE_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_COMMAND_INVOCATION = re.compile(r"\bsbc-imager\s+([a-z][a-z0-9-]*)")
_FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")

EXPECTED_COMMANDS = frozenset({"platforms", "plan", "fetch", "build", "verify", "image"})


def _command_names() -> set[str]:
    names: set[str] = set()
    for registered in app.registered_commands:
        if registered.name:
            names.add(registered.name)
        elif registered.callback is not None:
            names.add(registered.callback.__name__.replace("_", "-"))
    for group in app.registered_groups:
        if group.name:
            names.add(group.name)
    return names


def _known_flags() -> set[str]:
    root = typer.main.get_command(app)
    commands = getattr(root, "commands", None)
    if not isinstance(commands, dict):
        raise AssertionError("sbc-imager must be a click group")
    flags: set[str] = {"--help", "--version"}
    parameters = [*getattr(root, "params", ())]
    for command in commands.values():
        parameters.extend(getattr(command, "params", ()))
    for parameter in parameters:
        flags.update(getattr(parameter, "opts", ()))
        flags.update(getattr(parameter, "secondary_opts", ()))
    return flags


def _markdown_files() -> tuple[Path, ...]:
    return (README, MANIFEST_DOC, TAG_DOC)


def _normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _relative_links(path: Path) -> list[str]:
    links: list[str] = []
    for raw in _INLINE_LINK.findall(path.read_text(encoding="utf-8")):
        target = raw.strip().strip("<>")
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        links.append(target.split("#", 1)[0])
    return links


def test_cannoli_tag_doc_when_compared_to_registry_is_current() -> None:
    assert TAG_DOC.read_text(encoding="utf-8") == render_markdown()


def test_cannoli_tag_doc_when_read_explains_how_to_refresh_the_registry() -> None:
    text = _normalized(TAG_DOC)

    assert "## Refreshing the tag registry" in text
    assert "python -m sbc_imager.cannoli --markdown" in text
    assert "CANNOLI_COMMIT" in text
    assert "## Refreshing the tag registry" in render_markdown()


def test_manifest_doc_when_read_scopes_shader_validation_to_local_directories() -> None:
    text = _normalized(MANIFEST_DOC)

    assert "A local shader directory must contain a root `.glslp` preset" in text
    assert "a local shader directory with no root `.glslp`" in text
    assert "A source-relative path with an extension must still be `.glslp`" in text
    assert "a source-relative directory is copied as declared" in text
    assert "is not pre-validated for a root `.glslp`" in text


def test_manifest_doc_when_read_documents_the_branch_warning() -> None:
    text = _normalized(MANIFEST_DOC)

    assert "No warning is printed" not in text
    assert "resolved commit is recorded in the cache metadata" in text
    assert "print a `branch-ref` warning" in text


def test_manifest_doc_when_read_scopes_symlink_checks_to_local_typed_paths() -> None:
    text = _normalized(MANIFEST_DOC)

    assert "a symlink/special file in a local typed `path` tree" in text
    assert "Trees resolved through `[[source]]` (local, git, or URL)" in text
    assert "are not scanned for symlinks or special files by validation" in text


def test_cli_when_introspected_exposes_every_documented_command() -> None:
    registered = _command_names()

    assert registered == set(EXPECTED_COMMANDS)
    for path in _markdown_files():
        for name in _COMMAND_INVOCATION.findall(path.read_text(encoding="utf-8")):
            assert name in registered, f"{path.name} documents unknown command {name!r}"


def test_docs_when_flags_are_named_all_exist_in_the_cli() -> None:
    known = _known_flags()

    for path in _markdown_files():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "sbc-imager" not in line:
                continue
            for flag in _FLAG.findall(line):
                assert flag in known, f"{path.name} documents unknown flag {flag!r}"


def test_manifest_doc_when_valid_toml_blocks_are_loaded_all_parse(tmp_path: Path) -> None:
    blocks = _VALID_BLOCK.findall(MANIFEST_DOC.read_text(encoding="utf-8"))

    assert len(blocks) >= 5
    for index, body in enumerate(blocks):
        path = tmp_path / f"example-{index}.toml"
        path.write_text(body, encoding="utf-8")
        load_manifest(path)


def test_readme_when_read_states_the_real_limitations() -> None:
    text = README.read_text(encoding="utf-8").casefold()

    assert "no apk installation" in text
    assert "no rom, bios, or art downloads" in text
    assert "no zero-touch first boot" in text
    assert "66 mib" in text


def test_docs_when_relative_links_are_followed_resolve_to_files() -> None:
    missing: list[str] = []
    for path in _markdown_files():
        for target in _relative_links(path):
            if not (path.parent / target).exists():
                missing.append(f"{path.name} -> {target}")

    assert missing == []
