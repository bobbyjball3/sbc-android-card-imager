from __future__ import annotations

import io
import plistlib
from collections.abc import Sequence
from pathlib import Path

import pytest
from rich.console import Console

from sbc_imager.errors import SafetyError
from sbc_imager.imaging import DiskInfo, enumerate_disks, render_table
from sbc_imager.runner import CommandResult
from sbc_imager.sizes import format_size
from tests.fakes import FakeRunner

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "diskutil"


def _load(name: str) -> dict[str, object]:
    with (FIXTURES / name).open("rb") as handle:
        data: object = plistlib.load(handle)
    if not isinstance(data, dict):
        raise AssertionError(f"{name} is not a plist dictionary")
    return {str(key): value for key, value in data.items()}


def _result(command: Sequence[str], data: dict[str, object]) -> CommandResult:
    return CommandResult(tuple(command), 0, plistlib.dumps(data).decode("utf-8"), "", 0.01)


def _runner(
    info_names: Sequence[str],
    *,
    list_name: str = "list.plist",
    root_name: str = "info-root.plist",
) -> FakeRunner:
    results = [
        _result(("diskutil", "list", "-plist"), _load(list_name)),
        _result(("diskutil", "info", "-plist", "/"), _load(root_name)),
    ]
    for name in info_names:
        data = _load(name)
        identifier = data["DeviceIdentifier"]
        assert isinstance(identifier, str)
        results.append(_result(("diskutil", "info", "-plist", f"/dev/{identifier}"), data))
    return FakeRunner(results=results)


MAIN_INFOS = (
    "info-internal.plist",
    "info-disk-image.plist",
    "info-external-usb.plist",
    "info-boot.plist",
    "info-builtin-sd.plist",
)


def test_enumerate_disks_when_external_usb_removable_is_present_includes_it() -> None:
    runner = _runner(MAIN_INFOS)

    disks = enumerate_disks(runner)

    assert disks == [
        DiskInfo(
            identifier="disk9",
            size=63_864_373_248,
            label="SDCARD",
            model="SanDisk Ultra",
            protocol="USB",
            internal=False,
            removable=True,
            ejectable=True,
            whole=True,
            serial="0123456789AB",
        )
    ]
    assert runner.commands == [
        ["diskutil", "list", "-plist"],
        ["diskutil", "info", "-plist", "/"],
        ["diskutil", "info", "-plist", "/dev/disk0"],
        ["diskutil", "info", "-plist", "/dev/disk4"],
        ["diskutil", "info", "-plist", "/dev/disk9"],
        ["diskutil", "info", "-plist", "/dev/disk10"],
        ["diskutil", "info", "-plist", "/dev/disk11"],
    ]


def test_enumerate_disks_when_internal_disk_is_present_filters_it() -> None:
    disks = enumerate_disks(_runner(MAIN_INFOS))

    assert "disk0" not in {disk.identifier for disk in disks}


def test_enumerate_disks_when_disk_image_is_present_filters_it() -> None:
    disks = enumerate_disks(_runner(MAIN_INFOS))

    assert "disk4" not in {disk.identifier for disk in disks}


def test_enumerate_disks_when_boot_disk_is_present_rejects_it() -> None:
    disks = enumerate_disks(_runner(MAIN_INFOS))

    assert "disk10" not in {disk.identifier for disk in disks}


def test_enumerate_disks_when_builtin_sd_reader_is_internal_rejects_it() -> None:
    disks = enumerate_disks(_runner(MAIN_INFOS))

    assert "disk11" not in {disk.identifier for disk in disks}


def test_enumerate_disks_when_external_usb_has_no_removable_flags_includes_by_protocol() -> None:
    disks = enumerate_disks(
        _runner(("info-usb-protocol-only.plist",), list_name="list-external-only.plist")
    )

    assert [disk.identifier for disk in disks] == ["disk9"]


@pytest.mark.parametrize(
    "fixture",
    ["info-missing-internal.plist", "info-missing-whole.plist", "info-missing-virtual.plist"],
)
def test_enumerate_disks_when_required_key_missing_fails_closed(fixture: str) -> None:
    runner = _runner((fixture,), list_name="list-external-only.plist")

    with pytest.raises(SafetyError):
        enumerate_disks(runner)


@pytest.mark.parametrize(
    "fixture",
    ["info-internal.plist", "info-builtin-sd.plist", "info-disk-image.plist"],
)
def test_enumerate_disks_when_external_slot_returns_unsafe_info_never_includes_it(
    fixture: str,
) -> None:
    disks = enumerate_disks(_runner((fixture,), list_name="list-external-only.plist"))

    assert disks == []


def test_enumerate_disks_when_root_parent_whole_disk_missing_fails_closed() -> None:
    runner = _runner(
        ("info-external-usb.plist",),
        list_name="list-external-only.plist",
        root_name="info-root-missing-parent.plist",
    )

    with pytest.raises(SafetyError):
        enumerate_disks(runner)


def test_enumerate_disks_when_listing_missing_all_disks_fails_closed() -> None:
    runner = FakeRunner(results=[_result(("diskutil", "list", "-plist"), {"AllDisks": []})])

    with pytest.raises(SafetyError):
        enumerate_disks(runner)


def test_enumerate_disks_when_same_whole_disk_repeated_queries_it_once() -> None:
    runner = _runner(("info-external-usb.plist",), list_name="list-duplicate.plist")

    disks = enumerate_disks(runner)

    assert [disk.identifier for disk in disks] == ["disk9"]
    info_commands = [command for command in runner.commands if command[1] == "info"]
    assert info_commands.count(["diskutil", "info", "-plist", "/dev/disk9"]) == 1


def test_render_table_when_serial_present_shows_identity_size_model_protocol_and_serial() -> None:
    disk = enumerate_disks(_runner(MAIN_INFOS))[0]
    output = io.StringIO()
    console = Console(file=output, width=200, force_terminal=False, color_system=None)

    render_table(console, [disk])

    rendered = output.getvalue()
    assert "disk9" in rendered
    assert "SDCARD" in rendered
    assert format_size(disk.size) in rendered
    assert "SanDisk Ultra" in rendered
    assert "USB" in rendered
    assert "0123456789AB" in rendered
