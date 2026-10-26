#!/usr/bin/env bash
# unlock.sh - stage a sabrina bootloader unlock. Builds ghostlock from the
# upstream clone, then drives backup/patch/flash of the u-boot env. Root steps
# run in a separate ghostlock shell; this script never runs as root.
# Flashing + first boot factory-resets /data.
set -euo pipefail

ENV_PART="/dev/block/platform/ffe07000.emmc/by-name/env"
DEV_TMP="/data/local/tmp"
GHOSTLOCK_DEV="$DEV_TMP/ghostlock"
ENV_TOOL_DEV="$DEV_TMP/env_tool.sh"
STAGED_DEV="$DEV_TMP/env.patched.img"
DUMP_DEV="$DEV_TMP/env.img"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
START_PWD="$PWD"

BUILD_REPO="${BUILD_REPO:-https://github.com/k-o-n-t-o-r/ghostlock-sabrina}"
BUILD_DIR="${BUILD_DIR:-$START_PWD/ghostlock-build}"
NDK_URL="https://dl.google.com/android/repository/android-ndk-r30-linux.zip"

PATCHER="${PATCHER:-$REPO_ROOT/scripts/patch_env_unlock.py}"
GHOSTLOCK="${GHOSTLOCK:-}"

SERIAL=""
PATCH_ARGS=()

usage() {
    cat <<EOF
usage: $(basename "$0") [-s SERIAL] [--unlock-only] [-- <patcher args>]
  -s, --serial SERIAL   adb serial, if multiple devices
      --unlock-only     patch lock bits only (no bootdelay/button tweaks)
env: BUILD_REPO= GHOSTLOCK= PATCHER=
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        -s|--serial) SERIAL="$2"; shift 2;;
        --unlock-only) PATCH_ARGS+=("--unlock-only"); shift;;
        -h|--help) usage; exit 0;;
        --) shift; PATCH_ARGS+=("$@"); break;;
        *) echo "unknown option: $1" >&2; usage; exit 2;;
    esac
done

log() { printf '>> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
pause() { printf '%s%s%s ' "$CY" "${1:-press Enter}" "$RST"; read -r _ </dev/tty || true; }

CY=$'\033[1;36m'; RED=$'\033[1;31m'; RST=$'\033[0m'   # cyan = your instructions, red = commands to run
inst() { printf '%s' "$CY"; cat; printf '%s' "$RST"; }   # colorize a heredoc block

build_ghostlock() {
    for t in git wget unzip make; do command -v "$t" >/dev/null || die "$t not on PATH"; done
    [ -d "$BUILD_DIR/.git" ] || git clone "$BUILD_REPO" "$BUILD_DIR"
    cd "$BUILD_DIR"
    if [ ! -d android-ndk-r30 ]; then
        wget -q "$NDK_URL" -O ndk.zip && unzip -q ndk.zip && rm -f ndk.zip
    fi
    export ANDROID_NDK_HOME="$BUILD_DIR/android-ndk-r30"
    make -j4 >/dev/null 2>&1 || die "build failed (re-run make in $BUILD_DIR to see why)"
    mkdir -p "$REPO_ROOT/bin"
    mv -f ghostlock "$REPO_ROOT/bin/ghostlock"
    cd "$START_PWD"
}

command -v adb      >/dev/null || die "adb not on PATH"
command -v fastboot >/dev/null || die "fastboot not on PATH"
command -v python3  >/dev/null || die "python3 not on PATH"
[ -f "$PATCHER" ] || die "patcher not found: $PATCHER"

ADB=(adb);      [ -n "$SERIAL" ] && ADB=(adb -s "$SERIAL")
FB=(fastboot);  [ -n "$SERIAL" ] && FB=(fastboot -s "$SERIAL")

log "building ghostlock"
build_ghostlock
[ -n "$GHOSTLOCK" ] || for c in "$REPO_ROOT/bin/ghostlock" "$BUILD_DIR/ghostlock"; do
    [ -f "$c" ] && GHOSTLOCK="$c" && break
done
[ -f "$GHOSTLOCK" ] || die "ghostlock binary not found after build"

"${ADB[@]}" wait-for-device

WORKDIR="$START_PWD/unlock-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$WORKDIR"
PULLED="$WORKDIR/env.orig.img"
PATCHED="$WORKDIR/env.patched.img"
ENV_TOOL_HOST="$WORKDIR/env_tool.sh"

cat > "$ENV_TOOL_HOST" <<EOF
#!/system/bin/sh
# run under a root (ghostlock) shell: sh $ENV_TOOL_DEV --backup|--flash
ENV="$ENV_PART"
case "\$1" in
  --backup)
    dd if="\$ENV" of="$DUMP_DEV" bs=1M && chmod 644 "$DUMP_DEV" && echo "OK: backup" ;;
  --flash)
    [ -f "$STAGED_DEV" ] || { echo "ERR: $STAGED_DEV missing"; exit 1; }
    dd if="$STAGED_DEV" of="\$ENV" bs=1M && sync
    printf 'readback '; dd if="\$ENV" bs=64k count=1 2>/dev/null | grep -a -o 'lock=[0-9]*' | head -1 ;;
  *) echo "usage: \$0 --backup|--flash"; exit 2 ;;
