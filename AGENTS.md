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
Ansible stages a Cannoli payload tree from a device vars file, and a privileged Linux
container turns that tree into a sparse MBR + exFAT SD card image file. The pipeline is:
device vars -> `ansible/build.yml` staging (17 base dirs + 51 Roms tags + settings marker +
pinned remote/local payloads) -> containerized MBR+exFAT sparse image -> `fsck.exfat -n` ->
atomic publish of a `.img` file. The tool is payload-only: it does not download ROMs,
install APKs, or provide zero-touch first boot.

### The no-block-device rule (deliberate design change)
The tool produces an image **file** only. All block-device writes were ripped out: there
is no macOS raw-device imager, no disk enumeration for writing, no `ERASE` prompt, and no
`--dry-run` flashing path. `container/build-image.sh` refuses any output path under
`/dev/` and any non-`.img` output. The ONLY supported write path is the user running `dd`
or balenaEtcher (or Raspberry Pi Imager in "use custom image" mode) against the built
`.img`. Never reintroduce device-writing code.

### Architecture and layout
- `ansible/build.yml` - the single playbook (`hosts: localhost`, `connection: local`).
  Staging tasks are tagged `payload`; only the final container-invocation task is tagged
  `image`. Default vars: `payload_dir: build/payload`, `dist_dir: dist`,
  `image_output: dist/<device>.img`. Vars files: `ansible/vars/cannoli.yml` (shared
  contract) + `ansible/vars/<device>.yml` (device payload).
- `ansible/vars/cannoli.yml` - data-only source of truth for the on-card contract:
  `cannoli_base_dirs` (17), `cannoli_tags` (51, one `Cannoli/Roms/<TAG>` each), and
  `cannoli_settings_marker: Cannoli/Config/settings.json` (a FILE written as `"{}\n"`,
  not a directory). No display-name/BIOS metadata lives here; that reference data lives
  in `docs/cannoli-platform-tags.md`.
- `ansible/vars/<device>.yml` - per-device pins: `device`, `image_label`,
  `image_device`, `image_size_mib`, `image_output`, `remote_assets` (exact
  GitHub `repo`/`tag`/`asset` + card `dest`), `local_files` (`src` under
  `ansible/files/<device>/` + `dest`), and `local_dirs`.
- `ansible/files/<device>/` - local payload files copied into the staged tree.
- `container/build-image.sh` + `Dockerfile` - the builder. The Dockerfile (build context =
  repo root) installs exfatprogs/util-linux/fdisk/rsync/coreutils on
  `debian:bookworm-slim` and copies the script to `/usr/local/bin/build-image` as the
  ENTRYPOINT. Image tag: `sbc-imager-builder:local`.
- `tests/*.sh` - shell QA scripts (see Testing strategy).
- `docs/cannoli-platform-tags.md` - human reference for the 51-tag contract.
- `Taskfile.yml` and `pyproject.toml` - task runner and pinned toolchain
  (`ansible-core` lives in `pyproject.toml`; playbooks run via `uv run ansible-playbook`).

### Container boundary (`build-image`)
Interface: `build-image <payload> <out.img> <size_mib> <label>`, invoked by the playbook as
`docker run --rm --privileged -e HOST_UID -e HOST_GID -v <payload>:/payload:ro -v <dist>:/out
sbc-imager-builder:local /payload /out/<name>.img <size_mib> <label>`.

Rules enforced inside the container:
- Refuses `out` under `/dev/` (or `//dev/`), non-`.img` outputs, a missing payload dir,
  an `out`/`.partial` that exists as a non-regular file, a non-integer `size_mib` < 2,
  and a label outside 1-11 characters.
- Assembles into `<out>.partial`: sparse `truncate`; `sfdisk` with
  `label: dos`, `start=2048`, `type=7`; `losetup --offset 1048576 --sizelimit
  (size-1MiB)`; `mkfs.exfat -L <label>`; mount + `rsync -rlt --delete`; `sync`;
  `umount`; `fsck.exfat -n`; `losetup -d`; then atomic `mv <out>.partial <out>`.
- Applies `HOST_UID`/`HOST_GID` ownership to the published image when set.
- Traps clean up the loop device, mountpoint, and partial file on any exit; SIGINT/SIGTERM
  exit 130/143. The final stdout line is `Wrote <out> (<size>MiB, label <label>)`.

