#!/usr/bin/env python3
from pathlib import Path
import sys

ksu_root = Path(sys.argv[1]).resolve()
kernel_root = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else ksu_root.parents[1]


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


def insert_once(path: Path, marker: str, addition: str, label: str) -> None:
    text = path.read_text()
    if addition.strip() in text:
        print(f"[kernel-fixes] already fixed: {label}")
        return
    pos = text.find(marker)
    if pos < 0:
        fail(f"expected insertion marker missing for {label}: {path}")
    path.write_text(text[:pos] + addition + text[pos:])
    print(f"[kernel-fixes] fixed: {label}")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    edit(path, old, new, label)


if not ksu_root.is_dir():
    fail(f"SukiSU source directory not found: {ksu_root}")
if not kernel_root.is_dir():
    fail(f"kernel root directory not found: {kernel_root}")

allowlist = ksu_root / "policy" / "allowlist.c"
compat = ksu_root / "infra" / "kernel_compat.h"
ksud = ksu_root / "runtime" / "ksud.c"
sulog = ksu_root / "sulog" / "event.c"
lsm_hook = ksu_root / "hook" / "lsm_hook.c"
sucompat = ksu_root / "feature" / "sucompat.c"

for path in (allowlist, compat, ksud, sulog, lsm_hook, sucompat):
    if not path.is_file():
        fail(f"required SukiSU source file missing: {path}")

