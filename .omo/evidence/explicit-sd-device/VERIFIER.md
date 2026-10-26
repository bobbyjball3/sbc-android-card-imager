# Independent verification - explicit SD device

Verdict: **APPROVE**

No blockers found.

## Scope verified

- Worktree: `/Users/bball/projects/sbc-android-card-imager-wt/rg477m-example`
- Branch: `feat/explicit-sd-device`
- HEAD: `54049098cde6a71767ccf2428232e2bacf217ee7` (matches expected)
- Base: `b7a7df5505737f29bae5bd5d5e94849523c2ae4a` (matches expected)
- Commits in `base..HEAD`: 3 (matches expected)
  - `f650e382e9258d31407a1019424ab92c0853fd2f` feat(imaging): assess and list whole disks
  - `13b038eddaaec327d2b1c98444198229a0c80bd7` feat(imaging): allow explicit built-in SD targets
  - `54049098cde6a71767ccf2428232e2bacf217ee7` docs: document explicit disk and built-in SD selection

## Worktree and commit integrity

- `git status --porcelain=v1 --untracked-files=all` was empty before and after verification.
- Every commit has the required footer:
  `Co-authored-by: DeepSeek - Flash <deepseek@deepseek.com>`
- Commit subjects/messages are focused and well below the 75-word limit.
- `git diff --name-status base..HEAD` contains only the 9 expected files:
  - `AGENTS.md`
  - `README.md`
  - `docs/manifest.md`
  - `src/sbc_imager/cli_image.py`
  - `src/sbc_imager/imaging.py`
  - `src/sbc_imager/imaging_write.py`
  - `tests/unit/test_cli_image.py`
  - `tests/unit/test_imaging_enum.py`
  - `tests/unit/test_imaging_write.py`
- `git diff --check main..HEAD` exited 0 with no output.
  - Note: `main` is `0fb6379` and is an ancestor of the expected base. Consequently
    `main..HEAD` includes the pre-existing feature stack. Relative to the specified
    base, only the 3 feature commits and 9 files above are present. This is not a
    feature blocker.

## Automated gates

| Command | Result |
| --- | --- |
| `uv run pytest -m "not integration" -q --cov --cov-fail-under=85` | PASS: 622 passed, 1 skipped, 3 deselected; 92.54% coverage (required 85%) |
| `task lint` | PASS: ruff check clean; ruff format check (77 files); pyright 0 errors, 0 warnings |
| `uv run pre-commit run --all-files` | PASS: ruff check, ruff format, pyright, pytest-unit |
| `git diff --check main..HEAD` | PASS: no output |

## CLI behavior (read-only, uid 501, no sudo)

All commands were run with `uv run sbc-imager ...`. No write command and no `sudo`
was used.

### `image --list` (no root, no image)

Exit 0. Reported:

| Disk | Model | Protocol | Status | Reason |
| --- | --- | --- | --- | --- |
| disk0 | APPLE SSD AP1024Z | Apple Fabric | blocked | internal disk |
| disk1 | APPLE SSD AP1024Z | Apple Fabric | blocked | virtual disk |
| disk2 | APPLE SSD AP1024Z | Apple Fabric | blocked | virtual disk |
| disk3 | APPLE SSD AP1024Z | Apple Fabric | blocked | virtual disk |
| disk5 | Built In SDXC Reader | Secure Digital | blocked | internal SD reader; re-run with --allow-builtin-sd |

### `image --list --allow-builtin-sd`

Exit 0. disk5 changed to `allowed` with reason
`internal SD reader (--allow-builtin-sd)`; disk0/1/2/3 remained blocked.

### Explicit disk5 without opt-in

```shell
uv run sbc-imager image --image examples/rg477m/dist/rg477m.img \
  --device /dev/disk5 --dry-run
```

Exit 2:

