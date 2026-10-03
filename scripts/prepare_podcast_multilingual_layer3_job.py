#!/usr/bin/env python3
"""Freeze an ES/KO dual-worker Layer 3 candidate job under an explicit review waiver.

This creates private run inputs only. It does not start model inference or grant
release eligibility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PODCAST = ROOT / "artifacts/podcasts/if-i-had-more-time-jesus-is-worthy"
PREP = PODCAST / "layer3-dual-worker-prep"
SOURCE = PODCAST / "pipeline/source-revision-quote-unquote/english-source-package.json"
ANCHOR = PODCAST / "sentence-interpretation-v2-quote-unquote/6e72e5868b64227f9d4df59aac8809b74a4bd6e6b4f5dcf5921456bccd3c4b16/anchor-manifest.json"
BASE_ROUTE = PREP / "speaker-route-v1.json"
TIMELINE = PREP / "audio-timeline-map-v1.json"
REGISTRY = ROOT / "config/speaker-voice-registry.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def json_sha(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: Path) -> dict[str, str]:
    value = load(path)
    return {"path": str(path.resolve()), "sha256": file_sha(path), "jsonSha256": json_sha(value)}


def make(locale: str, candidate_path: Path | None = None,
         policy_path: Path | None = None, waiver_path: Path | None = None,
         extension_dir: Path | None = None, out: Path | None = None) -> Path:
    if locale not in {"es", "ko"}:
        raise ValueError("Only the user-authorized Spanish and Korean locales are supported")
    l2 = PODCAST / "layer2-formal-prep" / locale
    candidate_path = (candidate_path or l2 / "candidate.machine.json").resolve()
    policy_path = (policy_path or next(l2.glob("policy-v2-user-review-waived-r*.json"))).resolve()
    waiver_path = (waiver_path or l2 / next(p.name for p in l2.glob("user-review-waiver-r*.json"))).resolve()
    candidate, source, anchor = load(candidate_path), load(SOURCE), load(ANCHOR)
    policy, waiver = load(policy_path), load(waiver_path)
    route = load(BASE_ROUTE)
    base_ids = [row["translationGroupId"] for row in route["groups"]]
    groups = candidate["groups"]
    if len(groups) != 839 or [g["translationGroupId"] for g in groups] != base_ids:
        raise ValueError(f"{locale}: candidate group sequence differs from approved route")
    if candidate["status"] != "machine_review_pass_human_review_pending" or candidate["releaseEligible"]:
        raise ValueError(f"{locale}: candidate is not machine-passed and human-review-pending")
    if waiver["humanApproval"] or waiver["releaseEligible"] or not waiver["audioHumanReviewRequired"]:
        raise ValueError(f"{locale}: waiver must keep approval/release false and audio review required")
    if waiver["targetLocale"] != locale or waiver["translationPolicySha256"] != json_sha(policy):
        raise ValueError(f"{locale}: waiver and frozen policy do not match")
    if waiver["englishSourcePackageJsonSha256"] != json_sha(source) or waiver["anchorManifestSha256"] != json_sha(anchor):
        raise ValueError(f"{locale}: waiver is bound to another Layer 1 source")

    out = (out or PREP / f"{locale}-voice-extension-r2").resolve()
    ext = (extension_dir or PREP / f"{locale}-voice-extension-r1").resolve()
    out.mkdir(parents=True, exist_ok=True)
    route["targetCandidateCanonicalJsonSha256"] = json_sha(candidate)
    route["status"] = "approved"
    route["groups"] = [{k: v for k, v in row.items() if k != "_discard"} for row in route["groups"]]
    # Add the locale to the source identity without changing acoustic mapping evidence.
    route_path = out / "speaker-route.json"
    route_path.write_text(json.dumps(route, ensure_ascii=False, indent=2) + "\n")

    plan_path = ext / "dual-worker-plan.json"
    plan = load(plan_path)
    if plan.get("workerCount") != 2 or plan.get("batchSizePerWorker") != 8:
        raise ValueError(f"{locale}: voice plan is not two replicas at batch 8")
    plan_workers = {w["speakerId"]: w for w in plan["workers"]}
    route_rows = {row["translationGroupId"]: row for row in route["groups"]}
    units = []
    counts = {}
    for index, group in enumerate(groups):
        route_row = route_rows[group["translationGroupId"]]
        speaker_id = route_row.get("speakerId")
        worker = plan_workers.get(speaker_id)
        if not worker or route_row.get("status") != "routed":
            raise ValueError(f"{locale}: unresolved speaker mapping for {group['translationGroupId']}")
        units.append({"unitIndex": index, "translationGroupId": group["translationGroupId"],
                      "sourceUnitIds": group["sourceUnitIds"], "text": group["targetText"],
                      "outputRelativePath": f"{locale}/audio/unit-{index:04d}.wav",
                      "workerId": worker["workerId"], "speakerId": speaker_id,
                      "checkpointSha256": worker["checkpointSha256"]})
        counts[speaker_id] = counts.get(speaker_id, 0) + 1

    adapters = [ext / "speech-adapter-eric_geiger.json", ext / "speech-adapter-steve_bang_lee.json"]
    authorities = [ext / "voice-authority-eric_geiger.json", ext / "voice-authority-steve_bang_lee.json"]
    worker_rows = []
    for speaker_id in ("eric_geiger", "steve_bang_lee"):
        w = plan_workers[speaker_id]
        adapter = load(ext / f"speech-adapter-{speaker_id}.json")
        authority = load(ext / f"voice-authority-{speaker_id}.json")
        worker_rows.append({"workerId": w["workerId"], "speakerId": speaker_id,
                            "speakerKey": w["speakerKey"], "checkpointPath": w["checkpointPath"],
                            "checkpointSha256": w["checkpointSha256"],
                            "languageParameter": w["languageParameter"],
                            "adapterJsonSha256": json_sha(adapter),
                            "authorizationJsonSha256": file_sha(ext / f"voice-authority-{speaker_id}.json"),
                            "batchSize": 8})
    job = {
        "schemaVersion": "sermon-target-language-speech-job-v4-multilingual-podcast",
        "status": "prepared_for_target_language_speech", "releaseEligible": False,
        "synthesisEligible": True, "targetLocale": locale,
        "inputs": {
            "englishSourcePackage": artifact(SOURCE), "anchorManifest": artifact(ANCHOR),
            "targetLanguageCandidate": artifact(candidate_path), "targetLanguagePolicy": artifact(policy_path),
            "speakerRegistry": artifact(REGISTRY), "speakerRoute": artifact(route_path),
            "audioTimelineMap": artifact(TIMELINE),
            "audioOperationPolicies": artifact(ext / "audio-operation-policies.json"),
            "contentReviewWaiver": artifact(waiver_path),
            "voiceAuthorizations": [artifact(p) for p in authorities],
            "adapters": [artifact(p) for p in adapters]
        },
        "workers": [{"workerId": w["workerId"], "speakerId": w["speakerId"],
                     "speakerKey": w["speakerKey"], "adapterJsonSha256": w["adapterJsonSha256"],
                     "checkpointRef": f"speaker-voice://qwen3-tts-12hz-1.7b-base/{w['speakerId']}/{w['checkpointSha256']}",
                     "checkpointSha256": w["checkpointSha256"],
                     "authorizationJsonSha256": w["authorizationJsonSha256"], "batchSize": 8}
                    for w in worker_rows],
        "renderContract": {"textPolicy": "exact_machine_reviewed_target_text",
                           "ratePolicy": "natural_no_time_stretch", "playbackRate": 1,
                           "postProcessing": "none_before_measurement",
                           "videoSyncPolicy": "not_applicable_audio_only",
                           "audioTimingPolicy": "preserve_source_audio_clock_and_measure_target_duration"},
        "units": units
    }
    job_path = out / "speech-job-v4.json"
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n")
    runtime_workers = {"schemaVersion": "podcast-dual-worker-runtime-plan-v1",
                       "targetLocale": locale, "jobJsonSha256": json_sha(job),
                       "reviewWaiverJsonSha256": json_sha(waiver),
                       "workers": [{"workerId": w["workerId"], "speakerId": w["speakerId"],
                                    "speakerKey": w["speakerKey"], "checkpointPath": w["checkpointPath"],
                                    "checkpointSha256": w["checkpointSha256"],
                                    "languageParameter": w["languageParameter"]} for w in plan_workers.values()]}
    workers_path = out / "runtime-workers.json"
    workers_path.write_text(json.dumps(runtime_workers, ensure_ascii=False, indent=2) + "\n")
    summary = {"targetLocale": locale, "groups": len(units), "speakerCounts": counts,
               "workerCount": 2, "batchSizePerWorker": 8,
               "candidateCanonicalJsonSha256": json_sha(candidate),
               "policyCanonicalJsonSha256": json_sha(policy),
               "waiverCanonicalJsonSha256": json_sha(waiver),
               "routeCanonicalJsonSha256": json_sha(route), "jobCanonicalJsonSha256": json_sha(job),
               "workersFileSha256": file_sha(workers_path), "releaseEligible": False,
               "humanTranslationApproval": "waived_by_user_not_approved",
               "audioHumanReviewRequired": True, "videoSync": "not_applicable_audio_only"}
    (out / "run-binding.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return job_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locale", choices=("es", "ko"), required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--waiver", type=Path)
    parser.add_argument("--extension-dir", type=Path)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args()
    path = make(args.locale, args.candidate, args.policy, args.waiver,
                args.extension_dir, args.out_dir)
    print(path)


if __name__ == "__main__":
    main()