esac
EOF

log "pushing ghostlock + env_tool.sh"
"${ADB[@]}" push "$GHOSTLOCK" "$GHOSTLOCK_DEV" >/dev/null
"${ADB[@]}" push "$ENV_TOOL_HOST" "$ENV_TOOL_DEV" >/dev/null
"${ADB[@]}" shell "chmod 755 $GHOSTLOCK_DEV $ENV_TOOL_DEV" || true

inst <<EOF

Get a root shell in a SECOND terminal (leave it open):
    ${RED}adb shell "cd /data/local/tmp && ./ghostlock --cred"${CY}
It is a SILENT root shell: no '#' prompt. Success is a line ending in
    [!] partial plan (hits=3/3) - skipping exec (commit_creds BUG_ON guard); battery written
Paste the commands below into that shell; they run as root with no prompt echo.
If it dies, re-run the command above.
EOF

printf '\n%sNow run this from the root shell:%s\n' "$RED" "$RST"
printf '%s    sh %s --backup%s\n' "$RED" "$ENV_TOOL_DEV" "$RST"
pause "press Enter after 'OK: backup':"

log "pulling + patching env"
"${ADB[@]}" pull "$DUMP_DEV" "$PULLED" >/dev/null || die "pull failed (did --backup run?)"
python3 -I "$PATCHER" "$PULLED" -o "$PATCHED" --no-backup "${PATCH_ARGS[@]+"${PATCH_ARGS[@]}"}"
"${ADB[@]}" push "$PATCHED" "$STAGED_DEV" >/dev/null

printf '\n%sNow run this from the root shell:%s\n' "$RED" "$RST"
printf '%s    sh %s --flash%s\n' "$RED" "$ENV_TOOL_DEV" "$RST"
printf 'expect readback lock=10100010 (unlocked)\n'

inst <<EOF

After --flash, complete the unlock:
  1. Power the device OFF.
  2. Power on; when the ORANGE light comes on, press and HOLD the power button.
  3. Hold through boot into the bootloader.
EOF

printf '%sDid the device land in RescueParty (recovery) instead of the bootloader? [y/N]%s ' "$CY" "$RST"
read -r rp </dev/tty || true
case "$rp" in
    y|Y|yes|YES)
        log "routing out of RescueParty to the bootloader (each reboot can take ~30s)"
        log "rescue -> fastboot ..."
        "${ADB[@]}" reboot fastboot || true
        log "fastboot -> bootloader ..."
        "${FB[@]}" reboot bootloader || true ;;
esac

log "waiting for fastboot device"
until "${FB[@]}" devices 2>/dev/null | grep -q .; do sleep 1; done

log "unlock state:"
"${FB[@]}" getvar unlocked

printf '%s\nfastboot -w is REQUIRED to finish the unlock (wipes userdata/cache).%s\n' "$CY" "$RST"
pause "press Enter to run it:"
"${FB[@]}" -w

log "done. env backup: $PULLED"
