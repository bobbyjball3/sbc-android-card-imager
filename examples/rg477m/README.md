# RG477M Cannoli card

A pinned example for an Anbernic RG477M: a Cannoli-ready card skeleton plus
Obtainium, the Obtainium Emulation Pack, and a Tailscale import file.

## Device

The RG477M uses a MediaTek Dimensity 8300, runs Android 14, and installs
`arm64-v8a` APKs. The image is payload-only: it does not flash or replace the
Android boot images.

## Pins

| Item | Pin | Size | SHA-256 | License |
| --- | --- | --- | --- | --- |
| Obtainium APK | `ImranR98/Obtainium` tag `v1.7.1`, asset `app-arm64-v8a-release.apk` | 27,194,505 bytes | `04dfd02c56dae8d5271d2d402977e1b07c8eeffb313df054a13e71b75b8b8a26` | GPL-3.0 |
| Obtainium Emulation Pack | `RJNY/Obtainium-Emulation-Pack` tag `v8.0.1`, asset `obtainium-emulation-pack-v8.0.1.json` | 78,201 bytes | `c2170687b07881f5891fe9751903c13c31b80de506bd41b718f99abb45592169` | Unlicense |

Both are fetched from their exact GitHub release tags and verified by SHA-256 in
the source cache. The pack is a JSON file, not an APK, so the manifest declares
it as a single-file `[[artifact]]` source. Neither file is vendored in this
repository.

## Tailscale

The local [`obtainium-tailscale.json`](obtainium-tailscale.json) is an Obtainium
import file for `com.tailscale.ipn`. It points Obtainium at
`tailscale/tailscale-android` and deliberately tracks the latest release instead
of pinning a version; at the time of writing the current latest tag is
`1.104.1-t7f4efe814-g6d75bd403` and Obtainium selects the universal APK. The
Tailscale APK itself is not embedded in this image; Obtainium downloads it when
you import the file and refresh apps.

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

## Cannoli skeleton

Building [`rg477m.toml`](rg477m.toml) creates the full pinned skeleton
automatically:

- every top-level Cannoli directory (`Art`, `BIOS`, `Cheats`, `Config`, `Guides`,
  `Media`, `Overlays`, `Roms`, `Save States`, `Saves`, `Shaders`, `Wallpapers`,
  and the retained backup/log directories);
- all 51 `Cannoli/Roms/<TAG>` directories, including the tags above;
- all 68 directories returned by the pinned `cannoli.required_dirs()` contract;
- `Cannoli/Config/settings.json` containing `{}` and a generated `CREDITS.md`.

There are no `[[rom]]`, `[[bios]]`, or `[[art]]` entries. ROMs, BIOS files, and
box art are supplied by Cannoli/RomM on the card; this repository contains no
such payloads.

## Build

Run from the repository root:

```shell
uv run sbc-imager plan --manifest examples/rg477m/rg477m.toml
uv run sbc-imager build --manifest examples/rg477m/rg477m.toml
uv run sbc-imager verify --manifest examples/rg477m/rg477m.toml --image examples/rg477m/dist/rg477m.img
```

The first build resolves both GitHub sources and caches them. Later builds can
use `--offline`:

```shell
uv run sbc-imager build --manifest examples/rg477m/rg477m.toml --offline
```

The build requires Docker; the assembler and filesystem scans run in the pinned
Linux container.

### Card size

With `size = "auto"` and `reserve = "8GiB"`, the manifest produces an image of
about **8.09 GiB**: roughly 26 MiB of content, 64 MiB of filesystem overhead,
8 GiB of reserve, and the 1 MiB MBR offset. That image is sparse and fits any
card larger than the computed size.

To fill a specific larger card, override the size explicitly. For example, for
a 256 GiB card:

```shell
uv run sbc-imager build --manifest examples/rg477m/rg477m.toml --size 256GiB
```

`--size` must leave a 1 MiB aligned partition and must be large enough for the
content plus the 64 MiB overhead. Without `--size`, the build uses the
auto-sized image from the manifest.

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

## Verify

The verification compares every staged file hash and the directory skeleton
against the manifest. For a quick smoke check without writing a full card, use a
small pinned size:

```shell
uv run sbc-imager build --manifest examples/rg477m/rg477m.toml --size 256MiB --output /tmp/rg477m.img --json
uv run sbc-imager verify --manifest examples/rg477m/rg477m.toml --image /tmp/rg477m.img
```
