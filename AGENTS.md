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
Ansible stages a device payload tree selected by `payload_profile` (`cannoli` or `nextui`),
and a privileged Linux container turns that tree into a sparse MBR + exFAT SD card image
file. The pipeline is: device vars + profile -> `ansible/build.yml` staging (profile task
file, pinned remote assets/archives, local files) -> containerized MBR+exFAT sparse image
-> `fsck.exfat -n` -> atomic publish of a `.img` file. Two payload profiles ship today:
`cannoli` (17 base dirs + 51 Roms tags + settings marker + Obtainium) and `nextui`
(pinned NextUI `-all` archive + pinned Grout pak on `tg5040`). The tool is payload-only:
it does not download ROMs, install APKs, or provide zero-touch first boot.

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
  `image`. It validates `payload_profile in ['cannoli', 'nextui']`, loads
  `ansible/vars/<profile>.yml` with `include_vars`, and includes
  `ansible/tasks/payload-<profile>.yml`. Default vars: `payload_profile: cannoli`,
  `payload_dir: build/payload`, `dist_dir: dist`, `image_output: dist/<device>.img`,
  `cache_dir: build/cache`, plus empty `remote_assets`, `remote_archives`, `local_files`,
  and `local_dirs` so a profile can opt in. Only `ansible/vars/<device>.yml` is in
  `vars_files`.
- `ansible/tasks/payload-cannoli.yml` - Cannoli staging: base dirs, 51
  `Cannoli/Roms/<TAG>` dirs, `Obtainium`, and the settings marker.
- `ansible/tasks/payload-nextui.yml` - NextUI staging: `nextui_base_dirs`,
  `Tools/<nextui_platform>`, `Cheats`, and a guard that `remote_archives` is non-empty.
- `ansible/vars/cannoli.yml` - data-only source of truth for the Cannoli on-card
  contract: `cannoli_base_dirs` (17), `cannoli_tags` (51, one `Cannoli/Roms/<TAG>`
  each), and `cannoli_settings_marker: Cannoli/Config/settings.json` (a FILE written as
  `"{}\n"`, not a directory). No display-name/BIOS metadata lives here; that reference
  data lives in `docs/cannoli-platform-tags.md`.
- `ansible/vars/nextui.yml` - NextUI profile contract: `nextui_base_dirs: [Tools]`.
  `nextui_platform` lives in the device vars (`tg5040` for the Brick/Smart Pro).
- `ansible/vars/<device>.yml` - per-device pins: `device`, `payload_profile`,
  `image_label`, `image_device`, `image_size_mib`, `image_output`, `remote_assets`
  (exact GitHub `repo`/`tag`/`asset` + card `dest`), `remote_archives` (exact
  `repo`/`tag`/`asset`/`sha256` + card `dest`), `local_files` (`src` under
  `ansible/files/<device>/` + `dest`), `local_dirs`, and `nextui_platform` when needed.
- `ansible/files/<device>/` - local payload files copied into the staged tree.
- `container/build-image.sh` + `Dockerfile` - the builder. The Dockerfile (build context =
  repo root) installs exfatprogs/util-linux/fdisk/rsync/coreutils on
  `debian:bookworm-slim` and copies the script to `/usr/local/bin/build-image` as the
  ENTRYPOINT. Image tag: `sbc-imager-builder:local`. The two payload profiles share this
  same builder; do not fork or change it for NextUI.
- `tests/*.sh` - shell QA scripts (see Testing strategy).
- `docs/cannoli-platform-tags.md` - human reference for the 51-tag Cannoli contract.
- `docs/nextui-layout.md` + `examples/trimui-brick/` - human reference and example for
  the NextUI card, first boot, Grout setup, and licensing.
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
- `payload_profile` is validated up front and must be `cannoli` or `nextui`; an unknown
  value fails before any staging. The profile vars file and profile task file are both
  selected from `payload_profile`.
- Size resolution order: (1) a non-empty `image_device` reads that disk's geometry
  read-only via `diskutil info -plist` + `plutil`, asserts `WholeDisk == true`, and sets
  `image_size_mib = TotalSize // 1MiB`; (2) otherwise `image_size_mib` comes from the
  device vars file or `-e`; (3) neither -> the final assert fails. The playbook never
  writes the device in any path.
- The size assert requires `image_size_mib >= 2`, and the NextUI profile adds a
  `>= 1024` MiB guard. Pass `-e image_device=` to force the explicit size instead of a
  device read.
- `remote_archives` are cached under `cache_dir` (default `build/cache`):
  `ansible.builtin.get_url` with `checksum: "sha256:<pin>"`, `force: false`, and
  `timeout: 600`, then `stat` before and after download to assert the cached checksum.
  A mismatch names the file and says to delete it from `cache_dir`.
  `ansible.builtin.unarchive` with `remote_src: true` extracts them into
  `payload_dir/<dest>`. The Grout entry additionally extracts into `Grout.pak` and
  chmods `launch.sh` and `grout` to 0755. The whole archive block is guarded by
  `remote_archives | length > 0`, so the Cannoli profile (empty list) is unaffected.
- Remote assets use `ansible.builtin.get_url` with `force: no` against
  `https://github.com/<repo>/releases/download/<tag>/<asset>` (the 302 to
  objects.githubusercontent.com is followed). Exact tag only; no mutable selectors.
  If redirect/403 failures appear, switch ONLY that task to `ansible.builtin.uri` with
  `follow_redirects: all`.
