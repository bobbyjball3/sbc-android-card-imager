# Demo assets

Every file in this directory is a tiny, non-copyrighted placeholder. There are
no real ROMs, BIOS dumps, APKs, artwork, or shader programs here.

- `apks/Demo.apk` is a plain text file with the extension the example manifest
  expects.
- `overlays/GBA/bezel.png` is a valid 1x1 PNG image.
- `shaders/crt-lamp/` contains a minimal text shader preset and shader.
- `manuals/readme.txt` is a text artifact copied to `Manuals/` on the card.

ROMs, BIOS files, and box art are not part of the demo: Cannoli/RomM supplies
those files on the card. The example manifest (`../imager.toml`) references only
the local placeholder paths above, so it can be planned, built, and verified
without a network connection.
