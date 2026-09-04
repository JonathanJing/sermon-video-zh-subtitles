#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
poc_dir="$(cd "$script_dir/.." && pwd)"
cd "$poc_dir"

asr_model="${LOCAL_LIVE_ASR_MODEL:-artifacts/models/ggml-base.en.bin}"

if [ ! -x .venv/bin/python ] || [ ! -f "$asr_model" ]; then
  echo "Run ./scripts/setup-local.sh first." >&2
  exit 1
fi

gateway_args=(--asr-model "$asr_model")
if [ -f artifacts/weekly-pack.json ]; then
  gateway_args+=(--pack artifacts/weekly-pack.json)
fi

.venv/bin/python -m backend.gateway "${gateway_args[@]}" &
gateway_pid=$!
npm run dev -- --host 0.0.0.0 --port 4173 --strictPort &
vite_pid=$!

cleanup() {
  kill "$gateway_pid" "$vite_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Local live captions: http://127.0.0.1:4173/"
while kill -0 "$gateway_pid" 2>/dev/null && kill -0 "$vite_pid" 2>/dev/null; do
  sleep 1
done
