#!/bin/bash
# Runs on Spark. Batch 1 Qwen3-TTS for ko then es, then Qwen3-ASR back-transcription for both.
set -u
BASE=/home/achillesjing/sentence-first-agent
RESULTS=/home/achillesjing/dgx-spark-benchmark/results
RT=/home/achillesjing/sermon-speech-runtime
CKPT=/results/sermon-speaker-bank-20260905/steve_bang_lee/checkpoints/checkpoint-epoch-0
ASR=/runtime/model-cache/hub/models--Qwen--Qwen3-ASR-0.6B/snapshots/5eb144179a02acc5e5ba31e748d22b0cf3e303b0
for LOC in ko es; do
  WORK="$BASE/20261022-scroll-u127-214-$LOC"
  mkdir -p "$WORK/tts"
  echo "tts start $LOC $(date -u +%FT%TZ)" >> "$WORK/tts-run.log"
  docker run --rm --gpus all --ipc=host --network none \
    --tmpfs /tmp:rw,exec,nosuid,size=512m \
    -v "$WORK":/work:rw -v "$BASE/tools":/tools:ro -v "$RESULTS":/results:ro \
    -v "$RESULTS"/sermon-voice-poc-20260905/venv/lib/python3.12/site-packages:/voice-packages:ro \
    -e PYTHONPATH=/voice-packages -e NUMBA_CACHE_DIR=/tmp/numba \
    -e TRITON_CACHE_DIR=/tmp/triton -e XDG_CACHE_HOME=/tmp/cache \
    -e HF_HOME=/tmp/hf -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
    --entrypoint python nvcr.io/nvidia/pytorch:26.06-py3 \
    /tools/tts_sentences.py --speech /work/speech.jsonl --checkpoint "$CKPT" \
    --out /work/tts --device cuda:0 --dtype bfloat16 --seed 7 >> "$WORK/tts-run.log" 2>&1
  echo "tts exit $LOC $? $(date -u +%FT%TZ)" >> "$WORK/tts-run.log"
  docker run --rm --gpus all --ipc=host --network none \
    --tmpfs /tmp:rw,exec,nosuid,size=512m \
    -v "$WORK":/work:rw -v "$BASE/tools":/tools:ro -v "$RT":/runtime:ro \
    -e PYTHONPATH=/runtime/venv/lib/python3.12/site-packages -e NUMBA_CACHE_DIR=/tmp/numba \
    -e HF_HOME=/runtime/model-cache -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
    --entrypoint python nvcr.io/nvidia/pytorch:26.06-py3 \
    /tools/asr_check.py transcribe --speech /work/speech.jsonl --tts /work/tts \
    --model "$ASR" --out /work/asr.jsonl --locale "$LOC" --batch-size 8 > "$WORK/asr-run.log" 2>&1
  echo "asr exit $LOC $?" >> "$WORK/asr-run.log"
  echo "== $LOC"; grep -c '"id"' "$WORK/tts/tts-log.jsonl"; tail -n 1 "$WORK/tts-run.log"; tail -n 1 "$WORK/asr-run.log"
done
