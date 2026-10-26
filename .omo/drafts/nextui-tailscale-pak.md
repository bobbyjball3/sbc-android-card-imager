---
slug: nextui-tailscale-pak
status: drafting
intent: clear
review_required: false
pending-action: answer the abstraction question, then approval gate, then write .omo/plans/nextui-tailscale-pak.md
approach: Generalize the existing `remote_archives` entry contract (final `dest` + optional `executables`, plus a required-keys assert), add the pinned minui-tailscale 2.0.0 and Central Scrutinizer v0.3.0 paks to the `tg5040` profile, port the NextUI test's MBR/mount checks into the builder container so macOS can run them, then update the NextUI docs, example, README, and AGENTS for three paks.
---

# Draft: nextui-tailscale-pak

## Affected user and ideal state

**Affected user:** the repo owner building a TrimUI Brick card on macOS. Today one
`task image DEVICE=trimui-brick` produces a NextUI card with Grout only; after this
change the same command produces a card whose `Tools` menu offers Grout, Tailscale, and
The Central Scrutinizer, with no extra local install step and no secret baked into the
image.

| Row | Statement | Reason |
| --- | --- | --- |
| IS-1 | Every Brick image contains `Tools/tg5040/{Grout.pak,Tailscale.pak,Central Scrutinizer.pak}`, each runnable after the NextUI first boot. | The three paks are the point of the image; a missing one means a manual install. |
| IS-2 | Every pak is fetched from an exact tag/asset, SHA-256 verified from the cache, and a corrupt or truncated cached file fails the build naming the file and the remedy. | Reproducible builds; a silent bad download produces a card that fails on device. |
| IS-3 | No credential, token, key, or pairing state ever exists in the repo or the image; Tailscale state and Central Scrutinizer pairing live only on the card after the user acts. | The project already forbids pre-seeding Grout config/tokens. |
| IS-4 | The user knows how to enable each pak: `authkey` at the card root before first Tailscale launch (optional `loginserver` for Headscale), pairing PIN for Central Scrutinizer, RomM pairing for Grout; and which paths each writes. | Each pak has a different first-run flow and deletes or creates files; guessing costs a debug cycle. |
| IS-5 | Adding a pak is a data change in the device vars; the existing Grout result is byte-identical and the Cannoli tree is untouched. | One pipeline, one regression gate, no per-pak code paths. |
| IS-6 | `task test` passes on macOS and in CI, including the NextUI image build, MBR layout, and mounted card contents. | Repo rule: CI steps must run locally; the NextUI image half is currently Linux-only. |
| IS-7 | Docs and Credits state each pak's license (MIT), bundled third-party components, and that nothing is vendored. | Legal hygiene already applied to NextUI/Grout. |

| Row | Statement | Reason |
| --- | --- | --- |
| GAP-1 | `ansible/build.yml` hardcodes Grout via `'/Grout.pak' if item.repo == 'rommapp/grout'` (destination-dir and unarchive tasks) plus a Grout-only chmod task; no entry validation. | A third pak would add more special cases. |
| GAP-2 | `ansible/vars/trimui-brick.yml` pins only NextUI and Grout. | No Tailscale or Central Scrutinizer artifact is staged. |
| GAP-3 | `tests/ansible-payload-nextui.sh` asserts only Grout; the corrupt-cache injection only corrupts `Grout.pak.zip`. | New entries and their verify path would be untested. |
| GAP-4 | The same test runs `sfdisk`, `sudo losetup`, `sudo mount` on the host; macOS has no `sfdisk`, so it exits non-zero after building the image. | Blocks agent-executed QA on the owner's machine. |
| GAP-5 | `docs/nextui-layout.md`, `examples/trimui-brick/README.md`, `README.md`, `AGENTS.md` describe Grout only. | The next reader cannot find the paks, their pins, or their flows. |
| GAP-6 | No documentation of the paks' on-card writes (`.userdata/` state/logs, auto.sh boot hook, CS screen-timeout change, CS terminal risk) or of the Tailscale admin-console requirement. | Users will not know where state lives or why a key is required. |

## Components (topology ledger)

