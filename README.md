# VideoMosaic Android

Portable Android project scaffold for the automatic video-sample music generator.

## Restore in a fresh Linux x86_64 sandbox

```bash
tar -xzf videomosaic-android-portable.tar.gz
cd videomosaic-android
bash scripts/bootstrap_android.sh
bash scripts/build_debug.sh
```

The bootstrap installs the Android SDK into `$HOME/.android-sdk` by default. The SDK, Gradle caches, and build outputs are intentionally excluded from the portable archive.

## Important commands

```bash
bash scripts/bootstrap_android.sh          # install/repair Android CLI + SDK
bash scripts/check_environment.sh          # verify pinned SDK packages
bash scripts/build_debug.sh                # build app-debug.apk
bash scripts/install_native_toolchain.sh   # optional NDK + CMake for FFmpeg/DSP
bash scripts/package_project.sh            # portable archive without SDK/cache/build junk
```

## Verified build

GitHub Actions run `33809759072` successfully built the project from commit `43b283efcc927a0787e6ac62166d4dfac538e95d` using Android API 36, Build Tools 36.0.0, AGP 9.4.0 and Gradle 9.6.0.

Debug APK: 873210 bytes, SHA-256 `7a1e0b84b09e7fd22883dcee56722ce05414d7a7980ab99f09baea80cbb15fcc`.

See `docs/ENVIRONMENT.md`, `docs/HANDOFF.md`, and `PROJECT_STATE.json`.
