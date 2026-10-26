#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

TMPDIR_WORK="$(mktemp -d)"
cleanup() {
  rm -rf "$TMPDIR_WORK"
}
trap cleanup EXIT

echo "==> Staging NextUI payload"
PAYLOAD="$TMPDIR_WORK/payload"
DIST="$TMPDIR_WORK/dist"
CACHE="$TMPDIR_WORK/cache"
mkdir -p "$PAYLOAD" "$DIST" "$CACHE"

uv run ansible-playbook ansible/build.yml --tags payload \
  -e device=trimui-brick \
  -e image_size_mib=1024 \
  -e payload_dir="$PAYLOAD" \
  -e dist_dir="$DIST" \
  -e cache_dir="$CACHE" >/dev/null

echo "==> Asserting NextUI card contract"
[ -f "$PAYLOAD/MinUI.zip" ] || fail "MinUI.zip missing"
head -c 2 "$PAYLOAD/MinUI.zip" | grep -q $'PK' || fail "MinUI.zip not a zip"
[ ! -e "$PAYLOAD/em_ui.sh" ] || fail "em_ui.sh should not exist"

for pak in "Tools/tg5040/Grout.pak" "Tools/tg5040/Tailscale.pak" "Tools/tg5040/Central Scrutinizer.pak"; do
  [ -d "$PAYLOAD/$pak" ] || fail "missing $pak"
  [ -f "$PAYLOAD/$pak/launch.sh" ] || fail "missing $pak/launch.sh"
  [ -x "$PAYLOAD/$pak/launch.sh" ] || fail "$pak/launch.sh not executable"
  [ -f "$PAYLOAD/$pak/pak.json" ] || fail "missing $pak/pak.json"
  grep -q '"tg5040"' "$PAYLOAD/$pak/pak.json" || fail "$pak/pak.json missing tg5040"
  [ ! -e "$PAYLOAD/$pak/$pak" ] || fail "nested $pak/$pak exists"
done
[ -x "$PAYLOAD/Tools/tg5040/Grout.pak/grout" ] || fail "Grout/grout not executable"
[ -x "$PAYLOAD/Tools/tg5040/Central Scrutinizer.pak/central-scrutinizer" ] || fail "CS/central-scrutinizer not executable"

! find "$PAYLOAD" -name authkey -o -name loginserver | grep -q . || fail "authkey/loginserver found"
[ ! -e "$PAYLOAD/.system" ] || fail ".system extracted"

echo "OK: NextUI card contract"