| id | outcome (one line) | status | evidence path |
| --- | --- | --- | --- |
| C1 | `remote_archives` entries carry `dest` (final directory) and optional `executables`, with a required-keys assert; Grout staging output unchanged; Cannoli unaffected. | active | `.omo/evidence/nextui-tailscale-pak/task-01-contract.log` |
| C2 | The NextUI test's MBR + mount assertions run inside the builder container; no host `sfdisk`/`sudo mount`; cleanup leaves no loop device. | active | `.omo/evidence/nextui-tailscale-pak/task-02-test-portability.log` |
| C3 | Tailscale 2.0.0 is cached, verified, extracted to `Tools/tg5040/Tailscale.pak`, `launch.sh` executable, asserted in the test. | active | `.omo/evidence/nextui-tailscale-pak/task-03-tailscale.log` |
| C4 | Central Scrutinizer v0.3.0 is cached, verified, extracted to `Tools/tg5040/Central Scrutinizer.pak`, `launch.sh` + `central-scrutinizer` executable, asserted in the test. | active | `.omo/evidence/nextui-tailscale-pak/task-04-central-scrutinizer.log` |
| C5 | Layout doc, example, README, AGENTS, and Credits describe all three paks, pins, flows, on-card writes, and licenses. | active | `.omo/evidence/nextui-tailscale-pak/task-05-docs.log` |

## Open assumptions (announced defaults)

| assumption | adopted default | rationale | reversible? |
| --- | --- | --- | --- |
| Ansible abstraction level | Per-entry YAML contract (`dest`, optional `executables`) + one `assert` over the entries; no custom module. | Three paks share one identical shape; a module is ~150 lines plus unit tests and CI wiring to replace three dicts. See the open question - user may override. | yes |
| One archive list | Keep `remote_archives` for the NextUI card root and all paks; `dest` distinguishes them. | A second `nextui_paks` list would duplicate cache/download/verify logic. | yes |
| Pak contents | Extract each upstream archive whole; no pruning of other-platform binaries. | Pruning mutates a checksum-pinned upstream artifact. | yes |
| Destination folders | Use the upstream folder names verbatim: `Grout.pak`, `Tailscale.pak`, `Central Scrutinizer.pak` (space included). | Upstream install docs; MinUI/NextUI discover `*.pak` directories by name. | yes |
| Inclusion policy | Ship all three unconditionally on the `nextui`/`tg5040` profile; no toggles. | Opinionated personal image; paks are inert until launched. | yes |
| Image sizing | Keep `image_size_mib: 8192` and the test formula `du -sm(payload) + 256` with a 1024 MiB floor. | Adds ~74 MB compressed across the two new paks. | yes |
| Hardware verification | Do not claim any pak runs on a Brick; document TUN/login, pairing, and server behavior as unverified on hardware. | No device available to the agent; same posture as the unproven exFAT boot. | n/a |

## Findings (cited - path:lines)

Repo (verified by direct read):

- `ansible/build.yml:98-105` - destination-directory task appends
  `'/Grout.pak' if item.repo == 'rommapp/grout' else ''`.
- `ansible/build.yml:160-167` - unarchive task repeats the same conditional.
- `ansible/build.yml:169-177` - chmod task hardcodes
  `Tools/{{ nextui_platform }}/Grout.pak/{{ launch.sh|grout }}`, `when: payload_profile == 'nextui'`.
- `ansible/build.yml:88-89` - archive block guarded by `remote_archives | length > 0`, so
  Cannoli (empty list, `ansible/vars/trimui-brick.yml:27`) is unaffected.
- `ansible/build.yml:107-158` - cache stat -> assert -> `get_url` (checksum, `force: false`,
  timeout 600) -> stat -> assert, looped per entry; adding entries needs no code change.
- `ansible/vars/trimui-brick.yml:15-25` - `remote_archives` shape: `repo`, `tag`, `asset`,
  `sha256`, `dest`.
- `tests/ansible-payload-nextui.sh:69-71` - 15-entry top-level list.
- `tests/ansible-payload-nextui.sh:91-98` - Grout-only pak assertions.
- `tests/ansible-payload-nextui.sh:113-135` - corrupt-cache injection hardcodes
  `Grout.pak.zip`.
- `tests/ansible-payload-nextui.sh:178-193` - host `sfdisk` + `sudo losetup` + `sudo mount`
  (the macOS failure).
- `tests/smoke-image.sh:160-285` - portable pattern: `docker run --rm --privileged
  --entrypoint sfdisk`, and a container that runs `losetup`/`mount`/content checks.
