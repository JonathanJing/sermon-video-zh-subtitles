#!/usr/bin/env bash
# Install, inspect or remove the Sunday live-capture LaunchAgent on this Mac.
#
# Default: every Sunday at 09:55 local, the wrapper starts and waits for the
# 10:00 service, records until 11:20, then fetches the provider session log.
#
#   ./install-schedule.sh                 # install for Sundays
#   ./install-schedule.sh --uninstall     # remove
#   ./install-schedule.sh --room mariners-irvine-outdoor --start 09:00 --stop 10:20
#
# launchd runs a missed calendar job when the Mac wakes, but it cannot wake a
# sleeping Mac by itself.  The wrapper holds a caffeinate assertion while the
# capture is running.  Keep the Mac on AC power and logged in on Sunday.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
UID_NUM="$(id -u)"
DOMAIN="gui/$UID_NUM"

LABEL="ai.pastors.live-capture"
ROOM="mariners-north-irvine"
START="10:00"
STOP="11:20"
WEEKDAY="0"          # launchd: Sunday=0
HOUR="9"
MINUTE="55"
OUT_ROOT="$ROOT/artifacts/live-capture"
TZ_NAME="America/Los_Angeles"
UNINSTALL="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label) LABEL="$2"; shift 2 ;;
    --room) ROOM="$2"; shift 2 ;;
    --start) START="$2"; shift 2 ;;
    --stop) STOP="$2"; shift 2 ;;
    --weekday) WEEKDAY="$2"; shift 2 ;;
    --hour) HOUR="$2"; shift 2 ;;
    --minute) MINUTE="$2"; shift 2 ;;
    --out-root) OUT_ROOT="$2"; shift 2 ;;
    --timezone) TZ_NAME="$2"; shift 2 ;;
    --uninstall) UNINSTALL="1"; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ "$UNINSTALL" == "1" ]]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "removed $DOMAIN/$LABEL and $PLIST"
  exit 0
fi

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "missing $ROOT/.venv/bin/python" >&2
  exit 1
fi
if [[ ! -f "$HERE/run-capture.sh" ]]; then
  echo "missing $HERE/run-capture.sh" >&2
  exit 1
fi
if ! [[ "$WEEKDAY" =~ ^[0-6]$ ]] || ! [[ "$HOUR" =~ ^[0-9]+$ ]] || ! [[ "$MINUTE" =~ ^[0-9]+$ ]]; then
  echo "invalid weekday/hour/minute: $WEEKDAY $HOUR $MINUTE" >&2
  exit 2
fi
if (( HOUR > 23 || MINUTE > 59 )); then
  echo "hour/minute out of range" >&2
  exit 2
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs" "$OUT_ROOT"

cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$HERE/run-capture.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$ROOT</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>CAPTURE_ROOM</key>
    <string>$ROOM</string>
    <key>CAPTURE_START</key>
    <string>$START</string>
    <key>CAPTURE_STOP</key>
    <string>$STOP</string>
    <key>CAPTURE_OUT_ROOT</key>
    <string>$OUT_ROOT</string>
    <key>CAPTURE_TIMEZONE</key>
    <string>$TZ_NAME</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>$WEEKDAY</integer>
    <key>Hour</key>
    <integer>$HOUR</integer>
    <key>Minute</key>
    <integer>$MINUTE</integer>
  </dict>
  <key>RunAtLoad</key>
  <false/>
  <key>ProcessType</key>
  <string>Background</string>
  <key>ThrottleInterval</key>
  <integer>60</integer>
  <key>StandardOutPath</key>
  <string>$HOME/Library/Logs/$LABEL.out.log</string>
  <key>StandardErrorPath</key>
  <string>$HOME/Library/Logs/$LABEL.err.log</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl enable "$DOMAIN/$LABEL"

echo "installed $DOMAIN/$LABEL"
echo "  plist: $PLIST"
echo "  room: $ROOM  start: $START  stop: $STOP  timezone: $TZ_NAME"
echo "  calendar: weekday=$WEEKDAY (0=Sunday) at $(printf '%02d:%02d' "$HOUR" "$MINUTE")"
launchctl print "$DOMAIN/$LABEL" | grep -E 'state =|runs =|next fire date|last exit code' | sed 's/^/  /' || true
