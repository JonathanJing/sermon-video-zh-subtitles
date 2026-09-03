#!/usr/bin/env python3
"""Validate human sermon-boundary decisions and write immutable approved artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import build_sermon_parallel_corpus_poc as corpus  # noqa: E402
from scripts import prepare_sermon_boundary_reviews as reviews  # noqa: E402


def parse_approved_at(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("approvedAt is required")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("approvedAt must include an explicit timezone")
    return parsed.isoformat()


def validate_decision(
    *,
    packet: dict[str, Any],
    decision: dict[str, Any],
    cues: list[dict[str, Any]],
    actual_source_cues_sha256: str,
) -> dict[str, Any]:
    reviews.validate_review_packet(packet)
    video_id = str(packet["videoId"])
    if decision.get("status") != "approved":
        raise ValueError(f"{video_id}: operator decision status is not approved")
    if decision.get("videoId") != video_id:
        raise ValueError(f"{video_id}: decision videoId does not match review packet")
    if decision.get("contentScope") != "sermon_only":
        raise ValueError(f"{video_id}: decision contentScope must be sermon_only")
    if decision.get("reviewPayloadSha256") != packet.get("reviewPayloadSha256"):
        raise ValueError(f"{video_id}: decision is not bound to the current review packet")
    expected_source_hash = packet["sourceBindings"]["sourceCuesSha256"]
    if decision.get("sourceCuesSha256") != expected_source_hash:
        raise ValueError(f"{video_id}: decision source hash does not match review packet")
    if actual_source_cues_sha256 != expected_source_hash:
        raise ValueError(f"{video_id}: immutable source cues changed after review")
    if decision.get("audioReviewCompleted") is not True:
        raise ValueError(f"{video_id}: audioReviewCompleted must be true")
    approver = str(decision.get("approver") or "").strip()
    if not approver:
        raise ValueError(f"{video_id}: approver is required")
    approved_at = parse_approved_at(decision.get("approvedAt"))
    reason = str(decision.get("decisionReason") or "").strip()
    if not reason:
        raise ValueError(f"{video_id}: decisionReason is required")

    start_id = str(decision.get("selectedStartCueId") or "")
    end_id = str(decision.get("selectedEndCueId") or "")
    start_allowed = {str(item["cueId"]) for item in packet["startContext"]}
    end_allowed = {str(item["cueId"]) for item in packet["endContext"]}
    if start_id not in start_allowed:
        raise ValueError(f"{video_id}: selected start cue is outside reviewed context")
    if end_id not in end_allowed:
        raise ValueError(f"{video_id}: selected end cue is outside reviewed context")
    cue_index = {str(item["cueId"]): index for index, item in enumerate(cues)}
    if start_id not in cue_index or end_id not in cue_index:
        raise ValueError(f"{video_id}: selected cue does not exist in immutable source")
    if cue_index[end_id] < cue_index[start_id]:
        raise ValueError(f"{video_id}: approved boundary is reversed")
    start_cue = cues[cue_index[start_id]]
    end_cue = cues[cue_index[end_id]]
    decision_sha256 = corpus.stable_json_sha256(decision)
    return {
        "schemaVersion": 1,
        "status": "approved_human_boundary",
        "contentScope": "sermon_only",
        "videoId": video_id,
        "startCueId": start_id,
        "startMs": int(start_cue["startMs"]),
        "endCueId": end_id,
        "endMs": int(end_cue["endMs"]),
        "approvedByHuman": True,
        "requiresHumanReview": False,
        "approval": {
            "approver": approver,
            "approvedAt": approved_at,
            "audioReviewCompleted": True,
            "decisionReason": reason,
            "notes": str(decision.get("notes") or "").strip(),
            "decisionSha256": decision_sha256,
            "reviewPayloadSha256": packet["reviewPayloadSha256"],
        },
        "sourceBindings": packet["sourceBindings"],
        "trainingEligibility": "blocked",
        "remainingTrainingBlockers": [
            "source_training_rights_unconfirmed",
            "gpt_external_student_distillation_not_authorized",
            "source_english_not_human_reviewed",
            "chinese_not_human_approved",
        ],
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
        "--out-root",
        type=Path,
        default=Path("data/derived/sermon-boundary-approved-v1"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reports/sermon-parallel-corpus-poc/boundary-approval-summary.json"),
    )
    args = parser.parse_args()
    args.corpus_root = corpus.resolve_path(args.corpus_root)
    args.poc_root = corpus.resolve_path(args.poc_root)
    args.review_root = corpus.resolve_path(args.review_root)
    args.out_root = corpus.resolve_path(args.out_root)
    args.report = corpus.resolve_path(args.report)
    return args


def main() -> int:
    args = parse_args()
    selection = corpus.read_json(args.poc_root / "pilot-selection.json")
    video_ids = [str(item) for item in selection.get("videoIds") or []]
    approvals: list[dict[str, Any]] = []
    for video_id in video_ids:
        review_dir = args.review_root / video_id
        decision_path = review_dir / "operator-decision.json"
        if not decision_path.exists():
            raise SystemExit(
                f"Missing human decision for {video_id}: "
                f"{corpus.display_path(decision_path)}"
            )
        packet = corpus.read_json(review_dir / "review-packet.json")
        decision = corpus.read_json(decision_path)
        cues_path = (
            args.corpus_root / video_id / "normalized" / "cues.youtube-auto.jsonl"
        )
        cues = corpus.read_jsonl(cues_path)
        approvals.append(
            validate_decision(
                packet=packet,
                decision=decision,
                cues=cues,
                actual_source_cues_sha256=corpus.sha256_file(cues_path),
            )
        )

    # Validate every decision before writing any approval artifact.
    for approval in approvals:
        corpus.write_json(
            args.out_root / approval["videoId"] / "approved-boundary.json", approval
        )
    summary = {
        "schemaVersion": 1,
        "status": "approved_human_boundaries",
        "contentScope": "sermon_only",
        "videoIds": video_ids,
        "approvals": [
            {
                "videoId": item["videoId"],
                "startCueId": item["startCueId"],
                "endCueId": item["endCueId"],
                "approvedAt": item["approval"]["approvedAt"],
                "decisionSha256": item["approval"]["decisionSha256"],
            }
            for item in approvals
        ],
        "trainingEligibility": "blocked",
        "remainingBlockerMeaning": "Boundary approval does not approve source English, Chinese, training rights, or external-model distillation.",
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "generatedAt": corpus.utc_now(),
    }
    corpus.write_json(args.report, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
