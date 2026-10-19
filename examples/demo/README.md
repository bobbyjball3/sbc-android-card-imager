# Demo assets

Every file in this directory is a tiny, non-copyrighted placeholder. There are
no real ROMs, BIOS dumps, APKs, artwork, or shader programs here.

- `roms/GBA/demo.gba`, `bios/GBA/gba_bios.bin`, and `apks/Demo.apk` are plain
  text files with the extensions the example manifest expects.
- `art/GBA/demo.png` and `overlays/GBA/bezel.png` are valid 1x1 PNG images.
- `shaders/crt-lamp/` contains a minimal text shader preset and shader.
- `manuals/readme.txt` is a text artifact copied to `Manuals/` on the card.

The example manifest (`../imager.toml`) references only these local paths, so
it can be planned, built, and verified without a network connection.
