#!/usr/bin/env python3
"""Build the shared Layer 1 English Source Package.

The package binds one frozen English transcript/alignment artifact to one
clause-stable anchor manifest.  It is target-locale neutral: no translation
prompt, target text, TTS setting, or publication state is allowed here.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

try:
    from scripts import four_layer_measure as measure
except ImportError:  # Direct execution via ``python scripts/...``.
    import four_layer_measure as measure


SCHEMA_VERSION = "sermon-english-source-package-v1"
REVIEW_SCHEMA_VERSION = "sermon-english-source-review-v1"
REVIEW_SCHEMA_V2 = "sermon-english-source-review-v2"
LAYER2_CANDIDATE_OVERRIDE_DECISION = "approved_for_layer2_candidates_despite_machine_rejection"
MACHINE_JUDGE_SCHEMA_VERSION = "sermon-english-source-machine-judge-v1"
MACHINE_JUDGE_MODEL = "gpt-6-astra"
MACHINE_JUDGE_REASONING_EFFORT = "medium"
MACHINE_JUDGE_CHECKS = frozenset({
    "meaningPreserved",
    "negationsNumbersNames",
    "quotationAndClauseIntegrity",
    "timelineCoherent",
    "translationContextSufficient",
})
MACHINE_JUDGE_THRESHOLDS = {
    "requiredDeterministicCheckPassRate": 1.0,
    "requiredSentencePassRate": 1.0,
    "maximumHighRiskSentences": 0,
    "maximumUnresolvedIssues": 0,
}
SHA256 = re.compile(r"^[a-f0-9]{64}$")
APPROVED_CHECKS = (
    "sourceIdentity",
    "transcriptCompleteness",
    "wordAlignment",
    "sentenceAndPauseBoundaries",
)
MACHINE_AND_HUMAN_REVIEWABLE_ANCHOR_ISSUES = frozenset({
    "clause_unit_exceeds_target_without_safe_boundary",
})


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def artifact(path: Path, *, value: object | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"Bound artifact is missing: {resolved}")
    result = {"path": str(resolved), "sha256": file_sha256(resolved)}
    if value is not None:
        result["jsonSha256"] = json_sha256(value)
    return result


def _finite(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _sha_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and SHA256.fullmatch(value) else None


def _validate_service_date(value: str | None) -> None:
    if value is None:
        return
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValueError("service_date must use YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("service_date must be a real calendar date") from exc


def _validate_reviewed_at(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("English source review identity and time are required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("English source review time must be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("English source review time must include a timezone")


def _alignment_provider(summary: dict[str, Any]) -> str:
    identity = summary.get("pipelineInputIdentity")
    selected = summary.get("readingAligner")
    if not selected and isinstance(identity, dict):
        selected = identity.get("readingAligner")
    normalized = str(selected or "mfa").strip().lower()
    if normalized == "mfa":
        return "mfa"
    if "qwen" in normalized and "align" in normalized:
        return "qwen3-forced-aligner"
    return "other"


def _source_media(summary: dict[str, Any]) -> dict[str, Any] | None:
    identity = summary.get("pipelineInputIdentity")
    raw = identity.get("sourceAudio") if isinstance(identity, dict) else None
    digest = _sha_or_none(raw.get("sha256")) if isinstance(raw, dict) else None
    if digest is None:
        return None
    media: dict[str, Any] = {"sha256": digest}
    if isinstance(raw.get("sizeBytes"), int) and raw["sizeBytes"] >= 0:
        media["sizeBytes"] = raw["sizeBytes"]
    duration = summary.get("sourceDurationSeconds")
    if _finite(duration) and float(duration) > 0:
        media["durationSeconds"] = float(duration)
    return media


def source_gate_issues(media, start, end, approved):
    """Production source invariants shared by construction and read-side checks."""
    issues = []
    if not isinstance(media, dict) or _sha_or_none(media.get("sha256")) is None:
        issues.append({"stage": "source", "type": "source_media_identity_missing"})
    if not approved:
        issues.append({"stage": "source", "type": "approved_sermon_window_missing"})
    duration = media.get("durationSeconds") if isinstance(media, dict) else None
    if (not _finite(start) or not _finite(end) or not 0 <= start < end
            or (duration is not None and (not _finite(duration) or end > duration + 0.01))):
        issues.append({"stage": "source", "type": "source_window_incoherent"})
    return issues


def source_identity(source, transcript_artifact, anchor_artifact, review, machine_judge, implementation):
    """Use recorded implementation identity so valid older packages remain valid."""
    window, media = source["approvedWindow"], source["media"]
    approval = window["evidence"]
    return json_sha256({
        "sourceId": source["sourceId"], "sourceUrlHash": source["sourceUrlHash"],
        "serviceDate": source["serviceDate"],
        "approvedWindow": {"startSeconds": float(window["startSeconds"]), "endSeconds": float(window["endSeconds"])},
        "alignedSegmentsSha256": transcript_artifact["sha256"],
        "anchorManifestJsonSha256": anchor_artifact["jsonSha256"],
        "sourceMediaSha256": media.get("sha256") if media else None,
        "approvalEvidenceSha256": approval.get("sha256") if approval else None,
        "reviewEvidenceSha256": review["evidence"].get("sha256") if review["evidence"] else None,
        "machineJudgeEvidenceSha256": machine_judge.get("sha256") if machine_judge else None,
        "implementation": implementation,
    })


def validate_ready_package(package):
    source = package["source"]
    window = source["approvedWindow"]
    if (package["status"] != "ready_for_translation" or package["translationEligible"] is not True
            or package["candidateTranslationEligible"] is not True or package["issues"]
            or source_gate_issues(source["media"], window["startSeconds"], window["endSeconds"],
                                 window["status"] == "approved" and window["humanApproval"] is True)):
        raise ValueError("Source package does not satisfy production readiness invariants")
    identity = source_identity(source, package["transcript"]["artifact"], package["anchors"]["artifact"],
                               package["review"], package["evidence"]["machineJudge"], package["implementation"])
    if (package["downstreamInvalidationKey"] != identity
            or package["packageId"] != f"english-source-{identity[:24]}"):
        raise ValueError("Source derived identity differs from bound evidence")


def _layer2_override_receipt(review_path: Path | None, *, aligned_sha256: str,
                             anchor_json_sha256: str, source_unit_ids: list[str],
                             source_id: str | None = None, anchor_issues: list[dict[str, Any]] | None = None):
    """Validate the v2 human override without changing machine review evidence."""
    if review_path is None:
        return None
    review_path = review_path.resolve()
    review = read_object(review_path, "English source review")
    if review.get("schemaVersion") != REVIEW_SCHEMA_V2:
        return None
    from jsonschema import Draft202012Validator, FormatChecker
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "sermon-english-source-review-v2.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(review))
    if errors:
        raise ValueError(f"Invalid versioned Layer 2 override receipt: {errors[0].message}")
    override = review.get("layer2CandidateOverride")
    if not isinstance(override, dict) or override.get("decision") != LAYER2_CANDIDATE_OVERRIDE_DECISION:
        raise ValueError("Layer 2 candidate override decision is missing")
    if override.get("scope") != "layer2_candidate_only":
        raise ValueError("Human override exceeds Layer 2 candidate scope")
    if source_id is not None and override.get("sourceId") != source_id:
        raise ValueError("Layer 2 override belongs to a different source")
    if review.get("alignedSegmentsSha256") != aligned_sha256 or review.get("anchorManifestJsonSha256") != anchor_json_sha256:
        raise ValueError("Layer 2 override belongs to different aligned English or anchors")
    if override.get("targetLocales") != ["es", "ko", "zh-Hans"]:
        raise ValueError("Layer 2 override locale scope is invalid")
    if override.get("audioGeneration") is not False or override.get("publication") is not False:
        raise ValueError("Layer 2 override cannot authorize audio or publication")
    if not override.get("userInstructionItemId") or not override.get("authorizationItemId"):
        raise ValueError("Layer 2 override must bind the user instruction and override authorization")
    if review.get("reviewedSourceUnitIds") != source_unit_ids:
        raise ValueError("Layer 2 override must cover every source unit in order")
    machine_artifact = override.get("machineJudge")
    if not isinstance(machine_artifact, dict) or set(machine_artifact) != {"path", "sha256", "jsonSha256"}:
        raise ValueError("Layer 2 override must bind the rejected machine judge artifact")
    machine_path = Path(machine_artifact["path"]).resolve()
    machine_judge = read_object(machine_path, "bound English source machine judge")
    if (file_sha256(machine_path) != machine_artifact["sha256"]
            or json_sha256(machine_judge) != machine_artifact["jsonSha256"]
            or machine_judge.get("status") != "rejected_for_layer2_shadow"
            or machine_judge.get("layer2DevelopmentEligible") is not False
            or machine_judge.get("productionTranslationEligible") is not False
            or machine_judge.get("alignedSegmentsSha256") != aligned_sha256
            or machine_judge.get("anchorManifestJsonSha256") != anchor_json_sha256):
        raise ValueError("Layer 2 override does not bind the rejected machine review")
    failures = [item.get("sourceSentenceId") for item in machine_judge.get("sentences", [])
                if isinstance(item, dict) and item.get("verdict") == "fail"]
    high_risk = [item.get("sourceSentenceId") for item in machine_judge.get("sentences", [])
                 if isinstance(item, dict) and item.get("risk") == "high"]
    if (override.get("acknowledgedFailureSentenceIds") != failures
            or override.get("acknowledgedHighRiskSentenceIds") != high_risk):
        raise ValueError("Layer 2 override must acknowledge the exact failed and high-risk sentences")
    issue_types = sorted({str(item.get("type", "unknown_anchor_issue"))
                          for item in (anchor_issues or []) if isinstance(item, dict)})
    if override.get("acknowledgedAnchorIssueTypes") != issue_types:
        raise ValueError("Layer 2 override must acknowledge the exact anchor issue types")
    return {"reviewPath": review_path, "review": review, "override": override,
            "machineJudge": machine_judge, "machineJudgeArtifact": machine_artifact}


def validate_layer2_candidate_package(package, anchor):
    """Validate only the explicitly overridden Layer 2 candidate path.

    This never makes the English package production-ready. Audio and release
    consumers continue to require validate_ready_package().
    """
    source = package.get("source", {})
    window = source.get("approvedWindow", {})
    if (package.get("schemaVersion") != SCHEMA_VERSION
            or package.get("status") != "candidate_ready_for_translation"
            or package.get("candidateTranslationEligible") is not True
            or package.get("translationEligible") is not False):
        raise ValueError("Explicit Layer 2 candidate override package required")
    if source_gate_issues(source.get("media"), window.get("startSeconds"), window.get("endSeconds"),
                          window.get("status") == "approved" and window.get("humanApproval") is True):
        raise ValueError("Layer 2 override cannot waive source identity or sermon window gates")
    anchor_hash = json_sha256(anchor)
    aligned_sha = package.get("transcript", {}).get("artifact", {}).get("sha256")
    if package.get("anchors", {}).get("artifact", {}).get("jsonSha256") != anchor_hash:
        raise ValueError("Layer 2 candidate source and anchor differ")
    unit_ids = [unit.get("sourceUnitId") for unit in anchor.get("sourceUnits", [])]
    evidence = package.get("review", {}).get("evidence")
    if not isinstance(evidence, dict) or not evidence.get("path"):
        raise ValueError("Layer 2 candidate override evidence is missing")
    receipt = _layer2_override_receipt(
        Path(evidence["path"]), aligned_sha256=aligned_sha, anchor_json_sha256=anchor_hash,
        source_unit_ids=unit_ids, source_id=source.get("sourceId"),
        anchor_issues=anchor.get("issues", []),
    )
    if receipt is None:
        raise ValueError("Versioned Layer 2 override receipt is required")
    if artifact(receipt["reviewPath"], value=receipt["review"]) != evidence:
        raise ValueError("Layer 2 override receipt artifact identity changed")
    if package.get("evidence", {}).get("machineJudge") != receipt["machineJudgeArtifact"]:
        raise ValueError("Layer 2 override does not match the package machine judge evidence")
    if package.get("review", {}).get("humanApproval") is not True:
        raise ValueError("Layer 2 override must remain a human decision")
    if package.get("review", {}).get("reviewedSourceUnitIds") != unit_ids:
        raise ValueError("Layer 2 override must cover all source units")
    if any(package.get("review", {}).get("checks", {}).get(name) != "approved" for name in APPROVED_CHECKS):
        raise ValueError("Layer 2 override source checks are incomplete")
    allowed_issue_types = set(receipt["override"]["acknowledgedAnchorIssueTypes"])
    if any(item.get("stage") != "anchors" or item.get("type") not in allowed_issue_types
           for item in package.get("issues", [])):
        raise ValueError("Layer 2 override cannot waive unrelated source package issues")
    identity = source_identity(source, package["transcript"]["artifact"], package["anchors"]["artifact"],
                               package["review"], package["evidence"].get("machineJudge"),
                               package["implementation"])
    if (package.get("downstreamInvalidationKey") != identity
            or package.get("packageId") != f"english-source-{identity[:24]}"):
        raise ValueError("Layer 2 candidate derived identity differs from bound evidence")
    return receipt["override"]


def _review_payload(
    review_path: Path | None,
    *,
    aligned_sha256: str,
    anchor_json_sha256: str,
    source_unit_ids: list[str],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    pending = {
        "humanApproval": False,
        "reviewedBy": None,
        "reviewedAt": None,
        "reviewedSourceUnitIds": [],
        "checks": {name: "pending" for name in APPROVED_CHECKS},
        "evidence": None,
    }
    if review_path is None:
        return pending, None
    review_path = review_path.resolve()
    review = read_object(review_path, "English source review")
    review_schema = review.get("schemaVersion")
    if review_schema not in {REVIEW_SCHEMA_VERSION, REVIEW_SCHEMA_V2}:
        raise ValueError("Unsupported English source review schema")
    if review.get("alignedSegmentsSha256") != aligned_sha256:
        raise ValueError("English source review belongs to different aligned segments")
    if review.get("anchorManifestJsonSha256") != anchor_json_sha256:
        raise ValueError("English source review belongs to a different anchor manifest")
    if review.get("humanApproval") is not True:
        raise ValueError("English source review must retain explicit human approval")
    if review.get("reviewedSourceUnitIds") != source_unit_ids:
        raise ValueError("English source review must cover every source unit in order")
    checks = review.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(APPROVED_CHECKS):
        raise ValueError("English source review has an invalid check set")
    if any(checks[name] != "approved" for name in APPROVED_CHECKS):
        raise ValueError("English source review has not approved every Layer 1 check")
    if not str(review.get("reviewedBy", "")).strip():
        raise ValueError("English source review identity and time are required")
    _validate_reviewed_at(review.get("reviewedAt"))
    evidence = artifact(review_path, value=review)
    return {
        "humanApproval": True,
        "reviewedBy": review["reviewedBy"],
        "reviewedAt": review["reviewedAt"],
        "reviewedSourceUnitIds": source_unit_ids,
        "checks": checks,
        "evidence": evidence,
    }, review


def _machine_judge_payload(
    machine_judge_path: Path | None,
    *,
    aligned_sha256: str,
    anchor_json_sha256: str,
    source_sentence_ids: list[str],
    manifest_issues: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, bool]:
    if machine_judge_path is None:
        return None, False
    machine_judge_path = machine_judge_path.resolve()
    judge = read_object(machine_judge_path, "English source machine judge receipt")
    if judge.get("schemaVersion") != MACHINE_JUDGE_SCHEMA_VERSION:
        raise ValueError("Unsupported English source machine judge schema")
    if judge.get("reviewType") != "model" or judge.get("humanApproval") is not False:
        raise ValueError("English source machine judge must retain model-only provenance")
    judge_script = Path(__file__).resolve().with_name("judge_english_source_for_translation.py")
    if (judge.get("implementationSha256") != file_sha256(judge_script)
            or judge.get("model") != MACHINE_JUDGE_MODEL
            or judge.get("reasoningEffort") != MACHINE_JUDGE_REASONING_EFFORT
            or judge.get("promptVersion") != MACHINE_JUDGE_SCHEMA_VERSION
            or judge.get("thresholds") != MACHINE_JUDGE_THRESHOLDS):
        raise ValueError("English source machine judge implementation or policy is not current")
    if judge.get("alignedSegmentsSha256") != aligned_sha256:
        raise ValueError("English source machine judge belongs to different aligned segments")
    if judge.get("anchorManifestJsonSha256") != anchor_json_sha256:
        raise ValueError("English source machine judge belongs to a different anchor manifest")
    if judge.get("reviewedSourceSentenceIds") != source_sentence_ids:
        raise ValueError("English source machine judge must cover every source sentence in order")
    expected_issue_hashes = [json_sha256(issue) for issue in manifest_issues]
    if judge.get("reviewedManifestIssueJsonSha256s") != expected_issue_hashes:
        raise ValueError("English source machine judge does not bind every manifest issue")
    deterministic = judge.get("deterministicReview", {})
    sentences = judge.get("sentences")
    sentence_ids = [item.get("sourceSentenceId") for item in sentences or [] if isinstance(item, dict)]
    counts = judge.get("counts", {})
    pass_state = bool(
        judge.get("status") == "approved_for_layer2_shadow"
        and judge.get("layer2DevelopmentEligible") is True
        and judge.get("productionTranslationEligible") is False
        and deterministic.get("status") == "pass"
        and isinstance(deterministic.get("checks"), list)
        and deterministic["checks"]
        and all(item.get("status") == "pass" for item in deterministic["checks"] if isinstance(item, dict))
        and len(deterministic["checks"]) == sum(isinstance(item, dict) for item in deterministic["checks"])
        and deterministic.get("issues") == []
        and sentence_ids == source_sentence_ids
        and all(
            item.get("verdict") == "pass"
            and item.get("risk") != "high"
            and set(item.get("checks", {})) == MACHINE_JUDGE_CHECKS
            and all(item["checks"][name] == "pass" for name in MACHINE_JUDGE_CHECKS)
            and item.get("unresolvedIssues") == []
            for item in sentences or [] if isinstance(item, dict)
        )
        and len(sentences or []) == len(source_sentence_ids)
        and counts.get("sourceSentences") == len(source_sentence_ids)
        and counts.get("sourceUnits") > 0
        and counts.get("manifestIssues") == len(manifest_issues)
        and counts.get("sentencePass") == len(source_sentence_ids)
        and counts.get("sentenceFail") == 0
        and counts.get("highRiskSentences") == 0
        and isinstance(judge.get("requestIds"), list) and bool(judge["requestIds"])
        and judge.get("unresolvedIssues") == []
    )
    if judge.get("layer2DevelopmentEligible") is True and not pass_state:
        raise ValueError("English source machine judge pass is internally inconsistent")
    return artifact(machine_judge_path, value=judge), pass_state


def _machine_judge_accepts_anchor_issue(
    machine_judge_artifact: dict[str, Any] | None,
    issue: dict[str, Any],
    *,
    source_units: list[dict[str, Any]],
    manifest_issues: list[dict[str, Any]],
) -> bool:
    """Check whether a bound receipt clears one whitelisted sentence warning."""
    if (not isinstance(machine_judge_artifact, dict)
            or issue.get("type") not in MACHINE_AND_HUMAN_REVIEWABLE_ANCHOR_ISSUES
            or not isinstance(issue.get("sourceSentenceId"), str)):
        return False
    path_value = machine_judge_artifact.get("path")
    if not isinstance(path_value, str):
        return False
    machine_path = Path(path_value)
    try:
        judge = read_object(machine_path, "bound English source machine judge")
    except ValueError:
        return False
    if (file_sha256(machine_path) != machine_judge_artifact.get("sha256")
            or json_sha256(judge) != machine_judge_artifact.get("jsonSha256")):
        return False

    reviewed_issue_hashes = judge.get("reviewedManifestIssueJsonSha256s")
    expected_issue_hashes = [json_sha256(item) for item in manifest_issues]
    if (not isinstance(reviewed_issue_hashes, list)
            or reviewed_issue_hashes != expected_issue_hashes
            or json_sha256(issue) not in reviewed_issue_hashes):
        return False

    deterministic = judge.get("deterministicReview")
    deterministic_checks = deterministic.get("checks") if isinstance(deterministic, dict) else None
    if (not isinstance(deterministic, dict)
            or deterministic.get("status") != "pass"
            or deterministic.get("issues") != []
            or not isinstance(deterministic_checks, list)
            or not deterministic_checks
            or any(not isinstance(check, dict) or check.get("status") != "pass"
                   for check in deterministic_checks)):
        return False

    sentence_id = issue["sourceSentenceId"]
    expected_units = [
        unit.get("sourceUnitId") for unit in source_units
        if unit.get("sourceSentenceId") == sentence_id
    ]
    judge_sentences = judge.get("sentences")
    if not isinstance(judge_sentences, list):
        return False
    matching_sentences = [
        item for item in judge_sentences
        if isinstance(item, dict) and item.get("sourceSentenceId") == sentence_id
    ]
    if len(matching_sentences) != 1 or not expected_units:
        return False
    sentence = matching_sentences[0]
    checks = sentence.get("checks")
    return bool(
        sentence.get("sourceUnitIds") == expected_units
        and sentence.get("verdict") == "pass"
        and sentence.get("risk") in {"low", "medium"}
        and isinstance(checks, dict)
        and set(checks) == MACHINE_JUDGE_CHECKS
        and all(checks.get(name) == "pass" for name in MACHINE_JUDGE_CHECKS)
        and sentence.get("unresolvedIssues") == []
    )


def build_package(
    aligned_segments_path: Path,
    anchor_manifest_path: Path,
    *,
    summary_path: Path | None = None,
    approval_evidence_path: Path | None = None,
    review_path: Path | None = None,
    machine_judge_path: Path | None = None,
    source_id: str | None = None,
    source_url_hash: str | None = None,
    service_date: str | None = None,
) -> dict[str, Any]:
    aligned_segments_path = aligned_segments_path.resolve()
    anchor_manifest_path = anchor_manifest_path.resolve()
    try:
        segments = json.loads(aligned_segments_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read frozen aligned English: {exc}") from exc
    if not isinstance(segments, list) or not segments:
        raise ValueError("Frozen aligned English must be a non-empty JSON array")
    manifest = read_object(anchor_manifest_path, "anchor manifest")
    if manifest.get("schemaVersion") != "sermon-sentence-anchor-manifest-v2":
        raise ValueError("Layer 1 requires the clause-stable v2 anchor manifest")
    if manifest.get("input", {}).get("mfaSegmentsSha256") != file_sha256(aligned_segments_path):
        raise ValueError("Anchor manifest does not bind the supplied aligned English")
    source_units = manifest.get("sourceUnits")
    if not isinstance(source_units, list) or not source_units:
        raise ValueError("Anchor manifest has no source units")

    summary: dict[str, Any] = {}
    summary_artifact = None
    if summary_path is not None:
        summary_path = summary_path.resolve()
        summary = read_object(summary_path, "pipeline summary")
        summary_artifact = artifact(summary_path, value=summary)

    if source_url_hash is not None and _sha_or_none(source_url_hash) is None:
        raise ValueError("source_url_hash must be a SHA-256 value")
    _validate_service_date(service_date)
    aligned_artifact = artifact(aligned_segments_path, value=segments)
    anchor_artifact = artifact(anchor_manifest_path, value=manifest)
    source_id = str(source_id or "").strip() or f"english-{aligned_artifact['sha256'][:24]}"
    source_unit_ids = [str(unit.get("sourceUnitId", "")) for unit in source_units]
    if any(not item for item in source_unit_ids) or len(source_unit_ids) != len(set(source_unit_ids)):
        raise ValueError("Anchor manifest source unit IDs must be non-empty and unique")

    approval = None
    approval_artifact = None
    if approval_evidence_path is not None:
        approval_evidence_path = approval_evidence_path.resolve()
        approval = read_object(approval_evidence_path, "operator window approval")
        approval_artifact = artifact(approval_evidence_path, value=approval)
        if source_url_hash and approval.get("sourceUrlHash") not in (None, source_url_hash):
            raise ValueError("Operator approval belongs to a different source URL")
        identity = summary.get("pipelineInputIdentity")
        pipeline_window = identity.get("sermonWindow") if isinstance(identity, dict) else None
        if isinstance(pipeline_window, dict):
            for approval_key, window_key in (("startTime", "startTime"), ("endTime", "endTime")):
                approved_value = approval.get(approval_key)
                if approved_value is not None and approved_value != pipeline_window.get(window_key):
                    raise ValueError("Operator approval belongs to a different sermon window")
    approval_pass = bool(
        isinstance(approval, dict)
        and approval.get("status") == "approved"
        and approval.get("humanApproval") is True
    )

    starts = [float(unit["start"]) for unit in source_units]
    ends = [float(unit["end"]) for unit in source_units]
    start = summary.get("sermonStartSeconds")
    end = summary.get("sermonEndSeconds")
    if not _finite(start) or float(start) < 0:
        start = min(starts)
    if not _finite(end) or float(end) <= float(start):
        end = max(ends)

    aligned_sha = aligned_artifact["sha256"]
    anchor_json_sha = anchor_artifact["jsonSha256"]
    review, _ = _review_payload(
        review_path,
        aligned_sha256=aligned_sha,
        anchor_json_sha256=anchor_json_sha,
        source_unit_ids=source_unit_ids,
    )
    manifest_issues = manifest.get("issues") if isinstance(manifest.get("issues"), list) else []
    source_sentence_ids = list(dict.fromkeys(str(unit["sourceSentenceId"]) for unit in source_units))
    machine_judge_artifact, machine_judge_pass = _machine_judge_payload(
        machine_judge_path,
        aligned_sha256=aligned_sha,
        anchor_json_sha256=anchor_json_sha,
        source_sentence_ids=source_sentence_ids,
        manifest_issues=[item for item in manifest_issues if isinstance(item, dict)],
    )
    layer2_override = None
    review_evidence = review.get("evidence")
    if isinstance(review_evidence, dict) and review_evidence.get("path"):
        layer2_override = _layer2_override_receipt(
            Path(review_evidence["path"]), aligned_sha256=aligned_sha,
            anchor_json_sha256=anchor_json_sha, source_unit_ids=source_unit_ids,
            source_id=source_id, anchor_issues=manifest_issues)
        if layer2_override is not None and machine_judge_artifact != layer2_override["machineJudgeArtifact"]:
            raise ValueError("Layer 2 override must bind the package's exact machine judge evidence")
    media = _source_media(summary)
    # The full judge pass retains its established behavior. A globally rejected
    # receipt can clear only an individually passing long clause, and only
    # alongside the bound human approval. Keep every warning in the manifest.
    def accepted_anchor_warning(issue: dict[str, Any]) -> bool:
        if (not review["humanApproval"]
                or issue.get("type") not in MACHINE_AND_HUMAN_REVIEWABLE_ANCHOR_ISSUES):
            return False
        if machine_judge_pass:
            return True
        return _machine_judge_accepts_anchor_issue(
            machine_judge_artifact,
            issue,
            source_units=source_units,
            manifest_issues=[item for item in manifest_issues if isinstance(item, dict)],
        )

    issues: list[dict[str, Any]] = [
        {"stage": "anchors", "type": str(item.get("type", "unknown_anchor_issue")), "detail": item}
        for item in manifest_issues if isinstance(item, dict)
        and not accepted_anchor_warning(item)
    ]
    issues.extend(source_gate_issues(media, start, end, approval_pass))
    for name, value in review["checks"].items():
        if value != "approved":
            issues.append({"stage": "review", "type": f"{name}_review_pending"})

    production_ready = not issues
    candidate_ready = production_ready or machine_judge_pass or layer2_override is not None
    status = (
        "ready_for_translation" if production_ready
        else "candidate_ready_for_translation" if candidate_ready
        else "blocked"
    )
    implementation = {
        "builderSha256": file_sha256(Path(__file__).resolve()),
        "anchorGeneratorSha256": file_sha256(Path(__file__).resolve().with_name("sermon_sentence_interpretation.py")),
    }
    source_metadata = {
        "sourceId": source_id, "sourceUrlHash": source_url_hash, "serviceDate": service_date,
        "media": media, "approvedWindow": {
            "startSeconds": float(start), "endSeconds": float(end),
            "status": "approved" if approval_pass else "pending", "humanApproval": approval_pass,
            "evidence": approval_artifact},
    }
    downstream_key = source_identity(source_metadata, aligned_artifact, anchor_artifact,
                                     review, machine_judge_artifact, implementation)
    identity = summary.get("pipelineInputIdentity")
    runtime = summary.get("readingAlignmentRuntime")
    if runtime is None and isinstance(identity, dict):
        runtime = identity.get("mfa")

    package = {
        "schemaVersion": SCHEMA_VERSION,
        "packageId": f"english-source-{downstream_key[:24]}",
        "sourceLocale": "en",
        "status": status,
        "candidateTranslationEligible": candidate_ready,
        "translationEligible": production_ready,
        "implementation": implementation,
        "source": source_metadata,
        "transcript": {
            "artifact": aligned_artifact,
            "provenance": {
                "kind": "asr_reviewed" if summary.get("sourceTextReview") else "asr",
                "model": str(summary.get("models", {}).get("referenceAsr") or "unknown"),
            },
            "completenessReview": review["checks"]["transcriptCompleteness"],
        },
        "alignment": {
            "provider": _alignment_provider(summary),
            "timingKind": str(manifest.get("input", {}).get("timingKind", "unknown")),
            "artifact": aligned_artifact,
            "runtime": runtime if isinstance(runtime, dict) else None,
            "sourceWordCount": int(manifest.get("counts", {}).get("sourceWords", 0)),
            "issueCount": sum(
                str(item.get("type", "")).startswith("alignment_")
                for item in manifest_issues if isinstance(item, dict)
            ),
        },
        "anchors": {
            "artifact": anchor_artifact,
            "schemaVersion": manifest["schemaVersion"],
            "unitPolicy": manifest.get("policy", {}).get("unitPolicy"),
            "sourceSentenceCount": int(manifest.get("counts", {}).get("sourceSentences", 0)),
            "sourceUnitCount": len(source_units),
            "sourceWordCount": int(manifest.get("counts", {}).get("sourceWords", 0)),
            "issueCount": len(manifest_issues),
        },
        "canonicalEnglishContent": None,
        "review": review,
        "issues": issues,
        "downstreamInvalidationKey": downstream_key,
        "evidence": {
            "pipelineSummary": summary_artifact,
            "machineJudge": machine_judge_artifact,
        },
    }
    if layer2_override is not None:
        validate_layer2_candidate_package(package, manifest)
    return package


def write_immutable(path: Path, payload: object) -> None:
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise ValueError(f"Existing English Source Package changed: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aligned-segments", type=Path, required=True)
    parser.add_argument("--anchor-manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--approval-evidence", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--machine-judge", type=Path)
    parser.add_argument("--source-id")
    parser.add_argument("--source-url-hash")
    parser.add_argument("--service-date")
    parser.add_argument("--progress-ledger", type=Path,
                        help="Record producer timing in this four-layer run ledger")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with measure.producer_step(args.progress_ledger, "L1-04") as metrics:
        package = build_package(
            args.aligned_segments,
            args.anchor_manifest,
            summary_path=args.summary,
            approval_evidence_path=args.approval_evidence,
            review_path=args.review,
            machine_judge_path=args.machine_judge,
            source_id=args.source_id,
            source_url_hash=args.source_url_hash,
            service_date=args.service_date,
        )
        metrics.update(sourceUnits=package["anchors"]["sourceUnitCount"],
                       sourcePackageSha256=json_sha256(package),
                       approvedForTranslation=package["translationEligible"])
        output_already_present = args.out.exists()
        write_immutable(args.out.resolve(), package)
        metrics["cacheHit"] = output_already_present
    print(json.dumps(package, ensure_ascii=False, indent=2))
    return 0 if package["candidateTranslationEligible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
