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

from jsonschema import Draft202012Validator, FormatChecker

try:
    from scripts import sermon_sentence_interpretation as interpretation
    from scripts import target_language_policy as policy_tools
except ImportError:  # Direct execution via ``python scripts/...``.
    import sermon_sentence_interpretation as interpretation
    import target_language_policy as policy_tools


CANDIDATE_SCHEMA = "sermon-target-language-candidate-v2"
SOURCE_PACKAGE_SCHEMA = "sermon-english-source-package-v1"
SPEECH_JOB_SCHEMA = "sermon-target-language-speech-job-v2"
REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_SCHEMA = "sermon-target-language-speech-adapter-v1"
HUMAN_REVIEW_RECEIPT_SCHEMA = "sermon-target-language-human-review-receipt-v1"
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


def validate_target_candidate(source_package: dict[str, Any], anchor: dict[str, Any], candidate: dict[str, Any], *,
                              require_human_approval: bool = True) -> dict[str, Any]:
    """Fail closed on locale identity, source coverage and review boundaries."""
    _require(source_package.get("schemaVersion") == SOURCE_PACKAGE_SCHEMA,
             "Unsupported English Source Package")
    _require(source_package.get("status") == "ready_for_translation"
             and source_package.get("translationEligible") is True,
             "English Source Package is not approved for translation")
    _require(interpretation.is_supported_anchor_manifest(anchor), "Unsupported anchor manifest")
    _require(candidate.get("schemaVersion") == CANDIDATE_SCHEMA,
             "Unsupported target-language candidate")
    _require(candidate.get("sourceLocale") == "en", "Target candidate source locale must be en")
    _require(candidate.get("englishSourcePackageJsonSha256")
             == interpretation.json_sha256(source_package),
             "Target candidate belongs to another English Source Package")
    _require(source_package.get("anchors", {}).get("artifact", {}).get("jsonSha256")
             == interpretation.json_sha256(anchor),
             "English Source Package belongs to another anchor manifest")
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


def validate_policy_binding(candidate: dict[str, Any], policy: dict[str, Any]) -> None:
    result = policy_tools.validate_policy(policy)
    _require(policy["targetLocale"] == candidate["targetLocale"],
             "Target-Language Policy locale differs from candidate")
    if policy["schemaVersion"] == policy_tools.POLICY_V2:
        _require(policy["sourceScope"]["englishSourcePackageJsonSha256"]
                 == candidate["englishSourcePackageJsonSha256"]
                 and policy["sourceScope"]["anchorManifestSha256"]
                 == candidate["anchorManifestSha256"],
                 "Source-scoped policy differs from target candidate source")
    _require(candidate["translationPolicySha256"] == result["translationPolicySha256"],
             "Target candidate belongs to another Target-Language Policy")
    _require(result["productionPolicyReady"],
             "Target-Language Policy has unresolved scripture, terminology, or language-review gates")
    for stage in ("translator", "reviewer"):
        expected = policy[stage]
        actual = candidate["generation"][stage]
        # A model alias resolving to another response identity needs a new
        # frozen policy; the old policy hash must not silently cover drift.
        _require(actual["model"] == expected["model"]
                 and actual["promptVersion"] == expected["promptVersion"],
                 f"Target candidate {stage} generation differs from policy")
    required_checks = policy["languageReview"]["requiredChecks"]
    for group in candidate["groups"]:
        _require(group["languageReview"]["pluginId"] == policy["languageReview"]["pluginId"]
                 and group["languageReview"]["policySha256"] == result["languageReviewPolicySha256"],
                 "Target candidate language review belongs to another policy")
        checks = group["languageReview"]["checks"]
        _require(len(checks) == len(required_checks)
                 and {check["checkId"] for check in checks} == set(required_checks),
                 "Target candidate language review does not cover every required policy check")


