#!/usr/bin/env python3
"""Summarize one browser-to-model long-running E2E session.

This is deliberately read-only. It can score an in-progress session, then add
artifact integrity checks after the browser has stopped and finalized it.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


FAILURE_TYPES = {
    "audio.frame_rejected",
    "audio.stream_gap",
    "asr.failed",
    "pipeline.failed",
    "translation.failed",
}
SWAP_USED_RE = re.compile(r"(?<![A-Za-z])used[\s_]*=[\s_]*([0-9.]+)\s*([KMG])")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
FIRST_RENDER_KINDS = {"chinese_first_token", "readable_partial_first", "readable_final_first"}
FINAL_RENDER_KINDS = {"chinese_final", "readable_final", "readable_final_first"}


def percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def distribution(values: list[int]) -> dict[str, int | None]:
    return {
        "p50": round(statistics.median(values)) if values else None,
        "p95": percentile(values, 0.95),
        "max": max(values, default=None),
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def numeric(events: list[dict[str, Any]], event_type: str, *keys: str) -> list[int]:
    values: list[int] = []
    for event in events:
        if event.get("type") != event_type:
            continue
        value: Any = event
        for key in keys:
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, (int, float)):
            values.append(round(value))
    return values


def milliseconds(value: Any) -> int | None:
    return round(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def caption_delivery(events: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    """Measure actual browser renders, never model tokens as visible captions.

    Coverage is per emitted ASR final, not word accuracy or time-based speech
    coverage. No-new-caption intervals include intentional silence and retained
    captions; they must not be described as blank screens or service outages.
    """
    asr_events = [event for event in events if event.get("type") == "asr.final"]
    asr = {event["segmentId"]: event for event in asr_events if event.get("segmentId")}
    translations = {
        event["segmentId"] for event in events
        if event.get("type") == "translation.final" and event.get("segmentId")
    }
    unit_sources: dict[str, list[str]] = {}
    for event in events:
        segment_id = event.get("segmentId")
        sources = event.get("sourceSegmentIds")
        if segment_id and isinstance(sources, list):
            unit_sources[segment_id] = [source for source in sources if isinstance(source, str) and source]

    def source_ids(segment_id: str) -> list[str]:
        return unit_sources.get(segment_id, [segment_id])

    def raw_coverage(unit_ids: set[str]) -> set[str]:
        return {source for unit_id in unit_ids for source in source_ids(unit_id)}
    first: dict[str, dict[str, Any]] = {}
    final: dict[str, dict[str, Any]] = {}
    render_events = [event for event in events if event.get("type") == "caption_rendered"]
    for event in render_events:
        segment_id = event.get("segmentId")
        if not segment_id:
            continue
        kind = event.get("renderKind")
        if kind in FIRST_RENDER_KINDS:
            first.setdefault(segment_id, event)
        if kind in FINAL_RENDER_KINDS:
            final.setdefault(segment_id, event)

    first_end: list[int] = []
    first_start: list[int] = []
    first_source_end: list[int] = []
    final_end: list[int] = []
    for segment_id, event in first.items():
        latency = milliseconds(event.get("audioEndToBrowserRenderMs"))
        sources = source_ids(segment_id)
        if not sources or any(source not in asr for source in sources) or latency is None:
            continue
        first_end.append(latency)
        start = milliseconds(asr[sources[0]].get("audioStartMs"))
        first_end_ms = milliseconds(asr[sources[0]].get("audioEndMs"))
        end = milliseconds(asr[sources[-1]].get("audioEndMs"))
        if start is not None and end is not None and end >= start:
            first_start.append(latency + end - start)
        if first_end_ms is not None and end is not None and end >= first_end_ms:
            first_source_end.append(latency + end - first_end_ms)
    for segment_id, event in final.items():
        latency = milliseconds(event.get("audioEndToBrowserRenderMs"))
        sources = source_ids(segment_id)
        if sources and all(source in asr for source in sources) and latency is not None:
            final_end.append(latency)

    def elapsed_ms(event: dict[str, Any]) -> int | None:
        if (elapsed := milliseconds(event.get("elapsedMs"))) is not None:
            return elapsed
        try:
            timestamp = event.get("browserRenderedAt") or event["at"]
            return milliseconds((
                datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                - datetime.fromisoformat(manifest["startedAt"].replace("Z", "+00:00"))
            ).total_seconds() * 1000)
        except (KeyError, TypeError, ValueError, AttributeError):
            return None

    times = sorted(value for event in render_events if (value := elapsed_ms(event)) is not None)
    duration = milliseconds(manifest.get("durationMs"))
    # A drain may render its last caption after recording has stopped. Do not
    # truncate that evidence or report a negative trailing interval.
    end_of_observation = max(duration, times[-1]) if duration is not None and times else None
    gaps = [later - earlier for earlier, later in zip(times, times[1:])]
    full_timeline = bool(times) and len(times) == len(render_events) and end_of_observation is not None
    denominator = len(asr) if asr and len(asr) == len(asr_events) else None

    def covered(ids: set[str]) -> int:
        return len(raw_coverage(ids) & asr.keys())

    return {
        "definition": "Coverage of emitted raw ASR final IDs through sourceSegmentIds (legacy: segmentId). Latency distributions are per visible translation unit, not speech recall, WER or translation accuracy.",
        "asrFinalSegmentCount": denominator,
        "translationFinalUnitCount": len(translations),
        "firstVisibleUnitCount": len(first),
        "finalVisibleUnitCount": len(final),
        "translationFinalSegmentCount": covered(translations),
        "firstVisibleSegmentCount": covered(set(first)),
        "finalVisibleSegmentCount": covered(set(final)),
        "firstVisibleCoverageRate": covered(set(first)) / denominator if denominator else None,
        "finalVisibleCoverageRate": covered(set(final)) / denominator if denominator else None,
        "missingFirstVisibleSegmentIds": sorted(asr.keys() - raw_coverage(set(first))),
        "missingFinalVisibleSegmentIds": sorted(asr.keys() - raw_coverage(set(final))),
        "unknownSourceSegmentIds": sorted(raw_coverage(translations | first.keys() | final.keys()) - asr.keys()),
        "firstVisibleLatencySampleCount": len(first_end),
        "finalVisibleLatencySampleCount": len(final_end),
        "speechStartLatencySampleCount": len(first_start),
        "firstSourceEndLatencySampleCount": len(first_source_end),
        "renderKindCounts": dict(Counter(event.get("renderKind", "missing") for event in render_events)),
        "audioEndToBrowserFirstVisibleMs": distribution(first_end),
        "audioEndToBrowserFinalVisibleMs": distribution(final_end),
        "audioStartToBrowserFirstVisibleMs": distribution(first_start),
        "firstSourceAudioEndToBrowserFirstVisibleMs": distribution(first_source_end),
        "cadence": {
            "definition": "Intervals with no recorded new browser caption, including silence and retained captions; not blank-screen duration.",
            "completeTimeline": full_timeline,
            "timedRenderEventCount": len(times),
            "firstCaptionAfterSessionStartMs": times[0] if times else None,
            "longestBetweenCaptionUpdatesMs": max(gaps, default=None),
            "trailingNoNewCaptionMs": end_of_observation - times[-1] if full_timeline else None,
            "longestNoNewCaptionIntervalMs": max(
                [times[0], *gaps, end_of_observation - times[-1]]
            ) if full_timeline else None,
        },
    }


def delivery_accounting(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Explain intentional policy skips separately; never qualify them as Gold."""
    raw_events = [event for event in events if event.get("type") == "asr.final"]
    raw_counts = Counter(event["segmentId"] for event in raw_events if event.get("segmentId"))
    raw_ids = set(raw_counts)
    unit_sources: dict[str, list[str]] = {}
    for event in events:
        if event.get("segmentId") and isinstance(event.get("sourceSegmentIds"), list):
            unit_sources[event["segmentId"]] = [
                source for source in event["sourceSegmentIds"] if isinstance(source, str) and source
            ]
    visible_units = {
        event["segmentId"] for event in events
        if event.get("type") == "caption_rendered" and event.get("segmentId")
        and event.get("renderKind") in FIRST_RENDER_KINDS | FINAL_RENDER_KINDS
    }
    # One source in both a partial and final of the same unit is normal; only
    # mapping it into multiple visible units (or twice in one list) is duplicate.
    mapped_counts = Counter(source for unit in visible_units for source in unit_sources.get(unit, [unit]))
    visible_ids = set(mapped_counts) & raw_ids
    guarded_ids: set[str] = set()
    for event in events:
        if event.get("type") == "translation.skipped" and event.get("reason") == "insufficient_lexical_content":
            segment_id = event.get("segmentId")
            if segment_id:
                guarded_ids.update(unit_sources.get(segment_id, [segment_id]))
    known_guarded = guarded_ids & raw_ids
    other_missing = raw_ids - visible_ids - known_guarded
    duplicate_mapped = sorted(source for source, count in mapped_counts.items() if count > 1 and source in raw_ids)
    return {
        "definition": "Raw final disposition accounting only; a visible mapping can include an English/error fallback and does not establish translation accuracy.",
        "lexicalGuardReviewStatus": "policy_decision_not_human_reviewed",
        "rawFinalCount": len(raw_events),
        "rawFinalUniqueIdCount": len(raw_ids),
        "rawFinalMissingIdCount": sum(not event.get("segmentId") for event in raw_events),
        "duplicateRawFinalIds": sorted(source for source, count in raw_counts.items() if count > 1),
        "visibleMappedRawFinalCount": len(visible_ids),
        "lexicalGuardSkippedRawFinalCount": len(known_guarded),
        "lexicalGuardSkippedRawFinalIds": sorted(known_guarded),
        "otherMissingRawFinalCount": len(other_missing),
        "otherMissingRawFinalIds": sorted(other_missing),
        "duplicateMappedRawFinalCount": len(duplicate_mapped),
        "duplicateMappedRawFinalIds": duplicate_mapped,
        "visibleAndLexicalGuardOverlapIds": sorted(visible_ids & known_guarded),
        "unknownMappedRawFinalIds": sorted((set(mapped_counts) | guarded_ids) - raw_ids),
    }


