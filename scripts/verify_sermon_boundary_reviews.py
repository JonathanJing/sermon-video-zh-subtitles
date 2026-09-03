#!/usr/bin/env python3
"""Verify v2 sermon-boundary review packets without treating them as approvals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import build_sermon_parallel_corpus_poc as corpus  # noqa: E402
from scripts import prepare_sermon_boundary_reviews as reviews  # noqa: E402
from scripts import verify_sermon_parallel_corpus_poc as poc_verify  # noqa: E402


def add_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any) -> None:
    checks.append({"name": name, "state": "pass" if passed else "fail", "observed": observed})


def verify_packet(
    *, video_id: str, corpus_root: Path, review_root: Path
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    review_dir = review_root / video_id
    packet_path = review_dir / "review-packet.json"
    template_path = review_dir / "operator-decision.template.json"
    markdown_path = review_dir / "review.zh.md"
    required = [packet_path, template_path, markdown_path]
    missing = [corpus.display_path(path) for path in required if not path.exists()]
    add_check(checks, "required_review_artifacts", not missing, missing)
    if missing:
        return {"videoId": video_id, "status": "failed", "checks": checks}

    packet = corpus.read_json(packet_path)
    try:
        reviews.validate_review_packet(packet)
    except (KeyError, TypeError, ValueError) as exc:
        packet_valid = False
        packet_error = str(exc)
    else:
        packet_valid = True
        packet_error = None
    add_check(checks, "review_payload_hash", packet_valid, packet_error or "match")

    cues_path = corpus_root / video_id / "normalized" / "cues.youtube-auto.jsonl"
    manifest_path = corpus_root / video_id / "manifest.json"
    source_match = (
        cues_path.exists()
        and manifest_path.exists()
        and packet["sourceBindings"]["sourceCuesSha256"] == corpus.sha256_file(cues_path)
        and packet["sourceBindings"]["sourceManifestSha256"]
        == corpus.sha256_file(manifest_path)
    )
    add_check(checks, "immutable_source_binding", source_match, {"match": source_match})

    template = corpus.read_json(template_path)
    template_safe = (
        template.get("status") == "pending_operator_input"
        and template.get("audioReviewCompleted") is False
        and not template.get("selectedStartCueId")
        and not template.get("selectedEndCueId")
        and template.get("reviewPayloadSha256") == packet.get("reviewPayloadSha256")
    )
    add_check(checks, "template_is_not_approval", template_safe, template.get("status"))

    cues = corpus.read_jsonl(cues_path) if cues_path.exists() else []
    by_id = {str(item["cueId"]): index for index, item in enumerate(cues)}
    v2 = packet.get("boundaryCandidateV2") or {}
    start_id = str(v2.get("startCueId") or "")
    end_id = str(v2.get("endCueId") or "")
    candidate_valid = (
        start_id in by_id
        and end_id in by_id
        and by_id[end_id] >= by_id[start_id]
        and start_id in {str(item["cueId"]) for item in packet.get("startContext") or []}
        and end_id in {str(item["cueId"]) for item in packet.get("endContext") or []}
    )
    add_check(
        checks,
        "v2_candidate_in_reviewed_context",
        candidate_valid,
        {"startCueId": start_id, "endCueId": end_id},
    )

    no_decision_claim = not (review_dir / "operator-decision.json").exists()
    no_approved_artifact = packet.get("approvedByHuman") is False
    add_check(
        checks,
        "no_unverified_human_approval",
        no_decision_claim and no_approved_artifact,
        {"decisionFilePresent": not no_decision_claim},
    )
    failures = [item["name"] for item in checks if item["state"] == "fail"]
    return {
        "videoId": video_id,
        "status": "pass_requires_operator_review" if not failures else "failed",
        "v1StartCueId": packet.get("boundaryCandidateV1", {}).get("startCueId"),
        "v2StartCueId": start_id,
        "v2EndCueId": end_id,
        "checks": checks,
        "failedChecks": failures,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=Path("data/raw/mariners-sermon-captions-v1"),
    )
    parser.add_argument(
        "--poc-root",
        type=Path,
        default=Path("data/derived/sermon-parallel-corpus-poc-v1"),
    )
    parser.add_argument(
        "--review-root",
        type=Path,
        default=Path("data/derived/sermon-boundary-operator-review-v2"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "data/reports/sermon-parallel-corpus-poc/boundary-review-v2-verification.json"
        ),
    )
    args = parser.parse_args()
    args.corpus_root = corpus.resolve_path(args.corpus_root)
    args.poc_root = corpus.resolve_path(args.poc_root)
    args.review_root = corpus.resolve_path(args.review_root)
    args.out = corpus.resolve_path(args.out)
    return args


def main() -> int:
    args = parse_args()
    selection = corpus.read_json(args.poc_root / "pilot-selection.json")
    video_ids = [str(item) for item in selection.get("videoIds") or []]
    packet_reports = [
        verify_packet(video_id=video_id, corpus_root=args.corpus_root, review_root=args.review_root)
        for video_id in video_ids
    ]
    secret_findings = poc_verify.scan_secret_markers(args.review_root)
    failed = [item["videoId"] for item in packet_reports if item["status"] == "failed"]
    status = (
        "pass_requires_operator_review"
        if len(video_ids) == 3 and not failed and not secret_findings
        else "failed"
    )
    report = {
        "schemaVersion": 1,
        "status": status,
        "contentScope": "sermon_only",
        "videoIds": video_ids,
        "reviews": packet_reports,
        "failedVideoIds": failed,
        "secretFindings": secret_findings,
        "approvedByHuman": False,
        "trainingEligibility": "blocked",
        "blockerMeaning": "Review packet integrity passed; source-audio operator approval is still required.",
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "verifiedAt": corpus.utc_now(),
    }
    corpus.write_json(args.out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status == "pass_requires_operator_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())
