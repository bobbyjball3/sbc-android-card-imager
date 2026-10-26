# progress-reporting evidence

**Status:** implemented and verified
**Date:** 2026-10-19
**Worktree:** `/Users/bball/projects/sbc-android-card-imager-wt/rg477m-example`
**Branch:** `feat/progress-reporting`
**Base:** `92ae713`
**HEAD:** `8997de7` (`docs: document build progress output`)

## Commits

- `10829b4` `feat(progress): report build and assembler phases`
- `8997de7` `docs: document build progress output`

Both include `Co-authored-by: DeepSeek - Flash <deepseek@deepseek.com>`.

## Implemented

- New `src/sbc_imager/progress.py` shared reporter:
  - `ProgressEvent`
  - `TextReporter` (phase/count/elapsed lines)
  - `JsonReporter` (newline-delimited JSON)
  - `NullReporter`
  - `make_reporter(auto|human|json|none)`
  - `SBC_PROGRESS` encode/parse for container-to-host events
- `build` supports `--progress auto|human|json|none` (default `auto`).
  - `auto`: human on a TTY, off otherwise.
  - `json`: stderr is pure JSONL with `event: progress` or `event: log`.
  - `--json` stdout remains the report only.
- Host build phases: load, resolve, stage, container, assemble, verify-image, publish-output.
- Assembler phases: prepare, format, copy counts, fsck, verify counts, publish.
- `populate()` and `verify()` accept count callbacks.
- Normal build logs are wrapped as `event: log` in JSON progress mode.

## Verification

- `uv run pytest -m "not integration" -q`: **659 passed, 1 skipped, 3 deselected**
- Coverage: **92.67%**, `--cov-fail-under=85` passed
- `task lint`: ruff, format, pyright all passed
- `uv run pre-commit run --all-files`: all hooks passed
- `git diff --check main..HEAD`: exit 0
- Docker assembler image rebuilt during QA.
- Demo build with `--progress human`: exit 0; phases observed from load through publish-output.
- Demo build with `--progress json`: exit 0; 46 stderr lines, 41 `progress` + 5 `log` events, every line valid JSON.

## Evidence files

- `pytest.log`
- `coverage.log`
- `lint.log`
- `precommit.log`
- `diff-check.log`
- `git-state.log`
- `human.stdout.log`, `human.stderr.log`
- `json.stdout.log`, `json.stderr.log`

## Residual risks

- This first slice instruments `build`/assembler only. `fetch`, `plan`, and `verify` are not yet using the shared reporter; `image` already has its own byte/speed progress bar.
- `auto` suppresses progress when stderr is not a TTY.
- Long phases without a known total show a start line and final elapsed time, not a live spinner or heartbeat.
- The assembler image must be rebuilt after assembler progress changes to emit the new in-container events.
- A full 512 GB build was not exercised; the demo build and unit tests prove the plumbing.
- No push or merge was performed.
