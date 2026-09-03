#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
source "$PROJECT_ROOT/versions.env"
cd "$PROJECT_ROOT"

if [[ ! -f local.properties || ! -f gradle/wrapper/gradle-wrapper.jar ]]; then
  ./scripts/bootstrap_android.sh
fi

CACHE_GRADLE="${XDG_CACHE_HOME:-$HOME/.cache}/videomosaic-bootstrap/gradle-${GRADLE_VERSION}/bin/gradle"
if [[ -x "$CACHE_GRADLE" ]]; then
  "$CACHE_GRADLE" --no-daemon :app:assembleDebug
else
  ./gradlew --no-daemon :app:assembleDebug
fi

APK="$PROJECT_ROOT/app/build/outputs/apk/debug/app-debug.apk"
[[ -f "$APK" ]] || { echo "Build completed but APK not found: $APK" >&2; exit 1; }
echo "APK: $APK"
