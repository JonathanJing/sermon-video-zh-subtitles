#!/usr/bin/env bash
set -euo pipefail

runtime_dir="${TMPDIR:-/tmp}/sermon-live-caption-poc"
pid_file="$runtime_dir/sunday-live.pid"

if [ ! -f "$pid_file" ]; then
  echo "Sunday live captions are not running."
  exit 0
fi

launcher_pid="$(cat "$pid_file" 2>/dev/null || true)"
if ! [[ "$launcher_pid" =~ ^[0-9]+$ ]]; then
  echo "The launcher PID file is invalid; removing it without stopping any process." >&2
  rm -f "$pid_file"
  exit 1
fi

if ! kill -0 "$launcher_pid" 2>/dev/null; then
  echo "Sunday live captions are already stopped. Removing the stale PID file."
  rm -f "$pid_file"
  exit 0
fi

launcher_command="$(ps -p "$launcher_pid" -o command= 2>/dev/null || true)"
case "$launcher_command" in
  *sunday-live.sh*) ;;
  *)
    echo "PID $launcher_pid does not belong to the Sunday live-caption launcher." >&2
    echo "No process was stopped. Remove this stale file after checking it: $pid_file" >&2
    exit 1
    ;;
esac

echo "Stopping Sunday live captions…"
kill -TERM "$launcher_pid"

for _ in $(seq 1 50); do
  if ! kill -0 "$launcher_pid" 2>/dev/null; then
    rm -f "$pid_file"
    echo "Sunday live captions stopped. You can close the browser page."
    exit 0
  fi
  sleep 0.1
done

echo "The launcher did not stop within 5 seconds." >&2
echo "Use Control-C in its Terminal window; no forced kill was sent." >&2
exit 1
