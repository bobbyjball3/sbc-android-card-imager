# Manifest reference

An sbc-imager TOML manifest describes the card payload. Every
path is resolved relative to the manifest file, so a manifest and its assets can
move together. The loader is strict: unknown tables or keys are errors, not
ignored.

The manifest is validated before any image bytes are written. A valid manifest
still needs its local files to exist and its remote sources to be fetchable at
`plan`/`build` time; the parser itself does not touch those paths.

## Commands and flags

All commands accept the global `--verbose`/`-v` and `--help` options.
`--version` prints the package version and exits.

| Command | Purpose | Flags |
| --- | --- | --- |
| `sbc-imager platforms` | List all 51 Cannoli tags. | `--json` |
| `sbc-imager plan` | Resolve sources, validate, and print the planned tree and sizes. | `--manifest PATH`, `--offline`, `--strict`, `--json`, `--allow-branch` |
| `sbc-imager fetch` | Populate the cache from every declared source. | `--manifest PATH`, `--offline`, `--json`, `--allow-branch` |
| `sbc-imager build` | Fetch, stage, assemble, verify, and atomically publish an image. | `--manifest PATH`, `--output PATH`, `--size SIZE`, `--reserve SIZE`, `--offline`, `--force`, `--keep-work`, `--allow-branch`, `--json` |
| `sbc-imager verify` | Re-verify an image tree against the manifest. | `--image PATH`, `--manifest PATH`, `--offline`, `--allow-branch`, `--json` |
| `sbc-imager image` | Interactively flash a verified image on macOS. | `--image PATH`, `--dry-run` |

There is deliberately no `--device` option and no unattended flashing mode.
`sbc-imager image` requires root only when it actually writes; `--dry-run` does
not.

## Path resolution

- The manifest path itself is opened as-is; `~` expands to your home directory.
- `[[apk]]` and `[[artifact]]` `path` values are local, as are
  `[[overlay]]`/`[[shader]]` `path` values without `source`. A relative path
  resolves against the manifest's directory, `~` expands, and the result is
  resolved to an absolute path.
- For `[[overlay]]` and `[[shader]]`, a missing `source` means the `path` is a
  local path and follows the rule above. When `source` is present, `path` is a
  path inside that source's resolved root (or the source's `subdir`); it must be
  relative and must not contain `..`.
- `[[source]]` with `type = "local"` uses `url` as a local path, resolved against
  the manifest directory when relative.
- `[image].output` resolves against the manifest directory; the default is
  `dist/<name>.img`.
- `as` values are a single filename component, never a path. They rename a file
  destination and are not allowed to contain `/`.

## [image]

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` | string | manifest filename stem | Image name used in defaults and artifacts. |
| `label` | string | `"CANNOLI"` | exFAT volume label. At most 11 characters. |
| `size` | string | `"auto"` | `"auto"` or a pinned size such as `"128GiB"`. |
| `reserve` | string | `"8GiB"` | Free space added by automatic sizing. Still parsed when `size` is pinned. |
| `output` | string | `"dist/<name>.img"` | Output image path, relative to the manifest. |

Sizes accept a whole or up-to-three-decimal number plus `B`, `KiB`, `MiB`,
`GiB`, or `TiB` (case-insensitive). Negative or fractional-byte results are
errors.

## [[source]]

Remote sources may be referenced only by `[[overlay]]` and `[[shader]]` entries.
APKs and generic artifacts must be local.

| Key | Type | Required | Meaning |
| --- | --- | --- | --- |
| `id` | string | yes | Unique source identifier used by overlays/shaders. |
| `type` | string | yes | `local`, `git`, or `url` (HTTP/HTTPS download). |
| `url` | string | yes | Git URL, HTTP(S) URL, or local path for `local`. |
| `ref` | string | for `git` | Tag or 40-character commit SHA. |
| `subdir` | string | no | Relative directory inside the git checkout. |
| `filename` | string | no | HTTPS filename; defaults to the URL basename. |
| `sha256` | string | for `url` | 64-character lowercase hex SHA-256 of the download. |
| `license` | string | for remote | License of the fetched content; also written to `CREDITS.md`. |
| `attribution` | string | for remote | Attribution text; also written to `CREDITS.md`. |

Pinning rules:

- **git:** `ref` must be a tag or an exact 40-hex commit. A branch is rejected
  unless `--allow-branch` is passed; with that flag the branch is fetched, the
  resolved commit is recorded in the cache metadata, and `plan`/`fetch` each
  print a `branch-ref` warning. Submodules and Git LFS are not supported.
- **url:** the SHA-256 is mandatory, so an HTTPS download is pinned by content.
  `http://` is accepted but not recommended.
