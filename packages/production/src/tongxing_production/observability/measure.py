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
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import four_layer_progress as progress
from scripts import sermon_accounting as accounting

AUDIT_SCHEMA = "sermon-four-layer-timing-audit-v1"
STEP_PATTERN = re.compile(r"L[1-4]-\d{2}(?:@[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)?")
SUBSTAGE_PATTERN = re.compile(r"[a-z][a-z0-9_]{1,39}")
PUBLIC_SUBSTAGES = {
    "initial_translation", "independent_review", "unit_synthesis",
    "audio_validation", "schedule_sync",
}
_producer_stage: ContextVar[str | None] = ContextVar("four_layer_producer_stage", default=None)


def stage_name(step_id: str) -> str:
    if not STEP_PATTERN.fullmatch(step_id):
        raise ValueError("invalid four-layer step ID")
    return "four_layer." + step_id.replace("@", ":")


@contextmanager
def producer_substage(name: str, *, billing: str = "api"):
    """Record one bounded child operation inside an active four-layer producer."""
    if not SUBSTAGE_PATTERN.fullmatch(name):
        raise ValueError("invalid four-layer substage ID")
    parent = _producer_stage.get() or accounting._stage.get() or os.environ.get("SERMON_ACCOUNTING_STAGE", "")
    if not parent.startswith("four_layer.L"):
        yield
        return
    if billing not in {"local", "api", "orchestrator"}:
        raise ValueError("invalid billing category")
    with accounting.stage(f"{parent}.sub.{name}", billing=billing):
        yield


def record_substage_metrics(metrics: dict) -> None:
    """Append only the supplied aggregate metrics to the active child span."""
    stage = accounting._stage.get() or os.environ.get("SERMON_ACCOUNTING_STAGE", "")
    if stage.startswith("four_layer.L") and ".sub." in stage:
        accounting.record_workload(stage, metrics)


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
                                       {"pageId": ledger["pageId"], "target": ledger["target"],
                                        "targetLocale": locale or "en",
                                        "ledgerIdentitySha256": progress.ledger_identity(ledger)},
                                       evidence_directory=ledger_path.parent):
        with accounting.stage(stage_name(step_id), billing="local"):
            producer_token = _producer_stage.set(stage_name(step_id))
            original_error = None
            try:
                yield metrics
            except BaseException as exc:
                original_error = exc
                raise
            finally:
                try:
                    accounting._finalize(
                        lambda: accounting.record_workload(stage_name(step_id), metrics),
                        original_error,
                    )
                finally:
                    _producer_stage.reset(producer_token)


def execute(ledger_path: Path, step_id: str, command: list[str], *, billing: str = "local") -> int:
    ledger = progress.load(ledger_path)
    if step_id not in ledger["steps"]:
        raise ValueError("step does not belong to this ledger")
    if not command:
        raise ValueError("command is required after --")
    if billing not in {"local", "api", "orchestrator"}:
        raise ValueError("invalid billing category")
    accounting_dir = ledger_path.parent / "accounting"
    with accounting.accounting_session(accounting_dir, "four_layer_step",
                                       {"pageId": ledger["pageId"], "target": ledger["target"],
                                        "ledgerIdentitySha256": progress.ledger_identity(ledger)}):
        with accounting.stage(stage_name(step_id), billing=billing):
            result = subprocess.run(command, env=accounting.subprocess_environment(), check=False)
            if result.returncode:
                raise subprocess.CalledProcessError(result.returncode, command)
    return 0


