# Cannoli platform tags

Pinned Cannoli version: **v1.9.1**

Pinned commit: `7755e376b6add0bbd25ea19104c368b7a40b979f`

Source: <https://raw.githubusercontent.com/CannoliHQ/cannoli/7755e376b6add0bbd25ea19104c368b7a40b979f/app/src/main/assets/platforms.json>

This document is the human reference for the on-card folder contract. The
runtime source of truth is [`ansible/vars/cannoli.yml`](../ansible/vars/cannoli.yml):
the Ansible playbook stages one `Cannoli/Roms/<TAG>` directory per tag below,
the 17 base directories, and the `settings.json` install marker. There is no
Python registry and no network access at runtime.

## Directory contract

`ansible/vars/cannoli.yml` declares:

- **17 base directories** (`cannoli_base_dirs`), relative to the card root:
  `Cannoli`, `Cannoli/Art`, `Cannoli/BIOS`, `Cannoli/Backup`, `Cannoli/Cheats`,
  `Cannoli/Config`, `Cannoli/Guides`, `Cannoli/Logs`,
  `Cannoli/Media/Screenshots`, `Cannoli/Media/Recordings`, `Cannoli/Overlays`,
  `Cannoli/Roms`, `Cannoli/Save States`, `Cannoli/Saves`, `Cannoli/Shaders`,
  `Cannoli/Wallpapers`, and `APKs`.
- **51 platform tags** (`cannoli_tags`), each staged as `Cannoli/Roms/<TAG>`.
- **the settings marker** (`cannoli_settings_marker`):
  `Cannoli/Config/settings.json`, a file written as exactly `"{}\n"` that
  preselects the card as a Cannoli install.

The staged tree is 70 directories: the 17 base dirs + 51 Roms tag dirs + the
implicit `Cannoli/Media` parent + `Obtainium` (the destination of device
`local_files`). There is no `CREDITS.md` in the staged tree.

## Tags

This registry contains all 51 platform tags shipped by the pinned Cannoli
release. ROMs belong in `Cannoli/Roms/<TAG>/`; `APKs/` sits at the card root.

| Tag | Platform | Notes |
| --- | --- | --- |
| GB | Game Boy |  |
| GBC | Game Boy Color |  |
| GBA | Game Boy Advance |  |
| NES | Nintendo Entertainment System |  |
| FDS | Famicom Disk System |  |
| SNES | Super Nintendo Entertainment System |  |
| N64 | Nintendo 64 |  |
| NDS | Nintendo DS |  |
| GG | Game Gear |  |
| SMS | Master System |  |
| MD | Sega Genesis |  |
| SG1000 | Sega SG-1000 |  |
| 32X | Sega 32X |  |
| SEGACD | Sega CD |  |
| SATURN | Sega Saturn |  |
| PS | PlayStation |  |
| PSP | PSP |  |
| DC | Dreamcast |  |
| LYNX | Atari Lynx |  |
| JAGUAR | Atari Jaguar |  |
| ATARI2600 | Atari 2600 |  |
| ATARI5200 | Atari 5200 |  |
| ATARI7800 | Atari 7800 |  |
| PCE | PC Engine |  |
| PCFX | PC-FX |  |
| PICO8 | PICO-8 |  |
| NGP | Neo Geo Pocket |  |
| NGPC | Neo Geo Pocket Color |  |
| WS | WonderSwan |  |
| WSC | WonderSwan Color |  |
| NEOGEO | Neo Geo |  |
| MAME | Arcade |  |
| FBN | Arcade |  |
| VIRTUALBOY | Virtual Boy |  |
| POKEMINI | Pokemon Mini |  |
| COLECOVISION | ColecoVision |  |
| VECTREX | Vectrex |  |
| INTELLIVISION | Intellivision |  |
| SUPERGRAFX | PC Engine SuperGrafx |  |
| DOS | DOS |  |
| SCUMMVM | ScummVM |  |
| AMIGA | Amiga |  |
| PC | PC | shortcut files only |
| PS2 | PlayStation 2 |  |
| GC | GameCube |  |
| WII | Wii |  |
| 3DS | Nintendo 3DS |  |
| WIIU | Wii U |  |
| PSVITA | PS Vita |  |
| PS3 | PlayStation 3 |  |
| NSW | Nintendo Switch |  |

## Hard-required BIOS

These platforms will not start without the listed BIOS files. Place them under `Cannoli/BIOS/<TAG>/`.

| Tag | Required files |
| --- | --- |
| SATURN | `sega_101.bin`, `mpr-17933.bin` |
| PCFX | `pcfx.rom` |
| PSP | `PPSSPP/ppge_atlas.zim` |
| INTELLIVISION | `exec.bin`, `grom.bin` |
| COLECOVISION | `Databases/msxromdb.xml`, `Machines/Shared Roms/MSX.rom` |
| AMIGA | `kick34005.A500`, `kick40068.A1200`, `kick40060.CD32`, `kick40060.CD32.ext` |

## Refreshing the contract

The contract is pinned to Cannoli v1.9.1 and is never fetched at runtime. To
refresh it, fetch the pinned upstream `platforms.json` for the chosen release
and update, in one change:

1. `cannoli_tags` (and any changed base directories or the marker path) in
   `ansible/vars/cannoli.yml`;
2. this document (tag table, base-dir list, BIOS notes);
3. the test expectations: the derived counts and base-directory checks in
   `tests/ansible-payload.sh` (17 base, 51 tags, 70 directories).
