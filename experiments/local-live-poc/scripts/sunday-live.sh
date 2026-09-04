#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
poc_dir="$(cd "$script_dir/.." && pwd)"
cd "$poc_dir"

mode="run"
if [ "${1:-}" = "--check" ]; then
  mode="check"
elif [ "$#" -gt 0 ]; then
  echo "Usage: ./scripts/sunday-live.sh [--check]" >&2
  exit 2
fi

asr_provider="${LOCAL_LIVE_ASR_PROVIDER:-whisper-cli}"

for command_name in curl npm ollama caffeinate open; do
  if ! command -v "$command_name" >/dev/null; then
    echo "Missing required command: $command_name" >&2
    echo "Run ./scripts/setup-local.sh before Sunday." >&2
    exit 1
  fi
done

asr_model=""
qwen_model=""
asr_model=""
if [ "$asr_provider" = "qwen-mlx-websocket" ]; then
  if ! command -v mlx_audio.server >/dev/null; then
    echo "Missing required command: mlx_audio.server" >&2
    exit 1
  fi
else
  if ! command -v whisper-cli >/dev/null; then
    echo "Missing required command: whisper-cli" >&2
    exit 1
  fi
fi

if [ ! -x .venv/bin/python ] || [ ! -d node_modules ]; then
  echo "Local dependencies are not ready. Run ./scripts/setup-local.sh first." >&2
  exit 1
fi

if [ "$asr_provider" = "qwen-mlx-websocket" ]; then
  qwen_model="${LOCAL_LIVE_QWEN_ASR_MODEL:-}"
  if [ -z "$qwen_model" ] || [ ! -d "$qwen_model" ]; then
    echo "LOCAL_LIVE_QWEN_ASR_MODEL must name an installed MLX Qwen model directory." >&2
    exit 1
  fi
  asr_model_file="$qwen_model"
elif [ -n "${LOCAL_LIVE_ASR_MODEL:-}" ]; then
  asr_model="$LOCAL_LIVE_ASR_MODEL"
elif [ -f artifacts/models/ggml-small.en.bin ]; then
  asr_model="artifacts/models/ggml-small.en.bin"
else
  asr_model="artifacts/models/ggml-base.en.bin"
fi

if [ "$asr_provider" != "qwen-mlx-websocket" ]; then
if [ "$asr_provider" != "qwen-mlx-websocket" ]; then
  case "$asr_model" in
    /*) asr_model_file="$asr_model" ;;
    *) asr_model_file="$poc_dir/$asr_model" ;;
  esac
  if [ ! -f "$asr_model_file" ]; then
    echo "ASR model is missing: $asr_model_file" >&2
    echo "Run ./scripts/setup-local.sh first or set LOCAL_LIVE_ASR_MODEL." >&2
    exit 1
  fi
fi
fi

translation_model="${LOCAL_LIVE_OLLAMA_MODEL:-sermon-milmmt-46-4b-v1-q8:benchmark}"
session_root="${LOCAL_LIVE_SESSION_ROOT:-$poc_dir/artifacts/sessions}"
mkdir -p "$session_root"
probe_file="$(mktemp "$session_root/.sunday-preflight.XXXXXX")"
rm -f "$probe_file"

available_kb="$(df -Pk "$session_root" | awk 'NR == 2 {print $4}')"
minimum_kb=10485760
if [ -z "$available_kb" ] || [ "$available_kb" -lt "$minimum_kb" ]; then
  echo "Less than 10 GiB is available for Sunday recordings: $session_root" >&2
  exit 1
fi

ollama_ready() {
  curl -fsS --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1
}

if ! ollama_ready; then
  if [ "$mode" = "check" ]; then
    echo "Ollama is not running." >&2
    exit 1
  fi
  echo "Starting Ollama…"
  open -gja Ollama
  for _ in $(seq 1 30); do
    if ollama_ready; then
      break
    fi
    sleep 1
  done
fi
if ! ollama_ready; then
  echo "Ollama did not become ready within 30 seconds." >&2
  exit 1
fi

if ! ollama list | awk -v model="$translation_model" 'NR > 1 && $1 == model { found = 1 } END { exit !found }'; then
  echo "Configured Ollama model is not installed: $translation_model" >&2
  exit 1
fi

echo "Sunday preflight passed."
echo "ASR: $asr_provider ($asr_model_file)"
echo "Translation: $translation_model"
echo "Sessions: $session_root"
echo "Free disk: $((available_kb / 1024 / 1024)) GiB"

if [ "$mode" = "check" ]; then
  exit 0
fi

gateway_ready() {
  curl -fsS --max-time 2 http://127.0.0.1:8766/api/health 2>/dev/null \
    | .venv/bin/python -c 'import json, sys; raise SystemExit(json.load(sys.stdin).get("status") != "ready")' \
    >/dev/null 2>&1
}

ui_ready() {
  curl -fsS --max-time 2 http://127.0.0.1:4173/ >/dev/null 2>&1
}

if gateway_ready && ui_ready; then
  echo "Sunday live captions are already running."
  open http://127.0.0.1:4173/
  exit 0
fi

runtime_dir="${TMPDIR:-/tmp}/sermon-live-caption-poc"
pid_file="$runtime_dir/sunday-live.pid"
mkdir -p "$runtime_dir"

if [ -f "$pid_file" ]; then
  existing_pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ "$existing_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null; then
    echo "Sunday live captions already have a running launcher (PID $existing_pid)." >&2
    exit 1
  fi
  rm -f "$pid_file"
fi
printf '%s\n' "$$" > "$pid_file"

caffeinate -di -w $$ &
caffeinate_pid=$!
runtime_pid=""

cleanup() {
  if [ -n "$runtime_pid" ]; then
    kill "$runtime_pid" 2>/dev/null || true
  fi
  kill "$caffeinate_pid" 2>/dev/null || true
  if [ "$(cat "$pid_file" 2>/dev/null || true)" = "$$" ]; then
    rm -f "$pid_file"
  fi
}
trap cleanup EXIT INT TERM

LOCAL_LIVE_ASR_MODEL="$asr_model" \
LOCAL_LIVE_ASR_PROVIDER="$asr_provider" \
LOCAL_LIVE_QWEN_ASR_MODEL="${qwen_model:-}" \
LOCAL_LIVE_MLX_AUDIO_URL="${LOCAL_LIVE_MLX_AUDIO_URL:-ws://127.0.0.1:18766/v1/audio/transcriptions/realtime}" \
LOCAL_LIVE_OLLAMA_MODEL="$translation_model" \
LOCAL_LIVE_SESSION_ROOT="$session_root" \
  ./scripts/run-local.sh &
runtime_pid=$!

for _ in $(seq 1 120); do
  if gateway_ready && ui_ready; then
    echo "Sunday live captions are ready: http://127.0.0.1:4173/"
    echo "Keep this Terminal window open. Stop the recording in the page before pressing Control-C."
    open http://127.0.0.1:4173/
    wait "$runtime_pid"
    exit $?
  fi
  if ! kill -0 "$runtime_pid" 2>/dev/null; then
    echo "The local live-caption runtime exited before it became ready." >&2
    wait "$runtime_pid"
    exit $?
  fi
  sleep 1
done

echo "The local live-caption runtime did not become ready within 120 seconds." >&2
exit 1
