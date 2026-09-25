#!/usr/bin/env bash
set -euo pipefail

FIXES_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KERNEL_ROOT="$(pwd)"
ROOT_IMPL="none"
KPM="off"
SUSFS="off"
DEVICE="sdm450"

die() { echo "[kernel-fixes] ERROR: $*" >&2; exit 1; }
log() { echo "[kernel-fixes] $*"; }

while [ "$#" -gt 0 ]; do
  case "$1" in
    --kernel-root) KERNEL_ROOT="$2"; shift 2 ;;
    --device) DEVICE="$2"; shift 2 ;;
    --root) ROOT_IMPL="$2"; shift 2 ;;
    --kpm) KPM="$2"; shift 2 ;;
    --susfs) SUSFS="$2"; shift 2 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

KERNEL_ROOT="$(cd "$KERNEL_ROOT" && pwd)"

[ "$DEVICE" = "sdm450" ] || die "Unsupported device: $DEVICE"
case "$ROOT_IMPL" in none|kernelsu-next|sukisu-ultra|resukisu) ;; *) die "Unsupported root: $ROOT_IMPL" ;; esac
case "$KPM" in on|off) ;; *) die "Invalid KPM value: $KPM" ;; esac
case "$SUSFS" in on|off) ;; *) die "Invalid SUSFS value: $SUSFS" ;; esac

apply_patch_once() {
  local patch_dir="$1"
  local patch_file="$2"
  local label="$3"

  log "Applying $label"
  if patch -d "$patch_dir" -p1 -N --batch --dry-run < "$patch_file" >/tmp/kernel-fixes-dryrun.log 2>&1; then
    patch -d "$patch_dir" -p1 -N --batch < "$patch_file"
    return
  fi

  if patch -d "$patch_dir" -p1 -R --batch --dry-run < "$patch_file" >/tmp/kernel-fixes-reverse.log 2>&1; then
    log "$label already applied"
    return
  fi

  cat /tmp/kernel-fixes-dryrun.log >&2
  die "Cannot apply $label"
}

fetch_external() {
  curl -fL --retry 3 --retry-delay 2 "$1" -o "$2"
  test -s "$2"
}

if [ "$ROOT_IMPL" = "sukisu-ultra" ]; then
  test -L "$KERNEL_ROOT/drivers/kernelsu" || die "drivers/kernelsu is not a symlink"
  KSU_DIR="$(readlink -f "$KERNEL_ROOT/drivers/kernelsu")"
  test -d "$KSU_DIR" || die "Resolved SukiSU source does not exist"

  case "$KSU_DIR" in
    "$KERNEL_ROOT"/KernelSU/kernel) ;;
    *) die "Unexpected SukiSU source target: $KSU_DIR" ;;
  esac

  log "Patching exact compiler source: $KSU_DIR"
  apply_patch_once     "$KSU_DIR"     "$FIXES_ROOT/patches/sukisu-ultra/001-sukisu-4.9-compat.patch"     "SukiSU-Ultra 4.9 compatibility"

  if [ "$KPM" = "on" ]; then
    KPM_URL="https://raw.githubusercontent.com/JackA1ltman/NonGKI_Kernel_Build_2nd/fe5053e603e20ce6ba97900da2c3c0229c7505d4/Patches/Patch/set_memory_to_49_and_low.patch"
    KPM_PATCH="/tmp/kernel-fixes-set-memory-to-49-and-low.patch"
    fetch_external "$KPM_URL" "$KPM_PATCH"
    apply_patch_once "$KERNEL_ROOT" "$KPM_PATCH" "KPM 4.9 memory compatibility"
  fi
fi

if [ "$ROOT_IMPL" = "resukisu" ] && [ "$SUSFS" = "on" ]; then
  SUSFS_URL="https://raw.githubusercontent.com/JackA1ltman/NonGKI_Kernel_Build_2nd/fe5053e603e20ce6ba97900da2c3c0229c7505d4/Patches/Patch/susfs_patch_to_4.9.patch"
  SUSFS_PATCH="/tmp/kernel-fixes-susfs-4.9.patch"
  INLINE_URL="https://raw.githubusercontent.com/JackA1ltman/NonGKI_Kernel_Build_2nd/fe5053e603e20ce6ba97900da2c3c0229c7505d4/Patches/susfs_inline_hook_patches.sh"
  INLINE_SCRIPT="/tmp/kernel-fixes-susfs-inline-hook.sh"

  fetch_external "$SUSFS_URL" "$SUSFS_PATCH"
  apply_patch_once "$KERNEL_ROOT" "$SUSFS_PATCH" "ReSukiSU SUSFS 4.9 compatibility"

  fetch_external "$INLINE_URL" "$INLINE_SCRIPT"
  chmod +x "$INLINE_SCRIPT"
  (
    cd "$KERNEL_ROOT"
    "$INLINE_SCRIPT"
  )
fi

log "Compatibility fix application completed"