edit(
    allowlist,
    '#define FILE_MAGIC',
    '#include "infra/kernel_compat.h"\\n\\n#define FILE_MAGIC',
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


def remove_call(path: Path, needle: str, label: str) -> None:
    lines = path.read_text().splitlines(keepends=True)
    if not any(needle in line for line in lines):
        print(f"[kernel-fixes] already fixed: {label}")
        return
    filtered = [line for line in lines if needle not in line]
    path.write_text("".join(filtered))
    print(f"[kernel-fixes] fixed: {label}")


remove_call(
    ksud,
    "ksu_selinux_hide_handle_post_fs_data();",
    "remove incompatible post-fs-data SELinux hook",
)

remove_call(
    ksud,
    "ksu_selinux_hide_handle_second_stage();",
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
    '''#ifdef CONFIG_KSU_SUSFS
#define USER_ARG_NULL (&(struct user_arg_ptr){ 0 })
#else
#define USER_ARG_NULL ((struct user_arg_ptr){ 0 })
#endif''',
    "fix user_arg_ptr ABI mismatch for SUSFS/non-SUSFS",
)

# Fresh non-GKI installations can hit a userspace/kernel fd-bootstrap
# deadlock. Handle the legacy SukiSU manager prctl directly in the LSM hook.
prctl_marker = "static struct security_hook_list ksu_hooks[] = {"
prctl_block = '''/* Legacy prctl detection + fd bootstrap for non-GKI built-in builds. */
#define KSU_LEGACY_PRCTL_OPTION 0xDEADBEEFu
static int ksu_task_prctl(int option, unsigned long arg2, unsigned long arg3,
                          unsigned long arg4, unsigned long arg5)
{
    if ((unsigned int)option != KSU_LEGACY_PRCTL_OPTION)
        return -ENOSYS;

    if (arg2 == 2u) {
        if (!ksu_is_manager_appid_valid()) {
            uid_t appid = current_uid().val % KSU_PER_USER_RANGE;
            ksu_set_manager_appid(appid);
            pr_info("ksu prctl: crowned uid=%u as manager\\n", current_uid().val);
        }
        if (is_manager())
            ksu_install_fd();

        {
            int version = KERNEL_SU_VERSION;
            int flags = is_manager() ? 1 : 0;
            int result = 0;

            if (copy_to_user((void __user *)arg3, &version, sizeof(version)))
                return -EFAULT;
            if (copy_to_user((void __user *)arg4, &flags, sizeof(flags)))
                return -EFAULT;
            if (copy_to_user((void __user *)arg5, &result, sizeof(result)))
                return -EFAULT;
        }
        return 0;
    }

    return -EINVAL;
}

'''
insert_once(lsm_hook, prctl_marker, prctl_block, "legacy manager prctl bootstrap")
replace_once(
    lsm_hook,
    '''#ifndef CONFIG_KSU_SUSFS
    LSM_HOOK_INIT(task_fix_setuid, ksu_task_fix_setuid),
#endif
};''',
    '''#ifndef CONFIG_KSU_SUSFS
    LSM_HOOK_INIT(task_fix_setuid, ksu_task_fix_setuid),
#endif
    LSM_HOOK_INIT(task_prctl, ksu_task_prctl),
};''',
    "register legacy manager prctl hook",
)

# The built-in non-SUSFS path should also survive a fresh installation where
# /data/adb/ksud has not been populated yet.
fallback_old = '''    memcpy((void *)filename->name, ksud_path, sizeof(ksud_path));

    pending_sucompat = ksu_sulog_capture_sucompat(filename->name, (struct user_arg_ptr*)argv_user, GFP_KERNEL);
'''
fallback_new = '''    {
        struct path kpath;
        if (kern_path(ksud_path, 0, &kpath) == 0) {
            path_put(&kpath);
            memcpy((void *)filename->name, ksud_path, sizeof(ksud_path));
        } else {
            pr_warn("ksu_handle_execveat_sucompat: ksud not found, falling back to sh\\\\n");
            memcpy((void *)filename->name, sh_path, sizeof(sh_path));
        }
    }

    pending_sucompat = ksu_sulog_capture_sucompat(filename->name, (struct user_arg_ptr*)argv_user, GFP_KERNEL);
'''
if fallback_old in sucompat.read_text():
    replace_once(sucompat, fallback_old, fallback_new, "ksud-to-sh fallback for fresh install")
else:
    print("[kernel-fixes] already fixed: ksud-to-sh fallback or source variant differs")

# Manual non-GKI hook sites. SukiSU's current docs explicitly reserve
# KPROBES for GKI/LKM and require these call sites for non-GKI kernels.
manual_patches = [
    (
        kernel_root / "fs" / "exec.c",
        "static int do_execveat_common(int fd, struct filename *filename,\\n",
        '''#ifdef CONFIG_KSU
extern bool ksu_execveat_hook __read_mostly;
extern int ksu_handle_execveat(int *fd, struct filename **filename_ptr,
                               void *argv, void *envp, int *flags);
#endif

''',
        '''static int do_execveat_common(int fd, struct filename *filename,
''',
        '''#ifdef CONFIG_KSU
        if (unlikely(ksu_execveat_hook))
            ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);
#endif
''',
        "manual execve hook",
    ),
]

# exec.c: declaration before the function and call at the top.
exec_c = kernel_root / "fs" / "exec.c"
insert_once(
    exec_c,
    "static int do_execveat_common(int fd, struct filename *filename,\\n",
    manual_patches[0][2],
    "manual execve hook declaration",
)
replace_once(
    exec_c,
    '''static int do_execveat_common(int fd, struct filename *filename,
			      struct user_arg_ptr argv,
			      struct user_arg_ptr envp,
			      int flags)
{
	char *pathbuf = NULL;
''',
    '''static int do_execveat_common(int fd, struct filename *filename,
			      struct user_arg_ptr argv,
			      struct user_arg_ptr envp,
			      int flags)
{
#ifdef CONFIG_KSU
	if (unlikely(ksu_execveat_hook))
		ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);
#endif
	char *pathbuf = NULL;
''',
    "manual execve hook call",
)

open_c = kernel_root / "fs" / "open.c"
insert_once(
    open_c,
    "SYSCALL_DEFINE3(faccessat, int, dfd, const char __user *, filename, int, mode)\\n",
    '''#ifdef CONFIG_KSU
extern int ksu_handle_faccessat(int *dfd, const char __user **filename_user, int *mode,
				int *flags);
#endif

''',
    "manual faccessat hook declaration",
)
replace_once(
    open_c,
    '''SYSCALL_DEFINE3(faccessat, int, dfd, const char __user *, filename, int, mode)
{
	const struct cred *old_cred;
''',
    '''SYSCALL_DEFINE3(faccessat, int, dfd, const char __user *, filename, int, mode)
{
#ifdef CONFIG_KSU
	ksu_handle_faccessat(&dfd, &filename, &mode, NULL);
#endif
	const struct cred *old_cred;
''',
    "manual faccessat hook call",
)

read_c = kernel_root / "fs" / "read_write.c"
insert_once(
    read_c,
    "ssize_t vfs_read(struct file *file, char __user *buf, size_t count, loff_t *pos)\\n",
    '''#ifdef CONFIG_KSU
extern bool ksu_vfs_read_hook __read_mostly;
extern int ksu_handle_vfs_read(struct file **file_ptr, char __user **buf_ptr,
			       size_t *count_ptr, loff_t **pos);
#endif

''',
    "manual vfs_read hook declaration",
)
replace_once(
    read_c,
    '''ssize_t vfs_read(struct file *file, char __user *buf, size_t count, loff_t *pos)
{
	ssize_t ret;
''',
    '''ssize_t vfs_read(struct file *file, char __user *buf, size_t count, loff_t *pos)
{
	ssize_t ret;
#ifdef CONFIG_KSU
	if (unlikely(ksu_vfs_read_hook))
		ksu_handle_vfs_read(&file, &buf, &count, &pos);
#endif
''',
    "manual vfs_read hook call",
)

stat_c = kernel_root / "fs" / "stat.c"
insert_once(
    stat_c,
    "int vfs_fstatat(int dfd, const char __user *filename, struct kstat *stat,\\n",
    '''#ifdef CONFIG_KSU
extern int ksu_handle_stat(int *dfd, const char __user **filename_user, int *flags);
#endif

''',
    "manual stat hook declaration",
)
replace_once(
    stat_c,
    '''int vfs_fstatat(int dfd, const char __user *filename, struct kstat *stat,
		int flag)
{
	struct path path;
''',
    '''int vfs_fstatat(int dfd, const char __user *filename, struct kstat *stat,
		int flag)
{
#ifdef CONFIG_KSU
	ksu_handle_stat(&dfd, &filename, &flag);
#endif
	struct path path;
''',
    "manual stat hook call",
)

reboot_c = kernel_root / "kernel" / "reboot.c"
insert_once(
    reboot_c,
    "SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd,\\n",
    '''#ifdef CONFIG_KSU
extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg);
#endif

''',
    "manual reboot hook declaration",
)
replace_once(
    reboot_c,
    '''SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd,
		void __user *, arg)
{
	struct pid_namespace *pid_ns = task_active_pid_ns(current);
''',
    '''SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd,
		void __user *, arg)
{
#ifdef CONFIG_KSU
	ksu_handle_sys_reboot(magic1, magic2, cmd, (void __user **)&arg);
#endif
	struct pid_namespace *pid_ns = task_active_pid_ns(current);
''',
    "manual reboot hook call",
)

input_c = kernel_root / "drivers" / "input" / "input.c"
insert_once(
    input_c,
    "static void input_handle_event(struct input_dev *dev,\\n",
    '''#ifdef CONFIG_KSU
extern int ksu_handle_input_handle_event(unsigned int *type, unsigned int *code, int *value);
#endif

''',
    "manual input hook declaration",
)
replace_once(
    input_c,
    '''static void input_handle_event(struct input_dev *dev,
			       unsigned int type, unsigned int code, int value)
{
	int disposition = input_get_disposition(dev, type, code, &value);
''',
    '''static void input_handle_event(struct input_dev *dev,
			       unsigned int type, unsigned int code, int value)
{
#ifdef CONFIG_KSU
	ksu_handle_input_handle_event(&type, &code, &value);
#endif
	int disposition = input_get_disposition(dev, type, code, &value);
''',
    "manual input hook call",
)

devpts_c = kernel_root / "fs" / "devpts" / "inode.c"
insert_once(
    devpts_c,
    "void *devpts_get_priv(struct dentry *dentry)\\n",
    '''#ifdef CONFIG_KSU
extern int ksu_handle_devpts(struct inode *inode);
#endif

''',
    "manual devpts hook declaration",
)
replace_once(
    devpts_c,
    '''void *devpts_get_priv(struct dentry *dentry)
{
	if (dentry->d_sb->s_magic != DEVPTS_SUPER_MAGIC)
''',
    '''void *devpts_get_priv(struct dentry *dentry)
{
#ifdef CONFIG_KSU
	ksu_handle_devpts(dentry->d_inode);
#endif
	if (dentry->d_sb->s_magic != DEVPTS_SUPER_MAGIC)
''',
    "manual devpts hook call",
)

print("[kernel-fixes] SukiSU 4.9 source transformation completed")
