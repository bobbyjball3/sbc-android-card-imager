# Explicit SD device evidence

Branch: `feat/explicit-sd-device`
Base: `b7a7df5505737f29bae5bd5d5e94849523c2ae4a`
HEAD: `54049098cde6a71767ccf2428232e2bacf217ee7`

## Commits

- `f650e382e9258d31407a1019424ab92c0853fd2f` feat(imaging): assess and list whole disks
- `13b038eddaaec327d2b1c98444198229a0c80bd7` feat(imaging): allow explicit built-in SD targets
- `54049098cde6a71767ccf2428232e2bacf217ee7` docs: document explicit disk and built-in SD selection

## Verification

- `uv run pytest -m "not integration" -q --cov=sbc_imager --cov-fail-under=85`: PASS, 622 passed, 1 skipped, 3 deselected, 92.54% coverage.
- `uv run task lint`: PASS (ruff check, ruff format --check, pyright 0 errors).
- `uv run pre-commit run --all-files`: PASS (ruff check, ruff format, pyright, pytest-unit).
- `git diff --check main..HEAD`: PASS (no output).

See `pytest-coverage.log`, `lint.log`, `pre-commit.log`, `diff-check.log`.

## Read-only disk listing

`image --list` (see `image-list.log`) reports:

| Disk | Model | Protocol | Status | Reason |
| --- | --- | --- | --- | --- |
| disk0 | APPLE SSD AP1024Z | Apple Fabric | blocked | internal disk |
| disk1 | APPLE SSD AP1024Z | Apple Fabric | blocked | virtual disk |
| disk2 | APPLE SSD AP1024Z | Apple Fabric | blocked | virtual disk |
| disk3 | APPLE SSD AP1024Z | Apple Fabric | blocked | virtual disk |
| disk5 | Built In SDXC Reader | Secure Digital | blocked | internal SD reader; re-run with --allow-builtin-sd |

`image --list --allow-builtin-sd` (see `image-list-allow.log`) marks disk5
`allowed` with reason `internal SD reader (--allow-builtin-sd)`.

## Rejection without opt-in

`uv run sbc-imager image --image examples/rg477m/dist/rg477m.img --device /dev/disk5`
exits 2 with:

```text
Error: refusing /dev/disk5; disk5 is not a safe target: internal SD reader; re-run with --allow-builtin-sd
Hint: run `sbc-imager image --list` to inspect every whole disk and its reason
```

See `device-disk5-rejected.log`.

## Dry run only (no write, no sudo)

Command:

```shell
uv run sbc-imager image --image examples/rg477m/dist/rg477m.img \
  --device /dev/disk5 --allow-builtin-sd --dry-run
```

Exits 0 (see `device-disk5-dry-run.log`):

```text
Dry run: no data will be written.
Device: disk5 (/dev/rdisk5)
Model: Built In SDXC Reader
Disk size: 511868665856 bytes (476.715GiB)
Image: examples/rg477m/dist/rg477m.img
Image size: 8686403584 bytes (8.09GiB)
Image SHA-256: dd0b0f88e2d7c9ced977e86be4f6217bb62ce6478596d67ef7542e537790805e
```

`511868665856` bytes is `511.9 GB` in decimal units, matching the expected
511.9 GB.
