#!/usr/bin/env bash
# Run one Sunday live capture: English captions + Mandarin audio/captions.
#
# launchd starts this script a few minutes before the service; capture.py
# waits for the wall-clock start, records until the stop time, and finalizes
# by itself.  Afterwards fetch_session.py reads the provider's session log
# (exact timestamps, read-only, listener telemetry removed).
#
# Environment overrides:
#   CAPTURE_ROOM        default mariners-north-irvine
#   CAPTURE_START       default 10:00  (HH:MM, local)
#   CAPTURE_STOP        default 11:20  (HH:MM, local)
#   CAPTURE_OUT_ROOT    default <repo>/artifacts/live-capture
#   CAPTURE_TIMEZONE    default America/Los_Angeles
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PY="$ROOT/.venv/bin/python"
CAFFEINATE="/usr/bin/caffeinate"

ROOM="${CAPTURE_ROOM:-mariners-north-irvine}"
START="${CAPTURE_START:-10:00}"
STOP="${CAPTURE_STOP:-11:20}"
OUT_ROOT="${CAPTURE_OUT_ROOT:-$ROOT/artifacts/live-capture}"
TZ_NAME="${CAPTURE_TIMEZONE:-America/Los_Angeles}"
BASE_URL="https://translate.pastors.ai"

DATE="$(TZ="$TZ_NAME" date +%Y-%m-%d)"
RUN_DIR="$OUT_ROOT/$ROOM/$DATE"
if [[ -e "$RUN_DIR" ]]; then
  RUN_DIR="$OUT_ROOT/$ROOM/${DATE}-$(TZ="$TZ_NAME" date +%H%M%S)"
fi
mkdir -p "$RUN_DIR"
LOG="$RUN_DIR/wrapper.log"

exec > >(tee -a "$LOG") 2>&1

echo "=== live capture wrapper $(TZ="$TZ_NAME" date '+%Y-%m-%d %H:%M:%S %Z') ==="
echo "room=$ROOM start=$START stop=$STOP timezone=$TZ_NAME"
echo "run_dir=$RUN_DIR"

if pgrep -f "live-translate-capture/capture.py" >/dev/null 2>&1; then
  echo "another capture.py is already running; refusing to start a second one"
  exit 3
fi

echo "--- host"
hostname
sw_vers 2>/dev/null | sed 's/^/  /'
TZ="$TZ_NAME" date '+  local: %Y-%m-%d %H:%M:%S %Z'
pmset -g batt 2>/dev/null | head -3 | sed 's/^/  /'
df -h "$ROOT" 2>/dev/null | tail -1 | sed 's/^/  disk: /'

echo "--- preflight: room config and broadcast state"
curl -fsS --max-time 15 "$BASE_URL/api/rooms/$ROOM/config" -o "$RUN_DIR/preflight.room-config.json" \
  && echo "  room config: ok" || echo "  room config: FAILED (capture will still retry)"
curl -fsS --max-time 15 "$BASE_URL/api/rooms" -o "$RUN_DIR/preflight.rooms.json" \
  && echo "  rooms: ok" || echo "  rooms: FAILED"

if [[ -f "$RUN_DIR/preflight.room-config.json" ]]; then
  "$PY" - "$RUN_DIR/preflight.room-config.json" <<'PY'
import json
import sys
try:
    config = json.load(open(sys.argv[1], encoding="utf-8"))
    languages = [item.get("code") for item in config.get("languages", [])]
    print("  languages: " + ", ".join(code for code in languages if code))
    missing = [code for code in ("captions", "zh") if code not in languages]
    if missing:
        print("  WARNING: room config is missing " + ", ".join(missing))
except Exception as exc:  # noqa: BLE001 - preflight only
    print(f"  language check failed: {exc}")
PY
fi
if [[ -f "$RUN_DIR/preflight.rooms.json" ]]; then
  "$PY" - "$RUN_DIR/preflight.rooms.json" "$ROOM" <<'PY'
import json
import sys
try:
    rooms = json.load(open(sys.argv[1], encoding="utf-8"))
    room_id = sys.argv[2]
    match = next((room for room in rooms if room.get("id") == room_id), None)
    if match is None:
        print(f"  room {room_id}: not listed")
    else:
        print(f"  room {room_id}: broadcasting={match.get('broadcasting')} listeners={match.get('listeners')}")
except Exception as exc:  # noqa: BLE001 - preflight only
    print(f"  room state check failed: {exc}")
PY
fi

CAPTURE_STATUS=99
if [[ -x "$CAFFEINATE" ]]; then
  echo "--- capture"
  "$CAFFEINATE" -i -m -s "$PY" "$HERE/capture.py" \
    --room "$ROOM" \
    --start-at "$START" \
    --stop-at "$STOP" \
    --timezone "$TZ_NAME" \
    --out "$RUN_DIR" \
    --out-root "$OUT_ROOT"
  CAPTURE_STATUS=$?
else
  echo "caffeinate not found; running capture without a sleep assertion" >&2
  "$PY" "$HERE/capture.py" \
    --room "$ROOM" \
    --start-at "$START" \
    --stop-at "$STOP" \
    --timezone "$TZ_NAME" \
    --out "$RUN_DIR" \
    --out-root "$OUT_ROOT"
  CAPTURE_STATUS=$?
fi
echo "capture exit=$CAPTURE_STATUS"

FETCH_STATUS=99
if [[ -f "$RUN_DIR/capture.json" ]]; then
  echo "--- provider session log"
  "$PY" "$HERE/fetch_session.py" --capture-dir "$RUN_DIR" >"$RUN_DIR/fetch.log" 2>&1
  FETCH_STATUS=$?
  if [[ $FETCH_STATUS -eq 0 ]]; then
    echo "  session log: ok"
  else
    echo "  session log: FAILED (see $RUN_DIR/fetch.log)"
  fi
else
  echo "  session log skipped: no capture.json"
fi

cat >"$RUN_DIR/run.status.json" <<EOF
{
  "schema": "live-translate-capture-wrapper/v1",
  "finished_at": "$(TZ="$TZ_NAME" date '+%Y-%m-%dT%H:%M:%S%z')",
  "room": "$ROOM",
  "requested_start": "$START",
  "requested_stop": "$STOP",
  "capture_exit": $CAPTURE_STATUS,
  "session_fetch_exit": $FETCH_STATUS,
  "run_dir": "$RUN_DIR"
}
EOF

echo "=== finished: capture_exit=$CAPTURE_STATUS session_fetch_exit=$FETCH_STATUS ==="
if [[ $CAPTURE_STATUS -ne 0 ]]; then
  exit 2
fi
exit 0
