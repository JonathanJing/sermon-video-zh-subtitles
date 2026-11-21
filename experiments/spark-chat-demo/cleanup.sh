#!/usr/bin/env bash
# Tear the demo down and put the host back the way it was: no listeners, no
# model weights, no build tree, no state. Default removes EVERYTHING under
# DEMO_ROOT; pass --keep-logs to keep logs/ and state/ for a post-mortem.
set -uo pipefail

DEMO_ROOT="${DEMO_ROOT:-$HOME/spark-chat-demo}"
KEEP_LOGS=0
[ "${1:-}" = "--keep-logs" ] && KEEP_LOGS=1

say() { printf '\033[1;33m[cleanup]\033[0m %s\n' "$*"; }
STATE="$DEMO_ROOT/state"

# ---------------------------------------------------------------- 1. processes
if [ -f "$STATE/pids.json" ]; then
  say "stopping processes recorded in $STATE/pids.json"
  mapfile -t PIDS < <(python3 - "$STATE/pids.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print(d.get("servePid") or ""); print(d.get("llamaPid") or "")
PY
)
  for pid in "${PIDS[@]}"; do
    [ -n "$pid" ] || continue
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null
      for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
      kill -0 "$pid" 2>/dev/null && { say "pid $pid ignored TERM, killing"; kill -KILL "$pid" 2>/dev/null; }
    fi
  done
fi

# Belt and braces: anything still holding our paths (config reloads, orphans).
for pattern in "llama-server.*$DEMO_ROOT" "serve.py.*--port 8088"; do
  if pgrep -f "$pattern" >/dev/null 2>&1; then
    say "killing leftover: $pattern"
    pkill -f "$pattern" 2>/dev/null
    sleep 1
    pkill -9 -f "$pattern" 2>/dev/null
  fi
done

# ---------------------------------------------------------------- 2. files
if [ "$KEEP_LOGS" = "1" ]; then
  say "keeping logs/ and state/ (--keep-logs)"
  rm -rf -- "$DEMO_ROOT/models" "$DEMO_ROOT/build" "$DEMO_ROOT/scripts"
else
  say "removing $DEMO_ROOT (models, build tree, logs, state, scripts)"
  rm -rf -- "$DEMO_ROOT"
fi

# ---------------------------------------------------------------- 3. verify clean
RC=0
for port in 8080 8088; do
  if (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -q ":$port "; then
    say "STILL LISTENING on :$port"; RC=1
  fi
done
# Exclude this script and its parent shell: both carry DEMO_ROOT on their own
# command line, so a plain pgrep would always match itself.
LEFT_PIDS="$(pgrep -f "$DEMO_ROOT" 2>/dev/null | grep -vxE "$$|$PPID" || true)"
if [ -n "$LEFT_PIDS" ]; then
  LEFT_REAL="$(ps -o pid=,args= -p $(echo "$LEFT_PIDS" | paste -sd, -) 2>/dev/null | grep -v "cleanup.sh" || true)"
  if [ -n "$LEFT_REAL" ]; then say "STILL RUNNING:"; echo "$LEFT_REAL" | head -3; RC=1; fi
fi
if [ -e "$DEMO_ROOT" ] && [ "$KEEP_LOGS" = "0" ]; then
  say "STILL PRESENT: $DEMO_ROOT"; RC=1
fi
LEFT="$(du -sh "$DEMO_ROOT" 2>/dev/null | cut -f1 || true)"

if [ "$RC" = "0" ]; then
  say "clean: no listeners on 8080/8088, no demo processes, ${LEFT:-0} left under $DEMO_ROOT"
  say "disk: $(df -h / | tail -1 | awk '{print $3" used, "$4" available ("$5")"}')"
else
  say "cleanup incomplete; see messages above"
fi
exit "$RC"
