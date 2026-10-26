# F1 - Plan compliance audit

**Verdict: CHANGES_REQUESTED**

- Plan audited: `/Users/bball/projects/sbc-android-card-imager/.omo/plans/sbc-android-card-imager.md`
- Worktree audited: `/Users/bball/projects/sbc-android-card-imager-wt/sbc-android-card-imager-wave-3`
- Branch / HEAD: `feat/sbc-imager-wave-3` / `98919d335dc90fc656101f9b3add1d0b47dfd4fa`
- `feat/sbc-imager`: `98919d3` (same commit)
- `main`: `0fb6379` (untouched)
- Audit mode: read-only (no source, plan, commit, or push changes). This file is the only write.

## Commands run

```text
uv run sbc-imager --version                     -> 0.1.0
uv run sbc-imager --help                        -> six commands present
uv run sbc-imager platforms --json              -> 51 entries
uv run sbc-imager plan --manifest examples/imager.toml --json
                                                -> exit 0, pure JSON
uv run pytest -m "not integration" -q           -> 506 passed, 1 skipped, 3 deselected
uv run ruff check . && uv run ruff format --check .
                                                -> all checks passed; 74 files formatted
git status --porcelain (all 10 worktrees)       -> empty everywhere
```

## Blocking findings

### 1. Plan still requires a 64 MiB demo build; repository proves 64 MiB is impossible and uses 66 MiB

The plan's own size math is `overhead = max(64 MiB, ceil(content / 100))` plus a
1 MiB partition offset. A 64 MiB image therefore cannot contain the 64 MiB
overhead and any non-zero content, but the plan still specifies 64 MiB in four
places:

- Plan line 86: integration tests use "a 64 MiB image".
- Plan line 89: E2E is `build --size 64MiB`.
- Plan line 299 (todo 17 acceptance): `build --size 64MiB ... exits 0`.
- Plan lines 305 and 309 (todo 18): E2E "builds a 64 MiB image".

The repository correctly implements and documents the 66 MiB minimum, and the
execution evidence shows the 64 MiB acceptance criterion failing:

- `README.md:94-99` - "The 66 MiB minimum ... A 64 MiB image therefore cannot hold ...".
- `docs/manifest.md:255-256` - 64 MiB overhead floor; 66 MiB minimum for the demo.
- `tests/integration/test_build_e2e.py:32-35` - `IMAGE_SIZE = "66MiB"`.
- `.omo/evidence/task-17-sbc-android-card-imager.log:60-82` - 64 MiB probe exits 2
  with `content-overflow`; 66 MiB build exits 0.
- `.omo/evidence/task-18-sbc-android-card-imager.log:55-64` - same conclusion.

**Required remediation:** update the plan's acceptance text (lines 86, 89, 299,
305, 309) from 64 MiB to 66 MiB, or change the sizing contract so 64 MiB is
genuinely buildable. This is a plan/repo mismatch: todo 17 and todo 18 are marked
`[x]` although their written acceptance criteria cannot pass.

### 2. Todo 15 says apt packages are pinned to resolved versions; Dockerfile installs unpinned packages

Plan line 275 requires `apt-get install --no-install-recommends e2fsprogs
exfatprogs util-linux` **pinned to resolved versions**. `Dockerfile:12-17` installs
`e2fsprogs`, `exfatprogs`, `util-linux`, and `fdisk` with no version constraints.
The base image is digest-pinned (`Dockerfile:5`), but the apt layer is still
re-resolved on every build, so the "pinned assembler container" guarantee is
incomplete. Task-15 evidence lists the versions observed during that one build
(`e2fsprogs 1.47.0-2+b2`, etc.) but does not pin them.

**Required remediation:** either pin each package to the resolved Debian version
in `Dockerfile:13-17` or amend plan line 275 to state that only the base image is
digest-pinned. The extra `fdisk` package is justified by the `sfdisk` integration
assertions, but it is also absent from the plan's package list.

### 3. Todo 10 requires a branch warning; the user-facing command prints none

Plan line 225 says a branch ref is rejected unless `allow_branch` is set, "and then
emits a warning." The implementation stores a warning only in
`ResolvedSource.metadata["warning"]` (`src/sbc_imager/sources_git.py:102-122`);
the planner's `warnings` tuple is populated only from `validate_manifest`, so no
warning reaches `plan`, `fetch`, `build`, or the CLI. The documentation makes the
deviation explicit and the test locks it in:

- `docs/manifest.md:80-82` - "No warning is printed."
- `tests/unit/test_docs.py:94-99` - asserts the doc does not claim a branch warning.

**Required remediation:** either surface the metadata warning through the planner
and CLI, or amend plan line 225 to match the documented behavior.

## Non-blocking deviations to reconcile

- **Container argv (todo 15).** Plan line 275 specifies
  `-v <work>:/work:ro`, `--out /out/<name>.img.partial`, and
  `--report /out/<name>.report.json`. `src/sbc_imager/container.py:127-154`
  instead mounts the plan directory at `/plan`, writes `/out/<name>.img`, and has
  no `--report`; the host writes `<output>.report.json` in `build.py`. Behavior is
  functionally complete, but the exact interface described in the plan is not the
  one implemented.
- **`Taskfile.yml` setup (todo 4).** Plan line 165 says `uv run pre-commit install`;
  `Taskfile.yml:8` uses `--allow-missing-config`.
