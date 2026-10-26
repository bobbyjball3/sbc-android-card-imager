# F4 Ideal-State Fidelity Audit — RG477M Example

**Verdict: APPROVE**

- Date: 2026-10-19
- Auditor: opencode / deepseek-flash
- Mode: read-only against source/tests/docs/plan/git; only this report was written.
- Worktree: `/Users/bball/projects/sbc-android-card-imager-wt/rg477m-example`
- Branch: `feat/rg477m-example`
- HEAD: `0a423012e8d6b9efd7757b7f24e723b2413d97c2`
- Working tree: clean (`## feat/rg477m-example`)
- Plan: `/Users/bball/projects/sbc-android-card-imager/.omo/plans/rg477m-example.md`, `IS-1..IS-10`

No new `- [ ] N.` follow-up rows are required. Every ideal-state row has a proving artifact.

## Per-IS results

| IS | Result | Proving artifact | Basis |
| --- | --- | --- | --- |
| IS-1 | **PASS** | `task-04-rg477m-manifest.txt`, `task-06-rg477m-proof/tree.json`, F4 independent build/image inspection | `examples/rg477m/rg477m.toml` pins `ImranR98/Obtainium` tag `v1.7.1`, asset `app-arm64-v8a-release.apk`. Cached APK is 27,194,505 bytes, SHA-256 `04dfd02c...8a26`, and contains `lib/arm64-v8a/*.so`. The independent 256 MiB build contains `APKs/Obtainium.apk` at the same size/SHA. |
| IS-2 | **PASS** | `task-04-rg477m-manifest.txt` (cache `source.json` + plan), `task-06-rg477m-proof/tree.json`, F4 image inspection | Source pins `RJNY/Obtainium-Emulation-Pack` tag `v8.0.1`, asset `obtainium-emulation-pack-v8.0.1.json`; cache provenance is release `v8.0.1`, 78,201 bytes, SHA-256 `c2170687...2169`. Image contains `Obtainium/obtainium-emulation-pack-v8.0.1.json` with that SHA. |
| IS-3 | **PASS** | `task-04-rg477m-manifest.txt`, `task-06-rg477m-proof/tree.json`, F4 image inspection | Local `examples/rg477m/obtainium-tailscale.json` is declared as the local artifact and lands at `Obtainium/tailscale.json` (383 bytes) in the image. |
| IS-4 | **PASS** | `task-06-rg477m-proof/tree.dirs.json`, `skeleton-and-credits.txt`, `image-settings-credits.txt`, F4 image inspection | Independently mounted image: 68 required dirs present with `missing_dirs=[]`, 51 `Cannoli/Roms/<TAG>` dirs, all top-level Cannoli dirs (`Art`, `BIOS`, `Cheats`, `Config`, `Guides`, `Media`, `Overlays`, `Roms`, `Save States`, `Saves`, `Shaders`, `Wallpapers` plus retained `Backup`/`Logs`), `Cannoli/Config/settings.json` is `{}`, and `CREDITS.md` exists. Actual dirs = 70 (68 required + `APKs` + `Obtainium`), as expected. |
| IS-5 | **PASS** | `task-05-rg477m-readme.txt`, `task-06-rg477m-proof/skeleton-and-credits.txt`, F4 image inspection | README maps all ten platforms (GB, GBC, GBA, GG, NGPC, NES, SNES, MD, PS, N64). The image's 51 Roms tags include every requested tag. |
| IS-6 | **PASS** | `W1-verifier.md`, `task-01-*`, `task-02-*`, F4 direct probes | Direct probes reproduced: source+path -> `ConfigError` naming both; source without `as` -> missing-`as` error; unknown source -> `unknown-source`; directory root -> `artifact-source-directory`; missing resolution -> `missing-source-resolution`; single-file happy path plans `Obtainium/p.json` with real size and source id. Parser stores `path=None`; destination is `<root>/<dest>/<as>`. |
| IS-7 | **PASS** | `task-04-rg477m-manifest.txt` (online vs offline plans), `task-06-rg477m-proof/task-06-proof.log`, F4 independent offline build/verify | Online and `--offline` plans produce identical entries/sizes. F4 ran `build --offline --size 256MiB` after cache warm: exit 0, `content_files=3`, `content_bytes=27273089`, `verify.ok=true`, `actual_files=5`; subsequent `verify` exit 0. |
| IS-8 | **PASS** | `examples/rg477m/rg477m.toml`, `task-04-rg477m-manifest.txt`, `task-06-rg477m-proof/tree.json`, F4 image inspection | No `[[rom]]`, `[[bios]]`, or `[[art]]` tables exist. The example directory tracks only the manifest, README, and Tailscale JSON. Image contains exactly 5 files, no ROM/BIOS/art payload files; `Cannoli/Art` and `Cannoli/BIOS` are empty skeleton dirs only. |
| IS-9 | **PASS** | `task-05-rg477m-readme.txt`, `examples/rg477m/README.md`, root `README.md:153` | README documents both pins (tag, asset, size, SHA, license), device/ABI, platform mapping table, skeleton, build/plan/verify commands, card-size choice/`--size`, and both Obtainium import steps. Relative links resolve; root README points to `examples/rg477m/`. |
| IS-10 | **PASS** | `task-04-rg477m-manifest.txt`, `tests/unit/test_examples.py`, F4 source check of Obtainium | JSON is valid (`json.tool` exit 0), 383 bytes with trailing newline, one app with `id=com.tailscale.ipn`, GitHub URL, `author`, `name`, string `additionalSettings` decoding to the required five settings, and `settings: null`. Checked against current Obtainium `App.fromJson`/`appFromStoredJson`: legacy `{apps, settings}` import is accepted; `id/url/author/name` and string `additionalSettings` are the required fields, with defaults supplied for omitted optional fields. |