- `docs/nextui-layout.md:21-24` pin table; `:48` Tools row; `:77-115` Grout section;
  `:171-183` attribution; `:185-205` refresh procedure.
- `examples/trimui-brick/README.md:21-37` pin table; `:125-144` Grout setup.
- `README.md` NextUI profile bullet, Brick happy-path table, `### First boot and Grout`,
  `## NextUI layout summary`, `## Credits and Attribution`.
- `AGENTS.md:141-142` (Grout-specific extract/chmod), `:166-178` NextUI contract
  conventions, `:207-210` NextUI test description.

Upstream, Tailscale pak:

- Release `2.0.0` (2026-08-28), asset `Tailscale.pak.zip`, size `72,816,569`, digest
  `sha256:c4d202fb99f0ab156b17596ba42d26dafb9358a8ce91e7361e6f399f49cd8e20`.
- `pak.json`: `name: Tailscale`, `version: 2.0.0`, `platforms` include `tg5040`, `launch: launch.sh`.
- Install: extract into `/Tools/<platform>/`, expect `Tailscale.pak/launch.sh`. `authkey`
  goes at the **card root** (deleted after first login); optional `loginserver` for Headscale.
- `launch.sh`: `tailscaled --statedir="$USERDATA_PATH/$PAK_NAME/"`, writes
  `$SDCARD_PATH/.userdata/$PLATFORM/auto.sh` for start-on-boot, logs to
  `$LOGS_PATH/$PAK_NAME.txt`, chmods its own `bin/` binaries at launch.
- Packaging: `git archive HEAD` + appended `bin/` files -> bare root, no prefix.
- License: MIT (project). Bundled Tailscale client 1.102.3 (license file shipped in the pak),
  jq and minui-list/minui-presenter with their own license files.

Upstream, Central Scrutinizer:

- Release `v0.3.0` (2026-09-11), asset `Central.Scrutinizer.pak.zip`, size `1,318,350`,
  digest `sha256:e3b6f0028ca5d31dcb1ba638829359ecf179facf409cab76f0a0b08688d88ee5`.
- `pak.json`: `name: Central Scrutinizer`, `version: v0.3.0`, `platforms:
  [tg5040, tg5050, my355, h700]`, `release_filename: Central.Scrutinizer.pak.zip`.
- `Makefile` `package` target: `cd "build/universal/Central Scrutinizer.pak" && zip -9 -r
  .../Central.Scrutinizer.pak.zip . -x '.*'` -> bare root, folder name contains a space,
  binary is `central-scrutinizer`.
- `launch.sh`: `exec ./central-scrutinizer`, logs to `$LOGS_PATH/central-scrutinizer.txt`.
- README: device-hosted dashboard on port 8877, 4-digit pairing PIN or QR, no cloud or
  account, optional background mode (temporarily sets NextUI Screen timeout to Never),
  optional browser terminal (real shell, off by default), managed dirs `Roms/ Saves/ Bios/
  Overlays/ Cheats/ Collections/ Screenshots/`.
- License: MIT, Copyright (c) 2026 Kevin Vranken.

## Decisions (with rationale)

1. `remote_archives` entries become self-describing: `dest` is the final directory the
   archive is extracted into, and `executables` lists the files under it to chmod 0755.
   Rationale: removes the existing Grout special case; all three paks now use one path.
2. No separate `nextui_paks` list. Rationale: one download/cache/verify loop; `dest`
   already distinguishes the card root from a pak folder.
3. Stage upstream folder names verbatim, including the space in `Central Scrutinizer.pak`.
   Rationale: matches upstream install docs and NextUI pak discovery.
4. Never stage `authkey`, `loginserver`, pairing state, or pak config. Rationale: existing
   no-credentials invariant.
5. Containerize the NextUI test's image checks. Rationale: otherwise the agent cannot prove
   the new assertions on this macOS host.
6. Document Central Scrutinizer's terminal and background-mode side effects as risks.
   Rationale: it opens a real shell and mutates a NextUI setting; the card owner must know.

## Scope IN

- `ansible/build.yml`: replace both Grout conditionals with `item.dest`; replace the Grout
  chmod task with an `executables` loop; add a required-keys assert over `remote_archives`.
- `ansible/vars/trimui-brick.yml`: Grout `dest` becomes the full path; add Tailscale and
  Central Scrutinizer entries with their pins and `executables`.
