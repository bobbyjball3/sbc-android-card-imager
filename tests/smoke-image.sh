#!/usr/bin/env bash
# Offline smoke test for the tree-to-image builder.
#
# Proves that container/build-image.sh, running in the local
# sbc-imager-builder:local image, turns a tiny payload tree into a valid
# sparse MBR + exFAT image:
#   - exactly 66 MiB, regular file, no leftover .partial
#   - MBR partition starts at LBA 2048 and is type 7 (exFAT)
#   - fsck.exfat reports the partition clean
#   - the mounted filesystem has the expected tree and file bytes
#   - the builder detaches its loop device
#   - invalid input exits non-zero
#
# Everything is offline: the payload is generated locally from placeholder
# bytes (no ROMs, no network). Evidence is appended to
# .omo/evidence/ansible-pivot/smoke.log (gitignored).
#
# usage: tests/smoke-image.sh

set -euo pipefail

IMAGE=sbc-imager-builder:local
IMAGE_NAME=smoke-card.img
SIZE_MIB=66
LABEL=CANNOLI
MIB=1048576
TOTAL_BYTES=$((SIZE_MIB * MIB))
OFFSET_BYTES=$MIB
PART_BYTES=$((TOTAL_BYTES - OFFSET_BYTES))
SETTINGS_BYTES=3

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(dirname -- "$script_dir")
evidence_dir=${EVIDENCE_DIR:-"$repo_root/.omo/evidence/ansible-pivot"}
evidence_file="$evidence_dir/smoke.log"

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

section "environment"
log "date: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
log "image: $IMAGE"
log "size_mib: $SIZE_MIB"
log "label: $LABEL"
log "total_bytes: $TOTAL_BYTES"
log "part_bytes: $PART_BYTES"
log "evidence: $evidence_file"

docker image inspect "$IMAGE" >/dev/null 2>&1 ||
    fail "builder image $IMAGE is missing; build it first (do not rebuild blind)"

work=$(mktemp -d "${TMPDIR:-/tmp}/smoke-image.XXXXXX")
payload="$work/payload"
outdir="$work/out"
mkdir -p -- "$payload/Cannoli/Config" \
    "$payload/Cannoli/Roms/GBA" \
    "$payload/APKs" \
    "$outdir"

# Deterministic, tiny, offline fixture. Placeholder bytes only.
printf '{}\n' >"$payload/Cannoli/Config/settings.json"
printf 'placeholder apk payload\n' >"$payload/APKs/Demo.apk"
printf 'placeholder gba rom payload\n' >"$payload/Cannoli/Roms/GBA/demo.gba"

apk_bytes=$(wc -c <"$payload/APKs/Demo.apk" | tr -d '[:space:]')
gba_bytes=$(wc -c <"$payload/Cannoli/Roms/GBA/demo.gba" | tr -d '[:space:]')

section "fixture layout"
log "work dir: $work"
while IFS= read -r dir_path; do
    log "dir  ${dir_path#"$payload"/}"
done < <(find "$payload" -mindepth 1 -type d | sort)
while IFS= read -r file_path; do
    log "file ${file_path#"$payload"/} ($(wc -c <"$file_path" | tr -d '[:space:]') bytes)"
done < <(find "$payload" -type f | sort)
log "expected settings.json bytes: $SETTINGS_BYTES"
log "expected APKs/Demo.apk bytes: $apk_bytes"
log "expected Cannoli/Roms/GBA/demo.gba bytes: $gba_bytes"

image="$outdir/$IMAGE_NAME"

section "build 66MiB image"
build_cmd=(
    docker run --rm --privileged
    -e "HOST_UID=$(id -u)"
    -e "HOST_GID=$(id -g)"
    -v "$payload:/payload:ro"
    -v "$outdir:/out"
    "$IMAGE" "/payload" "/out/$IMAGE_NAME" "$SIZE_MIB" "$LABEL"
)
show_cmd "${build_cmd[@]}"
build_out=""
build_rc=0
build_out=$("${build_cmd[@]}" 2>&1) || build_rc=$?
emit "$build_out"
log "builder exit code: $build_rc"
[ "$build_rc" -eq 0 ] || fail "builder exited $build_rc"

expected_last="Wrote /out/$IMAGE_NAME (${SIZE_MIB}MiB, label $LABEL)"
actual_last=$(printf '%s\n' "$build_out" | tail -n 1)
[ "$actual_last" = "$expected_last" ] ||
    fail "unexpected final builder line: $actual_last (want: $expected_last)"
log "builder final line OK: $actual_last"

