# F4. Ideal-state fidelity

Date: 2026-10-25

## IS-1: No host block writes; dd/Etcher only
- [x] Playbook never writes devices; size logic only reads via diskutil when image_device set
- [x] container/build-image.sh refuses /dev/* and non-.img paths
- [x] Taskfile has no block-device write tasks
- Evidence: F2 diff review, F3 builder logs

## IS-2: Profile switch; Cannoli unchanged
- [x] payload_profile in ['cannoli','nextui']
- [x] tests/ansible-payload.sh passes with 70 dirs/3 files/marker/no CREDITS.md
- Evidence: F3 tests/ansible-payload.sh output

## IS-3: NextUI root + Grout at Tools/tg5040/Grout.pak
- [x] ansible/vars/trimui-brick.yml configured for nextui/tg5040
- [x] ansible/tasks/payload-nextui.yml creates structure
- [x] Grout extracted to Tools/tg5040/Grout.pak with chmod 0755
- Evidence: tests/ansible-payload-nextui.sh assertions (happy path)

## IS-4: Exact pins, SHA-256, cache, extraction
- [x] NextUI v6.15.0 NextUI-20261013-0-all.zip SHA-256 pinned
- [x] Grout v5.4.0.0 Grout.pak.zip SHA-256 pinned
- [x] Cache under build/cache with force:false, timeout:600
- [x] Checksum verification via stat/assert
- [x] Corrupt cache and empty archives tested
- Evidence: F3 tests/ansible-payload-nextui.sh (includes failure injections)

## IS-5: MBR + exFAT image, fsck.exfat -n clean
- [x] Container builder unchanged, produces MBR + exFAT
- [x] Smoke test passes
- [x] tests/ansible-payload-nextui.sh builds real image
- Evidence: F3 logs

## IS-6: Size and IMAGE_DEVICE device-aware
- [x] Taskfile conditionally passes SIZE_MIB/IMAGE_DEVICE
- [x] 8192 MiB default for trimui-brick, >=1024 guard
- [x] Four dry-run shapes verified
- Evidence: F3 dry-run outputs

## IS-7: Both paths tested in CI
- [x] task test runs ansible-payload.sh, ansible-payload-nextui.sh, smoke-image.sh
- [x] CI installs unzip
- [x] validate checks both devices
- Evidence: Taskfile, CI workflow, F3

## IS-8: Docs/AGENTS/examples/licensing/risk
- [x] docs/nextui-layout.md created with pins, layout, first-boot, Grout, licenses
- [x] examples/trimui-brick/README.md created
- [x] README.md updated with multi-device table, Brick quickstart, risks, credits
- [x] AGENTS.md updated for profiles, remote_archives, cache_dir, testing
- [x] pyproject.toml device-neutral description
- [x] ExFAT boot unproven noted with FAT32 fallback; hardware boot is user post-handoff check (not agent-proven)
- Evidence: Files exist, pins match vars

## Verdict
All IS-1..IS-8 satisfied. Hardware boot verification remains a user responsibility on real TrimUI Brick hardware (explicitly documented). No shortfalls identified.

PASS
