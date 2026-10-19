"""End-to-end build of the bundled example card, checked against the image."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pytest

from sbc_imager.assembler import assemble
from sbc_imager.assembler_report import Report
from sbc_imager.assembler_steps import MountState, attach_loop, cleanup, mount_filesystem
from sbc_imager.assembler_verify import dirs_path_for, parse_partition, verify_image
from sbc_imager.cannoli import PLATFORM_TAGS
from sbc_imager.config import Manifest, load_manifest
from sbc_imager.planner import BuildPlan, build_plan
from sbc_imager.runner import Runner, SubprocessRunner
from sbc_imager.staging import StageResult, stage
from sbc_imager.validation import validate_manifest
from sbc_imager.verify import build_expected, compare, load_actual_tree

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "linux", reason="loop/mount/exfat require Linux"),
]

MIB = 1024 * 1024
# The planner's minimum overhead is 64 MiB, so a pinned image needs at least
# 1 MiB (offset) + content + 64 MiB. 65 MiB still leaves no room for nonzero
# content, so 66 MiB is the smallest 1 MiB-aligned size that fits this fixture.
IMAGE_SIZE = "66MiB"
ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "examples" / "imager.toml"

REQUIRED_FILES = (
    "APKs/Demo.apk",
    "Cannoli/Roms/GBA/demo.gba",
    "Cannoli/BIOS/GBA/gba_bios.bin",
    "Cannoli/Art/GBA/demo.png",
    "Cannoli/Overlays/GBA/bezel.png",
    "Cannoli/Shaders/crt-lamp/crt-lamp.glslp",
    "Cannoli/Shaders/crt-lamp/crt-lamp.glsl",
    "Manuals/readme.txt",
)


def _build(tmp_path: Path) -> tuple[Manifest, BuildPlan, StageResult, Path, Path, Report]:
    manifest = load_manifest(MANIFEST)
    validate_manifest(manifest)
    plan = build_plan(manifest, {}, size=IMAGE_SIZE)
    staged = stage(plan, tmp_path / "stage-work")
    image = tmp_path / "demo.img"
    work = tmp_path / "assemble-work"
    report = assemble(
        staged.stage_dir,
        staged.stage_plan_path,
        image,
        work,
        SubprocessRunner(),
    )
    return manifest, plan, staged, image, work, report


def _assert_assembler_outputs(image: Path, work: Path, report: Report) -> None:
    assert image.is_file()
    assert not image.with_name(f"{image.name}.partial").exists()
    tree = work / "tree.json"
    report_path = work / "report.json"
    assert tree.is_file()
    assert report_path.is_file()
    assert report.fsck_ok is True
    assert report.label == "CANNOLI"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["fsck_ok"] is True
    assert payload["tree_sha256"] == hashlib.sha256(tree.read_bytes()).hexdigest()


def _assert_tree(root: Path) -> None:
    assert len(PLATFORM_TAGS) == 51
    for tag in PLATFORM_TAGS:
        assert (root / "Cannoli" / "Roms" / tag).is_dir(), tag
    assert (root / "Cannoli/Config/settings.json").read_text(encoding="utf-8") == "{}\n"
    credits = (root / "CREDITS.md").read_text(encoding="utf-8")
    assert "Cannoli" in credits
    assert "GPL-3.0" in credits
    for relative in REQUIRED_FILES:
        assert (root / relative).is_file(), relative


def _assert_hashes(root: Path, staged: StageResult) -> None:
    for entry in staged.entries:
        data = (root / entry.dest).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry.sha256, entry.dest


def _assert_no_loops(runner: Runner, image: Path) -> None:
    output = runner.run(["losetup", "-a"], check=False).stdout
    assert str(image) not in output, output


def test_build_e2e_when_example_is_valid_produces_verified_card(tmp_path: Path) -> None:
    if os.geteuid() != 0:
        pytest.skip("requires root to attach loops and mount exFAT")
    manifest, plan, staged, image, work, report = _build(tmp_path)
    runner = SubprocessRunner()

    assert plan.image_bytes == 66 * MIB
    assert image.stat().st_size == plan.image_bytes
    assert report.content_files == len(plan.entries)
    assert report.content_bytes == plan.content_bytes
    _assert_assembler_outputs(image, work, report)

    expected = build_expected(manifest, {})
    verify_dir = tmp_path / "verify"
    tree_path = verify_dir / "tree.json"
    verify_image(image, tree_path, verify_dir, SubprocessRunner())
    actual = load_actual_tree(tree_path, dirs_path_for(tree_path))
    comparison = compare(expected, actual)
    assert comparison.ok is True, comparison.payload()
    for entry in staged.entries:
        assert actual.files[entry.dest.as_posix()] == entry.sha256

    sfdisk = runner.run(["sfdisk", "-d", str(image)]).stdout
    assert re.search(r"start=\s*2048\b", sfdisk), sfdisk
    assert re.search(r"(?:Id=\s*7\b|type=\s*7\b)", sfdisk), sfdisk
    partition = parse_partition(image.read_bytes()[:512])
    assert (partition.start_lba, partition.type_) == (2048, 7)

    loop = attach_loop(runner, image, partition.offset_bytes, partition.size_bytes)
    mountpoint = tmp_path / "mnt"
    mountpoint.mkdir()
    mounted = False
    try:
        fsck = runner.run(["fsck.exfat", "-n", loop], check=False)
        assert fsck.returncode == 0, fsck.stderr
        mount_filesystem(runner, loop, mountpoint, readonly=True)
        mounted = True
        _assert_tree(mountpoint)
        _assert_hashes(mountpoint, staged)
    finally:
        cleanup(runner, MountState(mountpoint, loop, mounted))
    _assert_no_loops(runner, image)
