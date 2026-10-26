# F1 final gate - plan compliance re-audit

**Verdict: APPROVE**

- Plan: `/Users/bball/projects/sbc-android-card-imager/.omo/plans/sbc-android-card-imager.md`
- Worktree: `/Users/bball/projects/sbc-android-card-imager-wt/sbc-android-card-imager-wave-3`
- Branch: `feat/sbc-imager-wave-3`
- Final HEAD: `13b6751946c690aa55a5e51faa51965be401d53d`
- `main`: `0fb6379f891bc0c1dd47f9998bb3173cc41a32eb` (untouched)
- Audit mode: read-only. No source, test, docs, plan, or git changes. This file is
  the only write. F1 remains unchecked in the plan.

No blockers. All four prior F1 findings are closed at the final HEAD, and the
required structural, scope, and shipped-behavior checks pass.

## Prior F1 findings

| Prior finding | Status | Fresh evidence at `13b6751` |
| --- | --- | --- |
| 1. Demo/build references used 64 MiB where 64 MiB overhead applies | **Closed** | Plan demo/build references are 66 MiB: lines 89, 299, 300, 305, 381. Line 86 explains 64-66 MiB test images and states the Cannoli E2E uses 66 MiB. No `--size 64MiB` remains in the plan or repo. Raw 64 MiB references remain only where valid: MBR sizing (line 260), raw assembler integration (line 269), and raw verify integration (line 290). `README.md:94-99`, `docs/manifest.md:255-257`, and `tests/integration/test_build_e2e.py:32-35` agree on the 66 MiB minimum. |
| 2. Dockerfile apt packages were unpinned; plan did not match | **Closed** | `Dockerfile:13-17` pins `e2fsprogs=1.47.0-2+b2`, `exfatprogs=1.2.0-1+deb12u1`, `util-linux=2.38.1-5+deb12u3`, and `fdisk=2.38.1-5+deb12u3`; the base image is digest-pinned at `Dockerfile:5`. Plan line 275 now specifies exact bookworm versions and includes `fdisk`. Fresh `docker build` at HEAD exited 0; the apt log confirmed those exact versions; fresh privileged preflight exited 0. |
| 3. `--allow-branch` branch warnings were not surfaced | **Closed** | `sources_git.py:102-110` creates the branch warning; `planner.py:165-180` lifts it into the shared `Warning` schema (`validation_common.py:13`); `build_plan` extends validation warnings (`planner.py:268-269`). `plan` prints and serializes it (`planner.py:200-210`, `cli.py:130-145`); `fetch` prints and attaches it per source in JSON (`cli.py:246-260`). Docs (`docs/manifest.md:80-83`) and tests agree. Fresh targeted tests: 5 branch-warning tests passed, 22 docs/config tests passed. |
| 4. Container argv/CMD did not match the plan | **Closed** | Plan line 275 now matches `container.py:127-154`: `-v <work>:/plan:ro`, `-v <stage>:/stage:ro`, `-v <out>:/out`, `--work /tmp/assemble`, and no `--report`. Plan CMD matches `Dockerfile:25`: `CMD ["python", "-m", "sbc_imager.assembler", "--help"]`. Fresh `test_container.py`: 20 passed. |

## Required checks

### 1. Checkbox state at audit start

- `- [x] N.` implementation rows: **24**.
- Unchecked `- [ ] N.` implementation rows: **0**.
- `F1`-`F4`: all four remain `- [ ]` (plan lines 376-382). F1 was not checked.

### 2. Structural grammar

Each of the 24 implementation rows contains all required fields (counted 24/24):
`What to do / Must NOT do`, `Closes`, `Parallelization`, `References`,
`Acceptance criteria`, `QA scenarios`, `Commit: Y | ...`, and an indented
`Recommended task executor category:`. Every QA block contains a happy path and a
failure path (plus cancellation/tamper where applicable).

### 3. Gaps, ideal states, and guardrails

- GAP-1 through GAP-10 are each closed by at least one implementation row; no gap
  is unclosed.
- IS-1 through IS-10 in `## Scope` each appear exactly once in the
  `## Success criteria` table.