- `tests/ansible-payload-nextui.sh`: containerized MBR/mount checks and cleanup; assertions
  for all three paks; corrupt-cache injection over the pak archives.
- `docs/nextui-layout.md`, `examples/trimui-brick/README.md`, `README.md`, `AGENTS.md`.

## Scope OUT (Must NOT have)

- No custom Ansible module/role/collection (unless the open question overrides this).
- No `authkey`, `loginserver`, pairing state, config override, or any credential in the repo
  or image; no interactive prompt in the playbook.
- No pruning of upstream pak contents; no vendored pak archives.
- No Cannoli changes, no new payload profile, no `tg5050`/`my355`/`h700` support.
- No FAT32 builder, no container/Dockerfile/Taskfile/CI-dependency change.
- No ROMs/BIOS; no mutable `latest` tag.
- No claim that any pak or the exFAT card has been verified on real Brick hardware.

## Open questions

Resolved with the user:

1. Abstraction level at three paks -> **data + validation assert**; no custom module.
2. Tailscale auth key -> **docs only, no key staged** (write `authkey` at the card root
   after flashing; the pak deletes it).
3. macOS test portability -> **fold the containerized MBR/mount fix into this plan**.

## Approval gate

status: awaiting-approval
approach: five implementation todos (contract + assert, test portability, Tailscale pin,
Central Scrutinizer pin, docs) followed by the standard four-item verification wave.
next workflow action: on explicit user okay, write `.omo/plans/nextui-tailscale-pak.md`
from the plan template and append the todos; then hand off for `$ulw-execute`.

## Gap pass (Metis unavailable - in-session substitute)

Metis failed to start again with a provider/model error. Substitute pass, ranked:

| # | Kind | Gap | Handling in the plan |
| --- | --- | --- | --- |
| 1 | BLOCKER | Entry validation must not break the Cannoli profile (`remote_archives: []`) and must name missing keys. | Assert loops over entries; empty list is a no-op. Check key presence with `['repo','tag','asset','sha256','dest'] \| difference(item.keys() \| list) \| length == 0`, sha256 length 64, `dest` non-empty string, asset names unique. |
| 2 | BLOCKER | `executables` loop must tolerate entries without the key and entries with an empty list. | `remote_archives \| selectattr('executables','defined') \| list \| subelements('executables')`; `loop_control.label` on `item.0.asset`. |
| 3 | RISK | Archive contents could nest a pak folder, producing `X.pak/X.pak`. | Test asserts `<pak>/<pak>` does not exist for all three; upstream packaging verified bare-root for all three. |
| 4 | RISK | Cache key is only `item.asset`; duplicate asset names would collide. | Validation asserts asset names are unique. |
| 5 | RISK | Test image may be too small with +74 MB of paks. | Print `du -sm` into evidence; formula stays `du + 256`, floor 1024; contingency if the build hits ENOSPC: headroom 512 + floor 2048 in the same commit. |
| 6 | RISK | Corrupt-cache injection over three 340 MB cache copies is slow. | Loop over the two pak assets (Grout, Tailscale); happy path first; fresh payload dir per run. |
| 7 | RISK | Paths contain a space (`Central Scrutinizer.pak`). | Quote every path in the test; use module args (never shell) in Ansible. |
| 8 | RISK | Containerized mount check could leak a loop device. | Container trap cleans up; `--rm`; assert `losetup -a` inside a fresh container has no reference to the test image. |
| 9 | RISK | Secrets could leak into the image later. | Test asserts no `authkey`/`loginserver` anywhere under the payload. |
| 10 | RISK | Docs drift across five places. | Todo 5 lists exact rows/sections per file; F1/F4 re-check pin table vs vars. |
| 11 | RISK | Version strings differ per pak (`2.0.0`, `v0.3.0`, `v5.4.0.0`). | Each pak's test assertion matches its own exact string. |
| 12 | NIT | Comments in `nextui.yml:4` and `payload-nextui.yml:7` say Grout only. | Update both in todo 1. |

Hardware-only unknowns recorded, not planned as work: Tailscale needs `/dev/net/tun` and a
login; Central Scrutinizer needs Wi-Fi and port 8877 and offers a shell terminal; exFAT boot
remains unproven. All are documented as unverified on hardware.