def swap_used_mb(value: str) -> float | None:
    match = SWAP_USED_RE.search(value)
    if not match:
        return None
    amount = float(match.group(1))
    return amount * {"K": 1 / 1024, "M": 1, "G": 1024}[match.group(2)]


def rss_summary(values: list[int]) -> dict[str, int | None]:
    return {
        "firstKb": values[0] if values else None,
        "lastKb": values[-1] if values else None,
        "growthKb": values[-1] - values[0] if values else None,
        "maxKb": max(values, default=None),
    }


def load_ollama_telemetry(path: Path | None) -> dict[str, int | None] | None:
    if path is None:
        return None
    with path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source, delimiter="\t"))
    values = [
        int(row["ollama_rss_kb"])
        for row in rows
        if row.get("ollama_rss_kb", "").isdigit() and int(row["ollama_rss_kb"]) > 0
    ]
    return {**rss_summary(values), "sampleCount": len(values), "expectedSampleCount": len(rows)}


def load_health_telemetry(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    with path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source, delimiter="\t"))
    if not rows:
        return {"sampleCount": 0}
    http_codes = [row.get("http_code") for row in rows]
    return {
        "sampleCount": len(rows),
        "httpCodeSampleCount": sum(bool(value and value.isdigit()) for value in http_codes),
        "http200Samples": sum(value == "200" for value in http_codes),
        "statusSampleCount": sum(row.get("status") in {"ready", "degraded"} for row in rows),
        "readySamples": sum(row.get("status") == "ready" for row in rows),
        "asrAvailableSampleCount": sum(row.get("asr_available") in {"true", "false"} for row in rows),
        "asrAvailableSamples": sum(row.get("asr_available") == "true" for row in rows),
        "liveAvailableSampleCount": sum(row.get("live_available") in {"true", "false"} for row in rows),
        "liveAvailableSamples": sum(row.get("live_available") == "true" for row in rows),
    }


