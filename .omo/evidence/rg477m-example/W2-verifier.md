# Wave 2 Verifier Report — RG477M Example (todos 4–6)

**Verdict: APPROVE**

No blockers. Wave 2 is independently verified against the plan. Read-only verification; the only file written is this report.

- Worktree: `/Users/bball/projects/sbc-android-card-imager-wt/rg477m-example`
- Branch: `feat/rg477m-example`
- HEAD: `0a423012e8d6b9efd7757b7f24e723b2413d97c2` (matches expected)
- Wave 1 base: `4e8ecef7f707ae0ad42b19151563839ef4331e92` (matches expected `4e8ecef`)
- `main` remains untouched by these commits; no push/PR/merge/amend.

## 1. Git state, commits, footers

`git status --short --branch`:

```
## feat/rg477m-example
```

Working tree clean (no untracked/modified files). Branch has no upstream configured (`git rev-parse @{u}` exits 128), so no push occurred. `git log --merges 4e8ecef..HEAD` is empty. Reflog shows three plain `commit:` entries, no `commit (amend)`.

`git log --oneline -8`:

```
0a42301 test(examples): prove the RG477M manifest and imports
bdf7a1c docs(examples): document the RG477M image and imports
f75975b feat(examples): add RG477M manifest and Tailscale import
4e8ecef docs(manifest): document single-file artifact sources
68df276 feat(manifest): plan single-file artifact sources
6710495 feat(manifest): allow single-file artifact sources
0563975 fix(github): keep tokens off asset downloads
d474576 docs(github): document pinned GitHub APK sources
```

Wave 2 commits and footers (each ends with the required footer):

```
f75975bebfa6bda919cf72fc5478eb33dd0f652a
feat(examples): add RG477M manifest and Tailscale import
Co-authored-by: DeepSeek - Flash <deepseek@deepseek.com>

bdf7a1cd22d8b31cd9c7bb771da48aed83d1996c
docs(examples): document the RG477M image and imports
Co-authored-by: DeepSeek - Flash <deepseek@deepseek.com>

0a423012e8d6b9efd7757b7f24e723b2413d97c2
test(examples): prove the RG477M manifest and imports
Co-authored-by: DeepSeek - Flash <deepseek@deepseek.com>
```

Commit contents are scoped correctly:

```
f75975b examples/rg477m/obtainium-tailscale.json, examples/rg477m/rg477m.toml
bdf7a1c AGENTS.md, README.md, examples/rg477m/README.md
0a42301 tests/unit/test_examples.py
```

`git log --name-only 4e8ecef..HEAD -- .omo` is empty. No `.omo/plans`, Boulder state, or Wave 3 changes are committed.

`git diff --check main..HEAD` exits 0 (no whitespace errors).

## 2. `examples/rg477m/rg477m.toml`

Verified by inspection:

- `[image]`: `name = "rg477m"`, `label = "CANNOLI"`, `size = "auto"`, `reserve = "8GiB"`, `output = "dist/rg477m.img"`.
- `[[source]] id = "obtainium"`: `type = "github"`, repo `ImranR98/Obtainium`, tag `v1.7.1`, asset `app-arm64-v8a-release.apk`.
- `[[source]] id = "emulation-pack"`: `type = "github"`, repo `RJNY/Obtainium-Emulation-Pack`, tag `v8.0.1`, asset `obtainium-emulation-pack-v8.0.1.json`.
- `[[apk]] source = "obtainium" as = "Obtainium.apk"` → `APKs/Obtainium.apk`.
- `[[artifact]] root = "card" dest = "Obtainium" source = "emulation-pack" as = "obtainium-emulation-pack-v8.0.1.json"` → `Obtainium/obtainium-emulation-pack-v8.0.1.json`.
- `[[artifact]] root = "card" dest = "Obtainium" path = "obtainium-tailscale.json" as = "tailscale.json"` → `Obtainium/tailscale.json`.
- Platform mapping comments present for GB, GBC, GBA, GG, NGPC, NES, SNES, MD, PS, N64, plus a note that the full skeleton is automatic.
- `grep -nE '^\[\[(rom|bios|art)\]\]'` → `no-rom-bios-art-entries`.
- No mutable release selector: manifest has no `release`/`latest` key; `latest` appears only in descriptive comments and the Tailscale local-file comment.

