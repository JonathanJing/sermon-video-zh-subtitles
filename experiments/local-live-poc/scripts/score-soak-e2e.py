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
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


FAILURE_TYPES = {
    "audio.frame_rejected",
    "audio.stream_gap",
    "asr.failed",
    "pipeline.failed",
    "translation.failed",
}
SWAP_USED_RE = re.compile(r"used_=_([0-9.]+)([KMG])")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


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
    return rss_summary(values)


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
        "http200Samples": sum(value == "200" for value in http_codes),
        "readySamples": sum(row.get("status") == "ready" for row in rows),
        "asrAvailableSamples": sum(row.get("asr_available") == "true" for row in rows),
        "liveAvailableSamples": sum(row.get("live_available") == "true" for row in rows),
    }


def load_telemetry(
    path: Path | None,
    ollama_path: Path | None = None,
    health_path: Path | None = None,
) -> dict[str, Any] | None:
    if path is None:
        return None
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
    supplemental_health = load_health_telemetry(health_path)
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
        "elapsedSeconds": max(integers("elapsed_s"), default=None),
        "gatewayHealthSampleCount": health_sample_count,
        "gatewayHttp200Samples": health_ok_count,
        "gatewayNon200Samples": health_sample_count - health_ok_count,
        "supplementalHealth": supplemental_health,
        "gatewayRss": rss("gateway_rss_kb"),
        "mlxRss": rss("mlx_rss_kb"),
        "mlxProcessMissingSamples": sum(value == 0 for value in integers("mlx_rss_kb")),
        # A zero-only series means the sampler could not resolve the process.
        "ollamaRss": load_ollama_telemetry(ollama_path) or rss("ollama_rss_kb"),
        "swapUsedMb": {
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
