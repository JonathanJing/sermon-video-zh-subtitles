#!/usr/bin/env python3
"""Independently verify review bundle coverage, lineage, templates, and safety state."""

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
from scripts import export_sermon_parallel_review_bundle as export  # noqa: E402
from scripts import verify_sermon_parallel_corpus_poc as poc_verify  # noqa: E402


def add_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any) -> None:
    checks.append({"name": name, "state": "pass" if passed else "fail", "observed": observed})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--poc-root",
        type=Path,
        default=Path("data/derived/sermon-parallel-corpus-poc-v1"),
    )
    parser.add_argument(
        "--review-root",
        type=Path,
        default=Path("data/derived/sermon-parallel-review-poc-v1"),
    )
    parser.add_argument(
        "--schemas-root",
        type=Path,
        default=Path("schemas/sermon-parallel-corpus-v1"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/reports/sermon-parallel-review-poc-v1/final-verification.json"),
    )
    args = parser.parse_args()
    args.poc_root = corpus.resolve_path(args.poc_root)
    args.review_root = corpus.resolve_path(args.review_root)
    args.schemas_root = corpus.resolve_path(args.schemas_root)
    args.out = corpus.resolve_path(args.out)
    return args


def main() -> int:
    args = parse_args()
    checks: list[dict[str, Any]] = []
    selection = corpus.read_json(args.poc_root / "pilot-selection.json")
    video_ids = [str(value) for value in selection.get("videoIds") or []]
    all_items = corpus.read_jsonl(args.review_root / "review-items.all.jsonl")
    all_templates = corpus.read_jsonl(
        args.review_root / "human-decisions.template.all.jsonl"
    )
    item_ids = [str(item.get("reviewItemId") or "") for item in all_items]
    add_check(
        checks,
        "review_item_count_and_unique_ids",
        len(all_items) == 117 and len(set(item_ids)) == 117,
        {"items": len(all_items), "unique": len(set(item_ids))},
    )

    invalid_items: list[str] = []
    for item in all_items:
        try:
            export.validate_review_item(item)
        except (KeyError, TypeError, ValueError) as exc:
            invalid_items.append(f"{item.get('reviewItemId')}: {exc}")
    add_check(checks, "review_payload_hashes", not invalid_items, invalid_items)

    expected_by_id: dict[str, dict[str, Any]] = {}
    queue_by_id: dict[str, dict[str, Any]] = {}
    receipts: dict[str, dict[str, Any]] = {}
    boundaries: dict[str, dict[str, Any]] = {}
    for video_id in video_ids:
        sermon_dir = args.poc_root / video_id
        for segment in corpus.read_jsonl(sermon_dir / "segments.zh.final.jsonl"):
            expected_by_id[str(segment["id"])] = segment
        for queue_item in corpus.read_jsonl(sermon_dir / "human-review-queue.jsonl"):
            queue_by_id[str(queue_item["segmentId"])] = queue_item
        receipts[video_id] = corpus.read_json(sermon_dir / "source-receipt.json")
        boundaries[video_id] = corpus.read_json(sermon_dir / "boundary-candidate.json")
    add_check(
        checks,
        "exact_poc_segment_coverage",
        set(item_ids) == set(expected_by_id),
        {"expected": len(expected_by_id), "observed": len(item_ids)},
    )

    lineage_mismatches: list[str] = []
    for item in all_items:
        item_id = str(item["reviewItemId"])
        expected = expected_by_id.get(item_id)
        queue_item = queue_by_id.get(item_id)
        if expected is None or queue_item is None:
            lineage_mismatches.append(f"{item_id}: missing source segment or queue item")
            continue
        video_id = str(item["sermonId"])
        receipt = receipts[video_id]
        boundary = boundaries[video_id]
        source = item["source"]
        candidate = item["candidate"]
        matches = (
            source["manifestSha256"] == receipt["sourceManifest"]["sha256"]
            and source["cuesSha256"] == receipt["sourceCues"]["sha256"]
            and source["textSha256"] == expected["sourceTextSha256"]
            and source["english"] == expected["en"]
            and candidate["chinese"] == expected["zh"]
            and item["priority"] == queue_item["priority"]
            and item["issues"] == queue_item["issues"]
            and item["boundary"]["boundarySha256"]
            == corpus.stable_json_sha256(boundary)
        )
        if not matches:
            lineage_mismatches.append(item_id)
    add_check(checks, "candidate_lineage_exact", not lineage_mismatches, lineage_mismatches)

    template_by_id = {str(item.get("reviewItemId") or ""): item for item in all_templates}
    template_mismatches: list[str] = []
    for item in all_items:
        item_id = str(item["reviewItemId"])
        template = template_by_id.get(item_id)
        if template is None:
            template_mismatches.append(item_id)
            continue
        safe = (
            template.get("status") == "pending_human_input"
            and template.get("audioChecked") is False
            and template.get("adjudicationComplete") is False
            and template.get("englishDecision") == "pending"
            and template.get("chineseDecision") == "pending"
            and template.get("reviewPayloadSha256") == item["reviewPayloadSha256"]
        )
        if not safe:
            template_mismatches.append(item_id)
    add_check(
        checks,
        "decision_templates_are_not_approvals",
        len(template_by_id) == 117 and not template_mismatches,
        template_mismatches,
    )

    schema_files = [
        "review-item.schema.json",
        "human-review-decision.schema.json",
        "released-segment.schema.json",
        "dataset-manifest.schema.json",
    ]
    schema_errors: list[str] = []
    for name in schema_files:
        path = args.schemas_root / name
        try:
            value = corpus.read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            schema_errors.append(f"{name}: {exc}")
            continue
        if value.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            schema_errors.append(f"{name}: unexpected JSON Schema draft")
    add_check(checks, "formal_schema_files", not schema_errors, schema_errors)

    secret_findings = poc_verify.scan_secret_markers(args.review_root)
    add_check(checks, "no_secret_material", not secret_findings, secret_findings)
    no_decisions = not any(args.review_root.rglob("human-decisions.jsonl"))
    add_check(checks, "no_unobserved_human_decisions", no_decisions, {"present": not no_decisions})

    failed = [item["name"] for item in checks if item["state"] == "fail"]
    report = {
        "schemaVersion": export.REVIEW_SCHEMA_VERSION,
        "status": "pass_requires_human_review" if not failed else "failed",
        "checks": checks,
        "failedChecks": failed,
        "totals": {
            "sermons": len(video_ids),
            "items": len(all_items),
            "high": sum(1 for item in all_items if item["priority"] == "high"),
            "normal": sum(1 for item in all_items if item["priority"] == "normal"),
            "approvedHumanDecisions": 0,
        },
        "trainingEligibility": "blocked",
        "blockerMeaning": "Review bundle integrity passed; no human content or boundary decisions were observed.",
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "verifiedAt": corpus.utc_now(),
    }
    corpus.write_json(args.out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass_requires_human_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())
