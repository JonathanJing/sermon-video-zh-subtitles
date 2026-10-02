"""Read-only local log audit and bounded metrics; never executes jobs."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.local_experiment_log.contract import canonical, digest, validate_event, validate_manifest


def audit(manifest, raw_events):
    validate_manifest(manifest)
    errors, warnings, events, seen = [], [], [], {}
    for position, e in enumerate(raw_events, 1):
        try:
            validate_event(e)
            key = e["event_id"]
            if key in seen:
                if canonical(e) != seen[key]:
                    raise ValueError("event_id reused with different content")
                continue
            seen[key] = canonical(e)
            if e["experiment_id"] != manifest["experiment_id"] or e["evidence_kind"] != manifest["evidence_kind"]:
                raise ValueError("experiment/evidence kind differs from manifest")
            if manifest["layer_component_mapping"].get(e["component"]) != e["layer_id"]:
                raise ValueError("component/layer mapping differs from manifest")
            if (e["job_id"] is None) != (e["attempt"] is None):
                raise ValueError("job_id and attempt must both be present or absent")
            events.append(e)
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(f"event {position}: {exc}")

    producers, traces, starts, ends, trials = defaultdict(list), defaultdict(list), {}, {}, defaultdict(list)
    for e in events:
        producers[e["producer_id"]].append(e)
        traces[e["trace_id"]].append(e)
        if e["trial_id"]:
            trials[e["trial_id"]].append(e)
        if e["event"] in ("span.started", "span.ended"):
            target = starts if e["event"] == "span.started" else ends
            key = (e["trace_id"], e["span_id"])
            if key in target:
                errors.append(f"duplicate {e['event']}: {key}")
            target[key] = e

    for producer, items in producers.items():
        identities = {(e["clock_id"], e["host_id"], e["component"]) for e in items}
        if len(identities) != 1:
            errors.append(f"producer identity/clock changed: {producer}")
        ordered = sorted(items, key=lambda e: e["sequence"])
        seq = [e["sequence"] for e in ordered]
        if len(set(seq)) != len(seq):
            errors.append(f"duplicate producer sequence: {producer}")
        if any(b["monotonic_ns"] < a["monotonic_ns"] for a, b in zip(ordered, ordered[1:])):
            errors.append(f"producer monotonic clock regressed: {producer}")
        if any(b != a + 1 for a, b in zip(seq, seq[1:])):
            warnings.append(f"producer sequence gap: {producer}")

    durations = {}
    for key, end in ends.items():
        start = starts.get(key)
        if not start:
            errors.append(f"end without start: {key}")
            continue
        fields = ["producer_id", "clock_id", "host_id", "host_role", "component", "layer_id",
                  "parent_span_id", "trial_id", "worker_id", "config_sha256", "job_id", "attempt"]
        if any(start[k] != end[k] for k in fields) or start["payload"]["name"] != end["payload"]["name"]:
            errors.append(f"span identity/clock changed: {key}")
        elif end["monotonic_ns"] < start["monotonic_ns"]:
            errors.append(f"negative duration: {key}")
        else:
            durations[key] = (end["monotonic_ns"] - start["monotonic_ns"]) / 1e9

    for key, start in starts.items():
        if key not in ends:
            warnings.append(f"open span: {key}")
        parent = start["parent_span_id"]
        if parent and (key[0], parent) not in starts:
            errors.append(f"missing parent span: {key}")
        visited, cursor = set(), key
        while cursor in starts:
            if cursor in visited:
                errors.append(f"parent span cycle: {key}")
                break
            visited.add(cursor)
            p = starts[cursor]["parent_span_id"]
            cursor = (cursor[0], p) if p else None
    for e in events:
        if e["span_id"] and (e["trace_id"], e["span_id"]) not in starts:
            errors.append(f"event references missing span: {e['event_id']}")
        for link in e["links"]:
            if (link["trace_id"], link["span_id"]) not in starts:
                errors.append(f"missing linked span: {e['event_id']}")

    rows = []
    for trial_id, items in trials.items():
        reasons = []
        configs = [e for e in items if e["event"] == "trial.configured"]
        terminals = [e for e in items if e["event"] == "trial.completed"]
        row = {"trial_id": trial_id, "eligible": False, "reasons": reasons, "metrics": {}}
        rows.append(row)
        if len(configs) != 1:
            reasons.append("exactly_one_trial_configuration_required")
            continue
        config_event = configs[0]
        config = config_event["payload"]["config"]
        row.update(config_sha256=config_event["config_sha256"], batch_size=config["batch_size"],
                   load_policy=config["load_policy"])
        row["comparison_sha256"] = digest({k: v for k, v in config.items() if k not in ("batch_size", "load_policy")})
        if any(e["config_sha256"] != config_event["config_sha256"] or e["trace_id"] != config_event["trace_id"] for e in items):
            errors.append(f"trial identity/config changed: {trial_id}")
        jobs = {(e["job_id"], e["attempt"]) for e in items if e["job_id"]}
        if len(jobs) != 1:
            reasons.append("one_job_attempt_required_per_trial")
        if config["duration_mode"] != manifest["duration_mode"] or config["duration_seconds"] != manifest["duration_seconds"]:
            errors.append(f"trial duration differs from manifest: {trial_id}")
        if len(terminals) != 1:
            reasons.append("exactly_one_terminal_receipt_required")
        elif terminals[0]["payload"]["status"] not in ("succeeded", "budget_exhausted"):
            reasons.append("trial_did_not_succeed")
        elif config["duration_mode"] == "fixed_sample" and terminals[0]["payload"]["status"] != "succeeded":
            reasons.append("fixed_sample_terminal_not_successful")
        required_layers = set(manifest.get("required_layers", manifest["layer_component_mapping"].values()))
        if not required_layers.issubset({e["layer_id"] for e in items}):
            reasons.append("required_logical_layer_trace_incomplete")
        if config["output_cache_hit"] or config["dummy_warmup"]:
            reasons.append("cache_or_unaccounted_warmup")
        if config["duration_mode"] == "fixed_sample" and config["budget_scope"] is not None:
            reasons.append("fixed_sample_has_unexpected_budget_scope")
        admission = [e for e in items if e["event"] == "admission.decided"]
        if len(admission) != 1 or admission[0]["payload"]["decision"] != "admitted" or not admission[0]["job_id"]:
            reasons.append("missing_admitted_job")

        trial_keys = [k for k, s in starts.items() if s["trial_id"] == trial_id]
        request_keys = [k for k in trial_keys if starts[k]["payload"]["name"] == "request"]
        if len(request_keys) != 1 or request_keys[0] not in durations:
            reasons.append("request_span_missing_or_open")
        else:
            req = request_keys[0]
            if starts[req]["host_role"] != "macbook":
                reasons.append("request_not_measured_on_macbook")
            row["metrics"]["request_seconds"] = durations[req]
        if any(k not in ends or ends[k]["payload"]["status"] != "succeeded" for k in trial_keys):
            reasons.append("open_or_unsuccessful_trial_span")

        load_keys = [k for k in trial_keys if starts[k]["payload"]["name"] == "model.load"]
        if config["load_policy"] == "preload_and_reuse_admitted_worker":
            load_keys += [(link["trace_id"], link["span_id"]) for e in items for link in e["links"]
                          if link["relation"] == "uses_preloaded_model"]
        load_keys = sorted(set(load_keys))
        batches = [k for k in trial_keys if starts[k]["payload"]["name"] == "batch.inference"]
        if len(load_keys) != 1 or load_keys[0] not in durations:
            reasons.append("one_completed_model_load_required")
        else:
            load_key, load = load_keys[0], starts[load_keys[0]]
            row["model_load_span"] = {"trace_id": load_key[0], "span_id": load_key[1], "worker_id": load["worker_id"]}
            row["metrics"]["referenced_model_load_seconds"] = durations[load_key]
            identity = load["payload"].get("identity", {})
            if load["payload"]["name"] != "model.load" or not load["worker_id"] or ends[load_key]["payload"]["status"] != "succeeded":
                reasons.append("invalid_model_load_reference")
            if any(identity.get(k) != config[k] for k in ("checkpoint_sha256", "code_sha256", "runtime_sha256")):
                reasons.append("preload_model_identity_mismatch")
            if ends[load_key]["payload"].get("identity") != identity or ends[load_key]["payload"].get("worker_pid") != load["payload"].get("worker_pid"):
                reasons.append("load_identity_or_pid_changed")
            if any(starts[k]["worker_id"] != load["worker_id"] or starts[k]["clock_id"] != load["clock_id"] or
                   starts[k]["producer_id"] != load["producer_id"] or
                   starts[k]["payload"].get("worker_pid") != load["payload"].get("worker_pid") or
                   starts[k]["monotonic_ns"] < ends[load_key]["monotonic_ns"] for k in batches):
                reasons.append("batch_does_not_use_loaded_worker")
            worker_loads = [s for s in starts.values() if s["payload"]["name"] == "model.load" and s["worker_id"] == load["worker_id"]]
            if len(worker_loads) != 1:
                reasons.append("worker_reloaded_model")
            if load["host_role"] != "spark":
                reasons.append("model_not_loaded_on_spark")
            session_keys = [k for k, s in starts.items() if s["payload"]["name"] == "worker.session" and s["worker_id"] == load["worker_id"]]
            if len(session_keys) != 1 or session_keys[0] not in durations:
                reasons.append("completed_worker_session_required")
            else:
                session_key = session_keys[0]
                ss, se = starts[session_key], ends[session_key]
                row["worker_session_span"] = {"trace_id": session_key[0], "span_id": session_key[1]}
                if ss["clock_id"] != load["clock_id"] or ss["monotonic_ns"] > load["monotonic_ns"] or se["payload"]["status"] != "succeeded" or any(k not in ends or ends[k]["monotonic_ns"] > se["monotonic_ns"] for k in batches):
                    reasons.append("worker_session_does_not_cover_execution")

        budget_keys = [k for k in trial_keys if starts[k]["payload"]["name"] == "workload.budget"]
        budget = budget_keys[0] if len(budget_keys) == 1 and budget_keys[0] in durations else None
        if config["duration_mode"] == "wall_budget":
            if not budget or config["budget_scope"] not in ("generation_and_validation", "including_load"):
                reasons.append("explicit_completed_budget_span_required")
            elif abs(durations[budget] - config["duration_seconds"]) > .05:
                reasons.append("budget_span_does_not_match_fixed_duration")
            elif config["budget_scope"] == "including_load" and load_keys and load_keys[0] in starts:
                ls = starts[load_keys[0]]
                if ls["clock_id"] != starts[budget]["clock_id"] or ls["monotonic_ns"] < starts[budget]["monotonic_ns"]:
                    reasons.append("load_outside_including_load_budget")

        qualities = [e for e in items if e["event"] == "quality.checked"]
        completed, generated_seconds, inference_seconds = [], 0, 0
        if not batches:
            reasons.append("no_inference_batch")
        batches.sort(key=lambda k: (starts[k]["clock_id"], starts[k]["monotonic_ns"]))
        expected_chunks = [config["unit_ids"][i:i + config["batch_size"]] for i in range(0, len(config["unit_ids"]), config["batch_size"])]
        actual_chunks = [starts[k]["payload"]["unit_ids"] for k in batches]
        if actual_chunks != expected_chunks[:len(actual_chunks)] or len(actual_chunks) > len(expected_chunks):
            reasons.append("configured_batch_not_applied_to_frozen_units")
        for key in batches:
            start, end = starts[key], ends.get(key)
            if not end or key not in durations:
                continue
            p, ep = start["payload"], end["payload"]
            q = [e for e in qualities if e["payload"]["batch_span_id"] == key[1]]
            if p["unit_ids"] != ep["unit_ids"] or ep["actual_batch_size"] != len(p["unit_ids"]) or ep["returned_wave_count"] != len(p["unit_ids"]) or len(p["unit_ids"]) > config["batch_size"]:
                reasons.append("actual_batch_or_output_count_mismatch")
            if p["cuda_synchronized"] is not True or ep["cuda_synchronized"] is not True:
                reasons.append("inference_timer_not_cuda_synchronized")
            if len(q) != 1:
                reasons.append("one_quality_record_per_batch_required")
                continue
            qe, qp = q[0], q[0]["payload"]
            if qe["clock_id"] != end["clock_id"] or qe["producer_id"] != end["producer_id"] or qe["worker_id"] != end["worker_id"] or qe["monotonic_ns"] < end["monotonic_ns"] or qp["unit_ids"] != p["unit_ids"]:
                reasons.append("quality_identity_or_timing_mismatch")
                continue
            if not qp["finite_signal"] or not qp["duration_valid"] or qp["truncation_detected"] or qp["sample_rate_hz"] != 24000 or qp["human_listening_status"] == "failed":
                reasons.append("quality_check_failed")
                continue
            if config["duration_mode"] == "wall_budget":
                if not budget or qe["clock_id"] != starts[budget]["clock_id"] or start["monotonic_ns"] < starts[budget]["monotonic_ns"] or qe["monotonic_ns"] > starts[budget]["monotonic_ns"] + round(config["duration_seconds"] * 1e9):
                    continue  # Explicitly exclude batches outside the measurement budget.
            completed += p["unit_ids"]
            generated_seconds += qp["generated_audio_seconds"]
            inference_seconds += durations[key]
        if len(completed) != len(set(completed)) or not set(completed).issubset(config["unit_ids"]):
            reasons.append("duplicate_or_unknown_completed_unit")
        if config["duration_mode"] == "fixed_sample" and set(completed) != set(config["unit_ids"]):
            reasons.append("fixed_sample_incomplete")
        if not completed:
            reasons.append("no_valid_completed_unit")

        manifests = [e for e in items if e["event"] == "artifact.manifested"]
        verified = [e for e in items if e["event"] == "artifact.verified"]
        manifest_ids = [e["payload"]["artifact_id"] for e in manifests]
        verified_ids = [e["payload"]["artifact_id"] for e in verified]
        if len(set(manifest_ids)) != len(manifest_ids) or set(verified_ids) != set(manifest_ids):
            reasons.append("artifact_identity_set_mismatch")
        covered = set()
        for art in manifests:
            ap = art["payload"]
            match = [v for v in verified if v["payload"]["artifact_id"] == ap["artifact_id"]]
            if len(match) != 1 or any(match[0]["payload"][k] != ap[k] for k in ("sha256", "size_bytes", "unit_ids")) or not match[0]["payload"]["bytes_verified"]:
                reasons.append("artifact_bytes_missing_or_mismatch")
                continue
            v = match[0]
            if len(request_keys) != 1 or request_keys[0] not in ends or v["clock_id"] != ends[request_keys[0]]["clock_id"] or v["host_role"] != "macbook" or v["monotonic_ns"] > ends[request_keys[0]]["monotonic_ns"] or v["monotonic_ns"] < starts[request_keys[0]]["monotonic_ns"]:
                reasons.append("artifact_not_verified_before_macbook_request_end")
                continue
            covered.update(ap["unit_ids"])
        if not set(completed).issubset(covered):
            reasons.append("completed_units_without_verified_bytes")
        row["metrics"].update(completed_units=len(completed), generated_audio_seconds=generated_seconds,
                              inference_seconds=inference_seconds,
                              inference_seconds_all_observed_batches=sum(durations[k] for k in batches if k in durations),
                              rtf_inference=inference_seconds / generated_seconds if generated_seconds else None)
        denominator = config["duration_seconds"] if config["duration_mode"] == "wall_budget" else row["metrics"].get("request_seconds")
        row["metrics"]["units_per_second"] = len(completed) / denominator if denominator else None
        if budget:
            row["metrics"]["budget_observed_seconds"] = durations[budget]
        row["batch_timings_seconds"] = [durations[k] for k in batches if k in durations]
        batch_times = row["batch_timings_seconds"]
        row["metrics"]["first_inference_batch_seconds"] = batch_times[0] if batch_times else None
        row["metrics"]["subsequent_inference_batches_seconds"] = sum(batch_times[1:]) if len(batch_times) > 1 else None
        row["resource_snapshot_count"] = sum(e["event"] == "resource.sampled" for e in items)
        row["human_listening_statuses"] = sorted({q["payload"]["human_listening_status"] for q in qualities})
        reasons[:] = sorted(set(reasons))
        row["eligible"] = not reasons

    if errors or warnings:
        for row in rows:
            row["eligible"] = False
            row["reasons"].append("experiment_log_errors_or_incomplete_stream")
    groups = defaultdict(list)
    for row in rows:
        if row["eligible"]:
            groups[(row["comparison_sha256"], row["load_policy"], row["batch_size"])].append(row)
    summaries = []
    for (comparison, policy, batch), group in sorted(groups.items()):
        metrics = {}
        for metric in group[0]["metrics"]:
            values = [r["metrics"].get(metric) for r in group]
            values = [v for v in values if type(v) in (int, float)]
            metrics[metric] = {"n": len(values), "median": statistics.median(values) if values else None}
        summaries.append({"comparison_sha256": comparison, "load_policy": policy, "batch_size": batch,
                          "trial_count": len(group), "metrics": metrics})
    sessions = []
    for key, start in starts.items():
        if start["payload"]["name"] != "worker.session":
            continue
        referenced_rows = [r for r in rows if r.get("worker_session_span") == {"trace_id": key[0], "span_id": key[1]}]
        load_ids = sorted({(r["model_load_span"]["trace_id"], r["model_load_span"]["span_id"]) for r in referenced_rows})
        sessions.append({"trace_id": key[0], "span_id": key[1], "worker_id": start["worker_id"],
                         "session_seconds": durations.get(key), "load_seconds_once": sum(durations.get(k, 0) for k in load_ids) if load_ids else None,
                         "referenced_trial_count": len(referenced_rows), "eligible_trial_count": sum(r["eligible"] for r in referenced_rows),
                         "amortized_load_seconds_per_referenced_trial": sum(durations.get(k, 0) for k in load_ids) / len(referenced_rows) if referenced_rows else None,
                         "note": "Session cost is counted once. Amortization is a calculation, not an additional measured span."})
    return {"schema_version": "local.experiment.audit.v1", "experiment_id": manifest["experiment_id"],
            "evidence_kind": manifest["evidence_kind"], "hardware_execution_independently_verified": False,
            "unique_event_count": len(events), "duplicate_event_count": len(raw_events) - len(events) if not errors else None,
            "errors": errors, "warnings": warnings, "trials": rows, "groups": summaries, "sessions": sessions,
            "note": "Evidence consistency only; producer truth, deployment and job admission are not authorized by this report."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--logs", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--canonical", type=Path, help="Existing-profile accounting events paired with the measurement sidecars")
    args = parser.parse_args()
    inputs = [args.manifest, *args.logs] + ([args.canonical] if args.canonical else [])
    if args.out.resolve() in {p.resolve() for p in inputs}:
        parser.error("output must not overwrite input")
    try:
        manifest = json.loads(args.manifest.read_text())
        validate_manifest(manifest)
        events = []
        for path in args.logs:
            for line_number, line in enumerate(path.read_text().splitlines(), 1):
                if line.strip():
                    try:
                        events.append(json.loads(line))
                    except ValueError as exc:
                        raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        if manifest["evidence_kind"] == "real" and args.canonical is None:
            raise ValueError("real experiments require canonical accounting evidence")
        if args.canonical:
            from experiments.local_experiment_log.canonical_bridge import accounting, verify_pair
            canonical_rows = [json.loads(line) for line in args.canonical.read_text().splitlines() if line.strip()]
            by_id = {}
            for row in canonical_rows:
                accounting.validate_event(row)
                if row["eventId"] in by_id and canonical(by_id[row["eventId"]]) != canonical(row):
                    raise ValueError("canonical_event_conflict")
                by_id[row["eventId"]] = row
            for e in events:
                verify_pair(by_id[e["event_id"]], e)
            integrity = accounting.replay_integrity(canonical_rows)
            if integrity["status"] != "consistent":
                raise ValueError("canonical_replay_inconsistent")
        report = audit(manifest, events)
        report["canonical_contract_verified"] = args.canonical is not None
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"audit failed: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"evidence_kind": report["evidence_kind"], "errors": len(report["errors"]),
                      "warnings": len(report["warnings"]), "eligible_trials": sum(r["eligible"] for r in report["trials"]),
                      "report": str(args.out)}, ensure_ascii=False))
    return 1 if report["errors"] or report["warnings"] or not report["trials"] or any(not r["eligible"] for r in report["trials"]) else 0


if __name__ == "__main__":
    sys.exit(main())
