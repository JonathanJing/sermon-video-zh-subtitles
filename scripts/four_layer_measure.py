#!/usr/bin/env python3
"""Measure a four-layer command and audit timing coverage without changing gates.

The existing append-only sermon accounting ledger is the timing source. Tracker
status and human approvals remain separate operator/validator decisions.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import four_layer_progress as progress
from scripts import sermon_accounting as accounting

AUDIT_SCHEMA = "sermon-four-layer-timing-audit-v1"
STEP_PATTERN = re.compile(r"L[1-4]-\d{2}(?:@[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)?")


def stage_name(step_id: str) -> str:
    if not STEP_PATTERN.fullmatch(step_id):
        raise ValueError("invalid four-layer step ID")
    return "four_layer." + step_id.replace("@", ":")


def configured_ledger(path: Path | None) -> Path | None:
    """A weekly run opts in once; producer CLIs then record their own spans."""
    value = path or os.environ.get("SERMON_FOUR_LAYER_LEDGER")
    return Path(value) if value else None


@contextmanager
def producer_step(ledger_path: Path | None, step_id: str, *, locale: str | None = None):
    """Time a canonical producer without changing human review or tracker gates.

    The mutable workload holds counts and hashes only. A failed producer still
    closes its span; a killed process leaves an unmatched start for the audit.
    """
    metrics: dict = {}
    ledger_path = configured_ledger(ledger_path)
    if ledger_path is None:
        yield metrics
        return
    ledger = progress.load(ledger_path)
    step = ledger["steps"].get(step_id)
    if step is None or step.get("locale") != locale:
        raise ValueError("producer step or locale does not belong to this ledger")
    directory = ledger_path.parent / "accounting"
    inherited = os.environ.get("SERMON_ACCOUNTING_DIR")
    if inherited and Path(inherited).resolve() != directory.resolve():
        raise ValueError("producer accounting directory differs from progress ledger")
    with accounting.accounting_session(directory, "four_layer_producer",
                                       {"pageId": ledger["pageId"], "targetLocale": locale or "en"},
                                       evidence_directory=ledger_path.parent):
        with accounting.stage(stage_name(step_id), billing="local"):
            original_error = None
            try:
                yield metrics
            except BaseException as exc:
                original_error = exc
                raise
            finally:
                accounting._finalize(
                    lambda: accounting.record_workload(stage_name(step_id), metrics),
                    original_error,
                )


def execute(ledger_path: Path, step_id: str, command: list[str], *, billing: str = "local") -> int:
    ledger = progress.load(ledger_path)
    if step_id not in ledger["steps"]:
        raise ValueError("step does not belong to this ledger")
    if not command:
        raise ValueError("command is required after --")
    if billing not in {"local", "api", "orchestrator"}:
        raise ValueError("invalid billing category")
    accounting_dir = ledger_path.parent / "accounting"
    with accounting.accounting_session(accounting_dir, "four_layer_step"):
        with accounting.stage(stage_name(step_id), billing=billing):
            result = subprocess.run(command, env=accounting.subprocess_environment(), check=False)
            if result.returncode:
                raise subprocess.CalledProcessError(result.returncode, command)
    return 0


def timing_audit(ledger: dict, events: list[dict], *, damaged_rows: int = 0) -> dict:
    measured: dict[str, dict] = defaultdict(lambda: {"attempts": 0, "failedAttempts": 0,
                                                     "executionSeconds": 0.0,
                                                     "lastStatus": None, "lastAt": None})
    open_spans: dict[str, str] = {}
    attempt_history: dict[str, list[dict]] = defaultdict(list)
    by_span: dict[str, dict] = {}
    for event in events:
        if event.get("event") not in {"stage_started", "stage_finished", "workload"}:
            continue
        stage = str(event.get("stage") or "")
        if not stage.startswith("four_layer."):
            continue
        step = stage.removeprefix("four_layer.").replace(":", "@", 1)
        span_id = event.get("spanId")
        if event.get("event") == "stage_started":
            if step in ledger["steps"] and isinstance(span_id, str):
                open_spans[span_id] = step
                attempt = {"spanId": span_id, "startedAt": event.get("startedAt"),
                           "finishedAt": None, "status": "unfinished",
                           "elapsedSeconds": None, "workload": None}
                attempt_history[step].append(attempt)
                by_span[span_id] = attempt
            continue
        if event.get("event") == "workload":
            if isinstance(span_id, str) and span_id in by_span:
                by_span[span_id]["workload"] = event.get("metrics")
            continue
        open_spans.pop(span_id, None)
        elapsed = event.get("elapsedSeconds")
        if step not in ledger["steps"] or not isinstance(elapsed, (int, float)) or elapsed < 0:
            continue
        item = measured[step]
        item["attempts"] += 1
        item["failedAttempts"] += event.get("status") != "completed"
        item["executionSeconds"] += elapsed
        item["lastStatus"] = event.get("status") if event.get("status") in {"completed", "failed"} else None
        item["lastAt"] = event.get("recordedAt")
        if isinstance(span_id, str) and span_id in by_span:
            by_span[span_id].update(finishedAt=event.get("recordedAt"),
                                    status=item["lastStatus"], elapsedSeconds=elapsed)

    reviews: dict[str, dict] = defaultdict(lambda: {"closedWaitSeconds": 0.0,
                                                    "closedWaits": 0, "openWait": False})
    opened: dict[str, datetime] = {}
    for event in ledger.get("history", []):
        try:
            occurred = datetime.fromisoformat(event["at"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        if event.get("action") == "invalidate":
            for invalidated_step in event.get("steps", []):
                if invalidated_step in opened:
                    seconds = (occurred - opened.pop(invalidated_step)).total_seconds()
                    if seconds >= 0:
                        reviews[invalidated_step]["closedWaitSeconds"] += seconds
                        reviews[invalidated_step]["closedWaits"] += 1
            continue
        step = event.get("step")
        if event.get("action") != "update" or step not in ledger["steps"]:
            continue
        if step in opened and event.get("status") != "waiting_review":
            seconds = (occurred - opened.pop(step)).total_seconds()
            if seconds >= 0:
                reviews[step]["closedWaitSeconds"] += seconds
                reviews[step]["closedWaits"] += 1
        if event.get("status") == "waiting_review" and step not in opened:
            opened[step] = occurred
    for step in opened:
        reviews[step]["openWait"] = True

    rows = []
    for step, state in ledger["steps"].items():
        execution = measured.get(step)
        review = reviews.get(step)
        rows.append({"step": step, "status": state["status"],
                     "measuredExecutionSeconds": round(execution["executionSeconds"], 3) if execution else None,
                     "executionAttempts": execution["attempts"] if execution else 0,
                     "failedExecutionAttempts": execution["failedAttempts"] if execution else 0,
                     "lastExecutionStatus": execution["lastStatus"] if execution else None,
                     "lastExecutionAt": execution["lastAt"] if execution else None,
                     "openExecution": step in open_spans.values(),
                     "attemptHistory": attempt_history.get(step, []),
                     "operatorReviewWaitSeconds": round(review["closedWaitSeconds"], 3) if review and review["closedWaits"] else None,
                     "closedReviewWaits": review["closedWaits"] if review else 0,
                     "openReviewWait": review["openWait"] if review else False})
    return {"schemaVersion": AUDIT_SCHEMA, "pageId": ledger["pageId"],
            "target": ledger["target"], "accountingEvents": len(events),
            "damagedAccountingRows": damaged_rows,
            "measuredStepCount": len(measured),
            "completedWithoutMeasuredExecution": [row["step"] for row in rows
                                                  if row["status"] == "complete"
                                                  and row["measuredExecutionSeconds"] is None],
            "rows": rows,
            "limits": ["Operator review intervals use tracker update timestamps, not measured attention time.",
                       "Execution spans may overlap; their durations must not be summed as end-to-end time.",
                       "Missing spans are unknown, never zero."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run", help="measure one command under a tracker step")
    run.add_argument("--ledger", type=Path, required=True)
    run.add_argument("--step", required=True)
    run.add_argument("--billing", choices=("local", "api", "orchestrator"), default="local")
    run.add_argument("command", nargs=argparse.REMAINDER)
    audit = sub.add_parser("audit", help="read-only timing coverage preflight")
    audit.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "run":
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            return execute(args.ledger, args.step, command, billing=args.billing)
        ledger = progress.load(args.ledger)
        directory = args.ledger.parent / "accounting"
        events, damaged = accounting.read_events(directory) if (directory / "events.jsonl").exists() else ([], [])
        print(json.dumps(timing_audit(ledger, events, damaged_rows=len(damaged)), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"four-layer timing failed: {type(exc).__name__}", file=sys.stderr)
        return exc.returncode if isinstance(exc, subprocess.CalledProcessError) else 2


if __name__ == "__main__":
    raise SystemExit(main())
