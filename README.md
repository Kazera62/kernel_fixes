# Kazera Kernel Fixes

Centralized compatibility fixes for Kazera kernel CI.

The main kernel workflow pins this repository to an exact commit and calls the scripts in this repository after root integration and before Kconfig/build.

## Design

The fix engine verifies the real source path used by Kbuild.

For SukiSU-Ultra, `drivers/kernelsu` is a symlink. The SukiSU fix is applied to the resolved symlink target and then verified through that same path. This prevents a patch from being reported as successful while the compiler still sees the old source.

## Current target

- Samsung Galaxy M11/A11, SDM450
- Linux 4.9
- SukiSU-Ultra, KPM off/on
- ReSukiSU + SUSFS

## Scripts

`scripts/apply-fixes.sh` applies the required compatibility changes.

`scripts/verify-fixes.sh` verifies the changes in the exact kernel source tree before compilation.

Third-party patch URLs are pinned to immutable upstream commit paths inside the fix engine; the main kernel workflow does not contain patch logic.
