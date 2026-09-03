# Handoff

## Current state

VideoMosaic Android has reached the first real mosaic-generation MVP.

Implemented:

- reproducible Android SDK/Gradle bootstrap and GitHub Actions build;
- persistent JSON project model;
- system audio picker and multi-select video picker;
- persistable content URI permissions;
- media metadata inspection;
- PCM decode through Android `MediaExtractor` + `MediaCodec`;
- RMS/peak and onset detection;
- per-event YIN pitch estimation instead of only whole-file pitch;
- tone-event timeline containing start time, duration, pitch, MIDI note and confidence;
- automatic target-note to source-video-segment matching;
- repetition and duration penalties in the matcher;
- exact source interval clipping with Media3 `ClippingConfiguration`;
- source clip speed fitting to target-event duration with `EditedMediaItem.setSpeed()`;
- hard-cut sequential video/audio composition;
- internal Media3 `CompositionPlayer` preview with playback controls;
- MP4 export with Media3 `Transformer`.

Media3 is pinned to `1.11.0`.

## Current sandbox limitation

The ChatGPT sandbox shell cannot resolve public download hosts such as `dl.google.com`, so local Android SDK installation remains blocked. Development and APK verification use GitHub Actions.

## Latest verified build

GitHub Actions run `33815388830` completed successfully from commit `e8f0abb27e0d0e504102b9e23934da18e07a8c5c`.

Application version: `0.5.0-mosaic`
Test application id: `dev.videomosaic.app.v050`

Verified debug APK:

- size: 5860700 bytes
- SHA-256: `b6a56691ac364c037891d3e65f8440717b3c2f40665a7caeb895e50958dbf163`

The test application id is intentionally separate so it installs alongside the earlier control build and avoids debug-signature conflicts between ephemeral GitHub runners.

## Runtime workflow

1. Pick target music.
2. Analyze target music. It is split at detected attacks and pitch is estimated for each event.
3. Import source videos.
4. Analyze the video library. Each video's audio is split into tone events with timestamps and pitch metadata.
5. Tap `Подобрать ноты и запустить предпросмотр`.
6. The matcher selects the closest source event for every target event.
7. Each source video is clipped to a timestamp range and speed-fitted so its output duration equals the target event duration.
8. `CompositionPlayer` previews the sequential hard-cut composition. Audio comes from the selected video fragments, not from the original target song.
9. Tap `Экспортировать MP4` to render the same `Composition` with `Transformer`.

## Important current limitations

- Melody/onset extraction is still heuristic, especially for dense/polyphonic mastered songs.
- Pitch is matched but not yet pitch-corrected. A source fragment may therefore be near the target note rather than exact.
- Duration is fitted by playback speed; future versions should combine trimming, looping/freeze strategies and time-stretching to avoid extreme speed changes.
- There is no manual per-note replacement editor yet.
- Export/runtime behavior must be tested on physical devices and with varied source codecs/resolutions.

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

Runtime-test 0.5.0 on a physical Android device. Then add pitch correction/time-stretching and a manual timeline editor where a user can replace an automatically chosen fragment for an individual target note.
