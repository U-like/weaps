#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
source "$PROJECT_ROOT/versions.env"

SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
if [[ -z "$SDK_ROOT" && -f "$PROJECT_ROOT/local.properties" ]]; then
  SDK_ROOT="$(sed -n 's/^sdk.dir=//p' "$PROJECT_ROOT/local.properties" | head -n1)"
fi
if [[ -z "$SDK_ROOT" || ! -x "$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" ]]; then
  bash "$SCRIPT_DIR/bootstrap_android.sh"
  SDK_ROOT="$(sed -n 's/^sdk.dir=//p' "$PROJECT_ROOT/local.properties" | head -n1)"
fi
SDKMANAGER="$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager"

echo "[native] Installing NDK $ANDROID_NDK and CMake $ANDROID_CMAKE"
"$SDKMANAGER" --sdk_root="$SDK_ROOT" \
  "ndk;$ANDROID_NDK" \
  "cmake;$ANDROID_CMAKE"

echo '[native] Native toolchain ready.'
