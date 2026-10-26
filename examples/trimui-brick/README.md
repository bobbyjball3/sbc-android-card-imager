# TrimUI Brick NextUI card

A pinned example for a TrimUI Brick running NextUI with the Grout RomM client:
the official NextUI `-all` release plus a pinned Grout pak, staged by Ansible
from [`ansible/vars/trimui-brick.yml`](../../ansible/vars/trimui-brick.yml) and
built into a sparse `.img` by the container builder. You write that image to a
card with `dd` or balenaEtcher - the tool never writes a device.

See [`docs/nextui-layout.md`](../../docs/nextui-layout.md) for the full on-card
layout, first-boot behavior, and licensing details.

## Device

The TrimUI Brick runs NextUI from an MBR-partitioned microSD card and uses the
**`tg5040`** platform directory. The Brick Pro and Smart Pro share `tg5040`;
the Smart Pro S uses `tg5050` and is out of scope for this profile.

This is not an Android or Cannoli card. The image is payload-only: a pre-seeded
NextUI card, not an official NextUI image and not a bootloader/OS flash.

## Pins

The device vars file pins two remote GitHub release archives:

| Item | Pin | Card destination | Size | SHA-256 | License |
| --- | --- | --- | --- | --- | --- |
| NextUI | `LoveRetro/NextUI` tag `v6.15.0`, asset `NextUI-20261013-0-all.zip` | card root (`.`) | 243,439,698 bytes | `d5edceaa92d0264f34da87f017a40fb8244dc3081f894f17c6979ffe94c4c38a` | PolyForm Noncommercial 1.0.0 |
| Grout | `rommapp/grout` tag `v5.4.0.0`, asset `Grout.pak.zip` | `Tools/tg5040/Grout.pak` | 24,839,934 bytes | `eb5ffa37aca0d484e1c8c16f16c8cf4e7a74f798d5a023ea907f99d6cea45328` | MIT |

The playbook downloads both archives from their exact GitHub release tags into
`build/cache`, verifies the cached SHA-256, and extracts them into the payload
tree. There are no mutable selectors. Neither archive is vendored in this
repository. NextUI is personal/noncommercial-use software; do not redistribute
the resulting image commercially.

Asset names embed upstream build dates. When refreshing a pin, update the vars,
this table, the layout doc, and the test expectations together.

## Layout and first boot

The staged card root has fifteen top-level entries: `Bios/`, `Cheats/`,
`Emus/`, `Overlays/`, `README.txt`, `Roms/`, `Saves/`, `Shaders/`, `Tools/`,
`MinUI.zip`, `h700/`, `trimui/`, `nextui.pak_store.pakz`,
`nextui.updater.pakz`, and `nextui.upgrade_bluez.tg5040.pakz`. There is no
`em_ui.sh` in the real v6.15.0 `-all` asset, and `MinUI.zip` stays zipped.

The first boot runs the normal NextUI installer. It removes `MinUI.zip`, the
`.pakz` packages, and `trimui/`, then creates `.system/`, `.tmp_update/`, and
`.userdata/`. The card after first boot intentionally differs from the built
image. `Tools/tg5040/Grout.pak` is not part of that removal. Do not power off
during installation; power the device on again when it completes.

Start from a supported device running the stock TrimUI OS. If another CFW was
used, reinstall stock OS first. No minimum stock firmware version is
documented. The upstream installer may also modify the device itself, not just
the card; read the upstream release notes before booting.

Hardware boot of this exFAT image has **not** been verified by this project.
The tests prove the image contents and filesystem, not the Brick firmware's
behavior.

## Build

Build the container once, then use the `task` target or the underlying playbook
command from the repository root:

```shell
task container   # docker build -t sbc-imager-builder:local .
```

Recommended: size the image read-only from the actual card, then build:

```shell
task image DEVICE=trimui-brick IMAGE_DEVICE=/dev/diskN
```

`IMAGE_DEVICE` only reads `diskutil info -plist`, asserts the `WholeDisk` flag,
and computes the image size from `TotalSize`; it never writes the device. Pass
`-e image_device=` (or omit `IMAGE_DEVICE`) to use an explicit size instead.

Explicit size fallback (the device vars pin `image_size_mib: 8192`):

```shell
task image DEVICE=trimui-brick SIZE_MIB=8192
```

NextUI builds require at least 1024 MiB. The default output is
`dist/trimui-brick.img`, the label is `NEXTUI`, and the image is published
atomically via `dist/trimui-brick.img.partial` + `mv`.

To stage the payload tree without invoking the container:

```shell
uv run ansible-playbook ansible/build.yml --tags payload \
  -e device=trimui-brick -e image_size_mib=8192
```

All `sfdisk`, `mkfs.exfat`, mount, and `fsck.exfat -n` work happens inside the
pinned Linux container. Defaults are `payload_dir: build/payload`,
`dist_dir: dist`, and `cache_dir: build/cache`.

## Write the image to a card

The tool produces `dist/trimui-brick.img` and stops. Write it yourself with
`dd` (macOS, Linux, or Git Bash) or balenaEtcher:

```shell
diskutil list                       # find the card's raw node, e.g. disk4
sudo dd if=dist/trimui-brick.img of=/dev/rdisk4 bs=4m
```

Or use [balenaEtcher](https://etcher.balena.io/) on any OS (or Raspberry Pi
Imager in "use custom image" mode). Double-check the device node - this
overwrites the whole card.

### Filesystem

NextUI's documentation allows FAT32 or exFAT with an MBR partition table; the
upstream `README.txt` recommends FAT32. This tool builds **exFAT only**.
exFAT boot on the Brick is unproven here. If the card does not boot, the
fallback is FAT32, which is not implemented by this project - a FAT32 builder
would be a separate change. There is no FAT32 support or boot guarantee in this
example.

## Grout setup

Grout is extracted to `Tools/tg5040/Grout.pak` and is not pre-configured. After
NextUI is installed:

1. Open the `Tools` menu and launch `Grout`.
2. Choose a language.
3. Enter the RomM connection details: protocol, hostname, optional port, and
   SSL verification setting.
4. Authenticate with **Pair with Another Device** (RomM 5.0+) or a **Pairing
   Code**; older RomM servers use the pairing-code flow.
5. Map RomM platforms to card directories. NextUI uses descriptive names such
   as `Game Boy (GB)`; Grout suggests them.
6. Save the mappings. Grout builds its initial library cache.

Grout writes its settings to
`Tools/tg5040/Grout.pak/config.json` on the card. Keep that file when updating
the pak by hand so you do not have to authenticate and remap again. No server
URL, username, password, or API token is present in the image or this
repository.

## ROMs, BIOS, and saves

This repository contains no ROMs, BIOS files, box art, or saves, and the tool
does not download or install them. The image ships empty NextUI platform
directories. Supply ROMs and BIOS files yourself, or let Grout download them
from your RomM server after you configure it. NextUI and its emulators are
upstream projects with their own licenses.

## Test

The shell suite proves the payload and image contracts offline apart from the
pinned GitHub archive downloads:

```shell
task test                              # Cannoli + NextUI + builder smoke
bash tests/ansible-payload-nextui.sh   # NextUI tree, exFAT image, mount checks
bash tests/ansible-payload.sh          # Cannoli regression
bash tests/smoke-image.sh              # offline exFAT builder smoke
```

The NextUI test stages the real pinned archives, asserts the card root and Grout
pak, builds a real exFAT image, and mounts it in a disposable container. It does
not boot hardware and does not write a real card.