- **local:** paths are not copied into the cache and are re-read on every build.

Duplicate source ids are rejected. `plan` resolves only sources referenced by an
overlay or shader; `fetch` resolves every declared source; `build` resolves the
sources it needs. An unused source produces a warning.

## Typed entries

ROMs, BIOS files, and box art are supplied by Cannoli/RomM and are not manifest
inputs. The directory skeleton still exists on the card, including
`Cannoli/Roms/<TAG>` for every pinned tag plus top-level `Cannoli/BIOS` and
`Cannoli/Art`. The retired `[[rom]]`, `[[bios]]`, and `[[art]]` tables are
rejected with a migration error.

### [[overlay]]

| Key | Type | Required | Meaning |
| --- | --- | --- | --- |
| `platform` | string | yes | Cannoli tag, case-insensitive. |
| `path` | string | yes | Local file/directory, or a path inside `source`. |
| `source` | string | no | A declared `[[source]].id`. |
| `as` | string | no | Rename a file, or prefix a directory. |

Overlays must be `.png`; non-PNG files in a local directory are skipped with a
warning. With `source`, `path` is source-relative and the source may be a single
file or a directory.

Destination: `Cannoli/Overlays/<TAG>/`.

### [[shader]]

| Key | Type | Required | Meaning |
| --- | --- | --- | --- |
| `path` | string | yes | Local file/directory, or a path inside `source`. |
| `source` | string | no | A declared `[[source]].id`. |
| `as` | string | no | Rename a file, or name a preset directory. |

A shader file must be `.glslp`. A local shader directory must contain a root
`.glslp` preset; its files are copied under that preset name. A source-relative
path with an extension must still be `.glslp`, but a source-relative directory
is copied as declared and is not pre-validated for a root `.glslp` before
source resolution. For example, a resolved source directory containing only
`inner.glsl` is accepted and planned under
`Cannoli/Shaders/<preset>/inner.glsl`.

Destination: `Cannoli/Shaders/<preset>/...`.

### [[apk]]

| Key | Type | Required | Meaning |
| --- | --- | --- | --- |
| `path` | string | yes | Local `.apk` file or directory. |
| `as` | string | no | Rename a file, or prefix a directory. |

APKs are copied only; they are never installed. Destination: `APKs/`.

### [[artifact]]

| Key | Type | Required | Meaning |
| --- | --- | --- | --- |
| `root` | string | no | `cannoli` (default) or `card`. |
| `dest` | string | yes | Relative destination directory inside the chosen root. |
| `path` | string | yes | Local file or directory. |
| `as` | string | no | Rename a single-file entry; ignored for directories. |

Destination: `<card root>/<dest>/...` or `Cannoli/<dest>/...`. Writing into
`Config/` produces an `artifact-config` warning. `Cannoli/Config/settings.json`
and `CREDITS.md` are reserved and cannot be targeted.

## Validation rules

Errors stop the command with exit code 2 before image bytes are written:

- Unknown top-level keys, unknown keys in a table, wrong value types, missing
  required keys, and duplicate `[[source]].id` values.
- The retired `[[rom]]`, `[[bios]]`, and `[[art]]` tables; those files are
  supplied by Cannoli/RomM.
- `source` on an APK or artifact entry (it is an unknown key).
- Unknown or case-ambiguous platform tags on `[[overlay]]`. Tags are normalized
  to the canonical uppercase form from the pinned Cannoli registry.
- A missing local path, or a symlink/special file in a local typed `path` tree
  (local `[[overlay]]`/`[[shader]]`, `[[apk]]`, or `[[artifact]]`). The typed
  root itself may not be a symlink; symlinked parent directories are followed.
  Trees resolved through `[[source]]` (local, git, or URL) are copied as
  declared and are not scanned for symlinks or special files by validation.
- An overlay that is not `.png`; a shader file that is not `.glslp` or a local
  shader directory with no root `.glslp`; an APK that is not `.apk`.
