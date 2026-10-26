# sbc-android-card-imager

Personal project to create sparse SD card images for my opinionated SBC and
handheld device setups. Use or fork as you will - just keep it open source. I'll
probably make this somewhat flexible, but my real target is myself, so it may
not do what you want, how you want it.

The tool turns a device vars file into a ready-to-flash card image. Ansible
stages the payload tree for the selected profile, a pinned Linux container
assembles an uncompressed sparse MBR + exFAT `.img`, and then it stops. Writing
that image to an SD card is deliberately **your** step, with `dd` or
balenaEtcher - the tool no longer writes block devices at all.

Two payload profiles ship today: **Cannoli** for Android handhelds/SBCs such as
the Anbernic RG477M, and **NextUI** for the TrimUI Brick.

## What it does

- Ansible (`ansible/build.yml`) stages a payload tree from a device vars file
  (`ansible/vars/<device>.yml`) and a `payload_profile` (`cannoli` or
  `nextui`).
- **Cannoli profile:** creates the full Cannoli v1.9.1 layout - all 51
  `Cannoli/Roms/<TAG>` folders, the other 16 base directories, the
  `Cannoli/Config/settings.json` `{}` install marker, and `APKs/` at the card
  root. ROMs, BIOS files, and box art are supplied by Cannoli/RomM and are not
  inputs.
- **NextUI profile:** downloads the pinned NextUI `-all` release archive and
  the pinned Grout pak, verifies both SHA-256 checksums, caches them under
  `build/cache`, and extracts them into the card tree. `MinUI.zip` stays zipped
  for the NextUI installer.
- Downloads pinned GitHub release assets and archives (exact repo/tag/asset;
  archives also pinned by SHA-256) and copies local payload files into the
  staged tree.
- Builds a sparse MBR + exFAT `.img` inside a privileged Linux container
  (`sbc-imager-builder:local`), checks the filesystem with `fsck.exfat -n`, and
  atomically publishes the image via `<out>.partial` + `mv`.
- Produces an image **file** only. The builder refuses `/dev/*` output paths
  and non-`.img` outputs. There is no flashing mode: you write the image with
  `dd` or balenaEtcher (or Raspberry Pi Imager in "use custom image" mode).

## Supported devices

| Device | Payload profile | Card tree | Device vars |
| --- | --- | --- | --- |
| Anbernic RG477M | `cannoli` | Android 14 / `arm64-v8a`; Cannoli v1.9.1 | [`ansible/vars/rg477m.yml`](ansible/vars/rg477m.yml) |
| TrimUI Brick | `nextui` | NextUI v6.15.0 on platform `tg5040`; Grout v5.4.0.0, Tailscale (minui-tailscale) 2.0.0, Central Scrutinizer v0.3.0 | [`ansible/vars/trimui-brick.yml`](ansible/vars/trimui-brick.yml) |

Both images are payload or pre-seeded card files, not official firmware images.
See [`docs/cannoli-platform-tags.md`](docs/cannoli-platform-tags.md) for the
pinned Cannoli platform table.

## Requirements

