"""Shared prompt and validation for the sermon Omni annotation POC."""
from __future__ import annotations

import json
import re
from pathlib import Path


SCHEMA_VERSION = "sermon-omni-annotation-poc-v3"
EVENT_TYPES = {"transition", "scripture_reading", "sermon_explanation", "other"}
PAUSE_KINDS = {"sentence_boundary", "rhetorical_pause", "hesitation", "unknown"}

PROMPT = """You are analyzing a short English sermon clip. A transcript candidate may be
supplied below. If supplied, it is unreviewed and may omit, substitute, or mistime words.
Treat the audio and video as primary evidence; use any transcript only as an aid. If the
transcript section says [not supplied], return transcript_status=not_provided and never
claim transcript evidence. Never infer audible pauses
from text alone and never infer that scripture is being read merely because scripture is
visible on screen.

Identify when the speaker transitions into a scripture quotation, reads scripture, and
returns to explanation. Read visible scripture reference/text when legible. Mark only
audible rhetorical pauses of at least 0.25 seconds. Times are seconds relative to the
start of this clip, not the full service.

Return JSON only, with this exact shape:
{
  "audio_status": "matched|mismatch|no_speech",
  "video_status": "matched|mismatch|no_visual",
  "transcript_status": "matched|partial|mismatch|not_provided",
  "events": [
    {
      "start_seconds": 0.0,
      "end_seconds": 1.0,
      "type": "transition|scripture_reading|sermon_explanation|other",
      "scripture_ref": "string or null",
      "on_screen_text": "short exact visible text or null",
      "evidence": {"audio": true, "video": false, "transcript": true},
      "confidence": 0.0,
      "note": "brief evidence-based explanation"
    }
  ],
  "pause_candidates": [
    {
      "at_seconds": 1.0,
      "duration_seconds": 0.3,
      "kind": "sentence_boundary|rhetorical_pause|hesitation|unknown",
      "evidence": {"audio": true, "video": false, "transcript": false},
      "confidence": 0.0,
      "note": "brief explanation"
    }
  ],
  "limitations": ["Approximate timing; requires review."]
}

Events must be ordered, non-overlapping, and within the clip. Confidence is from 0 to 1.
If audio is silent or mismatched, do not return any scripture_reading span or audible
pause candidate. Visible scripture may be reported as an `other` event with video-only
evidence, but it does not prove that anyone is reading it. Invisible annotations are
machine candidates only; do not claim human verification.

Clip duration: __DURATION__ seconds.
Machine transcript candidate:
__TRANSCRIPT__
"""


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_json(text: str) -> dict:
    content = text.strip()
    content = re.sub(r"^<think>.*?</think>\s*", "", content, flags=re.S)
    candidates = [content]
    candidates.extend(re.findall(r"```(?:json)?\s*(.*?)```", content, flags=re.S | re.I))
    decoder = json.JSONDecoder()
    objects: list[dict] = []
    complete: list[dict] = []
    required = {"audio_status", "video_status", "transcript_status", "events",
                "pause_candidates", "limitations"}
    for candidate in candidates:
        try:
            value = json.loads(candidate.strip())
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            objects.append(value)
        first_object = candidate.find("{")
        if first_object >= 0:
            try:
                value, _ = decoder.raw_decode(candidate[first_object:])
            except json.JSONDecodeError:
                value = None
            if isinstance(value, dict) and value not in objects:
                objects.append(value)
        for match in re.finditer(r"\{", candidate):
            try:
                value, _ = decoder.raw_decode(candidate[match.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and required.issubset(value):
                complete.append(value)
    if complete:
        return complete[-1]
    if objects:
        return max(objects, key=lambda value: len(required.intersection(value)))
    raise json.JSONDecodeError("No JSON object found", content, 0)


def _evidence_errors(value: object, prefix: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{prefix}_evidence_not_object"]
    return [f"{prefix}_evidence_{key}_not_bool" for key in ("audio", "video", "transcript")
            if type(value.get(key)) is not bool]


def validate(data: object, duration: float) -> list[str]:
    if not isinstance(data, dict):
        return ["not_object"]
    errors: list[str] = []
    if data.get("audio_status") not in {"matched", "mismatch", "no_speech"}:
        errors.append("invalid_audio_status")
    if data.get("video_status") not in {"matched", "mismatch", "no_visual"}:
        errors.append("invalid_video_status")
    if data.get("transcript_status") not in {"matched", "partial", "mismatch", "not_provided"}:
        errors.append("invalid_transcript_status")
    events = data.get("events")
    if not isinstance(events, list):
        errors.append("events_not_list")
        events = []
    previous_end = 0.0
    for index, event in enumerate(events):
        prefix = f"event_{index}"
        if not isinstance(event, dict):
            errors.append(f"{prefix}_not_object")
            continue
        start, end = event.get("start_seconds"), event.get("end_seconds")
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not 0 <= float(start) < float(end) <= duration + 0.05):
            errors.append(f"{prefix}_invalid_time")
        elif float(start) < previous_end - 0.05:
            errors.append(f"{prefix}_overlap_or_unordered")
        else:
            previous_end = float(end)
        if event.get("type") not in EVENT_TYPES:
            errors.append(f"{prefix}_invalid_type")
        if event.get("scripture_ref") is not None and not isinstance(event.get("scripture_ref"), str):
            errors.append(f"{prefix}_invalid_scripture_ref")
        if event.get("on_screen_text") is not None and not isinstance(event.get("on_screen_text"), str):
            errors.append(f"{prefix}_invalid_on_screen_text")
        confidence = event.get("confidence")
        if type(confidence) not in (int, float) or not 0 <= float(confidence) <= 1:
            errors.append(f"{prefix}_invalid_confidence")
        if not isinstance(event.get("note"), str) or not event.get("note", "").strip():
            errors.append(f"{prefix}_missing_note")
        errors.extend(_evidence_errors(event.get("evidence"), prefix))
        evidence = event.get("evidence")
        if data.get("audio_status") != "matched" and event.get("type") == "scripture_reading":
            errors.append(f"{prefix}_unsupported_audio_scripture")
        if event.get("on_screen_text") and isinstance(evidence, dict) and evidence.get("video") is not True:
            errors.append(f"{prefix}_unsupported_visual_text")
    pauses = data.get("pause_candidates")
    if not isinstance(pauses, list):
        errors.append("pause_candidates_not_list")
        pauses = []
    for index, pause in enumerate(pauses):
        prefix = f"pause_{index}"
        if not isinstance(pause, dict):
            errors.append(f"{prefix}_not_object")
            continue
        at, length = pause.get("at_seconds"), pause.get("duration_seconds")
        if (type(at) not in (int, float) or type(length) not in (int, float)
                or not 0 <= float(at) <= duration + 0.05 or float(length) < 0.25):
            errors.append(f"{prefix}_invalid_time")
        if pause.get("kind") not in PAUSE_KINDS:
            errors.append(f"{prefix}_invalid_kind")
        confidence = pause.get("confidence")
        if type(confidence) not in (int, float) or not 0 <= float(confidence) <= 1:
            errors.append(f"{prefix}_invalid_confidence")
        if not isinstance(pause.get("note"), str) or not pause.get("note", "").strip():
            errors.append(f"{prefix}_missing_note")
        errors.extend(_evidence_errors(pause.get("evidence"), prefix))
        evidence = pause.get("evidence")
        if data.get("audio_status") != "matched" and isinstance(evidence, dict) and evidence.get("audio") is True:
            errors.append(f"{prefix}_unsupported_audio_pause")
    if not isinstance(data.get("limitations"), list) or any(not isinstance(x, str) for x in data.get("limitations", [])):
        errors.append("invalid_limitations")
    elif data.get("limitations") == ["string"]:
        errors.append("placeholder_limitation")
    return sorted(set(errors))


def validate_expected_audio(data: object, expected_status: str | None) -> list[str]:
    """Check model claims against the audio condition fixed by the harness."""
    if expected_status is None or not isinstance(data, dict):
        return []
    errors: list[str] = []
    if data.get("audio_status") != expected_status:
        errors.append(f"unexpected_audio_status_expected_{expected_status}")
    if expected_status != "matched":
        for index, event in enumerate(data.get("events") or []):
            if not isinstance(event, dict):
                continue
            if event.get("type") == "scripture_reading":
                errors.append(f"event_{index}_forbidden_without_matched_audio")
            evidence = event.get("evidence")
            if isinstance(evidence, dict) and evidence.get("audio") is True:
                errors.append(f"event_{index}_false_audio_evidence")
        for index, pause in enumerate(data.get("pause_candidates") or []):
            if isinstance(pause, dict):
                errors.append(f"pause_{index}_forbidden_without_matched_audio")
    return sorted(set(errors))


def validate_expected_modalities(
        data: object, *, expected_audio_status: str | None = None,
        expected_video_status: str | None = None,
        expected_transcript_status: str | None = None) -> list[str]:
    """Check model evidence claims against modalities fixed by the harness."""
    errors = validate_expected_audio(data, expected_audio_status)
    if not isinstance(data, dict):
        return sorted(set(errors))
    if expected_video_status is not None and data.get("video_status") != expected_video_status:
        errors.append(f"unexpected_video_status_expected_{expected_video_status}")
    if expected_video_status != "matched" and expected_video_status is not None:
        for index, event in enumerate(data.get("events") or []):
            if not isinstance(event, dict):
                continue
            if event.get("on_screen_text"):
                errors.append(f"event_{index}_false_visual_text")
            evidence = event.get("evidence")
            if isinstance(evidence, dict) and evidence.get("video") is True:
                errors.append(f"event_{index}_false_video_evidence")
        for index, pause in enumerate(data.get("pause_candidates") or []):
            if isinstance(pause, dict):
                evidence = pause.get("evidence")
                if isinstance(evidence, dict) and evidence.get("video") is True:
                    errors.append(f"pause_{index}_false_video_evidence")
    if (expected_transcript_status is not None
            and data.get("transcript_status") != expected_transcript_status):
        errors.append(f"unexpected_transcript_status_expected_{expected_transcript_status}")
    if expected_transcript_status == "not_provided":
        for index, event in enumerate(data.get("events") or []):
            if isinstance(event, dict):
                evidence = event.get("evidence")
                if isinstance(evidence, dict) and evidence.get("transcript") is True:
                    errors.append(f"event_{index}_false_transcript_evidence")
        for index, pause in enumerate(data.get("pause_candidates") or []):
            if isinstance(pause, dict):
                evidence = pause.get("evidence")
                if isinstance(evidence, dict) and evidence.get("transcript") is True:
                    errors.append(f"pause_{index}_false_transcript_evidence")
    return sorted(set(errors))
