# F4 - Ideal-state fidelity

**Verdict: APPROVE**

- Plan: `/Users/bball/projects/sbc-android-card-imager/.omo/plans/sbc-android-card-imager.md`
- Worktree: `/Users/bball/projects/sbc-android-card-imager-wt/sbc-android-card-imager-wave-3`
- Branch: `feat/sbc-imager-wave-3`
- HEAD: `98919d335dc90fc656101f9b3add1d0b47dfd4fa`
- Date: 2026-10-19
- Mode: read-only verification (evidence file only; no product edits, commits, or pushes)

## How the rows were verified

Each IS row was checked against delivered behavior on HEAD `98919d3`, not only the plan text. I read the implementation, inspected the worker QA artifacts, and re-ran the cheap host gates plus the real Linux integration suite on this HEAD. Evidence artifacts for earlier todos live in their per-wave worktrees because each wave worker wrote `.omo/evidence/` in its own worktree; the final wave-3 worktree contains tasks 19-21. This is evidence bookkeeping only; the behavior below was independently re-proven on the final branch.

## Targeted checks on HEAD `98919d3`

| Check | Result |
| --- | --- |
| `uv run pytest tests/unit -q` | **506 passed, 1 skipped** (the skip is the APFS sparse-hole assertion in `tests/unit/test_fs.py:156`) |
| `docker run --rm --privileged ... pytest -m integration -q` (current source, pinned assembler image) | **3 passed, 507 deselected** - real Linux `losetup`/`mount`/`mkfs.exfat`/`fsck.exfat` E2E |
| `task lint` | **PASS** - ruff check, ruff format --check, pyright (0 errors) |
| `uv run sbc-imager plan --manifest examples/imager.toml --json` | **PASS** - 8 planned files, content 830 bytes, auto image 70,254,592 bytes (67 MiB) |
| `from sbc_imager.cannoli import PLATFORM_TAGS` | **51 tags**; registry order matches the pinned Cannoli v1.9.1 list |
| `render_markdown() == docs/cannoli-platform-tags.md` | **True** |
| `uv run sbc-imager image --help` | Only `--image`, `--dry-run`, `--help`; **no `--device`, no `--yes`** |
| `uv run sbc-imager --version` | **0.1.0** |
| `git diff main -- AGENTS.md` | **91 insertions, 0 deletions**; `# END Global Rules` retained |
| Inspected `task-16-qa/out/qa.img` via the current assembler verifier | **verified 5 files**, including `Cannoli/Config/settings.json` (`{}\n`), `CREDITS.md`, `APKs/app.apk`, ROM and BIOS; its stage plan has **51** `Cannoli/Roms/<TAG>` dirs |
| `grep -RIn "RG477M\|Retroid\|Pocket Nova" src examples docs README.md AGENTS.md Taskfile.yml Dockerfile` | **no matches** - no device-specific code path |

## IS-1..IS-10 proof table

