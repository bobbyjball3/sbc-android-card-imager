# F4 final gate - spec-compliance re-verification

**Verdict: APPROVE**

- Original request: `/Users/bball/projects/sbc-android-card-imager/PROMPT.md` / plan `/Users/bball/projects/sbc-android-card-imager/.omo/plans/sbc-android-card-imager.md`
- Worktree: `/Users/bball/projects/sbc-android-card-imager-wt/sbc-android-card-imager-wave-3`
- Branch: `feat/sbc-imager-wave-3`
- Final HEAD: `13b6751946c690aa55a5e51faa51965be401d53d`
- `main`: `0fb6379f891bc0c1dd47f9998bb3173cc41a32eb` (untouched)
- Audit mode: read-only. No source, test, docs, plan, or git changes. This file is the only write. F4 remains unchecked in the plan.

No blockers. The shipped implementation at final HEAD still satisfies the original
request, and the hardening commits `f9341ed`..`14c49da` plus docs commit
`13b6751` did not regress the spec. Every claim below was checked with command
output or direct inspection at `13b6751`, not from worker prose.

## 1. Required command surface

`uv run sbc-imager --help` exposed exactly the requested commands:

```text
platforms  List every Cannoli platform tag and its display name.
plan       Resolve sources, size the image, and print the planned card tree.
fetch      Populate the source cache from every declared source.
build      Build, verify, and atomically publish a card image.
image      Flash a verified image to a removable card after typed confirmation.
verify     Verify an image's tree against the manifest without writing to it.
```

`uv run sbc-imager --version` -> `0.1.0`. `uv run sbc-imager platforms --json`
returned **51** tags, from `GB` through `NSW`. `uv run sbc-imager image --help`
showed only `--image`, `--dry-run`, and `--help`; there is **no `--device`**, no
`--yes`, and no unattended mode.

Manifest-driven demo plan at final HEAD (`examples/imager.toml`, no `--size`):

```text
Content: 830B  Overhead: 64MiB  Reserve: 1MiB
Partition: 66MiB at offset 1MiB  Image: 67MiB
```

That matches README: the default demo auto-sizes to 67 MiB (1 MiB offset +
66 MiB partition), while the documented pinned demo build is 66 MiB.

## 2. Packaging proof

Built from the worktree to an isolated temp output directory to preserve
read-only state:

```text
$ uv build --out-dir <tmp>/dist
Successfully built .../sbc_android_card_imager-0.1.0.tar.gz
Successfully built .../sbc_android_card_imager-0.1.0-py3-none-any.whl
```

Wheel inspection (`unzip -l`) contains:

- `sbc_imager/cli.py`
- `sbc_imager/py.typed` (0 bytes, as expected)
- `sbc_android_card_imager-0.1.0.dist-info/entry_points.txt`

Entry point contents:

```text
[console_scripts]
sbc-imager = sbc_imager.cli:app
```

Isolated install with `UV_TOOL_DIR`/`UV_TOOL_BIN_DIR` pointed inside the same
temp directory (no global install):

```text
$ uv tool install --force <tmp>/dist/*.whl
Installed 16 packages
 + sbc-android-card-imager==0.1.0 (from file:///.../sbc_android_card_imager-0.1.0-py3-none-any.whl)
Installed 1 executable: sbc-imager

$ <tmp>/bin/sbc-imager --version
0.1.0
$ <tmp>/tool/sbc-android-card-imager/bin/python -m sbc_imager --version
0.1.0
```

The installed CLI `--help` also listed all six commands. `tests/unit/test_packaging.py`
passed 4/4 (`uv run pytest tests/unit/test_packaging.py -q`).

## 3. Test, lint, and type gates

```text
$ uv run pytest tests/unit -q
518 passed, 1 skipped in 4.87s
```
The skip is the pre-existing environment-dependent APFS sparse-hole assertion in
`tests/unit/test_fs.py:156`.

```text
$ uv run pytest tests/unit/test_imaging_write.py tests/unit/test_config.py \
    tests/unit/test_cli_plan.py tests/unit/test_docs.py tests/unit/test_cannoli.py -q
95 passed in 1.34s

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
74 files already formatted
$ uv run pyright
0 errors, 0 warnings, 0 informations
```

Real Linux integration path was also run against the final source in the pinned
assembler container:

```text
$ docker run --rm --privileged -v "$PWD:/src" -w /src sbc-imager-assembler:f4-final \
    sh -c 'pip install -q pytest && PYTHONPATH=/src/src python -m pytest -m integration -q'
3 passed, 519 deselected in 0.62s
```

