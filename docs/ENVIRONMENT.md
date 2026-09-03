# Build environment

The project is intentionally reproducible without Android Studio or an emulator.

Pinned versions are in `versions.env`:

- Android Gradle Plugin: 9.4.0
- Gradle: 9.6.0, distribution checksum pinned
- compileSdk / targetSdk: 36
- Build Tools: 36.0.0
- minimum Android: API 26
- host JDK: 17 or newer
- Android command-line tools: Linux build 15859902, checksum pinned
- optional NDK: 28.2.13676358
- optional CMake: 3.22.1

## What is portable

The source tree contains source code, Gradle launcher scripts, wrapper configuration, bootstrap scripts, documentation and version pins. It does not contain Android SDK packages, Gradle caches, `local.properties`, APKs, or build directories.

## Fresh sandbox recovery

```bash
bash scripts/bootstrap_android.sh
bash scripts/build_debug.sh
```

For the future FFmpeg/C++ layer:

```bash
bash scripts/install_native_toolchain.sh
```

`bootstrap_android.sh` is idempotent. Existing packages are reused and only missing SDK pieces are downloaded.

## SDK location

Default:

```text
$HOME/.android-sdk
```

Override with:

```bash
ANDROID_SDK_ROOT=/some/path bash scripts/bootstrap_android.sh
```

## Verified CI

GitHub Actions run `33809185671` successfully built the debug APK on Ubuntu 24.04 using API 36 and Build Tools 36.0.0.
