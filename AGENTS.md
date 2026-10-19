# AGENTS.md
## General Rules
- You **MUST** maintain this file and add useful context as part of each feature we build
- You **NEVER** modify or otherwise override any rule I define in the [Global Rules](#global-rules) H1

# Global Rules
## Git Rules
### General Git Rules
- Both git and the gh cli are configured. **NEVER** do anything destructive without asking even if the current mode is build.
- **ALWAYS** do your your work from a feature branch - not from main!
- **ALWAYS** base your your branches on latest main branch - no complex branching strategies
- **ALWAYS** use [conventional branches](https://conventionalbranch.org/#spec) for your branch names
- **ALWAYS** use [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/#specification)
- **ALWAYS** keep commit messages below 75 words. If 75 words cannot convey necessary context for a commit, that is a hint the commit contains too many changes - break it up.
- **NEVER** create monolithic commits like "refactor codebase" or "implement new data model". Commits should contain complete changes, but not necessarily all changes required for the current feature.
- **ALWAYS** include a co-author statement in commits you author on my behalf in the commit footer, like below. This footer does not count against commit message length constraints specified above.
```shell
Co-authored-by: ${MODEL_PROVIDER} - ${MODEL_MAKING_THE_COMMIT} <${MODEL_PROVIDER_LOWERCASE_SNAKECASE}@${MODEL_PROVIDER_WEBSITE}>

# Example
Co-authored-by: DeepSeek - Flash 4.1 <deepseek@deepseek.com>
```

### Safety
- **NEVER** update git config
- **NEVER** run destructive commands (--force, hard reset) without explicit request
- **NEVER** skip hooks (--no-verify) unless user asks
- **NEVER** force push to main/master
- **ALWAYS** fix and create NEW commit (don't amend) if commit fails due to hooks

## Project Toolchain
- Use pre-commit hooks to ensure any code included in this project is linted/formatted/bugchecked/etc.
- Prefer Python for code in the repository
  - use uv to manage python environment, dependencies, etc. (https://github.com/astral-sh/uv)
  - use ruff for formatting, linting, etc. (https://github.com/astral-sh/ruff)
  - Configure all possible settings in pyproject.toml rather than tool-specific config files
- Use Shell sparingly if at all
- Use Task for repeatable tasks (https://taskfile.dev)
- When at all possible whatever runs in GitHub actions should also be able to run local (exceptions can be made - ask if there's a trade-off). This implies that most github actions are just invocations of a given Task task
- If there are a lot of system level dependencies (e.g. linux utilities, dev header files, etc.) bias towards building a Dockerfile that sets up that build container rather than installing any utilities locally on Mac

## Software Rules
- Follow good software patterns (POLA, SRP, DRY, abstractions and interfaces, favor composition over inheritance, etc.)
- Use abstractions where it's useful, but follow the rule of threes

# END Global Rules

## Project Implementation Notes

### Purpose
`sbc-imager` turns one strict TOML manifest into a verified, flashable Cannoli-ready
SD card image, then flashes that image to a removable card on macOS. The pipeline is:
manifest -> pinned source cache -> staged `Cannoli/` tree -> containerized MBR+exFAT
sparse image -> `fsck`/hash verification -> interactive raw-device write. The tool is
payload-only: it does not download ROMs, install APKs, or provide zero-touch first boot.

### Package layout
- `src/sbc_imager/` - the package (typed, `py.typed`):
  - `cli.py`, `cli_image.py`, `cli_verify.py` - Typer app and command registration
  - `config.py` - strict manifest parsing into frozen dataclasses
  - `cannoli.py` - pinned platform registry and on-card path contract
  - `sources.py`, `sources_git.py` - content-addressed cache and pinned source resolution
  - `planner.py`, `validation*.py`, `staging.py` - destination mapping, rules, and staging
  - `assembler*.py`, `mbr.py`, `container.py`, `build.py`, `verify.py` - image assembly,
    container invocation, orchestration, and verification
  - `imaging.py`, `imaging_write.py` - macOS disk enumeration and raw-device writing
  - `runner.py` - injectable subprocess seam; `errors.py`, `sizes.py`, `fs.py` - shared support
- `tests/unit/` - fast, rootless tests; `tests/integration/` - privileged Linux-only tests
- `examples/imager.toml` + `examples/demo/` - sample manifest with placeholder assets
- `docs/` - manifest and generated Cannoli reference; `Dockerfile` - assembler container
- `Taskfile.yml` and `pyproject.toml` - task runner, dependencies, and tool configuration

### Task commands
Run `task <name>` from the repository root:
- `setup` - sync all uv groups and install pre-commit hooks
- `lint` - ruff check, ruff format check, and pyright
- `format` - apply ruff fixes and formatting
- `test` - unit tests (`pytest -m "not integration"`)
- `test:integration` - privileged integration tests; Linux with `sudo` and loop/mount/exfat
- `container` - build the local assembler image (`sbc-imager-assembler:local`)
- `plan` - plan a card from `examples/imager.toml` without writing an image
- `build` - build an image from the sample manifest
- `verify` - verify `dist/demo.img` against the sample manifest
- `image` - flash an image to a removable card interactively (macOS, `sudo`)
- `ci` - local gate: `lint`, `test`, then `uv build`

### Manifest conventions
Manifests are TOML with an `[image]` table and arrays of tables: `[[source]]`,
`[[overlay]]`, `[[shader]]`, `[[apk]]`, and `[[artifact]]`. ROMs, BIOS files, and box
art are supplied by Cannoli/RomM and are not manifest inputs; the retired `[[rom]]`,
`[[bios]]`, and `[[art]]` tables fail with a migration error, while the on-card
directory skeleton is still created. Unknown keys and invalid types are rejected;
there is no permissive fallback. Relative paths resolve against the manifest directory,
and `[image].size` supports `auto` or human-readable units (`reserve` likewise). Typed
entries map to `Cannoli/Overlays/<TAG>`, `Cannoli/Shaders/<preset>`, and root `APKs/`;
generic artifacts target an explicit root and destination, including the retained
`Cannoli/Roms/<TAG>`, `Cannoli/BIOS`, and `Cannoli/Art` skeleton. Overlays and shaders
may reference a `source` id instead of a local path.
Git sources require a pinned `ref` (commit or tag; branches need `--allow-branch`) and
HTTP sources require a pinned lowercase `sha256`. The cache lives under the platform cache
directory, can be overridden with `SBC_IMAGER_CACHE_DIR`, and supports `--offline`.
Validation enforces Cannoli tags, exFAT-safe names, duplicate/colliding destinations, and
required assets before anything is staged. A branch ref allowed with `--allow-branch` emits
a `branch-ref` warning from `plan` and `fetch`; `plan --json` puts it in `warnings`, while
`fetch --json` attaches it to the affected source row. Typed local root paths that are
themselves symlinks are rejected before resolution; symlinked parent directories are allowed.

### Cannoli registry conventions
Cannoli is pinned at **v1.9.1**, commit `7755e376b6add0bbd25ea19104c368b7a40b979f`.
`src/sbc_imager/cannoli.py` is the runtime source of truth: `PLATFORM_TAGS` holds all 51
tags with their display names, plus path builders and hard-required BIOS metadata. Its
`SIZE_OK` marker records the intentional exemption for this pinned data table. There
is no network access at runtime. `docs/cannoli-platform-tags.md` is generated from
`render_markdown()` and a test asserts it matches the registry. To refresh the registry,
fetch the pinned upstream `platforms.json` for the chosen release, update the pin
constants, `PLATFORM_TAGS`, the generated doc, and the tests together in one change.

### Image safety rules
Imaging runs only on macOS and only against external, removable, whole physical disks;
internal disks and the disk backing `/` are rejected. There is no `--device`, `--yes`, or
unattended mode: the operator selects a disk from the enumerated list, sees the
model/size/serial warning, and must type exactly `ERASE <device>` before any write.
Writes target only `/dev/rdisk<N>` (never `/dev/disk*`), require the image to fit, and
require a successful `diskutil unmountDisk`. `write_image` re-checks that the target is a
whole, non-internal disk immediately before writing, even when enumeration already ran. The
command never auto-sudoes, never uses
`dd`, never formats or partitions, and never retries. `--dry-run` reports the target and
image SHA-256 without writing. On interruption the card is left partially written with a
loud warning and exit code 130; it is not repaired automatically.

### Testing strategy
Write tests first. `task test` runs the rootless unit suite, which uses the fake
`Runner`/`SourceCache` seams and temporary directories instead of real subprocesses or
devices. `task test:integration` is opt-in and runs the loop/mount/`fsck.exfat` paths on
privileged Linux; it is skipped elsewhere. Coverage targets 85% and pre-commit runs ruff,
pyright, and the unit suite. The assembler image pins every apt package to an exact
bookworm version; refresh pins deliberately when the base digest changes. Fixtures must
use tiny non-copyrighted placeholders - never real ROMs, BIOS files, or other copyrighted
assets.

### Commit and co-author convention
Follow the Global Rules: work on a conventional feature branch based on current `main`,
use conventional commits, and keep changes focused. End commits authored on the user's
behalf with the co-author footer required by the Global Rules, for example:

```shell
Co-authored-by: DeepSeek - Flash <deepseek@deepseek.com>
```
