#!/usr/bin/env python3
"""Validate saved realtime caption session JSONL events."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


EXPECTED_REALTIME_MODEL = "gpt-realtime-translate"
EXPECTED_STABLE_CORRECTION_MODEL = "gpt-5.4-mini"
EXPECTED_TARGET_LANGUAGE = "zh"
ALLOWED_AUDIO_SOURCE_KINDS = {
    "ipad_mic",
    "iphone_mic",
    "authorized_audio_url",
    "authorized_audio_file",
    "authorized_youtube_source",
}
REALTIME_SOURCES = {"openai_realtime_translation_ws", "openai-realtime-webrtc"}
INPUT_TRANSCRIPT_SOURCES = REALTIME_SOURCES | {
    "openai_realtime_transcription_ws",
    "openai_audio_transcription_fallback",
}
STABLE_CORRECTION_SOURCE = "gpt-5.4-mini-stable-correction"
STABLE_CAPTION_SOURCE = "realtime-caption-stabilizer"
INPUT_TYPES = {"input_transcript_delta", "input_transcript_final"}
CAPTION_TYPES = {"caption_delta", "caption_stable", "caption_final"}
SECRET_PATTERNS = [
    "Authorization",
    "Bearer ",
    "apiKey",
    "api_key",
    "client_secret",
    "clientSecret",
    "eventToken",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "/secrets/",
    "BEGIN " + "PRIVATE KEY",
]
RAW_OPENAI_KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{12,}")


def main() -> int:
    args = parse_args()
    raw_text = read_text(args.events_jsonl)
    events = parse_jsonl(raw_text)
    report = validate_realtime_session(
        events=events,
        raw_text=raw_text,
        events_uri=args.events_jsonl,
        expected_model=args.expected_model,
        expected_stable_model=args.expected_stable_model,
        expected_target_language=args.expected_target_language,
        require_session_id=not args.allow_missing_session_id,
        require_model_event=not args.allow_missing_model_event,
        require_caption_stable=args.require_caption_stable,
        require_stable_correction=args.require_stable_correction,
        min_caption_events=args.min_caption_events,
        min_input_events=args.min_input_events,
        min_stable_p95_ms=args.min_stable_p95_ms,
        max_stable_p95_ms=args.max_stable_p95_ms,
    )
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events-jsonl", required=True, help="Local path or gs:// URI for realtime session events.")
    parser.add_argument("--expected-model", default=EXPECTED_REALTIME_MODEL)
    parser.add_argument("--expected-stable-model", default=EXPECTED_STABLE_CORRECTION_MODEL)
    parser.add_argument("--expected-target-language", default=EXPECTED_TARGET_LANGUAGE)
    parser.add_argument(
        "--allow-missing-session-id",
        action="store_true",
        help="Do not fail when archived events lack a sessionId field.",
    )
    parser.add_argument(
        "--allow-missing-model-event",
        action="store_true",
        help="Do not fail when no session/lifecycle event records the realtime model.",
    )
    parser.add_argument(
        "--require-caption-stable",
        action="store_true",
        help="Require at least one realtime-caption-stabilizer caption_stable event.",
    )
    parser.add_argument(
        "--require-stable-correction",
        action="store_true",
        help="Require at least one gpt-5.4-mini stable correction caption_final event.",
    )
    parser.add_argument("--min-caption-events", type=int, default=1)
    parser.add_argument("--min-input-events", type=int, default=1)
    parser.add_argument("--min-stable-p95-ms", type=int, default=0)
    parser.add_argument("--max-stable-p95-ms", type=int, default=6000)
    parser.add_argument("--out", help="Optional JSON report path.")
    args = parser.parse_args()
    if args.min_caption_events < 0 or args.min_input_events < 0:
        raise SystemExit("--min-caption-events and --min-input-events must be >= 0")
    if args.min_stable_p95_ms < 0 or args.max_stable_p95_ms < 0:
        raise SystemExit("--min-stable-p95-ms and --max-stable-p95-ms must be >= 0")
    return args


def validate_realtime_session(
    *,
    events: list[dict[str, Any]],
    raw_text: str,
    events_uri: str,
    expected_model: str = EXPECTED_REALTIME_MODEL,
    expected_stable_model: str = EXPECTED_STABLE_CORRECTION_MODEL,
    expected_target_language: str = EXPECTED_TARGET_LANGUAGE,
    require_session_id: bool = True,
    require_model_event: bool = True,
    require_caption_stable: bool = False,
    require_stable_correction: bool = False,
    min_caption_events: int = 1,
    min_input_events: int = 1,
    min_stable_p95_ms: int = 0,
    max_stable_p95_ms: int = 6000,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    type_counts = Counter(str(event.get("type") or "unknown") for event in events)
    source_counts = Counter(str(event.get("source") or "unspecified") for event in events)
    event_ids = [event.get("id") for event in events]
    session_ids = sorted(
        {
            str(event.get("sessionId"))
            for event in events
            if event.get("sessionId") is not None
        }
    )

    realtime_inputs = [event for event in events if event.get("type") in INPUT_TYPES and is_realtime_source(event)]
    input_transcripts = [
        event for event in events if event.get("type") in INPUT_TYPES and is_input_transcript_source(event)
    ]
    realtime_captions = [event for event in events if event.get("type") in CAPTION_TYPES and is_realtime_source(event)]
    input_with_english = [event for event in input_transcripts if contains_latin(event_text(event))]
    caption_with_chinese = [event for event in realtime_captions if contains_cjk(event_text(event))]
    stable_caption_commits = [event for event in events if is_stable_caption_event(event)]
    stable_latency = latency_summary(stable_caption_commits)
    stable_corrections = [event for event in events if is_stable_correction_event(event, expected_stable_model)]
    realtime_caption_segments = segment_ids(realtime_captions)
    input_transcript_segments = segment_ids(input_transcripts)
    stable_correction_segments = segment_ids(stable_corrections)
    stable_context_segments = stable_correction_context_segments(
        stable_corrections=stable_corrections,
        input_transcripts=input_transcripts,
        realtime_captions=realtime_captions,
    )

    model_values = sorted(
        {
            str(event.get("model"))
            for event in events
            if event.get("model") is not None
        }
    )
    realtime_source_values = sorted(
        {
            str(event.get("source"))
            for event in events
            if str(event.get("source") or "") in REALTIME_SOURCES
        }
    )
    target_language_values = sorted(
        {
            str(event.get("targetLanguage"))
            for event in events
            if event.get("targetLanguage") is not None
        }
    )
    audio_source_values = sorted(audio_source_kind_values(events))

    add_check(checks, "jsonl_has_events", bool(events), len(events))
    add_check(checks, "event_ids_strictly_increasing", event_ids_strictly_increasing(event_ids), event_ids[:5])
    add_check(
        checks,
        "session_id_consistent",
        (not require_session_id and len(session_ids) <= 1) or len(session_ids) == 1,
        session_ids,
    )
    add_check(checks, "secret_strings", not contains_secret_material(raw_text), None)
    add_check(checks, "realtime_sources", bool(realtime_source_values), realtime_source_values)
    add_check(checks, "target_language", expected_target_language in target_language_values, target_language_values)
    add_check(
        checks,
        "audio_source_kind",
        any(value in ALLOWED_AUDIO_SOURCE_KINDS for value in audio_source_values),
        audio_source_values,
    )
    add_check(checks, "input_transcript_events", len(input_transcripts) >= min_input_events, len(input_transcripts))
    add_check(checks, "input_transcript_english", bool(input_with_english), sample_texts(input_with_english))
    add_check(checks, "caption_events", len(realtime_captions) >= min_caption_events, len(realtime_captions))
    add_check(checks, "caption_chinese", bool(caption_with_chinese), sample_texts(caption_with_chinese))
    add_check(
        checks,
        "realtime_model",
        (not require_model_event) or expected_model in model_values,
        model_values,
    )
    if require_caption_stable:
        add_check(checks, "caption_stable", bool(stable_caption_commits), sample_texts(stable_caption_commits))
        add_check(
            checks,
            "caption_stable_window",
            bool(stable_caption_commits) and all(has_stabilizer_window(event) for event in stable_caption_commits),
            [event.get("stabilizerWindow") for event in stable_caption_commits[:2]],
        )
        add_check(
            checks,
            "caption_stable_latency_p95",
            bool(stable_latency)
            and min_stable_p95_ms <= int(stable_latency.get("p95Ms") or 0) <= max_stable_p95_ms,
            stable_latency,
        )
    if require_stable_correction:
        add_check(checks, "stable_correction", bool(stable_corrections), sample_texts(stable_corrections))
        add_check(
            checks,
            "stable_correction_matches_realtime_draft_segment",
            bool(stable_correction_segments & realtime_caption_segments),
            {
                "realtimeDraftSegments": sorted(realtime_caption_segments)[:5],
                "stableCorrectionSegments": sorted(stable_correction_segments)[:5],
            },
        )
        add_check(
            checks,
            "stable_correction_context",
            bool(stable_context_segments),
            {
                "contextSegments": sorted(stable_context_segments)[:5],
                "inputTranscriptSegments": sorted(input_transcript_segments)[:5],
                "realtimeDraftSegments": sorted(realtime_caption_segments)[:5],
                "stableCorrectionSegments": sorted(stable_correction_segments)[:5],
            },
        )

    failed = [check for check in checks if check["state"] == "fail"]
    return {
        "schemaVersion": 1,
        "status": "failed" if failed else "ok",
        "eventsJsonl": safe_uri(events_uri),
        "checks": checks,
        "failedChecks": [check["name"] for check in failed],
        "counts": {
            "events": len(events),
            "byType": dict(sorted(type_counts.items())),
            "bySource": dict(sorted(source_counts.items())),
            "inputTranscriptEvents": len(input_transcripts),
            "realtimeInputTranscriptEvents": len(realtime_inputs),
            "realtimeCaptionEvents": len(realtime_captions),
            "stableCaptionEvents": len(stable_caption_commits),
            "stableCorrectionEvents": len(stable_corrections),
        },
        "models": model_values,
        "sessionIds": session_ids,
        "realtimeSources": realtime_source_values,
        "targetLanguages": target_language_values,
        "audioSourceKinds": audio_source_values,
        "latency": latency_summary(events),
        "stableLatency": stable_latency,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def is_realtime_source(event: dict[str, Any]) -> bool:
    return str(event.get("source") or "") in REALTIME_SOURCES


def is_input_transcript_source(event: dict[str, Any]) -> bool:
    return str(event.get("source") or "") in INPUT_TRANSCRIPT_SOURCES


def is_stable_correction_event(event: dict[str, Any], expected_model: str) -> bool:
    if event.get("type") != "caption_final":
        return False
    source = str(event.get("source") or "")
    model = str(event.get("model") or "")
    text = event_text(event)
    return STABLE_CORRECTION_SOURCE in source and model == expected_model and contains_cjk(text)


def is_stable_caption_event(event: dict[str, Any]) -> bool:
    return (
        event.get("type") == "caption_stable"
        and str(event.get("source") or "") == STABLE_CAPTION_SOURCE
        and str(event.get("stability") or "") == "stable"
        and contains_cjk(event_text(event))
    )


def has_stabilizer_window(event: dict[str, Any]) -> bool:
    window = event.get("stabilizerWindow")
    if not isinstance(window, dict):
        return False
    return (
        int(window.get("windowMs") or 0) >= 5000
        and str(window.get("segmentId") or "") == str(event.get("segmentId") or "")
        and contains_latin(str(window.get("inputTextEn") or ""))
        and contains_cjk(str(window.get("draftZh") or ""))
    )


def segment_ids(events: list[dict[str, Any]]) -> set[str]:
    return {
        str(event.get("segmentId"))
        for event in events
        if str(event.get("segmentId") or "").strip()
    }


def stable_correction_context_segments(
    *,
    stable_corrections: list[dict[str, Any]],
    input_transcripts: list[dict[str, Any]],
    realtime_captions: list[dict[str, Any]],
) -> set[str]:
    input_segments = {
        str(event.get("segmentId"))
        for event in input_transcripts
        if str(event.get("segmentId") or "").strip() and contains_latin(event_text(event))
    }
    draft_segments = {
        str(event.get("segmentId"))
        for event in realtime_captions
        if str(event.get("segmentId") or "").strip() and contains_cjk(event_text(event))
    }
    return {
        str(event.get("segmentId"))
        for event in stable_corrections
        if str(event.get("segmentId") or "").strip()
        and str(event.get("segmentId")) in input_segments
        and str(event.get("segmentId")) in draft_segments
        and contains_latin(str(event.get("en") or event.get("sourceTextEn") or ""))
    }


def normalize_audio_source_kind(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")[:80]


def audio_source_kind_values(events: list[dict[str, Any]]) -> set[str]:
    values: set[str] = set()
    for event in events:
        explicit_value = normalize_audio_source_kind(event.get("audioSourceKind"))
        if explicit_value:
            values.add(explicit_value)
            continue

        source_value = normalize_audio_source_kind(event.get("source"))
        if source_value in ALLOWED_AUDIO_SOURCE_KINDS:
            values.add(source_value)
    return values


def event_text(event: dict[str, Any]) -> str:
    return str(event.get("text") or event.get("zh") or event.get("en") or event.get("delta") or "").strip()


def read_text(uri: str) -> str:
    if uri.startswith("gs://"):
        completed = subprocess.run(["gcloud", "storage", "cat", uri], check=True, capture_output=True, text=True)
        return completed.stdout
    return Path(uri).read_text(encoding="utf-8")


def parse_jsonl(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid JSONL at line {line_no}: {exc}") from exc
        if not isinstance(value, dict):
            raise SystemExit(f"Invalid JSONL at line {line_no}: expected an object.")
        rows.append(value)
    return rows


def add_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any = None) -> None:
    checks.append({"name": name, "state": "pass" if passed else "fail", "observed": observed})


def event_ids_strictly_increasing(values: list[Any]) -> bool:
    if not values:
        return False
    previous = 0
    for value in values:
        try:
            current = int(value)
        except (TypeError, ValueError):
            return False
        if current <= previous:
            return False
        previous = current
    return True


def contains_secret_material(text: str) -> bool:
    return any(pattern in text for pattern in SECRET_PATTERNS) or RAW_OPENAI_KEY_RE.search(text) is not None


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def contains_latin(text: str) -> bool:
    return any(("a" <= char <= "z") or ("A" <= char <= "Z") for char in text)


def sample_texts(events: list[dict[str, Any]], limit: int = 2) -> list[str]:
    return [event_text(event)[:120] for event in events[:limit]]


def latency_summary(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    values = []
    for event in events:
        try:
            values.append(int(event["latencyMs"]))
        except (KeyError, TypeError, ValueError):
            continue
    if not values:
        return None
    return {
        "count": len(values),
        "minMs": min(values),
        "maxMs": max(values),
        "p95Ms": percentile(values, 0.95),
        "avgMs": round(sum(values) / len(values), 1),
    }


def percentile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def safe_uri(uri: str) -> str:
    if uri.startswith("gs://"):
        return uri
    return Path(uri).name


if __name__ == "__main__":
    raise SystemExit(main())
