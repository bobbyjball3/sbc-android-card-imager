# Cannoli platform tags

Pinned Cannoli version: **v1.9.1**

Pinned commit: `7755e376b6add0bbd25ea19104c368b7a40b979f`

Source: <https://raw.githubusercontent.com/CannoliHQ/cannoli/7755e376b6add0bbd25ea19104c368b7a40b979f/app/src/main/assets/platforms.json>

This registry contains all 51 platform tags shipped by the pinned Cannoli release. ROMs belong in `Cannoli/Roms/<TAG>/`; `APKs/` sits at the card root.

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

## Refreshing the tag registry

This registry is pinned to Cannoli v1.9.1 and is never fetched at runtime. To refresh it, update `CANNOLI_VERSION`, `CANNOLI_COMMIT`, and `CANNOLI_PLATFORMS_URL` in `src/sbc_imager/cannoli.py`, copy the tag/name pairs from the pinned `platforms.json` into `PLATFORM_TAGS`, and regenerate this document:

```shell
uv run python -m sbc_imager.cannoli --markdown > docs/cannoli-platform-tags.md
```