def timing_audit(ledger: dict, events: list[dict], *, damaged_rows: int = 0) -> dict:
    identity = progress.ledger_identity(ledger)
    def matching(metadata: object) -> bool:
        return (isinstance(metadata, dict)
                and metadata.get("pageId") == ledger["pageId"]
                and metadata.get("target") == ledger["target"]
                and metadata.get("ledgerIdentitySha256") == identity)
    workflow_ids = {event.get("workflowId") for event in events
                    if event.get("event") == "workflow_started" and matching(event.get("metadata"))}
    # Producer accounting sessions inherit the canonical step's workflow.
    for event in events:
        if event.get("event") == "workflow_started" and event.get("parentWorkflowId") in workflow_ids:
            workflow_ids.add(event.get("workflowId"))
    scoped_events = [event for event in events
                     if event.get("workflowId") in workflow_ids
                     and event.get("workflowId") is not None]
    measured: dict[str, dict] = defaultdict(lambda: {"attempts": 0, "failedAttempts": 0,
                                                     "executionSeconds": 0.0,
                                                     "lastStatus": None, "lastAt": None})
    open_spans: dict[str, str] = {}
    attempt_history: dict[str, list[dict]] = defaultdict(list)
    by_span: dict[str, dict] = {}
    substage_runs: dict[str, dict[str, dict[str, dict]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: {
            "attempts": 0, "failedAttempts": 0, "executionSeconds": 0.0,
            "completedUnits": 0, "running": 0, "metrics": {}})))
    substage_spans: dict[str, tuple[str, str, str]] = {}
    span_parents: dict[str, str | None] = {}
    step_stage_names = {stage_name(step): step for step in ledger["steps"]}
    for event in scoped_events:
        if event.get("event") not in {"stage_started", "stage_finished", "workload"}:
            continue
        if event.get("event") == "stage_started" and isinstance(event.get("spanId"), str):
            span_parents[event["spanId"]] = event.get("parentSpanId")
        event_stage = str(event.get("stage") or "")
        step = step_stage_names.get(event_stage)
        substage = None
        if step is None:
            for parent_stage, candidate in step_stage_names.items():
                prefix = parent_stage + ".sub."
                if event_stage.startswith(prefix):
                    step = candidate
                    substage = event_stage[len(prefix):]
                    if not SUBSTAGE_PATTERN.fullmatch(substage):
                        step = None
                    break
        if step is None:
            continue
        span_id = event.get("spanId")
        if event.get("event") == "stage_started":
            if step in ledger["steps"] and isinstance(span_id, str):
                if substage:
                    parent_span = event.get("parentSpanId")
                    while isinstance(parent_span, str) and parent_span not in by_span:
                        parent_span = span_parents.get(parent_span)
                    if parent_span not in by_span:
                        continue
                    row = substage_runs[step][parent_span][substage]
                    row["attempts"] += 1
                    row["running"] += 1
                    substage_spans[span_id] = (step, parent_span, substage)
                    continue
                open_spans[span_id] = step
                attempt = {"spanId": span_id, "startedAt": event.get("startedAt"),
                           "finishedAt": None, "status": "unfinished",
                           "elapsedSeconds": None, "workload": None}
                attempt_history[step].append(attempt)
                by_span[span_id] = attempt
            continue
        if event.get("event") == "workload":
            if isinstance(span_id, str) and span_id in by_span:
                by_span[span_id]["workload"] = {
                    **(by_span[span_id].get("workload") or {}),
                    **(event.get("metrics") if isinstance(event.get("metrics"), dict) else {}),
                }
            elif isinstance(span_id, str) and span_id in substage_spans:
                child_step, parent_span, child_id = substage_spans[span_id]
                metrics = event.get("metrics") if isinstance(event.get("metrics"), dict) else {}
                safe_keys = {"audioSeconds", "overLimitUnits", "clipDurationSeconds",
                             "plannedDurationSeconds"}
                target = substage_runs[child_step][parent_span][child_id]["metrics"]
                for key, value in metrics.items():
                    if key not in safe_keys or not isinstance(value, (int, float)) or isinstance(value, bool):
                        continue
                    target[key] = target.get(key, 0) + value if key == "audioSeconds" else value
            continue
        if substage and isinstance(span_id, str) and span_id in substage_spans:
            _, parent_span, _ = substage_spans[span_id]
            row = substage_runs[step][parent_span][substage]
            row["running"] = max(0, row["running"] - 1)
            elapsed = event.get("elapsedSeconds")
            if isinstance(elapsed, (int, float)) and elapsed >= 0:
                row["executionSeconds"] += elapsed
            if event.get("status") == "completed":
                row["completedUnits"] += 1
            else:
                row["failedAttempts"] += 1
            substage_spans.pop(span_id, None)
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
    blockers: dict[str, dict] = defaultdict(lambda: {"closedWaitSeconds": 0.0,
                                                     "closedWaits": 0, "openWait": False})
    opened: dict[tuple[str, str], datetime] = {}
    for event in ledger.get("history", []):
        try:
            occurred = datetime.fromisoformat(event["at"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        if event.get("action") == "invalidate":
            for invalidated_step in event.get("steps", []):
                for state, bucket in (("waiting_review", reviews), ("blocked", blockers)):
                    key = (invalidated_step, state)
                    if key in opened:
                        seconds = (occurred - opened.pop(key)).total_seconds()
                        if seconds >= 0:
                            bucket[invalidated_step]["closedWaitSeconds"] += seconds
                            bucket[invalidated_step]["closedWaits"] += 1
            continue
        step = event.get("step")
        if event.get("action") != "update" or step not in ledger["steps"]:
            continue
        for state, bucket in (("waiting_review", reviews), ("blocked", blockers)):
            key = (step, state)
            if key in opened and event.get("status") != state:
                seconds = (occurred - opened.pop(key)).total_seconds()
                if seconds >= 0:
                    bucket[step]["closedWaitSeconds"] += seconds
                    bucket[step]["closedWaits"] += 1
            if event.get("status") == state and key not in opened:
                opened[key] = occurred
    for step, state in opened:
        (reviews if state == "waiting_review" else blockers)[step]["openWait"] = True

    reported: dict[str, dict] = defaultdict(dict)
    for event in ledger.get("history", []):
        if event.get("action") == "invalidate":
            for key in event.get("steps", []):
                if key in ledger["steps"]:
                    reported[key] = {"lastStatus": "pending"}
            continue
        key = event.get("step")
        if event.get("action") != "update" or key not in ledger["steps"]:
            continue
        status = event.get("status")
        if status == "running" and "firstRunningAt" not in reported[key]:
            reported[key]["firstRunningAt"] = event.get("at")
        if status == "complete":
            reported[key]["lastCompletedAt"] = event.get("at")
        reported[key]["lastStatus"] = status

    rows = []
    now_utc = datetime.now(timezone.utc)
    for step, state in ledger["steps"].items():
        execution = measured.get(step)
        review = reviews.get(step)
        child_rows = []
        latest_parent = attempt_history.get(step, [])[-1]["spanId"] if attempt_history.get(step) else None
        latest_substages = substage_runs.get(step, {}).get(latest_parent, {})
        parent_workload = next((attempt.get("workload") for attempt in reversed(attempt_history.get(step, []))
                                if attempt.get("spanId") == latest_parent and attempt.get("workload")), {})
        total_units = None
        if isinstance(parent_workload, dict):
            count_key = "translationGroups" if step.startswith("L2-") else "speechUnits"
            total_units = parent_workload.get(count_key)
        for substage, data in sorted(latest_substages.items()):
            child_total_units = None if substage == "schedule_sync" else total_units
            open_ages = []
            for span_id, (open_step, open_parent, open_substage) in substage_spans.items():
                if open_step == step and open_parent == latest_parent and open_substage == substage:
                    started_event = next((e for e in reversed(scoped_events)
                                          if e.get("event") == "stage_started"
                                          and e.get("spanId") == span_id), None)
                    if started_event:
                        try:
                            started = datetime.fromisoformat(started_event["startedAt"].replace("Z", "+00:00"))
                            open_ages.append(max(0.0, (now_utc - started).total_seconds()))
                        except (KeyError, TypeError, ValueError):
                            pass
            child_rows.append({"id": substage, "attempts": data["attempts"],
                               "failedAttempts": data["failedAttempts"],
                               "completedUnits": data["completedUnits"],
                               "totalUnits": child_total_units,
                               "running": data["running"],
                               "executionSeconds": round(data["executionSeconds"], 3),
                               "openElapsedSeconds": round(max(open_ages), 3) if open_ages else None,
                               **data["metrics"]})
        blocker = blockers.get(step)
        reported_step = reported.get(step, {})
        rows.append({"step": step, "status": state["status"],
                     "reportedFirstRunningAt": reported_step.get("firstRunningAt"),
                     "reportedLastCompletedAt": reported_step.get("lastCompletedAt"),
                     "statusHistoryMatchesCurrent": reported_step.get("lastStatus", "pending") == state["status"],
                     "measuredExecutionSeconds": round(execution["executionSeconds"], 3) if execution else None,
                     "executionAttempts": execution["attempts"] if execution else 0,
                     "failedExecutionAttempts": execution["failedAttempts"] if execution else 0,
                     "lastExecutionStatus": execution["lastStatus"] if execution else None,
                     "lastExecutionAt": execution["lastAt"] if execution else None,
                     "openExecution": step in open_spans.values(),
                     "attemptHistory": attempt_history.get(step, []),
                     "operatorReviewWaitSeconds": round(review["closedWaitSeconds"], 3) if review and review["closedWaits"] else None,
                     "closedReviewWaits": review["closedWaits"] if review else 0,
                     "openReviewWait": review["openWait"] if review else False,
                     "blockedWaitSeconds": round(blocker["closedWaitSeconds"], 3) if blocker and blocker["closedWaits"] else None,
                     "closedBlockedWaits": blocker["closedWaits"] if blocker else 0,
                     "openBlockedWait": blocker["openWait"] if blocker else False,
                     "subStages": child_rows})
    missing_completed = [row["step"] for row in rows
                         if row["status"] == "complete"
                         and row["measuredExecutionSeconds"] is None]
    missing_starts = [row["step"] for row in rows
                      if row["status"] == "complete" and row["reportedFirstRunningAt"] is None]
    mismatched_history = [row["step"] for row in rows if not row["statusHistoryMatchesCurrent"]]
    return {"schemaVersion": AUDIT_SCHEMA, "pageId": ledger["pageId"],
            "target": ledger["target"], "accountingEvents": len(events),
            "scopedAccountingEvents": len(scoped_events),
            "damagedAccountingRows": damaged_rows,
            "measuredStepCount": len(measured),
            "completedWithoutMeasuredExecutionCount": len(missing_completed),
            "completedWithoutMeasuredExecution": missing_completed,
            "completedWithoutReportedStartCount": len(missing_starts),
            "completedWithoutReportedStart": missing_starts,
            "statusHistoryMismatchCount": len(mismatched_history),
            "statusHistoryMismatch": mismatched_history,
            "rows": rows,
            "limits": ["Operator review intervals use tracker update timestamps, not measured attention time.",
                       "Unscoped or different-ledger accounting events are excluded from timing.",
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
