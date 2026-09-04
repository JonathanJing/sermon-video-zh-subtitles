#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
poc_dir="$(cd "$script_dir/.." && pwd)"
cd "$poc_dir"

firebase_runtime_env="$poc_dir/firebase/runtime.env"
if [ -f "$firebase_runtime_env" ]; then
  set -a
  # Local, git-ignored deployment values used by the double-click launcher.
  # shellcheck disable=SC1090
  . "$firebase_runtime_env"
  set +a
fi

mode="run"
if [ "${1:-}" = "--check" ]; then
  mode="check"
elif [ "$#" -gt 0 ]; then
  echo "Usage: ./scripts/sunday-live.sh [--check]" >&2
  exit 2
fi

default_qwen_model="${HOME}/Library/Caches/sermon-video-zh-subtitles/models/qwen3-asr-0.6b-8bit-89e96d92"
qwen_model="${LOCAL_LIVE_QWEN_ASR_MODEL:-$default_qwen_model}"
if [ -n "${LOCAL_LIVE_ASR_PROVIDER:-}" ]; then
  asr_provider="$LOCAL_LIVE_ASR_PROVIDER"
elif { [ -x .venv/bin/mlx_audio.server ] || command -v mlx_audio.server >/dev/null; } && [ -d "$qwen_model" ]; then
  asr_provider="qwen-mlx-websocket"
else
  asr_provider="whisper-cli"
fi

for command_name in curl npm ollama caffeinate open; do
  if ! command -v "$command_name" >/dev/null; then
    echo "Missing required command: $command_name" >&2
    echo "Run ./scripts/setup-local.sh before Sunday." >&2
    exit 1
  fi
done

firebase_database_url="${LOCAL_LIVE_FIREBASE_DATABASE_URL:-}"
firebase_viewer_url="${LOCAL_LIVE_FIREBASE_VIEWER_URL:-}"
firebase_public_mode="disabled"
if { [ -n "$firebase_database_url" ] && [ -z "$firebase_viewer_url" ]; } || \
   { [ -z "$firebase_database_url" ] && [ -n "$firebase_viewer_url" ]; }; then
  echo "Firebase public captions require both database and viewer URLs." >&2
  exit 1
fi
if [ -n "$firebase_database_url" ]; then
  if [ -z "${LOCAL_LIVE_FIREBASE_ACCESS_TOKEN:-}" ]; then
    if ! command -v gcloud >/dev/null; then
      echo "Firebase public captions require gcloud for short-lived credentials." >&2
      exit 1
    fi
    firebase_auth_command=(gcloud auth print-access-token)
    if [ -n "${LOCAL_LIVE_FIREBASE_IMPERSONATE_SERVICE_ACCOUNT:-}" ]; then
      firebase_auth_command+=(
        "--impersonate-service-account=${LOCAL_LIVE_FIREBASE_IMPERSONATE_SERVICE_ACCOUNT}"
      )
    fi
    if ! "${firebase_auth_command[@]}" >/dev/null 2>&1; then
      echo "Firebase credentials are unavailable; run gcloud auth login and retry." >&2
      exit 1
    fi
  fi
  firebase_public_mode="$firebase_viewer_url"
fi

asr_model=""
if [ "$asr_provider" = "qwen-mlx-websocket" ]; then
  if [ ! -x .venv/bin/mlx_audio.server ] && ! command -v mlx_audio.server >/dev/null; then
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

weekly_pack="${LOCAL_LIVE_WEEKLY_PACK:-$poc_dir/artifacts/weekly-pack.json}"
requested_context_policy="${LOCAL_LIVE_CONTEXT_POLICY:-}"
case "$requested_context_policy" in
  ""|none|english_alignment_v1|weekly_terms_v1|saturday_alignment_v1) ;;
  *) echo "Unsupported LOCAL_LIVE_CONTEXT_POLICY: $requested_context_policy" >&2; exit 1 ;;
