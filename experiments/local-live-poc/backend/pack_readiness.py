from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from .content_pack import (
    CONTEXT_POLICY_LEVELS,
    INJECTABLE_STATUSES,
    PackValidationError,
    load_pack,
    sha256_file,
)


MANIFEST_SCHEMA_VERSION = "weekly-context-pack-v2"
READINESS_SCHEMA_VERSION = "pack-readiness-v1"
MESSAGE_MATCH_STATUSES = {"unknown", "inferred", "human_confirmed", "rejected"}
def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _parse_datetime(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise PackValidationError(f"{field} must be an ISO-8601 datetime") from error
    if parsed.tzinfo is None:
        raise PackValidationError(f"{field} must include a timezone offset")
    return parsed


def _read_nonnegative_int(
    value: Any,
    field: str,
    blockers: list[str],
) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        blockers.append(f"invalid_nonnegative_integer:{field}")
        return None
    if parsed < 0:
        blockers.append(f"invalid_nonnegative_integer:{field}")
        return None
    return parsed


def _read_json(path: str | Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PackValidationError(f"unable to read {label}: {error}") from error
    if not isinstance(value, dict):
        raise PackValidationError(f"{label} must contain a JSON object")
    return value


def _write_json(path: str | Path, value: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def derive_pack_capabilities(
    pack: dict[str, Any],
    *,
    asr_phrase_candidate_count: int = 0,
) -> tuple[dict[str, bool], dict[str, int]]:
    entries = pack.get("entries") if isinstance(pack.get("entries"), list) else []
    approved_terms: set[tuple[str, str]] = set()
    verified_scripture: set[str] = set()
    reviewed_examples = 0
    machine_translation_violations = 0

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        injectable_terms = entry.get("injectableTerms")
        for term in injectable_terms if isinstance(injectable_terms, list) else []:
            if not isinstance(term, dict):
                continue
            source = _clean_text(term.get("source"))
            target = _clean_text(term.get("preferredZh"))
            if source and target:
                approved_terms.add((source, target))
        scripture_refs = entry.get("injectableScriptureRefs")
        for reference in scripture_refs if isinstance(scripture_refs, list) else []:
            cleaned = _clean_text(reference)
            if cleaned:
                verified_scripture.add(cleaned)
        if bool(entry.get("canInjectTranslation")):
            reviewed_examples += 1
            if _clean_text(entry.get("translationStatus")).lower() not in INJECTABLE_STATUSES:
                machine_translation_violations += 1

    counts = {
        "segmentCount": len(entries),
        "asrPhraseCandidateCount": max(0, int(asr_phrase_candidate_count)),
        "reviewedTermCount": len(approved_terms),
        "verifiedScriptureCount": len(verified_scripture),
        "reviewedExampleCount": reviewed_examples,
        "machineTranslationViolationCount": machine_translation_violations,
    }
    capabilities = {
        "englishMapReady": bool(entries),
        "asrPhraseCandidatesReady": counts["asrPhraseCandidateCount"] > 0,
        "approvedTermsReady": counts["reviewedTermCount"] > 0,
        "verifiedScriptureReady": counts["verifiedScriptureCount"] > 0,
        "reviewedExamplesReady": counts["reviewedExampleCount"] > 0,
    }
    return capabilities, counts


def select_context_policy(report: dict[str, Any], requested_policy: str | None = None) -> str:
    recommended = _clean_text(report.get("contextPolicy")) or "none"
    requested = _clean_text(requested_policy)
    if recommended not in CONTEXT_POLICY_LEVELS:
        raise PackValidationError(f"unsupported readiness contextPolicy: {recommended}")
    if not requested:
        return recommended
    if requested not in CONTEXT_POLICY_LEVELS:
        raise PackValidationError(f"unsupported requested contextPolicy: {requested}")
    if CONTEXT_POLICY_LEVELS[requested] <= CONTEXT_POLICY_LEVELS[recommended]:
        return requested
    return recommended


def evaluate_pack(
    manifest: dict[str, Any],
    pack: dict[str, Any],
    *,
    now: datetime | None = None,
    expected_target_sunday: str | None = None,
    actual_pack_sha256: str | None = None,
    actual_segments_sha256: str | None = None,
    actual_phrases_sha256: str | None = None,
    actual_asr_phrase_candidate_count: int | None = None,
    message_approval: dict[str, Any] | None = None,
    actual_message_approval_sha256: str | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)

    blockers: list[str] = []
    warnings: list[str] = []

    if manifest.get("schemaVersion") != MANIFEST_SCHEMA_VERSION:
        blockers.append("unsupported_manifest_schema")
    if pack.get("schemaVersion") != 1 or pack.get("packType") != "weekly":
        blockers.append("unsupported_weekly_pack_schema")
    if pack.get("status") != "active":
        blockers.append("pack_not_active")
    if _clean_text(manifest.get("packId")) != _clean_text(pack.get("packVersion")):
        blockers.append("pack_id_mismatch")

    target_sunday = _clean_text(manifest.get("targetSunday"))
    if not target_sunday:
        blockers.append("target_sunday_missing")
    else:
        try:
            parsed_target_sunday = datetime.strptime(target_sunday, "%Y-%m-%d").date()
            if parsed_target_sunday.weekday() != 6:
                blockers.append("target_sunday_not_sunday")
        except ValueError:
            blockers.append("target_sunday_invalid")
    if expected_target_sunday and target_sunday != expected_target_sunday:
        blockers.append("target_sunday_mismatch")

    message_identity = manifest.get("messageIdentity")
    if not isinstance(message_identity, dict):
        message_identity = {}
        blockers.append("message_identity_missing")
    match_status = _clean_text(message_identity.get("matchStatus")).lower()
    if match_status not in MESSAGE_MATCH_STATUSES:
        blockers.append("message_match_status_invalid")
    elif match_status != "human_confirmed":
        blockers.append(f"message_match_not_confirmed:{match_status or 'missing'}")
    message_key = _clean_text(message_identity.get("messageKey"))
    if not message_key:
        blockers.append("message_key_missing")

    approval_summary = (
        message_identity.get("approval")
        if isinstance(message_identity.get("approval"), dict)
        else {}
    )
    if match_status == "human_confirmed":
        if not message_approval:
            blockers.append("message_approval_file_missing")
        else:
            if message_approval.get("schemaVersion") != "saturday-message-identity-approval-v1":
                blockers.append("message_approval_schema_invalid")
            if message_approval.get("status") != "approved" or message_approval.get("humanApproval") is not True:
                blockers.append("message_approval_not_human_approved")
            if _clean_text(message_approval.get("matchStatus")) != "human_confirmed":
                blockers.append("message_approval_match_status_invalid")
            if _clean_text(message_approval.get("messageKey")) != message_key:
                blockers.append("message_approval_message_key_mismatch")
            if _clean_text(message_approval.get("targetSunday")) != target_sunday:
                blockers.append("message_approval_target_sunday_mismatch")
            if not _clean_text(message_approval.get("approvedBy")):
                blockers.append("message_approval_reviewer_missing")
            try:
                _parse_datetime(message_approval.get("approvedAt"), "messageApproval.approvedAt")
            except PackValidationError as error:
                blockers.append(str(error))
        if _clean_text(approval_summary.get("approvedBy")) != _clean_text(
            (message_approval or {}).get("approvedBy")
        ):
            blockers.append("message_approval_reviewer_mismatch")
        if _clean_text(approval_summary.get("approvedAt")) != _clean_text(
            (message_approval or {}).get("approvedAt")
        ):
            blockers.append("message_approval_timestamp_mismatch")
        if not actual_message_approval_sha256:
            blockers.append("message_approval_file_hash_missing")

    source_service_date = _clean_text(message_identity.get("sourceServiceDate"))
    try:
        datetime.strptime(source_service_date, "%Y-%m-%d")
    except ValueError:
        blockers.append("source_service_date_invalid")
    if source_service_date and _clean_text(pack.get("serviceDate")) != source_service_date:
        blockers.append("source_service_date_mismatch")
    if match_status == "human_confirmed" and _clean_text(
        (message_approval or {}).get("sourceServiceDate")
    ) != source_service_date:
        blockers.append("message_approval_source_service_date_mismatch")

    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
        blockers.append("manifest_provenance_missing")
    pack_provenance = pack.get("provenance")
    if not isinstance(pack_provenance, dict):
        pack_provenance = {}
        blockers.append("pack_provenance_missing")
    if _clean_text(provenance.get("sourceId")) != _clean_text(pack_provenance.get("sourceId")):
        blockers.append("source_id_mismatch")
    if not _clean_text(provenance.get("sourceUrlHash")):
        blockers.append("source_url_hash_missing")
    sermon_clip_sha = _clean_text(provenance.get("sermonClipSha256")).lower()
    if sermon_clip_sha != _clean_text(pack_provenance.get("audioSha256")).lower():
        blockers.append("sermon_clip_hash_mismatch")
    for key in ("sourceAudioSha256", "sermonClipSha256", "segmentSourceSha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", _clean_text(provenance.get(key)).lower()):
            blockers.append(f"provenance_hash_invalid:{key}")

    entries = pack.get("entries") if isinstance(pack.get("entries"), list) else []
    if not entries:
        blockers.append("english_map_empty")
    sequences = [entry.get("sequence") for entry in entries if isinstance(entry, dict)]
    if sequences != list(range(1, len(entries) + 1)):
        blockers.append("segment_sequence_not_contiguous")
    segment_ids = [_clean_text(entry.get("segmentId")) for entry in entries if isinstance(entry, dict)]
    if any(not value for value in segment_ids) or len(set(segment_ids)) != len(segment_ids):
        blockers.append("segment_ids_invalid")
    if any(not _clean_text(entry.get("sourceTextEn")) for entry in entries if isinstance(entry, dict)):
        blockers.append("english_segment_empty")
    declared_segment_count = _read_nonnegative_int(
        pack_provenance.get("segmentCount"),
        "pack.provenance.segmentCount",
        blockers,
    )
    if declared_segment_count is not None and declared_segment_count != len(entries):
        blockers.append("segment_count_mismatch")

    manifest_policy = manifest.get("policy") if isinstance(manifest.get("policy"), dict) else {}
    pack_policy = pack.get("policy") if isinstance(pack.get("policy"), dict) else {}
    if manifest_policy.get("currentLiveEnglishIsSourceOfTruth") is not True:
        blockers.append("live_english_source_policy_invalid")
    if manifest_policy.get("machineTranslationInjectable") is not False:
        blockers.append("manifest_machine_translation_policy_invalid")
    if pack_policy.get("currentLiveEnglishIsSourceOfTruth") is not True:
        blockers.append("pack_live_english_source_policy_invalid")
    if pack_policy.get("machineTranslationInjectable") is not False:
        blockers.append("pack_machine_translation_policy_invalid")

    validity = manifest.get("validity")
    if not isinstance(validity, dict):
        validity = {}
        blockers.append("manifest_validity_missing")
    validity_timezone = _clean_text(validity.get("timezone"))
    if not validity_timezone or validity_timezone != _clean_text(pack.get("validUntilTimezone")):
        blockers.append("validity_timezone_mismatch")
    try:
        not_before = _parse_datetime(validity.get("notBefore"), "validity.notBefore")
        valid_until = _parse_datetime(validity.get("validUntil"), "validity.validUntil")
        if not_before > valid_until:
            blockers.append("validity_window_invalid")
        if current_time < not_before.astimezone(timezone.utc):
            blockers.append("pack_not_yet_valid")
        if current_time > valid_until.astimezone(timezone.utc):
            blockers.append("pack_expired")
    except PackValidationError as error:
        blockers.append(str(error))
    try:
        legacy_valid_until = _parse_datetime(pack.get("validUntil"), "pack.validUntil")
        if current_time > legacy_valid_until.astimezone(timezone.utc):
            blockers.append("legacy_pack_expired")
    except PackValidationError as error:
        blockers.append(str(error))

    artifact_manifest = manifest.get("artifacts")
    if not isinstance(artifact_manifest, dict):
        artifact_manifest = {}
        blockers.append("artifact_manifest_missing")
    expected_pack_sha = _clean_text(
        (artifact_manifest.get("weeklyPack") or {}).get("sha256")
        if isinstance(artifact_manifest.get("weeklyPack"), dict)
        else ""
    ).lower()
    expected_segments_sha = _clean_text(
        (artifact_manifest.get("saturdaySegments") or {}).get("sha256")
        if isinstance(artifact_manifest.get("saturdaySegments"), dict)
        else ""
    ).lower()
    expected_phrases_sha = _clean_text(
        (artifact_manifest.get("asrPhraseCandidates") or {}).get("sha256")
        if isinstance(artifact_manifest.get("asrPhraseCandidates"), dict)
        else ""
    ).lower()
    expected_message_approval_sha = _clean_text(
        (artifact_manifest.get("messageIdentityApproval") or {}).get("sha256")
        if isinstance(artifact_manifest.get("messageIdentityApproval"), dict)
        else ""
    ).lower()
    for label, value in (
        ("weeklyPack", expected_pack_sha),
        ("saturdaySegments", expected_segments_sha),
        ("asrPhraseCandidates", expected_phrases_sha),
        ("messageIdentityApproval", expected_message_approval_sha),
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            blockers.append(f"artifact_hash_invalid:{label}")
    source_audio_artifact = (
        artifact_manifest.get("sourceAudio")
        if isinstance(artifact_manifest.get("sourceAudio"), dict)
        else {}
    )
    sermon_clip_artifact = (
        artifact_manifest.get("sermonClip")
        if isinstance(artifact_manifest.get("sermonClip"), dict)
        else {}
    )
    if _clean_text(source_audio_artifact.get("sha256")).lower() != _clean_text(
        provenance.get("sourceAudioSha256")
    ).lower():
        blockers.append("source_audio_manifest_hash_mismatch")
    if _clean_text(sermon_clip_artifact.get("sha256")).lower() != sermon_clip_sha:
        blockers.append("sermon_clip_manifest_hash_mismatch")
    if expected_segments_sha != _clean_text(provenance.get("segmentSourceSha256")).lower():
        blockers.append("segment_manifest_hash_mismatch")
    if actual_pack_sha256 and expected_pack_sha != actual_pack_sha256.lower():
        blockers.append("weekly_pack_file_hash_mismatch")
    if actual_segments_sha256 and expected_segments_sha != actual_segments_sha256.lower():
        blockers.append("segments_file_hash_mismatch")
    if actual_phrases_sha256 and expected_phrases_sha != actual_phrases_sha256.lower():
        blockers.append("asr_phrases_file_hash_mismatch")
    if (
        actual_message_approval_sha256
        and expected_message_approval_sha != actual_message_approval_sha256.lower()
    ):
        blockers.append("message_approval_file_hash_mismatch")
    if expected_message_approval_sha != _clean_text(approval_summary.get("sha256")).lower():
        blockers.append("message_approval_manifest_hash_mismatch")

    declared_review = manifest.get("review") if isinstance(manifest.get("review"), dict) else {}
    declared_phrase_count = _read_nonnegative_int(
        declared_review.get("asrPhraseCandidateCount"),
        "review.asrPhraseCandidateCount",
        blockers,
    )
    if declared_phrase_count is None:
        declared_phrase_count = 0
    phrase_count = (
        declared_phrase_count
        if actual_asr_phrase_candidate_count is None
        else max(0, int(actual_asr_phrase_candidate_count))
    )
    if declared_phrase_count != phrase_count:
        blockers.append("review_count_mismatch:asrPhraseCandidateCount")
    actual_capabilities, actual_counts = derive_pack_capabilities(
        pack,
        asr_phrase_candidate_count=phrase_count,
    )
    declared_capabilities = (
        manifest.get("capabilities") if isinstance(manifest.get("capabilities"), dict) else {}
    )
    for key, actual in actual_capabilities.items():
        if declared_capabilities.get(key) is not actual:
            blockers.append(f"capability_mismatch:{key}")
    for key in ("reviewedTermCount", "verifiedScriptureCount", "reviewedExampleCount"):
        declared_count = _read_nonnegative_int(declared_review.get(key), f"review.{key}", blockers)
        if declared_count is not None and declared_count != actual_counts[key]:
            blockers.append(f"review_count_mismatch:{key}")
    if declared_review.get("machineChineseInjectable") is not False:
        blockers.append("machine_chinese_policy_invalid")
    if actual_counts["machineTranslationViolationCount"]:
        blockers.append("machine_translation_marked_injectable")

    if blockers:
        runtime_mode = "none"
        context_policy = "none"
        alignment_enabled = False
        status = "invalid"
    elif actual_capabilities["reviewedExamplesReady"]:
        runtime_mode = "full_alignment"
        context_policy = "saturday_alignment_v1"
        alignment_enabled = True
        status = "ready"
    elif actual_capabilities["approvedTermsReady"] or actual_capabilities["verifiedScriptureReady"]:
        runtime_mode = "terms_only"
        context_policy = "weekly_terms_v1"
        alignment_enabled = False
        status = "ready"
    elif actual_capabilities["englishMapReady"]:
        runtime_mode = "english_map_only"
        context_policy = "english_alignment_v1"
        alignment_enabled = True
        status = "degraded"
        warnings.append("no_reviewed_prompt_context")
    else:
        runtime_mode = "none"
        context_policy = "none"
        alignment_enabled = False
        status = "invalid"

    return {
        "schemaVersion": READINESS_SCHEMA_VERSION,
        "status": status,
        "evaluatedAt": current_time.isoformat().replace("+00:00", "Z"),
        "targetSunday": target_sunday or None,
        "packVersion": pack.get("packVersion"),
        "runtimeMode": runtime_mode,
        "contextPolicy": context_policy,
        "alignmentEnabled": alignment_enabled,
        "capabilities": actual_capabilities,
        "counts": actual_counts,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
    }


def evaluate_pack_files(
    manifest_path: str | Path,
    pack_path: str | Path,
    *,
    segments_path: str | Path | None = None,
    phrases_path: str | Path | None = None,
    message_approval_path: str | Path | None = None,
    now: datetime | None = None,
    expected_target_sunday: str | None = None,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path, "weekly context manifest")
    pack = load_pack(pack_path)
    message_approval = (
        _read_json(message_approval_path, "message identity approval")
        if message_approval_path
        else None
    )
    phrase_count = None
    if phrases_path:
        phrase_lines = {
            _clean_text(line).casefold()
            for line in Path(phrases_path).read_text(encoding="utf-8").splitlines()
            if _clean_text(line)
        }
        phrase_count = len(phrase_lines)
    return evaluate_pack(
        manifest,
        pack,
        now=now,
        expected_target_sunday=expected_target_sunday,
        actual_pack_sha256=sha256_file(pack_path),
        actual_segments_sha256=sha256_file(segments_path) if segments_path else None,
        actual_phrases_sha256=sha256_file(phrases_path) if phrases_path else None,
        actual_asr_phrase_candidate_count=phrase_count,
        message_approval=message_approval,
        actual_message_approval_sha256=(
            sha256_file(message_approval_path) if message_approval_path else None
        ),
    )


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Validate a Sunday Runtime Pack and select a safe mode.")
    command.add_argument("--manifest", required=True)
    command.add_argument("--pack", required=True)
    command.add_argument("--segments")
    command.add_argument("--phrases")
    command.add_argument("--message-approval")
    command.add_argument("--expected-target-sunday")
    command.add_argument("--now", help="ISO-8601 evaluation time; defaults to current UTC time")
    command.add_argument("--output", required=True)
    return command


def main() -> None:
    arguments = parser().parse_args()
    evaluation_time = _parse_datetime(arguments.now, "now") if arguments.now else None
    report = evaluate_pack_files(
        arguments.manifest,
        arguments.pack,
        segments_path=arguments.segments,
        phrases_path=arguments.phrases,
        message_approval_path=arguments.message_approval,
        now=evaluation_time,
        expected_target_sunday=arguments.expected_target_sunday,
    )
    _write_json(arguments.output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if report["status"] in {"ready", "degraded"} else 2)


if __name__ == "__main__":
    main()