section "image file assertions"
[ -e "$image" ] || fail "output image does not exist: $image"
[ -f "$image" ] || fail "output is not a regular file: $image"
[ ! -e "$image.partial" ] || fail "leftover partial file: $image.partial"
image_size=$(wc -c <"$image" | tr -d '[:space:]')
log "image size bytes: $image_size"
[ "$image_size" -eq "$TOTAL_BYTES" ] ||
    fail "image size $image_size != $TOTAL_BYTES"

section "MBR assertions (sfdisk -d)"
sfdisk_cmd=(
    docker run --rm --privileged
    -v "$outdir:/out"
    --entrypoint sfdisk
    "$IMAGE" -d "/out/$IMAGE_NAME"
)
show_cmd "${sfdisk_cmd[@]}"
sfdisk_rc=0
sfdisk_out=$("${sfdisk_cmd[@]}" 2>&1) || sfdisk_rc=$?
emit "$sfdisk_out"
log "sfdisk exit code: $sfdisk_rc"
[ "$sfdisk_rc" -eq 0 ] || fail "sfdisk exited $sfdisk_rc"
printf '%s\n' "$sfdisk_out" | grep -Eq 'start=[[:space:]]*2048([[:space:],]|$)' ||
    fail "MBR partition does not start at LBA 2048"
printf '%s\n' "$sfdisk_out" | grep -Eq '(Id=|type=)[[:space:]]*7([[:space:],]|$)' ||
    fail "MBR partition is not type 7 (exFAT)"
log "MBR OK: start=2048, type=7"

section "filesystem assertions (fsck.exfat -n)"
# The single-quoted container snippet uses shell variables expanded inside
# the container, not by this script.
# shellcheck disable=SC2016
fsck_cmd=(
    docker run --rm --privileged
    -v "$outdir:/out"
    -e "OFFSET_BYTES=$OFFSET_BYTES"
    -e "PART_BYTES=$PART_BYTES"
    -e "IMAGE_NAME=$IMAGE_NAME"
    --entrypoint sh
    "$IMAGE" -c 'set -eu
loop=""
cleanup_loop() {
    rc=$?
    trap - EXIT INT TERM
    if [ -n "$loop" ]; then
        losetup -d "$loop" >/dev/null 2>&1 || true
    fi
    exit "$rc"
}
trap cleanup_loop EXIT INT TERM
loop=$(losetup --find --show --offset "$OFFSET_BYTES" --sizelimit "$PART_BYTES" "/out/$IMAGE_NAME")
fsck.exfat -n "$loop"'
)
show_cmd "${fsck_cmd[@]}"
fsck_rc=0
fsck_out=$("${fsck_cmd[@]}" 2>&1) || fsck_rc=$?
emit "$fsck_out"
log "fsck exit code: $fsck_rc"
[ "$fsck_rc" -eq 0 ] || fail "fsck.exfat exited $fsck_rc"
printf '%s\n' "$fsck_out" | grep -qi 'clean' ||
    fail "fsck.exfat did not report the filesystem clean"
log "fsck OK: filesystem clean"