```text
Error: refusing /dev/disk5; disk5 is not a safe target: internal SD reader; re-run with --allow-builtin-sd
Hint: run `sbc-imager image --list` to inspect every whole disk and its reason
```

### Explicit disk5 with opt-in, dry run

```shell
uv run sbc-imager image --image examples/rg477m/dist/rg477m.img \
  --device /dev/disk5 --allow-builtin-sd --dry-run
```

Exit 0:

```text
Dry run: no data will be written.
Device: disk5 (/dev/rdisk5)
Model: Built In SDXC Reader
Disk size: 511868665856 bytes (476.715GiB)
Image: examples/rg477m/dist/rg477m.img
Image size: 8686403584 bytes (8.09GiB)
Image SHA-256: dd0b0f88e2d7c9ced977e86be4f6217bb62ce6478596d67ef7542e537790805e
```

### Normalization

Both `--device disk5` and `--device /dev/rdisk5` (with `--allow-builtin-sd
--dry-run`) produced the same exit-0 dry-run result and normalized to
`disk5 (/dev/rdisk5)`. `/dev/disk5` was also exercised and behaved the same.

### Opt-in without an explicit device

```shell
uv run sbc-imager image --image examples/rg477m/dist/rg477m.img \
  --allow-builtin-sd --dry-run
```

Exit 2:

```text
Error: --allow-builtin-sd requires an explicit --device
Hint: select a target with --device /dev/diskN; use --list with --allow-builtin-sd to inspect statuses
```

## Code safety inspection

- `--device` is never a blind bypass. `cli_image.py:61-75` normalizes the input and
  requires a matching `DiskAssessment` whose `allowed` flag is true. Unknown
  identifiers are rejected. Both the assessed allow-list and
  `validate_target()` (`cli_image.py:196-198`) are used before a dry run or write.
- Built-in SD opt-in is narrowly scoped. `DiskInfo.is_builtin_sd`
  (`imaging.py:43-52`) requires whole, internal, `Physical`,
  removable-or-ejectable, and protocol `Secure Digital`/`SD Card`.
  `_assess_disk` (`imaging.py:155-182`) checks virtual, boot, and internal
  status first, so the boot disk is always blocked. `--allow-builtin-sd` never
  widens the external/default path; it only changes the internal-SD branch.
- `write_image(allow_internal=...)` (`imaging_write.py:90-118`) calls
  `validate_target()` again immediately before writing. `validate_target`
  (`imaging_write.py:56-87`) checks boot, whole-disk, internal, and removable
  rules; `allow_internal=True` still rejects internal non-SD disks, and the
  default remains rejection of all internal disks.
- Interactive behavior is unchanged for external disks:
  no `--device` uses `enumerate_disks(runner)` with the default
  `allow_builtin_sd=False`, renders the safe table, prompts for the selection,
  then requires the exact typed `ERASE <diskN>` confirmation.
- `_NO_DISKS` (`cli_image.py:32-35`) points to
  `sbc-imager image --list`; the no-disk path supplies the `_LIST_HINT` as well.
- Docs were checked for stale claims. `AGENTS.md`, `README.md`, and
  `docs/manifest.md` all document `--list`, explicit `--device`, and the
  `--allow-builtin-sd` opt-in. No remaining claim says `--device` is absent or
  that built-in SD slots are never offered.

## No writes and no repository edits

- Only read-only operations were used: `diskutil list`, `diskutil info`,
  `image --list`, `image --help`, and `--dry-run` invocations.
- No `sudo` and no non-dry-run image write were executed.
- The dry runs printed `Dry run: no data will be written.`
- HEAD remained `54049098cde6a71767ccf2428232e2bacf217ee7`.
- `git status --porcelain` remained clean; no source, test, documentation, plan,
  or git metadata was modified by verification.
- The only file written for this verification is this report.

## Evidence path

`/Users/bball/projects/sbc-android-card-imager/.omo/evidence/explicit-sd-device/VERIFIER.md`
