#!/usr/bin/env python3
"""Build a human-approved Layer 2 candidate from an already approved review CSV.

This operator command reads cached translator and reviewer responses referenced by
the CSV. It makes no model/API calls. The final target text comes only from each
CSV ``currentText`` field; semantic findings are copied from the cached reviewer
response and language findings are recomputed with the frozen policy plugin.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Use the same production checkout host bindings as tools/ops/run.py.
from tools.ops.run import bind_host
bind_host()

from tongxing_production.source import sentence_interpretation as interpretation
from tongxing_production.text import candidate as producer
from tongxing_production.text import human_override
from tongxing_production.text import policy as policy_tools


SCHEMA = "sermon-target-language-human-override-receipt-v2"
EXPECTED_ROWS = 416
DISCLOSURE = (
    "Human approval covers the exact currentText values in this review sheet. "
    "Machine findings remain unchanged; this receipt does not authorize Layer 3."
)
RATIONALE = (
    "The user approved the exact currentText in the bound full review sheet; "
    "the listed machine findings remain unresolved and unchanged."
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def response_content(path: Path) -> tuple[str, str, dict[str, Any]]:
    cached = load_json(path)
    response = cached.get("response")
    require(isinstance(response, dict), f"Cached API response missing: {path}")
    response_id, model = response.get("id"), response.get("model")
    choices = response.get("choices")
    require(isinstance(response_id, str) and response_id.strip()
            and isinstance(model, str) and model.strip()
            and isinstance(choices, list) and choices
            and isinstance(choices[0], dict)
            and isinstance(choices[0].get("message"), dict)
            and isinstance(choices[0]["message"].get("content"), str),
            f"Cached response lacks raw id, model, or parsed content: {path}")
    parsed = json.loads(choices[0]["message"]["content"])
    require(isinstance(parsed, dict), f"Cached response content must be a JSON object: {path}")
    return response_id, model, parsed


def read_csv(path: Path) -> list[dict[str, str]]:
    require(path.is_file() and not path.is_symlink(), f"Review CSV is missing or symlinked: {path}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"translationGroupId", "sourceUnitIds", "currentText",
                    "selectedModelOutputFile", "selectedReviewFile"}
        require(reader.fieldnames is not None and required <= set(reader.fieldnames),
                "Review CSV is missing required evidence columns")
        rows = list(reader)
    require(len(rows) == EXPECTED_ROWS, f"Expected {EXPECTED_ROWS} approved review rows, got {len(rows)}")
    return rows


def _semantic_review(reviewed: dict[str, Any], group_id: str, source_ids: list[str]) -> dict[str, Any]:
    require(reviewed.get("translationGroupId") == group_id
            and reviewed.get("sourceUnitIds") == source_ids,
            f"Cached reviewer response belongs to a different group: {group_id}")
    semantic = reviewed.get("semanticReview")
    require(isinstance(semantic, dict), f"Cached reviewer response has no semantic findings: {group_id}")
    semantic = json.loads(json.dumps(semantic, ensure_ascii=False))
    # The current candidate contract stores evidence as one string; preserve all
    # reviewer evidence text while adapting the cached response's list form.
    if isinstance(semantic.get("evidence"), list):
        semantic["evidence"] = "\n".join(str(item) for item in semantic["evidence"])
    return semantic


def build(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    source, anchor, policy, decision = (load_json(path) for path in (
        args.english_source_package, args.anchor, args.policy, args.review_decision))
    rows = read_csv(args.review_sheet)
    require(decision.get("schemaVersion") == "sermon-target-language-review-sheet-decision-v1"
            and decision.get("decision") == "approved_as_presented",
            "Review decision does not record approval of the current sheets")
    require(decision.get("userMessageItemId") and decision.get("userStatement"),
            "Review decision lacks the user approval identity")
    frozen = decision.get("binding", {})
    require(frozen.get("frozenEnglishSourcePackageJsonSha256") == interpretation.json_sha256(source)
            and frozen.get("frozenAnchorManifestSha256") == interpretation.json_sha256(anchor),
            "Review decision is bound to a different source or anchor")
    locale = policy.get("targetLocale")
    locale_decision = decision.get("targetLocales", {}).get(locale)
    require(isinstance(locale_decision, dict), f"Review decision does not approve locale {locale}")
    sheet_hash = file_hash(args.review_sheet)
    sheet_binding = locale_decision.get("reviewSheet", {})
    require(Path(sheet_binding.get("path", "")).resolve() == args.review_sheet.resolve()
            and sheet_binding.get("sha256") == sheet_hash
            and sheet_binding.get("bytes") == args.review_sheet.stat().st_size,
            "Review CSV path, hash, or byte count differs from the recorded approval")

    request = producer.prepare_request(source, anchor, policy)
    source_units = {row["sourceUnitId"] for row in request["sourceUnits"]}
    approved_ids = locale_decision.get("approvedGroupIds")
    group_ids = [row.get("translationGroupId", "") for row in rows]
    require(approved_ids == group_ids and locale_decision.get("approvedTextUnitCount") == EXPECTED_ROWS,
            "The approved group IDs/count do not exactly match the ordered review sheet")

    groups: list[dict[str, Any]] = []
    translator_ids: list[str] = []
    reviewer_ids: list[str] = []
    translator_models: set[str] = set()
    reviewer_models: set[str] = set()
    response_caches: list[dict[str, str]] = []
    for row in rows:
        group_id = row["translationGroupId"]
        source_ids = [value.strip() for value in row["sourceUnitIds"].split(",") if value.strip()]
        target = row["currentText"]
        require(source_ids and all(value in source_units for value in source_ids)
                and isinstance(target, str) and target.strip(),
                f"Invalid approved source/text row: {group_id}")
        translator_path = (args.review_sheet.parent / row["selectedModelOutputFile"]).resolve()
        reviewer_path = (args.review_sheet.parent / row["selectedReviewFile"]).resolve()
        # Paths in exported sheets are relative to the run root; the review CSV
        # lives one directory below that root.
        if not translator_path.is_file():
            translator_path = (args.review_sheet.parent.parent / row["selectedModelOutputFile"]).resolve()
        if not reviewer_path.is_file():
            reviewer_path = (args.review_sheet.parent.parent / row["selectedReviewFile"]).resolve()
        translator_id, translator_model, translated = response_content(translator_path)
        reviewer_id, reviewer_model, reviewed = response_content(reviewer_path)
        require(translated.get("translationGroupId") == group_id
                and translated.get("sourceUnitIds") == source_ids,
                f"Cached translator response belongs to a different group: {group_id}")
        semantic = _semantic_review(reviewed, group_id, source_ids)
        translator_ids.append(translator_id)
        reviewer_ids.append(reviewer_id)
        translator_models.add(translator_model)
        reviewer_models.add(reviewer_model)
        response_caches.extend((
            {"role": "translator", "translationGroupId": group_id,
             "path": str(translator_path), "sha256": file_hash(translator_path),
             "responseId": translator_id},
            {"role": "reviewer", "translationGroupId": group_id,
             "path": str(reviewer_path), "sha256": file_hash(reviewer_path),
             "responseId": reviewer_id},
        ))
        groups.append({
            "translationGroupId": group_id,
            "sourceUnitIds": source_ids,
            "targetUtterances": [target],
            "coverage": [{"sourceUnitId": source_id, "targetText": target}
                         for source_id in source_ids],
            "semanticReview": semantic,
            "translatorRequestId": translator_id,
            "reviewerRequestId": reviewer_id,
        })

    require(len(set(translator_ids)) == len(translator_ids)
            and len(set(reviewer_ids)) == len(reviewer_ids)
            and not set(translator_ids).intersection(reviewer_ids),
            "Cached translator and reviewer response IDs are duplicated or overlap")
    require(len(translator_models) == len(reviewer_models) == 1,
            "Cached response model identity is inconsistent within a lane")
    require(next(iter(translator_models)) == policy["translator"]["model"]
            and next(iter(reviewer_models)) == policy["reviewer"]["model"],
            "Cached response models differ from the frozen policy")

    evidence = {
        **request,
        "generation": {
            "translator": {"model": next(iter(translator_models)),
                           "promptVersion": policy["translator"]["promptVersion"],
                           "requestIds": list(dict.fromkeys(translator_ids))},
            "reviewer": {"model": next(iter(reviewer_models)),
                         "promptVersion": policy["reviewer"]["promptVersion"],
                         "requestIds": list(dict.fromkeys(reviewer_ids))},
        },
        "groups": groups,
    }
    plugin_hash = policy["languageReview"]["pluginImplementationSha256"]
    language_receipt = producer.run_language_plugin(
        source, anchor, policy, request, evidence, args.plugin, plugin_hash)
    candidate_groups: list[dict[str, Any]] = []
    for group, plugin_group in zip(groups, language_receipt["groupReviews"]):
        candidate_group = {key: group[key] for key in (
            "translationGroupId", "sourceUnitIds", "targetUtterances", "coverage", "semanticReview")}
        candidate_group["targetText"] = "".join(group["targetUtterances"])
        candidate_group["languageReview"] = {
            "status": plugin_group["status"],
            "pluginId": language_receipt["pluginId"],
            "policySha256": policy_tools.validate_policy(policy)["languageReviewPolicySha256"],
            "checks": plugin_group["checks"],
        }
        candidate_groups.append(candidate_group)

    reviewed_at = args.reviewed_at or decision.get("recordedAt")
    reviewer = args.reviewer
    require(isinstance(reviewer, str) and reviewer.strip(), "--reviewer is required")
    require(human_override.handoff._reviewed_at(reviewed_at),
            "A timezone-aware --reviewed-at or decision recordedAt is required")
    candidate = {
        "schemaVersion": "sermon-target-language-candidate-v2",
        "sourceLocale": "en",
        "targetLocale": locale,
        "englishSourcePackageJsonSha256": interpretation.json_sha256(source),
        "anchorManifestSha256": interpretation.json_sha256(anchor),
        "translationPolicySha256": request["translationPolicySha256"],
        "status": "human_override_approved",
        "releaseEligible": False,
        "generation": evidence["generation"],
        "groups": candidate_groups,
        "modelReview": {
            "status": "pass" if all(group["semanticReview"]["status"] == "pass" for group in candidate_groups)
            else "fail",
            "reviewedGroupIds": group_ids,
        },
        "humanReview": {
            "translation": "approved", "reviewer": reviewer.strip(),
            "reviewedAt": reviewed_at, "reviewedGroupIds": group_ids,
        },
    }
    human_override._validate_candidate_binding(source, anchor, candidate)

    exceptions: list[dict[str, Any]] = []
    for group in candidate_groups:
        findings = human_override._findings(group)
        if findings:
            exceptions.append({
                "translationGroupId": group["translationGroupId"],
                "sourceUnitIds": group["sourceUnitIds"],
                "targetTextSha256": hashlib.sha256(group["targetText"].encode("utf-8")).hexdigest(),
                "machineFindings": findings,
                "disposition": "accepted_as_is",
                "rationale": RATIONALE,
            })
    require(bool(exceptions), "No current machine-failing groups were found for this override receipt")
    receipt = {
        "schemaVersion": SCHEMA,
        "decision": "approved_with_exceptions",
        "targetLocale": locale,
        "englishSourcePackageJsonSha256": interpretation.json_sha256(source),
        "anchorManifestJsonSha256": interpretation.json_sha256(anchor),
        "translationPolicySha256": candidate["translationPolicySha256"],
        "candidateJsonSha256": interpretation.json_sha256(candidate),
        "reviewer": reviewer.strip(),
        "reviewedAt": reviewed_at,
        "reviewedGroupIds": group_ids,
        # Bind the unchanged top-level machine-review summary exactly as it
        # appears on the candidate, including a fail status.
        "modelReview": json.loads(json.dumps(candidate["modelReview"])),
        "reviewSheet": {"path": str(args.review_sheet.resolve()), "sha256": sheet_hash,
                        "bytes": args.review_sheet.stat().st_size},
        "reviewDecision": {
            "path": str(args.review_decision.resolve()),
            "sha256": file_hash(args.review_decision),
            "jsonSha256": interpretation.json_sha256(decision),
            "userMessageItemId": str(decision["userMessageItemId"]),
            "userStatement": decision["userStatement"],
        },
        "responseCaches": response_caches,
        "groupOverrides": exceptions,
        "humanApproval": True,
        "machineEvidenceChanged": False,
        "releaseEligible": False,
        "disclosure": DISCLOSURE,
    }
    human_override._schema(receipt, SCHEMA + ".schema.json")
    human_override.validate_override_receipt(source, anchor, candidate, receipt)
    return candidate, receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--english-source-package", required=True, type=Path)
    parser.add_argument("--anchor", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--review-sheet", required=True, type=Path)
    parser.add_argument("--review-decision", required=True, type=Path)
    parser.add_argument("--plugin", required=True, type=Path)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at")
    parser.add_argument("--candidate-out", required=True, type=Path)
    parser.add_argument("--receipt-out", required=True, type=Path)
    args = parser.parse_args()
    require(args.candidate_out != args.receipt_out
            and not args.candidate_out.exists() and not args.receipt_out.exists(),
            "Choose two new, distinct output paths; existing artifacts are immutable")
    candidate, receipt = build(args)
    interpretation.write_json(args.candidate_out, candidate)
    interpretation.write_json(args.receipt_out, receipt)
    print(json.dumps({"status": "built", "locale": candidate["targetLocale"],
                      "groups": len(candidate["groups"]), "exceptions": len(receipt["groupOverrides"]),
                      "candidate": str(args.candidate_out.resolve()),
                      "receipt": str(args.receipt_out.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