| IS | Delivered by | Proving QA artifact / test / command | Result |
| --- | --- | --- | --- |
| **IS-1** One CLI build produces a flashable sparse `.img` with the correct `Cannoli/` tree and every declared file at its path. | 3, 12, 14, 17, 18 | `task-18-sbc-android-card-imager.log` (wave-2): full example assembled, `verify` host comparison `ok=True`, all 8 declared files hashed, fsck clean. `task-17-sbc-android-card-imager.log`: live `sbc-imager build` produced `dist/card.img`, no `.partial`, `verify.ok=true`, report written. Re-ran integration on HEAD: 3 passed. Inspected `task-16-qa/out/qa.img` tree: declared files at exact destinations. | **PASS** |
| **IS-2** First launch preselects the card as an existing install and all 51 `Roms/<TAG>` folders exist, with the `Config/settings.json` `{}` marker. | 3, 12, 14, 18 | `task-18` log: `Roms dirs=51 expected=51`; `settings='{}\n'`; full tag list printed. Current HEAD: `build_plan` reports 51 `Cannoli/Roms/*` dirs and `Marker(path='Cannoli/Config/settings.json', content='{}\n')`. Inspected `qa.img` stage plan: 51 Roms dirs, marker present. | **PASS** |
| **IS-3** Local/git/HTTP sources use immutable pins and SHA-256 where applicable, a content-addressed cache, and `--offline`. | 9, 10, 11, 12, 17 | `task-10` (wave-1): tag and 40-hex commit resolve, branch rejected without `--allow-branch`, offline hit/miss, stale-cache behavior, credential redaction. `task-11` (wave-1): HTTP success, checksum mismatch, 404, redirect, offline hit/miss, malformed SHA, traversal filename. `task-12`: `fetch --offline` cache hit. `task-17`: `build --offline` cache miss names the cache key. Code: `sources_git.py:192`, `sources.py:177`. | **PASS** |
| **IS-4** Invalid manifests fail before image bytes, naming the entry/destination: unknown tag, case-insensitive collision, exFAT-invalid name, duplicate destination, symlink, missing file, oversize content. | 7, 8, 17 | `task-8` (w1-t8): one `ConfigError` per family, including `unknown-platform`, `exfat-name`, `symlink`, `destination-collision`, `duplicate-destination`, `missing-path`, `content-overflow`; `tests/unit/test_validation.py` 74 passed. `task-12`: collision/empty/pinned-overflow exit 2. `task-18` adversarial probes: missing file, missing directory, invalid TOML, duplicate destination, unknown key. `build.py:219-226` validates before resolve/stage/assemble. | **PASS** |
| **IS-5** Every built image is checked with `fsck.exfat -n`, a per-file SHA-256 tree comparison, and a summary report before flashing. | 14, 16, 17 | `task-16` (wave-2): `pass.json` `ok=true`, `fsck` clean, host compare; `tampered.json` reports `mismatched: ["Cannoli/Roms/GBA/demo.gba"]`; image SHA unchanged by verify. `task-18`: `fsck.exfat -n` clean (75 dirs, 10 files), all hashes match, tamper and extra-file probes fail. `build.py:243-266` verifies before `_publish` and writes `<output>.report.json`. Current HEAD integration: 3 passed. | **PASS** |
| **IS-6** Flashing lists only external removable whole disks, refuses internal/boot disks, shows details, requires the exact typed identifier, unmounts, writes with progress, syncs, ejects, supports `--dry-run`, and never writes `/dev/disk*`. | 19, 20, 21 | `task-19`: 0 safe disks on this Mac; external USB listed, internal/USB-slot/disk-image/boot fixtures rejected, missing keys fail closed. `task-20`: temp-file write SHA match, progress reaches 100%, dry-run writes 0 bytes, non-root/oversize/unmount failures exit 2, `/dev/disk*` and case variants refused, Ctrl-C partial-write warning. `task-21`: happy `ERASE disk9`; wrong/empty/`y` abort exit 2; no disks exit 2; dry-run never calls writer; help has no `--device`/`--yes`. Code: `imaging.py` filters, `imaging_write.py:85-91,144-188`, `cli_image.py:113-130`. | **PASS** |
| **IS-7** The build runs in a pinned Linux container; local Task targets mirror CI (Ubuntu real integration, macOS unit/CLI); `AGENTS.md` gains commands and conventions. | 4, 5, 23 | `task-4` and `task-5` (wave-0): `task --list` has all 11 targets, `task ci` passes, pre-commit passes, workflow calls Task/CLI, no Windows/secrets. `task-5`/current `.github/workflows/ci.yml`: ubuntu test job runs privileged integration and container preflight. `Dockerfile`: `python:3.12-slim-bookworm@sha256:34386ef...` pinned by digest. `task-23`: AGENTS diff 91 additive lines, 0 removed; prefix byte-identical; all 11 documented commands exist. Current HEAD `git diff main -- AGENTS.md`: 91/0. | **PASS** |
| **IS-8** All build logic has fast unit tests through an injected system-runner abstraction, plus a real end-to-end Linux image build. | 2, 4, 5, 14, 18 | `tests/fakes.py` `FakeRunner` and `runner.py` injection seam; current HEAD `uv run pytest tests/unit -q` = **506 passed, 1 skipped**. `tests/integration/test_build_e2e.py` and `test_assembler.py` drive real loop/mount/exFAT; current HEAD container run = **3 passed**. `task-18` also records 439 unit passes and the privileged E2E. | **PASS** |
| **IS-9** The same manifest and layout work unchanged for the RG477M and Retroid Pocket Nova; no device-specific code. | 3, 17, 18 | Static check on current HEAD: no `RG477M`, `Retroid`, or `Pocket Nova` references in `src`, `examples`, `docs`, `README.md`, `AGENTS.md`, `Taskfile.yml`, or `Dockerfile`. CLI has no device selector (`image --help` shows only `--image`/`--dry-run`). The single `examples/imager.toml` plans/builds the same Cannoli card layout; E2E task-18 validates that layout. The tool is device-agnostic by construction; there is no device parameter that could vary the build. | **PASS** |
| **IS-10** The repo ships a sample manifest, usage docs, a generated Cannoli tag reference, attribution/credits, and packaging proof. | 3, 22, 23, 24 | `examples/imager.toml` + `examples/demo/` placeholders. `task-22` (w3-t22): `tests/unit/test_docs.py` 10 passed, tag doc equality true, all documented links resolve, manifest examples parse, no zero-touch claim. `task-24` (w3-t24): wheel contains `sbc_imager/cli.py` and `py.typed`, entry point `sbc-imager = sbc_imager.cli:app`, isolated tool install prints 0.1.0. Current HEAD: `test_docs.py`/`test_packaging.py` pass; README has Credits and Attribution (Cannoli GPL-3.0, exfatprogs, RetroArch docs, Typer/Rich/uv/ruff/Task). | **PASS** |

## Git-state confirmation

| Item | Value | Result |
| --- | --- | --- |
| Wave-3 worktree status | `## feat/sbc-imager-wave-3`, no short entries | **clean** |
| Wave-3 HEAD | `98919d335dc90fc656101f9b3add1d0b47dfd4fa` | **98919d3** |
| `feat/sbc-imager` | `98919d335dc90fc656101f9b3add1d0b47dfd4fa` | **same commit** |
| Wave-3 vs `feat/sbc-imager` | `git diff --name-only feat/sbc-imager HEAD` empty; wave-3 is a descendant | **same tree** |
| `main` | `0fb6379f891bc0c1dd47f9998bb3173cc41a32eb` == `origin/main` | **untouched** |
| Main checkout status | `## main...origin/main`, no short entries | **clean** |
| `main` ancestry | `git merge-base --is-ancestor main feat/sbc-imager` | **yes** |

## Shortfall rows

None. All ten ideal-state rows are proven by the artifacts/tests above. No new `- [ ] N.` rows are proposed.
