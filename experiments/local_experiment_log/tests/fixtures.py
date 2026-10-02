"""Fabricated events for offline verification only. No execution or networking."""
import copy
from experiments.local_experiment_log.contract import digest, template


def fixture(mode="fixed_sample", warm=False):
    manifest = {"schema_version": "local.experiment.manifest.v1", "experiment_id": "synthetic-only-example",
                "evidence_kind": "synthetic", "duration_mode": mode, "duration_seconds": 180,
                "layer_component_mapping": {"example-client": "L3", "example-admission": "L3",
                                            "example-dispatch": "L3", "example-worker": "L3"},
                "required_layers": ["L3"],
                "admission_design_reference": "synthetic-only-not-an-admission",
                "artifact_return_reference": "synthetic-only-not-a-transfer"}
    config = {"sample_sha256": "a" * 64, "checkpoint_sha256": "b" * 64, "code_sha256": "c" * 64,
              "runtime_sha256": "d" * 64, "duration_mode": mode, "duration_seconds": 180,
              "budget_scope": "generation_and_validation" if mode == "wall_budget" else None,
              "unit_ids": [0, 1, 2, 3], "batch_size": 2,
              "load_policy": "preload_and_reuse_admitted_worker" if warm else "load_once_per_trial_process",
              "device": "cuda:0", "dtype": "bfloat16",
              "generation": {"temperature": 0.7, "repetition_penalty": 1.05, "max_new_tokens": 768,
                             "seed_policy": "42 plus batch start index", "attention_implementation": "sdpa"},
              "output_cache_hit": False, "dummy_warmup": False}
    events, sequence = [], {}
    cfg_hash = digest(config)
    def add(component, seconds, name, payload, span=None, parent=None, session=False, links=None):
        role = "macbook" if component == "example-client" else "spark" if component == "example-worker" else "mac-mini"
        sequence[component] = sequence.get(component, 0) + 1
        e = template()
        e.update(evidence_kind="synthetic", event_id=f"synthetic-event-{len(events) + 1}",
                 experiment_id=manifest["experiment_id"], trial_id=None if session else "synthetic-trial-1",
                 trace_id="synthetic-session" if session else "synthetic-trace-1", span_id=span,
                 parent_span_id=parent, links=links or [], event=name,
                 level="info",
                 layer_id=manifest["layer_component_mapping"][component], component=component,
                 host_role=role, host_id="synthetic-" + role, producer_id="synthetic-producer-" + component,
                 sequence=sequence[component], clock_id="synthetic-clock-" + role,
                 monotonic_ns=round(seconds * 1e9), timestamp_utc="2026-10-02T00:00:00Z",
                 job_id=None if session or name == "trial.configured" else "synthetic-job-1",
                 attempt=None if session or name == "trial.configured" else 1,
                 worker_id="synthetic-worker-1" if role == "spark" else None,
                 config_sha256=None if session else cfg_hash, payload=payload)
        events.append(e)

    identity = {k: config[k] for k in ["checkpoint_sha256", "code_sha256", "runtime_sha256"]}
    worker = "example-worker"
    add("example-client", .5, "trial.configured", {"config": config})
    add("example-client", 1, "span.started", {"name": "request"}, "request")
    add("example-admission", 1.1, "admission.decided", {"decision": "admitted", "reference": "synthetic-only"})
    add("example-dispatch", 1.2, "resource.sampled", {"source": "synthetic", "metrics": {"system_available_gib": 40}})
    add(worker, .1, "span.started", {"name": "worker.session"}, "session", session=warm)
    add(worker, .2, "span.started", {"name": "model.load", "identity": identity, "worker_pid": 999}, "load", "session", session=warm)
    add(worker, 2.2, "span.ended", {"name": "model.load", "status": "succeeded", "identity": identity, "worker_pid": 999}, "load", "session", session=warm)
    if mode == "wall_budget":
        add(worker, 3, "span.started", {"name": "workload.budget"}, "budget")
    for i, unit_ids in enumerate(([0, 1], [2, 3])):
        span = f"batch-{i}"
        start = 3.1 + i * 1.2
        links = [{"relation": "uses_preloaded_model", "trace_id": "synthetic-session", "span_id": "load"}] if warm else []
        payload = {"name": "batch.inference", "unit_ids": unit_ids, "cuda_synchronized": True, "worker_pid": 999}
        add(worker, start, "span.started", payload, span, links=links)
        add(worker, start + 1, "span.ended", {**payload, "status": "succeeded", "actual_batch_size": 2, "returned_wave_count": 2}, span)
        add(worker, start + 1.1, "quality.checked", {"batch_span_id": span, "unit_ids": unit_ids,
            "finite_signal": True, "sample_rate_hz": 24000, "duration_valid": True, "truncation_detected": False,
            "generated_audio_seconds": 20, "human_listening_status": "pending"}, span)
    add(worker, 5.5, "resource.sampled", {"source": "synthetic", "metrics": {"worker_rss_mib": 1000}})
    artifact = {"artifact_id": "synthetic-audio", "sha256": "e" * 64, "size_bytes": 100,
                "unit_ids": [0, 1, 2, 3]}
    add(worker, 5.6, "artifact.manifested", artifact)
    if mode == "wall_budget":
        add(worker, 183, "span.ended", {"name": "workload.budget", "status": "succeeded"}, "budget")
    add(worker, 184 if mode == "wall_budget" else 6, "span.ended", {"name": "worker.session", "status": "succeeded"}, "session", session=warm)
    add("example-client", 190 if mode == "wall_budget" else 7, "artifact.verified", {**artifact, "bytes_verified": True}, "request")
    add("example-client", 191 if mode == "wall_budget" else 8, "span.ended", {"name": "request", "status": "succeeded"}, "request")
    add("example-client", 191.1 if mode == "wall_budget" else 8.1, "trial.completed", {"status": "succeeded", "receipt_reference": "synthetic-only"})
    return copy.deepcopy(manifest), copy.deepcopy(events)
