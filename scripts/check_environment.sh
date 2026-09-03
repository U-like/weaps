#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
source "$PROJECT_ROOT/versions.env"

SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
if [[ -z "$SDK_ROOT" && -f "$PROJECT_ROOT/local.properties" ]]; then
  SDK_ROOT="$(sed -n 's/^sdk.dir=//p' "$PROJECT_ROOT/local.properties" | head -n1)"
fi

FAIL=0
check_path() {
  local label="$1" path="$2"
  if [[ -e "$path" ]]; then
    printf '[ok]   %-24s %s\n' "$label" "$path"
  else
    printf '[FAIL] %-24s %s\n' "$label" "$path"
    FAIL=1
  fi
}

printf 'VideoMosaic Android environment\n'
printf '%s\n' '--------------------------------'
printf '[info] Java: %s\n' "$(java -version 2>&1 | head -n1)"
printf '[info] SDK root: %s\n' "${SDK_ROOT:-<not found>}"

if [[ -z "$SDK_ROOT" ]]; then
  echo '[FAIL] SDK root is not configured.'
  exit 1
fi

check_path "sdkmanager" "$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager"
check_path "adb" "$SDK_ROOT/platform-tools/adb"
check_path "android-${ANDROID_COMPILE_SDK}" "$SDK_ROOT/platforms/android-${ANDROID_COMPILE_SDK}/android.jar"
check_path "build-tools ${ANDROID_BUILD_TOOLS}" "$SDK_ROOT/build-tools/${ANDROID_BUILD_TOOLS}/aapt2"
check_path "Gradle wrapper" "$PROJECT_ROOT/gradlew"
check_path "Gradle wrapper JAR" "$PROJECT_ROOT/gradle/wrapper/gradle-wrapper.jar"

if (( FAIL != 0 )); then
  echo 'Environment is incomplete. Run ./scripts/bootstrap_android.sh'
  exit 1
fi

echo 'Environment is complete.'
