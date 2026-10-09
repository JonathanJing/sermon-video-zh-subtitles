"""Apply evidence-bound source text corrections without rewriting raw ASR.

This module validates an existing model review: a user-directed conversational
review, or a machine audio adjudication written by
``source_meaning_machine_adjudication`` from the bound audio. It does not
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
MODEL = "gpt-6.1-sol"
SUPPORTED_MODELS = {MODEL, "gpt-6-astra"}
STATUS = "approved_for_source_correction"
AUTHORITY = "user_directed_conversation_review"
MACHINE_AUTHORITY = "machine_audio_adjudication"
AUTHORITIES = {AUTHORITY, MACHINE_AUTHORITY}
# A machine-authority review rests on exactly one source-meaning receipt among
# its evidence; every patch must be that receipt's corrections and nothing else.
MACHINE_RECEIPT_SCHEMA = "sermon-source-meaning-machine-adjudication-v1"
MACHINE_ROLE = "machine_adjudicator"
UNIT_TIME_TOLERANCE = 0.05
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


def _machine_receipt(review: dict[str, Any], evidence: list[dict[str, str]],
                     package: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """The one verified source-meaning receipt a machine-authority review rests on.

    The receipt must be the bound-audio adjudication itself: the machine role,
    no human approval, the same adjudicator identity and signature the review
    carries, and, through the adjudicator's own validator, its listeners'
    hearings and its bindings to the actual package (``source.json``,
    ``anchor.json``) and media it was made against. A hand-written or stale
    receipt for other inputs is refused before any patch is read.
    """
    receipts: list[tuple[str, dict[str, Any]]] = []
    for item in evidence:
        try:
            value = json.loads(Path(item["path"]).read_bytes())
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("schemaVersion") == MACHINE_RECEIPT_SCHEMA:
            receipts.append((item["sha256"], value))
    if len(receipts) != 1:
        raise ValueError("Machine audio adjudication requires exactly one source-meaning receipt as evidence")
    sha, receipt = receipts[0]
    adjudicator, media, bindings, units = (receipt.get(k) for k in ("adjudicator", "media", "bindings", "units"))
    if not (
        receipt.get("decidedByRole") == MACHINE_ROLE
        and receipt.get("humanApproval") is False
        and receipt.get("decidedBy") == review.get("reviewedBy")
        and receipt.get("reviewedAt") == review.get("reviewedAt")
        and isinstance(adjudicator, dict) and adjudicator.get("model") == review.get("model")
        and isinstance(media, dict) and isinstance(bindings, dict)
        and isinstance(units, list) and units
    ):
        raise ValueError("Source-meaning receipt does not carry the adjudication this review claims")
    _require_sha256(media.get("sha256"), "Source-meaning receipt media sha256")
    for name in ("source.json", "anchor.json"):
        _require_sha256(bindings.get(name), f"Source-meaning receipt binding {name}")
    for row in units:
        if not (isinstance(row, dict) and isinstance(row.get("sourceUnitId"), str)
                and isinstance(row.get("frozenText"), str) and row.get("decision") in
                {"transcript_confirmed", "transcript_corrected", "undetermined"}):
            raise ValueError("Source-meaning receipt has an invalid unit row")
        if row["decision"] == "transcript_corrected":
            _require_text(row.get("correctedText"), "Source-meaning receipt correctedText")
            unit = row.get("unit")
            if not (isinstance(unit, dict) and isinstance(unit.get("start"), (int, float))
                    and isinstance(unit.get("end"), (int, float))):
                raise ValueError("Source-meaning receipt corrected unit has no timing")
    if not (isinstance(package, dict) and isinstance(package.get("source"), dict)
            and isinstance(package.get("anchor"), dict)):
        raise ValueError("Machine audio adjudication requires the adjudicated source package "
                         "(source.json and anchor.json) as adjudicated_package")
    from scripts import source_meaning_machine_adjudication as adjudicator_module
    try:
        adjudicator_module.validate_receipt(receipt, source=package["source"], anchor=package["anchor"],
                                            media_sha256=package.get("mediaSha256"))
    except adjudicator_module.SourceAdjudicationError as exc:
        raise ValueError(f"Source-meaning receipt is not bound to the adjudicated package and media: {exc}") from exc
    return sha, receipt


def _machine_expected_text(receipt: dict[str, Any], segment: dict[str, Any]) -> tuple[str, list[str]]:
    """The segment text after applying every corrected unit the receipt places inside it, and those units."""
    original = segment["text"]
    expected = original
    applied: list[str] = []
    for row in receipt["units"]:
        if row["decision"] != "transcript_corrected":
            continue
        unit = row["unit"]
        chunk_bound = ("referenceChunkId" in unit and "referenceChunkId" in segment
                       and str(unit["referenceChunkId"]).strip() != str(segment["referenceChunkId"]).strip())
        try:
            inside = (float(segment["start"]) <= float(unit["start"]) + UNIT_TIME_TOLERANCE
                      and float(segment["end"]) >= float(unit["end"]) - UNIT_TIME_TOLERANCE)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Machine source correction needs timed segments") from exc
        if chunk_bound or not inside or original.count(row["frozenText"]) != 1:
            continue
        if expected.count(row["frozenText"]) != 1:
            raise ValueError("Source-meaning receipt corrections overlap inside one segment")
        expected = expected.replace(row["frozenText"], row["correctedText"])
        applied.append(row["sourceUnitId"])
    if not applied:
        raise ValueError("Machine source correction patches a segment the receipt did not correct")
    return expected, applied


def apply_review(
    segments: list[dict[str, Any]],
    review_path: str | Path,
    source_audio_path: str | Path,
    asr_path: str | Path,
    *,
    adjudicated_package: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return corrected copies and model provenance after validating all evidence.

    The review must bind the original audio and ASR files, every supporting
    evidence file, and each segment's exact original UTF-8 text. A machine
    audio adjudication review also needs ``adjudicated_package``: the
    ``source`` and ``anchor`` objects its receipt adjudicated and, when known,
    the parent media's ``mediaSha256``; the receipt must be bound to them and
    every correction it holds must be patched. No input object or file is
    modified, including when validation fails.
    """
    review_path = Path(review_path).resolve()
    review, review_hash = _load_review(review_path)
    if not (
        review.get("schemaVersion") == SCHEMA
        and review.get("reviewType") == "model"
        and review.get("model") in SUPPORTED_MODELS
        and review.get("humanApproval") is False
        and review.get("status") == STATUS
        and review.get("authority") in AUTHORITIES
    ):
        raise ValueError("A conversational source correction review with model identity is required")
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
    machine: tuple[str, dict[str, Any]] | None = None
    if review["authority"] == MACHINE_AUTHORITY:
        machine = _machine_receipt(review, verified_evidence, adjudicated_package)

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
    consumed: dict[str, int] = {}
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
        if machine is not None:
            # The machine may only change what its own bound-audio receipt corrected.
            if evidence_hash != machine[0]:
                raise ValueError("Machine source correction patch does not cite the source-meaning receipt")
            expected_text, units_here = _machine_expected_text(machine[1], by_id[segment_id])
            if corrected != expected_text:
                raise ValueError("Machine source correction patch differs from the receipt's corrections")
            for unit_id in units_here:
                if unit_id in consumed:
                    raise ValueError(f"Machine source correction applies receipt unit {unit_id} in two segments")
                consumed[unit_id] = segment_id
        changes[segment_id] = corrected
        applied.append({
            "segmentId": segment_id,
            "originalTextSha256": original_hash,
            "correctedTextSha256": text_sha256(corrected),
            "reason": reason,
            "evidenceSha256": evidence_hash,
        })

    if machine is not None:
        # Layer 1 applies the whole adjudication or none of it: a review that drops a
        # segment's patch would record the full receipt as evidence for a partial change.
        omitted = [row["sourceUnitId"] for row in machine[1]["units"]
                   if row["decision"] == "transcript_corrected" and row["sourceUnitId"] not in consumed]
        if omitted:
            raise ValueError("Machine source correction omits receipt corrections for units: " + ", ".join(omitted))
    corrected_segments = deepcopy(segments)
    for segment in corrected_segments:
        if segment["id"] in changes:
            segment["text"] = changes[segment["id"]]
    provenance = {
        "schemaVersion": SCHEMA,
        "reviewType": "model",
        "model": review["model"],
        "humanApproval": False,
        "status": STATUS,
        "authority": review["authority"],
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
    if machine is not None:
        provenance["machineEvidence"] = {
            "receiptSha256": machine[0], "decidedBy": machine[1]["decidedBy"],
            "mediaSha256": machine[1]["media"]["sha256"], "bindings": dict(machine[1]["bindings"]),
        }
    return corrected_segments, provenance
