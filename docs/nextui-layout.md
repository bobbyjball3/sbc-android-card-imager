# NextUI card layout (TrimUI Brick)

Pinned NextUI release: **v6.15.0**

Pinned Grout release: **v5.4.0.0**

This document is the human reference for the `nextui` payload profile used by
the TrimUI Brick. The runtime source of truth is
[`ansible/vars/trimui-brick.yml`](../ansible/vars/trimui-brick.yml) plus the
profile contract in [`ansible/vars/nextui.yml`](../ansible/vars/nextui.yml).
The playbook downloads the pinned release ZIPs, verifies their SHA-256 values,
extracts them into the payload tree, and the container builder turns that tree
into a sparse MBR + exFAT `.img`.

The official NextUI release is a **ZIP archive, not an `.img`**. This tool
builds a pre-seeded card image from that ZIP; it is not an official NextUI
image, and the first boot still runs the normal NextUI installer.

## Pins

| Project | Repository | Tag | Asset | Size | SHA-256 | Card destination | License |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NextUI | `LoveRetro/NextUI` | `v6.15.0` | `NextUI-20261013-0-all.zip` | 243,439,698 bytes | `d5edceaa92d0264f34da87f017a40fb8244dc3081f894f17c6979ffe94c4c38a` | card root (`.`) | PolyForm Noncommercial 1.0.0 |
| Grout | `rommapp/grout` | `v5.4.0.0` | `Grout.pak.zip` | 24,839,934 bytes | `eb5ffa37aca0d484e1c8c16f16c8cf4e7a74f798d5a023ea907f99d6cea45328` | `Tools/tg5040/Grout.pak` | MIT |

The download URLs are the exact GitHub release paths
(`https://github.com/<repo>/releases/download/<tag>/<asset>`); there are no
`latest` or mutable selectors. Archives are cached under `build/cache`,
checksum-verified before extraction, and never vendored in this repository.
Asset names embed upstream build dates, so refresh the tag, asset, size, and
SHA-256 together.

## Card root

The NextUI `-all` archive is extracted directly to the card root. The staged
tree has exactly these 15 top-level entries:

| Entry | Kind | Notes |
| --- | --- | --- |
| `Bios/` | directory | NextUI BIOS tree; BIOS files are user-supplied. |
| `Cheats/` | directory | Cheat data directory; ensured by the NextUI profile. |
| `Emus/` | directory | Extra emulator content from the `-all` archive. |
| `Overlays/` | directory | RetroArch overlay content. |
| `README.txt` | file | Upstream release notes. |
| `Roms/` | directory | Empty platform folders until you add games. |
| `Saves/` | directory | Save files. |
| `Shaders/` | directory | Shader content. |
| `Tools/` | directory | Pak directory; receives `Tools/tg5040/Grout.pak`. |
| `MinUI.zip` | file | Stays **zipped** at the root; the tool never extracts it. |
| `h700/` | directory | Anbernic H700 payload shipped by `-all`; unused on the Brick. |
| `trimui/` | directory | TrimUI bootstrap/launcher payload required for first boot. |
| `nextui.pak_store.pakz` | file | NextUI Pak Store update package. |
| `nextui.updater.pakz` | file | NextUI updater package. |
| `nextui.upgrade_bluez.tg5040.pakz` | file | TrimUI `tg5040` Bluetooth upgrade package. |

There is **no `em_ui.sh`** in the real v6.15.0 `-all` asset. Some upstream
makefile listings mention it, but it is not part of the shipped archive and the
staged tree must not contain one.

`MinUI.zip` is copied as a file and must stay zipped; extracting it breaks the
NextUI bootstrap. The `trimui/` directory is also required at the card root:
NextUI uses it for the first-boot installation and launcher path. The `h700/`
directory ships in the `-all` union for Anbernic H700 devices and is simply
unused on the Brick.

## Platform

The TrimUI Brick uses the NextUI platform directory **`tg5040`**. The same
platform identifier is used by the TrimUI Brick Pro and Smart Pro. The Smart Pro
S uses **`tg5050`** and is out of scope for this profile; no part of this build
targets or verifies `tg5050`.

The NextUI release is shared across the TrimUI family, so the archive is not
Brick-specific. This profile only installs the Grout pak under
`Tools/tg5040`, which is the Brick's platform directory.

## Grout

Grout is installed by extracting the pinned `Grout.pak.zip` into:

```text
Tools/tg5040/Grout.pak/
```

The pak contains `grout`, `launch.sh`, `pak.json`, `lib/`, and its own
documentation/license files. The playbook makes `grout` and `launch.sh`
executable (mode `0755`).

Grout is **not pre-configured** by this repository. There is no server URL,
username, password, or API token in the image or the repository. Grout writes
its state to:

```text
Tools/tg5040/Grout.pak/config.json
```

### First-run setup

