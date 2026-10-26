# Wave 1 independent verification (plan todos 1-3)

**Verdict: APPROVE**

- Date: 2026-10-19
- Verifier: opencode / deepseek-flash
- Mode: read-only. No source, test, docs, plan, or git changes were made. Only this report was written.
- Worktree: `/Users/bball/projects/sbc-android-card-imager-wt/rg477m-example`
- Branch: `feat/rg477m-example`
- Base: `0563975` (`git merge-base HEAD 0563975` == `0563975`; `HEAD~3` == `0563975`)
- HEAD: `4e8ecef` (`4e8ecef7f707ae0ad42b19151563839ef4331e92`)
- Working tree: clean (`git status --short --branch` -> only `## feat/rg477m-example`; porcelain count 0, also rechecked after pre-commit)

## Gate results

| # | Command | Result |
| --- | --- | --- |
| 1 | `git status --short --branch` | clean, branch only |
| 1 | `git log --oneline -5` | `4e8ecef`, `68df276`, `6710495`, `0563975`, `d474576` |
| 2 | `uv run pytest -m "not integration" -q` | **581 passed, 1 skipped, 3 deselected** in 4.19s |
| 3 | `uv run pytest -m "not integration" -q --cov=sbc_imager --cov-report=term-missing --cov-fail-under=85` | **581 passed, 1 skipped, 3 deselected**; **92.65%** total (required 85%) |
| 4 | `task lint` | ruff check passed; ruff format `75 files already formatted`; pyright `0 errors, 0 warnings, 0 informations` |
| 4 | `uv run pre-commit run --all-files` | all 4 hooks Passed (ruff check, ruff format, pyright, pytest-unit); exit 0 |
| 5 | `git diff --check main..HEAD` | exit 0, no whitespace errors |
| 7 | `uv run pytest tests/unit/test_docs.py -q` | **10 passed** in 0.66s |

The one skip is the expected platform-dependent sparse-file test:
`tests/unit/test_fs.py:156: filesystem does not report sparse holes`.

## Commit audit

Exactly the three expected commits sit on `0563975`, with no Wave 2 or plan/Boulder content:

```
4e8ecef docs(manifest): document single-file artifact sources
68df276 feat(manifest): plan single-file artifact sources
6710495 feat(manifest): allow single-file artifact sources
```

All three have the required co-author footer:

```
Co-authored-by: DeepSeek - Flash <deepseek@deepseek.com>
```

Per-commit scope matches the plan:

- `6710495`: `config.py`, `validation_checks.py`, `validation_destinations.py` plus config/validation unit tests.
- `68df276`: `planner.py`, `cli.py`, `verify.py` plus planner/CLI/verify unit tests.
- `4e8ecef`: `docs/manifest.md`, `AGENTS.md`, `README.md` only.

`git diff --name-only 0563975..HEAD` contains no `.omo/`, `.boulder`, or `.opencode` paths.
`git ls-tree -r --name-only HEAD | grep '^examples/rg477m/'` -> no matches.
No `examples/rg477m` pointer exists in `README.md`, `AGENTS.md`, or `docs/`, matching todo 3's instruction to defer it.

## Source inspection

All required behavior is present and matches the todo text:

1. **`src/sbc_imager/config.py`**
   - `_KEYS["artifact"]` includes `source`.
   - `ArtifactEntry` (`config.py:103`) has `path: Path | None`, `source: str | None`, `as_: str | None`.
   - `_artifact()` (`config.py:307`) with `source`:
     - rejects `path` with `artifact[N] cannot set both 'path' and 'source' in manifest ...`;
     - requires `as` via `_required_text` and rejects an empty `as`;
     - stores `path=None`.
   - Local artifacts keep `_local_path(...)` behavior and `path` required.

2. **`src/sbc_imager/validation_checks.py`**
   - `check_artifacts()` (`:112`) validates `root`, `dest`, and the `Config/` warning **before** branching, then for `source` validates `as` and returns 0 bytes without touching the local filesystem.
   - Local `path is None` guard emits `missing-path`.
   - `check_sources()` (`:139`) includes `("artifact", manifest.artifacts)` in referenced-source collection, so referenced artifact sources do not produce `unused-source` and unknown ones produce `unknown-source`.

3. **`src/sbc_imager/validation_destinations.py`**
   - `_artifact_destinations()` (`:130`) source branch yields `<base>/<as>` where base is `<dest>` for `card` and `Cannoli/<dest>` for `cannoli`; `src` and `source_root` stay `None`; no filesystem access.
   - Local `path is None` guard emits `missing-path`.

