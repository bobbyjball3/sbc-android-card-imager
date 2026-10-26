# build-device-expand evidence

**Status:** implemented and verified
**Date:** 2026-10-19
**Worktree:** `/Users/bball/projects/sbc-android-card-imager-wt/rg477m-example`
**Branch:** `feat/build-device-expand`
**Base:** `54049098cde6a71767ccf2428232e2bacf217ee7`
**HEAD:** `92ae713` (`docs: document build-time target sizing`)

## Commits

- `ac6c599` `feat(build): size images to the target disk`
- `92ae713` `docs: document build-time target sizing`

Both include `Co-authored-by: DeepSeek - Flash <deepseek@deepseek.com>`.

## Automated gates

- `uv run pytest -m "not integration" -q`: **650 passed, 1 skipped, 3 deselected**
- Coverage with `--cov-fail-under=85`: **92.65%**, passed
- `task lint`: ruff check, format check, pyright all passed
- `uv run pre-commit run --all-files`: all hooks passed
- `git diff --check main..HEAD`: exit 0

## CLI surface

`uv run sbc-imager build --help` now exposes:

- `--device`
- `--expand`
- `--allow-builtin-sd`

Flag rules implemented and tested:

- `--expand` requires `--device`
- `--device` requires `--expand`
- `--size` conflicts with `--expand`
- `--allow-builtin-sd` requires `--device`
- unsafe target devices are rejected with the assessment reason and `image --list` hint

## Disk5 sizing (read-only, no build)

```text
device          = disk5
model           = Built In SDXC Reader
disk_bytes      = 511,868,665,856
image_bytes     = 511,868,665,856
partition_bytes = 511,867,617,280
size string     = "488156MiB"
```

Without `--allow-builtin-sd`:

```text
refusing /dev/disk5; disk5 is not a safe target: internal SD reader; re-run with --allow-builtin-sd
hint: run `sbc-imager image --list` to inspect every whole disk and its reason
```

## Usage

```shell
uv run sbc-imager build \
  --manifest examples/rg477m/rg477m.toml \
  --device /dev/disk5 \
  --allow-builtin-sd \
  --expand
```

This only reads disk geometry and sizes the image; it does not write the card.
The host image is sparse; flashing still writes the full logical size.

Then:

```shell
sudo -E uv run sbc-imager image \
  --image examples/rg477m/dist/rg477m.img \
  --device /dev/disk5 \
  --allow-builtin-sd
```

## Residual risks

- No real 512 GB image/build was executed; sizing and CLI behavior are proven by unit tests and a read-only disk5 assessment.
- `build --expand` uses macOS `diskutil`; non-expand builds remain platform-independent.
- The disk geometry is read at build time and is not bound to the later flash target; the image command revalidates fit and safety.
- `--reserve` is still parsed but does not affect an expanded size.
- The host image is sparse; the card write is still the full logical size.
- No push or merge was performed.
