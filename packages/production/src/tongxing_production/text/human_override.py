"""Create source-bound human exception receipts for machine-rejected L2 groups.

An override is an auditable human disposition, never a rewrite of machine evidence.
This module deliberately does not promote candidates or authorize Layer 3; consumers
must explicitly support this receipt version before an override can affect release.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from ..source import sentence_interpretation as interpretation
from . import backend as _text
from . import candidate as producer


WORKSHEET_SCHEMA = "sermon-target-language-human-override-worksheet-v1"
RECEIPT_SCHEMA = "sermon-target-language-human-override-receipt-v1"
SEMANTIC_CHECKS = ("completeMeaning", "negationsNumbersNames", "quotationAttribution", "noAddedMeaning")


class _Handoff:
    def __getattr__(self, name):
        return getattr(_text.current().unmoved.speech_handoff(), name)


handoff = _Handoff()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _schema(value: dict[str, Any], name: str) -> None:
    schema = json.loads(_text.current().schemas.path(name).read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    _require(not errors, f"Invalid {name}: {errors[0].message}" if errors else "")


def _findings(group: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    semantic = group.get("semanticReview") or {}
    checks = semantic.get("checks") or {}
    for check in SEMANTIC_CHECKS:
        if checks.get(check) != "pass":
            findings.append({"gate": "semanticReview", "checkId": check,
                             "machineStatus": str(checks.get(check, "missing"))})
    for key in ("issues", "uncertainty"):
        for index, _ in enumerate(semantic.get(key) or []):
            findings.append({"gate": "semanticReview", "checkId": f"{key}[{index}]",
                             "machineStatus": "reported"})
    language = group.get("languageReview") or {}
    if language.get("status") != "pass":
        findings.append({"gate": "languageReview", "checkId": "status",
                         "machineStatus": str(language.get("status", "missing"))})
    for check in language.get("checks") or []:
        if isinstance(check, dict) and check.get("status") != "pass":
            findings.append({"gate": "languageReview", "checkId": str(check.get("checkId", "unknown")),
                             "machineStatus": str(check.get("status", "missing"))})
    return findings


def _validate_candidate_binding(source: dict[str, Any], anchor: dict[str, Any],
                                candidate: dict[str, Any]) -> list[dict[str, Any]]:
    producer.validate_source_for_translation(source, anchor)
    handoff._validate_schema(candidate, "sermon-target-language-candidate-v2.schema.json",
                             "target candidate")
    _require(candidate.get("sourceLocale") == "en"
             and candidate.get("englishSourcePackageJsonSha256") == interpretation.json_sha256(source)
             and candidate.get("anchorManifestSha256") == interpretation.json_sha256(anchor),
             "Human override candidate belongs to another source or anchor")
    groups = candidate.get("groups")
    _require(isinstance(groups, list) and groups, "Human override candidate has no groups")
    unit_ids = [unit["sourceUnitId"] for unit in anchor["sourceUnits"]]
    assigned: list[str] = []
    seen: set[str] = set()
    for group in groups:
        _require(isinstance(group, dict) and isinstance(group.get("translationGroupId"), str)
                 and group["translationGroupId"] not in seen, "Invalid or duplicate translation group")
        seen.add(group["translationGroupId"])
        source_ids = group.get("sourceUnitIds")
        utterances = group.get("targetUtterances")
        _require(isinstance(source_ids, list) and source_ids
                 and isinstance(utterances, list) and utterances
                 and all(isinstance(text, str) and text.strip() for text in utterances)
                 and group.get("targetText") == "".join(utterances),
                 f"Invalid target text or source binding: {group['translationGroupId']}")
        assigned.extend(source_ids)
    _require(assigned == unit_ids, "Human override candidate must cover every source unit once in order")
    return groups


def build_worksheet(source: dict[str, Any], anchor: dict[str, Any],
                    candidate: dict[str, Any]) -> dict[str, Any]:
    """Freeze only groups with machine findings; no decisions are inferred."""
    groups = _validate_candidate_binding(source, anchor, candidate)
    rows = []
    for group in groups:
        findings = _findings(group)
        if not findings:
            continue
        rows.append({
            "translationGroupId": group["translationGroupId"],
            "sourceUnitIds": copy.deepcopy(group["sourceUnitIds"]),
            "targetText": group["targetText"],
            "targetTextSha256": hashlib.sha256(group["targetText"].encode("utf-8")).hexdigest(),
            "machineFindings": findings,
            "disposition": "pending",
            "rationale": None,
        })
    _require(rows, "Candidate has no machine findings to override")
    worksheet = {
        "schemaVersion": WORKSHEET_SCHEMA,
        "decision": "pending",
        "targetLocale": candidate["targetLocale"],
        "englishSourcePackageJsonSha256": interpretation.json_sha256(source),
        "anchorManifestJsonSha256": interpretation.json_sha256(anchor),
        "translationPolicySha256": candidate["translationPolicySha256"],
        "candidateJsonSha256": interpretation.json_sha256(candidate),
        "groupOverrides": rows,
        "disclosure": "Human override records an exception; machine findings remain unchanged.",
    }
    _schema(worksheet, WORKSHEET_SCHEMA + ".schema.json")
    return worksheet


def approve_worksheet(source: dict[str, Any], anchor: dict[str, Any], candidate: dict[str, Any],
                      worksheet: dict[str, Any], *, reviewer: str, reviewed_at: str) -> dict[str, Any]:
    """Record explicit per-group accept/defer decisions against frozen candidate bytes."""
    expected = build_worksheet(source, anchor, candidate)
    _require(worksheet.get("decision") == "pending"
             and all(worksheet.get(key) == expected[key] for key in (
        "schemaVersion", "targetLocale", "englishSourcePackageJsonSha256",
        "anchorManifestJsonSha256", "translationPolicySha256", "candidateJsonSha256",
        "disclosure")), "Human override worksheet identity changed")
    _require(handoff._reviewed_at(reviewed_at) and isinstance(reviewer, str) and reviewer.strip(),
             "Human override requires reviewer and timezone-aware review time")
    rows = worksheet.get("groupOverrides")
    _require(isinstance(rows, list) and len(rows) == len(expected["groupOverrides"]),
             "Human override worksheet group set changed")
    receipt_rows = []
    for row, frozen in zip(rows, expected["groupOverrides"]):
        _require(isinstance(row, dict) and set(row) == set(frozen)
                 and all(row[key] == frozen[key] for key in frozen
                         if key not in {"disposition", "rationale"}),
                 "Human override source, target, or machine findings changed")
        _require(row["disposition"] in {"accepted_as_is", "deferred"}
                 and isinstance(row["rationale"], str) and row["rationale"].strip(),
                 "Every override needs an explicit disposition and rationale")
        receipt_rows.append({key: copy.deepcopy(row[key]) for key in (
            "translationGroupId", "sourceUnitIds", "targetTextSha256", "machineFindings",
            "disposition", "rationale")})
    decision = "approved_with_exceptions" if all(
        row["disposition"] == "accepted_as_is" for row in receipt_rows) else "partially_deferred"
    receipt = {
        "schemaVersion": RECEIPT_SCHEMA,
        "decision": decision,
        "targetLocale": candidate["targetLocale"],
        "englishSourcePackageJsonSha256": interpretation.json_sha256(source),
        "anchorManifestJsonSha256": interpretation.json_sha256(anchor),
        "translationPolicySha256": candidate["translationPolicySha256"],
        "candidateJsonSha256": interpretation.json_sha256(candidate),
        "reviewer": reviewer.strip(),
        "reviewedAt": reviewed_at,
        "groupOverrides": receipt_rows,
        "machineEvidenceChanged": False,
        "releaseEligible": False,
        "disclosure": "This receipt does not turn a machine failure into a pass or authorize Layer 3.",
    }
    _schema(receipt, RECEIPT_SCHEMA + ".schema.json")
    return receipt


def verify_receipt(source: dict[str, Any], anchor: dict[str, Any], candidate: dict[str, Any],
                   receipt: dict[str, Any]) -> None:
    """Fail closed if receipt is stale, mutated, or attached to another candidate."""
    _schema(receipt, RECEIPT_SCHEMA + ".schema.json")
    expected = build_worksheet(source, anchor, candidate)
    _require(receipt.get("targetLocale") == candidate["targetLocale"]
             and receipt.get("englishSourcePackageJsonSha256") == interpretation.json_sha256(source)
             and receipt.get("anchorManifestJsonSha256") == interpretation.json_sha256(anchor)
             and receipt.get("translationPolicySha256") == candidate["translationPolicySha256"]
             and receipt.get("candidateJsonSha256") == interpretation.json_sha256(candidate),
             "Human override receipt is stale or belongs to another input")
    frozen = {row["translationGroupId"]: row for row in expected["groupOverrides"]}
    rows = receipt.get("groupOverrides")
    _require(isinstance(rows, list) and len(rows) == len(expected["groupOverrides"])
             and [row.get("translationGroupId") for row in rows]
             == [row["translationGroupId"] for row in expected["groupOverrides"]],
             "Human override receipt does not cover the exact machine-rejected group set")
    for row in rows:
        source_row = frozen.get(row.get("translationGroupId"))
        _require(source_row is not None and row["sourceUnitIds"] == source_row["sourceUnitIds"]
                 and row["targetTextSha256"] == source_row["targetTextSha256"]
                 and row["machineFindings"] == source_row["machineFindings"],
                 "Human override receipt does not match current machine evidence")
    decision = ("approved_with_exceptions" if all(row["disposition"] == "accepted_as_is" for row in rows)
                else "partially_deferred")
    _require(receipt.get("decision") == decision, "Human override receipt decision summary is inconsistent")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "approve", "verify"))
    parser.add_argument("--english-source-package", required=True, type=Path)
    parser.add_argument("--anchor", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--worksheet", type=Path)
    parser.add_argument("--reviewer")
    parser.add_argument("--reviewed-at")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))  # noqa: E731
    source, anchor, candidate = (read(path) for path in
                                 (args.english_source_package, args.anchor, args.candidate))
    _require(not args.out.exists(), "Use a new output path; override artifacts are immutable")
    if args.command == "prepare":
        _require(not any((args.worksheet, args.reviewer, args.reviewed_at, args.receipt)),
                 "prepare accepts only frozen source, anchor, and candidate inputs")
        result = build_worksheet(source, anchor, candidate)
    elif args.command == "approve":
        _require(args.worksheet and args.reviewer and args.reviewed_at and not args.receipt,
                 "approve requires --worksheet, --reviewer, and --reviewed-at")
        result = approve_worksheet(source, anchor, candidate, read(args.worksheet),
                                   reviewer=args.reviewer, reviewed_at=args.reviewed_at)
    else:
        _require(args.receipt and not any((args.worksheet, args.reviewer, args.reviewed_at)),
                 "verify requires only --receipt")
        verify_receipt(source, anchor, candidate, read(args.receipt))
        result = {"status": "verified", "receipt": str(args.receipt.resolve())}
    interpretation.write_json(args.out, result)
    print(json.dumps({"status": args.command, "out": str(args.out.resolve())}))


if __name__ == "__main__":
    main()
