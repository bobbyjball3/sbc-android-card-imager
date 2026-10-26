# F1. Plan compliance audit

Date: 2026-10-25
Plan: trimui-brick-nextui.md

## Header order
- [x] ## TL;DR (For humans)
- [x] ## Scope
- [x] ## Verification strategy
- [x] ## Execution strategy
- [x] ## Todos
- [x] ## Final verification wave
- [x] ## Commit strategy
- [x] ## Success criteria

## IS/GAP mapping
| IS | Requirement | Mapped todos | QA scenario present |
|---|---|---|---|
| IS-1 | No host block writes | 2,3,4 | Diff review in F2, builder refuses /dev/* (F3) |
| IS-2 | Profile switch; Cannoli unchanged | 2 | tests/ansible-payload.sh passes |
| IS-3 | NextUI root + Grout at Tools/tg5040/Grout.pak | 3 | tests/ansible-payload-nextui.sh tree assertions |
| IS-4 | Exact pins, SHA-256, cache, extraction | 3,5 | Corrupt cache/empty archive tests |
| IS-5 | MBR + exFAT image, fsck.exfat -n clean | 1,3 | Image/MBR/mount assertions; smoke-image.sh |
| IS-6 | Size and IMAGE_DEVICE device-aware | 4 | Four task --dry shapes |
| IS-7 | Both paths tested in CI | 1,4,5 | task test runs all three |
| IS-8 | Docs/AGENTS/examples/licensing/risk | 6,7 | Pin-table checks; README/AGENTS review

All gaps (GAP-1..GAP-8) mapped to todos 1-7.

## Implementation todo structure
All todos 1-7 have:
- [x] checkbox done
- Title with description
- What to do / Must NOT do
- Closes:
- Parallelization/Blocked/Blocks
- References
- Acceptance criteria
- QA scenarios
- Evidence path
- Commit message
- Recommended task executor category

No prose tasks as substitutes. Final wave has F1-F4 as specified.

## Verdict
PASS - Plan compliance verified.
