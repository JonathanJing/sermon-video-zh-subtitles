#!/usr/bin/env python3
"""Merge optional human decisions into a versioned quality catalog without granting rights."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import build_sermon_parallel_corpus_poc as corpus  # noqa: E402
from scripts import export_sermon_parallel_review_bundle as review_export  # noqa: E402


DECISION_SCHEMA_VERSION = "sermon-parallel-human-decision-v1"
RELEASED_SCHEMA_VERSION = "sermon-parallel-released-v1"
MANIFEST_SCHEMA_VERSION = "sermon-parallel-dataset-manifest-v1"
DATASET_VERSION = "sermon-parallel-poc-quality-catalog-v1"
GENERIC_NORMAL_ISSUE = "human_approval_required_for_all_poc_segments"


def parse_reviewed_at(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("reviewedAt is required")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("reviewedAt must include a timezone")
    return parsed.isoformat()


def validate_human_decision(
    item: dict[str, Any], decision: dict[str, Any]
) -> dict[str, Any]:
    review_export.validate_review_item(item)
    item_id = str(item["reviewItemId"])
    if decision.get("schemaVersion") != DECISION_SCHEMA_VERSION:
        raise ValueError(f"{item_id}: unexpected decision schemaVersion")
    if decision.get("reviewItemId") != item_id:
        raise ValueError(f"{item_id}: decision item ID mismatch")
    if decision.get("reviewPayloadSha256") != item["reviewPayloadSha256"]:
        raise ValueError(f"{item_id}: decision is bound to a different review payload")
    status = str(decision.get("status") or "")
    if status not in {"approved", "changes_required", "rejected"}:
        raise ValueError(f"{item_id}: decision status is not final")
    if not str(decision.get("reviewer") or "").strip():
        raise ValueError(f"{item_id}: reviewer is required")
    if not str(decision.get("reviewerRole") or "").strip():
        raise ValueError(f"{item_id}: reviewerRole is required")
    normalized = dict(decision)
    normalized["reviewedAt"] = parse_reviewed_at(decision.get("reviewedAt"))
    if not isinstance(decision.get("materialErrorTypes"), list):
        raise ValueError(f"{item_id}: materialErrorTypes must be a list")
    allowed_errors = {
        "source_asr",
        "boundary",
        "omission",
        "unsupported_addition",
        "meaning",
        "negation",
        "number",
        "scripture",
        "proper_noun",
        "theology_term",
        "readability",
        "other",
    }
    if not set(decision["materialErrorTypes"]) <= allowed_errors:
        raise ValueError(f"{item_id}: unknown material error type")

    if status == "approved":
        required_true = (
            "audioChecked",
            "scriptureChecked",
            "properNounsChecked",
            "numbersChecked",
            "adjudicationComplete",
        )
        if not all(decision.get(field) is True for field in required_true):
            raise ValueError(f"{item_id}: approved decision lacks required checks")
        if decision.get("englishDecision") not in {"keep", "corrected"}:
            raise ValueError(f"{item_id}: approved English decision is invalid")
        if decision.get("chineseDecision") not in {"keep", "corrected"}:
            raise ValueError(f"{item_id}: approved Chinese decision is invalid")
        approved_en = str(decision.get("approvedEnglish") or "").strip()
        approved_zh = str(decision.get("approvedChinese") or "").strip()
        if not approved_en or not approved_zh or not corpus.CHINESE_RE.search(approved_zh):
            raise ValueError(f"{item_id}: approved text is empty or Chinese is invalid")
        if corpus.MARKDOWN_RE.search(approved_zh):
            raise ValueError(f"{item_id}: approved Chinese contains Markdown")
        if decision["englishDecision"] == "keep" and approved_en != item["source"]["english"]:
            raise ValueError(f"{item_id}: keep English does not match source candidate")
        if decision["chineseDecision"] == "keep" and approved_zh != item["candidate"]["chinese"]:
            raise ValueError(f"{item_id}: keep Chinese does not match model candidate")
    normalized["decisionSha256"] = corpus.stable_json_sha256(decision)
    return normalized


def is_automatic_silver_candidate(item: dict[str, Any]) -> bool:
    substantive = [value for value in item["issues"] if value != GENERIC_NORMAL_ISSUE]
    return (
        item["priority"] == "normal"
        and not substantive
        and item["boundary"]["approvedByHuman"] is True
        and item["boundary"]["status"] == "approved_human_boundary"
    )


def released_segment(
    item: dict[str, Any], decision: dict[str, Any] | None
) -> dict[str, Any]:
    review_export.validate_review_item(item)
    normalized_decision = (
        validate_human_decision(item, decision) if decision is not None else None
    )
    boundary_approved = (
        item["boundary"]["approvedByHuman"] is True
        and item["boundary"]["status"] == "approved_human_boundary"
    )
    source_en = item["source"]["english"]
    candidate_zh = item["candidate"]["chinese"]
    quality_tier = "isolated_reference"
    review_status = "pending_human"
    final_en = source_en
    final_zh = candidate_zh
    if normalized_decision is not None:
        status = normalized_decision["status"]
        if status == "approved":
            final_en = str(normalized_decision["approvedEnglish"]).strip()
            final_zh = str(normalized_decision["approvedChinese"]).strip()
            review_status = "human_approved"
            quality_tier = (
                "gold_human_reviewed"
                if boundary_approved
                else "human_reviewed_boundary_blocked"
            )
        elif status == "changes_required":
            review_status = "changes_required"
        else:
            review_status = "rejected"
    elif is_automatic_silver_candidate(item):
        quality_tier = "silver_automatic_candidate"

    blockers = [
        "source_training_rights_unconfirmed",
        "gpt_external_student_distillation_not_authorized",
    ]
    if not boundary_approved:
        blockers.append("sermon_boundary_not_human_approved")
    if quality_tier == "silver_automatic_candidate":
        blockers.append("silver_precision_calibration_not_passed")
    elif quality_tier not in {"gold_human_reviewed", "human_reviewed_boundary_blocked"}:
        blockers.extend(
            ["source_english_not_human_reviewed", "chinese_not_human_approved"]
        )
    if review_status == "rejected":
        blockers.append("human_review_rejected")
    result = {
        "schemaVersion": RELEASED_SCHEMA_VERSION,
        "id": item["segmentId"],
        "sermonId": item["sermonId"],
        "split": item["split"],
        "startMs": item["source"]["startMs"],
        "endMs": item["source"]["endMs"],
        "cueIds": item["source"]["cueIds"],
        "en": final_en,
        "zh": final_zh,
        "sourceEnglishSha256": item["source"]["textSha256"],
        "releasedEnglishSha256": corpus.sha256_bytes(final_en.encode("utf-8")),
        "releasedChineseSha256": corpus.sha256_bytes(final_zh.encode("utf-8")),
        "reviewPayloadSha256": item["reviewPayloadSha256"],
        "qualityTier": quality_tier,
        "reviewStatus": review_status,
        "trainingEligibility": "blocked",
        "trainingBlockers": list(dict.fromkeys(blockers)),
        "provenance": {
            "sourceManifestSha256": item["source"]["manifestSha256"],
            "sourceCuesSha256": item["source"]["cuesSha256"],
            "boundarySha256": item["boundary"]["boundarySha256"],
            "teacher": item["candidate"]["teacher"],
            "humanDecisionSha256": (
                normalized_decision["decisionSha256"]
                if normalized_decision is not None
                else None
            ),
        },
    }
    validate_released_segment(result)
    return result


def validate_released_segment(item: dict[str, Any]) -> None:
    if item.get("schemaVersion") != RELEASED_SCHEMA_VERSION:
        raise ValueError("Unexpected released segment schemaVersion")
    if item.get("trainingEligibility") != "blocked":
        raise ValueError("POC quality catalog cannot grant training eligibility")
    if not item.get("trainingBlockers"):
        raise ValueError("Blocked segment must list training blockers")
    if item.get("qualityTier") == "gold_human_reviewed" and item.get("reviewStatus") != "human_approved":
        raise ValueError("Gold segment lacks human approval")
    if item.get("qualityTier") == "silver_automatic_candidate" and item.get("reviewStatus") != "pending_human":
        raise ValueError("Silver automatic candidate has inconsistent review status")
    if item.get("releasedEnglishSha256") != corpus.sha256_bytes(
        str(item.get("en") or "").encode("utf-8")
    ):
        raise ValueError("Released English hash mismatch")
    if item.get("releasedChineseSha256") != corpus.sha256_bytes(
        str(item.get("zh") or "").encode("utf-8")
    ):
        raise ValueError("Released Chinese hash mismatch")


def calibration_summaries(
    review_items: list[dict[str, Any]], decisions: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    normal_items = [item for item in review_items if item["priority"] == "normal"]
    reviewed_normal = [
        decisions[item["reviewItemId"]]
        for item in normal_items
        if item["reviewItemId"] in decisions
    ]
    normal_complete = len(reviewed_normal) == len(normal_items)
    normal_nonapproved = sum(
        1 for decision in reviewed_normal if decision.get("status") != "approved"
    )
    normal_material_errors = sum(
        1 for decision in reviewed_normal if decision.get("materialErrorTypes")
    )
    silver_gate = (
        "pending"
        if not normal_complete
        else "pass"
        if normal_nonapproved == 0 and normal_material_errors == 0
        else "fail"
    )

    material_error_ids = {
        item_id
        for item_id, decision in decisions.items()
        if decision.get("materialErrorTypes")
    }
    high_ids = {
        str(item["reviewItemId"])
        for item in review_items
        if item["priority"] == "high"
    }
    material_high = len(material_error_ids & high_ids)
    material_normal = len(material_error_ids - high_ids)
    all_complete = len(decisions) == len(review_items)
    risk_gate = (
        "pending"
        if not all_complete
        else "pass"
        if material_normal == 0
        else "fail"
    )
    return (
        {
            "status": silver_gate,
            "normalExpected": len(normal_items),
            "normalReviewed": len(reviewed_normal),
            "normalApproved": len(reviewed_normal) - normal_nonapproved,
            "normalNonApproved": normal_nonapproved,
            "normalWithMaterialError": normal_material_errors,
        },
        {
            "status": risk_gate,
            "segmentsExpected": len(review_items),
            "segmentsReviewed": len(decisions),
            "materialErrorSegments": len(material_error_ids),
            "materialErrorSegmentsHigh": material_high,
            "materialErrorSegmentsNormal": material_normal,
            "highPriorityRecall": (
                round(material_high / len(material_error_ids), 6)
                if material_error_ids
                else None
            ),
        },
    )


def load_decisions(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    rows = corpus.read_jsonl(path)
    by_id = {str(item.get("reviewItemId") or ""): item for item in rows}
    if "" in by_id or len(by_id) != len(rows):
        raise RuntimeError("Human decisions contain missing or duplicate review item IDs")
    return by_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--review-root",
        type=Path,
        default=Path("data/derived/sermon-parallel-review-poc-v1"),
    )
    parser.add_argument(
        "--decisions",
        type=Path,
        default=Path("data/derived/sermon-parallel-review-poc-v1/human-decisions.jsonl"),
    )
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=Path("data/reports/sermon-parallel-corpus-splits-v1/split-manifest.json"),
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=Path("data/derived/sermon-parallel-quality-catalog-poc-v1"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reports/sermon-parallel-quality-catalog-poc-v1/summary.json"),
    )
    args = parser.parse_args()
    args.review_root = corpus.resolve_path(args.review_root)
    args.decisions = corpus.resolve_path(args.decisions)
    args.split_manifest = corpus.resolve_path(args.split_manifest)
    args.out_root = corpus.resolve_path(args.out_root)
    args.report = corpus.resolve_path(args.report)
    return args


def main() -> int:
    args = parse_args()
    review_items = corpus.read_jsonl(args.review_root / "review-items.all.jsonl")
    review_by_id = {str(item["reviewItemId"]): item for item in review_items}
    decisions = load_decisions(args.decisions)
    unknown_decisions = sorted(set(decisions) - set(review_by_id))
    if unknown_decisions:
        raise RuntimeError(f"Decisions reference unknown review items: {unknown_decisions}")
    released = [
        released_segment(item, decisions.get(str(item["reviewItemId"])))
        for item in review_items
    ]
    args.out_root.mkdir(parents=True, exist_ok=True)
    released_path = args.out_root / "released-segments.jsonl"
    corpus.write_jsonl(released_path, released)

    quality_counts = Counter(item["qualityTier"] for item in released)
    review_counts = Counter(item["reviewStatus"] for item in released)
    decision_statuses = Counter(str(item["status"]) for item in decisions.values())
    material_errors = Counter(
        value for decision in decisions.values() for value in decision.get("materialErrorTypes") or []
    )
    silver_calibration, risk_calibration = calibration_summaries(
        review_items, decisions
    )
    counts = {
        "total": len(released),
        "isolatedReference": quality_counts.get("isolated_reference", 0),
        "silverCandidate": quality_counts.get("silver_automatic_candidate", 0),
        "humanBoundaryBlocked": quality_counts.get("human_reviewed_boundary_blocked", 0),
        "gold": quality_counts.get("gold_human_reviewed", 0),
        "pending": review_counts.get("pending_human", 0),
        "rejected": review_counts.get("rejected", 0),
    }
    split_manifest_sha = corpus.sha256_file(args.split_manifest)
    manifest = {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "datasetVersion": DATASET_VERSION,
        "status": "quality_catalog_training_blocked",
        "sourceBundleSha256": corpus.sha256_file(
            args.review_root / "review-items.all.jsonl"
        ),
        "releasedSegmentsSha256": corpus.sha256_file(released_path),
        "counts": counts,
        "splitManifestSha256": split_manifest_sha,
        "trainingEligibility": "blocked",
        "blockingReasons": [
            "source_training_rights_unconfirmed",
            "gpt_external_student_distillation_not_authorized",
            *(
                []
                if quality_counts.get("gold_human_reviewed", 0) == len(released)
                else ["human_quality_review_incomplete"]
            ),
        ],
        "generatedAt": corpus.utc_now(),
    }
    corpus.write_json(args.out_root / "dataset-manifest.json", manifest)
    report = {
        **manifest,
        "decisionCoverage": {
            "observed": len(decisions),
            "expected": len(review_items),
            "statusCounts": dict(sorted(decision_statuses.items())),
            "materialErrorCounts": dict(sorted(material_errors.items())),
        },
        "automaticSilverCalibration": silver_calibration,
        "riskRuleCalibration": risk_calibration,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }
    corpus.write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
