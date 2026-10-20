#!/usr/bin/env bash
# Parity gate for the Ansible builder pivot (IS-8, plan Todo 9).
#
# Builds the SAME 128MiB RG477M card image with the OLD Python pipeline and
# the NEW Ansible pipeline, then proves the two images are identical except
# for CREDITS.md (which only the OLD pipeline writes):
#
#   OLD: uv run sbc-imager build --manifest examples/rg477m/rg477m.toml \
#        --size 128MiB --output "$work/old-rg477m.img"
#   NEW: uv run ansible-playbook ansible/build.yml -e device=rg477m \
#        -e image_device= -e image_size_mib=128 \
#        -e image_output="$work/new-rg477m.img" \
#        -e payload_dir="$work/new-payload" -e dist_dir="$work"
#
# Checks, in order:
#   1. both images are regular files of exactly 128 * 1048576 bytes
#   2. both MBRs show start=2048 and type=7 (sfdisk -d in a container)
#   3. normalized relative directory listings are identical and hold the
#      full contract: 70 dirs = 17 base dirs + 51 Cannoli/Roms/<tag> dirs +
#      implicit Cannoli/Media + Obtainium
#   4. normalized "<sha256>  <relative-path>" file listings are identical,
#      EXCLUDING CREDITS.md (4 files each)
#   5. the 3 payload files carry the pinned sizes and SHA-256 values and
#      settings.json is exactly "{}\n" on BOTH images
#   6. fsck.exfat -n exits 0 on both partitions
#   7. CREDITS.md exists in the OLD image only (intentional difference)
#   8. failure injection: appending one byte to a copy of the new image
#      makes the listing comparison fail non-zero
#
# Mounts happen only inside disposable privileged containers, read-only except
# for the failure-injection copy, and every container snippet detaches its
# loop device in a trap. No block device is ever written. Evidence is appended
# to .omo/evidence/ansible-pivot/parity/parity.log (gitignored).
#
# usage: tests/parity-rg477m.sh

set -euo pipefail

IMAGE=sbc-imager-builder:local
ASSEMBLER_IMAGE=sbc-imager-assembler:local
SIZE_MIB=128
MIB=1048576
TOTAL_BYTES=$((SIZE_MIB * MIB))
OFFSET_BYTES=$MIB
PART_BYTES=$((TOTAL_BYTES - OFFSET_BYTES))

# Pinned payload contract; mirrors tests/unit/test_examples.py and
# examples/rg477m/README.md.
APK_PATH=APKs/Obtainium.apk
PACK_PATH=Obtainium/obtainium-emulation-pack-v8.0.1.json
TAILSCALE_PATH=Obtainium/tailscale.json
SETTINGS_PATH=Cannoli/Config/settings.json
APK_SIZE=27194505
PACK_SIZE=78201
TAILSCALE_SIZE=383
APK_SHA=04dfd02c56dae8d5271d2d402977e1b07c8eeffb313df054a13e71b75b8b8a26
PACK_SHA=c2170687b07881f5891fe9751903c13c31b80de506bd41b718f99abb45592169
TAILSCALE_SHA=965cb8f0afb48f7dfee57099ccaa43f00c9ef50e16c50fd4a90f1cab0286fcd4
SETTINGS_SHA=ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356
EXPECTED_DIRS=70
EXPECTED_ROMS=51
EXPECTED_FILES=4

# The 17 declared base directories (ansible/vars/cannoli.yml), relative to the
# card root: Cannoli root (1) + 15 top-level Cannoli directories + APKs (1).
BASE_DIRS=(
    APKs
    Cannoli
    Cannoli/Art
    Cannoli/BIOS
    Cannoli/Backup
    Cannoli/Cheats
    Cannoli/Config
    Cannoli/Guides
    Cannoli/Logs
    Cannoli/Media/Screenshots
    Cannoli/Media/Recordings
    Cannoli/Overlays
    Cannoli/Roms
    "Cannoli/Save States"
    Cannoli/Saves
    Cannoli/Shaders
    Cannoli/Wallpapers
)

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(dirname -- "$script_dir")
evidence_dir=${EVIDENCE_DIR:-"$repo_root/.omo/evidence/ansible-pivot/parity"}
evidence_file="$evidence_dir/parity.log"

