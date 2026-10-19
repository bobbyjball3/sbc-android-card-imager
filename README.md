# sbc-android-card-imager

Personal project to create a sparse SD card image for my opinionated Android SBC
device setup. Use or fork as you will - just keep it open source. I'll probably
make this somewhat flexible, but my real target is myself, so it may not do what
you want, how you want it.

The tool turns a plain-text TOML manifest into a Cannoli-ready card image. It
plans every destination, fetches pinned local/git/HTTPS/GitHub sources into a
cache, stages the tree, assembles an uncompressed MBR + exFAT `.img` in a pinned
Linux container, verifies the filesystem and every file hash, and can flash the
result to a removable card on macOS.

## What it does

- Reads a manifest describing overlays, shaders, APKs, and arbitrary extra
  artifacts. ROMs, BIOS files, and box art are supplied by Cannoli/RomM and are
  not manifest inputs.
- Pins git refs and checksums HTTPS downloads, caches them content-addressed, and
  supports `--offline` rebuilds.
- Creates the full Cannoli v1.9.1 layout: all 51 `Cannoli/Roms/<TAG>` folders,
  the `Cannoli/Config/settings.json` `{}` install marker, `APKs/` at the card
  root, and `CREDITS.md`.
- Refuses invalid manifests before writing image bytes: unknown tags, bad exFAT
  names, case/NFC collisions, duplicate destinations, symlinks in local typed
  paths, and oversize content all fail early.
- Verifies the built image with `fsck.exfat -n`, a directory check, and a
  per-file SHA-256 comparison against the manifest.
- Flashes only an external removable whole disk, after showing its model, size,
  protocol, and serial, and after you type `ERASE <device>`. A `--dry-run` shows
  the same details without writing.

See [`docs/manifest.md`](docs/manifest.md) for the complete manifest reference
and [`docs/cannoli-platform-tags.md`](docs/cannoli-platform-tags.md) for the
generated platform table.

## Requirements

