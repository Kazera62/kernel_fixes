#!/usr/bin/env bash
set -euo pipefail

KERNEL_ROOT="$(pwd)"
ROOT_IMPL="none"
KPM="off"
SUSFS="off"
DEVICE="sdm450"

die() { echo "[kernel-fixes] VERIFY ERROR: $*" >&2; exit 1; }
ok() { echo "[kernel-fixes] VERIFY OK: $*"; }

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

case "$ROOT_IMPL" in
  sukisu-ultra)
    test -L "$KERNEL_ROOT/drivers/kernelsu" || die "drivers/kernelsu is not a symlink"
    KSU_DIR="$(readlink -f "$KERNEL_ROOT/drivers/kernelsu")"
    test "$KSU_DIR" = "$KERNEL_ROOT/KernelSU/kernel" || die "Unexpected SukiSU target: $KSU_DIR"

    grep -Fq '#include "infra/kernel_compat.h"' "$KSU_DIR/policy/allowlist.c" || die "fallthrough compatibility include missing"
    grep -Fq '#define fallthrough' "$KSU_DIR/infra/kernel_compat.h" || die "fallthrough compatibility macro missing"
    ! grep -Fq 'ksu_selinux_hide_handle_post_fs_data();' "$KSU_DIR/runtime/ksud.c" || die "old post-fs-data SELinux hook remains"
    ! grep -Fq 'ksu_selinux_hide_handle_second_stage();' "$KSU_DIR/runtime/ksud.c" || die "old second-stage SELinux hook remains"
    grep -Fq 'ksu_strncpy_from_user_nofault' "$KSU_DIR/sulog/event.c" || die "4.9 strncpy compatibility is missing"
    grep -Fq '#define USER_ARG_NULL (&(struct user_arg_ptr){ 0 })' "$KSU_DIR/sulog/event.c" || die "user_arg_ptr compatibility is missing"
    ok "SukiSU-Ultra source is patched at the compiler target"

    if [ "$KPM" = "on" ]; then
      grep -Fq 'config ARCH_HAS_SET_MEMORY' "$KERNEL_ROOT/arch/Kconfig" || die "KPM ARCH_HAS_SET_MEMORY fix missing"
      grep -Fq 'select ARCH_HAS_SET_MEMORY' "$KERNEL_ROOT/arch/arm64/Kconfig" || die "KPM arm64 selection fix missing"
      grep -Fq 'generic-y += set_memory.h' "$KERNEL_ROOT/arch/arm64/include/asm/Kbuild" || die "KPM arm64 generic set_memory integration missing"
      test -s "$KERNEL_ROOT/include/asm-generic/set_memory.h" || die "KPM generic set_memory header missing"
      grep -Fq '#include <asm/set_memory.h>' "$KERNEL_ROOT/arch/arm64/include/asm/cacheflush.h" || die "KPM arm64 cacheflush integration missing"
      ok "KPM 4.9 memory compatibility is present"
    fi
    ;;
  resukisu)
    if [ "$SUSFS" = "on" ]; then
      test -s "$KERNEL_ROOT/fs/susfs.c" || die "fs/susfs.c missing"
      test -s "$KERNEL_ROOT/include/linux/susfs.h" || die "include/linux/susfs.h missing"
      test -s "$KERNEL_ROOT/include/linux/susfs_def.h" || die "include/linux/susfs_def.h missing"
      grep -Rqs 'CONFIG_KSU_SUSFS' "$KERNEL_ROOT/fs/namespace.c" "$KERNEL_ROOT/fs/namei.c" "$KERNEL_ROOT/fs/stat.c" "$KERNEL_ROOT/fs/exec.c" || die "SUSFS hooks missing"
      ok "ReSukiSU SUSFS 4.9 integration is present"
    fi
    ;;
  none|kernelsu-next)
    ok "No additional compatibility source fixes required"
    ;;
  *) die "Unsupported root: $ROOT_IMPL" ;;
esac

printf '%s
' "[kernel-fixes] Verification completed successfully"
