#!/usr/bin/env bash
# QA: run the Ansible payload playbook and assert the staged Cannoli tree.
#
# The run is fully isolated: payload_dir and dist_dir point into an mktemp
# directory, so the repository build/ and dist/ trees are never touched.
#
# Directory arithmetic (all paths relative to the payload root):
#   17 declared cannoli_base_dirs
# + 51 declared cannoli_tags under Cannoli/Roms
# +  1 implicit Cannoli/Media (parent of the two declared Media/* dirs)
# +  1 required Obtainium dir (destination of the local Tailscale import)
# = 70 directories under the payload root, excluding the root itself.
#
# The plan text mentions 68; that is wrong because 17 + 51 already excludes
# the root (the Cannoli root is one of the 17 base dirs).

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

VAR_FILE="ansible/vars/cannoli.yml"
EXPECTED_BASE=17
EXPECTED_TAGS=51
EXPECTED_DIRS=70

TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/ansible-payload-qa.XXXXXX")
PAYLOAD_DIR="$TMP_DIR/payload"
DIST_DIR="$TMP_DIR/dist"
BASE_LIST="$TMP_DIR/base_dirs.txt"
TAG_LIST="$TMP_DIR/tags.txt"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

list_items() {
  awk -v key="$1" '
    $0 ~ ("^" key ":") { in_list = 1; next }
    /^[A-Za-z_][A-Za-z0-9_]*:/ { in_list = 0 }
    in_list && /^[[:space:]]*-[[:space:]]+/ {
      sub(/^[[:space:]]*-[[:space:]]+/, "")
      print
    }
  ' "$VAR_FILE"
}

file_size() {
  case "$(uname -s)" in
    Darwin) stat -f%z "$1" ;;
    *) stat -c%s "$1" ;;
  esac
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

# Assert the full contract against $1. Returns 0 only when every check passes.
assert_payload_tree() {
  local root=$1
  local rc=0
  local rel tag actual expected dir_count size digest missing

  # Top-level card-root entries: exactly APKs, Cannoli, Obtainium.
  actual=$(find "$root" -mindepth 1 -maxdepth 1 -exec basename {} \; \
    | LC_ALL=C sort | tr '\n' ' ')
  expected="APKs Cannoli Obtainium "
  if [[ "$actual" != "$expected" ]]; then
    echo "FAIL top-level entries: expected [$expected] got [$actual]" >&2
    rc=1
  else
    echo "PASS top-level entries: $actual"
  fi

  # 17/17 declared base directories.
  missing=0
  while IFS= read -r rel; do
    if [[ ! -d "$root/$rel" ]]; then
      echo "FAIL missing base dir: $rel" >&2
      rc=1
      missing=$((missing + 1))
    fi
  done < "$BASE_LIST"
  if [[ "$missing" -eq 0 ]]; then
    echo "PASS base dirs: $EXPECTED_BASE/$EXPECTED_BASE present"
  fi

  # 51/51 declared Cannoli/Roms/<tag> directories.
  missing=0
  while IFS= read -r tag; do
    if [[ ! -d "$root/Cannoli/Roms/$tag" ]]; then
      echo "FAIL missing roms dir: Cannoli/Roms/$tag" >&2
      rc=1
      missing=$((missing + 1))
    fi
  done < "$TAG_LIST"
  if [[ "$missing" -eq 0 ]]; then
    echo "PASS roms dirs: $EXPECTED_TAGS/$EXPECTED_TAGS present"
  fi

  # Total directories under the root: 17 + 51 + implicit Media + Obtainium.
  dir_count=$(find "$root" -mindepth 1 -type d | wc -l | tr -d ' ')
  if [[ "$dir_count" -ne "$EXPECTED_DIRS" ]]; then
    echo "FAIL directory count: expected $EXPECTED_DIRS got $dir_count" >&2
    rc=1
  else
    echo "PASS directory count: $dir_count (17 base + 51 roms + Cannoli/Media + Obtainium)"
  fi

  # settings.json must be exactly "{}\n" (3 bytes).
  if [[ ! -f "$root/Cannoli/Config/settings.json" ]]; then
    echo "FAIL settings marker missing: Cannoli/Config/settings.json" >&2
    rc=1
  elif ! printf '{}\n' | cmp -s - "$root/Cannoli/Config/settings.json"; then
    echo "FAIL settings marker is not exactly 3 bytes of '{}' + newline" >&2
    rc=1
  else
    echo "PASS settings marker: Cannoli/Config/settings.json is exactly 3 bytes"
  fi

  # Payload files: exact byte sizes; print derived SHA-256 values.
  while read -r rel expected; do
    if [[ ! -f "$root/$rel" ]]; then
      echo "FAIL missing payload file: $rel" >&2
      rc=1
      continue
    fi
    size=$(file_size "$root/$rel")
    if [[ "$size" -ne "$expected" ]]; then
      echo "FAIL size $rel: expected $expected bytes got $size" >&2
      rc=1
      continue
    fi
    digest=$(sha256_of "$root/$rel")
    echo "PASS file $rel: $size bytes sha256=$digest"
  done <<'FILES'
APKs/Obtainium.apk 27194505
Obtainium/obtainium-emulation-pack-v8.0.1.json 78201
Obtainium/tailscale.json 383
FILES

  # No CREDITS.md anywhere under the payload.
  actual=$(find "$root" -name 'CREDITS.md' -print)
  if [[ -n "$actual" ]]; then
    echo "FAIL CREDITS.md present under payload: $actual" >&2
    rc=1
  else
    echo "PASS no CREDITS.md under payload"
  fi

  return "$rc"
}