mkdir -p -- "$evidence_dir"
: >"$evidence_file"

work=""
cleanup() {
    local rc=$?
    trap - EXIT INT TERM
    if [ -n "$work" ] && [ -d "$work" ]; then
        rm -rf -- "$work"
    fi
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

log() {
    printf '%s\n' "$*" | tee -a "$evidence_file"
}

emit() {
    printf '%s\n' "$1" | tee -a "$evidence_file"
}

record() {
    printf '%s\n' "$1" >>"$evidence_file"
}

section() {
    log ""
    log "=== $* ==="
}

fail() {
    log "FAIL: $*"
    exit 1
}

show_cmd() {
    log "+ $(printf '%q ' "$@")"
}

# Same as show_cmd/record but evidence-only: used inside functions whose
# stdout is captured by the caller and must stay pure.
record_cmd() {
    printf '+ %s\n' "$(printf '%q ' "$@")" >>"$evidence_file"
}

section "environment"
log "date: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
log "repo: $repo_root"
log "evidence: $evidence_file"
log "size_mib: $SIZE_MIB"
log "total_bytes: $TOTAL_BYTES"
log "part_bytes: $PART_BYTES"
log "builder image: $IMAGE"
log "expected dirs: $EXPECTED_DIRS (17 base + 51 Roms tags + Cannoli/Media + Obtainium)"
log "expected files per listing: $EXPECTED_FILES (CREDITS.md excluded)"
log "expected APK: $APK_SIZE bytes sha256=$APK_SHA"
log "expected pack: $PACK_SIZE bytes sha256=$PACK_SHA"
log "expected tailscale: $TAILSCALE_SIZE bytes sha256=$TAILSCALE_SHA"
log "expected settings.json: 3 bytes sha256=$SETTINGS_SHA"

# Docker Desktop's image store occasionally answers "No such image" for a
# tag that exists (a transient daemon sync issue), so inspect is retried a
# few times before giving up.
image_present() {
    local image=$1
    local attempt
    for attempt in 1 2 3; do
        if docker image inspect "$image" >/dev/null 2>&1; then
            return 0
        fi
        log "image inspect attempt $attempt failed for $image; retrying in 2s"
        sleep 2
    done
    return 1
}

section "preflight"
command -v docker >/dev/null 2>&1 || fail "docker is required but not on PATH"
command -v uv >/dev/null 2>&1 || fail "uv is required but not on PATH"
image_present "$IMAGE" ||
    fail "builder image $IMAGE is missing; build it first (do not rebuild blind)"
if image_present "$ASSEMBLER_IMAGE"; then
    log "assembler image present: $ASSEMBLER_IMAGE"
else
    log "assembler image absent: $ASSEMBLER_IMAGE (the OLD pipeline builds it on demand)"
fi
log "sbc-imager version: $(uv run sbc-imager --version)"
log "ansible-playbook version: $(uv run ansible-playbook --version | head -n 1)"

work=$(mktemp -d "${TMPDIR:-/tmp}/parity-rg477m.XXXXXX")
old_img="$work/old-rg477m.img"
new_img="$work/new-rg477m.img"
tampered_img="$work/tampered-rg477m.img"
log "work dir: $work"

cd "$repo_root"

# ---------------------------------------------------------------------------
section "OLD pipeline build (Python sbc-imager)"
old_cmd=(uv run sbc-imager build
    --manifest examples/rg477m/rg477m.toml
    --size 128MiB
    --output "$old_img")
show_cmd "${old_cmd[@]}"
old_rc=0
old_out=$("${old_cmd[@]}" 2>&1) || old_rc=$?
emit "$old_out"
log "OLD build exit code: $old_rc"
[ "$old_rc" -eq 0 ] || fail "OLD pipeline build exited $old_rc (see log above)"

# ---------------------------------------------------------------------------
section "NEW pipeline build (Ansible + container builder)"
new_cmd=(uv run ansible-playbook ansible/build.yml
    -e device=rg477m
    -e image_device=
    -e image_size_mib=128
    -e "image_output=$new_img"
    -e "payload_dir=$work/new-payload"
    -e "dist_dir=$work")
show_cmd "${new_cmd[@]}"
new_rc=0
new_out=$("${new_cmd[@]}" 2>&1) || new_rc=$?
emit "$new_out"
log "NEW build exit code: $new_rc"
[ "$new_rc" -eq 0 ] || fail "NEW pipeline build exited $new_rc (see log above)"

# ---------------------------------------------------------------------------
section "image file assertions"
[ -e "$old_img" ] || fail "OLD output image does not exist: $old_img"
[ -e "$new_img" ] || fail "NEW output image does not exist: $new_img"
[ -f "$old_img" ] || fail "OLD output is not a regular file: $old_img"
[ -f "$new_img" ] || fail "NEW output is not a regular file: $new_img"
[ ! -e "$new_img.partial" ] || fail "NEW builder left a partial file: $new_img.partial"
old_size=$(wc -c <"$old_img" | tr -d '[:space:]')
new_size=$(wc -c <"$new_img" | tr -d '[:space:]')
log "OLD image bytes: $old_size"
log "NEW image bytes: $new_size"
[ "$old_size" -eq "$TOTAL_BYTES" ] ||
    fail "OLD image size $old_size != $TOTAL_BYTES"
[ "$new_size" -eq "$TOTAL_BYTES" ] ||
    fail "NEW image size $new_size != $TOTAL_BYTES"

# ---------------------------------------------------------------------------
# MBR assertions: partition must start at LBA 2048 with type 7 (exFAT).
check_mbr() {
    local img_path=$1
    local img_name rc=0 out cmd
    img_name=$(basename -- "$img_path")
    cmd=(docker run --rm --privileged
        -v "$work:/out"
        --entrypoint sfdisk
        "$IMAGE" -d "/out/$img_name")
    show_cmd "${cmd[@]}"
    out=$("${cmd[@]}" 2>&1) || rc=$?
    emit "$out"
    log "sfdisk -d exit code: $rc"
    [ "$rc" -eq 0 ] || fail "sfdisk -d failed for $img_name (exit $rc)"
    grep -Eq 'start=[[:space:]]*2048([[:space:],]|$)' <<<"$out" ||
        fail "MBR partition does not start at LBA 2048: $img_name"
    grep -Eq '(Id=|type=)[[:space:]]*7([[:space:],]|$)' <<<"$out" ||
        fail "MBR partition is not type 7 (exFAT): $img_name"
    log "MBR OK for $img_name: start=2048, type=7"
}

section "MBR assertions (sfdisk -d)"
check_mbr "$old_img"
check_mbr "$new_img"

# ---------------------------------------------------------------------------
# fsck.exfat -n on the partition (offset 1MiB, size = image - 1MiB).
check_fsck() {
    local img_path=$1
    local img_name rc=0 out cmd
    img_name=$(basename -- "$img_path")
    # shellcheck disable=SC2016
    cmd=(docker run --rm --privileged
        -v "$work:/out"
        -e "OFFSET_BYTES=$OFFSET_BYTES"
        -e "PART_BYTES=$PART_BYTES"
        -e "IMAGE_NAME=$img_name"
        --entrypoint sh
        "$IMAGE" -c 'set -eu
loop=""
cleanup_fsck() {
    rc=$?
    trap - EXIT INT TERM
    if [ -n "$loop" ]; then
        losetup -d "$loop" >/dev/null 2>&1 || true
    fi
    exit "$rc"
}
trap cleanup_fsck EXIT INT TERM
loop=$(losetup --find --show --offset "$OFFSET_BYTES" --sizelimit "$PART_BYTES" "/out/$IMAGE_NAME")
fsck.exfat -n "$loop"')
    show_cmd "${cmd[@]}"
    out=$("${cmd[@]}" 2>&1) || rc=$?
    emit "$out"
    log "fsck.exfat -n exit code: $rc"
    [ "$rc" -eq 0 ] || fail "fsck.exfat -n failed for $img_name (exit $rc)"
    log "fsck OK for $img_name"
}

section "filesystem assertions (fsck.exfat -n)"
check_fsck "$old_img"
check_fsck "$new_img"

# ---------------------------------------------------------------------------
# Normalized listings. file_listing mounts the partition read-only and emits
# "<sha256>  <relative-path>" for every file EXCLUDING CREDITS.md, sorted.
file_listing() {
    local img_path=$1
    local img_name rc=0 out cmd
    img_name=$(basename -- "$img_path")
    # shellcheck disable=SC2016
    cmd=(docker run --rm --privileged
        -v "$work:/out"
        -e "OFFSET_BYTES=$OFFSET_BYTES"
        -e "PART_BYTES=$PART_BYTES"
        -e "IMAGE_NAME=$img_name"
        --entrypoint sh
        "$IMAGE" -c 'set -eu
loop=""
mnt=""
cleanup_list() {
    rc=$?
    trap - EXIT INT TERM
    if [ -n "$mnt" ] && mountpoint -q "$mnt" 2>/dev/null; then
        umount "$mnt" >/dev/null 2>&1 || umount -l "$mnt" >/dev/null 2>&1 || true
    fi
    if [ -n "$loop" ]; then
        losetup -d "$loop" >/dev/null 2>&1 || true
    fi
    if [ -n "$mnt" ] && [ -d "$mnt" ]; then
        rmdir "$mnt" >/dev/null 2>&1 || true
    fi
    exit "$rc"
}
trap cleanup_list EXIT INT TERM
loop=$(losetup --find --show --offset "$OFFSET_BYTES" --sizelimit "$PART_BYTES" "/out/$IMAGE_NAME")
mnt=$(mktemp -d)
mount -t exfat -o ro "$loop" "$mnt"
(cd "$mnt" && find . -type f ! -path "./CREDITS.md" -print | LC_ALL=C sort | xargs sha256sum | LC_ALL=C sort -k2)')
    record_cmd "${cmd[@]}"
    out=$("${cmd[@]}" 2>&1) || rc=$?
    record "$out"
    [ "$rc" -eq 0 ] || fail "file listing failed for $img_name (exit $rc)"
    printf '%s\n' "$out"
}

dir_listing() {
    local img_path=$1
    local img_name rc=0 out cmd
    img_name=$(basename -- "$img_path")
    # shellcheck disable=SC2016
    cmd=(docker run --rm --privileged
        -v "$work:/out"
        -e "OFFSET_BYTES=$OFFSET_BYTES"
        -e "PART_BYTES=$PART_BYTES"
        -e "IMAGE_NAME=$img_name"
        --entrypoint sh
        "$IMAGE" -c 'set -eu
loop=""
mnt=""
cleanup_list() {
    rc=$?
    trap - EXIT INT TERM
    if [ -n "$mnt" ] && mountpoint -q "$mnt" 2>/dev/null; then
        umount "$mnt" >/dev/null 2>&1 || umount -l "$mnt" >/dev/null 2>&1 || true
    fi
    if [ -n "$loop" ]; then
        losetup -d "$loop" >/dev/null 2>&1 || true
    fi
    if [ -n "$mnt" ] && [ -d "$mnt" ]; then
        rmdir "$mnt" >/dev/null 2>&1 || true
    fi
    exit "$rc"
}
trap cleanup_list EXIT INT TERM
loop=$(losetup --find --show --offset "$OFFSET_BYTES" --sizelimit "$PART_BYTES" "/out/$IMAGE_NAME")
mnt=$(mktemp -d)
mount -t exfat -o ro "$loop" "$mnt"
(cd "$mnt" && find . -mindepth 1 -type d -print | LC_ALL=C sort)')
    record_cmd "${cmd[@]}"
    out=$("${cmd[@]}" 2>&1) || rc=$?
    record "$out"
    [ "$rc" -eq 0 ] || fail "directory listing failed for $img_name (exit $rc)"
    printf '%s\n' "$out"
}

section "file listings (sha256, CREDITS.md excluded)"
file_listing "$old_img" >"$work/old.files"
file_listing "$new_img" >"$work/new.files"

old_files_n=$(wc -l <"$work/old.files" | tr -d '[:space:]')
new_files_n=$(wc -l <"$work/new.files" | tr -d '[:space:]')
log "OLD file count (excluding CREDITS.md): $old_files_n"
log "NEW file count (excluding CREDITS.md): $new_files_n"
[ "$old_files_n" -eq "$EXPECTED_FILES" ] ||
    fail "OLD listing has $old_files_n files, want $EXPECTED_FILES"
[ "$new_files_n" -eq "$EXPECTED_FILES" ] ||
    fail "NEW listing has $new_files_n files, want $EXPECTED_FILES"

if happy_diff=$(diff -u -- "$work/old.files" "$work/new.files" 2>&1); then
    log "PASS: OLD and NEW file listings are identical ($old_files_n files)"
else
    record "$happy_diff"
    fail "file listings differ between OLD and NEW images"
fi

section "directory listings"
dir_listing "$old_img" >"$work/old.dirs"
dir_listing "$new_img" >"$work/new.dirs"

old_dirs_n=$(wc -l <"$work/old.dirs" | tr -d '[:space:]')
new_dirs_n=$(wc -l <"$work/new.dirs" | tr -d '[:space:]')
log "OLD directory count: $old_dirs_n"
log "NEW directory count: $new_dirs_n"
[ "$old_dirs_n" -eq "$EXPECTED_DIRS" ] ||
    fail "OLD image has $old_dirs_n dirs, want $EXPECTED_DIRS"
[ "$new_dirs_n" -eq "$EXPECTED_DIRS" ] ||
    fail "NEW image has $new_dirs_n dirs, want $EXPECTED_DIRS"

if happy_ddir=$(diff -u -- "$work/old.dirs" "$work/new.dirs" 2>&1); then
    log "PASS: OLD and NEW directory listings are identical ($old_dirs_n dirs)"
else
    record "$happy_ddir"
    fail "directory listings differ between OLD and NEW images"
fi

missing=0
for entry in "${BASE_DIRS[@]}"; do
    grep -Fqx "./$entry" "$work/old.dirs" ||
        { log "FAIL: OLD image missing base dir ./$entry"; missing=$((missing + 1)); }
    grep -Fqx "./$entry" "$work/new.dirs" ||
        { log "FAIL: NEW image missing base dir ./$entry"; missing=$((missing + 1)); }
done
[ "$missing" -eq 0 ] ||
    fail "missing $missing base directory entries (see log above)"
log "PASS: all ${#BASE_DIRS[@]} base dirs present in both images"

old_roms=$(grep -cE '^\./Cannoli/Roms/[^/]+$' "$work/old.dirs" || true)
new_roms=$(grep -cE '^\./Cannoli/Roms/[^/]+$' "$work/new.dirs" || true)
log "OLD Cannoli/Roms/<tag> dirs: $old_roms"
log "NEW Cannoli/Roms/<tag> dirs: $new_roms"
[ "$old_roms" -eq "$EXPECTED_ROMS" ] ||
    fail "OLD image has $old_roms Roms tags, want $EXPECTED_ROMS"
[ "$new_roms" -eq "$EXPECTED_ROMS" ] ||
    fail "NEW image has $new_roms Roms tags, want $EXPECTED_ROMS"

# Pinned hashes on the NEW image (the OLD image is identical by the diff above).
grep -Fqx "$APK_SHA  ./$APK_PATH" "$work/new.files" ||
    fail "NEW image APK hash mismatch for ./$APK_PATH"
grep -Fqx "$PACK_SHA  ./$PACK_PATH" "$work/new.files" ||
    fail "NEW image pack hash mismatch for ./$PACK_PATH"
grep -Fqx "$TAILSCALE_SHA  ./$TAILSCALE_PATH" "$work/new.files" ||
    fail "NEW image tailscale hash mismatch for ./$TAILSCALE_PATH"
grep -Fqx "$SETTINGS_SHA  ./$SETTINGS_PATH" "$work/new.files" ||
    fail "NEW image settings marker hash mismatch for ./$SETTINGS_PATH"
log "PASS: pinned SHA-256 values hold on the NEW image"

# ---------------------------------------------------------------------------
# Mounted assertions: exact payload sizes, settings content, CREDITS.md.
mount_asserts() {
    local img_path=$1
    local tag=$2
    local img_name rc=0 out cmd
    img_name=$(basename -- "$img_path")
    # shellcheck disable=SC2016
    cmd=(docker run --rm --privileged
        -v "$work:/out"
        -e "OFFSET_BYTES=$OFFSET_BYTES"
        -e "PART_BYTES=$PART_BYTES"
        -e "IMAGE_NAME=$img_name"
        -e "TAG=$tag"
        --entrypoint sh
        "$IMAGE" -c 'set -eu
loop=""
mnt=""
cleanup_asserts() {
    rc=$?
    trap - EXIT INT TERM
    if [ -n "$mnt" ] && mountpoint -q "$mnt" 2>/dev/null; then
        umount "$mnt" >/dev/null 2>&1 || umount -l "$mnt" >/dev/null 2>&1 || true
    fi
    if [ -n "$loop" ]; then
        losetup -d "$loop" >/dev/null 2>&1 || true
    fi
    if [ -n "$mnt" ] && [ -d "$mnt" ]; then
        rmdir "$mnt" >/dev/null 2>&1 || true
    fi
    exit "$rc"
}
trap cleanup_asserts EXIT INT TERM
loop=$(losetup --find --show --offset "$OFFSET_BYTES" --sizelimit "$PART_BYTES" "/out/$IMAGE_NAME")
mnt=$(mktemp -d)
mount -t exfat -o ro "$loop" "$mnt"
wc -c <"$mnt/APKs/Obtainium.apk" | tr -d "[:space:]" >"/out/$TAG.size-apk"
wc -c <"$mnt/Obtainium/obtainium-emulation-pack-v8.0.1.json" | tr -d "[:space:]" >"/out/$TAG.size-pack"
wc -c <"$mnt/Obtainium/tailscale.json" | tr -d "[:space:]" >"/out/$TAG.size-tailscale"
cat "$mnt/Cannoli/Config/settings.json" >"/out/$TAG.settings"
if [ -f "$mnt/CREDITS.md" ]; then
    echo present >"/out/$TAG.credits"
else
    echo absent >"/out/$TAG.credits"
fi')
    show_cmd "${cmd[@]}"
    out=$("${cmd[@]}" 2>&1) || rc=$?
    emit "$out"
    [ "$rc" -eq 0 ] || fail "mounted assertions failed for $img_name (exit $rc)"
}

section "mounted assertions (sizes, settings, CREDITS.md)"
mount_asserts "$old_img" old
mount_asserts "$new_img" new

for tag in old new; do
    apk_got=$(<"$work/$tag.size-apk")
    pack_got=$(<"$work/$tag.size-pack")
    tailscale_got=$(<"$work/$tag.size-tailscale")
    log "$tag image APK bytes: $apk_got (want $APK_SIZE)"
    log "$tag image pack bytes: $pack_got (want $PACK_SIZE)"
    log "$tag image tailscale bytes: $tailscale_got (want $TAILSCALE_SIZE)"
    [ "$apk_got" -eq "$APK_SIZE" ] ||
        fail "$tag image APK is $apk_got bytes, want $APK_SIZE"
    [ "$pack_got" -eq "$PACK_SIZE" ] ||
        fail "$tag image pack is $pack_got bytes, want $PACK_SIZE"
    [ "$tailscale_got" -eq "$TAILSCALE_SIZE" ] ||
        fail "$tag image tailscale is $tailscale_got bytes, want $TAILSCALE_SIZE"
    printf '{}\n' | cmp -s - "$work/$tag.settings" ||
        fail "$tag image settings.json is not exactly {} + newline"
    log "PASS: $tag image payload sizes and settings marker correct"
done

old_credits=$(<"$work/old.credits")
new_credits=$(<"$work/new.credits")
log "CREDITS.md in OLD image: $old_credits"
log "CREDITS.md in NEW image: $new_credits"
[ "$old_credits" = "present" ] || fail "OLD image is missing CREDITS.md"
[ "$new_credits" = "absent" ] || fail "NEW image unexpectedly contains CREDITS.md"
log "NOTE: CREDITS.md present in the OLD image only; this is the one"
log "      intentional, expected difference between the two pipelines."

# ---------------------------------------------------------------------------
section "failure injection (the gate must be able to fail)"
cp -- "$new_img" "$tampered_img"
# shellcheck disable=SC2016
tamper_cmd=(docker run --rm --privileged
    -v "$work:/out"
    -e "OFFSET_BYTES=$OFFSET_BYTES"
    -e "PART_BYTES=$PART_BYTES"
    -e "IMAGE_NAME=tampered-rg477m.img"
    --entrypoint sh
    "$IMAGE" -c 'set -eu
loop=""
mnt=""
cleanup_tamper() {
    rc=$?
    trap - EXIT INT TERM
    if [ -n "$mnt" ] && mountpoint -q "$mnt" 2>/dev/null; then
        umount "$mnt" >/dev/null 2>&1 || umount -l "$mnt" >/dev/null 2>&1 || true
    fi
    if [ -n "$loop" ]; then
        losetup -d "$loop" >/dev/null 2>&1 || true
    fi
    if [ -n "$mnt" ] && [ -d "$mnt" ]; then
        rmdir "$mnt" >/dev/null 2>&1 || true
    fi
    exit "$rc"
}
trap cleanup_tamper EXIT INT TERM
loop=$(losetup --find --show --offset "$OFFSET_BYTES" --sizelimit "$PART_BYTES" "/out/$IMAGE_NAME")
mnt=$(mktemp -d)
mount -t exfat "$loop" "$mnt"
printf "X" >>"$mnt/Cannoli/Config/settings.json"
umount "$mnt"
mnt=""
losetup -d "$loop"
loop=""
echo "appended one byte to Cannoli/Config/settings.json"')
show_cmd "${tamper_cmd[@]}"
tamper_rc=0
tamper_out=$("${tamper_cmd[@]}" 2>&1) || tamper_rc=$?
emit "$tamper_out"
log "tamper exit code: $tamper_rc"
[ "$tamper_rc" -eq 0 ] || fail "tamper container exited $tamper_rc (see log above)"

file_listing "$tampered_img" >"$work/tampered.files"
tamper_diff=""
diff_rc=0
tamper_diff=$(diff -u -- "$work/new.files" "$work/tampered.files" 2>&1) || diff_rc=$?
record "$tamper_diff"
log "tampered vs reference listing diff exit code: $diff_rc (expected non-zero)"
[ "$diff_rc" -ne 0 ] ||
    fail "failure injection: listing comparison returned 0 (the gate cannot fail)"
log "PASS: failure injection detected (comparison helper returned $diff_rc)"

# ---------------------------------------------------------------------------
section "loop and container leak check"
loops_cmd=(docker run --rm --privileged --entrypoint losetup "$IMAGE" -a)
show_cmd "${loops_cmd[@]}"
loops_rc=0
loops_out=$("${loops_cmd[@]}" 2>&1) || loops_rc=$?
emit "$loops_out"
log "losetup -a exit code: $loops_rc"
[ "$loops_rc" -eq 0 ] || fail "losetup -a exited $loops_rc"
if printf '%s\n' "$loops_out" | grep -Eq 'rg477m\.img'; then
    fail "loop device leaked for a parity image"
fi
log "no loop device references any parity image"

leftover=$(docker ps -q --filter "ancestor=$IMAGE" --filter "ancestor=$ASSEMBLER_IMAGE")
if [ -n "$leftover" ]; then
    fail "leftover running containers: $leftover"
fi
log "no leftover containers from $IMAGE or $ASSEMBLER_IMAGE"

section "result"
log "PASS: parity gate holds. OLD and NEW 128MiB RG477M images are identical"
log "      except for CREDITS.md (OLD only): same dirs, same file hashes,"
log "      same MBR (start=2048, type=7), both fsck clean; failure injection"
log "      correctly makes the comparison non-zero."
