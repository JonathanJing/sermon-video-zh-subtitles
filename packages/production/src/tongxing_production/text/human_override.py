"""Create source-bound human exception receipts for machine-rejected L2 groups.

An override is an auditable human disposition, never a rewrite of machine evidence.
This module deliberately does not promote candidates or authorize Layer 3; consumers
must explicitly support this receipt version before an override can affect release.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import os
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


# Absolute paths a deployment path map linked to hash-verified staged files inside an isolated
# container (audio.renderer.materialize_path_map). Only these may be symlinks; any other
# symlinked evidence is still refused.
_MAPPED_ALIASES: set[str] = set()


def admit_mapped_aliases(paths) -> None:
    _MAPPED_ALIASES.update(str(path) for path in paths)


def _regular_file(path: Path) -> bool:
    return path.is_file() and (not path.is_symlink() or str(path) in _MAPPED_ALIASES)


def _review_sheet_cache_path(sheet_path: Path, csv_value: str) -> Path:
    path = Path(csv_value)
    if not path.is_absolute():
        path = sheet_path.parent.parent / path
    # Normalize without following symlinks: a path-mapped cache must keep its original path.
    return Path(os.path.abspath(path))


def _cached_response_identity(path: Path, expected_group_id: str) -> str:
    _require(_regular_file(path),
             f"Selected model response cache is missing or symlinked: {path}")
    cached = json.loads(path.read_text(encoding="utf-8"))
    response = cached.get("response") if isinstance(cached, dict) else None
    choices = response.get("choices") if isinstance(response, dict) else None
    _require(isinstance(response, dict) and isinstance(response.get("id"), str)
             and isinstance(choices, list) and choices
             and isinstance(choices[0], dict)
             and isinstance(choices[0].get("message"), dict)
             and isinstance(choices[0]["message"].get("content"), str),
             f"Selected response cache lacks raw response identity: {path}")
    parsed = json.loads(choices[0]["message"]["content"])
    _require(isinstance(parsed, dict)
             and parsed.get("translationGroupId") == expected_group_id,
             f"Selected response cache belongs to another group: {path}")
    return response["id"]


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


def validate_override_receipt(source: dict[str, Any], anchor: dict[str, Any],
                              candidate: dict[str, Any], receipt: dict[str, Any]) -> None:
    """Validate the full-review v2 receipt consumed by formal Layer 3.

    The review-sheet and decision artifacts prove the human-reviewed text and the
    user's whole-candidate approval. Exception rows only explain which unchanged
    machine failures the human accepted; they never rewrite group machine evidence.
    """
    _schema(receipt, "sermon-target-language-human-override-receipt-v2.schema.json")
    groups = _validate_candidate_binding(source, anchor, candidate)
    group_ids = [group["translationGroupId"] for group in groups]
    human = candidate.get("humanReview") or {}
    model_review = candidate.get("modelReview") or {}
    source_hash = interpretation.json_sha256(source)
    anchor_hash = interpretation.json_sha256(anchor)
    _require(candidate.get("status") == "human_override_approved"
             and human.get("translation") == "approved"
             and isinstance(human.get("reviewer"), str) and human["reviewer"].strip()
             and handoff._reviewed_at(human.get("reviewedAt"))
             and human.get("reviewedGroupIds") == group_ids
             and model_review.get("status") in {"pending", "pass", "fail"}
             and model_review.get("reviewedGroupIds") == group_ids,
             "Candidate lacks complete human approval for its override receipt")
    _require(receipt.get("decision") == "approved_with_exceptions"
             and receipt.get("targetLocale") == candidate["targetLocale"]
             and receipt.get("englishSourcePackageJsonSha256") == source_hash
             and receipt.get("anchorManifestJsonSha256") == anchor_hash
             and receipt.get("translationPolicySha256") == candidate["translationPolicySha256"]
             and receipt.get("candidateJsonSha256") == interpretation.json_sha256(candidate)
             and receipt.get("reviewer") == human["reviewer"]
             and receipt.get("reviewedAt") == human["reviewedAt"]
             and receipt.get("reviewedGroupIds") == group_ids
             and receipt.get("modelReview") == model_review
             and receipt.get("modelReview", {}).get("reviewedGroupIds") == group_ids
             and receipt.get("humanApproval") is True
             and receipt.get("machineEvidenceChanged") is False
             and receipt.get("releaseEligible") is False,
             "Human override receipt differs from the approved candidate or source")

    sheet_ref = receipt["reviewSheet"]
    sheet_path = Path(sheet_ref["path"])
    _require(_regular_file(sheet_path)
             and sheet_path.stat().st_size == sheet_ref["bytes"]
             and interpretation.sha256(sheet_path) == sheet_ref["sha256"],
             "Human override review-sheet bytes changed")
    decision_ref = receipt["reviewDecision"]
    decision_path = Path(decision_ref["path"])
    _require(_regular_file(decision_path)
             and interpretation.sha256(decision_path) == decision_ref["sha256"],
             "Human override user-decision file bytes changed")
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    _require(interpretation.json_sha256(decision) == decision_ref["jsonSha256"]
             and decision.get("schemaVersion") == "sermon-target-language-review-sheet-decision-v1"
             and decision.get("decision") == "approved_as_presented"
             and decision.get("userMessageItemId") == decision_ref["userMessageItemId"]
             and decision.get("userStatement") == decision_ref["userStatement"]
             and decision.get("binding", {}).get("frozenEnglishSourcePackageJsonSha256") == source_hash
             and decision.get("binding", {}).get("frozenAnchorManifestSha256") == anchor_hash,
             "Human override is not bound to the recorded user approval and frozen source")
    locale_decision = decision.get("targetLocales", {}).get(candidate["targetLocale"], {})
    _require(locale_decision.get("approvedTextUnitCount") == len(group_ids)
             and locale_decision.get("approvedGroupIds") == group_ids
             and locale_decision.get("reviewSheet", {}).get("sha256") == sheet_ref["sha256"],
             "User approval does not cover the exact candidate group set")
    with sheet_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    _require(len(rows) == len(groups), "Human review sheet has incomplete group coverage")
    response_caches = receipt.get("responseCaches")
    _require(isinstance(response_caches, list) and len(response_caches) == 2 * len(rows),
             "Human override receipt does not bind every selected translator and reviewer cache")
    for row, group in zip(rows, groups):
        source_ids = [item.strip() for item in row["sourceUnitIds"].split(",") if item.strip()]
        _require(row["translationGroupId"] == group["translationGroupId"]
                 and source_ids == group["sourceUnitIds"]
                 and row["currentText"] == group["targetText"],
                 "Approved review-sheet text differs from candidate text")
    for index, row in enumerate(rows):
        for lane, csv_column in (("translator", "selectedModelOutputFile"),
                                 ("reviewer", "selectedReviewFile")):
            entry = response_caches[index * 2 + (lane == "reviewer")]
            cache_path = _review_sheet_cache_path(sheet_path, row[csv_column])
            _require(isinstance(entry, dict)
                     and entry.get("role") == lane
                     and entry.get("translationGroupId") == row["translationGroupId"]
                     and entry.get("path") == str(cache_path)
                     and _regular_file(cache_path)
                     and entry.get("sha256") == interpretation.sha256(cache_path)
                     and entry.get("responseId") == _cached_response_identity(
                         cache_path, row["translationGroupId"]),
                     f"Selected {lane} cache identity changed for {row['translationGroupId']}")

    expected_exceptions = []
    for group in groups:
        findings = _findings(group)
        if findings:
            expected_exceptions.append({
                "translationGroupId": group["translationGroupId"],
                "sourceUnitIds": list(group["sourceUnitIds"]),
                "targetTextSha256": hashlib.sha256(group["targetText"].encode("utf-8")).hexdigest(),
                "machineFindings": findings,
                "disposition": "accepted_as_is",
            })
    actual = receipt.get("groupOverrides")
    _require(bool(expected_exceptions) and isinstance(actual, list)
             and len(actual) == len(expected_exceptions),
             "Human override receipt does not enumerate every machine exception")
    for row, expected in zip(actual, expected_exceptions):
        _require(all(row.get(key) == value for key, value in expected.items())
                 and isinstance(row.get("rationale"), str) and row["rationale"].strip(),
                 "Human override does not match the exact failed checks or text")


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