list_items cannoli_base_dirs > "$BASE_LIST"
list_items cannoli_tags > "$TAG_LIST"
EXPECTED_BASE=$(wc -l < "$BASE_LIST" | tr -d ' ')
EXPECTED_TAGS=$(wc -l < "$TAG_LIST" | tr -d ' ')

if [[ "$EXPECTED_BASE" -lt 1 || "$EXPECTED_TAGS" -lt 1 ]]; then
  echo "FAIL could not derive contract lists from $VAR_FILE" >&2
  exit 1
fi
if [[ "$EXPECTED_BASE" -ne 17 || "$EXPECTED_TAGS" -ne 51 ]]; then
  echo "FAIL derived contract counts: expected 17 base + 51 tags, got" \
    "$EXPECTED_BASE base + $EXPECTED_TAGS tags" >&2
  exit 1
fi

PLAYBOOK_CMD=(
  uv run ansible-playbook ansible/build.yml
  --tags payload
  -e device=rg477m
  -e "image_device="
  -e image_size_mib=128
  -e "payload_dir=$PAYLOAD_DIR"
  -e "dist_dir=$DIST_DIR"
)

echo "== Command =="
printf '%s\n' "${PLAYBOOK_CMD[*]}"

echo "== Happy run =="
if ! "${PLAYBOOK_CMD[@]}" >"$TMP_DIR/play.log" 2>&1; then
  echo "FAIL playbook exited non-zero; full log follows" >&2
  cat "$TMP_DIR/play.log" >&2
  exit 1
fi
tail -n 15 "$TMP_DIR/play.log"

echo "== Assertions (happy run) =="
if ! assert_payload_tree "$PAYLOAD_DIR"; then
  echo "FAIL happy-run payload contract is not satisfied" >&2
  exit 1
fi

echo "== Failure injection =="
BAD_DIR="$TMP_DIR/payload-broken"
cp -R "$PAYLOAD_DIR" "$BAD_DIR"
read -r REMOVED_TAG < "$TAG_LIST"
rm -rf "$BAD_DIR/Cannoli/Roms/$REMOVED_TAG"
echo "Removed Cannoli/Roms/$REMOVED_TAG from a copy of the tree"

bad_output=""
if bad_output=$(assert_payload_tree "$BAD_DIR" 2>&1); then
  echo "FAIL failure-injection: helper accepted a tree missing $REMOVED_TAG" >&2
  exit 1
fi
echo "PASS failure-injection: missing Cannoli/Roms/$REMOVED_TAG rejected (non-zero)"
printf '%s\n' "$bad_output" | sed 's/^/    /'

echo "== Result =="
echo "PASS: payload contract holds (70 directories, 3 files, no CREDITS.md)"
