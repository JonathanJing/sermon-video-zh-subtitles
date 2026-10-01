#!/usr/bin/env python3
"""FIELD-09 local measurement harness. No network, capture, tuning or promotion."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

from jsonschema import Draft202012Validator, FormatChecker

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCHEMA = ROOT / "schemas/sermon-field-benchmark-manifest-v1.schema.json"
CORE = ROOT / "experiments/sermon-dubbing-poc/web/fingerprint-core.mjs"
WORKER = HERE / "measure-case.mjs"
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
STATUSES = ("accepted", "rejected", "failed", "timeout")
REASONS = {"matched", "silence", "insufficient_audio", "no_consensus", "ambiguous", "low_confidence",
           "incompatible_index", "incompatible_query", "asset_unavailable", "asset_outside_root",
           "asset_size_or_type", "asset_changed", "asset_hash_mismatch", "index_invalid",
           "index_binding_invalid", "index_postings_invalid", "wav_invalid", "wav_unsupported",
           "capture_window_invalid", "ground_truth_outside_index", "worker_input_invalid",
           "implementation_changed", "worker_failed"}


class BenchmarkError(Exception):
    """Only static, privacy-safe codes are exposed at the command line."""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    def no_constant(_):
        raise ValueError("nonfinite_json")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result
    return json.loads(data, parse_constant=no_constant, object_pairs_hook=pairs)


def validate_manifest(manifest):
    schema = strict_json(SCHEMA.read_bytes())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    if next(validator.iter_errors(manifest), None):
        raise BenchmarkError("manifest_schema_invalid")
    sources, sessions = {}, {}
    # Split boundaries include a source family (including transcodes/edits), exact
    # file bytes in every asset role, and the full capture session, never windows.
    groups = {}
    def bind(kind, identity, split):
        key = (kind, identity)
        if key in groups and groups[key] != split:
            raise BenchmarkError("split_leakage")
        groups[key] = split
    for source in manifest["sources"]:
        if source["id"] in sources:
            raise BenchmarkError("duplicate_source_id")
        sources[source["id"]] = source
        bind("family", source["familyId"], source["split"])
        for kind in ("recording", "index"):
            if kind not in source:
                continue
            bind("bytes", source[kind]["sha256"], source["split"])
            bind("path", source[kind]["path"], source["split"])
    for session in manifest["sessions"]:
        if session["id"] in sessions:
            raise BenchmarkError("duplicate_session_id")
        sessions[session["id"]] = session
        bind("capture_session", session["captureSessionId"], session["split"])
        source = sources.get(session["sourceRecordingId"])
        if not source or source["split"] != session["split"]:
            raise BenchmarkError("session_source_split_invalid")
        bind("bytes", session["recording"]["sha256"], session["split"])
        bind("path", session["recording"]["path"], session["split"])
        synthetic = manifest["datasetKind"] == "synthetic_only"
        if synthetic != (session["authorization"] == "synthetic_generated") or synthetic != (session["capturePlatform"] == "synthetic"):
            raise BenchmarkError("evidence_kind_invalid")
    seen, used_sessions, used_sources = set(), set(), set()
    for item in manifest["cases"]:
        if item["id"] in seen:
            raise BenchmarkError("duplicate_case_id")
        seen.add(item["id"])
        session, source = sessions.get(item["sessionId"]), sources.get(item["targetSourceRecordingId"])
        if not session or not source or session["split"] != source["split"]:
            raise BenchmarkError("case_reference_or_split_invalid")
        if "index" not in source:
            raise BenchmarkError("target_index_required")
        if item["expected"]["kind"] == "positive" and source["id"] != session["sourceRecordingId"]:
            raise BenchmarkError("positive_source_identity_invalid")
        used_sessions.add(session["id"])
        used_sources.update((source["id"], session["sourceRecordingId"]))
    if used_sessions != set(sessions) or used_sources != set(sources):
        raise BenchmarkError("unused_source_or_session")
    if {s["split"] for s in sessions.values()} != {"dev", "holdout"}:
        raise BenchmarkError("both_splits_required")
    return sources, sessions


def distribution(values):
    """Nearest-rank percentiles; no interpolation, and no invented value for n=0."""
    ordered = sorted(values)
    return {"count": len(ordered), "p50": ordered[math.ceil(.5 * len(ordered)) - 1] if ordered else None,
            "p95": ordered[math.ceil(.95 * len(ordered)) - 1] if ordered else None}


def rate(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def summarize(rows):
    positive = [r for r in rows if r["expectedKind"] == "positive"]
    negative = [r for r in rows if r["expectedKind"] == "negative"]
    accepted_positive = [r for r in positive if r["status"] == "accepted"]
    observed_negative = [r for r in negative if r["status"] in ("accepted", "rejected")]
    false_accepts = sum(r["status"] == "accepted" for r in negative)
    wrong_position = sum(r["correctWithinTolerance"] is False for r in accepted_positive)
    return {
        "caseCount": len(rows), "sourceFamilyCount": len({r["querySourceFamilyId"] for r in rows} | {r["targetSourceFamilyId"] for r in rows}),
        "sourceRecordingCount": len({r["querySourceRecordingId"] for r in rows} | {r["targetSourceRecordingId"] for r in rows}),
        "captureSessionCount": len({r["captureSessionId"] for r in rows}),
        "captureAssetCount": len({r["sessionId"] for r in rows}),
        "independentAcousticSampleCount": None,
        "outcomeCounts": {status: sum(r["status"] == status for r in rows) for status in STATUSES},
        "reasonCounts": dict(sorted(Counter(r["reason"] for r in rows).items())),
        "positiveCorrectWithinTolerance": rate(sum(r["correctWithinTolerance"] is True for r in positive), len(positive)),
        "positiveAccepted": rate(len(accepted_positive), len(positive)),
        "positiveAcceptedOutsideTolerance": rate(wrong_position, len(positive)),
        "observedWrongJumpAllPlanned": rate(false_accepts + wrong_position, len(rows)),
        "negativeFalseAcceptAllPlanned": rate(false_accepts, len(negative)),
        "negativeFalseAcceptObserved": rate(false_accepts, len(observed_negative)),
        "negativeCorrectRejectionAllPlanned": rate(sum(r["status"] == "rejected" for r in negative), len(negative)),
        "negativeUnresolvedCount": len(negative) - len(observed_negative),
        "positiveAcceptedAbsoluteLocalizationErrorSeconds": distribution([r["absoluteLocalizationErrorSeconds"] for r in accepted_positive]),
        "caseWallMsAllPlanned": distribution([r["caseWallMs"] for r in rows]),
        "caseWallMsByOutcome": {s: distribution([r["caseWallMs"] for r in rows if r["status"] == s]) for s in STATUSES},
        "dspMsCompletedOnly": distribution([r["dspMs"] for r in rows if r["dspMs"] is not None]),
        "timeoutCount": sum(r["status"] == "timeout" for r in rows),
        "confidenceIntervals": "not_estimated_clustered_windows_are_not_independent",
    }


def measure(root, source, query_source, session, item, timeout, algorithm_sha):
    payload = {"root": str(root), "source": source, "querySource": query_source,
               "session": session, "item": item, "algorithmSha256": algorithm_sha}
    started = time.perf_counter()
    try:
        completed = subprocess.run(["node", str(WORKER)], input=json.dumps(payload), text=True,
                                   capture_output=True, timeout=timeout, check=False)
        if completed.returncode != 0 or len(completed.stdout) > 4096:
            raise ValueError("worker_protocol_invalid")
        result = strict_json(completed.stdout)
        if result.get("status") not in STATUSES or result.get("reason") not in REASONS:
            raise ValueError("worker_protocol_invalid")
        if result["status"] in ("accepted", "rejected"):
            if result.get("algorithmSha256") != algorithm_sha or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", result.get("nodeVersion", "")):
                raise ValueError("worker_protocol_invalid")
            for key in ("dspMs", "preparationMs"):
                value = result.get(key)
                if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError("worker_protocol_invalid")
            position = result.get("predictedSourceStartSeconds")
            if result["status"] == "accepted" and (not isinstance(position, (int, float)) or not math.isfinite(position) or position < 0):
                raise ValueError("worker_protocol_invalid")
    except subprocess.TimeoutExpired:
        result = {"status": "timeout", "reason": "case_deadline_exceeded"}
    except (OSError, ValueError, TypeError, AttributeError):
        result = {"status": "failed", "reason": "worker_unavailable_or_invalid"}
    result["caseWallMs"] = (time.perf_counter() - started) * 1000
    return result


def run(manifest_bytes, data_root):
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise BenchmarkError("manifest_too_large")
    try:
        manifest = strict_json(manifest_bytes)
    except (ValueError, UnicodeError):
        raise BenchmarkError("manifest_json_invalid") from None
    sources, sessions = validate_manifest(manifest)
    root = Path(data_root).resolve(strict=True)
    if not root.is_dir():
        raise BenchmarkError("data_root_invalid")
    implementation = {"runnerSha256": sha256(Path(__file__).read_bytes()), "workerSha256": sha256(WORKER.read_bytes()),
                      "algorithmSha256": sha256(CORE.read_bytes()), "manifestSchemaSha256": sha256(SCHEMA.read_bytes())}
    rows = []
    for item in manifest["cases"]:
        session = sessions[item["sessionId"]]
        source = sources[item["targetSourceRecordingId"]]
        query_source = sources[session["sourceRecordingId"]]
        result = measure(root, source, query_source, session, item, manifest["protocol"]["caseTimeoutSeconds"], implementation["algorithmSha256"])
        predicted = result.get("predictedSourceStartSeconds") if result["status"] == "accepted" else None
        expected = item["expected"].get("sourceStartSeconds")
        error = predicted - expected if predicted is not None and expected is not None else None
        rows.append({"caseId": item["id"], "split": session["split"], "sessionId": session["id"], "captureSessionId": session["captureSessionId"],
                     "targetSourceRecordingId": source["id"], "targetSourceFamilyId": source["familyId"],
                     "querySourceRecordingId": query_source["id"], "querySourceFamilyId": query_source["familyId"],
                     "capturePlatform": session["capturePlatform"], "systemVersion": session["systemVersion"],
                     "deviceTier": session["deviceTier"], "route": session["route"], "condition": session["condition"],
                     "expectedKind": item["expected"]["kind"], "expectedSourceStartSeconds": expected,
                     "predictedSourceStartSeconds": predicted, "signedLocalizationErrorSeconds": error,
                     "absoluteLocalizationErrorSeconds": abs(error) if error is not None else None,
                     "correctWithinTolerance": abs(error) <= manifest["protocol"]["localizationToleranceSeconds"] if error is not None else None,
                     "status": result["status"], "reason": result["reason"], "caseWallMs": result["caseWallMs"],
                     "preparationMs": result.get("preparationMs"), "dspMs": result.get("dspMs"),
                     "inputSampleRate": result.get("inputSampleRate"), "nodeVersion": result.get("nodeVersion"),
                     "timeoutRightCensored": result["status"] == "timeout",
                     "provenance": {"expectedTargetRecordingSha256": source["recording"]["sha256"], "expectedIndexSha256": source["index"]["sha256"],
                                    "expectedQuerySourceRecordingSha256": query_source["recording"]["sha256"], "expectedCaptureSha256": session["recording"]["sha256"],
                                    "inputVerification": "verified" if result["status"] in ("accepted", "rejected") else "incomplete"}})
    for name, file in (("runnerSha256", Path(__file__)), ("workerSha256", WORKER), ("algorithmSha256", CORE), ("manifestSchemaSha256", SCHEMA)):
        if sha256(file.read_bytes()) != implementation[name]:
            raise BenchmarkError("implementation_changed")
    grouped = defaultdict(list)
    dimensions = ("split", "capturePlatform", "systemVersion", "deviceTier", "route", "condition")
    for row in rows:
        grouped[tuple(row[d] for d in dimensions)].append(row)
    return {"schemaVersion": "sermon-field-benchmark-report-v1", "datasetKind": manifest["datasetKind"],
            "evidenceScope": "synthetic_harness_only" if manifest["datasetKind"] == "synthetic_only" else "offline_local_recording_replay_only",
            "generatedAt": datetime.now(timezone.utc).isoformat(), "manifestSha256": sha256(manifest_bytes),
            "implementation": implementation, "algorithmVersion": "spectral-landmarks-v1", "indexSchemaVersion": "sermon-landmark-index-v1",
            "measurementRuntime": {"engine": "node_offline_worker", "hostSystem": platform.system(), "pythonVersion": platform.python_version(),
                                   "nodeVersionsObserved": sorted({r["nodeVersion"] for r in rows if r["nodeVersion"]})},
            "protocol": manifest["protocol"], "splitPolicy": manifest["splitPolicy"],
            "status": "completed_with_unresolved_cases" if any(r["status"] in ("failed", "timeout") for r in rows) else "measurement_complete",
            "metrics": {split: summarize([r for r in rows if r["split"] == split]) for split in ("dev", "holdout")},
            "strata": [{"stratum": dict(zip(dimensions, key)), "metrics": summarize(group)} for key, group in sorted(grouped.items())],
            "cases": rows, "promotionAllowed": False,
            "acceptance": {key: "not_run" for key in ("swiftParity", "legacyPackedParity", "browserSafari", "nativeIOS", "device", "venue", "audibleOutput", "subtitleAlignment", "peakMemory", "microphoneOccupancy", "firstSecondHit")},
            "limitations": ["window_counts_are_not_independent_acoustic_samples", "declared_family_and_session_identity_requires_curation",
                            "offline_wall_time_includes_process_start_asset_verification_and_dsp_not_capture_or_playback",
                            "timeouts_are_right_censored_and_never_dropped", "localization_error_is_accepted_positive_only_success_denominator_is_all_planned",
                            "negative_false_accept_rate_is_incomplete_when_cases_are_unresolved", "zero_observed_false_accepts_does_not_prove_zero_risk",
                            "capture_platform_labels_do_not_establish_platform_runtime_acceptance"],
            "privacy": {"localOnly": True, "containsAudio": False, "containsLandmarks": False, "containsPaths": False,
                        "sharing": "not_authorized_by_running_benchmark", "ids": "use_opaque_nonidentifying_labels"}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path, help="New local report; never overwrites existing evidence")
    args = parser.parse_args(argv)
    try:
        # Reserve output before running any case. A partial file is never a valid report.
        fd = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        print("field-benchmark: output_unavailable_or_exists", file=sys.stderr)
        return 2
    try:
        with args.manifest.open("rb") as stream:
            manifest_bytes = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(manifest_bytes) > MAX_MANIFEST_BYTES:
            raise BenchmarkError("manifest_too_large")
        report = run(manifest_bytes, args.data_root)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = None
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({"status": report["status"], "caseCount": len(report["cases"]), "promotionAllowed": False}))
        return 1 if report["status"] == "completed_with_unresolved_cases" else 0
    except (BenchmarkError, OSError, ValueError) as error:
        code = str(error) if isinstance(error, BenchmarkError) else "input_or_output_invalid"
        print("field-benchmark: " + code, file=sys.stderr)
        return 2
    finally:
        if fd is not None:
            os.close(fd)
            args.report.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
