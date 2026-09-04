#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
poc_dir="$(cd "$script_dir/.." && pwd)"
cd "$poc_dir"

asr_model="${LOCAL_LIVE_ASR_MODEL:-artifacts/models/ggml-base.en.bin}"
asr_provider="${LOCAL_LIVE_ASR_PROVIDER:-whisper-cli}"

if [ ! -x .venv/bin/python ]; then
  echo "Run ./scripts/setup-local.sh first." >&2
  exit 1
fi

gateway_args=(--asr-provider "$asr_provider")
mlx_audio_pid=""
if [ "$asr_provider" = "qwen-mlx-websocket" ]; then
  qwen_model="${LOCAL_LIVE_QWEN_ASR_MODEL:-}"
  if [ -z "$qwen_model" ] || [ ! -d "$qwen_model" ]; then
    echo "LOCAL_LIVE_QWEN_ASR_MODEL must name an installed MLX Qwen model directory." >&2
    exit 1
  fi
  gateway_args+=(--mlx-audio-model "$qwen_model")
  gateway_args+=(--mlx-audio-url "${LOCAL_LIVE_MLX_AUDIO_URL:-ws://127.0.0.1:18766/v1/audio/transcriptions/realtime}")
  if [ -z "${LOCAL_LIVE_VAD_THRESHOLD_RMS:-}" ]; then
    # The Qwen endpoint can turn quiet room noise into short lexical finals
    # (observed as "The."). 450 rejects that noise on the MacBook built-in
    # microphone while retaining the acoustic sermon replay signal.
    gateway_args+=(--vad-threshold-rms 450)
  fi
  mlx_audio_ready() {
    .venv/bin/python -c 'import socket; s=socket.create_connection(("127.0.0.1", 18766), .5); s.close()' \
      >/dev/null 2>&1
  }
  if ! mlx_audio_ready; then
    if [ -x .venv/bin/mlx_audio.server ]; then
      mlx_audio_server=".venv/bin/mlx_audio.server"
    elif command -v mlx_audio.server >/dev/null; then
      mlx_audio_server="$(command -v mlx_audio.server)"
    else
      echo "mlx_audio.server is required for the Qwen ASR provider." >&2
      exit 1
    fi
    "$mlx_audio_server" --host 127.0.0.1 --port 18766 --workers 1 &
    mlx_audio_pid=$!
    for _ in $(seq 1 120); do
      if mlx_audio_ready; then
        break
      fi
      if ! kill -0 "$mlx_audio_pid" 2>/dev/null; then
        echo "MLX Audio exited before becoming ready." >&2
        wait "$mlx_audio_pid"
        exit $?
      fi
      sleep 1
    done
    if ! mlx_audio_ready; then
      echo "MLX Audio did not become ready within 120 seconds." >&2
      exit 1
    fi
  fi
else
  if [ ! -f "$asr_model" ]; then
    echo "ASR model is missing: $asr_model" >&2
    exit 1
  fi
  gateway_args+=(--asr-model "$asr_model")
fi
if [ -f artifacts/weekly-pack.json ]; then
  gateway_args+=(--pack artifacts/weekly-pack.json)
fi

restart_exit_code=75
gateway_pid=""
start_gateway() {
  .venv/bin/python -m backend.gateway "${gateway_args[@]}" &
  gateway_pid=$!
}

start_gateway
npm run dev -- --host 0.0.0.0 --port 4173 --strictPort &
vite_pid=$!

cleanup() {
  kill "$gateway_pid" "$vite_pid" 2>/dev/null || true
  if [ -n "$mlx_audio_pid" ]; then
    kill "$mlx_audio_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "Local live captions: http://127.0.0.1:4173/"
unexpected_restarts=0
while kill -0 "$vite_pid" 2>/dev/null; do
  while kill -0 "$gateway_pid" 2>/dev/null && kill -0 "$vite_pid" 2>/dev/null; do
    sleep 1
  done
  if ! kill -0 "$vite_pid" 2>/dev/null; then
    break
  fi
  set +e
  wait "$gateway_pid"
  gateway_status=$?
  set -e

  if ! kill -0 "$vite_pid" 2>/dev/null; then
    break
  fi
  if [ "$gateway_status" -eq "$restart_exit_code" ]; then
    unexpected_restarts=0
    echo "Gateway restart requested; starting it again."
    start_gateway
    continue
  fi
  unexpected_restarts=$((unexpected_restarts + 1))
  if [ "$unexpected_restarts" -gt 3 ]; then
    echo "Gateway exited repeatedly; stop and start the POC again." >&2
    exit "$gateway_status"
  fi
  echo "Gateway exited unexpectedly (status $gateway_status); restarting ($unexpected_restarts/3)." >&2
  sleep 1
  start_gateway
done
