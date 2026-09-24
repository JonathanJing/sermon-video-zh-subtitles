#!/usr/bin/env python3
"""Prepare a human translation worksheet and admit its reviewed candidate.

This command never decides whether a translation is correct. A reviewer may
fill every group separately, or attest after reviewing the complete frozen
worksheet and let `approve-batch` expand that decision into the unchanged
per-group receipt contract.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

try:
    from scripts import four_layer_measure as measure
    from scripts import prepare_target_language_speech_job as handoff
    from scripts import sermon_sentence_interpretation as interpretation
except ImportError:  # Direct execution via ``python scripts/...``.
    import four_layer_measure as measure
    import prepare_target_language_speech_job as handoff
    import sermon_sentence_interpretation as interpretation


WORKSHEET_SCHEMA = "sermon-target-language-human-review-worksheet-v1"
GROUP_RECEIPT_SCHEMA = "sermon-target-language-group-review-receipt-v1"


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


def apply_batch_approval(worksheet: dict[str, Any], *, reviewer: str,
                         reviewed_at: str, evidence: str) -> dict[str, Any]:
    """Expand one explicit full-text human attestation over pending rows only."""
    _require(isinstance(reviewer, str) and reviewer.strip()
             and handoff._reviewed_at(reviewed_at)
             and isinstance(evidence, str) and evidence.strip(),
             "Batch approval requires reviewer, timezone-aware time, and full-review evidence")
    _require(worksheet.get("decision") == "pending"
             and worksheet.get("reviewer") is None
             and worksheet.get("reviewedAt") is None,
             "Batch approval requires an untouched pending worksheet")
    rows = worksheet.get("groupReviews")
    _require(isinstance(rows, list) and rows
             and all(isinstance(row, dict) and row.get("decision") == "pending"
                     and row.get("evidence") is None for row in rows),
             "Batch approval cannot override a group decision or evidence")
    filled = copy.deepcopy(worksheet)
    filled["decision"] = "approved"
    filled["reviewer"] = reviewer.strip()
    filled["reviewedAt"] = reviewed_at
    for row in filled["groupReviews"]:
        row["decision"] = "approved"
        row["evidence"] = evidence.strip()
    return filled


def _context_rows(worksheet: dict[str, Any], group_id: str,
                  scope: str) -> list[dict[str, Any]]:
    """Conservatively bind all groups in connected source blocks."""
    rows = worksheet["groupReviews"]
    selected = next((row for row in rows if row["translationGroupId"] == group_id), None)
    _require(selected is not None, f"Unknown translation group: {group_id}")
    _require(scope in {"whole_candidate", "connected_blocks"}, "Invalid context scope")
    if scope == "whole_candidate":
        return rows
    blocks: dict[str, set[str]] = {}
    for row in rows:
        names = []
        for unit in row["sourceUnits"]:
            match = re.fullmatch(r"(.+)-u\d+", unit["sourceUnitId"])
            if match is None:
                raise ValueError("Unknown source unit naming cannot use block-scoped review")
            names.append(match.group(1))
        blocks[row["translationGroupId"]] = set(names)
    affected = {group_id}
    scope = set(blocks[group_id])
    while True:
        newly = {name for name, names in blocks.items()
                 if name not in affected and names.intersection(scope)}
        if not newly:
            break
        affected.update(newly)
        for name in newly:
            scope.update(blocks[name])
    return [row for row in rows if row["translationGroupId"] in affected]


def record_group_review(source_package: dict[str, Any], anchor: dict[str, Any],
                        candidate: dict[str, Any], policy: dict[str, Any], *,
                        group_id: str, decision: str, evidence: str,
                        reviewer: str, reviewed_at: str,
                        context_scope: str = "whole_candidate",
                        context_evidence: str | None = None) -> dict[str, Any]:
    worksheet = build_worksheet(source_package, anchor, candidate, policy)
    _require(decision in {"approved", "rejected"}
             and isinstance(evidence, str) and evidence.strip()
             and isinstance(reviewer, str) and reviewer.strip()
             and handoff._reviewed_at(reviewed_at),
             "Group review requires a human decision, evidence, reviewer, and timezone-aware time")
    row = next((item for item in worksheet["groupReviews"]
                if item["translationGroupId"] == group_id), None)
    _require(row is not None, f"Unknown translation group: {group_id}")
    _require(context_scope == "whole_candidate" or
             (context_scope == "connected_blocks"
              and isinstance(context_evidence, str) and context_evidence.strip()),
             "Block-scoped reuse needs explicit reviewed context evidence")
    _require(context_scope != "whole_candidate" or context_evidence is None,
             "Whole-candidate context cannot claim block independence")
    context = _context_rows(worksheet, group_id, context_scope)
    receipt = {
        "schemaVersion": GROUP_RECEIPT_SCHEMA,
        "sourceLocale": "en", "targetLocale": worksheet["targetLocale"],
        "englishSourcePackageJsonSha256": worksheet["englishSourcePackageJsonSha256"],
        "anchorManifestJsonSha256": worksheet["anchorManifestJsonSha256"],
        "translationPolicySha256": worksheet["translationPolicySha256"],
        "originCandidateJsonSha256": worksheet["candidateJsonSha256"],
        "translationGroupId": group_id,
        "groupReviewJsonSha256": interpretation.json_sha256(row),
        "contextScope": context_scope,
        "contextEvidence": context_evidence.strip() if context_evidence else None,
        "contextGroupIds": [item["translationGroupId"] for item in context],
        "contextJsonSha256": interpretation.json_sha256(context),
        "decision": decision, "evidence": evidence.strip(),
        "reviewer": reviewer.strip(), "reviewedAt": reviewed_at,
    }
    handoff._validate_schema(receipt, "sermon-target-language-group-review-receipt-v1.schema.json",
                             "group review receipt")
    return receipt


def approve_group_receipts(source_package: dict[str, Any], anchor: dict[str, Any],
                           candidate: dict[str, Any], policy: dict[str, Any],
                           receipts: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Only complete, still-valid unit decisions may form the legacy full gate."""
    worksheet = build_worksheet(source_package, anchor, candidate, policy)
    frozen = copy.deepcopy(worksheet)
    rows = worksheet["groupReviews"]
    ids = [row["translationGroupId"] for row in rows]
    _require(len(receipts) == len(ids), "One group review receipt is required per group")
    by_id: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        handoff._validate_schema(receipt, "sermon-target-language-group-review-receipt-v1.schema.json",
                                 "group review receipt")
        group_id = receipt["translationGroupId"]
        _require(group_id in ids and group_id not in by_id,
                 f"Duplicate or foreign group review receipt: {group_id}")
        by_id[group_id] = receipt
    _require(set(by_id) == set(ids), "Group review receipts do not cover every group")
    reviewers = {receipt["reviewer"] for receipt in receipts}
    _require(len(reviewers) == 1,
             "The current full candidate contract needs one reviewer; mixed reviewers require a new schema")
    latest = max(receipts, key=lambda item: datetime.fromisoformat(
        item["reviewedAt"].replace("Z", "+00:00")))["reviewedAt"]
    for row, original in zip(rows, frozen["groupReviews"]):
        group_id = row["translationGroupId"]
        receipt = by_id[group_id]
        _require(receipt["contextScope"] == "whole_candidate" or
                 (receipt["contextScope"] == "connected_blocks"
                  and isinstance(receipt["contextEvidence"], str)
                  and receipt["contextEvidence"].strip()),
                 f"Group context reuse evidence is missing: {group_id}")
        _require(receipt["contextScope"] != "whole_candidate"
                 or receipt["originCandidateJsonSha256"] == worksheet["candidateJsonSha256"],
                 f"Whole-candidate group review belongs to another candidate: {group_id}")
        context = _context_rows(frozen, group_id, receipt["contextScope"])
        _require(receipt["targetLocale"] == worksheet["targetLocale"]
                 and receipt["englishSourcePackageJsonSha256"] == worksheet["englishSourcePackageJsonSha256"]
                 and receipt["anchorManifestJsonSha256"] == worksheet["anchorManifestJsonSha256"]
                 and receipt["translationPolicySha256"] == worksheet["translationPolicySha256"]
                 and receipt["groupReviewJsonSha256"] == interpretation.json_sha256(original)
                 and receipt["contextGroupIds"] == [item["translationGroupId"] for item in context]
                 and receipt["contextJsonSha256"] == interpretation.json_sha256(context),
                 f"Group review identity or context changed: {group_id}")
        _require(receipt["decision"] == "approved", f"Group is not approved: {group_id}")
        row["decision"] = "approved"
        row["evidence"] = (f"{receipt['evidence']} "
                           f"[groupReceiptJsonSha256={interpretation.json_sha256(receipt)}]")
    worksheet["decision"] = "approved"
    worksheet["reviewer"] = next(iter(reviewers))
    worksheet["reviewedAt"] = latest
    approved, final_receipt = approve_worksheet(
        source_package, anchor, candidate, policy, worksheet,
    )
    manifest = {
        "schemaVersion": "sermon-target-language-group-review-aggregation-v1",
        "approvedCandidateJsonSha256": interpretation.json_sha256(approved),
        "humanReviewReceiptJsonSha256": interpretation.json_sha256(final_receipt),
        "groupReceipts": [{"translationGroupId": group_id,
                           "jsonSha256": interpretation.json_sha256(by_id[group_id])}
                          for group_id in ids],
    }
    return approved, final_receipt, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "approve", "approve-batch",
                                            "record-group", "approve-groups"))
    parser.add_argument("--english-source-package", type=Path, required=True)
    parser.add_argument("--anchor", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--worksheet", type=Path)
    parser.add_argument("--reviewer")
    parser.add_argument("--reviewed-at")
    parser.add_argument("--full-review-evidence",
                        help="Human attestation that every displayed group was reviewed")
    parser.add_argument("--group-id")
    parser.add_argument("--decision", choices=("approved", "rejected"))
    parser.add_argument("--evidence")
    parser.add_argument("--group-receipt", type=Path, action="append", default=[])
    parser.add_argument("--context-scope", choices=("whole_candidate", "connected_blocks"),
                        default="whole_candidate")
    parser.add_argument("--context-evidence",
                        help="Human reason this group has no dependencies outside its source block")
    parser.add_argument("--progress-ledger", type=Path,
                        help="Record producer timing in this four-layer run ledger")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    candidate = _load(args.candidate)
    locale = candidate.get("targetLocale")
    with measure.producer_step(args.progress_ledger, f"L2-04@{locale}", locale=locale) as metrics:
        _require(not args.out.exists(), "Use a new output path; review artifacts are immutable")
        source_package, anchor, policy = (
            _load(path) for path in (args.english_source_package, args.anchor, args.policy)
        )
        metrics.update(translationGroups=len(candidate.get("groups") or []),
                       sourceUnits=len(anchor.get("sourceUnits") or []),
                       candidateSha256=interpretation.json_sha256(candidate))
        if args.command == "record-group":
            _require(args.worksheet is None and not args.group_receipt
                     and args.group_id and args.decision and args.evidence
                     and args.reviewer and args.reviewed_at
                     and args.full_review_evidence is None,
                     "record-group requires one explicit human group decision")
            receipt = record_group_review(
                source_package, anchor, candidate, policy,
                group_id=args.group_id, decision=args.decision, evidence=args.evidence,
                reviewer=args.reviewer, reviewed_at=args.reviewed_at,
                context_scope=args.context_scope, context_evidence=args.context_evidence,
            )
            interpretation.write_json(args.out, receipt)
            print(json.dumps({"status": "group_review_recorded", "out": str(args.out.resolve())}))
        elif args.command == "approve-groups":
            _require(args.worksheet is None and args.group_receipt
                     and not any((args.group_id, args.decision, args.evidence,
                                  args.reviewer, args.reviewed_at, args.full_review_evidence,
                                  args.context_evidence))
                     and args.context_scope == "whole_candidate",
                     "approve-groups consumes only existing group receipts")
            approved, receipt, manifest = approve_group_receipts(
                source_package, anchor, candidate, policy,
                [_load(path) for path in args.group_receipt],
            )
            args.out.mkdir(parents=True)
            interpretation.write_json(args.out / "candidate.approved.json", approved)
            interpretation.write_json(args.out / "human-review-receipt.json", receipt)
            interpretation.write_json(args.out / "group-review-aggregation.json", manifest)
            print(json.dumps({"status": "human_translation_approved", "out": str(args.out.resolve())}))
        elif args.command == "prepare":
            _require(args.worksheet is None, "prepare does not consume a worksheet")
            _require(not any((args.reviewer, args.reviewed_at, args.full_review_evidence,
                              args.group_id, args.decision, args.evidence, args.group_receipt,
                              args.context_evidence))
                     and args.context_scope == "whole_candidate",
                     "Review attestation is only valid for approve-batch")
            worksheet = build_worksheet(source_package, anchor, candidate, policy)
            interpretation.write_json(args.out, worksheet)
            print(json.dumps({"status": "human_review_pending", "worksheet": str(args.out.resolve())}))
        else:
            _require(args.worksheet is not None, "approve requires --worksheet")
            worksheet = _load(args.worksheet)
            if args.command == "approve-batch":
                _require(not any((args.group_id, args.decision, args.evidence, args.group_receipt,
                                  args.context_evidence))
                         and args.context_scope == "whole_candidate",
                         "approve-batch does not consume individual group decisions")
                worksheet = apply_batch_approval(
                    worksheet, reviewer=args.reviewer, reviewed_at=args.reviewed_at,
                    evidence=args.full_review_evidence,
                )
            else:
                _require(not any((args.reviewer, args.reviewed_at, args.full_review_evidence,
                                  args.group_id, args.decision, args.evidence, args.group_receipt,
                                  args.context_evidence))
                         and args.context_scope == "whole_candidate",
                         "Review attestation is only valid for approve-batch")
            approved, receipt = approve_worksheet(
                source_package, anchor, candidate, policy, worksheet,
            )
            args.out.mkdir(parents=True)
            interpretation.write_json(args.out / "candidate.approved.json", approved)
            interpretation.write_json(args.out / "human-review-receipt.json", receipt)
            print(json.dumps({"status": "human_translation_approved", "out": str(args.out.resolve())}))


if __name__ == "__main__":
    main()
