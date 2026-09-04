#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
poc_dir="$(cd "$script_dir/.." && pwd)"
cd "$poc_dir/firebase"

if ! java -version >/dev/null 2>&1 && [ -x /opt/homebrew/opt/openjdk@21/bin/java ]; then
  export PATH="/opt/homebrew/opt/openjdk@21/bin:$PATH"
  export JAVA_HOME="/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
fi
if ! java -version >/dev/null 2>&1; then
  echo "Java 21 or newer is required for the Firebase RTDB Emulator." >&2
  exit 1
fi

npx --yes firebase-tools@15.29.0 emulators:exec \
  --only database \
  --project demo-ai-for-god-caption-dev \
  "node --test ../tests/firebase/*.test.mjs"