- No Must-NOT-have feature leaked into `src/`, `Taskfile.yml`, `Dockerfile`, or
  `.github/`: no bootable/vendor image logic, adb/APK install, Android/data or
  obb writes, ROM/BIOS/art downloads, scraping, RetroArch cores, native macOS
  assembler, Windows imaging, unattended flashing, `--device`, `--yes`,
  compression, GPT/ext4, or `shell=True`.

### 4. Headers

Order is exactly: `## TL;DR (For humans)` (first `##`), `## Scope`,
`## Verification strategy`, `## Execution strategy`, `## Todos`,
`## Final verification wave`, `## Commit strategy`, `## Success criteria`.

### 5. Shipped behavior (fresh commands at final HEAD)

| Command / check | Result |
| --- | --- |
| `uv run pytest -m "not integration" -q --cov=sbc_imager --cov-fail-under=85` | **518 passed, 1 skipped, 3 deselected; 92.99% coverage** |
| Privileged Linux `pytest -m integration -q` in a fresh `python:3.12-slim` container | **3 passed, 519 deselected** |
| `task lint` (ruff check, ruff format --check, pyright) | **Pass** |
| `uv run pre-commit run --all-files` | **All 4 hooks pass** |
| `git diff --check main..HEAD` | **Exit 0** |
| `uv run sbc-imager --version` / `--help` | **0.1.0** / all six commands present |
| `uv run sbc-imager platforms --json` | **51 tags** |
| `uv run sbc-imager image --help` | only `--image`, `--dry-run`; no `--device`/`--yes` |
| `uv run sbc-imager plan --manifest examples/imager.toml --json` | exit 0, pure JSON, 8 entries, `warnings` key present |
| `render_markdown() == docs/cannoli-platform-tags.md` | **True** |
| `uv build` + wheel inspection | sdist/wheel built; wheel contains `sbc_imager/cli.py`, `sbc_imager/py.typed`, and `sbc-imager = sbc_imager.cli:app` |
| `docker build -t sbc-imager-assembler:f1-audit .` | **Exit 0**, pinned apt versions installed |
| `docker run --rm --privileged --network none ... --preflight` | **Exit 0**, loop/mkfs.exfat/fsck.exfat/exfat available |
| AGENTS.md vs `main` | Prefix through `# END Global Rules` byte-identical; 99 additions, 0 deletions; `# END Global Rules` retained |
| All named task test modules (rows 1-24) | present |

All 24 rows still describe the shipped behavior; no prose-only claim was accepted
where the plan requires a command or artifact, and the four corrective commits
were re-verified rather than taken on report.

### 6. Git state and hardening commits

`git log 98919d3..HEAD` contains exactly the six hardening commits plus the final
notes commit, in order:

```text
f9341ed fix(container): pin assembler apt packages
efae552 fix(sources): surface branch-ref warnings
520c5a2 fix(config): reject symlinked local roots
fb580cd docs: regenerate cannoli tags without trailing whitespace
c6ba1d4 chore(cannoli): mark platform table SIZE_OK
14c49da fix(imaging): recheck target disk classification
13b6751 docs(agents): record final hardening invariants
```

- Worktree status: `## feat/sbc-imager-wave-3` with no short entries (clean).
- Main checkout status: `## main...origin/main` with no short entries (clean).
- Main was not modified and is an ancestor of HEAD.
- `feat/sbc-imager` remains at `98919d3`; the final hardening lives on
  `feat/sbc-imager-wave-3` as requested.

## Non-blocking residuals (pre-existing, unchanged by this re-audit)

- `Taskfile.yml:8` uses `pre-commit install --allow-missing-config` while plan line
  165 says `pre-commit install`. Setup still installs hooks; prior F1 classified
  this as non-blocking.
- Plan rows 16 and 17 name `.json` evidence files; the delivered files are
  `task-16-sbc-android-card-imager.log` and `task-17-sbc-android-card-imager.log`.
  The evidence exists and includes the JSON QA artifacts under `task-16-qa/`;
  prior F1 classified this as a naming mismatch, not missing evidence.

## Evidence

This report: `/Users/bball/projects/sbc-android-card-imager/.omo/evidence/F1-final-sbc-android-card-imager.md`

Prior report preserved: `/Users/bball/projects/sbc-android-card-imager/.omo/evidence/F1-sbc-android-card-imager.md`