4. **`src/sbc_imager/planner.py`**
   - `_expand()` (`:161`) has an explicit artifact branch before the overlay/shader fallthrough.
   - Missing resolution -> `missing-source-resolution: artifact[N] references source '...'`.
   - Non-file root -> `artifact-source-directory: artifact[N] source '...' must resolve to a single file`.
   - File root -> one `PlannedEntry` with real size and `source_id`.
   - `content_bytes = sum(entry.size for entry in entries)` (`:353`) therefore includes artifact source bytes.

5. **`src/sbc_imager/cli.py:96` and `src/sbc_imager/verify.py:92`**
   - Both referenced-source tuples include `*manifest.artifacts`, so `plan`/`build` reference resolution and `verify` source resolution cover artifact sources.

## Failure probes (independent of worker counts)

A direct probe using the real parser/validator/planner produced:

```
source+path:       ConfigError -> artifact[0] cannot set both 'path' and 'source' in manifest ...
source without as: ConfigError -> artifact[0] is missing required key 'as' in manifest ...
unknown source:    ConfigError -> unknown-source: artifact[0] references unknown source 'nope'
invalid as:        ConfigError -> invalid-as: artifact[0] 'as' must be a single relative filename: 'nested/p.json'
invalid dest:      ConfigError -> invalid-dest: artifact[0] destination must stay inside the card: '../escape'
happy parse:       path=None, source=pack, as_=p.json, root=cannoli, dest=Config
happy dest:        Cannoli/Config/p.json, kind=artifact, src=None, source_root=None
config warning:    [('artifact-config', 'artifact[0] writes into Config/')]
local path None:   missing-path from both validate_manifest and iter_destinations
planner file:      Cannoli/Config/p.json, kind=artifact, size=2, source_id=pack, content_bytes=2
planner directory: artifact-source-directory: artifact[0] source 'pack' must resolve to a single file
planner missing:   missing-source-resolution: artifact[0] references source 'pack'
```

The unit-test assertions were inspected, not just the pass count:

- `tests/unit/test_config.py`: asserts `path is None`, `source`, `as_`, plus `path`+`source` and missing-`as` failures.
- `tests/unit/test_validation.py`: asserts no `unused-source` warning, `unknown-source` includes `artifact[0]` and the id, `invalid-as`, `invalid-dest`, both root destinations with `src is None`/`source_root is None`, and `artifact-config` warning.
- `tests/unit/test_planner.py`: asserts destination/kind/src/size/source_id/content_bytes, `artifact-source-directory`, and `missing-source-resolution`.
- `tests/unit/test_cli_plan.py`: monkeypatches `resolve_github`, asserts exit 0, artifact destination/kind/source, and only the referenced source resolved.
- `tests/unit/test_verify.py`: asserts artifact source resolution and `Obtainium/pack.json` in `build_expected(...).files`.

## Docs audit

- `docs/manifest.md`: path-resolution, `[[source]]` scope, `[[artifact]]` key table, validation rules, and the new `<!-- valid-manifest -->` GitHub artifact example all describe the implemented behavior: no `path` with `source`, `as` required, single-file only, `<root>/<dest>/<as>`, directory root is an error, and `Config/` warning applies to both forms.
- The stale "`source` on an artifact entry is an unknown key" rule is gone. No `docs/`, `README.md`, or `AGENTS.md` text claims artifact `source` is unknown.
- The new valid-manifest block is one of 7 blocks; all 7 parse through `load_manifest`.
- `README.md` limitation text now lists single-file `[[apk]]`/`[[artifact]]` remote sources and still preserves the RomM-supplied sentence.
- `AGENTS.md` now says artifacts may reference a `source` id.
- `tests/unit/test_docs.py`: 10 passed, including the valid-TOML and relative-link checks.

## Wave 2 / plan isolation

- `examples/rg477m/*`: absent from HEAD.
- No `.omo/plans/*`, `.boulder`, or `.opencode` changes in any Wave 1 commit.
- Plan checkboxes were not modified.

## Non-blocking observation

`AGENTS.md` line 99 adds artifacts to the "may reference a `source` id" sentence but does not explicitly restate the todo-3 wording "single-file artifacts and the source+as restriction"; the detailed restriction lives in `docs/manifest.md` and the APK-specific sentence still covers only APKs. This is accurate as written and does not affect any todo-3 acceptance criterion or Wave 1 gate, so it is not a blocker. A one-line AGENTS clarification would improve future agent context.

## Evidence path

`/Users/bball/projects/sbc-android-card-imager/.omo/evidence/rg477m-example/W1-verifier.md`