| Task | Requirements |
| --- | --- |
| Build | Python 3.12+, [uv](https://docs.astral.sh/uv/), and Docker (Docker Desktop or Colima) with privileged container support. Docker is required; there is no native macOS assembler. |
| Imaging | macOS with `diskutil`, root access (`sudo`), and a USB card reader or, with explicit opt-in, an internal SD reader. Linux and Windows imaging are not supported. |
| Verify | Docker, because the filesystem scan runs inside the pinned container. |
| Development | Python 3.12+, uv, Task, and Docker for the end-to-end image test. |

The build path has no Windows support. The container is pinned by digest in the
`Dockerfile`; `build` builds `sbc-imager-assembler:local` automatically when it
is missing.

## Install

From a checkout of this repository:

```shell
uv tool install .
```

For development, install the project and its dev dependencies instead:

```shell
uv sync --all-groups
uv run sbc-imager --version
```

## Quickstart

```shell
# 1. See every Cannoli platform tag and display name.
sbc-imager platforms

# 2. Resolve sources, validate the manifest, and print the plan.
sbc-imager plan --manifest examples/imager.toml

# 3. Optionally warm the source cache without building.
sbc-imager fetch --manifest examples/imager.toml

# 4. Build and atomically publish a verified image.
#    The bundled demo is tiny, so a pinned 66 MiB image is enough.
sbc-imager build --manifest examples/imager.toml --size 66MiB

# 5. Re-verify the published image against the manifest.
sbc-imager verify --image dist/demo.img --manifest examples/imager.toml

# 6. Inspect every whole disk and why it is or is not a safe target.
sbc-imager image --list

# 7. Show the selected card and image without writing.
sbc-imager image --image dist/demo.img --dry-run

# 8. Actually flash it. This is destructive and requires root.
sudo -E sbc-imager image --image dist/demo.img
```

An explicit target skips the interactive menu, but still requires the typed
`ERASE <device>` confirmation before writing:

```shell
# External card reader.
sudo -E sbc-imager image --image dist/demo.img --device /dev/disk9

# Internal built-in SD reader: explicit device plus opt-in.
sudo -E uv run sbc-imager image --image dist/demo.img --device /dev/disk5 --allow-builtin-sd
```

### Size an image to the target card

`build --expand` sizes the image to the full aligned capacity of the selected
disk without writing the card. It reads the same safe whole-disk assessment as
`image`, so `--device` accepts `diskN`, `/dev/diskN`, or `/dev/rdiskN`, and
`--allow-builtin-sd` is required for an internal SD reader. `--expand` requires
`--device`; `--device` is invalid without `--expand`; `--size` cannot be
combined with `--expand`.

```shell
uv run sbc-imager build --manifest examples/rg477m/rg477m.toml \
  --device /dev/disk5 --allow-builtin-sd --expand
```

The image is the largest 1 MiB-aligned size that fits the disk, with a minimum
of 2 MiB. For the 511,868,665,856-byte disk5 that is `488156MiB`
(511,868,665,856 bytes), with a 511,867,617,280-byte partition. The expanded
size overrides `[image].size`; reserve is not used for that sizing. The host
image is sparse, but flashing still writes the full logical size. Then flash it:

```shell
sudo -E uv run sbc-imager image \
  --image examples/rg477m/dist/rg477m.img \
  --device /dev/disk5 --allow-builtin-sd
```

### Progress output

`build` reports phase progress on stderr: source resolution, staging, container
preparation, assembly phases, verification, and publication. Known counts show
as `current/total`; long phases show a phase line and elapsed time when they
finish.

```shell
uv run sbc-imager build --manifest examples/rg477m/rg477m.toml --progress human
```

`--progress` accepts `auto` (default; human on a TTY, otherwise off), `human`,
`json`, or `none`. In `json` mode stderr is newline-delimited JSON with
`event: "progress"` or `event: "log"`. `--json` still keeps the
machine-readable report on stdout pure; progress goes to stderr. Rebuild the
assembler container after upgrading so the in-container phases are emitted:

```shell
task container
```

Without `--size`, the demo manifest sizes itself to 67 MiB (1 MiB partition
offset plus a 66 MiB partition for 592 bytes of content, the 64 MiB overhead,
and the 1 MiB reserve declared in the example).

### The 66 MiB minimum

The planner reserves at least **64 MiB of filesystem overhead** plus a **1 MiB
partition offset**. A 64 MiB image therefore cannot hold the overhead and any
content at all. The smallest 1 MiB-aligned image that can hold the tiny demo
fixture is **66 MiB**; 65 MiB leaves no room for non-zero content. Larger cards
normally use `size = "auto"` and the `reserve` setting instead.

## Manifest at a glance

```toml
[image]
name = "demo"
label = "CANNOLI"
size = "auto"
reserve = "1MiB"
output = "dist/demo.img"

[[overlay]]
platform = "GBA"
path = "demo/overlays/GBA/bezel.png"

[[shader]]
path = "demo/shaders/crt-lamp"

[[apk]]
path = "demo/apks/Demo.apk"

[[artifact]]
root = "card"
dest = "Manuals"
path = "demo/manuals/readme.txt"
```

ROMs, BIOS files, and box art are not manifest inputs: Cannoli/RomM supplies
those files on the card. The manifest creates their directory skeleton but does
not copy or download their contents.

A pinned GitHub release asset can feed an APK entry. Only exact tags are
supported in Phase 1; there is no `latest` or other mutable release selector.

```toml
[[source]]
id = "obtainium"
type = "github"
repo = "ImranR98/Obtainium"
tag = "v1.7.1"
asset = "app-arm64-v8a-release.apk"

[[apk]]
source = "obtainium"
as = "Obtainium.apk"
```

The asset is selected by exact file name, its SHA-256/license/attribution are
detected and cached, and it lands at `APKs/Obtainium.apk`. See
[`examples/obtainium.toml`](examples/obtainium.toml). A complete RG477M manifest
with the pinned Obtainium APK, Obtainium Emulation Pack, and Tailscale import is
in [`examples/rg477m/`](examples/rg477m/).

Relative `path`, `output`, and local source `url` values resolve against the
manifest's directory; `~` expands to your home directory. The bundled
[`examples/imager.toml`](examples/imager.toml) uses only the placeholder files in
[`examples/demo/`](examples/demo/README.md), so it works without a network
connection.

## Cannoli layout summary

The image contains a payload tree, not an Android system image:

```text
Cannoli/
  Art/
  BIOS/
  Cheats/<TAG>/
  Config/settings.json      # "{}" marker that preselects the card
  Guides/<TAG>/
  Media/Recordings/
  Media/Screenshots/
  Overlays/<TAG>/
  Roms/<TAG>/               # all 51 v1.9.1 tags
  Save States/<TAG>/
  Saves/<TAG>/
  Shaders/<preset>/
  Wallpapers/
APKs/
CREDITS.md
```

`[[artifact]]` entries can add other payload files under either the card root
(`root = "card"`) or the Cannoli root (`root = "cannoli"`). Cannoli's own
generated data, emulator cores, and app-private data are never included.

## Safety and limitations

- **Payload-only.** The image is not a bootable Android image and does not
  contain or modify bootloaders, kernels, `super`, `system`, `vendor`,
  `userdata`, `misc`, or `vbmeta` partitions. It does not install Android.
- **No APK installation.** APK files are copied to `APKs/` on the card; the tool
  does not run `adb`, install packages, or manage apps.
- **ROMs, BIOS files, and box art are RomM-supplied.** Cannoli/RomM provides
  those files on the card; this tool does not download or copy them. Remote
  sources are supported for `[[overlay]]`, `[[shader]]`, and single-file
  `[[apk]]`/`[[artifact]]` entries; GitHub APK and artifact sources require an
  exact tag and asset name. The repository contains no copyrighted ROMs or BIOS
  files.
- **No zero-touch first boot.** The card preselects Cannoli as an existing
  install and ships every platform folder, but you still configure emulators,
  cores, and settings on first launch.
- **No native macOS assembler and no Windows support.** Image assembly always
  runs in the pinned Linux container.
- **Explicit or interactive flashing, never unattended.** Flashing requires
  root. `image --list` is read-only, needs no root or image, and shows every
  whole disk with a safety status and reason. The command either prompts from
  the safe list or accepts an explicit `--device diskN`, `/dev/diskN`, or
  `/dev/rdiskN`; the target must resolve to a safe enumerated whole disk. It
  shows model/size/protocol/serial when available and still requires typing
  `ERASE <device>`. It unmounts, writes, syncs, and ejects. There is no `--yes`
  or unattended mode.
- **Internal disks are rejected unless explicitly opted in.** External
  removable whole disks are the default. `--allow-builtin-sd` is valid only
  with an explicit `--device` (or the read-only `--list` diagnostic) and permits
  an internal disk only when it is a whole physical, removable or ejectable
  `Secure Digital`/`SD Card` reader. It never permits the boot disk or a
  non-removable internal disk. A USB card reader remains the default path.
- **Flashing is destructive.** Every byte on the selected card is overwritten.
  Use `--dry-run` first. There is no multi-card batch mode, no compression, and
  no FAT32/ext4 option.
- **No renaming or multi-disc bundling beyond `as`.** Retained files keep their
  relative names and subdirectories unless a typed entry declares an `as` rename;
  you are responsible for names Cannoli and the emulators expect.

## Sample output

A successful build prints progress on stderr and a summary on stdout:

```text
Staged 5 files in /var/folders/.../sbc-build-...
Wrote /Users/me/sbc-android-card-imager/dist/demo.img (66MiB)
Image: /Users/me/sbc-android-card-imager/dist/demo.img
Size: 66MiB  SHA-256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef  Verified files: 7
```

`build` also writes `dist/demo.img.report.json` next to the image (and prints
the same payload with `--json`). Abridged:

```json
{
  "content_bytes": 592,
  "content_files": 5,
  "image": "/Users/me/sbc-android-card-imager/dist/demo.img",
  "image_bytes": 69206016,
  "offset": 1048576,
  "partition_bytes": 68157440,
  "schema_version": 1,
  "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "verify": {
    "actual_files": 7,
    "expected_files": 7,
    "extra": [],
    "mismatched": [],
    "missing": [],
    "missing_dirs": [],
    "ok": true
  },
  "warnings": []
}
```

A successful verification prints:

```text
Verification passed: 7 files match the manifest.
```

A failure names the offending entries instead:

```text
Verification failed:
  Hash mismatches: Cannoli/Overlays/GBA/bezel.png
```

## Development

```shell
task lint    # ruff check, ruff format --check, pyright
task test    # unit tests (no hardware or Docker required)
task ci      # lint, unit tests, and uv build
```

The full manifest schema, validation rules, size math, cache behavior, and exit
codes live in [`docs/manifest.md`](docs/manifest.md).

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
  <https://github.com/CannoliHQ/cannoli>. The platform registry, folder
  contract, and install marker are derived from this pinned release.
- **exfatprogs** - `mkfs.exfat` and `fsck.exfat` in the assembler container,
  GPL-2.0 - <https://github.com/exfatprogs/exfatprogs>.
- **RetroArch / libretro documentation** - overlay, shader, BIOS, and core
  layout guidance - <https://docs.libretro.com/>.
- **Typer** (MIT), **Rich** (MIT), **uv** (Apache-2.0/MIT), **ruff** (MIT), and
  **Task** (MIT) - the CLI, terminal output, environment, linting, and task
  runner used by this project.
- The demo assets under `examples/demo/` are tiny, non-copyrighted placeholders
  created for this repository. See
  [`examples/demo/README.md`](examples/demo/README.md).

## License

This project is licensed under the GNU General Public License v3.0 or later
(GPL-3.0-or-later). See [`LICENSE`](LICENSE).
