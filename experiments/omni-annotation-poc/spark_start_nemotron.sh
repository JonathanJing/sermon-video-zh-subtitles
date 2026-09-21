#!/usr/bin/env bash
set -euo pipefail

container=omni-poc-nemotron
weights=/home/achillesjing/omni-annotation-poc/models/nemotron-3-nano-omni-nvfp4
data=/home/achillesjing/omni-annotation-poc/20260920-scripture-01/data

if docker ps --format '{{.Names}}' | grep -qx "$container"; then
  echo "$container already running"
  exit 0
fi
if docker ps -a --format '{{.Names}}' | grep -qx "$container"; then
  docker rm "$container" >/dev/null
fi

docker run -d \
  --name "$container" \
  --gpus all \
  --ipc=host \
  -p 127.0.0.1:8910:8000 \
  --shm-size=8g \
  -v "$weights:/model:ro" \
  -v "$data:/data:ro" \
  --entrypoint /bin/bash \
  vllm/vllm-openai:v0.20.0 \
  -lc 'pip install "vllm[audio]" && exec vllm serve /model \
    --served-model-name nemotron-3-nano-omni-nvfp4 \
    --host 0.0.0.0 \
    --port 8000 \
    --trust-remote-code \
    --gpu-memory-utilization 0.35 \
    --max-model-len 32768 \
    --max-num-seqs 1 \
    --max-num-batched-tokens 8192 \
    --limit-mm-per-prompt '\''{"video":1,"audio":1}'\'' \
    --media-io-kwargs '\''{"video":{"fps":2,"num_frames":64}}'\'' \
    --allowed-local-media-path /data \
    --kv-cache-dtype fp8'

echo "$container started on Spark loopback port 8910"
