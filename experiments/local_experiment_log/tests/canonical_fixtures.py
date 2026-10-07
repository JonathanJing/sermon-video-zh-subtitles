"""Synthetic caller-owned canonical context, never production identity."""
import hashlib
from experiments.local_experiment_log.tests.fixtures import fixture


def short(value):
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def compatible_fixture(warm=False):
    manifest, events = fixture(warm=warm)
    manifest["layer_component_mapping"] = {k: "L3" for k in manifest["layer_component_mapping"]}
    manifest["required_layers"] = ["L3"]
    trace_runs = {e["trace_id"]: "engineering.logsmoke." + ("trial" if e["trial_id"] else "session") for e in events}
    contexts = {}
    for e in events:
        old_trace = e["trace_id"]
        e["trace_id"] = short("sermon-trace-v1:" + trace_runs[old_trace])
        e["event_id"] = short(e["event_id"])
        e["producer_id"] = short(e["producer_id"])
        e["clock_id"] = short(e["clock_id"])
        e["layer_id"] = "L3"
        for link in e["links"]:
            link["trace_id"] = short("sermon-trace-v1:" + trace_runs[link["trace_id"]])
        contexts[e["event_id"]] = {
            "runId": trace_runs[old_trace], "workflowId": "layer3.tts.experiment.v1",
            "workUnitId": "layer3.tts." + e["payload"].get("name", e["event"]),
            "attemptId": "engineering.attempt." + (e["span_id"] or "observation"),
            "decisionId": None, "productionRunId": None, "engineeringRunId": "engineering.logsmoke",
            "executorType": "deterministic_program", "workKind": "engineering", "evidenceMode": "synthetic",
            "eventId": e["event_id"], "producerId": e["producer_id"], "sequence": e["sequence"],
            "traceId": e["trace_id"], "spanId": e["span_id"], "parentSpanId": e["parent_span_id"],
            "clockDomainId": e["clock_id"], "dependsOn": [], "blockedBy": [],
            "dependencyReadyAt": None, "queuedAt": None, "jobId": e["job_id"],
            "missingReasons": {"decisionId": "not_applicable", "productionRunId": "not_applicable",
                               "dependencyReadyAt": "not_observed", "queuedAt": "not_observed"}
        }
        if e["parent_span_id"] is None:
            contexts[e["event_id"]]["missingReasons"]["parentSpanId"] = "not_applicable"
    return manifest, events, contexts