- **Evidence extensions (todos 16 and 17).** The plan names `.json` evidence
  (lines 290 and 300); the delivered files are
  `task-16-sbc-android-card-imager.log` and
  `task-17-sbc-android-card-imager.log`. The evidence exists, so this is a naming
  mismatch rather than missing evidence.

## Passing checks

### 1. Checkbox state

- 24 implementation rows, all `- [x] N.` (plan lines 134-372).
- F1-F4 remain `- [ ] F<n>.` (plan lines 376-382).
- No implementation row is unchecked and no final row is checked.

### 2. Structural grammar

Every implementation row is column-zero and contains all required fields:
`What to do / Must NOT do`, `Closes`, `Parallelization`, `References`,
`Acceptance criteria`, `QA scenarios`, `Commit`, and a nested
`Recommended task executor category`. Every QA block contains a happy path and a
failure path. Headings are in template order and the first `##` heading is
`## TL;DR (For humans)` (line 3).

### 3. Gaps and ideal states

- GAP-1 through GAP-10 are each referenced by at least one implementation row:
  GAP-1 (1,2,4,6,22,24), GAP-2 (7,8,12,17), GAP-3 (3), GAP-4 (8,9,10,11,12),
  GAP-5 (13,14,15,17), GAP-6 (14,16,17,18), GAP-7 (19,20,21),
  GAP-8 (2,4,5,18), GAP-9 (22,23), GAP-10 (1,22,24).
- `## Success criteria` (plan lines 396-407) maps IS-1 through IS-10, each with
  delivering todos, a proving QA scenario, and an evidence path. All referenced
  evidence files exist in the per-wave worktrees (see inventory below).

### 4. Guardrails and scope

No Must-NOT-have feature leaked into the repository:

- No bootable Android/vendor partition or bootloader logic.
- No APK installation, `adb`, app management, or `Android/data`/`Android/obb` writes.
- No ROM/BIOS/art downloads; remote `[[source]]` is limited to overlay/shader use.
- No scraping, metadata database, or art fetching.
- No RetroArch cores or `.so` files on the card.
- No native macOS assembler; assembly runs in the container.
- No Windows imaging and no unattended flashing; no `--device` or `--yes`.
- No compression, ROM renaming/reorganization, symlinks, or manifest-driven hooks.

The mentions of these terms in `README.md` and `docs/manifest.md` are explicit
limitations, not implementations.

### 5. Promised artifacts

All exist in the audited worktree:

- `pyproject.toml`, `Taskfile.yml`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`
- `Dockerfile`, `.dockerignore`
- `src/sbc_imager/` (32 files including `py.typed`)
- `docs/manifest.md`, `docs/cannoli-platform-tags.md` (51 tags)
- `examples/imager.toml` and all `examples/demo/` placeholders
- `tests/` (31 test modules plus fixtures)
- `AGENTS.md` `## Project Implementation Notes` at line 48; diff vs `main` is
  append-only after `# END Global Rules`.

CLI commands verified live: `platforms`, `plan`, `fetch`, `build`, `verify`,
`image`; `--version` prints `0.1.0`; `platforms --json` returns 51 rows.
Docker preflight is implemented in `src/sbc_imager/assembler.py:146-183`
(`losetup -f`, `mkfs.exfat --version`, `fsck.exfat --version`, `exfat` in
`/proc/filesystems`) and is invoked with
`docker run --rm --privileged --network none <tag> python -m sbc_imager.assembler --preflight`
in `src/sbc_imager/container.py:78-105`.

### 6. Git state

`git status --porcelain` is empty in the main checkout and all nine linked
worktrees. `feat/sbc-imager` and `feat/sbc-imager-wave-3` both resolve to
`98919d3`. `main` remains at `0fb6379`.

## Evidence inventory

All 24 task evidence files exist, distributed across the per-wave attempt
directories:

- Wave 0: tasks 1-6 in `sbc-android-card-imager-wave-0/.omo/evidence/`
- Wave 1: tasks 7, 10, 11, 12 in `.../wave-1/.omo/evidence/`; tasks 8 and 9 in
  the `w1-t8` and `w1-t9` worktrees
- Wave 2: tasks 14-18 in `.../wave-2/.omo/evidence/`
- Wave 3: tasks 19-21 in `.../wave-3/.omo/evidence/`; tasks 22-24 in the
  `w3-t22`, `w3-t23`, and `w3-t24` worktrees
- Task 13: `/Users/bball/projects/sbc-android-card-imager/.omo/evidence/`

No task evidence is missing. The only naming mismatch is the `.log` vs `.json`
extension for tasks 16 and 17 noted above.

## Required actions before APPROVE

1. Resolve the 64 MiB acceptance mismatch in plan lines 86, 89, 299, 305, and 309
   (recommended: change to 66 MiB, matching the implementation, docs, E2E fixture,
   and task-17/task-18 evidence).
2. Pin the apt packages in `Dockerfile:13-17`, or amend plan line 275 to state
   that only the base image is digest-pinned.
3. Surface the `--allow-branch` warning (plan line 225) or amend the plan to match
   the documented "No warning is printed" behavior.
4. Reconcile the container argv described in plan line 275 with
   `src/sbc_imager/container.py:127-154`, or update the plan to the delivered
   interface.
