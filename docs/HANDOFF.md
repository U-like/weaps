# Handoff

## Current state

- Portable Android project scaffold created.
- Linux x86_64 bootstrap pins the Android command-line tools archive and checksum.
- SDK packages are installed outside the project and can be reconstructed.
- Gradle version, distribution checksum, and wrapper JAR checksum are pinned.
- Minimal Kotlin Android activity exists and has been built into a real APK.
- Optional NDK/CMake installer is ready for the later FFmpeg/DSP layer.

## Current sandbox limitation

The current ChatGPT sandbox shell cannot resolve public download hosts such as `dl.google.com`, so a local SDK install is blocked there. This does not block development because the same source tree has been verified on GitHub Actions.

## Verified build

GitHub Actions run `33809185671` completed successfully on Ubuntu 24.04. The runner installed Android command-line tools, API 36, Build Tools 36.0.0, generated and verified Gradle Wrapper 9.6.0, passed environment checks, and completed `:app:assembleDebug`.

Verified debug APK:

- size: 873210 bytes
- SHA-256: `e914efe13489c7893b58344f336a496e8fa5a0da13f05ca6937e1e270d3b0d30`

`buildVerified=true` in `PROJECT_STATE.json` is therefore justified.

## Resume procedure in a fresh sandbox with outbound internet

```bash
bash scripts/bootstrap_android.sh
bash scripts/check_environment.sh
bash scripts/build_debug.sh
```

If native development is needed:

```bash
bash scripts/install_native_toolchain.sh
```

## CI fallback

`.github/workflows/android-build.yml` provisions Android CLI tools, installs the pinned platform/build-tools, verifies Gradle, builds the APK and uploads `videomosaic-debug-apk`.

## Next application milestone

Build the real VideoMosaic project shell: media picker, project model, sample library screen, and audio-analysis module. Keep FFmpeg/NDK isolated behind a native media module.