- A typed entry that produces zero files.
- exFAT-invalid path components: the characters `\ / : * ? " < > |`, control
  characters, a trailing dot or space, the reserved names `CON`, `PRN`, `AUX`,
  `NUL`, `COM1`-`COM9`, `LPT1`-`LPT9`, or a component longer than 255 characters.
- Duplicate destinations, and destinations that collide after Unicode NFC
  normalization and case folding.
- Destinations reserved by Cannoli: `Cannoli/Config/settings.json` and
  `CREDITS.md`.
- A label longer than 11 characters, an invalid size/reserve, or content that
  does not fit a pinned size.

Warnings are non-fatal unless `plan --strict` is used:

- `non-nfc-name`, `artifact-config`, `unused-source`, `overlay-non-png`, and
  `branch-ref`.

## Size math

For a plan with `content` bytes of planned files:

```text
overhead       = max(64 MiB, ceil(content / 100))
reserve        = parsed [image].reserve (default 8 GiB)
partition      = align_up(content + overhead + reserve, 1 MiB)   # size = "auto"
image          = 1 MiB + partition
```

The first MiB is the MBR partition offset; the partition starts at LBA 2048 and
is formatted as exFAT with type `0x07`.

For a pinned `[image].size` or `build --size`:

```text
image must be a multiple of 1 MiB plus the 1 MiB offset
image must be at least 1 MiB + content + overhead
partition = image - 1 MiB
```

A pinned size ignores `reserve` for the space budget, though `reserve` is still
parsed. `--reserve` overrides `[image].reserve`; `--size` overrides
`[image].size`; `--output` overrides `[image].output`.

The 64 MiB overhead is a floor, so a tiny fixture needs at least a 66 MiB pinned
image: 1 MiB offset + 64 MiB overhead + content. A 64 MiB image cannot hold the
overhead and any content, and 65 MiB leaves no room for non-zero content.

## Cache and offline mode

The source cache lives under `platformdirs.user_cache_dir("sbc-imager")`.
Override it with `SBC_IMAGER_CACHE_DIR`.

- Git checkouts are keyed by `sha256(url + "\0" + ref + "\0" + subdir)` and
  stored under `<cache>/git/<key>/`, with a `meta.json` recording the URL, ref,
  resolved commit, and fetch time.
- HTTPS files are stored under `<cache>/http/<sha256>/<filename>` and are only
  published after the digest matches.
- Local paths are never cached.

`--offline` forbids network access and requires a valid cached git checkout or
HTTP file. A missing or stale cache entry fails with exit code 1 and names the
cache key or checksum. `fetch --offline` is a cache check, not a download.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | Source/cache failure, assembler or container failure, verification failure, or a failed external command. |
| `2` | Manifest/config validation error, safety refusal, or CLI usage error. |
| `130` | `image` was interrupted after a write started; the card is partially written and must be re-flashed. |

## Examples

### Local payload (valid)

<!-- valid-manifest -->
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

### Local source referenced by an overlay (valid)

<!-- valid-manifest -->
```toml
[image]
name = "local-source"

[[source]]
id = "my-overlays"
type = "local"
url = "overlays"

[[overlay]]
platform = "GBA"
path = "GBA/bezel.png"
source = "my-overlays"
```

### Git overlay source (valid)

<!-- valid-manifest -->
```toml
[image]
name = "git-overlay"

[[source]]
id = "overlays"
type = "git"
url = "https://github.com/example/cannoli-overlays.git"
ref = "v1.0.0"
subdir = "gba"
license = "CC-BY-4.0"
attribution = "Example overlay pack by Example Author"

[[overlay]]
platform = "GBA"
path = "bezel.png"
source = "overlays"
as = "gba-bezel.png"
```

### HTTPS shader source (valid)

<!-- valid-manifest -->
```toml
[image]
name = "https-shader"

[[source]]
id = "crt"
type = "url"
url = "https://example.com/shaders/crt/crt.glslp"
filename = "crt.glslp"
sha256 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
license = "MIT"
attribution = "CRT preset by Example Author"

[[shader]]
path = "crt/crt.glslp"
source = "crt"
as = "crt.glslp"
```

### Pinned size with a reserve (valid)

<!-- valid-manifest -->
```toml
[image]
name = "pinned"
size = "128GiB"
reserve = "4GiB"
output = "dist/pinned.img"

[[artifact]]
root = "cannoli"
dest = "Roms/SNES"
path = "roms/SNES"
```
