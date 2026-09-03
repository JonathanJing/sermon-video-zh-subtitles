#!/usr/bin/env python3
"""Independently verify POC quality tiers, review lineage, hashes, and blockers."""

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
from scripts import verify_sermon_parallel_corpus_poc as poc_verify  # noqa: E402


RELEASED_SCHEMA_VERSION = "sermon-parallel-released-v1"
MANIFEST_SCHEMA_VERSION = "sermon-parallel-dataset-manifest-v1"
DECISION_SCHEMA_VERSION = "sermon-parallel-human-decision-v1"
DATASET_VERSION = "sermon-parallel-poc-quality-catalog-v1"
GENERIC_NORMAL_ISSUE = "human_approval_required_for_all_poc_segments"
RIGHTS_BLOCKERS = {
    "source_training_rights_unconfirmed",
    "gpt_external_student_distillation_not_authorized",
}
ALLOWED_MATERIAL_ERRORS = {
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


def add_check(
    checks: list[dict[str, Any]], name: str, passed: bool, observed: Any
) -> None:
    checks.append(
        {"name": name, "state": "pass" if passed else "fail", "observed": observed}
    )


def boundary_is_approved(item: dict[str, Any]) -> bool:
    boundary = item.get("boundary") or {}
    return (
        boundary.get("approvedByHuman") is True
        and boundary.get("status") == "approved_human_boundary"
    )


def automatic_silver_candidate(item: dict[str, Any]) -> bool:
    issues = item.get("issues") or []
    substantive = [value for value in issues if value != GENERIC_NORMAL_ISSUE]
    return (
        item.get("priority") == "normal"
        and not substantive
        and boundary_is_approved(item)
    )


def expected_release_state(
    item: dict[str, Any], decision: dict[str, Any] | None
) -> dict[str, Any]:
    quality_tier = "isolated_reference"
    review_status = "pending_human"
    final_en = str(item["source"]["english"])
    final_zh = str(item["candidate"]["chinese"])
    decision_sha: str | None = None

    if decision is not None:
        decision_sha = corpus.stable_json_sha256(decision)
        status = decision.get("status")
        if status == "approved":
            review_status = "human_approved"
            final_en = str(decision.get("approvedEnglish") or "").strip()
            final_zh = str(decision.get("approvedChinese") or "").strip()
            quality_tier = (
                "gold_human_reviewed"
                if boundary_is_approved(item)
                else "human_reviewed_boundary_blocked"
            )
        elif status == "changes_required":
            review_status = "changes_required"
        elif status == "rejected":
            review_status = "rejected"
    elif automatic_silver_candidate(item):
        quality_tier = "silver_automatic_candidate"

    blockers = set(RIGHTS_BLOCKERS)
    if not boundary_is_approved(item):
        blockers.add("sermon_boundary_not_human_approved")
    if quality_tier == "silver_automatic_candidate":
        blockers.add("silver_precision_calibration_not_passed")
    elif quality_tier not in {
        "gold_human_reviewed",
        "human_reviewed_boundary_blocked",
    }:
        blockers.update(
            {"source_english_not_human_reviewed", "chinese_not_human_approved"}
        )
    if review_status == "rejected":
        blockers.add("human_review_rejected")
    return {
        "qualityTier": quality_tier,
        "reviewStatus": review_status,
        "en": final_en,
        "zh": final_zh,
        "humanDecisionSha256": decision_sha,
        "trainingBlockers": blockers,
    }


def validate_decision_binding(
    item: dict[str, Any], decision: dict[str, Any]
) -> list[str]:
    item_id = str(item.get("reviewItemId") or "")
    errors: list[str] = []
    if decision.get("schemaVersion") != DECISION_SCHEMA_VERSION:
        errors.append("schemaVersion")
    if decision.get("reviewItemId") != item_id:
        errors.append("reviewItemId")
    if decision.get("reviewPayloadSha256") != item.get("reviewPayloadSha256"):
        errors.append("reviewPayloadSha256")
    status = decision.get("status")
    if status not in {"approved", "changes_required", "rejected"}:
        errors.append("status")
    if not str(decision.get("reviewer") or "").strip():
        errors.append("reviewer")
    if not str(decision.get("reviewerRole") or "").strip():
        errors.append("reviewerRole")
    try:
        reviewed_at = datetime.fromisoformat(
            str(decision.get("reviewedAt") or "").replace("Z", "+00:00")
        )
        if reviewed_at.tzinfo is None:
            errors.append("reviewedAtTimezone")
    except ValueError:
        errors.append("reviewedAt")
    material_errors = decision.get("materialErrorTypes")
    if (
        not isinstance(material_errors, list)
        or len(material_errors) != len(set(material_errors or []))
        or not set(material_errors or []) <= ALLOWED_MATERIAL_ERRORS
    ):
        errors.append("materialErrorTypes")

    if status == "approved":
        required_true = (
            "audioChecked",
            "scriptureChecked",
            "properNounsChecked",
            "numbersChecked",
            "adjudicationComplete",
        )
        if not all(decision.get(field) is True for field in required_true):
            errors.append("requiredApprovalChecks")
        if decision.get("englishDecision") not in {"keep", "corrected"}:
            errors.append("englishDecision")
        if decision.get("chineseDecision") not in {"keep", "corrected"}:
            errors.append("chineseDecision")
        approved_en = str(decision.get("approvedEnglish") or "").strip()
        approved_zh = str(decision.get("approvedChinese") or "").strip()
        if not approved_en:
            errors.append("approvedEnglish")
        if not approved_zh or not corpus.CHINESE_RE.search(approved_zh):
            errors.append("approvedChinese")
        if corpus.MARKDOWN_RE.search(approved_zh):
            errors.append("approvedChineseMarkdown")
        if (
            decision.get("englishDecision") == "keep"
            and approved_en != item["source"]["english"]
        ):
            errors.append("keepEnglishMismatch")
        if (
            decision.get("chineseDecision") == "keep"
            and approved_zh != item["candidate"]["chinese"]
        ):
            errors.append("keepChineseMismatch")
    return errors


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
        default=Path(
            "data/derived/sermon-parallel-review-poc-v1/human-decisions.jsonl"
        ),
    )
    parser.add_argument(
        "--quality-root",
        type=Path,
        default=Path("data/derived/sermon-parallel-quality-catalog-poc-v1"),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path(
            "data/reports/sermon-parallel-quality-catalog-poc-v1/summary.json"
        ),
    )
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=Path(
            "data/reports/sermon-parallel-corpus-splits-v1/split-manifest.json"
        ),
    )
    parser.add_argument(
        "--schemas-root",
        type=Path,
        default=Path("schemas/sermon-parallel-corpus-v1"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "data/reports/sermon-parallel-quality-catalog-poc-v1/final-verification.json"
        ),
    )
    args = parser.parse_args()
    for field in (
        "review_root",
        "decisions",
        "quality_root",
        "summary",
        "split_manifest",
        "schemas_root",
        "out",
    ):
        setattr(args, field, corpus.resolve_path(getattr(args, field)))
    return args