## 4. End-to-end demo build at final HEAD

Built the real demo through the CLI and Docker at 66 MiB:

```text
$ uv run sbc-imager build --manifest examples/imager.toml --size 66MiB \
    --output <tmp>/demo.img
Staged 8 files in <tmp>/sbc-build-...
preflight ok: loop devices, mkfs.exfat, fsck.exfat, and exfat are available
assembled 8 files (830 bytes) into /out/demo.img
verified 10 files from /image/demo.img
Wrote <tmp>/demo.img (66MiB)
Size: 66MiB  SHA-256: 98ad8c839653fa4aa0ed7c84b0b8485b92f4c4d6e366ab3ffbbe01788bf1f442  Verified files: 10
```

`demo.img.report.json` confirmed:

```json
"content_bytes": 830,
"content_files": 8,
"image_bytes": 69206016,
"offset": 1048576,
"partition_bytes": 68157440,
"verify": {"actual_files": 10, "expected_files": 10, "ok": true, ...},
"warnings": []
```

Re-verification through the CLI:

```text
$ uv run sbc-imager verify --image <tmp>/demo.img --manifest examples/imager.toml
verified 10 files from /image/demo.img
Verification passed: 10 files match the manifest.
```

Direct image inspection in the pinned container:

```text
$ sfdisk -d /images/demo.img
/images/demo.img1 : start= 2048, size= 133120, type=7

root: APKs  CREDITS.md  Cannoli  Manuals
Cannoli/Roms/<TAG> directories: 51
Cannoli/Config/settings.json bytes: 7b 7d 0a   -> "{}\n"
CREDITS.md: "# Credits ... Cannoli v1.9.1 (commit 7755e37...) ... GPL-3.0 ..."
files in image: 10 (8 declared + settings marker + CREDITS.md)
```

This confirms MBR type `0x07` at LBA 2048, exFAT, all 51 Cannoli tag folders,
`Config/settings.json {}`, and `CREDITS.md`.

## 5. Pinned sources (git / HTTP / local)

Git source (local bare repo, branch `main`):

```text
$ sbc-imager plan --manifest branch.toml
exit=2
Error: git source 'assets' ref 'main' is a branch; pass --allow-branch to use it

$ sbc-imager plan --manifest branch.toml --allow-branch
Warning [0]: branch-ref: source[0] 'assets': branch ref accepted because --allow-branch was set

$ sbc-imager fetch --manifest branch.toml --allow-branch
Warning [0]: branch-ref: source[0] 'assets': branch ref accepted because --allow-branch was set

$ sbc-imager fetch --manifest branch.toml --allow-branch --json
[{"id":"assets","type":"git","root":"...","warnings":[{"code":"branch-ref", ...}]}]
```

HTTP source (local server, pinned SHA-256):

```text
$ sbc-imager fetch --manifest http.toml
crt  url  <cache>/http/<sha256>/crt.glslp
$ sbc-imager fetch --manifest http.toml --offline
crt  url  <cache>/http/<sha256>/crt.glslp
$ sbc-imager plan --manifest http.toml
Cannoli/Shaders/crt/crt.glslp  shader  5B
$ sbc-imager fetch --manifest bad-sha.toml
exit=1
Error: http source 'crt' checksum mismatch: expected 000..., got 37bff2...
```

Local source:

```text
$ sbc-imager plan --manifest local.toml
Cannoli/Overlays/GBA/bezel.png  overlay  3B
$ sbc-imager fetch --manifest local.toml
overlays  directory  <tmp>/local/overlays
```

The demo itself uses only local paths and built without network access.

## 6. Hardening commits re-verified

### Docker apt pins (`f9341ed`)

Fresh no-cache build of the delivered Dockerfile succeeded:

```text
$ docker build --no-cache -t sbc-imager-assembler:f4-final .
... exporting to image ... DONE
```

Installed versions exactly match the pins, and privileged preflight passes:

```text
e2fsprogs=1.47.0-2+b2
exfatprogs=1.2.0-1+deb12u1
fdisk=2.38.1-5+deb12u3
util-linux=2.38.1-5+deb12u3
preflight ok: loop devices, mkfs.exfat, fsck.exfat, and exfat are available
```

A normal `docker build -t sbc-imager-assembler:local .` also succeeded.

### Branch warning surfacing (`efae552`)

Covered by direct CLI runs above and by 5 branch-warning tests in
`tests/unit/test_cli_plan.py`; `plan`, `plan --json`, `fetch`, and
`fetch --json` all surface `branch-ref`.

### Symlink-root rejection (`520c5a2`)

