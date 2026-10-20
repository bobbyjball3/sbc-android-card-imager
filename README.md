# sbc-android-card-imager

Personal project to create a sparse SD card image for my opinionated Android SBC
device setup. Use or fork as you will - just keep it open source. I'll probably
make this somewhat flexible, but my real target is myself, so it may not do what
you want, how you want it.

The tool turns a device vars file into a Cannoli-ready card image. Ansible
stages the payload tree, a pinned Linux container assembles an uncompressed
sparse MBR + exFAT `.img`, and then it stops. Writing that image to an SD card
is deliberately **your** step, with `dd` or balenaEtcher - the tool no longer
writes block devices at all.

## What it does

- Ansible (`ansible/build.yml`) stages a Cannoli payload tree from a
  device vars file (`ansible/vars/<device>.yml`). ROMs, BIOS files, and box art
  are supplied by Cannoli/RomM and are not inputs.
- Creates the full Cannoli v1.9.1 layout: all 51 `Cannoli/Roms/<TAG>` folders,
  the other 16 base directories, the `Cannoli/Config/settings.json` `{}` install
  marker, and `APKs/` at the card root.
- Downloads pinned GitHub release assets (exact repo/tag/asset) and copies
  local payload files into the staged tree.
- Builds a sparse MBR + exFAT `.img` inside a privileged Linux container
  (`sbc-imager-builder:local`), checks the filesystem with `fsck.exfat -n`, and
  atomically publishes the image via `<out>.partial` + `mv`.
- Produces an image **file** only. The builder refuses `/dev/*` output paths
  and non-`.img` outputs. There is no flashing mode: you write the image with
  `dd` or balenaEtcher (or Raspberry Pi Imager in "use custom image" mode).

See [`docs/cannoli-platform-tags.md`](docs/cannoli-platform-tags.md) for the
pinned platform table and [`ansible/vars/rg477m.yml`](ansible/vars/rg477m.yml)
for the device vars that drive the RG477M build.

## Requirements

| Task | Requirements |
| --- | --- |
| Build | [uv](https://docs.astral.sh/uv/) (Python 3.12+) and Docker with privileged container support. Ansible runs through `uv run`; the `ansible-core` pin lives in `pyproject.toml`. No local `sfdisk`/`mkfs.exfat` needed - macOS only needs Docker + uv + Task. |
| Write to card | `dd` (macOS, Linux, or Git Bash on Windows) or [balenaEtcher](https://etcher.balena.io/) on any OS. The tool itself never touches a device. |
| Development | uv, Task, and Docker (privileged) for the shell test suite. |

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

# 2. Build the RG477M image as a 128 MiB file.
#    The task wrapper is shorthand for the ansible-playbook command below it.
task image DEVICE=rg477m SIZE_MIB=128
uv run ansible-playbook ansible/build.yml \
  -e device=rg477m -e image_device= -e image_size_mib=128

# 3. Write the image to your SD card. This is the ONLY write path - the tool
#    itself never touches a device. See "Write the image" below.
sudo dd if=dist/rg477m.img of=/dev/rdiskN bs=4m
```

### Collect the payload only

The playbook has two tag groups. `payload` stages the tree without invoking the
container; the full run (no `--tags`) stages and then builds the image:

```shell
# Stage the payload tree at build/payload (default) without building an image.
uv run ansible-playbook ansible/build.yml --tags payload \
  -e device=rg477m -e image_device= -e image_size_mib=128
```

The default vars are `payload_dir: build/payload`, `dist_dir: dist`, and
`image_output: dist/<device>.img`. Override any of them with `-e`:

```shell
uv run ansible-playbook ansible/build.yml \
  -e device=rg477m -e image_device= -e image_size_mib=128 \
  -e payload_dir=/tmp/payload -e dist_dir=/tmp -e image_output=/tmp/rg477m.img
```

### Change the size or label

- **Size.** `image_size_mib` is the image size in MiB (at least 2). The device
  vars file pins a value; `-e image_size_mib=N` overrides it. Alternatively,
  pass `-e image_device=/dev/diskN` and the playbook reads that disk's size
  read-only via `diskutil info` - it asserts the `WholeDisk` flag and never
  writes the device. A non-empty `image_device` wins over `image_size_mib`;
  pass `-e image_device=` to force the explicit size instead.
- **Label.** `image_label` is the exFAT volume label, 1-11 characters. Change
  it in `ansible/vars/<device>.yml` or with `-e image_label=MYLABEL`.

## Write the image

The tool **never writes to a block device** - on purpose. It produces
`dist/rg477m.img` and stops. Writing that image to your SD card is a separate,
manual step you perform with `dd` or balenaEtcher. There is no flashing mode,
no interactive card selector, no `ERASE` prompt, and no other supported write
path.

First double-check the device node - this is destructive and targets the whole
disk:

```shell
# macOS: list disks, then use the RAW node /dev/rdiskN for your card (N = its
# disk number, e.g. disk4 -> rdisk4). Do NOT target your boot disk.
diskutil list

sudo dd if=dist/rg477m.img of=/dev/rdiskN bs=4m
```

On Linux or Git Bash for Windows, the same `dd` works against the card's raw
node (e.g. `of=/dev/sdX` - make sure it is the card).

If you prefer a GUI, use [balenaEtcher](https://etcher.balena.io/) on any OS:
select `dist/rg477m.img`, select the card, and flash. Raspberry Pi Imager also
works in "use custom image" mode. All of these paths write the image produced
by this tool; the tool itself has no device-writing code path.

## The RG477M happy path

`ansible/vars/rg477m.yml` pins the Anbernic RG477M build:

| Var | Value |
| --- | --- |
| `device` | `rg477m` |
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

## Safety and limitations

- **Payload-only.** The image is not a bootable Android image and does not
  contain or modify bootloaders, kernels, `super`, `system`, `vendor`,
  `userdata`, `misc`, or `vbmeta` partitions. It does not install Android.
- **No APK installation.** APK files are copied to `APKs/` on the card; the tool
  does not run `adb`, install packages, or manage apps.
- **ROMs, BIOS files, and box art are RomM-supplied.** Cannoli/RomM provides
  those files on the card; this tool does not download or copy them. The only
  remote downloads are the pinned GitHub release assets declared in the device
  vars (`remote_assets`), each pinned by exact repo, tag, and asset name. The
  repository contains no copyrighted ROMs or BIOS files.
- **No zero-touch first boot.** The card preselects Cannoli as an existing
  install and ships every platform folder, but you still configure emulators,
  cores, and settings on first launch.
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
task lint        # ruff + pyright
task test        # test suite
task validate    # payload/build contract checks
task ci          # local gate
```

Shell tests live in `tests/`:

- `tests/ansible-payload.sh` - runs the payload playbook in a temp dir and
  asserts the full staged-tree contract (70 directories, 3 payload files, the
  3-byte settings marker, no `CREDITS.md`).
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
  opinionated in a way that lets me rapidly set up or re-set up an Android SBC
  device that I own.
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
