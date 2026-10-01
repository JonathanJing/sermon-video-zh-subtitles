#!/usr/bin/env python3
"""Offline work/ETA projection. No dispatch, gate authority, or ledger writes.

Status inputs are full, validator-produced snapshots, never inferred task states.
UTC is descriptive; liveness/active elapsed come from the trusted local monitor.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

PLAN_SCHEMA = "sermon-run-progress-plan-v1"
RECEIPT_SCHEMA = "sermon-run-progress-status-v1"
RECONCILIATION_SCHEMA = "sermon-run-progress-reconciliation-v1"
SCHEMA = "sermon-run-progress-v1"
ESTIMATOR_VERSION = "remaining-dag-resource-slots-v1"
DIMENSIONS = ("stage", "model", "locale", "lengthBucket", "cacheClass", "resourceClass")
COUNTS = ("processed", "executionSucceeded", "contentReviewPassed",
          "realHumanApproved", "simulatedHumanApproved", "admitted")
EXECUTION = {"pending", "running", "succeeded", "failed", "cancelled", "outcome_unknown"}
PHASES = {"pending", "running", "retrying", "waiting_review", "blocked", "complete", "unknown_outcome"}
RECEIPT_FIELDS = {"schemaVersion", "planId", "planVersion", "planSha256", "runId", "unitId",
                  "identitySha256", "eventId", "attemptId", "sequence", "observedAt", "executionStatus",
                  "reviewVerdict", "humanReviewKind", "humanApprovalStatus", "admissionStatus", "phase",
                  "evidenceValidated", "artifactSha256", "reviewedArtifactSha256", "humanReviewedArtifactSha256",
                  "evidenceRefs", "reasonCode", "heartbeatStatus", "heartbeatAgeSeconds", "heartbeatTimeoutSeconds",
                  "activeElapsedSeconds", "measurementValidated", "elapsedSeconds", "queueRemainingSeconds",
                  "timingSampleId", "workKind", "reconcilesAttemptIds"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _label(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:@+-]{1,160}", value):
        raise ValueError("invalid_label")
    return value


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid_sha256")
    return value


def _number(value, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 2**53 or (positive and value == 0):
        raise ValueError("invalid_nonnegative_number")
    return value


def _time(value):
    if not isinstance(value, str):
        raise ValueError("invalid_timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone_required")
    return result.astimezone(timezone.utc)


def _order(units):
    pending, result = set(units), []
    while pending:
        ready = sorted(k for k in pending if not set(units[k]["dependsOn"]) & pending)
        if not ready:
            raise ValueError("dependency_cycle")
        result.extend(ready)
        pending.difference_update(ready)
    return result


def freeze_plan(plan_id, version, run_id, units, resources, *, dag_version,
                weight_policy_version="explicit-unit-weights-v1", supersedes=None, migration_reason=None):
    """Freeze identities, DAG, positive weights and resource capacities, not state.

    A unit's identitySha256 binds its source/input/policy/revision. Output artifact
    hashes are supplied by validated receipts after execution, not guessed here.
    """
    if type(version) is not int or version < 1 or not units or not resources:
        raise ValueError("invalid_plan")
    pools = {}
    for name, row in resources.items():
        if set(row) != {"capacity", "resourceClass"} or type(row["capacity"]) is not int or not 1 <= row["capacity"] <= 256:
            raise ValueError("invalid_resource_capacity")
        pools[_label(name)] = {"capacity": row["capacity"], "resourceClass": _label(row["resourceClass"])}
    normalized = []
    for supplied in units:
        row = json.loads(json.dumps(supplied, allow_nan=False))
        allowed = {"id", "identitySha256", "dependsOn", "weight", "resources", "requiredEvidence", "priorSeconds"} | set(DIMENSIONS)
        if set(row) - allowed:
            raise ValueError("unknown_unit_field")
        for field in ("id", *DIMENSIONS):
            _label(row[field])
        _hash(row["identitySha256"])
        _number(row["weight"], positive=True)
        for field in ("dependsOn", "resources", "requiredEvidence"):
            if not isinstance(row[field], list) or len(set(row[field])) != len(row[field]):
                raise ValueError("invalid_unit_list")
            row[field] = sorted(row[field])
        if not row["resources"] or set(row["resources"]) - pools.keys():
            raise ValueError("unknown_resource")
        if (not row["requiredEvidence"] or set(row["requiredEvidence"]) - set(COUNTS[1:])
                or "executionSucceeded" not in row["requiredEvidence"]):
            raise ValueError("execution_evidence_required")
        if "priorSeconds" in row:
            prior = row["priorSeconds"]
            if set(prior) != {"lower", "upper", "sourceRef"} or _number(prior["lower"]) > _number(prior["upper"], positive=True):
                raise ValueError("invalid_prior")
            _label(prior["sourceRef"])
        normalized.append(row)
    normalized.sort(key=lambda row: row["id"])
    indexed = {row["id"]: row for row in normalized}
    if len(indexed) != len(normalized) or any(set(row["dependsOn"]) - indexed.keys() for row in normalized):
        raise ValueError("duplicate_or_unknown_unit")
    _order(indexed)
    if bool(supersedes) != bool(migration_reason):
        raise ValueError("explicit_migration_required")
    plan = {"schemaVersion": PLAN_SCHEMA, "planId": _label(plan_id), "planVersion": version,
            "runId": _label(run_id), "dagVersion": _label(dag_version),
            "weightPolicyVersion": _label(weight_policy_version), "units": normalized, "resources": pools,
            "denominator": str(sum((Decimal(str(row["weight"])) for row in normalized), Decimal(0))),
            "supersedesPlanSha256": _hash(supersedes) if supersedes else None,
            "migrationReason": _label(migration_reason) if migration_reason else None}
    return {**plan, "planSha256": digest(plan)}


def validate_plan(plan):
    expected = freeze_plan(plan["planId"], plan["planVersion"], plan["runId"], plan["units"], plan["resources"],
                           dag_version=plan["dagVersion"], weight_policy_version=plan["weightPolicyVersion"],
                           supersedes=plan["supersedesPlanSha256"], migration_reason=plan["migrationReason"])
    if plan != expected:
        raise ValueError("plan_hash_or_denominator_drift")
    return plan


def _transition(plan, previous):
    if previous is None:
        return None
    if previous.get("schemaVersion") != SCHEMA or previous.get("runId") != plan["runId"] or previous.get("planId") != plan["planId"]:
        raise ValueError("different_projection_identity")
    if previous["planSha256"] == plan["planSha256"]:
        return None
    if (plan["planVersion"] <= previous["planVersion"] or
            plan["supersedesPlanSha256"] != previous["planSha256"] or not plan["migrationReason"]):
        raise ValueError("explicit_versioned_plan_migration_required")
    return {"previousPlanSha256": previous["planSha256"], "previousPlanVersion": previous["planVersion"],
            "previousDenominator": previous["denominator"], "reason": plan["migrationReason"]}


def status_receipt(plan, unit_id, *, event_id, attempt_id, sequence, observed_at, **status):
    """Wrap a FULL local validator snapshot; this helper validates no artifacts."""
    unit = next(row for row in plan["units"] if row["id"] == unit_id)
    result = {"schemaVersion": RECEIPT_SCHEMA, **{k: plan[k] for k in ("planId", "planVersion", "planSha256", "runId")},
              "unitId": unit_id, "identitySha256": unit["identitySha256"], "eventId": event_id,
              "attemptId": attempt_id, "sequence": sequence, "observedAt": observed_at,
              "executionStatus": "pending", "reviewVerdict": "not_assessed", "humanReviewKind": "none",
              "humanApprovalStatus": "pending", "admissionStatus": "not_assessed", "phase": "pending",
              "evidenceValidated": False, "artifactSha256": None, "reviewedArtifactSha256": None,
              "humanReviewedArtifactSha256": None, "evidenceRefs": [], "reasonCode": None,
              "heartbeatStatus": "unknown", "heartbeatAgeSeconds": None, "heartbeatTimeoutSeconds": None,
              "activeElapsedSeconds": None, "measurementValidated": False,
              "elapsedSeconds": None, "timingSampleId": None, "queueRemainingSeconds": 0, "workKind": "planned",
              "reconcilesAttemptIds": [], **status}
    _validate_receipt(result, plan, unit)
    return result


def _validate_receipt(row, plan, unit):
    if set(row) != RECEIPT_FIELDS:
        raise ValueError("status_snapshot_requires_closed_full_schema")
    if row["schemaVersion"] != RECEIPT_SCHEMA or any(row[k] != plan[k] for k in ("planId", "planVersion", "planSha256", "runId")):
        raise ValueError("receipt_plan_binding_mismatch")
    if row["unitId"] != unit["id"] or row["identitySha256"] != unit["identitySha256"]:
        raise ValueError("receipt_unit_binding_mismatch")
    for key in ("eventId", "attemptId"):
        _label(row[key])
    if type(row["sequence"]) is not int or row["sequence"] < 1:
        raise ValueError("invalid_status_sequence")
    _time(row["observedAt"])
    choices = {"executionStatus": EXECUTION, "phase": PHASES,
               "reviewVerdict": {"pass", "needs_rework", "inconclusive", "not_assessed"},
               "humanReviewKind": {"none", "real", "simulated"}, "humanApprovalStatus": {"pending", "approved", "rejected"},
               "admissionStatus": {"admitted", "blocked", "waiting_human", "rejected", "not_assessed"},
               "heartbeatStatus": {"fresh", "stale", "unknown", "not_applicable"}, "workKind": {"planned", "rework"}}
    for key, values in choices.items():
        if row[key] not in values:
            raise ValueError("invalid_" + key)
    if type(row["evidenceValidated"]) is not bool or type(row["measurementValidated"]) is not bool:
        raise ValueError("invalid_validation_flag")
    for field in ("heartbeatAgeSeconds", "heartbeatTimeoutSeconds", "activeElapsedSeconds", "elapsedSeconds", "queueRemainingSeconds"):
        if row[field] is not None:
            _number(row[field])
    for field in ("artifactSha256", "reviewedArtifactSha256", "humanReviewedArtifactSha256"):
        if row[field] is not None:
            _hash(row[field])
    for field in ("evidenceRefs", "reconcilesAttemptIds"):
        if not isinstance(row[field], list) or len(set(row[field])) != len(row[field]):
            raise ValueError("invalid_receipt_refs")
        for ref in row[field]:
            _label(ref)
    if row["reasonCode"] is not None:
        _label(row["reasonCode"])
    if row["measurementValidated"]:
        _label(row["timingSampleId"])
        if row["elapsedSeconds"] is None:
            raise ValueError("validated_measurement_duration_required")
    if row["heartbeatStatus"] == "fresh" and (row["heartbeatAgeSeconds"] is None
            or row["heartbeatTimeoutSeconds"] is None or row["heartbeatTimeoutSeconds"] <= 0):
        raise ValueError("heartbeat_monitor_evidence_required")
    if row["reviewVerdict"] != "not_assessed" and row["executionStatus"] != "succeeded":
        raise ValueError("review_execution_conflict")
    if row["evidenceValidated"] and (not row["evidenceRefs"] or not row["artifactSha256"]):
        raise ValueError("validated_artifact_refs_required")
    if row["reviewVerdict"] == "pass" and row["reviewedArtifactSha256"] != row["artifactSha256"]:
        raise ValueError("review_artifact_mismatch")
    if row["humanApprovalStatus"] == "approved" and (row["humanReviewKind"] == "none" or
            not row["artifactSha256"] or row["humanReviewedArtifactSha256"] != row["artifactSha256"]):
        raise ValueError("human_artifact_mismatch")


def _facts(row):
    if row is None:
        return dict.fromkeys(COUNTS, False)
    success = row["executionStatus"] == "succeeded" and row["evidenceValidated"]
    human = success and row["humanApprovalStatus"] == "approved"
    return {"processed": row["executionStatus"] in {"succeeded", "failed", "cancelled"},
            "executionSucceeded": success, "contentReviewPassed": success and row["reviewVerdict"] == "pass",
            "realHumanApproved": human and row["humanReviewKind"] == "real",
            "simulatedHumanApproved": human and row["humanReviewKind"] == "simulated",
            "admitted": success and row["admissionStatus"] == "admitted"}


def reconciliation_proof(plan, unit_id, attempt_id, *, proof_id, unknown_event_id,
                         evidence_sha256, evidence_refs, outcome, evidence_validated=False):
    """Independent local validator output after reading durable reconciliation.

    The caller must validate the original durable receipt/result and its exact
    attempt binding. Status assertions or new-attempt success are not proof.
    """
    unit = next(row for row in plan["units"] if row["id"] == unit_id)
    value = {"schemaVersion": RECONCILIATION_SCHEMA,
             **{k: plan[k] for k in ("planSha256", "runId")}, "unitId": unit_id,
             "identitySha256": unit["identitySha256"], "attemptId": attempt_id,
             "proofId": proof_id, "unknownEventId": unknown_event_id,
             "evidenceSha256": evidence_sha256, "evidenceRefs": evidence_refs,
             "outcome": outcome, "evidenceValidated": evidence_validated}
    return {**value, "proofSha256": digest(value)}


def _verified_reconciliations(plan, proofs, histories):
    verified, candidates, issues = defaultdict(dict), defaultdict(dict), []
    expected = {"schemaVersion", "planSha256", "runId", "unitId", "identitySha256", "attemptId",
                "proofId", "unknownEventId", "evidenceSha256", "evidenceRefs", "outcome", "evidenceValidated", "proofSha256"}
    units = {row["id"]: row for row in plan["units"]}
    for proof in proofs:
        try:
            if set(proof) != expected or proof["schemaVersion"] != RECONCILIATION_SCHEMA:
                raise ValueError("invalid_reconciliation_schema")
            value = {k: v for k, v in proof.items() if k != "proofSha256"}
            if digest(value) != proof["proofSha256"]:
                raise ValueError("reconciliation_hash_mismatch")
            unit = units[proof["unitId"]]
            if (proof["planSha256"] != plan["planSha256"] or proof["runId"] != plan["runId"]
                    or proof["identitySha256"] != unit["identitySha256"]):
                raise ValueError("reconciliation_binding_mismatch")
            if proof["evidenceValidated"] is not True or not proof["evidenceRefs"]:
                raise ValueError("reconciliation_evidence_unverified")
            _hash(proof["evidenceSha256"])
            for key in ("proofId", "attemptId", "unknownEventId"):
                _label(proof[key])
            if not isinstance(proof["evidenceRefs"], list):
                raise ValueError("invalid_reconciliation_refs")
            for ref in proof["evidenceRefs"]:
                _label(ref)
            if proof["outcome"] not in {"succeeded", "failed", "cancelled", "not_executed"}:
                raise ValueError("unknown_reconciliation_outcome")
            attempts = [row for row in histories[unit["id"]] if row["attemptId"] == proof["attemptId"]]
            if not attempts:
                raise ValueError("reconciliation_attempt_not_observed")
            old = max(attempts, key=lambda row: row["sequence"])
            if old["eventId"] != proof["unknownEventId"] or old["executionStatus"] not in {"outcome_unknown", "running"}:
                raise ValueError("reconciliation_old_attempt_binding_mismatch")
            candidates[(unit["id"], proof["attemptId"])][proof["proofSha256"]] = proof
        except (KeyError, TypeError, ValueError):
            issues.append("invalid_or_unverified_reconciliation_evidence")
    for (unit_id, attempt_id), values in candidates.items():
        if len(values) == 1:
            verified[unit_id][attempt_id] = next(iter(values.values()))["outcome"]
        else:
            issues.append("conflicting_reconciliation_evidence")
    return verified, sorted(set(issues))


def _dimension(row):
    return tuple(row[k] for k in DIMENSIONS)


def _completed_work_unit_id(run_id, unit_id, attempt_id):
    return f"{run_id}:{unit_id}:{attempt_id}"


def _estimates(run_id, units, states, samples, at):
    groups, seen_samples, work_units, issues = defaultdict(list), {}, defaultdict(list), []
    current = []
    for unit_id, row in states.items():
        if row and row["executionStatus"] == "succeeded" and row["measurementValidated"] and row["elapsedSeconds"] is not None and row["elapsedSeconds"] > 0:
            current.append({**{k: units[unit_id][k] for k in DIMENSIONS}, "sampleId": row["timingSampleId"],
                            "workUnitId": _completed_work_unit_id(run_id, unit_id, row["attemptId"]),
                            "elapsedSeconds": row["elapsedSeconds"], "observedAt": row["observedAt"],
                            "executionStatus": "succeeded", "measurementKind": "empirical", "sourceRef": row["timingSampleId"]})
    for row in [*samples, *current]:
        try:
            sample_id = _label(row["sampleId"]); _label(row["sourceRef"])
            work_unit_id = _label(row["workUnitId"])
            if (row["measurementKind"] != "empirical" or row["executionStatus"] != "succeeded"
                    or _time(row["observedAt"]) > at):
                raise ValueError("untrusted_sample")
            for key in DIMENSIONS:
                _label(row[key])
            duration = _number(row["elapsedSeconds"], positive=True)
            signature = (_dimension(row), duration, row["observedAt"], row["measurementKind"], row["executionStatus"])
            if sample_id in seen_samples:
                if seen_samples[sample_id] != (work_unit_id, signature):
                    raise ValueError("conflicting_sample")
                continue
            seen_samples[sample_id] = (work_unit_id, signature)
            work_units[work_unit_id].append((signature, duration))
        except (KeyError, TypeError, ValueError):
            issues.append("invalid_or_conflicting_empirical_sample")
    for observations in work_units.values():
        signatures = {signature for signature, _ in observations}
        if len(signatures) != 1:
            issues.append("invalid_or_conflicting_empirical_sample")
            continue
        signature, duration = observations[0]
        groups[signature[0]].append(duration)
    result = {}
    for key, unit in units.items():
        values = groups[_dimension(unit)]
        if values:
            n = len(values)
            result[key] = {"lower": min(values) * (0.5 if n < 5 else 0.8),
                           "upper": max(values) * (2 if n < 5 else 1.5), "sampleCount": n,
                           "confidence": "low" if n < 5 else "medium", "basis": "empirical_envelope"}
        elif unit.get("priorSeconds"):
            result[key] = {**{k: unit["priorSeconds"][k] for k in ("lower", "upper")},
                           "sampleCount": 0, "confidence": "low", "basis": "explicit_cold_start_prior",
                           "sourceRef": unit["priorSeconds"]["sourceRef"]}
        else:
            result[key] = {"lower": None, "upper": None, "sampleCount": 0, "confidence": "unknown", "basis": "no_comparable_history"}
    comparable = {_dimension(row) for row in units.values()}
    return result, sum(_dimension(row) in comparable for row in seen.values()), issues


def _schedule(units, done, states, estimates, pools, endpoint):
    """Deterministic list scheduling, reserving all needed slots together."""
    slots = {key: list(row["queueSeconds"]) for key, row in pools.items()}
    finishes = {key: 0 for key in done}
    pending = set(units) - done
    schedule = []
    while pending:
        ready = [key for key in pending if set(units[key]["dependsOn"]) <= finishes.keys()]
        candidates = []
        for key in ready:
            unit, state = units[key], states[key]
            selection = {pool: min(range(len(slots[pool])), key=lambda i: (slots[pool][i], i)) for pool in unit["resources"]}
            running = state and state["executionStatus"] == "running"
            start = max([finishes[d] for d in unit["dependsOn"]] +
                        [slots[pool][i] for pool, i in selection.items()] +
                        [0 if running else (state or {}).get("queueRemainingSeconds", 0)])
            candidates.append((0 if running else 1, start, key, selection))
        _, start, key, selection = min(candidates)
        state = states[key] or {}
        elapsed = (state.get("activeElapsedSeconds") or 0) if state.get("executionStatus") == "running" else 0
        duration = max(0, estimates[key][endpoint] - elapsed)
        finish = start + duration
        for pool, i in selection.items():
            slots[pool][i] = finish
        finishes[key] = finish
        pending.remove(key)
        schedule.append({"unitId": key, "startSeconds": start, "finishSeconds": finish})
    return max(finishes.values(), default=0), schedule


def project_progress(plan, receipts, *, samples=(), at=None, previous=None, resource_state=None,
                     input_issues=(), reconciliations=()):
    """Pure projection of frozen business units; framework task count is unused."""
    validate_plan(plan)
    clock = _time(at) if isinstance(at, str) else (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    transition = _transition(plan, previous)
    units = {row["id"]: row for row in plan["units"]}
    by_unit, events, diagnostics = defaultdict(list), {}, [_label(code) for code in input_issues]
    tainted_units = set()
    for supplied in receipts:
        try:
            row = json.loads(json.dumps(supplied, allow_nan=False))
            _validate_receipt(row, plan, units[row["unitId"]])
            if _time(row["observedAt"]) > clock:
                raise ValueError("future_receipt")
            if row["eventId"] in events:
                if events[row["eventId"]] != row:
                    tainted_units.add(events[row["eventId"]]["unitId"])
                    raise ValueError("event_id_conflict")
                continue
            events[row["eventId"]] = row
            by_unit[row["unitId"]].append(row)
        except (KeyError, TypeError, ValueError):
            diagnostics.append("invalid_conflicting_or_unbound_receipt")
            if isinstance(supplied, dict) and isinstance(supplied.get("unitId"), str) and supplied["unitId"] in units:
                tainted_units.add(supplied["unitId"])
    verified_reconciliations, reconciliation_issues = _verified_reconciliations(plan, reconciliations, by_unit)
    states, facts, completed, rows = {}, {}, set(), []
    retry_count, rework_count, unresolved = 0, 0, []
    for key in _order(units):
        history = by_unit[key]
        sequences = defaultdict(list)
        for row in history:
            sequences[row["sequence"]].append(row)
        conflict = key in tainted_units or any(len(values) > 1 for values in sequences.values())
        state = max(history, key=lambda row: row["sequence"]) if history and not conflict else None
        if conflict:
            diagnostics.append("conflicting_unit_sequence")
        states[key] = state
        heartbeat_status = (state or {}).get("heartbeatStatus", "unknown")
        heartbeat_age = (state or {}).get("heartbeatAgeSeconds")
        if state and heartbeat_age is not None:
            # Aging an observation may only refuse an ETA; never renew a lease.
            heartbeat_age += max(0, (clock - _time(state["observedAt"])).total_seconds())
            if heartbeat_status == "fresh" and heartbeat_age >= state["heartbeatTimeoutSeconds"]:
                heartbeat_status = "stale"
        latest_attempts = {}
        for row in sorted(history, key=lambda row: row["sequence"]):
            latest_attempts[row["attemptId"]] = row
        retries = max(0, len(latest_attempts) - 1)
        rework = sum(row["workKind"] == "rework" for row in latest_attempts.values())
        retry_count += retries; rework_count += rework
        claimed = set((state or {}).get("reconcilesAttemptIds", []))
        reconciled = claimed & verified_reconciliations[key].keys()
        unknown = [attempt for attempt, row in latest_attempts.items()
                   if row["executionStatus"] == "outcome_unknown" and attempt not in reconciled]
        unknown += [attempt for attempt, row in latest_attempts.items()
                    if row["executionStatus"] == "running" and (not state or attempt != state["attemptId"])
                    and attempt not in reconciled]
        value = _facts(state)
        # A retry can invalidate current gates, but cannot erase a trustworthy
        # terminal execution that already processed this same frozen unit.
        value["processed"] = not conflict and (any(_facts(row)["processed"] for row in history) or
            any(verified_reconciliations[key][attempt] in {"succeeded", "failed", "cancelled"} for attempt in reconciled))
        processed_known = value["processed"] or bool(state and state["executionStatus"] in {"pending", "running"} and not unknown)
        facts[key] = value
        gates = [gate for gate in units[key]["requiredEvidence"] if not value[gate]]
        reason = (state or {}).get("reasonCode")
        if unknown:
            reason = "attempt_outcome_requires_reconciliation"
        elif conflict:
            reason = "conflicting_unit_sequence"
        elif not set(units[key]["dependsOn"]) <= completed:
            reason = reason or "dependency_unresolved"
        elif state and heartbeat_status == "stale" and state["executionStatus"] == "running":
            reason = "heartbeat_stale"
        if not gates and not reason and state and state["phase"] == "complete":
            completed.add(key)
        else:
            unresolved.append({"unitId": key, "reasonCode": reason or "required_evidence_missing", "missingEvidence": gates})
        rows.append({"unitId": key, **{k: units[key][k] for k in ("stage", "locale", "weight")}, **value,
                     "complete": key in completed, "phase": (state or {}).get("phase", "pending"),
                     "processedKnown": processed_known, "unknownOutcome": bool(unknown),
                     "retryCount": retries, "reworkAttempts": rework, "blockedReason": reason,
                     "heartbeatStatus": heartbeat_status, "heartbeatAgeSeconds": heartbeat_age,
                     "attemptId": (state or {}).get("attemptId")})
    estimates, sample_count, sample_issues = _estimates(plan["runId"], units, states, samples, clock)
    diagnostics.extend(sample_issues)
    denominator = Decimal(plan["denominator"])
    done_weight = sum((Decimal(str(units[k]["weight"])) for k in completed), Decimal(0))
    processed_weight = sum((Decimal(str(row["weight"])) for row in rows if row["processed"]), Decimal(0))
    unknown_weight = sum((Decimal(str(row["weight"])) for row in rows if not row["processedKnown"]), Decimal(0))
    known_weight = denominator - unknown_weight
    known_processed_percent = round(float(processed_weight * 100 / denominator), 6)
    if processed_weight < denominator:
        known_processed_percent = min(99.999999, known_processed_percent)
    processing_known = not unknown_weight and not diagnostics
    complete = len(completed) == len(units) and not diagnostics
    percent = float(done_weight * 100 / denominator)
    percent = round(percent, 6) if complete else min(99.999999, round(percent, 6))
    eta_reasons = set(diagnostics)
    pools = resource_state or {}
    if set(pools) != set(plan["resources"]):
        eta_reasons.add("resource_state_missing")
    else:
        for key, spec in plan["resources"].items():
            try:
                pool = pools[key]
                if pool["capacity"] != spec["capacity"] or pool["resourceClass"] != spec["resourceClass"]:
                    raise ValueError("resource_configuration_changed")
                age = (clock - _time(pool["observedAt"])).total_seconds()
                if pool["status"] != "ready" or age < 0 or age >= _number(pool["maxAgeSeconds"], positive=True):
                    raise ValueError("resource_outage_or_unknown")
                if len(pool["queueSeconds"]) != spec["capacity"]:
                    raise ValueError("queue_capacity_mismatch")
                for value in pool["queueSeconds"]:
                    _number(value)
            except (KeyError, TypeError, ValueError):
                eta_reasons.add("resource_queue_or_configuration_unknown")
    for key in set(units) - completed:
        state = states[key] or {}
        if estimates[key]["upper"] is None:
            eta_reasons.add("no_comparable_history")
        if any(key == row["unitId"] and row["reasonCode"] == "attempt_outcome_requires_reconciliation" for row in unresolved):
            eta_reasons.add("unknown_attempt_outcome")
        if state.get("phase") in {"blocked", "unknown_outcome", "waiting_review"}:
            eta_reasons.add(state["phase"])
        if state.get("reasonCode"):
            eta_reasons.add("observed_blocker")
        if state.get("queueRemainingSeconds", 0) is None:
            eta_reasons.add("unit_queue_unknown")
        if state.get("executionStatus") in {"failed", "cancelled", "outcome_unknown"}:
            eta_reasons.add("retry_or_reconciliation_not_authorized")
        if set(units[key]["requiredEvidence"]) & {"realHumanApproved", "simulatedHumanApproved"}:
            if not facts[key]["realHumanApproved"] and not facts[key]["simulatedHumanApproved"]:
                eta_reasons.add("human_review_remaining")
        if state.get("executionStatus") == "succeeded":
            eta_reasons.add("unresolved_post_execution_gate")
        if state.get("executionStatus") == "running":
            if not set(units[key]["dependsOn"]) <= completed:
                eta_reasons.add("running_dependency_unresolved")
            elapsed = state.get("activeElapsedSeconds")
            row = next(row for row in rows if row["unitId"] == key)
            if row["heartbeatStatus"] != "fresh" or elapsed is None:
                eta_reasons.add("heartbeat_or_active_elapsed_unknown")
            elif estimates[key]["upper"] is not None and elapsed >= estimates[key]["upper"]:
                eta_reasons.add("active_duration_exceeds_empirical_envelope")
    if not eta_reasons:
        for pool in pools:
            running = [k for k, state in states.items() if state and state["executionStatus"] == "running" and pool in units[k]["resources"]]
            if len(running) > sum(value == 0 for value in pools[pool]["queueSeconds"]):
                eta_reasons.add("running_units_contradict_available_resource_slots")
    eta = {"status": "unknown", "lowerSeconds": None, "upperSeconds": None, "earliestAt": None,
           "latestAt": None, "remainingSerialSeconds": None, "criticalPathSeconds": None,
           "sampleCount": sample_count, "confidence": "unknown", "reasonCodes": sorted(eta_reasons),
           "estimatorVersion": ESTIMATOR_VERSION, "updatedAt": clock.isoformat(), "perUnit": estimates,
           "assumptions": ["Comparable stage/model/locale/length/cache/resource-class samples only.",
                           "Envelope is a conservative scenario range, not a calibrated probability interval.",
                           "Non-preemptive deterministic list order; no new retries, future rework or unrecorded queue arrivals.",
                           "UTC is descriptive; active elapsed and heartbeat are supplied by the local monotonic monitor."]}
    if complete:
        eta.update(status="complete", lowerSeconds=0, upperSeconds=0, earliestAt=clock.isoformat(), latestAt=clock.isoformat(), reasonCodes=[])
    elif not eta_reasons:
        lower, _ = _schedule(units, completed, states, estimates, pools, "lower")
        upper, schedule = _schedule(units, completed, states, estimates, pools, "upper")
        remaining = set(units) - completed
        def active_elapsed(key):
            state = states[key] or {}
            return (state.get("activeElapsedSeconds") or 0) if state.get("executionStatus") == "running" else 0
        serial = sum(max(0, estimates[k]["upper"] - active_elapsed(k)) for k in remaining)
        path = {}
        for key in _order(units):
            duration = 0 if key in completed else max(0, estimates[key]["upper"] - active_elapsed(key))
            path[key] = max((path[d] for d in units[key]["dependsOn"]), default=0) + duration
        eta.update(status="estimated", lowerSeconds=round(min(lower, upper), 6), upperSeconds=round(max(lower, upper), 6),
                   earliestAt=(clock + timedelta(seconds=min(lower, upper))).isoformat(),
                   latestAt=(clock + timedelta(seconds=max(lower, upper))).isoformat(),
                   remainingSerialSeconds=round(serial, 6), criticalPathSeconds=round(max(path.values()), 6),
                   confidence="low" if any(estimates[k]["confidence"] == "low" for k in remaining) else "medium",
                   scheduleUpper=schedule)
    groups = []
    for stage, locale in sorted({(row["stage"], row["locale"]) for row in rows}):
        selected = [row for row in rows if row["stage"] == stage and row["locale"] == locale]
        groups.append({"stage": stage, "locale": locale, "done": sum(row["complete"] for row in selected),
                       "total": len(selected), **{k: sum(row[k] for row in selected) for k in COUNTS},
                       "applicableTotals": {k: sum(k in units[row["unitId"]]["requiredEvidence"] for row in selected) for k in COUNTS[1:]}})
    evidence_progress = {}
    for kind in COUNTS[1:]:
        applicable = [row for row in rows if kind in units[row["unitId"]]["requiredEvidence"]]
        weight = sum((Decimal(str(row["weight"])) for row in applicable), Decimal(0))
        passed = sum((Decimal(str(row["weight"])) for row in applicable if row[kind]), Decimal(0))
        unknown_evidence = []
        for row in applicable:
            state = states[row["unitId"]]
            unknown_fact = state is None or row["unknownOutcome"]
            if state and not row[kind]:
                if kind == "contentReviewPassed":
                    unknown_fact |= state["reviewVerdict"] in {"not_assessed", "inconclusive"}
                elif kind in {"realHumanApproved", "simulatedHumanApproved"}:
                    unknown_fact |= state["humanApprovalStatus"] == "pending"
                elif kind == "admitted":
                    unknown_fact |= state["admissionStatus"] == "not_assessed"
                elif kind == "executionSucceeded":
                    unknown_fact |= state["executionStatus"] == "succeeded" and not state["evidenceValidated"]
            if unknown_fact:
                unknown_evidence.append(row["unitId"])
        evidence_progress[kind] = {"status": "not_applicable" if not applicable else "unknown" if unknown_evidence else "known",
                                   "done": sum(row[kind] for row in applicable), "total": len(applicable),
                                   "denominator": str(weight), "knownPassedWeight": str(passed), "unknownUnits": unknown_evidence,
                                   "percent": None if not weight or unknown_evidence else round(float(passed * 100 / weight), 6)}
    return {"schemaVersion": SCHEMA, **{k: plan[k] for k in ("planId", "planVersion", "planSha256", "runId", "dagVersion", "weightPolicyVersion", "denominator", "supersedesPlanSha256", "migrationReason")},
            "updatedAt": clock.isoformat(), "planTransition": transition,
            "plannedProcessedPercent": known_processed_percent if processing_known else None,
            "knownProcessedPercentLowerBound": known_processed_percent, "knownProcessedWeight": str(processed_weight),
            "processingCoverage": {"status": "known" if processing_known else "partial", "knownWeight": str(known_weight),
                                   "unknownWeight": str(unknown_weight), "unknownUnits": [row["unitId"] for row in rows if not row["processedKnown"]],
                                   "unattributedEvidence": bool(diagnostics)},
            "gateCompletionPercent": percent, "plannedCompletionPercent": percent,
            "completedWeight": str(done_weight), "complete": complete,
            "currentPhases": sorted({row["stage"] for row in rows if not row["complete"] and
                                     (row["phase"] != "pending" or set(units[row["unitId"]]["dependsOn"]) <= completed)}),
            "counts": {"done": len(completed), "total": len(units), **{k: sum(row[k] for row in rows) for k in COUNTS}},
            "phaseLocales": groups, "units": rows, "unresolvedGates": unresolved,
            "evidenceProgress": evidence_progress,
            "extraWork": {"retryAttempts": retry_count, "reworkAttempts": rework_count, "includedInDenominator": False},
            "reconciliationEvidence": {"verifiedAttempts": sum(len(v) for v in verified_reconciliations.values()),
                                       "reasonCodes": reconciliation_issues},
            "integrity": {"status": "partial" if diagnostics else "consistent", "reasonCodes": sorted(set(diagnostics)), "acceptedReceipts": len(events)},
            "cost": {"status": "not_projected", "knownSubtotalUsd": None, "source": "existing_accounting_projection"},
            "resourceConfiguration": plan["resources"],
            "eta": eta, "executionAuthority": "none"}


def plan_from_tracker(ledger, plan_id, version, run_id, unit_specs, resources, **kwargs):
    """Reuse existing formal checkpoint dependencies; never import completion."""
    from scripts import four_layer_progress
    from scripts.build_four_layer_timeline import dependencies
    if ledger.get("schemaVersion") != four_layer_progress.SCHEMA or not isinstance(ledger.get("steps"), dict):
        raise ValueError("unsupported_tracker_schema")
    deps = dependencies(ledger["steps"])
    if set(unit_specs) != set(ledger["steps"]):
        raise ValueError("explicit_spec_required_for_each_tracker_step")
    units = [{**unit_specs[key], "id": key, "dependsOn": deps[key],
              "stage": key.split("@", 1)[0], "locale": row["locale"] or "shared"}
             for key, row in ledger["steps"].items()]
    return freeze_plan(plan_id, version, run_id, units, resources, **kwargs)


def samples_from_accounting(plan, events, bindings):
    """Use existing trace/monotonic projector; only explicitly bound leaf spans.

    Binding: spanId -> {accountingRunId, accountingWorkUnitId, unitId,
    identitySha256, stage/model/locale/lengthBucket/cacheClass/resourceClass}.
    The native stage/model/work-unit must match the explicit binding. Durations are
    samples only: successful process exits do not yield validated status receipts.
    """
    from scripts.weekly_pipeline_report import project_run, digest as span_digest
    units = {row["id"]: row for row in validate_plan(plan)["units"]}
    samples, issues = [], []
    for run_id in sorted({row["accountingRunId"] for row in bindings.values()}):
        selected = [e for e in events if e.get("runId") == run_id]
        if not selected:
            issues.append("bound_accounting_run_not_observed"); continue
        report = project_run(run_id, selected)
        if report["usage"]["unresolvedAttempts"]:
            issues.append("accounting_unknown_paid_outcome"); continue
        for span_id, binding in bindings.items():
            if binding["accountingRunId"] != run_id:
                continue
            unit = units.get(binding["unitId"])
            if unit is None or binding.get("identitySha256") != unit["identitySha256"]:
                issues.append("accounting_unit_binding_mismatch"); continue
            if any(binding.get(k) != unit[k] for k in DIMENSIONS) or not binding.get("accountingWorkUnitId"):
                issues.append("accounting_comparability_binding_missing"); continue
            matches = [row for row in report["workUnits"] if row["spanSha256"] == span_digest(span_id)]
            if len(matches) != 1 or matches[0]["status"] != "completed" or matches[0]["elapsedSeconds"] <= 0:
                issues.append("bound_leaf_timing_unknown"); continue
            row = matches[0]
            if row["executorType"] not in {"deterministic_program", "production_model"}:
                issues.append("accounting_nonproduction_duration_excluded"); continue
            if (row["stage"] != binding["stage"] or row.get("workUnitId") != binding["accountingWorkUnitId"]
                    or (unit["model"] != "none" and row.get("models") != [unit["model"]])):
                issues.append("accounting_stage_model_or_work_unit_mismatch"); continue
            if any(code in report["diagnostics"] for code in ("invalid_interval", "span_identity_mismatch", "unfinished_or_ambiguous_span")):
                issues.append("accounting_timing_integrity_unknown"); continue
            samples.append({**{k: unit[k] for k in DIMENSIONS}, "sampleId": "span:" + span_digest(span_id),
                            "workUnitId": binding["accountingWorkUnitId"],
                            "elapsedSeconds": row["elapsedSeconds"], "executionStatus": "succeeded",
                            "measurementKind": "empirical", "observedAt": row["finishedAt"], "sourceRef": "span:" + span_digest(span_id)})
    return {"samples": samples, "reasonCodes": sorted(set(issues)), "statusReceipts": []}


def _atomic(path, value, *, exclusive=False):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("projection_symlink_refused")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".run-progress-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            stream.flush(); os.fsync(stream.fileno())
        if exclusive:
            os.link(name, path)
            os.unlink(name)
        else:
            os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_progress(path, snapshot):
    """Replace only this projection schema, with fsync and per-output locking."""
    if snapshot.get("schemaVersion") != SCHEMA:
        raise ValueError("invalid_projection_schema")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    if path.is_symlink() or lock_path.is_symlink():
        raise ValueError("projection_symlink_refused")
    with lock_path.open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if path.exists():
            prior = json.loads(path.read_text())
            # Protect ledgers and unrelated JSON from accidental overwrite.
            _transition(snapshot, prior)
            if _time(prior["updatedAt"]) > _time(snapshot["updatedAt"]):
                raise ValueError("older_projection_refused")
        _atomic(path, snapshot)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--input", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    project = commands.add_parser("project")
    project.add_argument("--plan", type=Path, required=True)
    project.add_argument("--receipts", type=Path, required=True, help="JSON list or JSONL of full validated status snapshots")
    project.add_argument("--samples", type=Path)
    project.add_argument("--resource-state", type=Path)
    project.add_argument("--reconciliations", type=Path)
    project.add_argument("--at")
    project.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            spec = json.loads(args.input.read_text())
            plan = freeze_plan(**spec)
            _atomic(args.output, plan, exclusive=True)
        else:
            inputs = [args.plan, args.receipts, args.samples, args.resource_state, args.reconciliations]
            if any(p and p.resolve() == args.output.resolve() for p in inputs):
                raise ValueError("output_must_not_replace_input")
            plan = json.loads(args.plan.read_text())
            raw = args.receipts.read_text()
            receipts = json.loads(raw) if raw.lstrip().startswith("[") else [json.loads(line) for line in raw.splitlines() if line.strip()]
            previous = json.loads(args.output.read_text()) if args.output.exists() else None
            result = project_progress(plan, receipts, samples=json.loads(args.samples.read_text()) if args.samples else [],
                                      resource_state=json.loads(args.resource_state.read_text()) if args.resource_state else None,
                                      reconciliations=json.loads(args.reconciliations.read_text()) if args.reconciliations else [],
                                      at=args.at, previous=previous)
            write_progress(args.output, result)
        print(json.dumps({"output": str(args.output), "schemaVersion": PLAN_SCHEMA if args.command == "freeze" else SCHEMA}))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print("progress_projection_failed: " + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    if __package__ in {None, ""}:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