## 3. `examples/rg477m/obtainium-tailscale.json`

- `wc -c` → `383` bytes.
- File ends with a trailing newline (`... 6c0a 7d0a` = `l\n}\n`).
- `uv run python -m json.tool examples/rg477m/obtainium-tailscale.json` exits 0.
- Shape: one `apps` entry with `id="com.tailscale.ipn"`, `url="https://github.com/tailscale/tailscale-android"`, `author="tailscale"`, `name="Tailscale"`; `additionalSettings` is a nested JSON string with `includePrereleases=false`, `fallbackToOlderReleases=true`, `verifyLatestTag=false`, `sortMethodChoice="date"`, `autoApkFilterByArch=true`; top-level `settings` is `null`.
- It is deliberately pretty-printed (2-space JSON indentation) rather than the compact one-line form; 383 bytes is the pretty-printed size including the trailing newline, which is what the smoke build's `content_bytes` uses.

## 4. `examples/rg477m/README.md`

Verified by inspection:

- Device: Dimensity 8300, Android 14, `arm64-v8a`.
- Obtainium pin: `v1.7.1`, `app-arm64-v8a-release.apk`, 27,194,505 bytes, SHA `04dfd02c56dae8d5271d2d402977e1b07c8eeffb313df054a13e71b75b8b8a26`, GPL-3.0.
- Pack pin: `v8.0.1`, `obtainium-emulation-pack-v8.0.1.json`, 78,201 bytes, SHA `c2170687b07881f5891fe9751903c13c31b80de506bd41b718f99abb45592169`, Unlicense.
- Tailscale note: tracks `tailscale/tailscale-android`, latest release rather than a pin, package `com.tailscale.ipn`, universal APK. Independently checked GitHub's current latest release: `1.104.1-t7f4efe814-g6d75bd403` with `tailscale-android-universal-1.104.1.apk` — matches the README.
- Platform table covers all 10 requested platforms (GB→GB, GBC→GBC, GBA→GBA, Game Gear→GG, NGPC→NGPC, NES→NES, SNES→SNES, Genesis→MD, PS1→PS, N64→N64).
- Skeleton note states all top-level dirs, all 51 Roms tags, all 68 required dirs, `settings.json = {}`, and generated `CREDITS.md`.
- Build/plan/verify commands use the actual example paths; `--size` full-card override is documented separately from `size = "auto"`; auto size is stated as ≈8.09 GiB with the 1 MiB offset/64 MiB overhead/8 GiB reserve math.
- Import steps cover installing Obtainium, then importing both `Obtainium/obtainium-emulation-pack-v8.0.1.json` and `Obtainium/tailscale.json`.
- States there are no `[[rom]]`, `[[bios]]`, or `[[art]]` entries and no such payloads; states the Tailscale APK is not embedded.
- Relative links `rg477m.toml` and `obtainium-tailscale.json` both resolve to existing files. Root `README.md` pointer `[examples/rg477m/](examples/rg477m/)` exists and resolves (line 153).

## 5. Root `README.md` and `AGENTS.md`

- Root `README.md` points to the complete RG477M example at line 153.
- `AGENTS.md` single-file artifact clarification is present (lines 107–112): generic artifacts may use `source` with `as`, `as` is required, `path` cannot also be set, and the source must resolve to exactly one file.

## 6. `tests/unit/test_examples.py`

Verified by inspection:

- No network calls; all data comes from local files or `tmp_path`.
- Loads `examples/rg477m/rg477m.toml` via `load_manifest`, asserts `validate_manifest(...) == []`, and checks image/source/artifact fields.
- Asserts `iter_destinations()` and `build_plan()` produce exactly 3 destinations in the expected order.
- Validates the Tailscale JSON: trailing newline, exactly 383 bytes, one app, `com.tailscale.ipn`, URL, author, name, parsed `additionalSettings` dict, `settings is None`.
- Asserts 51 Roms tag dirs and 68 `required_dirs()` entries, including all 10 requested tags.
- Checks CREDITS contains Obtainium GPL-3.0, pack Unlicense, and both repo names.
- Failure test rejects a tampered manifest containing `[[rom]]`.

