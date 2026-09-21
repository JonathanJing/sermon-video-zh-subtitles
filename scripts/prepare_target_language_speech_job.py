#!/usr/bin/env python3
"""Validate a Layer 2 target-language candidate and prepare the Layer 3 handoff.

This adapter intentionally performs no translation or synthesis. It binds one
human-approved target-language candidate to the shared English anchor and a
locale-specific speech adapter, while keeping every output path inside that
locale's directory.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

try:
    from scripts import sermon_sentence_interpretation as interpretation
except ImportError:  # Direct execution via ``python scripts/...``.
    import sermon_sentence_interpretation as interpretation


CANDIDATE_SCHEMA = "sermon-target-language-candidate-v2"
SPEECH_JOB_SCHEMA = "sermon-target-language-speech-job-v1"
ADAPTER_SCHEMA = "sermon-target-language-speech-adapter-v1"
SEMANTIC_CHECKS = (
    "completeMeaning",
    "negationsNumbersNames",
    "quotationAttribution",
    "noAddedMeaning",
)
LOCALE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def _reviewed_at(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def validate_target_candidate(anchor: dict[str, Any], candidate: dict[str, Any], *,
                              require_human_approval: bool = True) -> dict[str, Any]:
    """Fail closed on locale identity, source coverage and review boundaries."""
    _require(interpretation.is_supported_anchor_manifest(anchor), "Unsupported anchor manifest")
    _require(candidate.get("schemaVersion") == CANDIDATE_SCHEMA,
             "Unsupported target-language candidate")
    _require(candidate.get("sourceLocale") == "en", "Target candidate source locale must be en")
    locale = candidate.get("targetLocale")
    _require(isinstance(locale, str) and LOCALE.fullmatch(locale) is not None
             and locale.split("-", 1)[0] != "en", "Invalid target locale")
    _require(candidate.get("anchorManifestSha256") == interpretation.json_sha256(anchor),
             "Target candidate belongs to another anchor manifest")
    _require(isinstance(candidate.get("translationPolicySha256"), str)
             and re.fullmatch(r"[a-f0-9]{64}", candidate["translationPolicySha256"]) is not None,
             "Invalid translation policy hash")
    _require(candidate.get("releaseEligible") is False,
             "Layer 2 candidate must not claim release eligibility")

    groups = candidate.get("groups")
    _require(isinstance(groups, list) and groups, "Target candidate has no groups")
    expected_units = [unit["sourceUnitId"] for unit in anchor.get("sourceUnits", [])]
    assigned_units: list[str] = []
    group_ids: list[str] = []
    for group in groups:
        _require(isinstance(group, dict), "Invalid target-language group")
        group_id = group.get("translationGroupId")
        source_ids = group.get("sourceUnitIds")
        utterances = group.get("targetUtterances")
        _require(isinstance(group_id, str) and group_id and group_id not in group_ids,
                 "Invalid or duplicate translation group id")
        _require(isinstance(source_ids, list) and source_ids
                 and all(isinstance(item, str) and item for item in source_ids),
                 f"Invalid source units: {group_id}")
        _require(isinstance(utterances, list) and utterances
                 and all(isinstance(item, str) and item.strip() for item in utterances),
                 f"Invalid target utterances: {group_id}")
        _require(group.get("targetText") == "".join(item.strip() for item in utterances),
                 f"Target text differs from utterances: {group_id}")
        coverage = group.get("coverage")
        _require(isinstance(coverage, list)
                 and [item.get("sourceUnitId") for item in coverage if isinstance(item, dict)] == source_ids
                 and all(isinstance(item.get("targetText"), str) and item["targetText"].strip()
                         for item in coverage), f"Invalid source coverage: {group_id}")
        semantic = group.get("semanticReview", {})
        _require(semantic.get("status") == "pass"
                 and all(semantic.get("checks", {}).get(check) == "pass"
                         for check in SEMANTIC_CHECKS)
                 and not semantic.get("issues") and not semantic.get("uncertainty"),
                 f"Semantic review is not pass: {group_id}")
        language = group.get("languageReview", {})
        language_checks = language.get("checks")
        _require(language.get("status") == "pass"
                 and isinstance(language.get("pluginId"), str) and language["pluginId"]
                 and isinstance(language_checks, list) and language_checks
                 and all(check.get("status") == "pass" for check in language_checks
                         if isinstance(check, dict))
                 and len(language_checks) == sum(isinstance(check, dict) for check in language_checks),
                 f"Language review is not pass: {group_id}")
        assigned_units.extend(source_ids)
        group_ids.append(group_id)

    _require(assigned_units == expected_units,
             "Target candidate must cover every source unit exactly once and in order")
    model_review = candidate.get("modelReview", {})
    _require(model_review.get("status") == "pass"
             and model_review.get("reviewedGroupIds") == group_ids,
             "Independent model review is incomplete")
    human = candidate.get("humanReview", {})
    if require_human_approval:
        _require(candidate.get("status") == "human_translation_approved"
                 and human.get("translation") == "approved"
                 and isinstance(human.get("reviewer"), str) and human["reviewer"].strip()
                 and _reviewed_at(human.get("reviewedAt"))
                 and human.get("reviewedGroupIds") == group_ids,
                 "Human translation approval is required before Layer 3")
    return {"targetLocale": locale, "groupIds": group_ids, "sourceUnitIds": assigned_units}


def validate_adapter(adapter: dict[str, Any], target_locale: str) -> None:
    _require(adapter.get("schemaVersion") == ADAPTER_SCHEMA,
             "Unsupported target-language speech adapter")
    _require(adapter.get("targetLocale") == target_locale,
             "Speech adapter locale differs from target candidate")
    for key in ("adapterId", "adapterVersion", "model", "voice", "languageParameter"):
        _require(isinstance(adapter.get(key), str) and adapter[key].strip(),
                 f"Missing speech adapter field: {key}")
    _require(adapter.get("capabilityStatus") in {"unverified_poc", "verified"},
             "Invalid speech adapter capability status")
    for key in ("normalizationPolicySha256", "asrScreeningPolicySha256", "subtitlePolicySha256"):
        _require(isinstance(adapter.get(key), str)
                 and re.fullmatch(r"[a-f0-9]{64}", adapter[key]) is not None,
                 f"Invalid speech adapter hash: {key}")


def prepare_job(anchor_path: Path, candidate_path: Path, adapter_path: Path,
                out: Path) -> dict[str, Any]:
    _require(not out.exists(), "Use a new speech job directory; prior jobs are immutable")
    for path in (anchor_path, candidate_path, adapter_path):
        _require(path.is_file(), f"Missing input: {path}")
    anchor, candidate, adapter = (_load(path) for path in (anchor_path, candidate_path, adapter_path))
    identity = validate_target_candidate(anchor, candidate)
    locale = identity["targetLocale"]
    validate_adapter(adapter, locale)
    language_root = f"languages/{locale}"
    verified = adapter["capabilityStatus"] == "verified"
    job = {
        "schemaVersion": SPEECH_JOB_SCHEMA,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "status": ("prepared_for_target_language_speech" if verified
                   else "prepared_adapter_validation_required"),
        "sourceLocale": "en",
        "targetLocale": locale,
        "releaseEligible": False,
        "synthesisEligible": verified,
        "inputs": {
            "anchorManifest": {
                "path": str(anchor_path.resolve()),
                "sha256": interpretation.sha256(anchor_path),
                "jsonSha256": interpretation.json_sha256(anchor),
            },
            "targetLanguageCandidate": {
                "path": str(candidate_path.resolve()),
                "sha256": interpretation.sha256(candidate_path),
                "jsonSha256": interpretation.json_sha256(candidate),
            },
        },
        "adapter": {
            key: adapter[key] for key in (
                "adapterId", "adapterVersion", "model", "voice", "languageParameter",
                "capabilityStatus", "normalizationPolicySha256",
                "asrScreeningPolicySha256", "subtitlePolicySha256",
            )
        } | {"configSha256": interpretation.sha256(adapter_path)},
        "renderContract": {
            "textPolicy": "exact_human_approved_target_text",
            "ratePolicy": interpretation.RATE_POLICY,
            "playbackRate": 1.0,
            "postProcessing": "none_before_measurement",
            "humanListeningReview": "pending",
        },
        "units": [{
            "unitIndex": index,
            "translationGroupId": group["translationGroupId"],
            "sourceUnitIds": group["sourceUnitIds"],
            "text": group["targetText"],
            "outputRelativePath": f"{language_root}/audio/unit-{index:04d}.wav",
        } for index, group in enumerate(candidate["groups"])],
        "outputContract": {
            "languageRoot": language_root,
            "audioDirectory": f"{language_root}/audio",
            "synchronizationDirectory": f"{language_root}/synchronization",
        },
    }
    out.mkdir(parents=True)
    interpretation.write_json(out / "job.json", job)
    return job


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    job = prepare_job(args.anchor, args.candidate, args.adapter, args.out)
    print(json.dumps({
        "status": job["status"],
        "targetLocale": job["targetLocale"],
        "synthesisEligible": job["synthesisEligible"],
        "job": str((args.out / "job.json").resolve()),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
