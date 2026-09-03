#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
source "$PROJECT_ROOT/versions.env"

JAR="$PROJECT_ROOT/gradle/wrapper/gradle-wrapper.jar"
if [[ -f "$JAR" ]]; then
  ACTUAL_SHA="$(sha256sum "$JAR" | awk '{print $1}')"
  if [[ "$ACTUAL_SHA" == "$GRADLE_WRAPPER_JAR_SHA256" ]]; then
    echo '[gradle] Verified existing Gradle Wrapper JAR.'
    chmod +x "$PROJECT_ROOT/gradlew"
    exit 0
  fi
  echo '[gradle] Existing wrapper JAR checksum is wrong; regenerating it.' >&2
  rm -f "$JAR"
fi

for tool in curl unzip sha256sum java; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Missing required tool: $tool" >&2; exit 1; }
done

CACHE_ROOT="${XDG_CACHE_HOME:-$HOME/.cache}/videomosaic-bootstrap"
ARCHIVE="$CACHE_ROOT/gradle-${GRADLE_VERSION}-bin.zip"
GRADLE_HOME="$CACHE_ROOT/gradle-${GRADLE_VERSION}"
URL="https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip"
mkdir -p "$CACHE_ROOT"

if [[ ! -f "$ARCHIVE" ]]; then
  printf '[gradle] Downloading Gradle %s\n' "$GRADLE_VERSION"
  curl --fail --location --retry 4 --retry-delay 2 "$URL" -o "$ARCHIVE"
else
  echo '[gradle] Using cached Gradle distribution.'
fi

ACTUAL_SHA="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
if [[ "$ACTUAL_SHA" != "$GRADLE_BIN_SHA256" ]]; then
  rm -f "$ARCHIVE"
  echo 'Gradle distribution checksum mismatch.' >&2
  exit 1
fi

if [[ ! -x "$GRADLE_HOME/bin/gradle" ]]; then
  TMP_UNZIP="$(mktemp -d)"
  trap 'rm -rf "$TMP_UNZIP"' EXIT
  unzip -q "$ARCHIVE" -d "$TMP_UNZIP"
  rm -rf "$GRADLE_HOME"
  mv "$TMP_UNZIP/gradle-${GRADLE_VERSION}" "$GRADLE_HOME"
  rm -rf "$TMP_UNZIP"
  trap - EXIT
fi

TMP_PROJECT="$(mktemp -d)"
trap 'rm -rf "$TMP_PROJECT"' EXIT
printf 'rootProject.name = "wrapper-bootstrap"\n' > "$TMP_PROJECT/settings.gradle"
printf '' > "$TMP_PROJECT/build.gradle"
(
  cd "$TMP_PROJECT"
  "$GRADLE_HOME/bin/gradle" --no-daemon wrapper \
    --gradle-version "$GRADLE_VERSION" \
    --distribution-type bin
)

mkdir -p "$PROJECT_ROOT/gradle/wrapper"
cp "$TMP_PROJECT/gradlew" "$PROJECT_ROOT/gradlew"
cp "$TMP_PROJECT/gradlew.bat" "$PROJECT_ROOT/gradlew.bat"
cp "$TMP_PROJECT/gradle/wrapper/gradle-wrapper.jar" "$PROJECT_ROOT/gradle/wrapper/gradle-wrapper.jar"
cp "$TMP_PROJECT/gradle/wrapper/gradle-wrapper.properties" "$PROJECT_ROOT/gradle/wrapper/gradle-wrapper.properties"
chmod +x "$PROJECT_ROOT/gradlew"

if grep -q '^distributionSha256Sum=' "$PROJECT_ROOT/gradle/wrapper/gradle-wrapper.properties"; then
  sed -i "s/^distributionSha256Sum=.*/distributionSha256Sum=$GRADLE_BIN_SHA256/" \
    "$PROJECT_ROOT/gradle/wrapper/gradle-wrapper.properties"
else
  printf 'distributionSha256Sum=%s\n' "$GRADLE_BIN_SHA256" >> \
    "$PROJECT_ROOT/gradle/wrapper/gradle-wrapper.properties"
fi

ACTUAL_JAR_SHA="$(sha256sum "$PROJECT_ROOT/gradle/wrapper/gradle-wrapper.jar" | awk '{print $1}')"
if [[ "$ACTUAL_JAR_SHA" != "$GRADLE_WRAPPER_JAR_SHA256" ]]; then
  echo "Generated Gradle Wrapper JAR checksum mismatch: $ACTUAL_JAR_SHA" >&2
  exit 1
fi

echo '[gradle] Canonical Gradle Wrapper generated and verified.'
