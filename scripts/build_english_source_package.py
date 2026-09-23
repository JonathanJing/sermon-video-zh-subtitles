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


SCHEMA_VERSION = "sermon-english-source-package-v1"
REVIEW_SCHEMA_VERSION = "sermon-english-source-review-v1"
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
    if review.get("schemaVersion") != REVIEW_SCHEMA_VERSION:
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
    media = _source_media(summary)
    issues: list[dict[str, Any]] = [
        {"stage": "anchors", "type": str(item.get("type", "unknown_anchor_issue")), "detail": item}
        for item in manifest_issues if isinstance(item, dict)
    ]
    if media is None:
        issues.append({"stage": "source", "type": "source_media_identity_missing"})
    if not approval_pass:
        issues.append({"stage": "source", "type": "approved_sermon_window_missing"})
    for name, value in review["checks"].items():
        if value != "approved":
            issues.append({"stage": "review", "type": f"{name}_review_pending"})

    production_ready = not issues
    candidate_ready = production_ready or machine_judge_pass
    status = (
        "ready_for_translation" if production_ready
        else "candidate_ready_for_translation" if candidate_ready
        else "blocked"
    )
    invalidation_identity = {
        "sourceId": source_id,
        "sourceUrlHash": source_url_hash,
        "serviceDate": service_date,
        "approvedWindow": {"startSeconds": float(start), "endSeconds": float(end)},
        "alignedSegmentsSha256": aligned_sha,
        "anchorManifestJsonSha256": anchor_json_sha,
        "sourceMediaSha256": media.get("sha256") if media else None,
        "approvalEvidenceSha256": approval_artifact.get("sha256") if approval_artifact else None,
        "reviewEvidenceSha256": review["evidence"].get("sha256") if review["evidence"] else None,
        "machineJudgeEvidenceSha256": machine_judge_artifact.get("sha256") if machine_judge_artifact else None,
        "implementation": {
            "builderSha256": file_sha256(Path(__file__).resolve()),
            "anchorGeneratorSha256": file_sha256(
                Path(__file__).resolve().with_name("sermon_sentence_interpretation.py")
            ),
        },
    }
    downstream_key = json_sha256(invalidation_identity)
    identity = summary.get("pipelineInputIdentity")
    runtime = summary.get("readingAlignmentRuntime")
    if runtime is None and isinstance(identity, dict):
        runtime = identity.get("mfa")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "packageId": f"english-source-{downstream_key[:24]}",
        "sourceLocale": "en",
        "status": status,
        "candidateTranslationEligible": candidate_ready,
        "translationEligible": production_ready,
        "implementation": invalidation_identity["implementation"],
        "source": {
            "sourceId": source_id,
            "sourceUrlHash": source_url_hash,
            "serviceDate": service_date,
            "media": media,
            "approvedWindow": {
                "startSeconds": float(start),
                "endSeconds": float(end),
                "status": "approved" if approval_pass else "pending",
                "humanApproval": approval_pass,
                "evidence": approval_artifact,
            },
        },
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
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
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
    write_immutable(args.out.resolve(), package)
    print(json.dumps(package, ensure_ascii=False, indent=2))
    return 0 if package["candidateTranslationEligible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
