#!/usr/bin/env python3
"""Closed public, read-only projection of one explicitly selected accounting run.

The private weekly report owns observed DAG/timing validation. The optional frozen
plan and FULL trusted-validator receipts are passed to sermon_run_progress; this
adapter does not validate original artifacts, invent ETA, or grant approval.
Never publish either private intermediate. No provider, dispatcher or publisher
is invoked. CLI output is a separate local file (or stdout).
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import sermon_accounting as accounting
from scripts import sermon_run_progress as progress
from scripts import weekly_pipeline_report as weekly

SCHEMA = "sermon-public-tracker-dag-v1"
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_OUTPUT_BYTES = 384 * 1024
MAX_NODES = 256
MAX_SECONDS = 366 * 24 * 60 * 60
LOCALES = frozenset({"en", "zh-Hans", "ko", "es", "vi"})
NODE_CODES = frozenset({"initial_translation", "independent_review", "unit_synthesis",
                       "audio_validation", "schedule_sync", "translation", "review", "asr",
                       "tts", "validation", "publication", "source", "unknown"})
# Exact input identities only. New models require an explicit public-code change;
# neither regex/prefix matching nor caller-supplied labels can expose identifiers.
MODEL_CODES = {
    **{name: name for name in ("gpt-6-astra", "gpt-6-sol", "gpt-6-luna")},
    "Qwen/Qwen3-ASR-0.6B": "qwen3-asr", "Qwen/Qwen3-ASR-1.7B": "qwen3-asr",
    "mlx-community/Qwen3-ASR-0.6B-8bit": "qwen3-asr",
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base": "qwen3-tts",
    "Qwen3-TTS-12Hz-1.7B-CustomVoice-finetuned": "qwen3-tts",
    "large-v3": "whisper", "openai/whisper-large-v3": "whisper",
}
OBSERVED_STATUSES = frozenset({"completed", "failed", "cancelled", "outcome_unknown", "unfinished_or_ambiguous"})
# No upstream free-form diagnostic is copied. This intentionally loses private
# detail while preserving useful public reasons and uncertainty.
REASONS = frozenset({
    "accounting_missing", "accounting_invalid", "accounting_too_large", "run_not_found",
    "damaged_events", "unsupported_schema", "conflicting_event_identity",
    "incomplete_or_conflicting_profile_events", "accounting_partial", "node_limit",
    "future_observation", "progress_inputs_invalid", "progress_run_mismatch",
    "progress_plan_missing", "progress_partial", "no_comparable_history", "ledger_run_binding_mismatch",
    "resource_state_missing", "resource_queue_or_configuration_unknown", "unit_queue_unknown",
    "unknown_attempt_outcome", "blocked", "unknown_outcome", "waiting_review", "observed_blocker",
    "retry_or_reconciliation_not_authorized", "human_review_remaining", "unresolved_post_execution_gate",
    "running_dependency_unresolved", "heartbeat_or_active_elapsed_unknown",
    "active_duration_exceeds_empirical_envelope", "running_units_contradict_available_resource_slots",
    "invalid_or_conflicting_empirical_sample", "invalid_conflicting_or_unbound_receipt",
    "conflicting_unit_sequence", "synthetic_evidence_not_production_approval",
    "evidence_mode_not_established", "stale_observations", "upstream_evidence_issue",
})
ARTIFACT_CODES = frozenset({
    "layer2_request", "layer2_run_identity", "layer2_evidence", "layer2_candidate",
    "layer2_language_review", "render_manifest", "same_video_source", "same_video_archive",
    "same_video_handoff", "same_video_pdf_render", "source", "summary", "reading",
    "reading_pdf_qa", "companion_pdf_qa", "notes", "context_pack", "window_approval",
    "timeline", "generation", "job", "render", "audio_qa", "synchronization",
    "anchor_approval", "alignment", "workflow_receipt",
})


def _number(value, maximum=2**53 - 1):
    return value if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= maximum else None


def _time(value):
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and len(value) <= 40:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("invalid_time")
    if result.tzinfo is None:
        raise ValueError("timezone_required")
    return result.astimezone(timezone.utc)


def _reasons(values):
    return sorted({value if isinstance(value, str) and value in REASONS else "upstream_evidence_issue"
                   for value in values})


def _mode(events):
    # A legacy loose envelope cannot establish real/synthetic provenance merely
    # by adding an arbitrary evidenceMode field.
    modes = {e.get("evidenceMode") if e.get("contractVersion") == "sermon-accounting-log-contract-v1"
             else None for e in events}
    if "synthetic" in modes:
        return "synthetic" if modes == {"synthetic"} else "mixed"
    return "real" if modes and modes <= {"current_execution", "cache_replay"} else "unknown"


def _labels(stage, locale=None):
    code, layer = "unknown", None
    if stage in NODE_CODES:
        code = stage
    if isinstance(stage, str):
        match = re.fullmatch(r"four_layer\.L([1-4])-\d{2}(?::(en|zh-Hans|ko|es|vi))?(?:\.sub\.([a-z_]+))?", stage)
        if match:
            layer = int(match[1])
            locale = match[2] or locale
            code = match[3] if match[3] in NODE_CODES else "unknown"
    return {"code": code, "layer": layer, "locale": locale if locale in LOCALES else "unknown"}


def _models(values):
    codes = sorted({MODEL_CODES[value] for value in values if isinstance(value, str) and value in MODEL_CODES})
    known = sum(isinstance(value, str) and value in MODEL_CODES for value in values)
    return {"modelCodes": codes, "modelStatus": "not_observed" if not values else
            "allowlisted" if known == len(values) else "partial" if codes else "unknown"}


def _empty_io():
    return {"inputArtifactCount": None, "outputArtifactCount": None, "status": "not_observed"}


def _empty_timing(status="not_observed"):
    return {"status": status, "startSeconds": None, "endSeconds": None,
            "elapsedSeconds": None, "activeElapsedSeconds": None}


def _unknown_eta(reason):
    return {"status": "unknown", "lowerSeconds": None, "upperSeconds": None,
            "remainingSerialSeconds": None, "criticalPathSeconds": None, "sampleCount": 0,
            "confidence": "unknown", "reasonCodes": _reasons([reason]),
            "estimatorVersion": progress.ESTIMATOR_VERSION}


def _blank(clock, reason):
    return {"schemaVersion": SCHEMA, "scope": "accounting_run", "generatedAt": clock.isoformat(),
            "executionAuthority": "none", "acceptance": "not_evaluated", "evidenceMode": "unknown",
            "freshness": {"status": "unknown", "sourceObservedAt": None, "ageSeconds": None},
            "quality": {"status": "unavailable", "reasonCodes": [reason], "damagedRowCount": 0,
                        "duplicateEventsIgnored": 0, "omittedNodeCount": 0},
            "summary": {"observedNodeCount": 0, "completedSpanCount": 0, "unfinishedSpanCount": 0,
                        "failedSpanCount": 0, "retryCount": None, "measuredSpanSeconds": None,
                        "endToEndWallSeconds": None}, "nodes": [],
            "criticalPath": {"status": "unknown", "activeSeconds": None, "nodeIds": [], "durationBasis": None},
            "io": {"status": "not_observed", "beforeArtifactCount": None, "afterArtifactCount": None,
                   "categories": [], "scope": "observed_file_snapshots_not_execution_proof"},
            "logs": {"schemaVersions": [], "contractVersions": [], "eventCount": 0, "profileEventCount": 0,
                     "legacyEventCount": 0, "damagedRowCount": 0},
            "progress": None, "eta": _unknown_eta("progress_plan_missing")}


def _snapshot(directory):
    """Copy one bounded locked byte snapshot; reuse BOTH canonical readers on it.

    This avoids two racing reads of a live ledger without modifying the canonical
    report API or repairing/re-encoding damaged input. Temp storage is private.
    """
    source = Path(directory) / "events.jsonl"
    with source.open("rb") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
        data = stream.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("accounting_too_large")
    with tempfile.TemporaryDirectory(prefix="tracker-dag-") as tmp:
        (Path(tmp) / "events.jsonl").write_bytes(data)
        events, damaged = accounting.read_events(tmp)
        report = weekly.project(tmp)
    return events, damaged, report


def verify_ledger_run_binding(ledger, events, run_id):
    """Require every non-wrapper observation in this run to descend from a bound
    tracker workflow. A match in one unrelated sibling is insufficient. Read-only
    adapter helper; caller must supply events from the canonical accounting reader.
    """
    from scripts.four_layer_progress import ledger_identity
    supported = [e for e in events if e.get("schemaVersion") in accounting.READABLE_SCHEMAS
                 and accounting._valid_event(e)]
    selected = [e for e in supported if e.get("runId") == run_id]
    excluded = accounting.profile_integrity(supported)["_excluded"]
    if any(id(event) in excluded for event in selected):
        return False
    seen = {}
    for event in selected:
        if event["eventId"] in seen and seen[event["eventId"]] != event:
            return False
        seen[event["eventId"]] = event
    workflows = [e for e in selected if e.get("event") == "workflow_started"]
    definitions = {}
    for event in workflows:
        key = event.get("workflowId")
        parent = event.get("parentWorkflowId")
        definition = (parent, event.get("metadata"))
        if (not isinstance(key, str) or parent is not None and not isinstance(parent, str)
                or event.get("metadata") is not None and not isinstance(event["metadata"], dict)
                or key == parent or key in definitions and definitions[key] != definition):
            return False
        definitions[key] = definition
    for key in definitions:
        visited, cursor = set(), key
        while cursor in definitions:
            if cursor in visited:
                return False
            visited.add(cursor)
            cursor = definitions[cursor][0]
    identity = ledger_identity(ledger)
    expected = {"pageId": ledger["pageId"], "target": ledger["target"], "ledgerIdentitySha256": identity}
    bound = {e.get("workflowId") for e in workflows if isinstance(e.get("metadata"), dict)
             and e["metadata"].get("pageId") == ledger["pageId"]
             and e["metadata"].get("target") == ledger["target"]
             and e["metadata"].get("ledgerIdentitySha256") == identity}
    bound.discard(None)
    if not bound:
        return False
    while True:
        expanded = bound | {e.get("workflowId") for e in workflows if e.get("parentWorkflowId") in bound}
        expanded.discard(None)
        if expanded == bound:
            break
        bound = expanded
    for event in workflows:
        if event.get("workflowId") in bound:
            metadata = event.get("metadata")
            if isinstance(metadata, dict) and any(key in metadata and metadata[key] != value
                                                 for key, value in expected.items()):
                return False
    stage_workflows = {e.get("workflowId") for e in selected
                       if e.get("event") in {"stage_started", "stage_finished"}}
    if not stage_workflows or not stage_workflows <= bound:
        return False
    return all(e.get("workflowId") in bound or e.get("workflowId") is None
               and e.get("event") in {"run_started", "run_finished"} for e in selected)


def _observed(result, run, events, report, clock, stale_after_seconds, *, all_events):
    mode = _mode(events)
    result["evidenceMode"] = mode
    measured = run["workUnits"]
    by_span = defaultdict(list)
    replay = accounting.profile_integrity(all_events)
    event_copies = defaultdict(list)
    for event in events:
        event_copies[event["eventId"]].append(event)
    safe_events = [copies[0] for copies in event_copies.values()
                   if all(copy == copies[0] for copy in copies) and id(copies[0]) not in replay["_excluded"]]
    for event in safe_events:
        if event.get("spanId"):
            by_span[weekly.digest(event["spanId"])].append(event)
    stamps = [_time(e["recordedAt"]) for e in safe_events]
    latest = max(stamps) if stamps else None
    future = latest is not None and latest > clock
    age = (clock - latest).total_seconds() if latest is not None else None
    result["freshness"] = {"status": "unknown" if future or latest is None else
                           "stale" if age >= stale_after_seconds else "fresh",
                           "sourceObservedAt": latest.isoformat() if latest else None,
                           "ageSeconds": _number(age, MAX_SECONDS)}
    reasons = list(report["diagnostics"])
    if run["status"] != "projected":
        reasons.append("accounting_partial")
    if future:
        reasons.append("future_observation")
    unfinished = []
    for supplied in run["unfinishedSpans"]:
        row = dict(supplied)
        pair = [e for e in by_span[row["spanSha256"]] if e["event"] in {"stage_started", "stage_finished"}]
        # weekly's unfinished representative is diagnostic, not an identity
        # decision. Conflicting legacy copies must never be first-row-wins.
        for field in ("stage", "executorType", "startedAt"):
            values = {e[field] for e in pair if e.get(field) is not None}
            row[field] = next(iter(values)) if len(values) == 1 else None
        unfinished.append(row)
    rows = sorted([*measured, *unfinished], key=lambda r: (_time(r["startedAt"]) if r.get("startedAt") else
                    datetime.min.replace(tzinfo=timezone.utc), r["spanSha256"]))
    omitted = max(0, len(rows) - MAX_NODES)
    if omitted:
        reasons.append("node_limit")
    rows = rows[:MAX_NODES]
    ids = {row["spanSha256"]: f"n{index + 1}" for index, row in enumerate(rows)}
    groups = defaultdict(list)
    for row in measured:
        if row.get("workUnitId") and row.get("attemptSha256"):
            groups[row["workUnitId"]].append(row)
    attempts = {}
    for group in groups.values():
        order = sorted({(_time(r["startedAt"]), r["attemptSha256"]) for r in group})
        # A repeated span of one attempt is not another retry.
        unique = list(dict.fromkeys(attempt for _, attempt in order))
        attempts.update({r["spanSha256"]: (unique.index(r["attemptSha256"]) + 1, len(unique) - 1) for r in group})
    origin = min(stamps) if stamps else clock
    nodes = []
    for row in rows:
        key = row["spanSha256"]
        status = row["status"] if row["status"] in OBSERVED_STATUSES else "unfinished_or_ambiguous"
        timing = _empty_timing("unfinished" if status == "unfinished_or_ambiguous" else "measured")
        if status != "unfinished_or_ambiguous":
            timing["elapsedSeconds"] = _number(row.get("elapsedSeconds"), MAX_SECONDS)
            if row.get("utcTimingTrusted", True) and not future:
                timing["startSeconds"] = _number((_time(row["startedAt"]) - origin).total_seconds(), MAX_SECONDS)
                timing["endSeconds"] = _number((_time(row["finishedAt"]) - origin).total_seconds(), MAX_SECONDS)
        deps = row.get("dependsOnSha256", [])
        dependency_status = "recorded" if row.get("dependencyRecorded") else "unknown"
        model_values = row.get("models", [])
        if status == "unfinished_or_ambiguous":
            starts = [event for event in by_span[key] if event["event"] == "stage_started"]
            finishes = [event for event in by_span[key] if event["event"] == "stage_finished"]
            if len(starts) == 1 and not finishes and isinstance(starts[0].get("dependsOn"), list):
                deps = [weekly.digest(dep) for dep in starts[0]["dependsOn"]]
                dependency_status = "recorded"
                # Only canonical receipt facts establish observed model identity;
                # api_attempt_started/requestedModel alone is merely intention.
                if run["usage"]["status"] == "consistent":
                    model_values = [receipt["model"] for receipt in run["usage"]["directReceipts"]
                                    if receipt.get("spanSha256") == key and receipt.get("model")]
                    model_values += [fact["model"] for fact in run["localModelObservations"]
                                     if fact.get("spanSha256") == key]
        if dependency_status == "recorded" and any(dep not in ids for dep in deps):
            dependency_status = "partial"
        number, retries = attempts.get(key, (None, None))
        nodes.append({"id": ids[key], "kind": "observed", **_labels(row.get("stage")),
                      "executorType": row.get("executorType") if row.get("executorType") in accounting.EXECUTOR_TYPES else "unknown",
                      **_models(model_values), "dependsOn": [ids[d] for d in deps if d in ids],
                      "dependencyStatus": dependency_status,
                      "unresolvedDependencyCount": sum(d not in ids for d in deps),
                      "status": status, "evidenceMode": _mode(by_span[key]),
                      "attemptNumber": number, "retryCount": retries, "timing": timing, "io": _empty_io()})
    remaining = {node["id"] for node in nodes}
    while remaining:
        ready = {node["id"] for node in nodes if node["id"] in remaining
                 and not set(node["dependsOn"]) & remaining}
        if not ready:
            break
        remaining -= ready
    if "dependency_cycle" in run["diagnostics"] or remaining:
        if remaining and "accounting_partial" not in reasons:
            reasons.append("accounting_partial")
        for node in nodes:
            node["dependencyStatus"] = "unknown"
            node["unresolvedDependencyCount"] += len(node["dependsOn"])
            node["dependsOn"] = []
    result["nodes"] = nodes
    result["summary"] = {"observedNodeCount": len(measured) + len(unfinished),
        "completedSpanCount": len(measured), "unfinishedSpanCount": len(unfinished),
        "failedSpanCount": sum(r["status"] == "failed" for r in measured),
        "retryCount": sum(len({r["attemptSha256"] for r in group}) - 1 for group in groups.values())
        if measured and len(attempts) == len(measured) and not unfinished else None,
        "measuredSpanSeconds": _number(sum(r["elapsedSeconds"] for r in measured), MAX_SECONDS) if measured else None,
        "endToEndWallSeconds": _number(run["endToEndWallSeconds"], MAX_SECONDS)}
    result["quality"].update(status="partial" if reasons else "projected", reasonCodes=_reasons(reasons),
                             duplicateEventsIgnored=report["duplicateEventsIgnored"], omittedNodeCount=omitted)
    cp = run["criticalPath"]
    if cp and not future and not omitted and all(key in ids for key in cp["spanPath"]):
        result["criticalPath"] = {"status": "measured", "activeSeconds": _number(cp["activeSeconds"], MAX_SECONDS),
            "nodeIds": [ids[key] for key in cp["spanPath"]],
            "durationBasis": cp["durationBasis"] if cp["durationBasis"] in
            {"verified_monotonic_dag", "recorded_utc_intervals"} else None}
    snapshots = run["artifactSnapshots"]
    categories, counts = Counter(), {}
    for phase in ("before", "after"):
        selected = [s for s in snapshots if s["phase"] == phase]
        # Same artifact appearing in repeated snapshots is availability once,
        # never another generated output or evidence of an execution.
        facts = {(a["category"], a["sha256"]) for s in selected for a in s["artifacts"]
                 if a["category"] in ARTIFACT_CODES}
        counts[phase] = len(facts) if selected else None
        categories.update(category for category, _ in facts)
    result["io"] = {"status": "observed" if snapshots else "not_observed",
        "beforeArtifactCount": counts["before"], "afterArtifactCount": counts["after"],
        "categories": sorted(categories), "scope": "observed_file_snapshots_not_execution_proof"}


def _planned(result, inputs, run_id, clock):
    allowed = {"plan", "receipts", "samples", "resource_state", "reconciliations", "previous"}
    if not isinstance(inputs, dict) or set(inputs) - allowed or not {"plan", "receipts"} <= inputs.keys():
        raise ValueError("progress_inputs_invalid")
    plan = inputs["plan"]
    progress.validate_plan(plan)
    if plan["runId"] != run_id:
        raise ValueError("progress_run_mismatch")
    if len(plan["units"]) > MAX_NODES:
        raise ValueError("node_limit")
    projected = progress.project_progress(**inputs, at=clock)
    mode = result["evidenceMode"]
    production = mode == "real"
    specs = {row["id"]: row for row in plan["units"]}
    ids = {row["unitId"]: f"p{index + 1}" for index, row in enumerate(projected["units"])}
    observations = defaultdict(list)
    if projected["integrity"]["status"] == "consistent":
        for receipt in inputs["receipts"]:
            # Canonical validation has already accepted these closed envelopes.
            # No wall-clock subtraction is a substitute for measured active time.
            observations[receipt["unitId"]].append(receipt)
    nodes = []
    for row in projected["units"]:
        spec = specs[row["unitId"]]
        timing = _empty_timing()
        history = observations[row["unitId"]]
        current = max(history, key=lambda r: r["sequence"]) if history else None
        if current and current["attemptId"] == row["attemptId"] and not row["unknownOutcome"]:
            if current["executionStatus"] == "running" and row["heartbeatStatus"] == "fresh":
                timing.update(status="partial", activeElapsedSeconds=_number(current["activeElapsedSeconds"], MAX_SECONDS))
            elif current["measurementValidated"] and current["executionStatus"] == "succeeded":
                timing.update(status="measured", elapsedSeconds=_number(current["elapsedSeconds"], MAX_SECONDS))
        evidence = {key: row[key] if production or key not in {"realHumanApproved", "admitted"} else False
                    for key in progress.COUNTS}
        nodes.append({"id": ids[row["unitId"]], "kind": "planned", **_labels(spec["stage"], spec["locale"]),
            "executorType": "unknown", **_models([spec["model"]] if spec["model"] != "none" else []),
            "dependsOn": [ids[key] for key in spec["dependsOn"]], "dependencyStatus": "recorded", "unresolvedDependencyCount": 0,
            "status": row["phase"], "evidenceMode": mode, "attemptNumber": None,
            "retryCount": row["retryCount"], "timing": timing, "io": _empty_io(),
            "evidence": evidence, "requiredEvidence": list(spec["requiredEvidence"]),
            "complete": row["complete"] and production, "processedKnown": row["processedKnown"],
            "unknownOutcome": row["unknownOutcome"], "heartbeatStatus": row["heartbeatStatus"]})
    counts = dict(projected["counts"])
    if not production:
        counts.update(realHumanApproved=0, admitted=0, done=0)
    result["progress"] = {"status": projected["integrity"]["status"], "planVersion": _number(plan["planVersion"]),
        "denominator": plan["denominator"], "plannedProcessedPercent": projected["plannedProcessedPercent"],
        "knownProcessedPercentLowerBound": projected["knownProcessedPercentLowerBound"],
        "gateCompletionPercent": projected["gateCompletionPercent"] if production else None,
        "complete": projected["complete"] and production, "counts": counts,
        "extraWork": dict(projected["extraWork"]), "nodes": nodes}
    eta = projected["eta"]
    result["eta"] = {"status": eta["status"], **{k: _number(eta[k], MAX_SECONDS) for k in
        ("lowerSeconds", "upperSeconds", "remainingSerialSeconds", "criticalPathSeconds")},
        "sampleCount": eta["sampleCount"], "confidence": eta["confidence"],
        "reasonCodes": _reasons(eta["reasonCodes"]), "estimatorVersion": progress.ESTIMATOR_VERSION}
    blockers = []
    if not production:
        blockers.append("synthetic_evidence_not_production_approval" if mode in {"synthetic", "mixed"}
                        else "evidence_mode_not_established")
    if result["quality"]["status"] == "unavailable" or "damaged_events" in result["quality"]["reasonCodes"]:
        blockers.append("accounting_partial")
    # Resource/heartbeat freshness remains owned by the canonical ETA projector;
    # accounting event freshness is observational and is not a worker heartbeat.
    if blockers:
        result["eta"] = {**_unknown_eta(blockers[0]), "sampleCount": eta["sampleCount"],
                         "reasonCodes": _reasons([*eta["reasonCodes"], *blockers])}
    if projected["integrity"]["status"] != "consistent":
        result["quality"]["status"] = "partial"
        result["quality"]["reasonCodes"] = _reasons([*result["quality"]["reasonCodes"], "progress_partial"])


def build_projection(accounting_dir, *, run_id, at=None, progress_inputs=None, stale_after_seconds=300, ledger=None):
    """Project one exact private run ID, never choose latest or bind by filename.

    Pass ledger when embedding in a page to check ledger/run binding against
    the exact same frozen bytes. Public IDs are snapshot-local: late historical
    observations can renumber them and they must not persist across runs. Unavailable/malformed sources return a safe unknown projection.
    Optional receipts must already originate from the existing local validator;
    their closed envelope, identities, ordering and ETA are checked canonically.
    """
    clock = _time(at) if at is not None else datetime.now(timezone.utc)
    if not isinstance(run_id, str) or not run_id or len(run_id) > 200:
        raise ValueError("explicit_run_id_required")
    if _number(stale_after_seconds, MAX_SECONDS) in {None, 0}:
        raise ValueError("invalid_stale_after_seconds")
    result = _blank(clock, "accounting_missing")
    try:
        events, damaged, report = _snapshot(accounting_dir)
        result["quality"]["damagedRowCount"] = len(damaged)
        if ledger is not None and not verify_ledger_run_binding(ledger, events, run_id):
            raise ValueError("ledger_run_binding_mismatch")
        selected = [event for event in events if event["runId"] == run_id and
                    event.get("schemaVersion") in accounting.READABLE_SCHEMAS]
        run = next((r for r in report["runs"] if r["runSha256"] == weekly.digest(run_id)), None)
        if "conflicting_event_identity" in report["diagnostics"]:
            # The legacy report retains a diagnostic representative; it is not
            # a public choice of which contradictory timing fact to believe.
            result = _blank(clock, "conflicting_event_identity")
        elif not run or not selected:
            result["quality"]["reasonCodes"] = ["run_not_found"]
        else:
            _observed(result, run, selected, report, clock, stale_after_seconds, all_events=events)
            profile_count = sum("contractVersion" in event for event in selected)
            result["logs"] = {"schemaVersions": sorted({e["schemaVersion"] for e in selected}),
                "contractVersions": ["sermon-accounting-log-contract-v1"] if profile_count else [],
                "eventCount": len({e["eventId"] for e in selected}),
                "profileEventCount": len({e["eventId"] for e in selected if "contractVersion" in e}),
                "legacyEventCount": len({e["eventId"] for e in selected if "contractVersion" not in e}),
                "damagedRowCount": len(damaged)}
    except FileNotFoundError:
        if ledger is not None:
            raise ValueError("ledger_run_binding_mismatch") from None
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        if ledger is not None:
            raise ValueError("ledger_run_binding_mismatch") from None
        result = _blank(clock, "accounting_too_large" if str(exc) == "accounting_too_large" else "accounting_invalid")
    if progress_inputs is not None:
        try:
            _planned(result, progress_inputs, run_id, clock)
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            code = str(exc) if str(exc) in {"progress_run_mismatch", "node_limit"} else "progress_inputs_invalid"
            result["eta"] = _unknown_eta(code)
            result["quality"]["reasonCodes"] = _reasons([*result["quality"]["reasonCodes"], code])
            if result["quality"]["status"] != "unavailable":
                result["quality"]["status"] = "partial"
    if len(json.dumps(result, allow_nan=False).encode()) > MAX_OUTPUT_BYTES:
        return _blank(clock, "node_limit")
    return result


def _read_json(path, *, lines=False):
    with path.open("rb") as stream:
        data = stream.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("input_too_large")
    raw = data.decode("utf-8")
    return ([json.loads(line) for line in raw.splitlines() if line.strip()]
            if lines and not raw.lstrip().startswith("[") else json.loads(raw))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accounting-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--ledger", type=Path, help="Require exact tracker ledger/workflow binding")
    parser.add_argument("--at")
    parser.add_argument("--stale-after-seconds", type=float, default=300)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--receipts", type=Path)
    parser.add_argument("--samples", type=Path)
    parser.add_argument("--resource-state", type=Path)
    parser.add_argument("--reconciliations", type=Path)
    parser.add_argument("--previous-progress", type=Path)
    parser.add_argument("--output", type=Path, help="Separate local projection; default stdout. Never publishes.")
    args = parser.parse_args(argv)
    paths = [args.plan, args.receipts, args.samples, args.resource_state, args.reconciliations, args.previous_progress]
    try:
        if any(paths) and not (args.plan and args.receipts):
            raise ValueError("plan_and_receipts_required")
        if args.output and (args.output.is_symlink() or any(path and path.resolve() == args.output.resolve()
                for path in [args.accounting_dir / "events.jsonl", args.ledger, *paths])):
            raise ValueError("output_must_not_replace_input")
        inputs = None
        if args.plan:
            inputs = {"plan": _read_json(args.plan), "receipts": _read_json(args.receipts, lines=True)}
            for name, path in (("samples", args.samples), ("resource_state", args.resource_state),
                               ("reconciliations", args.reconciliations), ("previous", args.previous_progress)):
                if path:
                    inputs[name] = _read_json(path)
        result = build_projection(args.accounting_dir, run_id=args.run_id, at=args.at,
                                  progress_inputs=inputs, stale_after_seconds=args.stale_after_seconds,
                                  ledger=_read_json(args.ledger) if args.ledger else None)
        data = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent, delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    stream.write(data); stream.flush(); os.fsync(stream.fileno())
                    os.replace(temporary, args.output)
                finally:
                    temporary.unlink(missing_ok=True)
        else:
            print(data, end="")
        return 0
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        print("tracker_dag_projection_failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
