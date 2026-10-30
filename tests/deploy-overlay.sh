#!/usr/bin/env bash
# QA: prove the Cannoli fast-deploy path copies the staged tree onto a mounted
# card (shaders and overlays included) and overlays without deleting user data.
set -euo pipefail

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

TMP=$(mktemp -d "${TMPDIR:-/tmp}/deploy-overlay.XXXXXX")
cleanup() {
  rm -rf "$TMP"
}
trap cleanup EXIT

PAYLOAD="$TMP/payload"
DIST="$TMP/dist"
CACHE="$TMP/cache"
CARD="$TMP/card"

# Simulate a card that already holds user data.
mkdir -p "$CARD/Cannoli/Roms/GB" "$CARD/Cannoli/Saves" "$CARD/Cannoli/BIOS"
printf 'user rom\n' >"$CARD/Cannoli/Roms/GB/mine.gb"
printf 'user save\n' >"$CARD/Cannoli/Saves/mine.srm"
printf 'user bios\n' >"$CARD/Cannoli/BIOS/mine.bin"

deploy() {
  local target=$1
  local log=$2
  uv run ansible-playbook ansible/build.yml --tags payload,deploy \
    -e device=rp-nova -e image_device= -e deploy_enabled=true \
    -e deploy_target="$target" \
    -e payload_dir="$PAYLOAD" -e dist_dir="$DIST" -e cache_dir="$CACHE" >"$log" 2>&1
}

echo "==> Deploying to a simulated card"
deploy "$CARD" "$TMP/deploy.log" || {
  cat "$TMP/deploy.log" >&2
  fail "deploy run failed"
}

echo "==> Asserting the payload landed (including shaders and overlays)"
[ -d "$CARD/Cannoli" ] || fail "Cannoli missing"
[ -f "$CARD/APKs/Obtainium.apk" ] || fail "APKs/Obtainium.apk missing"
[ -f "$CARD/Obtainium/obtainium-emulation-pack-v8.0.1.json" ] || fail "emulation pack missing"
[ -f "$CARD/Obtainium/nova-display-calibration.json" ] || fail "Nova Calibration import missing"
[ -f "$CARD/Obtainium/o2p-tweaks.json" ] || fail "O2P Tweaks import missing"
[ -f "$CARD/Cannoli/Config/settings.json" ] || fail "settings marker missing"
[ -f "$CARD/Cannoli/Shaders/crt-1tap.glslp" ] || fail "shader preset missing"
[ -f "$CARD/Cannoli/Shaders/shaders/crt-1tap.glsl" ] || fail "shader source missing"
[ -f "$CARD/Cannoli/Overlays/GB/Jeltron_GB-DMG.png" ] || fail "GB overlay missing"
[ -f "$CARD/Cannoli/Overlays/NES/Jeltron_CRT.png" ] || fail "CRT overlay missing"
echo "OK: payload (shaders + overlays) copied"

echo "==> Asserting overlay preserved existing user data"
[ -f "$CARD/Cannoli/Roms/GB/mine.gb" ] || fail "user ROM deleted by deploy"
[ -f "$CARD/Cannoli/Saves/mine.srm" ] || fail "user save deleted by deploy"
[ -f "$CARD/Cannoli/BIOS/mine.bin" ] || fail "user BIOS deleted by deploy"
echo "OK: user data preserved (no --delete)"

echo "==> Re-deploying (update) preserves user data"
deploy "$CARD" "$TMP/deploy2.log" || {
  cat "$TMP/deploy2.log" >&2
  fail "second deploy failed"
}
[ -f "$CARD/Cannoli/Roms/GB/mine.gb" ] || fail "user ROM lost on update"
[ -f "$CARD/Cannoli/Shaders/crt-1tap.glslp" ] || fail "shader preset lost on update"
echo "OK: update preserved user data and payload"

echo "==> Missing deploy target must fail"
BAD_CARD="$TMP/does-not-exist"
set +e
deploy "$BAD_CARD" "$TMP/deploy-bad.log"
BAD_RC=$?
set -e
[ "$BAD_RC" -ne 0 ] || fail "missing deploy target did not fail"
grep -q "not a mounted directory" "$TMP/deploy-bad.log" ||
  fail "missing-target failure did not mention the mounted-directory check"
echo "OK: missing deploy target rejected"

echo "==> Result"
echo "PASS: deploy copies the payload (shaders + overlays) and overlays without deleting user data"
