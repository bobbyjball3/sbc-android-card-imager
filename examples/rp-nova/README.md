# Retroid Pocket Nova Cannoli card

A pinned example for a Retroid Pocket Nova: a Cannoli-ready card skeleton plus
Obtainium, the Obtainium Emulation Pack, and a Tailscale import file. The card
is staged by Ansible from [`ansible/vars/rp-nova.yml`](../../ansible/vars/rp-nova.yml)
and built into a sparse `.img` by the container builder; you write that image to
a card with `dd` or balenaEtcher - the tool never writes a device.

## Device

The Retroid Pocket Nova uses a Qualcomm QCS8550 (Snapdragon 8 Gen 2 class,
Adreno 740), runs Android 13, and installs `arm64-v8a` APKs. It has a TF
(microSD) card slot. The image is payload-only: it does not flash or replace the
Android boot images.

## Pins

The device vars file pins two remote GitHub release assets plus one local file:

| Item | Pin | Card destination | Size | SHA-256 | License |
| --- | --- | --- | --- | --- | --- |
| Obtainium APK | `ImranR98/Obtainium` tag `v1.7.1`, asset `app-arm64-v8a-release.apk` | `APKs/Obtainium.apk` | 27,194,505 bytes | `04dfd02c56dae8d5271d2d402977e1b07c8eeffb313df054a13e71b75b8b8a26` | GPL-3.0 |
| Obtainium Emulation Pack | `RJNY/Obtainium-Emulation-Pack` tag `v8.0.1`, asset `obtainium-emulation-pack-v8.0.1.json` | `Obtainium/obtainium-emulation-pack-v8.0.1.json` | 78,201 bytes | `c2170687b07881f5891fe9751903c13c31b80de506bd41b718f99abb45592169` | Unlicense |
| Tailscale import | local `ansible/files/rp-nova/tailscale.json` | `Obtainium/tailscale.json` | 383 bytes | `965cb8f0afb48f7dfee57099ccaa43f00c9ef50e16c50fd4a90f1cab0286fcd4` | n/a |

The remote assets are downloaded by the playbook's `get_url` task from their
exact GitHub release tags (`force: no`); there are no mutable selectors. The
SHA-256 values above are the pinned upstream reference rather than a value
verified at runtime. The pack is a JSON file, not an APK. None of
these files is vendored in this repository.

## Tailscale

The local [`ansible/files/rp-nova/tailscale.json`](../../ansible/files/rp-nova/tailscale.json)
is an Obtainium import file for `com.tailscale.ipn`. It points Obtainium at
`tailscale/tailscale-android` and deliberately tracks the latest release instead
of pinning a version; at the time of writing the current latest tag is
`1.104.1-t7f4efe814-g6d75bd403` and Obtainium selects the universal APK. The
Tailscale APK itself is not embedded in this image; Obtainium downloads it when
you import the file and refresh apps. The device vars declare it under
`local_files`, so the playbook copies it to `Obtainium/tailscale.json`.

The image also includes the pinned Emulation Pack JSON from GitHub; it is not
regenerated or modified locally.

## Platform mapping

The image contains every Cannoli v1.9.1 tag directory. The platforms requested
for this device use these tags:

| Platform | Cannoli tag | ROM directory |
| --- | --- | --- |
| Game Boy | GB | `Cannoli/Roms/GB` |
| Game Boy Color | GBC | `Cannoli/Roms/GBC` |
| Game Boy Advance | GBA | `Cannoli/Roms/GBA` |
| Game Gear | GG | `Cannoli/Roms/GG` |
| Neo Geo Pocket Color | NGPC | `Cannoli/Roms/NGPC` |
| NES | NES | `Cannoli/Roms/NES` |
| SNES | SNES | `Cannoli/Roms/SNES` |
| Sega Genesis | MD | `Cannoli/Roms/MD` |
| PlayStation | PS | `Cannoli/Roms/PS` |
| Nintendo 64 | N64 | `Cannoli/Roms/N64` |
| PlayStation 2 | PS2 | `Cannoli/Roms/PS2` |
| GameCube | GC | `Cannoli/Roms/GC` |
| Wii | WII | `Cannoli/Roms/WII` |
| Nintendo Switch | NSW | `Cannoli/Roms/NSW` |

## Cannoli skeleton