- `--tags payload` stages the tree without invoking the container; a full run stages
  and builds. `payload_dir`/`dist_dir`/`image_output`/`cache_dir` are `-e` overridable and
  the tests use temp dirs to keep `build/`, `dist/`, and cached archives untouched.

### Cannoli contract conventions
Cannoli is pinned at **v1.9.1**, commit `7755e376b6add0bbd25ea19104c368b7a40b979f`.
`ansible/vars/cannoli.yml` is the runtime source of truth for the directory contract:
17 `cannoli_base_dirs` (Cannoli root + 15 Cannoli dirs + `APKs`), 51 `cannoli_tags`
(each staged as `Cannoli/Roms/<TAG>`), and the `cannoli_settings_marker` file. The staged
tree is 70 directories total: 17 + 51 + the implicit `Cannoli/Media` parent (of the two
declared `Media/*` dirs) + `Obtainium` (destination of device `local_files`). There is no
network access at runtime. To refresh the contract, update the pinned upstream
`platforms.json` data into `cannoli_tags`, `docs/cannoli-platform-tags.md`, and the test
expectations (`tests/ansible-payload.sh` counts)
together in one change. The old pipeline's `CREDITS.md` emission is gone; no payload
builds it.

### NextUI contract conventions
NextUI is pinned at **v6.15.0**, asset `NextUI-20261013-0-all.zip`, SHA-256
`d5edceaa92d0264f34da87f017a40fb8244dc3081f894f17c6979ffe94c4c38a`; it extracts to the
card root. Grout is pinned at **v5.4.0.0**, asset `Grout.pak.zip`, SHA-256
`eb5ffa37aca0d484e1c8c16f16c8cf4e7a74f798d5a023ea907f99d6cea45328`, and extracts to
`Tools/tg5040/Grout.pak` (`tg5040` covers the Brick, Brick Pro, and Smart Pro; the Smart
Pro S is `tg5050` and out of scope). The `-all` card root has 15 top-level entries; there
is no `em_ui.sh`, and `MinUI.zip` must stay zipped for the first-boot installer. Do not
extract it in the playbook. The first boot removes `MinUI.zip`, the `.pakz` files, and
`trimui/`, then creates `.system/`, `.tmp_update/`, and `.userdata/`; that device-side
change is expected and is not a host block-device write. No Grout `config.json`, server
URL, or token is ever pre-seeded. NextUI is PolyForm Noncommercial 1.0.0 and Grout is
MIT; both are downloaded at build time, never vendored, and the resulting image is for
personal noncommercial use. Keep those credits in `README.md` when refreshing pins.

### Task commands
Run `task <name>` from the repository root. Target names are `setup`, `lint`,
`validate`, `image`, `container`, `test`, and `ci`; the canonical commands they wrap are:
- `setup` - `uv sync --all-groups` and install pre-commit hooks
- `container` - `docker build -t sbc-imager-builder:local .`
- `image` - `uv run ansible-playbook ansible/build.yml -e device=<DEVICE>` (the full
  staged build; `--tags payload` collects the payload only). `DEVICE`, `SIZE_MIB`, and
  `IMAGE_DEVICE` are optional Task variables; when set, `SIZE_MIB`/`IMAGE_DEVICE` are
  passed through and the device vars decide otherwise.
- `lint` - `shellcheck container/build-image.sh tests/*.sh` and
  `uv run ansible-lint ansible/`
- `validate` - syntax-check the playbook for `rg477m` and `trimui-brick`
- `test` - the shell test suite (Cannoli, NextUI, and smoke)
- `ci` - the local gate (lint + validate + test)

The raw ansible-playbook commands are the verified interface; keep any Taskfile
wrapper a thin alias for them. CI (`.github/workflows/ci.yml`) installs `shellcheck` and
`unzip` before invoking the same Task targets, so local and CI runs match.

### Testing strategy
Write tests first. The suite is shell scripts in `tests/`:
- `tests/ansible-payload.sh` - runs the payload playbook into a temp dir and asserts the
  contract: exactly 3 top-level entries (`APKs`, `Cannoli`, `Obtainium`), 17/17 base dirs,
  51/51 Roms tags, 70 directories total, the 3-byte `"{}\n"` settings marker, the 3 pinned
  payload files with exact byte sizes (and prints their SHA-256), and no `CREDITS.md`.
  Includes failure injection against a copy of the tree.
- `tests/ansible-payload-nextui.sh` - runs the NextUI profile with temp
  payload/dist/cache dirs and asserts the card contract: the 15 top-level entries, a
  valid zipped `MinUI.zip`, no extracted `.system`, `trimui/app/...`, `h700/`, and
  `Tools/tg5040/Grout.pak` with executable `grout`/`launch.sh`, `pak.json` version and
  platform, and no Cannoli/APKs/Obtainium. It then builds a real exFAT image, checks
  size/MBR/mount contents, and injects missing-payload and corrupt-cache failures. The
  local host and CI both need `unzip`; no test writes a block device.
- `tests/smoke-image.sh` - offline 66 MiB tree-to-image smoke of the builder with a
  placeholder-byte fixture: exact image size, MBR start=2048/type=7, `fsck.exfat -n`
  clean, mounted content assertions, loop-device leak check, and invalid-input failure
  cases. All mounts run inside disposable privileged containers.
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