## Independent spot checks run for F4

| Check | Result |
| --- | --- |
| `git status --short --branch` | clean, `## feat/rg477m-example` |
| `git diff --check main..HEAD` | exit 0 |
| Targeted tests (`test_examples`, config, validation, planner, CLI plan, verify, docs) | `195 passed` |
| `sbc-imager plan --offline --json` | exit 0; 3 entries, `content_bytes=27273089`, no warnings |
| Cached APK/pack SHA-256 | exactly match the pinned values; APK contains `lib/arm64-v8a` |
| Tailscale JSON parse/shape | 383 bytes, trailing newline, required fields present, `settings is None` |
| Offline 256 MiB build + verify | build exit 0; `content_files=3`, `content_bytes=27273089`, `verify.ok=true`, 5/5 files; verify exit 0 |
| Read-only image mount | 5 files, 51 Roms tags, 68 required dirs with none missing, `settings.json={}`, CREDITS has Obtainium GPL-3.0 and pack Unlicense, no payload files |
| Forbidden manifest tables | none |
| README pin/platform/import tokens | all present |
| Temp image cleanup | removed; worktree still clean |

## Blockers / follow-ups

**None.** No IS row fails, and no new follow-up row is warranted.

Non-blocking observations (do not affect the verdict):

- `F3-manual-qa.log` is not present yet. Per the audit brief this F4 pass used Wave 1/Wave 2 evidence plus the independent offline build, verify, and image inspection above, so F3 is not required to prove the ideal state here.
- `tests/unit/test_examples.py` uses small fake source files for planning assertions while independently asserting the real pinned sizes/SHAs from the cache/image evidence; this is test isolation, not a fidelity gap.

## Evidence paths

- Wave 1: `/Users/bball/projects/sbc-android-card-imager/.omo/evidence/rg477m-example/W1-verifier.md`
- Wave 2: `/Users/bball/projects/sbc-android-card-imager/.omo/evidence/rg477m-example/W2-verifier.md`
- Task 01-05: `/Users/bball/projects/sbc-android-card-imager/.omo/evidence/rg477m-example/task-0*.txt`
- Build/verify proof: `/Users/bball/projects/sbc-android-card-imager/.omo/evidence/rg477m-example/task-06-rg477m-proof/`
- This report: `/Users/bball/projects/sbc-android-card-imager/.omo/evidence/rg477m-example/F4-ideal-state.md`
