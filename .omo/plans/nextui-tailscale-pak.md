# Plan: nextui-tailscale-pak

## TL;DR (decision-complete)
- **Goal:** Add Tailscale (ben16w/minui-tailscale 2.0.0) and Central Scrutinizer (Helaas/nextui-CentralScrutinizer-pak v0.3.0) to the TrimUI Brick/NextUI (tg5040) payload, and generalize `remote_archives` so any archive can declare `dest` (final directory) and optional `executables` to chmod. Keep Cannoli byte-for-byte unchanged. No host block-device writes, no secrets pre-seeded, no new container/Taskfile/CI deps.
- **Pinned assets (new):**
  - `ben16w/minui-tailscale` tag `2.0.0` asset `Tailscale.pak.zip` (72,816,569 B) sha256 `c4d202fb99f0ab156b17596ba42d26dafb9358a8ce91e7361e6f399f49cd8e20` → `Tools/tg5040/Tailscale.pak`, exec `launch.sh`
  - `Helaas/nextui-CentralScrutinizer-pak` tag `v0.3.0` asset `Central.Scrutinizer.pak.zip` (1,318,350 B) sha256 `e3b6f0028ca5d31dcb1ba638829359ecf179facf409cab76f0a0b08688d88ee5` → `Tools/tg5040/Central Scrutinizer.pak`, exec `launch.sh` and `central-scrutinizer`
- **Archive shape (upstream):** `Tailscale.pak.zip` root is FLAT (no `Tailscale.pak/` wrapper) despite README; macOS Archive Utility creates the folder on double-click but Linux `unzip` extracts flat. Build must `unzip -d Tools/tg5040/Tailscale.pak`. Central Scrutinizer zip root flat as well (extract into the named dir). Both are git-archived zips with `bin/`, `launch.sh` 0644, binaries 0755. 2.0.0 release artifact's `pak.json` is 1.3.0 due to build-before-bump (systemic off-by-one); pin by tag+sha256.
- **Tailscale behavior (evidence):** authkey required at SD root for first run, deleted after login; writes to `.userdata/<PLATFORM>/Tailscale/`, `.userdata/<PLATFORM>/logs/`, `.userdata/<PLATFORM>/auto.sh`; default tailscaled requires `/dev/net/tun` (no `--tun=userspace-networking`); uses default socket `/var/run/tailscale/tailscaled.sock` (inferred); DNS/route changes inherent. Repo MIT; bundled tailscale BSD-3-Clause with `tailscale.LICENSE` retained; jq `jq.LICENSE` present; minui-list/presenter license files not in zip (third-party). No `.pakz` recommendation upstream (manual extract to `Tools/<platform>/`).
- **CS behavior:** terminal/screen-timeout/pairing side effects unverified on hardware (document in README).
- **Constraints:** no host block-device writes, no secrets, no FAT32, no custom Ansible module, no vendored archives, no Cannoli changes, no `tg5050`/`my355`/`h700` scope creep.

## Scope / Non-scope
- **In scope:** `ansible/build.yml`, `ansible/tasks/payload-nextui.yml`, `ansible/vars/nextui.yml`, `ansible/vars/trimui-brick.yml`, `tests/ansible-payload-nextui.sh`, `docs/nextui-layout.md`, `examples/trimui-brick/README.md`, `README.md`, `AGENTS.md` (comments only as needed), evidence under `.omo/evidence/nextui-tailscale-pak/`
- **Out of scope:** `container/`, `Dockerfile`, `Taskfile.yml`, `.github/workflows/ci.yml`, `tests/smoke-image.sh`, Cannoli files, firmware/kernel, hardware boot verification, authkey provisioning, Headscale pairing

## Branch
Create `feat/nextui-tailscale-pak` from latest `main` before starting work.

