#!/usr/bin/env bash
set -euo pipefail

container=omni-poc-qwen
weights=/home/achillesjing/omni-annotation-poc/models/qwen3-omni-thinking
data=${OMNI_POC_DATA:-/home/achillesjing/omni-annotation-poc/20260920-scripture-qwen-15s/data}

if systemctl --user is-active --quiet llama-server.service; then
  echo "Refusing to start while llama-server.service is active; stopping it requires operator approval." >&2
  exit 3
fi
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
  -p 127.0.0.1:8911:8000 \
  --shm-size=8g \
  -v "$weights:/model:ro" \
  -v "$data:/data:ro" \
  --entrypoint /bin/bash \
  vllm/vllm-openai:v0.20.0 \
  -lc 'pip install "vllm[audio]" && exec vllm serve /model \
    --served-model-name qwen3-omni-30b-a3b-thinking \
    --host 0.0.0.0 \
    --port 8000 \
    --trust-remote-code \
    --dtype bfloat16 \
    --gpu-memory-utilization 0.60 \
    --max-model-len 16384 \
    --max-num-seqs 1 \
    --limit-mm-per-prompt '\''{"video":1,"audio":1}'\'' \
    --allowed-local-media-path /data'

echo "$container started on Spark loopback port 8911"
