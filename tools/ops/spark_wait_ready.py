#!/usr/bin/env python3
"""Wait until the held Spark exclusive session is ready for the next dispatch.

A dispatcher that calls ``require_ready`` once fails the moment a competing unit
is still active or MemAvailable has not settled; on 2026-10-11 that cost a manual
retry each time the previous locale's model was still unloading. This command
polls ``require`` and retries only the conditions that resolve on their own:

- ``competing_service_active:<unit>`` and ``competing_launcher_active`` (a frozen
  unit still shutting down, or the timer firing before its stop took effect);
- ``insufficient_available_memory`` (the previous job's memory still returning).

Any other error (unknown outcome, identity change, closed session) is returned at
once, because waiting would hide a problem that needs a person. Exit codes:
0 ready, 3 timed out while retrying, 1 not retryable or misconfigured.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Run by path from tools/ops: bind the production package to this checkout first.
from scripts import tongxing_host  # noqa: E402,F401  binds the production package ports
from tongxing_production.compute.spark_exclusive_session import Client, SessionError  # noqa: E402

RETRYABLE_PREFIXES = ("competing_service_active:",)
RETRYABLE = {"competing_launcher_active", "insufficient_available_memory"}
EXIT_READY, EXIT_NOT_RETRYABLE, EXIT_TIMEOUT = 0, 1, 3


def retryable(code: str) -> bool:
    return code in RETRYABLE or code.startswith(RETRYABLE_PREFIXES)


def wait(client, *, poll_seconds: float = 30.0, max_minutes: float = 30.0,
         sleep=time.sleep, clock=time.monotonic, now=lambda: datetime.now(timezone.utc).isoformat()) -> dict:
    """Poll ``client.require_ready()``; the report lists every refusal seen."""
    if not 1 <= poll_seconds <= 600 or not 0 < max_minutes <= 720:
        raise ValueError("poll between 1 and 600 seconds, wait at most 12 hours")
    deadline = clock() + max_minutes * 60
    attempts = []
    while True:
        try:
            result = client.require_ready()
        except SessionError as error:
            code = str(error)
            attempts.append({"at": now(), "error": code})
            if not retryable(code):
                return {"status": "not_ready", "reason": code, "attempts": attempts}
            if clock() + poll_seconds > deadline:
                return {"status": "timeout", "reason": code, "attempts": attempts,
                        "waitedMinutes": max_minutes}
            sleep(poll_seconds)
            continue
        return {"status": "ready", "attempts": attempts, "result": result}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--max-minutes", type=float, default=30.0)
    args = parser.parse_args(argv)
    try:
        client = Client.from_environment()
    except (SessionError, KeyError, ValueError) as error:
        print(json.dumps({"status": "misconfigured", "reason": str(error)}), file=sys.stderr)
        return EXIT_NOT_RETRYABLE
    report = wait(client, poll_seconds=args.poll_seconds, max_minutes=args.max_minutes)
    print(json.dumps(report, ensure_ascii=False))
    return {"ready": EXIT_READY, "timeout": EXIT_TIMEOUT}.get(report["status"], EXIT_NOT_RETRYABLE)


if __name__ == "__main__":
    sys.exit(main())
