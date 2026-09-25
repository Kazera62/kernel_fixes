#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()

def fail(message: str) -> None:
    print(f"[kernel-fixes] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)

def edit(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if new in text:
        print(f"[kernel-fixes] already fixed: {label}")
        return
    if old not in text:
        fail(f"expected source pattern missing for {label}: {path}")
    path.write_text(text.replace(old, new, 1))
    print(f"[kernel-fixes] fixed: {label}")

if not root.is_dir():
    fail(f"source directory not found: {root}")

allowlist = root / "policy" / "allowlist.c"
compat = root / "infra" / "kernel_compat.h"
ksud = root / "runtime" / "ksud.c"
sulog = root / "sulog" / "event.c"

for path in (allowlist, compat, ksud, sulog):
    if not path.is_file():
        fail(f"required SukiSU source file missing: {path}")

edit(
    allowlist,
    '#define FILE_MAGIC',
    '#include "infra/kernel_compat.h"\n\n#define FILE_MAGIC',
    "fallthrough compatibility include",
)

compat_text = compat.read_text()
if "#define fallthrough" not in compat_text:
    marker = "#endif"
    pos = compat_text.rfind(marker)
    if pos < 0:
        fail("kernel_compat.h has no final #endif")
    addition = '''
#ifndef fallthrough
#define fallthrough do { } while (0) /* fallthrough */
#endif

'''
    compat.write_text(compat_text[:pos] + addition + compat_text[pos:])
    print("[kernel-fixes] fixed: fallthrough compatibility macro")
else:
    print("[kernel-fixes] already fixed: fallthrough compatibility macro")

edit(
    ksud,
    '    stop_input_hook();\n    ksu_selinux_hide_handle_post_fs_data();',
    '    stop_input_hook();',
    "remove incompatible post-fs-data SELinux hook",
)

edit(
    ksud,
    '            pr_info("/system/bin/init second_stage executed\\n");\n            ksu_selinux_hide_handle_second_stage();\n            apply_kernelsu_rules();',
    '            pr_info("/system/bin/init second_stage executed\\n");\n            apply_kernelsu_rules();',
    "remove incompatible second-stage SELinux hook",
)

edit(
    sulog,
    'strncpy_from_user_nofault(arg, (const void __user *)untagged_addr((unsigned long)arg_user), sizeof(arg))',
    'ksu_strncpy_from_user_nofault(arg, (const void __user *)untagged_addr((unsigned long)arg_user), sizeof(arg))',
    "use SukiSU 4.9 nofault helper",
)

edit(
    sulog,
    '#define USER_ARG_NULL user_arg_null_ptr()',
    '#define USER_ARG_NULL (&(struct user_arg_ptr){ 0 })',
    "fix user_arg_ptr ABI mismatch",
)

print("[kernel-fixes] SukiSU 4.9 source transformation completed")
