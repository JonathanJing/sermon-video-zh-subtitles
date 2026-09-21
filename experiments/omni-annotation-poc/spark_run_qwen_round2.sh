#!/usr/bin/env bash
set -euo pipefail

service=llama-server.service
container=omni-poc-qwen
root=/home/achillesjing/omni-annotation-poc/20260920-round2
data=$root/data
start_script=$root/spark_start_qwen.sh
was_active=false

restore() {
  rc=$?
  trap - EXIT INT TERM
  if docker ps --format '{{.Names}}' | grep -qx "$container"; then
    docker stop "$container" >/dev/null || true
  fi
  if "$was_active"; then
    systemctl --user start "$service" || true
    restored=false
    for _ in $(seq 1 90); do
      if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
        restored=true
        break
      fi
      sleep 2
    done
    echo "ORIGINAL_SERVICE_RESTORED=$restored"
    if ! "$restored"; then
      rc=8
    fi
  fi
  exit "$rc"
}
trap restore EXIT INT TERM

if systemctl --user is-active --quiet "$service"; then
  was_active=true
fi
if ! "$was_active"; then
  echo "Original service was not active; refusing an ambiguous switch." >&2
  exit 4
fi
curl -fsS http://127.0.0.1:8000/health >/dev/null
echo "ORIGINAL_SERVICE_PREFLIGHT=healthy"

systemctl --user stop "$service"
for _ in $(seq 1 30); do
  systemctl --user is-active --quiet "$service" || break
  sleep 1
done
if systemctl --user is-active --quiet "$service"; then
  echo "Original service did not stop." >&2
  exit 5
fi
echo "ORIGINAL_SERVICE_STOPPED=yes"
free -h

OMNI_POC_DATA="$data" "$start_script"
qwen_ready=false
for _ in $(seq 1 300); do
  if curl -fsS http://127.0.0.1:8911/v1/models >/dev/null 2>&1; then
    qwen_ready=true
    break
  fi
  if ! docker ps --format '{{.Names}}' | grep -qx "$container"; then
    echo "Qwen container exited during startup." >&2
    docker logs --tail 200 "$container" >&2 || true
    exit 6
  fi
  sleep 2
done
if ! "$qwen_ready"; then
  echo "Qwen server startup timed out." >&2
  docker logs --tail 200 "$container" >&2 || true
  exit 7
fi
echo "QWEN_SERVER=healthy"
curl -fsS http://127.0.0.1:8911/v1/models \
  | python3 -c 'import json,sys; print("QWEN_MODEL=" + json.load(sys.stdin)["data"][0]["id"])'

cd "$data"
python3 run_round2_matrix.py \
  --manifest corpus-manifest.json \
  --provider openai-compatible \
  --base-url http://127.0.0.1:8911/v1 \
  --server-media-root /data \
  --model qwen3-omni-30b-a3b-thinking \
  --enable-thinking \
  --max-tokens 4096 \
  --sample s05-revelation-2-1-quote \
  --sample s08-revelation-2-4-visible-explanation \
  --sample s12-rhetorical-repeat \
  --out results/qwen

echo "QWEN_ROUND2_CASES=complete"
