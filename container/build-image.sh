#!/usr/bin/env bash
# Build a sparse MBR + exFAT card image from a payload tree.
#
# usage: build-image <payload> <out> <size_mib> <label>
#
# A dumb tree-to-image converter: it never touches a block device, refuses
# any output path under /dev/, assembles the image into <out>.partial next
# to the final path, and atomically renames it into place only after the
# partition passes `fsck.exfat -n`. Exit codes of rsync/mkfs/fsck are the
# only success checks.

set -euo pipefail

usage() {
    printf 'usage: build-image <payload> <out> <size_mib> <label>\n' >&2
}

die() {
    printf 'build-image: error: %s\n' "$*" >&2
    exit 1
}

# --- state tracked for trap cleanup ----------------------------------------
partial=""
loop=""
mnt=""
mounted=0

cleanup() {
    local rc=$?
    trap - EXIT INT TERM
    if [ "$mounted" -eq 1 ] && [ -n "$mnt" ]; then
        umount "$mnt" >/dev/null 2>&1 || umount -l "$mnt" >/dev/null 2>&1 || true
        mounted=0
    fi
    if [ -n "$loop" ]; then
        losetup -d "$loop" >/dev/null 2>&1 || true
        loop=""
    fi
    if [ -n "$mnt" ]; then
        rmdir "$mnt" >/dev/null 2>&1 || true
        mnt=""
    fi
    if [ -n "$partial" ]; then
        rm -f -- "$partial"
    fi
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [ "$#" -ne 4 ]; then
    usage
    exit 2
fi

payload=$1
out=$2
size_mib=$3
label=$4

# --- validation -------------------------------------------------------------
[ -d "$payload" ] || die "payload directory does not exist: $payload"

case "$out" in
    /dev/* | //dev/*)
        die "refusing to write to a device path: $out"
        ;;
esac

case "$out" in
    *.img) ;;
    *) die "output path must end in .img: $out" ;;
esac

if [ -e "$out" ] && [ ! -f "$out" ]; then
    die "output path exists and is not a regular file: $out"
fi

out_dir=$(dirname "$out")
[ -d "$out_dir" ] || die "output directory does not exist: $out_dir"

partial="${out}.partial"
if [ -e "$partial" ] && [ ! -f "$partial" ]; then
    die "partial output path exists and is not a regular file: $partial"
fi

case "$size_mib" in
    '' | *[!0-9]*) die "size_mib must be a positive integer, got: $size_mib" ;;
esac
[ "$size_mib" -ge 2 ] || die "size_mib must be at least 2, got: $size_mib"

label_len=${#label}
if [ "$label_len" -lt 1 ] || [ "$label_len" -gt 11 ]; then
    die "label must be 1-11 characters (exFAT limit), got ${label_len} characters: $label"
fi

total_bytes=$((size_mib * 1048576))
part_bytes=$((total_bytes - 1048576))

# --- assemble ---------------------------------------------------------------
# Sparse MBR disk: one partition starting at LBA 2048, type 0x07 (exFAT),
# filling the remainder of the image.
truncate -s "$total_bytes" "$partial"

printf 'label: dos\nstart=2048, type=7\n' | sfdisk --quiet --force "$partial" >/dev/null

loop=$(losetup --find --show --offset 1048576 --sizelimit "$part_bytes" "$partial")
case "$loop" in
    /dev/loop[0-9]*) ;;
    *) die "losetup returned an unexpected device: $loop" ;;
esac

mkfs.exfat -L "$label" "$loop" >/dev/null

mnt=$(mktemp -d "${TMPDIR:-/tmp}/build-image.XXXXXX")
mount -t exfat "$loop" "$mnt"
mounted=1

rsync -rlt --delete "$payload"/ "$mnt"/

sync
umount "$mnt"
mounted=0

fsck.exfat -n "$loop" >&2

losetup -d "$loop"
loop=""

mv "$partial" "$out"
partial=""

if [ -n "${HOST_UID:-}" ] && [ -n "${HOST_GID:-}" ]; then
    chown "${HOST_UID}:${HOST_GID}" "$out" || true
fi

printf 'Wrote %s (%sMiB, label %s)\n' "$out" "$size_mib" "$label"