1. Boot NextUI and open the `Tools` menu.
2. Launch `Grout`. Grout starts its first-run flow.
3. Choose a language.
4. Enter the RomM server connection: protocol (HTTP/HTTPS), hostname, optional
   non-standard port, and SSL verification preference.
5. Authenticate. On RomM 5.0 and newer, use **Pair with Another Device** (scan
   the QR code and approve the device in RomM) or choose **Pairing Code**. On
   older RomM servers, use the pairing-code flow. Grout stores the resulting
   API token on the card.
6. Map RomM platforms to card directories. NextUI uses descriptive directory
   names with tags, for example `Game Boy (GB)` or `Game Boy Advance (GBA)`;
   Grout suggests these names.
7. Save the mappings. Grout builds its initial library cache.

On a later manual Grout update, keep `config.json` so you do not have to
authenticate and remap platforms again. Grout's required RomM version matches
the first three components of its own version (for Grout `v5.4.0.0`, RomM 5.4.0).

## Image, first boot, and the post-install card

The builder produces `dist/trimui-brick.img` with:

- an MBR partition table;
- a partition starting at LBA 2048 (the 1 MiB offset NextUI expects);
- an exFAT filesystem labelled `NEXTUI`;
- the staged NextUI/Grout tree from above.

The image defaults to `image_size_mib: 8192`; use `IMAGE_DEVICE=/dev/diskN` to
size it from the target card's geometry (read-only), or `SIZE_MIB` to pin a
size. NextUI builds require at least 1024 MiB.

Because the release is a ZIP and this tool produces a pre-seeded image, the card
is not in its final installed state when you flash it. The first boot runs the
NextUI installer from the card. During that run the installer:

- removes `MinUI.zip`;
- removes the `nextui.*.pakz` packages;
- removes `trimui/`;
- creates `.system/`, `.tmp_update/`, and `.userdata/`.

The card after first boot therefore differs from the built image, and the
fifteen-entry list above describes the **pre-install** tree. `Tools/` and
`Tools/tg5040/Grout.pak` are not part of that documented removal, so the Grout
pak remains available after the installer finishes. Do not power off the device
while the installation screen is running; when it completes, power the device
on again.

The upstream `README.txt` also warns that the first-boot installer may modify
the device itself (for example, TrimUI NAND/TF1 paths), not just the card. This
project never writes a block device from the host; that device-side behavior is
upstream's installer, and you should read the upstream notes before booting.

### Stock OS prerequisite

Start from a supported TrimUI device running the **stock TrimUI OS**. If the
device was previously running another CFW, reinstall the stock OS first. No
minimum stock firmware version is documented by this project or by upstream, so
no version is asserted here.

## Filesystem note: exFAT risk and FAT32 fallback

NextUI's documentation allows a card formatted as **FAT32 or exFAT** with an MBR
partition table. The upstream `README.txt` recommends FAT32. This tool's builder
is exFAT-only, and exFAT boot on the Brick has **not been verified** by this
project or its tests.

If the Brick does not boot the exFAT image, the documented fallback is FAT32.
FAT32 is **not implemented** here: there is no FAT32 builder, no `dosfstools`
dependency, no partition type `0c` path, and no `fsck.vfat` check. Adding a
FAT32 builder is a separate future change. Do not treat this image as a
guarantee that the Brick will boot.

## Attribution and licensing

- **NextUI** is licensed under **PolyForm Noncommercial 1.0.0**. It is
  downloaded at build time from the pinned `LoveRetro/NextUI` release and is not
  vendored in this repository. The resulting card image is intended for
  personal, noncommercial use; do not redistribute it commercially.
  <https://github.com/LoveRetro/NextUI>
- **Grout** is licensed under the **MIT License**. It is downloaded at build
  time from the pinned `rommapp/grout` release and is not vendored in this
  repository. <https://github.com/rommapp/grout>

This repository's own code remains GPL-3.0-or-later; the bundled upstream
payloads keep their own licenses.

## Refreshing the pins

Asset names embed upstream build dates, so a refresh touches code, docs, and
tests together:

1. Pick the new NextUI release tag and record the exact asset name, byte size,
   and SHA-256. Do the same for Grout if it is also being refreshed.
2. Update `remote_archives` in
   [`ansible/vars/trimui-brick.yml`](../ansible/vars/trimui-brick.yml)
   (`repo`, `tag`, `asset`, `sha256`, `dest`).
3. Update the pin table and any changed layout details in this document, and the
   pin table in
   [`examples/trimui-brick/README.md`](../examples/trimui-brick/README.md).
4. Update [`tests/ansible-payload-nextui.sh`](../tests/ansible-payload-nextui.sh)
   to match the new top-level entries and Grout `pak.json` version/platform
   assertions.
5. Delete the stale archive from `build/cache` (or use a fresh `cache_dir`).
   The playbook rejects a cached file whose checksum no longer matches the new
   pin, and `get_url` uses `force: false`.
6. Rebuild and run `task validate` plus `task test`. A pin change is not
   complete until the payload test passes against the new archive.