| Task | Requirements |
| --- | --- |
| Build | [uv](https://docs.astral.sh/uv/) (Python 3.12+), `unzip`, and Docker with privileged container support. Ansible runs through `uv run`; the `ansible-core` pin lives in `pyproject.toml`. `unzip` is needed because `ansible.builtin.unarchive` extracts the pinned NextUI archive and paks. No local `sfdisk`/`mkfs.exfat` needed, but the host kernel must support exFAT (the container mounts it): on Linux use `sudo modprobe exfat` and install `linux-modules-extra-$(uname -r)` if the module is missing; Docker Desktop on macOS already provides it. |
| Write to card | `dd` (macOS, Linux, or Git Bash on Windows) or [balenaEtcher](https://etcher.balena.io/) on any OS. The tool itself never touches a device. |
| Development | uv, Task, `unzip`, Docker (privileged), and host exFAT kernel support for the shell test suite. On Linux, `sudo modprobe exfat` (install `linux-modules-extra-$(uname -r)` if missing). |

The builder image is `sbc-imager-builder:local`, built from the repository-root
`Dockerfile` (debian:bookworm-slim plus exfatprogs, util-linux, fdisk, rsync,
and coreutils).

## Setup

From a checkout of this repository:

```shell
uv sync --all-groups   # install the pinned Python toolchain (incl. ansible-core)
task container        # docker build -t sbc-imager-builder:local .
```

`task container` is shorthand for:

```shell
docker build -t sbc-imager-builder:local .
```

## Quickstart

```shell
# 1. Build the container (one-time, and after changing the Dockerfile/builder).
task container

# 2a. Build the RG477M Cannoli image as a 128 MiB file.
#     The task wrapper is shorthand for the ansible-playbook command below it.
task image DEVICE=rg477m SIZE_MIB=128
uv run ansible-playbook ansible/build.yml \
  -e device=rg477m -e image_device= -e image_size_mib=128

# 2b. Build the TrimUI Brick NextUI image. A non-empty IMAGE_DEVICE reads the
#     card's size read-only; SIZE_MIB=8192 is the fixed-size fallback.
task image DEVICE=trimui-brick IMAGE_DEVICE=/dev/diskN
task image DEVICE=trimui-brick SIZE_MIB=8192

# 3. Write the image to your SD card. This is the ONLY write path - the tool
#    itself never touches a device. See "Write the image" below.
sudo dd if=dist/<device>.img of=/dev/rdiskN bs=4m
```

For the Brick, `IMAGE_DEVICE=/dev/diskN` (macOS `diskutil`) sizes the image from
the real card without writing it. Use `SIZE_MIB=8192` when you want a fixed
size instead. NextUI requires at least 1024 MiB.

### Collect the payload only

The playbook has two tag groups. `payload` stages the tree without invoking the
container; the full run (no `--tags`) stages and then builds the image:

```shell
# Stage the RG477M payload tree at build/payload (default) without an image.
uv run ansible-playbook ansible/build.yml --tags payload \
  -e device=rg477m -e image_device= -e image_size_mib=128

# Stage the TrimUI Brick payload tree; archives are cached in build/cache.
uv run ansible-playbook ansible/build.yml --tags payload \
  -e device=trimui-brick -e image_device= -e image_size_mib=8192
```

The default vars are `payload_dir: build/payload`, `dist_dir: dist`,
`image_output: dist/<device>.img`, and `cache_dir: build/cache`. Override any of
them with `-e`:

```shell
uv run ansible-playbook ansible/build.yml \
  -e device=rg477m -e image_device= -e image_size_mib=128 \
  -e payload_dir=/tmp/payload -e dist_dir=/tmp -e image_output=/tmp/rg477m.img \
  -e cache_dir=/tmp/cache
```

### Change the size or label

- **Size.** `image_size_mib` is the image size in MiB (at least 2; NextUI
  requires at least 1024). The device vars file pins a value;
  `-e image_size_mib=N` overrides it. Alternatively, pass
  `-e image_device=/dev/diskN` and the playbook reads that disk's size
  read-only via `diskutil info` - it asserts the `WholeDisk` flag and never
  writes the device. A non-empty `image_device` wins over `image_size_mib`;
  pass `-e image_device=` to force the explicit size instead.
- **Label.** `image_label` is the exFAT volume label, 1-11 characters. Change
  it in `ansible/vars/<device>.yml` or with `-e image_label=MYLABEL`.

## Write the image

The tool **never writes to a block device** - on purpose. It produces
`dist/<device>.img` (for example `dist/rg477m.img` or
`dist/trimui-brick.img`) and stops. Writing that image to your SD card is a
separate, manual step you perform with `dd` or balenaEtcher. There is no
flashing mode, no interactive card selector, no `ERASE` prompt, and no other
supported write path.

First double-check the device node - this is destructive and targets the whole
disk:

```shell
# macOS: list disks, then use the RAW node /dev/rdiskN for your card (N = its
# disk number, e.g. disk4 -> rdisk4). Do NOT target your boot disk.
diskutil list

sudo dd if=dist/<device>.img of=/dev/rdiskN bs=4m
```

On Linux or Git Bash for Windows, the same `dd` works against the card's raw
node (e.g. `of=/dev/sdX` - make sure it is the card).

If you prefer a GUI, use [balenaEtcher](https://etcher.balena.io/) on any OS:
select `dist/<device>.img`, select the card, and flash. Raspberry Pi Imager
also works in "use custom image" mode. All of these paths write the image
produced by this tool; the tool itself has no device-writing code path.

## The RG477M happy path

`ansible/vars/rg477m.yml` pins the Anbernic RG477M build:

| Var | Value |
| --- | --- |
| `device` | `rg477m` |
| `payload_profile` | `cannoli` |
| `image_label` | `CANNOLI` |
| `image_device` | `/dev/disk5` (read-only geometry source) |
| `image_size_mib` | `488156` (the full aligned capacity of that disk5) |
| `image_output` | `dist/rg477m.img` |
| `remote_assets` | Obtainium APK `v1.7.1` -> `APKs/Obtainium.apk`; Obtainium Emulation Pack `v8.0.1` -> `Obtainium/obtainium-emulation-pack-v8.0.1.json` |
| `local_files` | `ansible/files/rg477m/tailscale.json` -> `Obtainium/tailscale.json` |
| `local_dirs` | none |

Because the vars file pins `image_device: /dev/disk5`, a bare
`uv run ansible-playbook ansible/build.yml -e device=rg477m` sizes the image
from that disk (read-only). Pass `-e image_device= -e image_size_mib=128` for a
quick small build, or `-e image_size_mib=<N>` to pin any size. See
[`examples/rg477m/`](examples/rg477m/) for the full device write-up.

## The TrimUI Brick happy path

`ansible/vars/trimui-brick.yml` pins the TrimUI Brick NextUI build:

| Var | Value |
| --- | --- |
| `device` | `trimui-brick` |
| `payload_profile` | `nextui` |
| `image_label` | `NEXTUI` |
| `image_size_mib` | `8192` (fixed-size fallback) |
| `image_output` | `dist/trimui-brick.img` |
| `nextui_platform` | `tg5040` (Brick, Brick Pro, and Smart Pro) |
| `remote_archives` | NextUI `LoveRetro/NextUI` `v6.15.0` / `NextUI-20261013-0-all.zip` -> card root; Grout `rommapp/grout` `v5.4.0.0` / `Grout.pak.zip` -> `Tools/tg5040/Grout.pak`; Tailscale `ben16w/minui-tailscale` `2.0.0` / `Tailscale.pak.zip` -> `Tools/tg5040/Tailscale.pak`; Central Scrutinizer `Helaas/nextui-CentralScrutinizer-pak` `v0.3.0` / `Central.Scrutinizer.pak.zip` -> `Tools/tg5040/Central Scrutinizer.pak` |
| `remote_assets` | none |
| `local_files` | none |
| `local_dirs` | none |

The two archives are SHA-256 pinned, cached under `build/cache`, verified before
extraction, and not vendored in this repository. For the Brick, prefer
`task image DEVICE=trimui-brick IMAGE_DEVICE=/dev/diskN` so the image is sized
read-only from the actual card; `task image DEVICE=trimui-brick SIZE_MIB=8192`
builds the documented fixed-size fallback. NextUI requires at least 1024 MiB.
See [`docs/nextui-layout.md`](docs/nextui-layout.md) and
[`examples/trimui-brick/`](examples/trimui-brick/) for the full layout and
device write-up.

### First boot and Grout

The pinned NextUI release is a ZIP tree, not an official `.img`, so this tool
builds a **pre-seeded** card; the stock NextUI installer still runs on first
boot.

1. Flash `dist/trimui-brick.img` to the card, insert it, and boot the device.
   The installer consumes `MinUI.zip`, the `.pakz` files, and `trimui/`, then
   creates `.system/`, `.tmp_update/`, and `.userdata/`. The card after first
   boot intentionally differs from the built image.
2. Reboot into NextUI and confirm `Tools` lists **Grout**.
3. Launch Grout once and enter your RomM server URL and API token on-device.
   Grout stores its config at `Tools/tg5040/Grout.pak/config.json`; the image
   and this repository never contain credentials or a server URL.
4. This tool never touches the device, but the upstream NextUI installer warns
   that some TrimUI devices write internal storage (NAND/TF1) during bootstrap.
   Treat the device-side write as part of the first boot, not this tool.

A supported device running the stock TrimUI OS (or MinUI) is a prerequisite. If
another CFW was installed before, reinstall the stock OS first. The resulting
image is for personal, noncommercial use under the NextUI license.

### exFAT risk and FAT32 fallback

NextUI documentation permits FAT32 or exFAT, but its `README.txt` recommends
FAT32. This tool always builds **exFAT**. Brick boot from the exFAT image has
not been verified in this repository, so treat it as an accepted risk: if the
Brick refuses the card, the documented fallback is a separate FAT32 builder
change (`dosfstools`, partition type `0c`, `fsck.vfat`), which this project does
not support today.

## Cannoli layout summary

The staged tree (and therefore the image) contains a payload tree, not an
Android system image:

```text
Cannoli/
  Art/
  BIOS/
  Backup/
  Cheats/
  Config/settings.json      # "{}" marker that preselects the card
  Guides/
  Logs/
  Media/Recordings/
  Media/Screenshots/
  Overlays/
  Roms/<TAG>/               # all 51 v1.9.1 tags
  Save States/
  Saves/
  Shaders/
  Wallpapers/
APKs/
Obtainium/                  # device payload files (per-device vars)
```

The 17 base directories and 51 tags are declared in
`ansible/vars/cannoli.yml` (plus the settings marker). The staged tree is 70
directories: 17 base dirs + 51 `Roms/<TAG>` dirs + the implicit
`Cannoli/Media` parent + `Obtainium`. Cannoli's own generated data, emulator
cores, and app-private data are never included.

## NextUI layout summary

The NextUI profile extracts the pinned `-all` archive and adds paks. Its
top-level card entries are:

```text
Bios/  Cheats/  Emus/  Overlays/  Roms/  Saves/  Shaders/  Tools/
README.txt
MinUI.zip                    # stays zipped for the first-boot installer
h700/                        # unused on the Brick
trimui/
nextui.pak_store.pakz
nextui.updater.pakz
nextui.upgrade_bluez.tg5040.pakz
```

There is no `em_ui.sh` in the pinned release. Grout lands at
`Tools/tg5040/Grout.pak` with executable `grout` and `launch.sh`. Tailscale and
Central Scrutinizer also land under `Tools/tg5040/`. The profile does not create
Cannoli, `APKs`, `Obtainium`, or a Cannoli settings marker.

## Safety and limitations

- **Payload or pre-seeded cards, not firmware.** The Cannoli image is not a
  bootable Android image and does not contain or modify bootloaders, kernels,
  `super`, `system`, `vendor`, `userdata`, `misc`, or `vbmeta` partitions. The
  NextUI image is built from the official NextUI ZIP tree and is not an official
  NextUI image; its first-boot installer still runs on the device.
- **No package installation.** Cannoli APK files are copied to `APKs/` on the
  card; the tool does not run `adb`, install packages, or manage apps. NextUI
  packages come from the pinned upstream archive, not from this tool.
- **ROMs, BIOS files, and box art are supplied elsewhere.** Cannoli/RomM or the
  NextUI archive provides those files on the card; this tool does not download
  or copy ROMs or BIOS files. The only remote downloads are the pinned GitHub
  release assets and archives declared in the device vars (`remote_assets` and
  `remote_archives`), each pinned by exact repo, tag, asset name, and - for
  archives - SHA-256. The repository contains no copyrighted ROMs or BIOS files.
- **No zero-touch first boot.** The Cannoli card preselects Cannoli as an
  existing install but still needs emulator, core, and settings configuration.
  The NextUI card still runs the upstream first-boot installer, and Grout needs
  its RomM server URL and token entered on-device.
- **Image assembly always runs in the pinned Linux container.** macOS never
  runs `sfdisk` or `mkfs.exfat` locally; the container does all of it.
- **No block-device writes, ever.** The builder refuses any output under
  `/dev/` and any non-`.img` output. The only supported way to get the image
  onto a card is `dd` or balenaEtcher, run by you. Double-check the device
  node before writing - flashing overwrites every byte on the selected card.
- **Read-only disk sizing.** `image_device` only reads `diskutil info` geometry
  and asserts the `WholeDisk` flag. It never unmounts, writes, or formats.
- **No verification pass or generated credits file.** The old per-file
  verification step and the credits file it wrote are gone; the container's
  `fsck.exfat -n` before publication is the built-image check.

## Development

```shell
task container   # build sbc-imager-builder:local
task lint        # shellcheck + ansible-lint
task test        # test suite
task validate    # payload/build contract checks
task ci          # local gate
```

Shell tests live in `tests/`:

- `tests/ansible-payload.sh` - runs the Cannoli payload playbook in a temp dir
  and asserts the full staged-tree contract (70 directories, 3 payload files,
  the 3-byte settings marker, no `CREDITS.md`).
- `tests/ansible-payload-nextui.sh` - stages the NextUI profile with a temp
  payload/cache/dist, asserts the 15-entry card root, zipped `MinUI.zip`,
  `trimui/`, and executable Grout pak, then builds and mounts a real exFAT image.
  Also injects missing-payload and corrupt-cache failures.
- `tests/smoke-image.sh` - offline 66 MiB tree-to-image smoke test of the
  builder: MBR layout, `fsck.exfat -n`, mounted contents, loop cleanup, and
  failure injection.

## AI Disclosure

I'm a software dev by trade, but I did use AI. I don't love AI and the probable
societal impacts, but it's really a great tool for software devs to accelerate
their work, and it lets me do this stuff while still having a bunch of time for
my family. If you don't like AI and don't want to use this project, I get it and
I wish you well.

## Some Notes

- I will not include any copyrighted material that is not properly attributed
  and is not going to get me into legal trouble (I'm not going to include any
  ROMs or BIOS files, for instance).
- Where I use other projects, I attribute them properly either in this README in
  [Credits and Attribution](#credits-and-attribution) or alongside the artifacts
  in Markdown files.
- This does what I want, how I want. It's not made for everyone. It's
  opinionated in a way that lets me rapidly set up or re-set up an SBC or
  handheld device that I own.
- I'll consider PRs, but I'm not promising any timeline for response, reviews,
  etc. If what you're submitting isn't something I want to maintain or include,
  I'll politely decline and you're welcome to fork this - just keep it open
  source.

## Credits and Attribution

- **Cannoli** v1.9.1, commit
  `7755e376b6add0bbd25ea19104c368b7a40b979f`, GPL-3.0 -
  <https://github.com/CannoliHQ/cannoli>. The directory contract in
  `ansible/vars/cannoli.yml` and the install marker are derived from this
  pinned release.
- **NextUI** v6.15.0, asset `NextUI-20261013-0-all.zip`, PolyForm
  Noncommercial License 1.0.0 - <https://github.com/LoveRetro/NextUI>. The
  archive is downloaded and SHA-256 verified at build time, not vendored. The
  resulting card image is intended for personal, noncommercial use only; review
  the upstream license before redistributing.
- **Grout** v5.4.0.0, asset `Grout.pak.zip`, MIT -
  <https://github.com/rommapp/grout>. The pak is downloaded and SHA-256
  verified at build time and is not vendored. Grout's RomM server URL and token
  are configured on-device and never stored in this repository or the image.
- **Tailscale (minui-tailscale)** 2.0.0, asset `Tailscale.pak.zip`, MIT (pak) / BSD-3-Clause (Tailscale client; license retained as `tailscale.LICENSE`). Downloaded at build time, not vendored. An auth key and optional login server are provided on-device (docs-only); the pak deletes them after login and stores state under `.userdata/<PLATFORM>/`.
- **Central Scrutinizer** v0.3.0, asset `Central.Scrutinizer.pak.zip`, MIT - <https://github.com/Helaas/nextui-CentralScrutinizer-pak>. Downloaded at build time, not vendored. Terminal/screen-timeout/pairing side effects are unverified on hardware.
- **exfatprogs** - `mkfs.exfat` and `fsck.exfat` in the builder container,
  GPL-2.0 - <https://github.com/exfatprogs/exfatprogs>.
- **Ansible** (`ansible-core`) - stages the payload tree, GPL-3.0 -
  <https://github.com/ansible/ansible>.
- **balenaEtcher** - the GUI path for writing the built image to a card,
  Apache-2.0 - <https://www.balena.io/etcher/>.
- **RetroArch / libretro documentation** - overlay, shader, BIOS, and core
  layout guidance - <https://docs.libretro.com/>.
- **uv** (Apache-2.0/MIT), **ruff** (MIT), and **Task** (MIT) - the environment,
  linting, and task runner used by this project.

## License

This project is licensed under the GNU General Public License v3.0 or later
(GPL-3.0-or-later). See [`LICENSE`](LICENSE).
