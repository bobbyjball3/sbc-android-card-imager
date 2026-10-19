from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from sbc_imager import assembler_verify, fs
from sbc_imager.assembler import assemble
from sbc_imager.assembler_steps import (
    MountState,
    attach_loop,
    cleanup,
    mount_filesystem,
    unmount,
)
from sbc_imager.config import load_manifest
from sbc_imager.planner import build_plan
from sbc_imager.runner import SubprocessRunner
from sbc_imager.staging import stage
from sbc_imager.verify import build_expected, compare, load_actual_tree

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "linux", reason="loop/mount/exfat require Linux"),
]

GBA_ROM = "Cannoli/Roms/GBA/demo.gba"

MANIFEST = """
[image]
name = "verify"
reserve = "1MiB"

[[rom]]
platform = "GBA"
path = "roms"

[[bios]]
platform = "GBA"
path = "bios.bin"

[[apk]]
path = "apps/app.apk"
"""


def _touch(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _manifest(tmp_path: Path) -> Path:
    _touch(tmp_path / "roms/demo.gba", b"DEMO ROM\n")
    _touch(tmp_path / "bios.bin", b"BIOS\n")
    _touch(tmp_path / "apps/app.apk", b"APK\n")
    path = tmp_path / "imager.toml"
    path.write_text(MANIFEST, encoding="utf-8")
    return path


def _tamper(runner: SubprocessRunner, image: Path, mountpoint: Path) -> None:
    partition = assembler_verify.parse_partition(image.read_bytes()[:512])
    loop: str | None = None
    mounted = False
    try:
        loop = attach_loop(runner, image, partition.offset_bytes, partition.size_bytes)
        mount_filesystem(runner, loop, mountpoint, readonly=False)
        mounted = True
        (mountpoint / GBA_ROM).write_bytes(b"TAMPERED\n")
        os.sync()
        unmount(runner, mountpoint)
        mounted = False
    finally:
        cleanup(runner, MountState(mountpoint, loop, mounted))


def test_verify_when_image_matches_passes_and_tampering_fails(tmp_path: Path) -> None:
    if os.geteuid() != 0:
        pytest.skip("requires root to attach loops and mount exFAT")
    runner = SubprocessRunner()
    manifest = load_manifest(_manifest(tmp_path))
    plan = build_plan(manifest, {})
    staged = stage(plan, tmp_path / "stage-work")
    image = tmp_path / "card.img"
    assemble(
        staged.stage_dir,
        staged.stage_plan_path,
        image,
        tmp_path / "assemble-work",
        runner,
    )
    expected = build_expected(manifest, {})
    before = fs.sha256_file(image)

    tree_path = tmp_path / "verify" / "tree.json"
    assembler_verify.verify_image(image, tree_path, tmp_path / "verify-work", runner)
    actual = load_actual_tree(tree_path, assembler_verify.dirs_path_for(tree_path))
    report = compare(expected, actual)

    assert report.ok is True, report.payload()
    assert actual.files[GBA_ROM] == expected.files[GBA_ROM]
    assert "Cannoli/Roms/SNES" in actual.dirs
    assert fs.sha256_file(image) == before

    mountpoint = tmp_path / "tamper-mnt"
    mountpoint.mkdir()
    _tamper(runner, image, mountpoint)

    second_tree = tmp_path / "verify-tampered" / "tree.json"
    assembler_verify.verify_image(image, second_tree, tmp_path / "verify-tampered-work", runner)
    tampered = load_actual_tree(second_tree, assembler_verify.dirs_path_for(second_tree))
    tampered_report = compare(expected, tampered)

    assert tampered_report.ok is False
    assert tampered_report.mismatched == (GBA_ROM,)