## Tasks (implementation wave)
1. **[ansible] Generalize remote_archives + validation**
   - WHERE: `ansible/build.yml:88-177`, `ansible/tasks/payload-nextui.yml:1-85`, `ansible/vars/nextui.yml:1-20`, `ansible/vars/trimui-brick.yml:1-120`
   - HOW:
     - Remove Grout-specific assumptions: delete repo sentinels (`item.repo == 'rommapp/grout'`) and the hardcoded chmod block. Make dest a final extraction directory (use `{{ payload_dir }}/{{ item.dest }}` directly). Add `file` to ensure dest dirs exist.
     - Replace hardcoded Grout chmod with a single data-driven loop: collect entries with `executables` defined via `selectattr('executables','defined') | list | subelements('executables')` (handle empty list), chmod `{{ payload_dir }}/{{ item.0.dest }}/{{ item.1 }}` to `0755`. Keep profile-agnostic (no `when: payload_profile == 'nextui'` on the chmod loop).
     - Add a required-keys + invariant assert before the archive block: for every entry require `repo, tag, asset, sha256, dest`; `sha256` must be 64 hex chars and length 64; `dest` non-empty string; `asset` names unique across list; `executables` if present must be a sequence; list can be empty (Cannoli unaffected).
     - Update comments in `ansible/vars/nextui.yml` and `ansible/tasks/payload-nextui.yml` to say "NextUI paks" (general).
   - VERIFY: `uv run ansible-lint ansible/` clean; Cannoli dry path unaffected; NextUI with existing Grout still passes.

