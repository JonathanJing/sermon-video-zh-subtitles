#!/usr/bin/env python3
"""Read local workflow logs without rewriting receipts or contacting services."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.sermon_accounting import diagnostic_event, format_diagnostic, read_events

LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def inspect_logs(directory, *, run_id="latest", level="INFO", tail=50):
    events, damaged = read_events(directory)
    run_ids = list(dict.fromkeys(e["runId"] for e in events))
    # Select by run start, not whichever old child wrote most recently.
    starts = [e["runId"] for e in events if e["event"] == "run_started"]
    selected = (starts or run_ids)[-1] if run_id == "latest" and run_ids else run_id
    if selected != "all" and selected not in run_ids:
        raise ValueError("run_not_found")
    selected_events = [e for e in events if selected == "all" or e["runId"] == selected]
    diagnostics = [diagnostic_event(e) for e in selected_events]
    failed = [d for d in diagnostics if LEVELS[d["level"]] >= LEVELS["ERROR"]]
    warnings = [d for d in diagnostics if d["level"] == "WARNING"]
    unfinished = []
    for start, end, field in (("run_started", "run_finished", "runId"),
                              ("workflow_started", "workflow_finished", "workflowId"),
                              ("stage_started", "stage_finished", "spanId"),
                              ("api_attempt_started", "api_attempt", "attemptId"),
                              ("sdk_call_started", "sdk_call_finished", "invocationId")):
        ended = {(e["runId"], e.get(field)) for e in selected_events if e["event"] == end}
        for event in selected_events:
            if event["event"] == start and (event["runId"], event.get(field)) not in ended:
                unfinished.append({"event": start, "runId": event["runId"], "id": event.get(field),
                                   "status": "interrupted_or_running"})
    filtered = [d for d in diagnostics if LEVELS[d["level"]] >= LEVELS[level]]
    return {"schemaVersion": "sermon-log-inspection-v1", "runId": selected,
            "status": "needs_attention" if damaged or failed or unfinished else "no_detected_error",
            "ledgerIntegrity": "incomplete_corrupt_events" if damaged else "readable",
            "damagedEvents": damaged, "errorEvents": len(failed), "warningEvents": len(warnings),
            "unfinished": unfinished, "matchingEvents": len(filtered), "events": filtered[-tail:],
            "scope": "Local recorded execution only; no production acceptance or current process health inferred."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="The accounting directory containing events.jsonl")
    parser.add_argument("--run-id", default="latest", help="A run ID, latest (default), or all")
    parser.add_argument("--level", choices=LEVELS, default="INFO", help="Minimum severity")
    parser.add_argument("--tail", type=int, default=50, help="Maximum number of matching events (1..10000)")
    parser.add_argument("--json", action="store_true", help="Print a structured diagnostic view")
    parser.add_argument("--check", action="store_true", help="Exit 2 for errors, damaged or unfinished records; 3 for unreadable logs")
    args = parser.parse_args(argv)
    if not 1 <= args.tail <= 10000:
        parser.error("--tail must be between 1 and 10000")
    try:
        report = inspect_logs(args.directory, run_id=args.run_id, level=args.level, tail=args.tail)
    except (OSError, ValueError):
        # Never display filesystem/exception details that may contain credentials.
        print(json.dumps({"status": "unavailable", "reasonCode": "ledger_or_run_unavailable"}), file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"run={report['runId']} status={report['status']} errors={report['errorEvents']} warnings={report['warningEvents']} unfinished={len(report['unfinished'])} damaged={len(report['damagedEvents'])}")
        for event in report["events"]:
            print(format_diagnostic(event))
    return 2 if args.check and report["status"] == "needs_attention" else 0


if __name__ == "__main__":
    raise SystemExit(main())