section "mounted content assertions"
# shellcheck disable=SC2016
mount_cmd=(
    docker run --rm --privileged
    -v "$outdir:/out"
    -e "OFFSET_BYTES=$OFFSET_BYTES"
    -e "PART_BYTES=$PART_BYTES"
    -e "IMAGE_NAME=$IMAGE_NAME"
    -e "SETTINGS_BYTES=$SETTINGS_BYTES"
    -e "APK_BYTES=$apk_bytes"
    -e "GBA_BYTES=$gba_bytes"
    --entrypoint sh
    "$IMAGE" -c 'set -eu
loop=""
mnt=""
fail() {
    echo "MISMATCH: $*" >&2
    exit 1
}
cleanup_mount() {
    rc=$?
    trap - EXIT INT TERM
    if [ -n "$mnt" ] && mountpoint -q "$mnt"; then
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
trap cleanup_mount EXIT INT TERM
loop=$(losetup --find --show --offset "$OFFSET_BYTES" --sizelimit "$PART_BYTES" "/out/$IMAGE_NAME")
mnt=$(mktemp -d)
mount -t exfat -o ro "$loop" "$mnt"
root="$mnt"

[ -d "$root/Cannoli" ] || fail "Cannoli directory missing"
[ -d "$root/Cannoli/Config" ] || fail "Cannoli/Config missing"
[ -d "$root/Cannoli/Roms" ] || fail "Cannoli/Roms missing"
[ -d "$root/Cannoli/Roms/GBA" ] || fail "Cannoli/Roms/GBA missing"
[ -d "$root/APKs" ] || fail "APKs directory missing"
[ -f "$root/Cannoli/Config/settings.json" ] || fail "settings.json missing"
[ -f "$root/APKs/Demo.apk" ] || fail "Demo.apk missing"
[ -f "$root/Cannoli/Roms/GBA/demo.gba" ] || fail "demo.gba missing"

settings_bytes=$(wc -c <"$root/Cannoli/Config/settings.json" | tr -d "[:space:]")
[ "$settings_bytes" -eq "$SETTINGS_BYTES" ] || fail "settings.json is $settings_bytes bytes, want $SETTINGS_BYTES"
[ "$(cat "$root/Cannoli/Config/settings.json")" = "{}" ] || fail "settings.json content is not {}\\n"
apk_bytes_actual=$(wc -c <"$root/APKs/Demo.apk" | tr -d "[:space:]")
[ "$apk_bytes_actual" -eq "$APK_BYTES" ] || fail "Demo.apk is $apk_bytes_actual bytes, want $APK_BYTES"
gba_bytes_actual=$(wc -c <"$root/Cannoli/Roms/GBA/demo.gba" | tr -d "[:space:]")
[ "$gba_bytes_actual" -eq "$GBA_BYTES" ] || fail "demo.gba is $gba_bytes_actual bytes, want $GBA_BYTES"

echo "mounted tree (type size path):"
(cd "$root" && find . -mindepth 1 -printf "%y %s %p\n" | sort)
echo "settings.json bytes: $settings_bytes"
echo "Demo.apk bytes: $apk_bytes_actual"
echo "demo.gba bytes: $gba_bytes_actual"
echo "MOUNT-CONTENT-OK"'
)
show_cmd "${mount_cmd[@]}"
mount_rc=0
mount_out=$("${mount_cmd[@]}" 2>&1) || mount_rc=$?
emit "$mount_out"
log "mount check exit code: $mount_rc"
[ "$mount_rc" -eq 0 ] || fail "mounted content check exited $mount_rc"
printf '%s\n' "$mount_out" | grep -q 'MOUNT-CONTENT-OK' ||
    fail "mounted content check did not complete"
log "mount content OK"

section "loop leak check"
loops_cmd=(
    docker run --rm --privileged
    --entrypoint losetup
    "$IMAGE" -a
)
show_cmd "${loops_cmd[@]}"
loops_rc=0
loops_out=$("${loops_cmd[@]}" 2>&1) || loops_rc=$?
emit "$loops_out"
log "losetup -a exit code: $loops_rc"
[ "$loops_rc" -eq 0 ] || fail "losetup -a exited $loops_rc"
if printf '%s\n' "$loops_out" | grep -F "$IMAGE_NAME" >/dev/null; then
    fail "loop device leaked for $IMAGE_NAME"
fi
log "no loop device references $IMAGE_NAME"

section "failure cases (must exit non-zero)"
fail_outdir="$work/out-fail"
mkdir -p -- "$fail_outdir"

missing_cmd=(
    docker run --rm --privileged
    -e "HOST_UID=$(id -u)"
    -e "HOST_GID=$(id -g)"
    -v "$fail_outdir:/out"
    "$IMAGE" /payload-does-not-exist "/out/fail.img" 2 CANNOLI
)
show_cmd "${missing_cmd[@]}"
missing_rc=0
missing_out=$("${missing_cmd[@]}" 2>&1) || missing_rc=$?
emit "$missing_out"
log "missing-payload exit code: $missing_rc"
[ "$missing_rc" -ne 0 ] || fail "builder accepted a missing payload directory"
missing_line=$(printf '%s\n' "$missing_out" | tail -n 1)
log "missing-payload error: $missing_line"
[ ! -e "$fail_outdir/fail.img" ] || fail "builder created an image for a missing payload"

ext_cmd=(
    docker run --rm --privileged
    -e "HOST_UID=$(id -u)"
    -e "HOST_GID=$(id -g)"
    -v "$payload:/payload:ro"
    -v "$fail_outdir:/out"
    "$IMAGE" /payload /out/fail.raw 2 CANNOLI
)
show_cmd "${ext_cmd[@]}"
ext_rc=0
ext_out=$("${ext_cmd[@]}" 2>&1) || ext_rc=$?
emit "$ext_out"
log "bad-extension exit code: $ext_rc"
[ "$ext_rc" -ne 0 ] || fail "builder accepted a non-.img output path"
ext_line=$(printf '%s\n' "$ext_out" | tail -n 1)
log "bad-extension error: $ext_line"

section "result"
log "PASS: 66MiB tree-to-image build, MBR, fsck, mount content, loop cleanup, failures"