The playbook stages the full pinned skeleton automatically from
[`ansible/vars/cannoli.yml`](../../ansible/vars/cannoli.yml):

- all 17 base directories (`Cannoli`, `Art`, `BIOS`, `Backup`, `Cheats`,
  `Config`, `Guides`, `Logs`, `Media/Screenshots`, `Media/Recordings`,
  `Overlays`, `Roms`, `Save States`, `Saves`, `Shaders`, `Wallpapers`, `APKs`);
- all 51 `Cannoli/Roms/<TAG>` directories, including the tags above;
- `Cannoli/Config/settings.json` containing exactly `{}\n` (3 bytes) - the
  marker file that preselects the card as a Cannoli install;
- `Obtainium/` with the pinned Emulation Pack and Tailscale import files.

The staged tree is 70 directories: 17 base dirs + 51 Roms tags + the implicit
`Cannoli/Media` parent + `Obtainium`. There is no `CREDITS.md`. ROMs, BIOS
files, and box art are supplied by Cannoli/RomM on the card; this repository
contains no such payloads.

## Build

Build the container once, then run the playbook from the repository root:

```shell
task container   # docker build -t sbc-imager-builder:local .
```

Stage the payload tree only (no container, no image):

```shell
uv run ansible-playbook ansible/build.yml --tags payload \
  -e device=rp-nova -e image_device= -e image_size_mib=128
```

Build the image (stages and assembles):

```shell
uv run ansible-playbook ansible/build.yml \
  -e device=rp-nova -e image_device= -e image_size_mib=128
```

Defaults are `payload_dir: build/payload`, `dist_dir: dist`, and
`image_output: dist/rp-nova.img`. The build requires Docker; all `sfdisk`,
`mkfs.exfat`, mount, and `fsck.exfat -n` work happens inside the pinned Linux
container, and the image is published atomically via `dist/rp-nova.img.partial`
+ `mv`.

### Card size

The device vars pin `image_size_mib: 488156` for a 512GB card at
`/dev/disk5`, and `image_device: /dev/disk5`. A bare
`uv run ansible-playbook ansible/build.yml -e device=rp-nova` therefore sizes the
image read-only from that disk: the playbook reads `diskutil info -plist`,
asserts the `WholeDisk` flag, and computes `image_size_mib` from `TotalSize` -
it never writes the device. Update `image_device` to your card's whole-disk node
if it is not `disk5`.

To pin a different size without touching disk geometry, override both:

```shell
uv run ansible-playbook ansible/build.yml \
  -e device=rp-nova -e image_device= -e image_size_mib=256
```

`image_size_mib` must be at least 2, and the image is always 1 MiB of MBR
offset plus an `(size - 1 MiB)` exFAT partition starting at LBA 2048. The host
image is sparse; writing it to a card still writes the full logical size.

## Write the image to a card

The tool produces `dist/rp-nova.img` and stops - it has no device-writing path.
Write the image yourself with `dd` (macOS, Linux, or Git Bash) or
balenaEtcher:

```shell
diskutil list                       # find the card's raw node, e.g. disk4
sudo dd if=dist/rp-nova.img of=/dev/rdisk4 bs=4m
```

Or use [balenaEtcher](https://etcher.balena.io/) on any OS (or Raspberry Pi
Imager in "use custom image" mode). Double-check the device node - this
overwrites the whole card.

## Import into Obtainium

1. Install Obtainium from `APKs/Obtainium.apk` on the device (or install your
   own Obtainium build).
2. Open Obtainium, choose **Import/Export**, then **Import from file**.
3. Import `Obtainium/obtainium-emulation-pack-v8.0.1.json` to add the emulation
   app pack.
4. Import `Obtainium/tailscale.json` to add
   `com.tailscale.ipn` from `tailscale/tailscale-android`.
5. Refresh/install from Obtainium; Tailscale tracks the latest release, while
   the emulation pack entries are whatever that pinned pack defines.

The two imports are independent; you can import either one.

## Test

The shell suite proves the payload contract and the builder, offline:

```shell
bash tests/ansible-payload.sh   # staged-tree contract (70 dirs, 3 files, marker)
bash tests/smoke-image.sh       # offline 66 MiB tree-to-image smoke test
```

The pinned SHA-256 values are documented above; there is no parity script
anymore.
