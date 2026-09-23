#!/usr/bin/env python3
"""Compile independently reviewed Layer 2 evidence into a single-locale candidate.

``prepare`` writes a source-bound request with English units and no translations.
``admit`` consumes that request after an external translator, independent model
reviewer, and verified locale-review plugin have filled its ``generation`` and
``groups`` fields. This command performs no model calls and never grants human
approval. The separate review_target_language_candidate.py worksheet remains
the only path from this candidate to an approved Layer 2 artifact.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import runpy
from typing import Any

try:
    from scripts import prepare_target_language_speech_job as handoff
    from scripts import sermon_sentence_interpretation as interpretation
    from scripts import target_language_policy as policy_tools
except ImportError:  # Direct execution via ``python scripts/...``.
    import prepare_target_language_speech_job as handoff
    import sermon_sentence_interpretation as interpretation
    import target_language_policy as policy_tools


REQUEST_SCHEMA = "sermon-target-language-evidence-request-v1"
LANGUAGE_RECEIPT_SCHEMA = "sermon-target-language-plugin-receipt-v1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _load(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(result, dict), f"Expected JSON object: {path}")
    return result


def prepare_request(source: dict[str, Any], anchor: dict[str, Any],
                    policy: dict[str, Any]) -> dict[str, Any]:
    """Freeze exactly one source and locale; leave all generated fields blank."""
    _require(source.get("schemaVersion") == handoff.SOURCE_PACKAGE_SCHEMA
             and source.get("status") == "ready_for_translation"
             and source.get("translationEligible") is True,
             "Approved English Source Package required")
    _require(interpretation.is_supported_anchor_manifest(anchor),
             "Unsupported anchor manifest")
    units = anchor.get("sourceUnits", [])
    unit_ids = [unit.get("sourceUnitId") for unit in units if isinstance(unit, dict)]
    _require(bool(unit_ids) and len(unit_ids) == len(units)
             and len(unit_ids) == len(set(unit_ids))
             and all(isinstance(unit.get("english"), str) and unit["english"].strip()
                     for unit in units), "Anchor units lack unique IDs or English text")
    review = source.get("review", {})
    _require(review.get("humanApproval") is True
             and review.get("reviewedSourceUnitIds") == unit_ids
             and all(review.get("checks", {}).get(check) == "approved" for check in
                     ("sourceIdentity", "transcriptCompleteness", "wordAlignment",
                      "sentenceAndPauseBoundaries"))
             and source.get("source", {}).get("approvedWindow", {}).get("humanApproval") is True,
             "English source lacks complete human review or approved window")
    anchor_hash = interpretation.json_sha256(anchor)
    _require(source.get("anchors", {}).get("artifact", {}).get("jsonSha256") == anchor_hash,
             "Source package and anchor manifest differ")
    identity = policy_tools.validate_policy(policy)
    _require(identity["productionPolicyReady"],
             "Production policy has unresolved scripture, terminology, or language-review gates")
    return {
        "schemaVersion": REQUEST_SCHEMA,
        "sourceLocale": "en",
        "targetLocale": policy["targetLocale"],
        "englishSourcePackageJsonSha256": interpretation.json_sha256(source),
        "anchorManifestSha256": anchor_hash,
        "translationPolicySha256": identity["translationPolicySha256"],
        "sourceUnits": [{"sourceUnitId": unit["sourceUnitId"], "english": unit["english"]}
                        for unit in units],
        "generation": None,
        "groups": None,
    }


def admit_evidence(source: dict[str, Any], anchor: dict[str, Any],
                   policy: dict[str, Any], request: dict[str, Any],
                   evidence: dict[str, Any], language_receipt: dict[str, Any],
                   plugin_path: Path, expected_plugin_sha256: str) -> dict[str, Any]:
    """Validate externally produced evidence; preserve human review as pending."""
    expected = prepare_request(source, anchor, policy)
    _require(request == expected, "Layer 2 request was changed or belongs to another source/policy")
    for key in ("schemaVersion", "sourceLocale", "targetLocale",
                "englishSourcePackageJsonSha256", "anchorManifestSha256",
                "translationPolicySha256", "sourceUnits"):
        _require(evidence.get(key) == expected[key], f"Layer 2 evidence identity changed: {key}")
    _require(set(evidence) == set(expected), "Layer 2 evidence has missing or unexpected fields")
    generation = evidence.get("generation")
    groups = evidence.get("groups")
    _require(isinstance(generation, dict) and set(generation) == {"translator", "reviewer"},
             "Separate translator and reviewer receipts required")
    _require(isinstance(groups, list) and groups, "Reviewed translation groups required")
    translator_ids: list[str] = []
    reviewer_ids: list[str] = []
    candidate_groups: list[dict[str, Any]] = []
    group_keys = {
        "translationGroupId", "sourceUnitIds", "targetUtterances", "coverage",
        "semanticReview", "translatorRequestId", "reviewerRequestId",
    }
    for group in groups:
        _require(isinstance(group, dict) and set(group) == group_keys,
                 "Every group needs exact translation and independent review evidence")
        t_id, r_id = group["translatorRequestId"], group["reviewerRequestId"]
        _require(isinstance(t_id, str) and t_id.strip()
                 and isinstance(r_id, str) and r_id.strip() and t_id != r_id,
                 "Each group needs distinct nonempty translator and reviewer request IDs")
        translator_ids.append(t_id)
        reviewer_ids.append(r_id)
        utterances = group["targetUtterances"]
        _require(isinstance(utterances, list) and utterances
                 and all(isinstance(text, str) and text.strip() for text in utterances),
                 "Target utterances are missing")
        candidate_group = {key: copy.deepcopy(value) for key, value in group.items()
                           if key not in {"translatorRequestId", "reviewerRequestId"}}
        candidate_group["targetText"] = "".join(text.strip() for text in utterances)
        candidate_groups.append(candidate_group)
    t_receipt, r_receipt = generation["translator"], generation["reviewer"]
    _require(isinstance(t_receipt, dict) and isinstance(r_receipt, dict),
             "Model receipts must be objects")
    _require(t_receipt.get("requestIds") == list(dict.fromkeys(translator_ids))
             and r_receipt.get("requestIds") == list(dict.fromkeys(reviewer_ids))
             and not set(translator_ids).intersection(reviewer_ids),
             "Model request IDs do not bind separate translator and reviewer calls")
    actual_receipt = run_language_plugin(source, anchor, policy, request,
                                         evidence, plugin_path, expected_plugin_sha256)
    _require(language_receipt == actual_receipt,
             "Language plugin receipt is missing, stale, or differs from a fresh plugin run")
    for group, result in zip(candidate_groups, actual_receipt["groupReviews"]):
        _require(result["status"] == "pass", "Language plugin rejected a group")
        group["languageReview"] = {
            "status": result["status"], "pluginId": actual_receipt["pluginId"],
            "policySha256": actual_receipt["languageReviewPolicySha256"],
            "checks": result["checks"],
        }
    candidate = {
        "schemaVersion": handoff.CANDIDATE_SCHEMA,
        "sourceLocale": "en",
        "targetLocale": policy["targetLocale"],
        "englishSourcePackageJsonSha256": expected["englishSourcePackageJsonSha256"],
        "anchorManifestSha256": expected["anchorManifestSha256"],
        "translationPolicySha256": expected["translationPolicySha256"],
        "status": "machine_review_pass_human_review_pending",
        "releaseEligible": False,
        "generation": copy.deepcopy(generation),
        "groups": candidate_groups,
        "modelReview": {"status": "pass", "reviewedGroupIds":
                        [group["translationGroupId"] for group in candidate_groups]},
        "humanReview": {"translation": "pending", "reviewer": None,
                        "reviewedAt": None, "reviewedGroupIds": []},
    }
    handoff._validate_schema(candidate, "sermon-target-language-candidate-v2.schema.json",
                             "target candidate")
    handoff.validate_target_candidate(source, anchor, candidate, require_human_approval=False)
    handoff.validate_policy_binding(candidate, policy)
    return candidate


def run_language_plugin(source: dict[str, Any], anchor: dict[str, Any],
                        policy: dict[str, Any], request: dict[str, Any],
                        evidence: dict[str, Any], plugin_path: Path,
                        expected_plugin_sha256: str) -> dict[str, Any]:
    """Run a pinned locale plugin and return a source/text-bound receipt.

    The plugin is a reviewed Python module exposing PLUGIN_ID, PLUGIN_VERSION,
    and ``review_group(policy, english_units, group) -> list[check]``. Its checks
    are recalculated at admission; a pass string in translation evidence is
    never accepted as language-review evidence.
    """
    expected = prepare_request(source, anchor, policy)
    _require(request == expected, "Layer 2 request was changed or belongs to another source/policy")
    for key in ("schemaVersion", "sourceLocale", "targetLocale",
                "englishSourcePackageJsonSha256", "anchorManifestSha256",
                "translationPolicySha256", "sourceUnits"):
        _require(evidence.get(key) == expected[key], f"Layer 2 evidence identity changed: {key}")
    _require(plugin_path.is_file(), "Language plugin implementation is missing")
    implementation_sha = hashlib.sha256(plugin_path.read_bytes()).hexdigest()
    _require(expected_plugin_sha256 == implementation_sha,
             "Language plugin implementation hash changed")
    module = runpy.run_path(str(plugin_path))
    plugin_id = policy["languageReview"]["pluginId"]
    _require(module.get("PLUGIN_ID") == plugin_id
             and isinstance(module.get("PLUGIN_VERSION"), str)
             and module["PLUGIN_VERSION"].strip()
             and callable(module.get("review_group")),
             "Language plugin ID, version, or entry point is invalid")
    groups = evidence.get("groups")
    _require(isinstance(groups, list) and groups, "Language plugin needs translation groups")
    source_by_id = {row["sourceUnitId"]: row for row in expected["sourceUnits"]}
    required_checks = policy["languageReview"]["requiredChecks"]
    group_reviews = []
    for group in groups:
        _require(isinstance(group, dict), "Invalid language plugin group")
        group_id, unit_ids, utterances = (group.get(key) for key in
                                          ("translationGroupId", "sourceUnitIds", "targetUtterances"))
        _require(isinstance(group_id, str) and group_id
                 and isinstance(unit_ids, list) and unit_ids
                 and all(isinstance(unit_id, str) and unit_id in source_by_id for unit_id in unit_ids)
                 and isinstance(utterances, list) and utterances
                 and all(isinstance(text, str) and text.strip() for text in utterances),
                 "Language plugin group lacks bound source or target text")
        target_text = "".join(text.strip() for text in utterances)
        plugin_group = {
            "translationGroupId": group_id,
            "sourceUnitIds": unit_ids,
            "targetUtterances": utterances,
            "targetText": target_text,
        }
        checks = module["review_group"](
            copy.deepcopy(policy),
            copy.deepcopy([source_by_id[unit_id] for unit_id in unit_ids]),
            copy.deepcopy(plugin_group),
        )
        _require(isinstance(checks, list) and len(checks) == len(required_checks)
                 and all(isinstance(check, dict) and set(check)
                         == {"checkId", "status", "evidence"}
                         and check["checkId"] in required_checks
                         and check["status"] in {"pass", "fail"}
                         and isinstance(check["evidence"], str) and check["evidence"].strip()
                         for check in checks)
                 and [check["checkId"] for check in checks] == required_checks,
                 f"Language plugin omitted or changed required checks: {group_id}")
        group_reviews.append({
            "translationGroupId": group_id,
            "sourceUnitIds": unit_ids,
            "targetTextSha256": hashlib.sha256(target_text.encode("utf-8")).hexdigest(),
            "status": "pass" if all(check["status"] == "pass" for check in checks) else "fail",
            "checks": checks,
        })
    _require([row["translationGroupId"] for row in group_reviews]
             == [group["translationGroupId"] for group in groups],
             "Language plugin receipt group order changed")
    identity = policy_tools.validate_policy(policy)
    return {
        "schemaVersion": LANGUAGE_RECEIPT_SCHEMA,
        "englishSourcePackageJsonSha256": expected["englishSourcePackageJsonSha256"],
        "anchorManifestSha256": expected["anchorManifestSha256"],
        "targetLocale": expected["targetLocale"],
        "translationPolicySha256": expected["translationPolicySha256"],
        "languageReviewPolicySha256": identity["languageReviewPolicySha256"],
        "pluginId": plugin_id,
        "pluginVersion": module["PLUGIN_VERSION"],
        "pluginImplementationSha256": implementation_sha,
        "groupIds": [row["translationGroupId"] for row in group_reviews],
        "groupReviews": group_reviews,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "review-language", "admit"))
    parser.add_argument("--english-source-package", required=True, type=Path)
    parser.add_argument("--anchor", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--language-receipt", type=Path)
    parser.add_argument("--plugin", type=Path)
    parser.add_argument("--plugin-sha256")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    _require(not args.out.exists(), "Use a new output path; Layer 2 artifacts are immutable")
    source, anchor, policy = (_load(path) for path in
                              (args.english_source_package, args.anchor, args.policy))
    if args.command == "prepare":
        _require(args.request is None and args.evidence is None and args.language_receipt is None,
                 "prepare does not consume prior evidence")
        result = prepare_request(source, anchor, policy)
    else:
        _require(args.request is not None and args.evidence is not None,
                 "review-language and admit require the original request and completed evidence")
        _require(args.plugin is not None and args.plugin_sha256 is not None,
                 "A pinned language plugin is required")
        if args.command == "review-language":
            _require(args.language_receipt is None,
                     "review-language creates, not consumes, a plugin receipt")
            result = run_language_plugin(source, anchor, policy,
                                         _load(args.request), _load(args.evidence),
                                         args.plugin, args.plugin_sha256)
        else:
            _require(args.language_receipt is not None,
                     "admit requires a separate language plugin receipt")
            result = admit_evidence(source, anchor, policy,
                                    _load(args.request), _load(args.evidence),
                                    _load(args.language_receipt), args.plugin,
                                    args.plugin_sha256)
    interpretation.write_json(args.out, result)
    status = {"prepare": "source_bound_request", "review-language": "language_plugin_reviewed",
              "admit": "machine_review_pass_human_review_pending"}[args.command]
    print(json.dumps({"status": status,
                      "out": str(args.out.resolve())}))


if __name__ == "__main__":
    main()