2. **[ansible] Pin three paks for tg5040**
   - WHERE: `ansible/vars/trimui-brick.yml`
   - HOW:
     - Keep/update Grout entry to new schema: `dest: Tools/tg5040/Grout.pak`, `executables: ["launch.sh","grout"]` (and verify paths; Grout extracts to that dir). Update any comment.
     - Add Tailscale: `repo: ben16w/minui-tailscale`, `tag: '2.0.0'`, `asset: Tailscale.pak.zip`, `sha256: c4d202fb99f0ab156b17596ba42d26dafb9358a8ce91e7361e6f399f49cd8e20`, `dest: Tools/tg5040/Tailscale.pak`, `executables: ["launch.sh"]`
     - Add Central Scrutinizer: `repo: Helaas/nextui-CentralScrutinizer-pak`, `tag: 'v0.3.0'`, `asset: Central.Scrutinizer.pak.zip`, `sha256: e3b6f0028ca5d31dcb1ba638829359ecf179facf409cab76f0a0b08688d88ee5`, `dest: Tools/tg5040/Central Scrutinizer.pak`, `executables: ["launch.sh","central-scrutinizer"]`
     - Keep order: NextUI archive first, then paks (order of paks doesn't matter if paths disjoint).
   - VERIFY: `uv run ansible-playbook ansible/build.yml -e device=trimui-brick --tags payload` stages all three; assert no `Tailscale.pak/Tailscale.pak` or `Central Scrutinizer.pak/Central Scrutinizer.pak`; assert `Tools/tg5040/Grout.pak/launch.sh` and `grout` executable; assert Tailscale has `pak.json` version string matches what we log (note artifact may show 1.3.0); assert CS has `pak.json` + both executables.

3. **[tests] Make NextUI test macOS-portable + cover three paks**
   - WHERE: `tests/ansible-payload-nextui.sh`
   - HOW:
     - Replace host `sfdisk`/`losetup`/`mount` MBR/mount checks with containerized equivalents (mirror `tests/smoke-image.sh`): run `sfdisk -d` via `--entrypoint sfdisk` in builder container; run losetup+mount+checks in a privileged container with trap; assert MBR start=2048 type=7; `fsck.exfat -n` clean.
     - Assert card contract: 15 top-level entries, valid `MinUI.zip`, no `em_ui.sh`, no extracted `.system`/`trimui/app/...`/`h700/`, and three paks at `Tools/tg5040/{Grout.pak,Tailscale.pak,Central Scrutinizer.pak}` each with required files and `launch.sh` executable; also assert `grout` and `central-scrutinizer` executable; assert `pak.json` exists for each and grep platform `tg5040` (or array contains tg5040).
     - Assert no flat extraction nesting: `[ ! -d "Tools/tg5040/Tailscale.pak/Tailscale.pak" ]` etc.
     - Assert no secrets: `! find "$PAYLOAD" -name authkey -o -name loginserver`.
     - Update corrupt-cache injection to loop over at least Grout and Tailscale (two pak assets); cache copies still done; assert failure names asset/checksum and says to delete from cache.
     - Update image size logic: account for larger payload (compute `du -sm`), keep formula `du+256`, floor 1024; add contingency comment/log if tight.
   - VERIFY: run on macOS in docker; checks pass with actual built image.

4. **[docs] Update pins, layout, credits, and warnings**
   - WHERE: `docs/nextui-layout.md`, `examples/trimui-brick/README.md`, `README.md`, `AGENTS.md`
   - HOW:
     - `docs/nextui-layout.md`: add Tailscale and Central Scrutinizer sections under `Tools/tg5040/`; document flat-zip extraction caveat (Linux vs macOS Archive Utility); document authkey at SD root (deleted after login), userdata paths, TUN requirement (default mode), `.userdata/<PLATFORM>/auto.sh`, `/var/run/tailscale` socket inference, DNS/route side effects; note CS terminal/pairing/screen-timeout unverified; note artifact pak.json version-lag (2.0.0 asset may ship 1.3.0).
     - `examples/trimui-brick/README.md`: add steps for all three paks, authkey instructions (docs-only), warnings.
     - `README.md`: update pin table to include both new paks (sha256 + size + repo/tag/asset); change text from "NextUI and Grout ZIPs" to "NextUI archive and paks" / "all archives SHA-256 pinned"; add Credits entries (Grout MIT, Tailscale client BSD-3-Clause + repo MIT, Central Scrutinizer MIT) and note bundled license files.
     - `AGENTS.md`: update "NextUI contract conventions" to mention three paks, platforms, auth notes, and CS side effects; do NOT modify Global Rules.
   - VERIFY: pin table matches `ansible/vars/trimui-brick.yml`; credits accurate.

5. **[meta] Evidence scaffolding**
   - WHERE: `.omo/evidence/nextui-tailscale-pak/`
   - HOW: create dir (gitignored) with placeholders or let verification fill; record commands/logs per F1-F4.
   - VERIFY: exists.

## Verification wave (blocking)
- **F1 (payload contract):** `uv run ansible-playbook ansible/build.yml -e device=trimui-brick --tags payload` in clean temp dirs; assert three paks present, executables correct, no secrets, no nesting, 15 top-level entries. Evidence: `payload-tree.txt`, `ls -la` of tg5040.
- **F2 (image build):** build image; assert MBR start=2048/type=7, size >=1024 MiB, `fsck.exfat -n` clean, ownership set. Evidence: `sfdisk-d.txt`, `fsck.log`.
- **F3 (mount/content):** mount via container and verify `MinUI.zip` present, paks present with correct perms, Grout/Tailscale/CS launch scripts exist. Evidence: `mount-listing.txt`.
- **F4 (lint/validate/tests):** `task lint`, `task validate`, `bash tests/ansible-payload.sh` (Cannoli), `bash tests/ansible-payload-nextui.sh` (updated). Evidence: command outputs.

## Risks & mitigations
- **Flat zip extraction:** unarchive the flat `Tailscale.pak.zip` directly into `Tools/tg5040/Tailscale.pak` (set dest to that dir). Same for CS. Test for nesting. (Librarian confirmed flat root; build will handle.)
- **Version lag:** 2.0.0 asset's `pak.json` may be 1.3.0. Do not rewrite pak.json; log the observed version in evidence and document in README/docs.
- **TUN/device support:** unknown on TrimUI Brick kernel; document as unverified requirement.
- **macOS test:** containerize all device checks to avoid `sudo losetup`/`diskutil` host deps.
- **Spaces in dir name:** quote everywhere; Ansible args fine.
- **Cache collisions:** validate unique asset names; corrupt two different assets.
- **License compliance:** retain `tailscale.LICENSE` and `jq.LICENSE`; document bundled components; note missing license files for minui-list/minui-presenter.

## Dependencies
- Docker available (for containerized checks and build). `unzip` available. `shellcheck`, `ansible-lint` via dev deps. Network for first fetches (cached after).

## Rollback
Revert commits on branch; no persistent system changes (build artifacts in `build/`/`dist/` gitignored). Cannoli untouched.

## Done when
- [ ] Generalized `remote_archives` with validation, three paks in trimui-brick vars
- [ ] `tests/ansible-payload-nextui.sh` passes on macOS with containerized checks
- [ ] All docs updated with correct pins and warnings
- [ ] `task lint`, `task validate`, both payload tests pass
- [ ] Evidence in `.omo/evidence/nextui-tailscale-pak/` for F1-F4
- [ ] Conventional commits with co-author footer
