# VideoMosaic Android

Portable Android project scaffold for the automatic video-sample music generator.

## Restore in a fresh Linux x86_64 sandbox

```bash
tar -xzf videomosaic-android-portable.tar.gz
cd videomosaic-android
./scripts/bootstrap_android.sh
./scripts/build_debug.sh
```

The bootstrap installs the Android SDK into `$HOME/.android-sdk` by default. The SDK, Gradle caches, and build outputs are intentionally excluded from the portable archive.

## Important commands

```bash
./scripts/bootstrap_android.sh   # install/repair the Android CLI build environment
./scripts/check_environment.sh   # verify expected tools and pinned SDK packages
./scripts/build_debug.sh         # build app-debug.apk
./scripts/package_project.sh     # create a transfer archive without SDK/cache/build junk
```

See `docs/ENVIRONMENT.md` and `docs/HANDOFF.md`.
