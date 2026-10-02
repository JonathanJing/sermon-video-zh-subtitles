"""Pure adapter to existing Tongxing accounting events; no dispatch or live writer."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.local_experiment_log.contract import canonical, digest, validate_event

from scripts import sermon_log_contract as accounting

CONTEXT_KEYS = {"runId", "workflowId", "workUnitId", "attemptId", "decisionId", "productionRunId",
                "engineeringRunId", "executorType", "workKind", "evidenceMode", "eventId", "producerId",
                "sequence", "traceId", "spanId", "parentSpanId", "clockDomainId", "missingReasons",
                "dependsOn", "blockedBy", "dependencyReadyAt", "queuedAt", "jobId", "attemptNumber"}
REQUIRED_CONTEXT = CONTEXT_KEYS - {"jobId", "attemptNumber"}
ALLOWED_LAYERS = {"L1": "layer1.", "L2": "layer2.", "L3": "layer3.", "L4": "layer4."}


def convert(measurement, context, start=None):
    """Caller provides canonical identities; never generate production/run/attempt identity."""
    validate_event(measurement)
    if set(context) - CONTEXT_KEYS or REQUIRED_CONTEXT - set(context):
        raise ValueError("canonical_context_incomplete_or_unknown")
    pairs = {"eventId": "event_id", "producerId": "producer_id", "sequence": "sequence",
             "traceId": "trace_id", "spanId": "span_id", "parentSpanId": "parent_span_id",
             "clockDomainId": "clock_id", "jobId": "job_id"}
    if any(context.get(k) != measurement[v] for k, v in pairs.items()):
        raise ValueError("canonical_identity_alias_conflict")
    if "attemptNumber" in context and context["attemptNumber"] != measurement["attempt"]:
        raise ValueError("canonical_attempt_number_conflict")
    expected_trace = hashlib.sha256(("sermon-trace-v1:" + context["runId"]).encode()).hexdigest()[:32]
    if context["traceId"] != expected_trace:
        raise ValueError("canonical_run_trace_binding_conflict")
    expected_evidence = {"real": "current_execution", "synthetic": "synthetic", "replay": "cache_replay"}[measurement["evidence_kind"]]
    if context["evidenceMode"] != expected_evidence:
        raise ValueError("canonical_evidence_mode_conflict")
    unit = context["workUnitId"]
    if not isinstance(unit, str) or not unit.startswith(ALLOWED_LAYERS[measurement["layer_id"]]):
        raise ValueError("canonical_logical_layer_conflict")
    if measurement["event"] == "trial.completed" and measurement["evidence_kind"] == "real":
        # A measurement cannot itself grant completion or production acceptance.
        if not measurement["payload"].get("receipt_reference"):
            raise ValueError("authoritative_receipt_reference_required")
    row = {k: copy.deepcopy(v) for k, v in context.items()}
    row.update(schemaVersion="sermon-workflow-accounting-v3", contractVersion=accounting.VERSION,
               recordedAt=measurement["timestamp_utc"].replace("+00:00", "Z"),
               stage="experiment." + measurement["payload"].get("name", measurement["event"]))
    row["metrics"] = {"experimentObservationSha256": digest(measurement),
                      "experimentIdentitySha256": hashlib.sha256(measurement["experiment_id"].encode()).hexdigest()}
    if measurement["config_sha256"]:
        row["metrics"]["configSha256"] = measurement["config_sha256"]
    if measurement["trial_id"]:
        row["metrics"]["trialIdentitySha256"] = hashlib.sha256(measurement["trial_id"].encode()).hexdigest()
    if measurement["worker_id"]:
        row["metrics"]["workerIdentitySha256"] = hashlib.sha256(measurement["worker_id"].encode()).hexdigest()
    p = measurement["payload"]
    if measurement["event"] == "span.started":
        row.update(event="stage_started", startedAt=row["recordedAt"], monotonicStartNs=str(measurement["monotonic_ns"]))
    elif measurement["event"] == "span.ended":
        if start is None:
            raise ValueError("canonical_start_evidence_required")
        validate_event(start)
        for key in ("clock_id", "producer_id", "trace_id", "span_id", "parent_span_id", "config_sha256", "worker_id"):
            if start[key] != measurement[key]:
                raise ValueError("canonical_span_identity_conflict")
        if start["event"] != "span.started" or start["payload"]["name"] != p["name"]:
            raise ValueError("canonical_start_evidence_conflict")
        begin, end = start["monotonic_ns"], measurement["monotonic_ns"]
        if end < begin:
            raise ValueError("canonical_clock_regression")
        row.update(event="stage_finished", startedAt=start["timestamp_utc"].replace("+00:00", "Z"),
                   completedAt=row["recordedAt"], monotonicStartNs=str(begin), monotonicEndNs=str(end),
                   elapsedSeconds=(end - begin) / 1e9, cacheHit=False, billing="local",
                   status={"succeeded": "completed", "failed": "failed", "cancelled": "cancelled", "timeout": "failed"}[p["status"]])
        if p["status"] == "timeout":
            row["errorType"] = "TimeoutError"
    else:
        row["event"] = "workload"
    if p.get("name") == "batch.inference":
        row["metrics"]["configuredUnitCount"] = len(p["unit_ids"])
        row["metrics"]["cudaSynchronized"] = p["cuda_synchronized"]
        for name in ("actual_batch_size", "returned_wave_count"):
            if name in p:
                row["metrics"]["actualBatchSize" if name == "actual_batch_size" else "returnedWaveCount"] = p[name]
    # Profile labels remain canonical. Detailed config, GPU metrics and experiment
    # links stay in the hash-bound sidecar; no unknown top-level profile fields.
    accounting.validate_event(row)
    return row


def verify_pair(row, measurement):
    accounting.validate_event(row)
    validate_event(measurement)
    if row.get("metrics", {}).get("experimentObservationSha256") != digest(measurement):
        raise ValueError("measurement_sidecar_hash_conflict")
    for key, other in (("eventId", "event_id"), ("producerId", "producer_id"), ("sequence", "sequence"),
                       ("traceId", "trace_id"), ("spanId", "span_id"), ("parentSpanId", "parent_span_id"),
                       ("clockDomainId", "clock_id")):
        if row[key] != measurement[other]:
            raise ValueError("measurement_sidecar_identity_conflict")
    if row.get("jobId") != measurement["job_id"]:
        raise ValueError("measurement_sidecar_job_conflict")
    if "attemptNumber" in row and row["attemptNumber"] != measurement["attempt"]:
        raise ValueError("measurement_sidecar_attempt_conflict")
    if not row["workUnitId"].startswith(ALLOWED_LAYERS[measurement["layer_id"]]):
        raise ValueError("measurement_sidecar_layer_conflict")
    expected_evidence = {"real": "current_execution", "synthetic": "synthetic", "replay": "cache_replay"}[measurement["evidence_kind"]]
    if row["evidenceMode"] != expected_evidence:
        raise ValueError("measurement_sidecar_evidence_conflict")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurements", type=Path, required=True)
    parser.add_argument("--contexts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.resolve() in {args.measurements.resolve(), args.contexts.resolve()} or args.out.exists():
        parser.error("output must be a new file distinct from inputs")
    try:
        measurements = [json.loads(line) for line in args.measurements.read_text().splitlines() if line.strip()]
        contexts = json.loads(args.contexts.read_text())
        starts = {(e["trace_id"], e["span_id"]): e for e in measurements if e["event"] == "span.started"}
        rows = [convert(e, contexts[e["event_id"]], starts.get((e["trace_id"], e["span_id"]))) for e in measurements]
        for row, measurement in zip(rows, measurements):
            verify_pair(row, measurement)
        integrity = accounting.replay_integrity(rows)
        if integrity["status"] != "consistent":
            raise ValueError("canonical_replay_inconsistent")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents replacing any existing evidence file.
        with args.out.open("x", encoding="utf-8") as stream:
            for row in rows:
                stream.write(accounting.canonical_bytes(row).decode() + "\n")
        print(json.dumps({"canonical_events": len(rows), "contract": accounting.VERSION, "replay_status": integrity["status"], "external_actions": 0}))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        # Fixed error codes from canonical validator contain no rejected payload.
        print("canonical bridge failed: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