## 7. Command gates (from the worktree)

`uv run pytest -m "not integration" -q`:

```
589 passed, 1 skipped, 3 deselected in 4.72s
```

Coverage gate `uv run pytest -m "not integration" -q --cov=sbc_imager --cov-report=term-missing --cov-fail-under=85`:

```
Required test coverage of 85% reached. Total coverage: 92.65%
589 passed, 1 skipped, 3 deselected in 5.55s
```

`task lint` (exit 0):

```
ruff check: All checks passed!
ruff format --check: 77 files already formatted
pyright: 0 errors, 0 warnings, 0 informations
```

`uv run pre-commit run --all-files` (exit 0):

```
ruff check...............................................................Passed
ruff format..............................................................Passed
pyright..................................................................Passed
pytest-unit..............................................................Passed
```

`git diff --check main..HEAD` exits 0.

`uv run python -m json.tool examples/rg477m/obtainium-tailscale.json` exits 0.

## 8. Plan online/offline

`GITHUB_TOKEN` was absent; no token was logged or used in output. Warm cache was used.

`uv run sbc-imager plan --manifest examples/rg477m/rg477m.toml` → exit 0:

```
APKs/Obtainium.apk                             apk      25.935MiB
Obtainium/obtainium-emulation-pack-v8.0.1.json artifact 76.368KiB
Obtainium/tailscale.json                       artifact 383B
Content: 26.01MiB  Overhead: 64MiB  Reserve: 8GiB
Partition: 8.089GiB at offset 1MiB  Image: 8.09GiB
```

`uv run sbc-imager plan --manifest examples/rg477m/rg477m.toml --offline` → exit 0 with identical output.

Cached source integrity independently re-hashed:

- Obtainium APK: 27,194,505 bytes, SHA-256 `04dfd02c56dae8d5271d2d402977e1b07c8eeffb313df054a13e71b75b8b8a26`, license GPL-3.0.
- Pack JSON: 78,201 bytes, SHA-256 `c2170687b07881f5891fe9751903c13c31b80de506bd41b718f99abb45592169`, license Unlicense.

## 9. Bounded smoke build + verify (256 MiB)

Build (`--offline --json`) exit 0:

```
content_files=3
content_bytes=27273089
verify.ok=true
expected_files=5
actual_files=5
missing=[]
extra=[]
mismatched=[]
missing_dirs=[]
image_bytes=268435456
```

Verify (`--json`) exit 0:

```
{"ok": true, "expected_files": 5, "actual_files": 5, "missing": [], "extra": [], "mismatched": [], "missing_dirs": []}
```

Independent read-only image inspection (attached the raw image with `hdiutil attach -readonly -nobrowse`, then detached and deleted the temp image):

- Image files: `APKs/Obtainium.apk`, `Cannoli/Config/settings.json`, `CREDITS.md`, `Obtainium/obtainium-emulation-pack-v8.0.1.json`, `Obtainium/tailscale.json` (5 files).
- `Cannoli/Roms` child directories: 51.
- `required_dirs()` count: 68; all 68 present in the image (`missing_required_dirs=[]`).
- `Cannoli/Config/settings.json` content: `{}` (plus newline).
- `CREDITS.md` contains Obtainium `GPL-3.0` and pack `Unlicense`, with the pinned SHA-256 values and release URLs.

No real disk was written; only a temp image under `/var/folders/.../T/opencode/` was created and removed.

## 10. Scope compliance

- No `.omo/plans`, Boulder, or Wave 3 files appear in `4e8ecef..HEAD`.
- No push (no upstream), no merge commits, no amend in reflog.
- Plan checkboxes were not modified.
- Source, tests, docs, plan, and git state were not edited during verification.

## Evidence path

`/Users/bball/projects/sbc-android-card-imager/.omo/evidence/rg477m-example/W2-verifier.md`

**Final verdict: APPROVE**
