# Handoff

## Current state

VideoMosaic Android is now a functional media-analysis MVP rather than a build scaffold.

Implemented:

- reproducible Android SDK/Gradle bootstrap and GitHub Actions build;
- persistent JSON project model;
- system audio picker;
- multi-select video picker;
- persistable content URI permissions;
- media metadata inspection (name, size, duration, video dimensions);
- PCM decode through Android `MediaExtractor` + `MediaCodec`;
- RMS and peak measurement;
- onset detection;
- batch audio analysis for imported video samples;
- YIN fundamental pitch estimation;
- conversion of detected pitch to MIDI note metadata and confidence.

No external DSP dependency is required for the current analysis layer.

## Current sandbox limitation

The current ChatGPT sandbox shell cannot resolve public download hosts such as `dl.google.com`, so a local SDK install remains blocked. Development and APK verification use GitHub Actions, where the pinned Android toolchain is installed successfully.

## Latest verified build

GitHub Actions run `33811946698` completed successfully from commit `8a8a1abcb3700226ad72b654d1a4d89cb9c54658`.

Application version: `0.4.0`

Verified debug APK:

- size: 915564 bytes
- SHA-256: `55d67cb65aac529f8cd923c4f7156256d9555e3b66e9ae28312b33a048775af5`

## What the app can do now

1. Pick a target audio file with Android Storage Access Framework.
2. Pick multiple source videos.
3. Keep access to those files across app restarts.
4. Persist the project in app storage.
5. Inspect media metadata.
6. Decode the target song or source-video audio to PCM.
7. Detect approximate transient/onset positions.
8. Measure RMS and peak level.
9. Estimate a dominant fundamental frequency with a bounded-cost YIN implementation.
10. Display approximate note, frequency, and pitch confidence for analyzed media.

The current pitch value is a whole-media summary. It is intentionally not yet treated as a final note label for long or polyphonic recordings.

## Resume procedure in a fresh sandbox with outbound internet

```bash
bash scripts/bootstrap_android.sh
bash scripts/check_environment.sh
bash scripts/build_debug.sh
```

For native work later:

```bash
bash scripts/install_native_toolchain.sh
```

## CI fallback

`.github/workflows/android-build.yml` provisions Android CLI tools, installs the pinned platform/build-tools, verifies Gradle, builds the APK and uploads `videomosaic-debug-apk`.

## Next application milestone

Segment each source video around detected onsets, estimate pitch per segment instead of per whole file, then create the first note-to-sample matching score. After that the project can generate a real automatic sample timeline rather than merely analyze imported media.
