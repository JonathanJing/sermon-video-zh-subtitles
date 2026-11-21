#!/usr/bin/env bash
# Start the throwaway Qwen3.8 demo: llama-server on loopback + the LAN chat page.
set -euo pipefail

DEMO_ROOT="${DEMO_ROOT:-$HOME/spark-chat-demo}"
STATE="$DEMO_ROOT/state"
LOGS="$DEMO_ROOT/logs"
LLAMA_BIN="$DEMO_ROOT/build/llama.cpp/build/bin/llama-server"
SERVE_PY="$DEMO_ROOT/scripts/serve.py"

say() { printf '\033[1;32m[run]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[run] %s\033[0m\n' "$*" >&2; exit 1; }

[ -x "$LLAMA_BIN" ] || die "llama-server missing, run install.sh first"
[ -f "$STATE/install.json" ] || die "install.json missing, run install.sh first"
mkdir -p "$STATE" "$LOGS"

readarray -t INFO < <(python3 - "$STATE/install.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))["model"]
print(m["path"]); print(m["name"]); print(m["nCtx"])
PY
)
MODEL_PATH="${INFO[0]}"; MODEL_NAME="${INFO[1]}"; N_CTX="${INFO[2]}"
[ -s "$MODEL_PATH" ] || die "model file missing: $MODEL_PATH"

if pgrep -f "llama-server.*$DEMO_ROOT" >/dev/null 2>&1; then
  say "demo already running; stop it with cleanup.sh first"
  exit 0
fi

say "starting llama-server ($MODEL_NAME, ctx $N_CTX, all layers on GPU)"
nohup "$LLAMA_BIN" \
  -m "$MODEL_PATH" \
  --host 127.0.0.1 --port 8080 \
  --ctx-size "$N_CTX" --n-gpu-layers 99 --parallel 1 \
  --no-warmup --jinja -fa on \
  >"$LOGS/llama-server.log" 2>&1 &
LLAMA_PID=$!

for _ in $(seq 1 120); do
  if curl -sf -m 2 http://127.0.0.1:8080/health >/dev/null 2>&1; then break; fi
  kill -0 "$LLAMA_PID" 2>/dev/null || { tail -30 "$LOGS/llama-server.log"; die "llama-server exited"; }
  sleep 2
done
curl -sf -m 3 http://127.0.0.1:8080/health >/dev/null || die "llama-server not healthy after wait"

say "starting chat page on 0.0.0.0:8088"
nohup python3 "$SERVE_PY" --host 0.0.0.0 --port 8088 --upstream http://127.0.0.1:8080 \
  >"$LOGS/serve.log" 2>&1 &
SERVE_PID=$!
sleep 1
curl -sf -m 3 http://127.0.0.1:8088/healthz >/dev/null || die "chat server failed to start"

python3 - "$STATE/pids.json" "$LLAMA_PID" "$SERVE_PID" <<'PY'
import json, sys, time
json.dump({"llamaPid": int(sys.argv[2]), "servePid": int(sys.argv[3]), "startedAt": time.time()},
          open(sys.argv[1], "w"), indent=2)
PY

IP="$(hostname -I | awk '{print $1}')"
say "ready: http://$IP:8088/  (loopback: http://127.0.0.1:8088/)"
say "logs: $LOGS/llama-server.log, $LOGS/serve.log, $LOGS/chat.jsonl"
say "stop and clean: bash $DEMO_ROOT/scripts/cleanup.sh"