```text
$ sbc-imager plan --manifest symlink.toml
exit=2
Error: symlink: rom[0] is a symlink: <tmp>/link-roms
```

Unit tests also prove a symlinked parent directory is still followed and rejected
only when the typed root itself is a symlink, matching `docs/manifest.md`.

### Generated-doc whitespace (`fb580cd`) and `SIZE_OK` (`c6ba1d4`)

`tests/unit/test_docs.py` passed, including exact equality between
`render_markdown()` and `docs/cannoli-platform-tags.md`. `src/sbc_imager/cannoli.py`
contains the intentional `# allow: SIZE_OK` marker documented in `AGENTS.md`.

### Writer defense-in-depth (`14c49da`)

`write_image` now rechecks `disk.whole` and `disk.internal` before any root check,
unmount, open, or copy. Two parametrized tests prove both refusals leave the
target untouched and make no runner calls. The writer still targets only
`/dev/rdisk<N>`, rejects `/dev/disk*`, aliases, block-device overrides, symlinked
devices, non-root writes, oversized images, and failed unmounts; it never uses
`dd` or a shell.

## 7. Docs/README claims vs actual behavior

| Claim | Evidence |
| --- | --- |
| 66 MiB demo / 67 MiB auto | Actual `--size 66MiB` build is 69,206,016 bytes; default plan is 67 MiB. |
| 51 tags and full Cannoli layout | `platforms --json` = 51; image has 51 `Cannoli/Roms/<TAG>` dirs. |
| `Config/settings.json {}` | Image bytes are `7b 7d 0a` = `{}\n`. |
| `CREDITS.md` | Present in image and contains Cannoli v1.9.1/GPL-3.0. |
| Branch refs need `--allow-branch` and warn | Direct CLI runs + tests. |
| Typed local root symlinks rejected | Direct CLI run exit 2 + tests. |
| Symlinked parent directories followed | `test_load_manifest_when_typed_path_parent_is_symlink_allows`. |
| Docker packages pinned to exact bookworm versions | Fresh no-cache build installed exact pins. |
| Writer rechecks whole/non-internal disk | Code + tests + AGENTS claim. |
| No `--device` / no unattended flashing | `image --help` shows only `--image`/`--dry-run`. |
| No Android system image / APK install / ROM-BIOS downloads / zero-touch boot / native macOS assembler | Source and docs inspection below. |

## 8. Out-of-scope feature checks

No out-of-scope behavior was found in `src/`, `tests/`, `docs/`, `README.md`,
`examples/`, `Dockerfile`, or `Taskfile.yml`:

- No Android system image, bootloader, kernel, `super`, `system`, `vendor`,
  `userdata`, `misc`, or `vbmeta` handling.
- APK handling is copy-only to `APKs/`; no `adb`, `fastboot`, package install,
  or app management.
- Remote `[[source]]` entries are only usable by `[[overlay]]` and `[[shader]]`;
  ROM/BIOS/art/APK/artifact tables reject a `source` key and use local paths only.
  No ROM/BIOS/art downloading.
- No zero-touch boot; README documents manual first-launch configuration.
- No `--device`, `--yes`, batch, or unattended flashing.
- Image assembly is Python inside the pinned Linux container; there is no native
  macOS assembler and no Windows build path.

The only matches for `adb`, `--device`, and `zero-touch` are negative README/doc
statements and a test asserting `--device` is absent.

## 9. Git state

```text
worktree: feat/sbc-imager-wave-3   (clean, no short entries)
HEAD:     13b6751946c690aa55a5e51faa51965be401d53d
main:     0fb6379f891bc0c1dd47f9998bb3173cc41a32eb (clean, unchanged)
main is an ancestor of HEAD
```

Non-blocking note only: `feat/sbc-imager` still points at `98919d3`, while the
final hardening and docs commits are on `feat/sbc-imager-wave-3`. The task defines
the final HEAD as `13b6751` in this worktree, so this is not treated as a spec
blocker.

## 10. Verdict

**APPROVE. Exact blockers: none.**

The final HEAD satisfies the requested command surface, manifest-driven pipeline,
pinned git/HTTP/local sources, 66 MiB demo, MBR+exFAT Cannoli image, 51 tags,
`Config/settings.json {}`, `CREDITS.md`, and safe macOS `/dev/rdisk` writer. The
hardening changes are effective and regression-tested, and no out-of-scope feature
was introduced.

Evidence path:
`/Users/bball/projects/sbc-android-card-imager/.omo/evidence/F4-final-sbc-android-card-imager.md`