def main() -> int:
    args = parse_args()
    checks: list[dict[str, Any]] = []
    review_path = args.review_root / "review-items.all.jsonl"
    released_path = args.quality_root / "released-segments.jsonl"
    manifest_path = args.quality_root / "dataset-manifest.json"
    review_items = corpus.read_jsonl(review_path)
    released = corpus.read_jsonl(released_path)
    manifest = corpus.read_json(manifest_path)
    summary = corpus.read_json(args.summary)
    decisions_rows = (
        corpus.read_jsonl(args.decisions) if args.decisions.exists() else []
    )

    review_by_id = {
        str(item.get("reviewItemId") or ""): item for item in review_items
    }
    released_by_id = {str(item.get("id") or ""): item for item in released}
    decisions = {
        str(item.get("reviewItemId") or ""): item for item in decisions_rows
    }
    add_check(
        checks,
        "exact_unique_review_and_release_coverage",
        len(review_items) == 117
        and len(review_by_id) == 117
        and "" not in review_by_id
        and len(released) == 117
        and len(released_by_id) == 117
        and "" not in released_by_id
        and set(review_by_id) == set(released_by_id),
        {
            "reviewRows": len(review_items),
            "uniqueReviewIds": len(review_by_id),
            "releasedRows": len(released),
            "uniqueReleasedIds": len(released_by_id),
        },
    )
    add_check(
        checks,
        "unique_known_human_decisions",
        len(decisions) == len(decisions_rows)
        and "" not in decisions
        and set(decisions) <= set(review_by_id),
        {
            "rows": len(decisions_rows),
            "unique": len(decisions),
            "unknown": sorted(set(decisions) - set(review_by_id)),
        },
    )

    decision_errors: list[str] = []
    for item_id, decision in decisions.items():
        if item_id not in review_by_id:
            continue
        errors = validate_decision_binding(review_by_id[item_id], decision)
        if errors:
            decision_errors.append(f"{item_id}: {','.join(errors)}")
    add_check(
        checks,
        "human_decisions_are_final_and_hash_bound",
        not decision_errors,
        decision_errors,
    )

    lineage_errors: list[str] = []
    tier_errors: list[str] = []
    safety_errors: list[str] = []
    for item_id, item in review_by_id.items():
        output = released_by_id.get(item_id)
        if output is None:
            continue
        expected = expected_release_state(item, decisions.get(item_id))
        source = item["source"]
        candidate = item["candidate"]
        provenance = output.get("provenance") or {}
        lineage_ok = (
            output.get("schemaVersion") == RELEASED_SCHEMA_VERSION
            and output.get("id") == item["segmentId"]
            and output.get("sermonId") == item["sermonId"]
            and output.get("split") == item["split"]
            and output.get("startMs") == source["startMs"]
            and output.get("endMs") == source["endMs"]
            and output.get("cueIds") == source["cueIds"]
            and output.get("reviewPayloadSha256") == item["reviewPayloadSha256"]
            and output.get("sourceEnglishSha256") == source["textSha256"]
            and provenance.get("sourceManifestSha256") == source["manifestSha256"]
            and provenance.get("sourceCuesSha256") == source["cuesSha256"]
            and provenance.get("boundarySha256")
            == item["boundary"]["boundarySha256"]
            and provenance.get("teacher") == candidate["teacher"]
        )
        if not lineage_ok:
            lineage_errors.append(item_id)
        tier_ok = (
            output.get("qualityTier") == expected["qualityTier"]
            and output.get("reviewStatus") == expected["reviewStatus"]
            and output.get("en") == expected["en"]
            and output.get("zh") == expected["zh"]
            and provenance.get("humanDecisionSha256")
            == expected["humanDecisionSha256"]
            and set(output.get("trainingBlockers") or [])
            == expected["trainingBlockers"]
            and output.get("releasedEnglishSha256")
            == corpus.sha256_bytes(str(output.get("en") or "").encode("utf-8"))
            and output.get("releasedChineseSha256")
            == corpus.sha256_bytes(str(output.get("zh") or "").encode("utf-8"))
        )
        if not tier_ok:
            tier_errors.append(item_id)
        safe = (
            output.get("trainingEligibility") == "blocked"
            and RIGHTS_BLOCKERS <= set(output.get("trainingBlockers") or [])
            and not (
                output.get("qualityTier") == "gold_human_reviewed"
                and item_id not in decisions
            )
        )
        if not safe:
            safety_errors.append(item_id)
    add_check(checks, "released_lineage_exact", not lineage_errors, lineage_errors)
    add_check(checks, "quality_tiers_exact", not tier_errors, tier_errors)
    add_check(
        checks,
        "rights_and_distillation_blockers_preserved",
        not safety_errors,
        safety_errors,
    )

    split_manifest = corpus.read_json(args.split_manifest)
    split_by_video = {
        str(item.get("videoId") or ""): item.get("split")
        for item in split_manifest.get("assignments") or []
    }
    sermon_ids = {str(item.get("sermonId") or "") for item in released}
    split_errors = [
        video_id
        for video_id in sorted(sermon_ids)
        if split_by_video.get(video_id) != "poc"
    ]
    add_check(
        checks,
        "whole_sermon_poc_split_binding",
        len(sermon_ids) == 3
        and not split_errors
        and all(item.get("split") == "poc" for item in released),
        {"sermons": sorted(sermon_ids), "mismatches": split_errors},
    )

    quality_counts = Counter(item.get("qualityTier") for item in released)
    review_counts = Counter(item.get("reviewStatus") for item in released)
    expected_counts = {
        "total": len(released),
        "isolatedReference": quality_counts.get("isolated_reference", 0),
        "silverCandidate": quality_counts.get("silver_automatic_candidate", 0),
        "humanBoundaryBlocked": quality_counts.get(
            "human_reviewed_boundary_blocked", 0
        ),
        "gold": quality_counts.get("gold_human_reviewed", 0),
        "pending": review_counts.get("pending_human", 0),
        "rejected": review_counts.get("rejected", 0),
    }
    expected_manifest_blockers = set(RIGHTS_BLOCKERS)
    if expected_counts["gold"] != expected_counts["total"]:
        expected_manifest_blockers.add("human_quality_review_incomplete")
    manifest_ok = (
        manifest.get("schemaVersion") == MANIFEST_SCHEMA_VERSION
        and manifest.get("datasetVersion") == DATASET_VERSION
        and manifest.get("status") == "quality_catalog_training_blocked"
        and manifest.get("trainingEligibility") == "blocked"
        and manifest.get("sourceBundleSha256") == corpus.sha256_file(review_path)
        and manifest.get("releasedSegmentsSha256")
        == corpus.sha256_file(released_path)
        and manifest.get("splitManifestSha256")
        == corpus.sha256_file(args.split_manifest)
        and manifest.get("counts") == expected_counts
        and set(manifest.get("blockingReasons") or [])
        == expected_manifest_blockers
    )
    add_check(
        checks,
        "dataset_manifest_exact",
        manifest_ok,
        {
            "counts": manifest.get("counts"),
            "expectedCounts": expected_counts,
            "blockingReasons": manifest.get("blockingReasons"),
        },
    )

    manifest_fields = {
        "schemaVersion",
        "datasetVersion",
        "status",
        "sourceBundleSha256",
        "releasedSegmentsSha256",
        "counts",
        "splitManifestSha256",
        "trainingEligibility",
        "blockingReasons",
        "generatedAt",
    }
    summary_ok = all(summary.get(key) == manifest.get(key) for key in manifest_fields)
    summary_ok = summary_ok and summary.get("apiKeyMaterialIncluded") is False
    summary_ok = summary_ok and summary.get("secretResourceNamesIncluded") is False
    summary_coverage = summary.get("decisionCoverage") or {}
    summary_ok = summary_ok and summary_coverage.get("observed") == len(decisions)
    summary_ok = summary_ok and summary_coverage.get("expected") == len(review_items)
    normal_items = [item for item in review_items if item.get("priority") == "normal"]
    normal_decisions = [
        decisions[str(item["reviewItemId"])]
        for item in normal_items
        if str(item["reviewItemId"]) in decisions
    ]
    normal_nonapproved = sum(
        1 for decision in normal_decisions if decision.get("status") != "approved"
    )
    normal_material = sum(
        1 for decision in normal_decisions if decision.get("materialErrorTypes")
    )
    expected_silver_status = (
        "pending"
        if len(normal_decisions) != len(normal_items)
        else "pass"
        if normal_nonapproved == 0 and normal_material == 0
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
        if item.get("priority") == "high"
    }
    expected_silver = {
        "status": expected_silver_status,
        "normalExpected": len(normal_items),
        "normalReviewed": len(normal_decisions),
        "normalApproved": len(normal_decisions) - normal_nonapproved,
        "normalNonApproved": normal_nonapproved,
        "normalWithMaterialError": normal_material,
    }
    expected_risk = {
        "status": (
            "pending"
            if len(decisions) != len(review_items)
            else "pass"
            if not (material_error_ids - high_ids)
            else "fail"
        ),
        "segmentsExpected": len(review_items),
        "segmentsReviewed": len(decisions),
        "materialErrorSegments": len(material_error_ids),
        "materialErrorSegmentsHigh": len(material_error_ids & high_ids),
        "materialErrorSegmentsNormal": len(material_error_ids - high_ids),
        "highPriorityRecall": (
            round(len(material_error_ids & high_ids) / len(material_error_ids), 6)
            if material_error_ids
            else None
        ),
    }
    summary_ok = summary_ok and summary.get("automaticSilverCalibration") == expected_silver
    summary_ok = summary_ok and summary.get("riskRuleCalibration") == expected_risk
    add_check(
        checks,
        "summary_matches_manifest_and_decision_coverage",
        summary_ok,
        {
            "observedDecisions": summary_coverage.get("observed"),
            "expectedDecisions": summary_coverage.get("expected"),
            "silverCalibration": summary.get("automaticSilverCalibration"),
            "riskCalibration": summary.get("riskRuleCalibration"),
        },
    )

    schema_errors: list[str] = []
    for name, expected_version in (
        ("released-segment.schema.json", RELEASED_SCHEMA_VERSION),
        ("dataset-manifest.schema.json", MANIFEST_SCHEMA_VERSION),
    ):
        try:
            schema = corpus.read_json(args.schemas_root / name)
        except (OSError, json.JSONDecodeError) as exc:
            schema_errors.append(f"{name}: {exc}")
            continue
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            schema_errors.append(f"{name}: JSON Schema draft")
        if schema.get("properties", {}).get("schemaVersion", {}).get("const") != expected_version:
            schema_errors.append(f"{name}: schemaVersion")
    add_check(checks, "formal_release_schemas", not schema_errors, schema_errors)

    secret_findings = poc_verify.scan_secret_markers(args.quality_root)
    secret_findings.extend(poc_verify.scan_secret_markers(args.summary.parent))
    add_check(checks, "no_secret_material", not secret_findings, secret_findings)

    failed = [item["name"] for item in checks if item["state"] == "fail"]
    report = {
        "schemaVersion": "sermon-parallel-quality-catalog-verification-v1",
        "status": "pass_training_blocked" if not failed else "failed",
        "checks": checks,
        "failedChecks": failed,
        "totals": {
            "sermons": len(sermon_ids),
            "segments": len(released),
            "humanDecisions": len(decisions),
            **expected_counts,
        },
        "trainingEligibility": "blocked",
        "blockerMeaning": (
            "Catalog integrity passed; quality tiers do not grant source rights or "
            "authorization to distill OpenAI outputs into an external student model."
        ),
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "verifiedAt": corpus.utc_now(),
    }
    corpus.write_json(args.out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass_training_blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