def load_telemetry(
    path: Path | None,
    ollama_path: Path | None = None,
    health_path: Path | None = None,
) -> dict[str, Any] | None:
    if path is None:
        if health_path is None:
            return None
        path = health_path
    with path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source, delimiter="\t"))
    if not rows:
        return {"sampleCount": 0}

    def integers(key: str, *, ignore_zero: bool = False) -> list[int]:
        result = [int(row[key]) for row in rows if row.get(key, "").isdigit()]
        return [value for value in result if value > 0] if ignore_zero else result

    def rss(key: str) -> dict[str, int | None]:
        values = integers(key, ignore_zero=True)
        return rss_summary(values)

    swap: list[float] = []
    for row in rows:
        direct = row.get("swap_used_mb", "")
        if direct.replace(".", "", 1).isdigit():
            swap.append(float(direct))
            continue
        if (value := swap_used_mb(row.get("swap", ""))) is not None:
            swap.append(value)
    supplemental_health = load_health_telemetry(health_path or (path if "http_code" in rows[0] else None))
    health = [row.get("health") or row.get("health_state") for row in rows]
    health_sample_count = supplemental_health.get("sampleCount", 0) if supplemental_health else len(health)
    health_ok_count = (
        supplemental_health.get("http200Samples", 0)
        if supplemental_health else sum(value in {"200", "ready"} for value in health)
    )
    memory_free = [
        int(row["memory_free_percent"])
        for row in rows
        if row.get("memory_free_percent", "").isdigit()
    ]
    return {
        "sampleCount": len(rows),
        "elapsedSeconds": max((
            float(row["elapsed_s"]) for row in rows
            if row.get("elapsed_s", "").replace(".", "", 1).isdigit()
        ), default=None),
        "gatewayHealthSampleCount": health_sample_count,
        "gatewayHttp200Samples": health_ok_count,
        "gatewayNon200Samples": health_sample_count - health_ok_count,
        "supplementalHealth": supplemental_health,
        "gatewayRss": rss("gateway_rss_kb"),
        "gatewayRssSampleCount": len(integers("gateway_rss_kb")),
        "mlxRss": rss("mlx_rss_kb"),
        "mlxRssSampleCount": len(integers("mlx_rss_kb")),
        "mlxProcessMissingSamples": sum(value == 0 for value in integers("mlx_rss_kb")) if integers("mlx_rss_kb") else None,
        # A zero-only series means the sampler could not resolve the process.
        "ollamaRss": load_ollama_telemetry(ollama_path) or {
            **rss("ollama_rss_kb"), "sampleCount": len(integers("ollama_rss_kb", ignore_zero=True)),
            "expectedSampleCount": len(rows),
        },
        "swapUsedMb": {
            "sampleCount": len(swap),
            "expectedSampleCount": len(rows),
            "first": swap[0] if swap else None,
            "last": swap[-1] if swap else None,
            "max": max(swap, default=None),
        },
        "memoryFreePercent": {
            "first": memory_free[0] if memory_free else None,
            "last": memory_free[-1] if memory_free else None,
            "min": min(memory_free, default=None),
        },
    }


