"""Apply evidence-bound source text corrections without rewriting raw ASR.

This module validates an existing conversational model review. It does not
generate a review, assess the audio, or create human approval. Only the text
field of explicitly reviewed segments changes; callers retain the raw inputs.
Relative evidence paths are resolved against the review file's directory.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any


SCHEMA = "sermon-source-text-review-v1"
MODEL = "gpt-6-astra"
STATUS = "approved_for_source_correction"
AUTHORITY = "user_directed_conversation_review"
PATCH_FIELDS = {
    "segmentId", "originalTextSha256", "correctedText", "reason", "evidenceSha256",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _file_sha256(path: Path, label: str) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(f"{label} is unavailable") from exc
    return digest.hexdigest()


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Source text review has a duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_review(path: Path) -> tuple[dict[str, Any], str]:
    try:
        contents = path.read_bytes()
        review = json.loads(contents, object_pairs_hook=_unique_json_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Source text review is unavailable or is not valid JSON") from exc
    if not isinstance(review, dict):
        raise ValueError("Source text review must be a JSON object")
    return review, hashlib.sha256(contents).hexdigest()


def apply_review(
    segments: list[dict[str, Any]],
    review_path: str | Path,
    source_audio_path: str | Path,
    asr_path: str | Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return corrected copies and model provenance after validating all evidence.

    The review must bind the original audio and ASR files, every supporting
    evidence file, and each segment's exact original UTF-8 text. No input object
    or file is modified, including when validation fails.
    """
    review_path = Path(review_path).resolve()
    review, review_hash = _load_review(review_path)
    if not (
        review.get("schemaVersion") == SCHEMA
        and review.get("reviewType") == "model"
        and review.get("model") == MODEL
        and review.get("humanApproval") is False
        and review.get("status") == STATUS
        and review.get("authority") == AUTHORITY
    ):
        raise ValueError("A conversational Astra source correction review with model identity is required")
    reviewed_by = _require_text(review.get("reviewedBy"), "reviewedBy")
    reviewed_at = _require_text(review.get("reviewedAt"), "reviewedAt")
    try:
        timestamp = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("reviewedAt must be an ISO timestamp with a timezone") from exc
    if timestamp.utcoffset() is None:
        raise ValueError("reviewedAt must be an ISO timestamp with a timezone")

    bound_inputs: dict[str, str] = {}
    for field, path in (
        ("sourceAudioSha256", Path(source_audio_path)),
        ("asrSha256", Path(asr_path)),
    ):
        expected = _require_sha256(review.get(field), field)
        actual = _file_sha256(path, field)
        if actual != expected:
            raise ValueError(f"Source text review has stale {field}")
        bound_inputs[field] = actual

    evidence = review.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("Source text review requires nonempty evidence")
    verified_evidence: list[dict[str, str]] = []
    evidence_paths: set[Path] = set()
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError("Source text review evidence must be an object")
        path = Path(_require_text(item.get("path"), "Evidence path"))
        path = (review_path.parent / path).resolve() if not path.is_absolute() else path.resolve()
        if path in evidence_paths:
            raise ValueError("Source text review has repeated evidence paths")
        evidence_paths.add(path)
        expected = _require_sha256(item.get("sha256"), "Evidence sha256")
        if _file_sha256(path, "Source text review evidence") != expected:
            raise ValueError("Source text review evidence changed")
        verified_evidence.append({"path": str(path), "sha256": expected})
    evidence_hashes = {item["sha256"] for item in verified_evidence}

    if not isinstance(segments, list) or not segments:
        raise ValueError("Source text review requires source segments")
    by_id: dict[int, dict[str, Any]] = {}
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError("Source segment must be an object")
        segment_id = segment.get("id")
        if type(segment_id) is not int or segment_id < 0 or segment_id in by_id:
            raise ValueError("Source segments have invalid or repeated IDs")
        _require_text(segment.get("text"), "Source segment text")
        by_id[segment_id] = segment

    patches = review.get("patches")
    if not isinstance(patches, list) or not patches:
        raise ValueError("Source text review requires nonempty patches")
    changes: dict[int, str] = {}
    applied: list[dict[str, Any]] = []
    for patch in patches:
        if not isinstance(patch, dict) or set(patch) != PATCH_FIELDS:
            raise ValueError("Source correction patch has missing or unknown fields")
        segment_id = patch.get("segmentId")
        if type(segment_id) is not int or segment_id not in by_id or segment_id in changes:
            raise ValueError("Source correction patch has an unknown or repeated segment ID")
        original = by_id[segment_id]["text"]
        original_hash = _require_sha256(patch.get("originalTextSha256"), "originalTextSha256")
        if original_hash != text_sha256(original):
            raise ValueError(f"Source correction segment {segment_id} text changed")
        corrected = _require_text(patch.get("correctedText"), "correctedText")
        if corrected == original:
            raise ValueError("Source correction patch does not change the text")
        reason = _require_text(patch.get("reason"), "Patch reason")
        evidence_hash = _require_sha256(patch.get("evidenceSha256"), "evidenceSha256")
        if evidence_hash not in evidence_hashes:
            raise ValueError("Source correction patch is missing its verified evidence")
        changes[segment_id] = corrected
        applied.append({
            "segmentId": segment_id,
            "originalTextSha256": original_hash,
            "correctedTextSha256": text_sha256(corrected),
            "reason": reason,
            "evidenceSha256": evidence_hash,
        })

    corrected_segments = deepcopy(segments)
    for segment in corrected_segments:
        if segment["id"] in changes:
            segment["text"] = changes[segment["id"]]
    provenance = {
        "schemaVersion": SCHEMA,
        "reviewType": "model",
        "model": MODEL,
        "humanApproval": False,
        "status": STATUS,
        "authority": AUTHORITY,
        "reviewedAt": reviewed_at,
        "reviewedBy": reviewed_by,
        "reviewPath": str(review_path),
        "reviewSha256": review_hash,
        **bound_inputs,
        "evidence": verified_evidence,
        "patchCount": len(applied),
        "correctedSegmentIds": [row["id"] for row in segments if row["id"] in changes],
        "patches": applied,
    }
    return corrected_segments, provenance