def _validate_schema(value: dict[str, Any], filename: str, label: str) -> None:
    schema = json.loads((REPO_ROOT / "schemas" / filename).read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    _require(not errors, f"Invalid {label}: {errors[0].message}" if errors else "")


def validate_human_review_receipt(source_package: dict[str, Any], anchor: dict[str, Any],
                                  candidate: dict[str, Any], receipt: dict[str, Any]) -> None:
    """Require an independently stored, exact-candidate human decision before speech."""
    _validate_schema(receipt, "sermon-target-language-human-review-receipt-v1.schema.json",
                     "human review receipt")
    group_ids = [group["translationGroupId"] for group in candidate["groups"]]
    human = candidate["humanReview"]
    _require(receipt["decision"] == "approved"
             and receipt["targetLocale"] == candidate["targetLocale"]
             and receipt["englishSourcePackageJsonSha256"] == interpretation.json_sha256(source_package)
             and receipt["anchorManifestJsonSha256"] == interpretation.json_sha256(anchor)
             and receipt["translationPolicySha256"] == candidate["translationPolicySha256"]
             and receipt["candidateJsonSha256"] == interpretation.json_sha256(candidate),
             "Human review receipt does not bind the approved candidate and source")
    _require(receipt["reviewer"] == human["reviewer"]
             and receipt["reviewedAt"] == human["reviewedAt"]
             and receipt["reviewedGroupIds"] == group_ids
             and human["reviewedGroupIds"] == group_ids
             and [row["translationGroupId"] for row in receipt["groupReviews"]] == group_ids
             and all(row["decision"] == "approved" for row in receipt["groupReviews"]),
             "Human review receipt has missing, rejected, or mismatched group reviews")


def validate_adapter(adapter: dict[str, Any], target_locale: str,
                     registry: dict[str, Any]) -> None:
    """Bind the adapter to registry identity, authorized purpose, and locale evidence."""
    _validate_schema(adapter, "sermon-target-language-speech-adapter-v1.schema.json", "speech adapter")
    _validate_schema(registry, "sermon-speaker-voice-registry-v1.schema.json", "Speaker Voice Registry")
    _require(adapter["targetLocale"] == target_locale, "Speech adapter locale differs from target candidate")
    _require(adapter["registryJsonSha256"] == interpretation.json_sha256(registry),
             "Speech adapter belongs to another Speaker Voice Registry")
    speakers = [row for row in registry["speakers"] if row["speakerId"] == adapter["speakerId"]]
    _require(len(speakers) == 1, "Speech adapter speaker is not uniquely registered")
    speaker = speakers[0]
    _require(speaker["speakerKey"] == adapter["speakerKey"] == adapter["voice"],
             "Speech adapter voice differs from registered speaker key")
    capabilities = [row for row in speaker["localeCapabilities"] if row["targetLocale"] == target_locale]
    _require(len(capabilities) == 1 and capabilities[0]["status"] != "unsupported",
             "Speech adapter locale capability is unavailable")
    capability = capabilities[0]
    authorization = speaker["authorization"]
    _require(authorization["status"] == "authorized"
             and adapter["authorizationPurpose"] in authorization["purposes"]
             and bool(authorization["evidence"]),
             "Speech adapter voice purpose is not authorized")
    _require(adapter["authorizationEvidenceSha256"] == interpretation.json_sha256(authorization["evidence"]),
             "Speech adapter authorization evidence changed")
    _require(adapter["capabilityEvidenceSha256"] == interpretation.json_sha256(capability["reviewEvidence"]),
             "Speech adapter locale review evidence changed")
    override = capability.get("adapterOverride")
    if override:
        expected_adapter = override["adapter"]
        expected_model = override["model"]
        expected_revision = override["revision"]
        expected_ref = override["conditioningRef"]
        expected_hash = expected_ref.rsplit("/", 1)[-1]
        if "provider" in override:
            _require(adapter["provider"] == override["provider"],
                     "Speech adapter provider differs from registry override")
    else:
        expected_adapter = "qwen3_tts_sft"
        expected_model = registry["baseModel"]["model"]
        expected_revision = registry["baseModel"]["revision"]
        expected_ref = speaker["checkpoint"]["checkpointRef"]
        expected_hash = speaker["checkpoint"]["checkpointSha256"]
        _require(adapter["provider"] == registry["baseModel"]["provider"],
                 "Speech adapter provider differs from registry")
    _require(adapter["adapterId"] == expected_adapter
             and adapter["model"] == expected_model
             and adapter["modelRevision"] == expected_revision
             and adapter["conditioningRef"] == expected_ref
             and adapter["conditioningSha256"] == expected_hash
             and adapter["languageParameter"] == capability["modelLanguage"],
             "Speech adapter model, checkpoint, or language differs from registry")
    status = adapter["capabilityStatus"]
    if status == "verified":
        purpose = "chinese_dubbing" if target_locale == "zh-Hans" else "multilingual_dubbing"
        _require(adapter["authorizationPurpose"] == purpose
                 and capability["status"] == "human_reviewed"
                 and bool(capability["reviewEvidence"])
                 and (not override or bool(override.get("provider"))),
                 "Verified speech adapter lacks production authorization or human-reviewed locale capability")
    elif status == "candidate":
        _require(capability["status"] in {"candidate", "human_reviewed"},
                 "Candidate speech adapter lacks registered locale capability")
    else:
        _require(status == "unverified_poc", "Invalid speech adapter capability status")


def prepare_job(source_package_path: Path, anchor_path: Path, candidate_path: Path, policy_path: Path,
                human_review_receipt_path: Path, adapter_path: Path, registry_path: Path,
                out: Path) -> dict[str, Any]:
    _require(not out.exists(), "Use a new speech job directory; prior jobs are immutable")
    for path in (source_package_path, anchor_path, candidate_path, policy_path,
                 human_review_receipt_path, adapter_path, registry_path):
        _require(path.is_file(), f"Missing input: {path}")
    source_package, anchor, candidate, policy, human_review_receipt, adapter, registry = (
        _load(path) for path in (source_package_path, anchor_path, candidate_path, policy_path,
                                 human_review_receipt_path, adapter_path, registry_path)
    )
    _validate_schema(candidate, "sermon-target-language-candidate-v2.schema.json", "target candidate")
    identity = validate_target_candidate(source_package, anchor, candidate)
    locale = identity["targetLocale"]
    validate_policy_binding(candidate, policy)
    validate_human_review_receipt(source_package, anchor, candidate, human_review_receipt)
    validate_adapter(adapter, locale, registry)
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
            "englishSourcePackage": {
                "path": str(source_package_path.resolve()),
                "sha256": interpretation.sha256(source_package_path),
                "jsonSha256": interpretation.json_sha256(source_package),
            },
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
            "humanReviewReceipt": {
                "path": str(human_review_receipt_path.resolve()),
                "sha256": interpretation.sha256(human_review_receipt_path),
                "jsonSha256": interpretation.json_sha256(human_review_receipt),
            },
            "targetLanguagePolicy": {
                "path": str(policy_path.resolve()),
                "sha256": interpretation.sha256(policy_path),
                "jsonSha256": interpretation.json_sha256(policy),
            },
            "speakerRegistry": {
                "path": str(registry_path.resolve()),
                "sha256": interpretation.sha256(registry_path),
                "jsonSha256": interpretation.json_sha256(registry),
            },
        },
        "adapter": {
            key: adapter[key] for key in (
                "adapterId", "adapterVersion", "provider", "model", "modelRevision",
                "voice", "speakerId", "speakerKey", "conditioningRef", "conditioningSha256",
                "registryJsonSha256", "authorizationPurpose", "authorizationEvidenceSha256",
                "capabilityEvidenceSha256", "languageParameter", "capabilityStatus",
                "normalizationPolicySha256", "asrScreeningPolicySha256", "subtitlePolicySha256",
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
    _validate_schema(job, "sermon-target-language-speech-job-v2.schema.json", "speech job")
    out.mkdir(parents=True)
    interpretation.write_json(out / "job.json", job)
    return job


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--english-source-package", type=Path, required=True)
    parser.add_argument("--anchor", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--human-review-receipt", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--speaker-registry", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    job = prepare_job(
        args.english_source_package, args.anchor, args.candidate, args.policy,
        args.human_review_receipt,
        args.adapter, args.speaker_registry, args.out,
    )
    print(json.dumps({
        "status": job["status"],
        "targetLocale": job["targetLocale"],
        "synthesisEligible": job["synthesisEligible"],
        "job": str((args.out / "job.json").resolve()),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
