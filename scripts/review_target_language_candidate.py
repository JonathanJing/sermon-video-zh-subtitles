#!/usr/bin/env python3
"""Prepare a human translation worksheet and admit its reviewed candidate.

This command never supplies an approval decision. A reviewer must fill every
group decision and evidence field in the worksheet before `approve` can emit
a new immutable candidate and its separate receipt.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

try:
    from scripts import prepare_target_language_speech_job as handoff
    from scripts import sermon_sentence_interpretation as interpretation
except ImportError:  # Direct execution via ``python scripts/...``.
    import prepare_target_language_speech_job as handoff
    import sermon_sentence_interpretation as interpretation


WORKSHEET_SCHEMA = "sermon-target-language-human-review-worksheet-v1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _load(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(result, dict), f"Expected JSON object: {path}")
    return result


def build_worksheet(source_package: dict[str, Any], anchor: dict[str, Any],
                    candidate: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Expose all source, coverage, machine and language evidence per group."""
    handoff._validate_schema(candidate, "sermon-target-language-candidate-v2.schema.json", "target candidate")
    handoff.validate_target_candidate(source_package, anchor, candidate, require_human_approval=False)
    handoff.validate_policy_binding(candidate, policy)
    human = candidate["humanReview"]
    _require(candidate["status"] == "machine_review_pass_human_review_pending"
             and human["translation"] == "pending"
             and human["reviewer"] is None and human["reviewedAt"] is None
             and not human["reviewedGroupIds"],
             "Worksheet requires a machine-reviewed candidate with human review still pending")
    units = {unit["sourceUnitId"]: unit for unit in anchor["sourceUnits"]}
    return {
        "schemaVersion": WORKSHEET_SCHEMA,
        "decision": "pending",
        "targetLocale": candidate["targetLocale"],
        "englishSourcePackageJsonSha256": interpretation.json_sha256(source_package),
        "anchorManifestJsonSha256": interpretation.json_sha256(anchor),
        "translationPolicySha256": candidate["translationPolicySha256"],
        "candidateJsonSha256": interpretation.json_sha256(candidate),
        "reviewer": None,
        "reviewedAt": None,
        "groupReviews": [{
            "translationGroupId": group["translationGroupId"],
            "sourceUnits": [{"sourceUnitId": unit_id, "english": units[unit_id]["english"]}
                            for unit_id in group["sourceUnitIds"]],
            "targetUtterances": group["targetUtterances"],
            "targetText": group["targetText"],
            "coverage": group["coverage"],
            "semanticReview": group["semanticReview"],
            "languageReview": group["languageReview"],
            "decision": "pending",
            "evidence": None,
        } for group in candidate["groups"]],
    }


def approve_worksheet(source_package: dict[str, Any], anchor: dict[str, Any],
                      candidate: dict[str, Any], policy: dict[str, Any],
                      worksheet: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    expected = build_worksheet(source_package, anchor, candidate, policy)
    for key in ("schemaVersion", "targetLocale", "englishSourcePackageJsonSha256",
                "anchorManifestJsonSha256", "translationPolicySha256", "candidateJsonSha256"):
        _require(worksheet.get(key) == expected[key], f"Human worksheet identity changed: {key}")
    reviewer = worksheet.get("reviewer")
    reviewed_at = worksheet.get("reviewedAt")
    _require(worksheet.get("decision") == "approved"
             and isinstance(reviewer, str) and reviewer.strip()
             and handoff._reviewed_at(reviewed_at),
             "Human worksheet requires an approved decision, reviewer, and timezone-aware review time")
    rows = worksheet.get("groupReviews")
    _require(isinstance(rows, list) and len(rows) == len(expected["groupReviews"]),
             "Human worksheet must review every group")
    for row, frozen in zip(rows, expected["groupReviews"]):
        _require(isinstance(row, dict) and set(row) == set(frozen)
                 and all(row[key] == frozen[key] for key in frozen if key not in {"decision", "evidence"}),
                 "Human worksheet source or target evidence changed")
        _require(row["decision"] == "approved"
                 and isinstance(row["evidence"], str) and row["evidence"].strip(),
                 "Human worksheet has an unapproved or unexplained group")
    approved = copy.deepcopy(candidate)
    group_ids = [group["translationGroupId"] for group in approved["groups"]]
    approved["status"] = "human_translation_approved"
    approved["humanReview"] = {
        "translation": "approved", "reviewer": reviewer.strip(), "reviewedAt": reviewed_at,
        "reviewedGroupIds": group_ids,
    }
    handoff._validate_schema(approved, "sermon-target-language-candidate-v2.schema.json", "approved candidate")
    handoff.validate_target_candidate(source_package, anchor, approved)
    receipt = {
        "schemaVersion": handoff.HUMAN_REVIEW_RECEIPT_SCHEMA,
        "decision": "approved",
        "targetLocale": approved["targetLocale"],
        "englishSourcePackageJsonSha256": expected["englishSourcePackageJsonSha256"],
        "anchorManifestJsonSha256": expected["anchorManifestJsonSha256"],
        "translationPolicySha256": expected["translationPolicySha256"],
        "candidateJsonSha256": interpretation.json_sha256(approved),
        "reviewer": reviewer.strip(),
        "reviewedAt": reviewed_at,
        "reviewedGroupIds": group_ids,
        "groupReviews": [{
            "translationGroupId": row["translationGroupId"],
            "decision": row["decision"], "evidence": row["evidence"].strip(),
        } for row in rows],
    }
    handoff.validate_human_review_receipt(source_package, anchor, approved, receipt)
    return approved, receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "approve"))
    parser.add_argument("--english-source-package", type=Path, required=True)
    parser.add_argument("--anchor", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--worksheet", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    _require(not args.out.exists(), "Use a new output path; review artifacts are immutable")
    source_package, anchor, candidate, policy = (
        _load(path) for path in (args.english_source_package, args.anchor, args.candidate, args.policy)
    )
    if args.command == "prepare":
        _require(args.worksheet is None, "prepare does not consume a worksheet")
        worksheet = build_worksheet(source_package, anchor, candidate, policy)
        interpretation.write_json(args.out, worksheet)
        print(json.dumps({"status": "human_review_pending", "worksheet": str(args.out.resolve())}))
    else:
        _require(args.worksheet is not None, "approve requires --worksheet")
        approved, receipt = approve_worksheet(
            source_package, anchor, candidate, policy, _load(args.worksheet),
        )
        args.out.mkdir(parents=True)
        interpretation.write_json(args.out / "candidate.approved.json", approved)
        interpretation.write_json(args.out / "human-review-receipt.json", receipt)
        print(json.dumps({"status": "human_translation_approved", "out": str(args.out.resolve())}))


if __name__ == "__main__":
    main()
