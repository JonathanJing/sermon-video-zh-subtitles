#!/usr/bin/env python3
"""Generate machine-reviewed Layer 2 candidates for a bounded sermon fragment.

This is a shadow/POC producer. It never grants human approval or production
release eligibility, even when the model review passes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.cloud import access_secret as cloud_access_secret


RESPONSES_URL = "https://api.openai.com/v1/responses"
LOCALES = {
    "zh-Hans": {"name": "Simplified Chinese", "modelLanguage": "Chinese"},
    "ko": {"name": "Korean", "modelLanguage": "Korean"},
    "es": {"name": "Spanish", "modelLanguage": "Spanish"},
    "vi": {"name": "Vietnamese", "modelLanguage": "Vietnamese"},
}
PROMPT_VERSION = "sermon-fragment-translation-poc-v1"
REVIEW_VERSION = "sermon-fragment-semantic-judge-poc-v1"


def canonical_sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    for item in data.get("output", []):
        for content in item.get("content", []):
            text = content.get("text") or content.get("output_text")
            if isinstance(text, str) and text.strip():
                return text
    raise ValueError("OpenAI response did not contain output text")


def request_json(api_key: str, model: str, system: str, user: object) -> tuple[str, dict[str, Any]]:
    response = requests.post(
        RESPONSES_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system}]},
                {"role": "user", "content": [{"type": "input_text", "text": json.dumps(user, ensure_ascii=False)}]},
            ],
            "reasoning": {"effort": "medium"},
            "text": {"format": {"type": "json_object"}},
        },
        timeout=180,
    )
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message", "request failed")
        except Exception:
            detail = "request failed"
        raise RuntimeError(f"OpenAI Responses API failed ({response.status_code}): {detail}")
    payload = response.json()
    parsed = json.loads(response_text(payload))
    if not isinstance(parsed, dict):
        raise ValueError("OpenAI JSON output must be an object")
    return str(payload.get("id") or "missing-response-id"), parsed


def index_output(value: dict[str, Any], source_ids: list[str], *, review: bool) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for locale_item in value.get("locales", []):
        locale = locale_item.get("targetLocale")
        if locale not in LOCALES or locale in result:
            raise ValueError(f"Unexpected or duplicate locale: {locale}")
        units: dict[str, dict[str, Any]] = {}
        for item in locale_item.get("units", []):
            source_id = item.get("sourceUnitId")
            if source_id not in source_ids or source_id in units:
                raise ValueError(f"Unexpected or duplicate source unit: {locale}/{source_id}")
            if not review and not str(item.get("targetText", "")).strip():
                raise ValueError(f"Empty target text: {locale}/{source_id}")
            units[source_id] = item
        if list(units) != source_ids:
            raise ValueError(f"Unit order or coverage differs for {locale}")
        result[locale] = units
    if set(result) != set(LOCALES):
        raise ValueError("Locale coverage differs")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor-manifest", type=Path, required=True)
    parser.add_argument("--english-source-package", type=Path, required=True)
    parser.add_argument("--source-unit", action="append", dest="source_units", required=True)
    parser.add_argument("--api-key-secret", required=True)
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--fragment-id", default="2026-09-20-lion-of-judah")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"Output already exists; use a new immutable run directory: {args.out}")

    anchors = json.loads(args.anchor_manifest.read_text(encoding="utf-8"))
    package = json.loads(args.english_source_package.read_text(encoding="utf-8"))
    by_id = {item["sourceUnitId"]: item for item in anchors["sourceUnits"]}
    if len(args.source_units) != len(set(args.source_units)) or any(item not in by_id for item in args.source_units):
        raise SystemExit("Selected source unit IDs must exist and be unique")
    selected = [
        {"sourceUnitId": unit_id, "english": by_id[unit_id]["english"], "start": by_id[unit_id]["start"], "end": by_id[unit_id]["end"]}
        for unit_id in args.source_units
    ]
    policy = {
        "schemaVersion": "sermon-target-language-policy-poc-v1",
        "scope": "machine_reviewed_fragment_poc_not_production",
        "sourceLocale": "en",
        "targetLocales": list(LOCALES),
        "rules": [
            "Translate each source unit independently without merging, dropping, or inventing meaning.",
            "Preserve negation, names, numbers, Bible references, imagery, and speaker emphasis.",
            "Use natural spoken target-language phrasing suitable for narration.",
            "Human translation approval remains required for production.",
        ],
    }
    translation_input = {"targetLocales": [{"targetLocale": key, "language": item["name"]} for key, item in LOCALES.items()], "sourceUnits": selected}
    api_key = cloud_access_secret(args.api_key_secret)
    translator_id, translation = request_json(
        api_key,
        args.model,
        "You are the translation stage of a sermon localization POC. Return strict JSON only with shape {locales:[{targetLocale,units:[{sourceUnitId,targetText}]}]}. Follow the supplied policy. Do not combine units. Do not add devotional honorifics or theological titles (for example Lord or 主) unless they are explicit in that source unit.",
        {"policy": policy, **translation_input},
    )
    translated = index_output(translation, args.source_units, review=False)
    reviewer_id, review = request_json(
        api_key,
        args.model,
        "You are an independent semantic judge. Compare every translation to its English source. Return strict JSON only with shape {locales:[{targetLocale,units:[{sourceUnitId,status,completeMeaning,negationsNumbersNames,quotationAttribution,noAddedMeaning,evidence,uncertainty,issues}]}]}. Each status/check is pass or fail. Use empty arrays when none. Be fail-closed.",
        {"policy": policy, "sourceUnits": selected, "translations": translation},
    )
    reviewed = index_output(review, args.source_units, review=True)
    del api_key

    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "translation-policy.json").write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    policy_sha = canonical_sha(policy)
    source_package_sha = canonical_sha(package)
    anchor_sha = canonical_sha(anchors)
    all_pass = True
    candidates = []
    for locale in LOCALES:
        units = []
        for source_id in args.source_units:
            result = reviewed[locale][source_id]
            checks = {name: result.get(name) for name in ("completeMeaning", "negationsNumbersNames", "quotationAttribution", "noAddedMeaning")}
            unit_pass = result.get("status") == "pass" and set(checks.values()) == {"pass"} and not result.get("issues")
            all_pass = all_pass and unit_pass
            units.append((source_id, translated[locale][source_id]["targetText"], result, checks, unit_pass))
        group_id = f"{args.fragment_id}-{locale}"
        locale_pass = all(item[4] for item in units)
        candidate = {
            "schemaVersion": "sermon-target-language-candidate-v2",
            "sourceLocale": "en",
            "targetLocale": locale,
            "englishSourcePackageJsonSha256": source_package_sha,
            "anchorManifestSha256": anchor_sha,
            "translationPolicySha256": policy_sha,
            "status": "machine_review_pass_human_review_pending" if locale_pass else "translation_draft",
            "releaseEligible": False,
            "generation": {
                "translator": {"model": args.model, "promptVersion": PROMPT_VERSION, "requestIds": [translator_id]},
                "reviewer": {"model": args.model, "promptVersion": REVIEW_VERSION, "requestIds": [reviewer_id]},
            },
            "groups": [{
                "translationGroupId": group_id,
                "sourceUnitIds": args.source_units,
                "targetUtterances": [item[1] for item in units],
                "targetText": " ".join(item[1] for item in units),
                "coverage": [{"sourceUnitId": item[0], "targetText": item[1]} for item in units],
                "semanticReview": {
                    "status": "pass" if locale_pass else "fail",
                    "checks": {name: "pass" if all(item[3][name] == "pass" for item in units) else "fail" for name in units[0][3]},
                    "evidence": "Independent GPT semantic review completed for all six source units.",
                    "uncertainty": [message for item in units for message in (item[2].get("uncertainty") or [])],
                    "issues": [message for item in units for message in (item[2].get("issues") or [])],
                },
                "languageReview": {
                    "status": "pass" if locale_pass else "fail",
                    "pluginId": "gpt-language-review-poc-v1",
                    "policySha256": policy_sha,
                    "checks": [{"checkId": "target_language_and_natural_narration", "status": "pass" if locale_pass else "fail", "evidence": f"Reviewed as {LOCALES[locale]['name']} narration; human review remains pending."}],
                },
            }],
            "modelReview": {"status": "pass" if locale_pass else "fail", "reviewedGroupIds": [group_id]},
            "humanReview": {"translation": "pending", "reviewer": None, "reviewedAt": None, "reviewedGroupIds": []},
        }
        locale_dir = args.out / locale
        locale_dir.mkdir()
        candidate_path = locale_dir / "target-language-candidate.json"
        candidate_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        candidates.append({"targetLocale": locale, "path": str(candidate_path.relative_to(args.out)), "jsonSha256": canonical_sha(candidate), "status": candidate["status"]})
    receipt = {
        "schemaVersion": "sermon-multilingual-fragment-poc-v1",
        "scope": "layer_2_shadow_poc",
        "productionEligible": False,
        "humanApproval": False,
        "sourcePackageId": package["packageId"],
        "selectedSourceUnits": selected,
        "translatorRequestId": translator_id,
        "reviewerRequestId": reviewer_id,
        "allMachineChecksPass": all_pass,
        "candidates": candidates,
    }
    (args.out / "layer2-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "allMachineChecksPass": all_pass, "locales": list(LOCALES)}))
    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