def measurement_evidence(
    manifest: dict[str, Any], delivery: dict[str, Any], integrity: dict[str, Any],
    counts: Counter, failure_count: int, telemetry: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fail closed on incomplete measurements without claiming venue readiness."""
    expected = delivery["asrFinalSegmentCount"]
    expected_units = delivery["translationFinalUnitCount"]
    health = (telemetry or {}).get("supplementalHealth") or {}
    samples = (telemetry or {}).get("sampleCount", 0)
    health_samples = health.get("sampleCount", 0)
    runtime = manifest.get("metadata", {}).get("runtimeIdentity") or manifest.get("runtimeIdentity") or {}
    git = runtime.get("git") or {}

    def full_count(actual: int, denominator: int | None) -> str:
        return "missing" if not denominator else "pass" if actual == denominator else "fail"

    checks = {
        "completedSession": "pass" if manifest.get("status") == "completed" else "fail",
        "artifactHashes": "pass" if all(item["sha256Matches"] is True for item in integrity.values()) else "missing" if any(item["sha256Matches"] is None for item in integrity.values()) else "fail",
        "pipelineFailures": "missing" if not counts["asr.processing"] else "pass" if failure_count == 0 else "fail",
        "asrOutcomesAccounted": full_count(sum(counts[k] for k in ("asr.final", "asr.empty", "asr.suppressed", "asr.failed")), counts["asr.processing"]),
        "translationCoverage": full_count(delivery["translationFinalSegmentCount"], expected),
        "firstVisibleCoverage": full_count(delivery["firstVisibleSegmentCount"], expected),
        "finalVisibleCoverage": full_count(delivery["finalVisibleSegmentCount"], expected),
        "sourceSegmentMapping": "fail" if delivery["unknownSourceSegmentIds"] else "pass" if expected else "missing",
        "firstVisibleTiming": full_count(delivery["firstVisibleLatencySampleCount"], expected_units),
        "finalVisibleTiming": full_count(delivery["finalVisibleLatencySampleCount"], expected_units),
        "speechStartTiming": full_count(delivery["speechStartLatencySampleCount"], expected_units),
        "firstSourceEndTiming": full_count(delivery["firstSourceEndLatencySampleCount"], expected_units),
        "captionTimeline": "pass" if delivery["cadence"]["completeTimeline"] else "missing",
        "swapSamples": "pass" if samples >= 2 and (telemetry or {}).get("swapUsedMb", {}).get("sampleCount") == samples else "missing",
        "gatewayRssSamples": "pass" if samples >= 2 and (telemetry or {}).get("gatewayRssSampleCount") == samples else "missing",
        "asrRssSamples": "pass" if samples >= 2 and (telemetry or {}).get("mlxRssSampleCount") == samples else "missing",
        "translationRssSamples": "pass" if (telemetry or {}).get("ollamaRss", {}).get("sampleCount", 0) >= 2 and (telemetry or {}).get("ollamaRss", {}).get("sampleCount") == (telemetry or {}).get("ollamaRss", {}).get("expectedSampleCount") else "missing",
        "healthSamples": "missing" if not health_samples or any(health.get(key, 0) != health_samples for key in ("httpCodeSampleCount", "statusSampleCount", "asrAvailableSampleCount", "liveAvailableSampleCount")) else "pass",
        "healthReady": "missing" if not health_samples else "pass" if all(health.get(key, 0) == health_samples for key in ("http200Samples", "readySamples", "asrAvailableSamples", "liveAvailableSamples")) else "fail",
        "cleanRuntimeRevision": "missing" if not git.get("revision") or git.get("dirty") is None or not runtime.get("fingerprintSha256") else "pass" if git["dirty"] is False else "fail",
    }
    return {
        "scope": "Saved session delivery and measurement completeness only; no ASR accuracy, translation quality, phone delivery or venue readiness claim.",
        "passed": all(value == "pass" for value in checks.values()),
        "checks": checks,
    }


def artifact_integrity(session_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    specs = (
        ("recording", "audioFile", "audioSha256"),
        ("pcm", "asrPcmFile", "pcmSha256"),
        ("wav", "asrWavFile", "pcmWavSha256"),
    )
    result: dict[str, Any] = {}
    for label, file_key, hash_key in specs:
        filename = manifest.get(file_key)
        expected = manifest.get(hash_key)
        path = session_dir / filename if filename else None
        result[label] = {
            "exists": bool(path and path.exists()),
            "sha256Matches": sha256(path) == expected if path and path.exists() and expected else None,
        }
    return result


def score(
    session_dir: Path,
    telemetry_path: Path | None,
    ollama_telemetry_path: Path | None = None,
    health_telemetry_path: Path | None = None,
) -> dict[str, Any]:
    manifest = json.loads((session_dir / "manifest.json").read_text(encoding="utf-8"))
    events = load_jsonl(session_dir / manifest.get("eventFile", "events.jsonl"))
    counts = Counter(event.get("type", "unknown") for event in events)
    asr_texts = [
        event.get("sourceTextEn", "").strip()
        for event in events
        if event.get("type") == "asr.final" and event.get("sourceTextEn", "").strip()
    ]
    normalized = Counter(text.casefold() for text in asr_texts)
    short_repeats = [
        {"text": text, "count": count, "shareOfNonEmptyAsrFinals": round(count / len(asr_texts), 4)}
        for text, count in normalized.most_common(10)
        if len(text.split()) <= 3 and count >= 2
    ]
    unexpected_cjk = [text for text in asr_texts if CJK_RE.search(text)]
    sequences = [event["sequence"] for event in events if isinstance(event.get("sequence"), int)]
    sequence_anomalies = sum(current <= previous for previous, current in zip(sequences, sequences[1:]))
    failures = [event for event in events if event.get("type") in FAILURE_TYPES]
    failure_reasons = Counter(
        event.get("message") or event.get("reason") or event.get("stage") or "unspecified"
        for event in failures
    )
    telemetry = load_telemetry(telemetry_path, ollama_telemetry_path, health_telemetry_path)
    gateway_samples = telemetry.get("gatewayHealthSampleCount", 0) if telemetry else 0
    gateway_http_200 = telemetry.get("gatewayHttp200Samples", 0) if telemetry else 0
    asr_processing = counts["asr.processing"]
    translation_started = counts["translation.started"]

    latency = {
        "asrQueueWaitMs": distribution(numeric(events, "asr.final", "uxMetrics", "asrQueueWaitMs")),
        "audioEndToAsrFinalMs": distribution(numeric(events, "asr.final", "uxMetrics", "audioEndToAsrFinalMs")),
        "translationTtftMs": distribution(numeric(events, "translation.final", "uxMetrics", "translationTtftMs")),
        "audioEndToChineseFirstTokenMs": distribution(
            numeric(events, "translation.final", "uxMetrics", "audioEndToChineseFirstTokenMs")
        ),
        "audioEndToChineseFinalMs": distribution(
            numeric(events, "translation.final", "uxMetrics", "audioEndToChineseFinalMs")
        ),
        "audioEndToBrowserFirstTokenMs": distribution([
            round(event["audioEndToBrowserRenderMs"])
            for event in events
            if event.get("type") == "caption_rendered"
            and event.get("renderKind") == "chinese_first_token"
            and isinstance(event.get("audioEndToBrowserRenderMs"), (int, float))
        ]),
    }
    finalized = manifest.get("status") == "completed"
    integrity = artifact_integrity(session_dir, manifest)
    delivery = caption_delivery(events, manifest)
    # Keep the legacy token metric unchanged; the explicit visible metrics work
    # for both legacy and readable_chunks and are the current UX measurements.
    for key in ("audioEndToBrowserFirstVisibleMs", "audioEndToBrowserFinalVisibleMs", "audioStartToBrowserFirstVisibleMs", "firstSourceAudioEndToBrowserFirstVisibleMs"):
        latency[key] = delivery[key]
    return {
        "schemaVersion": "local-live-soak-e2e-report-v1",
        "sessionId": manifest.get("sessionId", session_dir.name),
        "sessionStatus": manifest.get("status"),
        "durationMs": manifest.get("durationMs"),
        "eventCounts": dict(sorted(counts.items())),
        "failureEventCount": len(failures),
        "failureEventTypes": dict(Counter(event.get("type") for event in failures)),
        "failureReasonCounts": dict(failure_reasons.most_common()),
        "failureDetails": [
            {
                "type": event.get("type"),
                "segmentId": event.get("segmentId"),
                "reason": event.get("reason"),
                "message": event.get("message"),
            }
            for event in failures[:20]
        ],
        "availability": {
            "gatewayHttp200Rate": round(gateway_http_200 / gateway_samples, 4) if gateway_samples else None,
            "asrFinalRate": round(counts["asr.final"] / asr_processing, 4) if asr_processing else None,
            "translationFinalRate": (
                round(counts["translation.final"] / translation_started, 4)
                if translation_started else None
            ),
        },
        "sequenceNonIncreasingCount": sequence_anomalies,
        "asr": {
            "finalCount": counts["asr.final"],
            "emptyCount": counts["asr.empty"],
            "suppressedCount": counts["asr.suppressed"],
            "suppressedReasonCounts": dict(Counter(
                event.get("reason", "unspecified")
                for event in events if event.get("type") == "asr.suppressed"
            )),
            "nonEmptyFinalCount": len(asr_texts),
            "translationFinalCount": counts["translation.final"],
            "shortRepeatedOutputCandidates": short_repeats,
            "unexpectedCjkOutputCount": len(unexpected_cjk),
            "unexpectedCjkOutputs": unexpected_cjk[:20],
        },
        "latency": latency,
        "captionDelivery": delivery,
        "deliveryAccounting": delivery_accounting(events),
        "measurementEvidence": measurement_evidence(manifest, delivery, integrity, counts, len(failures), telemetry),
        "runtimeIdentity": manifest.get("metadata", {}).get("runtimeIdentity") or manifest.get("runtimeIdentity"),
        "telemetry": telemetry,
        "artifactIntegrity": integrity if finalized else {"pending": True},
        "allFinalizedArtifactHashesMatch": (
            all(item["sha256Matches"] is True for item in integrity.values()) if finalized else None
        ),
        "sessionDirectory": str(session_dir.resolve()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--telemetry", type=Path)
    parser.add_argument("--ollama-telemetry", type=Path)
    parser.add_argument("--health-telemetry", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = score(
        args.session_dir,
        args.telemetry,
        args.ollama_telemetry,
        args.health_telemetry,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "sessionId": result["sessionId"],
        "status": result["sessionStatus"],
        "failures": result["failureEventCount"],
        "asrFinals": result["asr"]["finalCount"],
        "latency": result["latency"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
