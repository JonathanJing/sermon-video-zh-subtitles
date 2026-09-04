#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.asr_gold import read_jsonl, validate_human_gold


WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")
NON_SPEECH_RE = re.compile(
    r"^(?:\[blank_audio\]|\[(?:music|silence|chimes|applause|laughter|inaudible)\]|\((?:music|silence|chimes|applause|laughter|inaudible|birds? chirping|crickets? chirping)\))$",
    re.IGNORECASE,
)


def words(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for ref_index, ref_word in enumerate(reference, start=1):
        current = [ref_index]
        for hyp_index, hyp_word in enumerate(hypothesis, start=1):
            current.append(min(
                current[-1] + 1,
                previous[hyp_index] + 1,
                previous[hyp_index - 1] + (ref_word != hyp_word),
            ))
        previous = current
    return previous[-1]


def percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_reference(path: Path, segment_id: str) -> tuple[str, str]:
    for line in path.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        if item.get("segmentId") == segment_id:
            return item["gptTranscribeEn"], "gpt-transcribe_audio_evidence_not_human_gold"
    raise ValueError(f"reference segment not found: {segment_id} in {path}")


def load_events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def score_case(
    case: dict[str, Any],
    config: dict[str, Any],
    poc_root: Path,
    human_gold: dict[str, str] | None = None,
) -> dict[str, Any]:
    source_root = Path(config["sourceRepository"])
    session_dir = poc_root / "artifacts" / "sessions" / case["sessionId"]
    events = load_events(session_dir / "events.jsonl")
    manifest = json.loads((session_dir / "manifest.json").read_text(encoding="utf-8"))
    if human_gold is not None:
        if case["caseId"] not in human_gold:
            raise ValueError(f"approved human Gold is missing case: {case['caseId']}")
        reference, provenance = human_gold[case["caseId"]], "approved_human_gold"
    else:
        reference, provenance = load_reference(source_root / case["referenceAudit"], case["referenceSegmentId"])
    asr_events = [event for event in events if event.get("type") == "asr.final"]
    suppressed_events = [event for event in events if event.get("type") == "asr.suppressed"]
    translation_events = [event for event in events if event.get("type") == "translation.final"]
    raw_parts = [event.get("sourceTextEn", "").strip() for event in asr_events]
    non_speech = [part for part in raw_parts if NON_SPEECH_RE.fullmatch(part)]
    speech_parts = [part for part in raw_parts if part and not NON_SPEECH_RE.fullmatch(part)]
    raw_hypothesis = " ".join(raw_parts)
    speech_hypothesis = " ".join(speech_parts)
    reference_words = words(reference)
    raw_hypothesis_words = words(raw_hypothesis)
    speech_hypothesis_words = words(speech_hypothesis)
    raw_edits = edit_distance(reference_words, raw_hypothesis_words)
    speech_edits = edit_distance(reference_words, speech_hypothesis_words)
    hypothesis_normalized = " ".join(speech_hypothesis_words)
    phrase_hits = {
        phrase: " ".join(words(phrase)) in hypothesis_normalized
        for phrase in case.get("criticalPhrases", [])
    }
    failure_types = {
        "audio.stream_gap", "audio.frame_rejected", "asr.failed",
        "translation.failed", "pipeline.failed",
    }
    failures = [event.get("type") for event in events if event.get("type") in failure_types]
    asr_latencies = [event["asrMetrics"]["latencyMs"] for event in asr_events]
    translation_latencies = [event["latencyMs"] for event in translation_events]
    integrity = {
        "recordingSha256Matches": sha256(session_dir / manifest["audioFile"]) == manifest["audioSha256"],
        "pcmSha256Matches": sha256(session_dir / manifest["asrPcmFile"]) == manifest["pcmSha256"],
        "wavSha256Matches": sha256(session_dir / manifest["asrWavFile"]) == manifest["pcmWavSha256"],
    }
    return {
        **case,
        "referenceProvenance": provenance,
        "referenceText": reference,
        "asrTextRaw": raw_hypothesis,
        "asrTextSpeechOnly": speech_hypothesis,
        "referenceWordCount": len(reference_words),
        "rawWordErrorCount": raw_edits,
        "rawWer": round(raw_edits / max(1, len(reference_words)), 4),
        "speechOnlyWordErrorCount": speech_edits,
        "speechOnlyWer": round(speech_edits / max(1, len(reference_words)), 4),
        "criticalPhraseHits": phrase_hits,
        "criticalPhraseRecall": round(sum(phrase_hits.values()) / max(1, len(phrase_hits)), 4),
        "asrFinalCount": len(asr_events),
        "translationFinalCount": len(translation_events),
        "nonSpeechOutputCount": len(non_speech),
        "nonSpeechOutputs": non_speech,
        "suppressedAsrCount": len(suppressed_events),
        "suppressedAsrOutputs": [event.get("sourceTextEn") for event in suppressed_events],
        "asrLatencyMs": {
            "median": round(statistics.median(asr_latencies)) if asr_latencies else None,
            "p95": percentile(asr_latencies, 0.95),
            "max": max(asr_latencies, default=None),
        },
        "translationLatencyMs": {
            "median": round(statistics.median(translation_latencies)) if translation_latencies else None,
            "p95": percentile(translation_latencies, 0.95),
            "max": max(translation_latencies, default=None),
        },
        "failureEvents": failures,
        "integrity": integrity,
        "sessionDirectory": str(session_dir),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--poc-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gold", type=Path, help="approved asr-human-gold-review-v1 JSONL")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    poc_root = args.poc_root.resolve() if args.poc_root else args.config.resolve().parent.parent
    human_gold = validate_human_gold(read_jsonl(args.gold)) if args.gold else None
    cases = [score_case(case, config, poc_root, human_gold) for case in config["cases"]]
    reference_words = sum(case["referenceWordCount"] for case in cases)
    speech_edits = sum(case["speechOnlyWordErrorCount"] for case in cases)
    critical_total = sum(len(case["criticalPhraseHits"]) for case in cases)
    critical_hits = sum(sum(case["criticalPhraseHits"].values()) for case in cases)
    result = {
        "schemaVersion": "local-live-acoustic-e2e-report-v1",
        "benchmarkId": config["benchmarkId"],
        "referencePolicy": config["referencePolicy"],
        "capturePath": config["capturePath"],
        "asrModel": config["asrModel"],
        "translationModel": config["translationModel"],
        "summary": {
            "caseCount": len(cases),
            "speakerCount": len({case["speaker"] for case in cases}),
            "referenceWordCount": reference_words,
            ("speechOnlyWer" if human_gold is not None else "provisionalSpeechOnlyWer"):
                round(speech_edits / max(1, reference_words), 4),
            "criticalPhraseRecall": round(critical_hits / max(1, critical_total), 4),
            "nonSpeechOutputCount": sum(case["nonSpeechOutputCount"] for case in cases),
            "suppressedAsrCount": sum(case["suppressedAsrCount"] for case in cases),
            "failureEventCount": sum(len(case["failureEvents"]) for case in cases),
            "allArtifactHashesMatch": all(all(case["integrity"].values()) for case in cases),
        },
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
