#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
OUT="${1:-$(dirname "$PROJECT_ROOT")/videomosaic-android-portable.tar.gz}"

cd "$(dirname "$PROJECT_ROOT")"
tar \
  --exclude='.git' \
  --exclude='.gradle' \
  --exclude='local.properties' \
  --exclude='*/build' \
  --exclude='*.apk' \
  -czf "$OUT" "$(basename "$PROJECT_ROOT")"

echo "$OUT"