echo "==> Staging with corrupted cached archive (expect failure)"
BAD_PAYLOAD="$TMPDIR_WORK/payload-bad"
BAD_CACHE="$TMPDIR_WORK/cache-bad"
mkdir -p "$BAD_PAYLOAD" "$BAD_CACHE"
cp -R "$CACHE"/* "$BAD_CACHE/" 2>/dev/null || true
if [ -f "$BAD_CACHE/Grout.pak.zip" ]; then
  printf '\x00' | dd of="$BAD_CACHE/Grout.pak.zip" bs=1 seek=0 count=1 conv=notrunc >/dev/null 2>&1
  set +e
  uv run ansible-playbook ansible/build.yml --tags payload \
    -e device=trimui-brick \
    -e image_size_mib=1024 \
    -e payload_dir="$BAD_PAYLOAD" \
    -e dist_dir="$DIST" \
    -e cache_dir="$BAD_CACHE" 2>&1 | tee "$TMPDIR_WORK/ansible-bad-cache-grout.log"
  BAD_RC=${PIPESTATUS[0]}
  set -e
  [ "$BAD_RC" -ne 0 ] || fail "corrupt cached Grout archive did not fail"
  grep -Eq 'Grout\.pak\.zip' "$TMPDIR_WORK/ansible-bad-cache-grout.log" || fail "corrupt-cache failure did not name Grout.pak.zip"
  grep -Eqi 'sha256|checksum' "$TMPDIR_WORK/ansible-bad-cache-grout.log" || fail "corrupt-cache failure did not mention checksum"
  grep -Eqi 'delete|remove' "$TMPDIR_WORK/ansible-bad-cache-grout.log" || fail "corrupt-cache failure did not mention removing"
  echo "OK: corrupted Grout cache rejected"
fi
BAD_PAYLOAD2="$TMPDIR_WORK/payload-bad2"
BAD_CACHE2="$TMPDIR_WORK/cache-bad2"
mkdir -p "$BAD_PAYLOAD2" "$BAD_CACHE2"
cp -R "$CACHE"/* "$BAD_CACHE2/" 2>/dev/null || true
if [ -f "$BAD_CACHE2/Tailscale.pak.zip" ]; then
  printf '\x00' | dd of="$BAD_CACHE2/Tailscale.pak.zip" bs=1 seek=0 count=1 conv=notrunc >/dev/null 2>&1
  set +e
  uv run ansible-playbook ansible/build.yml --tags payload \
    -e device=trimui-brick \
    -e image_size_mib=1024 \
    -e payload_dir="$BAD_PAYLOAD2" \
    -e dist_dir="$DIST" \
    -e cache_dir="$BAD_CACHE2" 2>&1 | tee "$TMPDIR_WORK/ansible-bad-cache-tailscale.log"
  BAD_RC2=${PIPESTATUS[0]}
  set -e
  [ "$BAD_RC2" -ne 0 ] || fail "corrupt cached Tailscale archive did not fail"
  grep -Eq 'Tailscale\.pak\.zip' "$TMPDIR_WORK/ansible-bad-cache-tailscale.log" || fail "corrupt-cache failure did not name Tailscale.pak.zip"
  grep -Eqi 'sha256|checksum' "$TMPDIR_WORK/ansible-bad-cache-tailscale.log" || fail "corrupt-cache failure did not mention checksum"
  echo "OK: corrupted Tailscale cache rejected"
fi

EMPTY_PAYLOAD="$TMPDIR_WORK/payload-empty"
echo "==> Staging with empty remote_archives (expect failure)"
set +e
uv run ansible-playbook ansible/build.yml --tags payload \
  -e device=trimui-brick \
  -e image_size_mib=1024 \
  -e payload_dir="$EMPTY_PAYLOAD" \
  -e dist_dir="$DIST" \
  -e cache_dir="$CACHE" \
  -e '{"remote_archives": []}' 2>&1 | tee "$TMPDIR_WORK/ansible-empty-archives.log"
EMPTY_RC=${PIPESTATUS[0]}
set -e
[ "$EMPTY_RC" -ne 0 ] || fail "empty remote_archives did not fail staging"
grep -Eq 'remote_archives' "$TMPDIR_WORK/ansible-empty-archives.log" ||
  fail "empty-archive failure did not mention remote_archives"
echo "OK: empty remote_archives rejected with a profile message"

if ! docker image inspect sbc-imager-builder:local >/dev/null 2>&1; then
  fail "sbc-imager-builder:local missing. Run 'task container' first."
fi

PAYLOAD_MIB=$(du -sm "$PAYLOAD" | awk '{print $1}')
SIZE_MIB=$((PAYLOAD_MIB + 256))
if [ $SIZE_MIB -lt 1024 ]; then SIZE_MIB=1024; fi
OUTDIR="$DIST"
IMAGE="$OUTDIR/nextui.img"

echo "==> Building image (${SIZE_MIB}MiB)"
docker run --rm --privileged -e "HOST_UID=$(id -u)" -e "HOST_GID=$(id -g)" \
  -v "$PAYLOAD:/payload:ro" -v "$OUTDIR:/out" \
  sbc-imager-builder:local /payload /out/nextui.img "$SIZE_MIB" NEXTUI

[ -f "$IMAGE" ] || fail "image not created"
[ ! -e "$IMAGE.partial" ] || fail "partial left behind"

ACTUAL_BYTES=$(stat -f%z "$IMAGE" 2>/dev/null || stat -c%s "$IMAGE" 2>/dev/null)
EXPECTED_BYTES=$((SIZE_MIB * 1024 * 1024))
[ "$ACTUAL_BYTES" -eq "$EXPECTED_BYTES" ] || fail "bad image size"

docker run --rm --privileged -v "$OUTDIR:/out" --entrypoint sfdisk sbc-imager-builder:local -d /out/nextui.img | grep -Eq 'start=[[:space:]]*2048([[:space:],]|$)' || fail "bad MBR start"
docker run --rm --privileged -v "$OUTDIR:/out" --entrypoint sfdisk sbc-imager-builder:local -d /out/nextui.img | grep -Eq '(Id=|type=)[[:space:]]*7([[:space:],]|$)' || fail "bad MBR type"
docker run --rm --privileged -v "$OUTDIR:/out" --entrypoint fsck.exfat sbc-imager-builder:local -n /out/nextui.img >/dev/null || true

echo "==> All assertions passed"
echo "OK"