esac
context_policy="none"
runtime_weekly_pack=""
if [ ! -f "$weekly_pack" ]; then
  if [ -z "$requested_context_policy" ] || [ "$requested_context_policy" = "none" ]; then
    # Do not export a nonexistent default path: backend.gateway also reads the
    # environment variable as its --pack default and would otherwise fail.
    weekly_pack=""
  else
    echo "Weekly pack is required for context policy $requested_context_policy: $weekly_pack" >&2
    exit 1
  fi
fi

pack_dir="$(dirname "$weekly_pack")"
pack_manifest="${LOCAL_LIVE_PACK_MANIFEST:-$pack_dir/manifest.json}"
pack_segments="${LOCAL_LIVE_PACK_SEGMENTS:-$pack_dir/saturday-segments.jsonl}"
pack_phrases="${LOCAL_LIVE_PACK_PHRASES:-$pack_dir/asr-phrases.candidate.txt}"
pack_message_approval="${LOCAL_LIVE_PACK_MESSAGE_APPROVAL:-$pack_dir/message-identity-approval.json}"
target_sunday="${LOCAL_LIVE_TARGET_SUNDAY:-$(.venv/bin/python - <<'PY'
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
print((today + timedelta(days=(6 - today.weekday()) % 7)).isoformat())
PY
)}"

if [ -f "$weekly_pack" ] && [ -f "$pack_manifest" ] && \
   [ -f "$pack_segments" ] && [ -f "$pack_phrases" ] && \
   [ -f "$pack_message_approval" ]; then
  readiness_report="$(mktemp "${TMPDIR:-/tmp}/sunday-pack-readiness.XXXXXX")"
  readiness_exit=0
  .venv/bin/python -m backend.pack_readiness \
    --manifest "$pack_manifest" \
    --pack "$weekly_pack" \
    --segments "$pack_segments" \
    --phrases "$pack_phrases" \
    --message-approval "$pack_message_approval" \
    --expected-target-sunday "$target_sunday" \
    --output "$readiness_report" >/dev/null || readiness_exit=$?
  if [ -s "$readiness_report" ]; then
    readiness_status="$(.venv/bin/python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["status"])' "$readiness_report")"
    recommended_context_policy="$(.venv/bin/python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["contextPolicy"])' "$readiness_report")"
    readiness_mode="$(.venv/bin/python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["runtimeMode"])' "$readiness_report")"
    readiness_blockers="$(.venv/bin/python -c 'import json,sys; print(",".join(json.load(open(sys.argv[1], encoding="utf-8"))["blockers"]))' "$readiness_report")"
    if [ "$readiness_status" = "ready" ] || [ "$readiness_status" = "degraded" ]; then
      runtime_weekly_pack="$weekly_pack"
      context_policy="$(.venv/bin/python -c 'import json,sys; from backend.pack_readiness import select_context_policy; print(select_context_policy(json.load(open(sys.argv[1], encoding="utf-8")), sys.argv[2]))' "$readiness_report" "$requested_context_policy")"
      if [ -n "$requested_context_policy" ] && [ "$context_policy" != "$requested_context_policy" ]; then
        echo "Requested context policy exceeds verified pack capability; using $recommended_context_policy." >&2
      fi
      echo "Verified Sunday context pack: $readiness_mode ($readiness_status)."
    else
      echo "Sunday context pack is invalid; using no context. Blockers: ${readiness_blockers:-unknown}" >&2
    fi
  else
    echo "Sunday context pack validation failed (exit $readiness_exit); using no context." >&2
  fi
  rm -f "$readiness_report"
elif [ -f "$weekly_pack" ]; then
  echo "Sunday context pack companions are incomplete; using no context." >&2
fi

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
echo "Context: $context_policy${runtime_weekly_pack:+ ($runtime_weekly_pack)}"
echo "Sessions: $session_root"
echo "Public viewer: $firebase_public_mode"
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
LOCAL_LIVE_WEEKLY_PACK="$runtime_weekly_pack" \
LOCAL_LIVE_CONTEXT_POLICY="$context_policy" \
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
