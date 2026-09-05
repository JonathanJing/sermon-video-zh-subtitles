#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
poc_dir="$(cd "$script_dir/.." && pwd)"
cd "$poc_dir"

runtime_dir="${TMPDIR:-/tmp}/sermon-live-caption-poc"
umask 077
mkdir -p "$runtime_dir"
log_root="${LOCAL_LIVE_RUNTIME_LOG_ROOT:-$poc_dir/artifacts/runtime}"
mkdir -p "$log_root"
log_dir="$(mktemp -d "$log_root/$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")"
log_dir="$(cd "$log_dir" && pwd)"
export LOCAL_LIVE_RUNTIME_LOG_DIRECTORY="$log_dir"
mlx_audio_log="$log_dir/mlx-audio.log"
exec > >(tee -a "$log_dir/supervisor.log") 2>&1
echo "Runtime logs: $log_dir"

asr_model="${LOCAL_LIVE_ASR_MODEL:-artifacts/models/ggml-base.en.bin}"
asr_provider="${LOCAL_LIVE_ASR_PROVIDER:-whisper-cli}"

if [ ! -x .venv/bin/python ]; then
  echo "Run ./scripts/setup-local.sh first." >&2
  exit 1
fi

gateway_args=(--asr-provider "$asr_provider")
mlx_audio_pid=""
mlx_audio_server=""
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
  if [ -x .venv/bin/mlx_audio.server ]; then
    mlx_audio_server=".venv/bin/mlx_audio.server"
  elif command -v mlx_audio.server >/dev/null; then
    mlx_audio_server="$(command -v mlx_audio.server)"
  else
    echo "mlx_audio.server is required for the Qwen ASR provider." >&2
    exit 1
  fi
  start_mlx_audio() {
    printf '%s starting MLX Audio\n' "$(date -u +%FT%TZ)" >> "$mlx_audio_log"
    "$mlx_audio_server" --host 127.0.0.1 --port 18766 --workers 1 \
      >> "$mlx_audio_log" 2>&1 &
    mlx_audio_pid=$!
  }
  wait_mlx_audio_ready() {
    for _ in $(seq 1 120); do
      if mlx_audio_ready; then
        return 0
      fi
      if [ -n "$mlx_audio_pid" ] && ! kill -0 "$mlx_audio_pid" 2>/dev/null; then
        return 1
      fi
      sleep 1
    done
    return 1
  }
  if ! mlx_audio_ready; then
    start_mlx_audio
    if ! wait_mlx_audio_ready; then
      echo "MLX Audio did not become ready within 120 seconds." >&2
      wait "$mlx_audio_pid" 2>/dev/null || true
      exit 1
    fi
  else
    echo "Reusing external MLX Audio; its stdout is not captured by this launcher." >> "$mlx_audio_log"
  fi
else
  if [ ! -f "$asr_model" ]; then
    echo "ASR model is missing: $asr_model" >&2
    exit 1
  fi
  gateway_args+=(--asr-model "$asr_model")
fi
weekly_pack="${LOCAL_LIVE_WEEKLY_PACK:-artifacts/weekly-pack.json}"
if [ -f "$weekly_pack" ]; then
  gateway_args+=(--pack "$weekly_pack")
else
  # Override gateway.py's environment-backed default when a direct caller leaves
  # LOCAL_LIVE_WEEKLY_PACK pointing at a missing optional pack.
  gateway_args+=(--pack "")
fi
gateway_args+=(--context-policy "${LOCAL_LIVE_CONTEXT_POLICY:-none}")

restart_exit_code=75
gateway_pid=""
start_gateway() {
  printf '%s starting Gateway\n' "$(date -u +%FT%TZ)" >> "$log_dir/gateway.log"
  PYTHONUNBUFFERED=1 .venv/bin/python -m backend.gateway "${gateway_args[@]}" >> "$log_dir/gateway.log" 2>&1 &
  gateway_pid=$!
}

start_gateway
npm run dev -- --host 127.0.0.1 --port 4173 --strictPort >> "$log_dir/frontend.log" 2>&1 &
vite_pid=$!

cleanup() {
  trap - EXIT INT TERM
  kill "$gateway_pid" "$vite_pid" 2>/dev/null || true
  if [ -n "$mlx_audio_pid" ]; then
    kill "$mlx_audio_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Local live captions: http://127.0.0.1:4173/"
unexpected_restarts=0
mlx_audio_restarts=0
while kill -0 "$vite_pid" 2>/dev/null; do
  if [ "$asr_provider" = "qwen-mlx-websocket" ] && ! mlx_audio_ready; then
    previous_status="external_or_unknown"
    if [ -n "$mlx_audio_pid" ]; then
      set +e
      wait "$mlx_audio_pid" 2>/dev/null
      previous_status=$?
      set -e
    fi
    mlx_audio_restarts=$((mlx_audio_restarts + 1))
    if [ "$mlx_audio_restarts" -gt 3 ]; then
      echo "MLX Audio exited repeatedly; stop and start the POC again. Log: $mlx_audio_log" >&2
      exit 1
    fi
    echo "MLX Audio unavailable (status $previous_status); restarting ($mlx_audio_restarts/3). Log: $mlx_audio_log" >&2
    start_mlx_audio
    if ! wait_mlx_audio_ready; then
      echo "MLX Audio restart did not become ready. Log: $mlx_audio_log" >&2
      kill "$mlx_audio_pid" 2>/dev/null || true
      wait "$mlx_audio_pid" 2>/dev/null || true
      sleep 1
      continue
    fi
    echo "MLX Audio recovered."
  fi

  if kill -0 "$gateway_pid" 2>/dev/null; then
    sleep 1
    continue
  fi
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
