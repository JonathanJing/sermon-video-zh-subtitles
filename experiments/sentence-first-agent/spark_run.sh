#!/bin/bash
# Run batch-1 TTS and/or Qwen3-ASR back-transcription for one locale on DGX Spark (experiment only).
#
# Runs ON Spark, from a directory holding this script, tts_sentences.py and asr_check.py.
# The work directory must already contain speech.jsonl. Finished items are skipped, so a
# stopped run resumes where it left off. Run it in the foreground over SSH (wrap the SSH call
# in a background task if you want to wait); `nohup ... &` over SSH hangs the session.
#
#   bash spark_run.sh --work DIR --locale zh-Hans|ko|es --checkpoint HOST_DIR [--steps tts,asr]
#                     [--seed 7] [--dry-run]
#
# Environment overrides (defaults are the paths verified on spark-38f8 on 2026-10-22):
#   IMAGE           nvcr.io/nvidia/pytorch:26.06-py3
#   VOICE_PACKAGES  site-packages with qwen_tts (mounted read-only at /voice-packages)
#   SPEECH_RUNTIME  Qwen ASR runtime with venv/ and model-cache/ (mounted read-only at /runtime)
#   ASR_SNAPSHOT    ASR model path relative to SPEECH_RUNTIME
set -u

IMAGE=${IMAGE:-nvcr.io/nvidia/pytorch:26.06-py3}
VOICE_PACKAGES=${VOICE_PACKAGES:-/home/achillesjing/dgx-spark-benchmark/results/sermon-voice-poc-20260905/venv/lib/python3.12/site-packages}
SPEECH_RUNTIME=${SPEECH_RUNTIME:-/home/achillesjing/sermon-speech-runtime}
ASR_SNAPSHOT=${ASR_SNAPSHOT:-model-cache/hub/models--Qwen--Qwen3-ASR-0.6B/snapshots/5eb144179a02acc5e5ba31e748d22b0cf3e303b0}
TOOLS=$(cd "$(dirname "$0")" && pwd)

WORK="" LOCALE="" CHECKPOINT="" STEPS="tts,asr" SEED=7 DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --work) WORK=$2; shift 2 ;;
    --locale) LOCALE=$2; shift 2 ;;
    --checkpoint) CHECKPOINT=$2; shift 2 ;;
    --steps) STEPS=$2; shift 2 ;;
    --seed) SEED=$2; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
case "$LOCALE" in zh-Hans|ko|es) ;; *) echo "--locale must be zh-Hans, ko or es" >&2; exit 2 ;; esac
case ",$STEPS," in *,tts,*|*,asr,*) ;; *) echo "--steps must name tts, asr or both" >&2; exit 2 ;; esac
[ -n "$WORK" ] || { echo "--work is required" >&2; exit 2; }
WORK=$(cd "$WORK" 2>/dev/null && pwd) || { echo "work directory not found" >&2; exit 2; }
[ -f "$WORK/speech.jsonl" ] || { echo "$WORK/speech.jsonl is missing" >&2; exit 2; }
for f in tts_sentences.py asr_check.py; do
  [ -f "$TOOLS/$f" ] || { echo "$TOOLS/$f is missing; copy it next to this script" >&2; exit 2; }
done

COMMON=(docker run --rm --gpus all --ipc=host --network none
        --tmpfs /tmp:rw,exec,nosuid,size=512m
        -v "$WORK":/work:rw -v "$TOOLS":/tools:ro
        -e NUMBA_CACHE_DIR=/tmp/numba -e TRITON_CACHE_DIR=/tmp/triton -e XDG_CACHE_HOME=/tmp/cache
        -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1)

# step NAME LOG CMD...: print the command; unless --dry-run, run it into LOG and stop on failure.
step() {
  local name=$1 log=$2; shift 2
  printf '%q ' "$@"; echo
  [ "$DRY" = 1 ] && return 0
  echo "$name start $LOCALE $(date -u +%FT%TZ)" >> "$log"
  "$@" >> "$log" 2>&1
  local status=$?
  echo "$name exit $LOCALE $status $(date -u +%FT%TZ)" >> "$log"
  [ "$status" = 0 ] || { echo "$name failed ($status); see $log" >&2; exit "$status"; }
}

if [[ ",$STEPS," == *",tts,"* ]]; then
  [ -f "$CHECKPOINT/model.safetensors" ] || { echo "--checkpoint must be a directory with model.safetensors" >&2; exit 2; }
  CHECKPOINT=$(cd "$CHECKPOINT" && pwd)
  [ "$DRY" = 1 ] || mkdir -p "$WORK/tts"
  step tts "$WORK/tts-run.log" "${COMMON[@]}" \
    -v "$CHECKPOINT":/checkpoint:ro -v "$VOICE_PACKAGES":/voice-packages:ro \
    -e PYTHONPATH=/voice-packages -e HF_HOME=/tmp/hf --entrypoint python "$IMAGE" \
    /tools/tts_sentences.py --speech /work/speech.jsonl --checkpoint /checkpoint --out /work/tts \
    --device cuda:0 --dtype bfloat16 --seed "$SEED"
fi

if [[ ",$STEPS," == *",asr,"* ]]; then
  [ -d "$SPEECH_RUNTIME/$ASR_SNAPSHOT" ] || { echo "ASR model not found: $SPEECH_RUNTIME/$ASR_SNAPSHOT" >&2; exit 2; }
  step asr "$WORK/asr-run.log" "${COMMON[@]}" \
    -v "$SPEECH_RUNTIME":/runtime:ro \
    -e PYTHONPATH=/runtime/venv/lib/python3.12/site-packages -e HF_HOME=/runtime/model-cache \
    --entrypoint python "$IMAGE" \
    /tools/asr_check.py transcribe --speech /work/speech.jsonl --tts /work/tts \
    --model "/runtime/$ASR_SNAPSHOT" --out /work/asr.jsonl --locale "$LOCALE" --batch-size 8
fi

[ "$DRY" = 1 ] || echo "== $LOCALE tts_wavs=$(ls "$WORK"/tts/*.wav 2>/dev/null | wc -l) asr_lines=$(cat "$WORK/asr.jsonl" 2>/dev/null | wc -l)"
