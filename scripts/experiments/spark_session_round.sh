#!/usr/bin/env bash
# Run one Spark-bound command, then close its exclusive session whatever happened.
#
# Usage (repo root, run in the background so the completion is notified):
#   scripts/experiments/spark_session_round.sh <session-id> <owner> -- <command...>
#
# The finish call always runs after the command, so services stop being held
# by a waiter that never checked. A failing command keeps its own exit code.
# If the command succeeded but finish failed, exit 7 so the failure is not hidden.
# finish refuses while a job hold is still active; that refusal is kept, not
# forced, because an active hold means the run did not end cleanly.
set -uo pipefail

if [[ $# -lt 4 || "$3" != "--" ]]; then
  echo "usage: $0 <session-id> <owner> -- <command...>" >&2
  exit 2
fi
SESSION_ID="$1"; OWNER="$2"; shift 3

REPO="$(git rev-parse --show-toplevel)"
PY="$REPO/.venv/bin/python"
CONTROL="$REPO/scripts/spark_exclusive_session.py"

"$@"
RUN_STATUS=$?

FINISH_OUTPUT="$("$PY" "$CONTROL" finish --session-id "$SESSION_ID" --owner "$OWNER" 2>&1)"
FINISH_STATUS=$?

echo "round: command_exit=$RUN_STATUS finish_exit=$FINISH_STATUS session=$SESSION_ID"
if [[ $FINISH_STATUS -ne 0 ]]; then
  echo "finish failed: $FINISH_OUTPUT" >&2
  [[ $RUN_STATUS -ne 0 ]] && exit "$RUN_STATUS"
  exit 7
fi
exit "$RUN_STATUS"