### Playbook conventions
- Size resolution order: (1) a non-empty `image_device` reads that disk's geometry
  read-only via `diskutil info -plist` + `plutil`, asserts `WholeDisk == true`, and sets
  `image_size_mib = TotalSize // 1MiB`; (2) otherwise `image_size_mib` comes from the
  device vars file or `-e`; (3) neither -> the final assert fails. The playbook never
  writes the device in any path.
- The size assert requires `image_size_mib >= 2`. Pass `-e image_device=` to force the
  explicit size instead of a device read.
- Remote assets use `ansible.builtin.get_url` with `force: no` against
  `https://github.com/<repo>/releases/download/<tag>/<asset>` (the 302 to
  objects.githubusercontent.com is followed). Exact tag only; no mutable selectors.
  If redirect/403 failures appear, switch ONLY that task to `ansible.builtin.uri` with
  `follow_redirects: all`.
- `--tags payload` stages the tree without invoking the container; a full run stages
  and builds. `payload_dir`/`dist_dir`/`image_output` are `-e` overridable and the tests
  use temp dirs to keep `build/` and `dist/` untouched.

### Cannoli contract conventions
Cannoli is pinned at **v1.9.1**, commit `7755e376b6add0bbd25ea19104c368b7a40b979f`.
`ansible/vars/cannoli.yml` is the runtime source of truth for the directory contract:
17 `cannoli_base_dirs` (Cannoli root + 15 Cannoli dirs + `APKs`), 51 `cannoli_tags`
(each staged as `Cannoli/Roms/<TAG>`), and the `cannoli_settings_marker` file. The staged
tree is 70 directories total: 17 + 51 + the implicit `Cannoli/Media` parent (of the two
declared `Media/*` dirs) + `Obtainium` (destination of device `local_files`). There is no
network access at runtime. To refresh the contract, update the pinned upstream
`platforms.json` data into `cannoli_tags`, `docs/cannoli-platform-tags.md`, and the test
expectations (`tests/ansible-payload.sh` counts, `tests/parity-rg477m.sh` `BASE_DIRS`)
together in one change. The old pipeline's `CREDITS.md` emission is gone; no payload
builds it.

### Task commands
Run `task <name>` from the repository root. Target names are `setup`, `lint`,
`validate`, `image`, `container`, `test`, and `ci`; the canonical commands they wrap are:
- `setup` - `uv sync --all-groups` and install pre-commit hooks
- `container` - `docker build -t sbc-imager-builder:local .`
- `image` - `uv run ansible-playbook ansible/build.yml -e device=<DEVICE>` (the full
  staged build; `--tags payload` collects the payload only)
- `lint` - ruff check, ruff format check, pyright
- `validate` - payload/build contract checks
- `test` - the shell test suite
- `ci` - the local gate (lint + test)

The raw ansible-playbook commands are the verified interface; keep any Taskfile
wrapper a thin alias for them.

### Testing strategy
Write tests first. The suite is shell scripts in `tests/`:
- `tests/ansible-payload.sh` - runs the payload playbook into a temp dir and asserts the
  contract: exactly 3 top-level entries (`APKs`, `Cannoli`, `Obtainium`), 17/17 base dirs,
  51/51 Roms tags, 70 directories total, the 3-byte `"{}\n"` settings marker, the 3 pinned
  payload files with exact byte sizes (and prints their SHA-256), and no `CREDITS.md`.
  Includes failure injection against a copy of the tree.
- `tests/smoke-image.sh` - offline 66 MiB tree-to-image smoke of the builder with a
  placeholder-byte fixture: exact image size, MBR start=2048/type=7, `fsck.exfat -n`
  clean, mounted content assertions, loop-device leak check, and invalid-input failure
  cases. All mounts run inside disposable privileged containers.
- `tests/parity-rg477m.sh` - parity gate: builds the same 128 MiB RG477M image with the
  old Python pipeline and the new Ansible pipeline and proves the listings match
  (excluding `CREDITS.md`, which only the old pipeline writes), plus a failure-injection
  check that the comparison can fail.
Evidence is appended under `.omo/evidence/` (gitignored). No test writes a block device;
fixtures use tiny non-copyrighted placeholder bytes - never real ROMs, BIOS files, or
other copyrighted assets.

### Commit and co-author convention
Follow the Global Rules: work on a conventional feature branch based on current `main`,
use conventional commits, and keep changes focused. End commits authored on the user's
behalf with the co-author footer required by the Global Rules, for example:

```shell
Co-authored-by: DeepSeek - Flash <deepseek@deepseek.com>
```
