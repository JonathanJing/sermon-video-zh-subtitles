#!/usr/bin/env python3
"""Compare Qwen ForcedAligner and MFA on one frozen transcript/audio pair.

This script compares structural validity and boundary agreement. It does not
declare either aligner more accurate without independently reviewed word Gold.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import statistics


SCHEMA = "sermon-word-aligner-comparison-v1"
TOKEN_RE = re.compile(r"[a-z0-9]+(?:['’][a-z0-9]+)?", re.I)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalized_tokens(text: str) -> list[str]:
    return [token.lower().replace("’", "'") for token in TOKEN_RE.findall(text or "")]


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("Percentile requires at least one value")
    if not 0 <= fraction <= 1:
        raise ValueError("Percentile fraction must be between zero and one")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def timing_summary(values: list[float]) -> dict:
    return {
        "median": round(statistics.median(values), 6),
        "p90": round(percentile(values, 0.90), 6),
        "p95": round(percentile(values, 0.95), 6),
        "max": round(max(values), 6),
    }


def validate_words(words: list[dict], label: str) -> dict:
    invalid = []
    previous_end = 0.0
    for index, word in enumerate(words, start=1):
        start, end = word.get("start"), word.get("end")
        reasons = []
        if (isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end)):
            reasons.append("nonfinite_or_nonnumeric_time")
        else:
            if start < 0:
                reasons.append("negative_start")
            if end <= start:
                reasons.append("zero_or_negative_duration")
            if start < previous_end - 1e-6:
                reasons.append("nonmonotonic_or_overlapping_word")
            previous_end = max(previous_end, float(end))
        tokens = normalized_tokens(str(word.get("text", "")))
        if len(tokens) != 1:
            reasons.append("not_exactly_one_normalized_word")
        if reasons:
            invalid.append({
                "index": index,
                "text": word.get("text"),
                "start": start,
                "end": end,
                "reasons": reasons,
            })
    return {
        "label": label,
        "wordCount": len(words),
        "invalidWordCount": len(invalid),
        "zeroOrNegativeDurationCount": sum(
            "zero_or_negative_duration" in item["reasons"] for item in invalid
        ),
        "invalidWords": invalid,
        "structurallyValid": not invalid,
    }


def flatten_mfa_words(segments: list[dict]) -> list[dict]:
    return [word for segment in segments for word in segment.get("wordTimes", [])]


def compare(frozen_text: str, qwen_words: list[dict], mfa_words: list[dict],
            review_delta_seconds: float) -> tuple[dict, list[dict]]:
    frozen_tokens = normalized_tokens(frozen_text)
    qwen_tokens = [token for word in qwen_words for token in normalized_tokens(str(word.get("text", "")))]
    mfa_tokens = [token for word in mfa_words for token in normalized_tokens(str(word.get("text", "")))]
    if frozen_tokens != qwen_tokens:
        raise ValueError("Qwen aligned tokens differ from the frozen transcript")
    if frozen_tokens != mfa_tokens:
        raise ValueError("MFA aligned tokens differ from the frozen transcript")
    if len(qwen_words) != len(mfa_words) or len(qwen_words) != len(frozen_tokens):
        raise ValueError("Comparison requires one aligned word per frozen transcript token")

    qwen_validation = validate_words(qwen_words, "qwen-forced-aligner")
    mfa_validation = validate_words(mfa_words, "mfa")
    pairs = []
    starts, ends, midpoints, durations = [], [], [], []
    for index, (token, qwen, mfa) in enumerate(zip(frozen_tokens, qwen_words, mfa_words), start=1):
        q_start, q_end = float(qwen["start"]), float(qwen["end"])
        m_start, m_end = float(mfa["start"]), float(mfa["end"])
        start_delta = abs(q_start - m_start)
        end_delta = abs(q_end - m_end)
        midpoint_delta = abs((q_start + q_end) / 2 - (m_start + m_end) / 2)
        duration_delta = abs((q_end - q_start) - (m_end - m_start))
        starts.append(start_delta)
        ends.append(end_delta)
        midpoints.append(midpoint_delta)
        durations.append(duration_delta)
        reasons = []
        if q_end <= q_start:
            reasons.append("qwen_zero_or_negative_duration")
        if m_end <= m_start:
            reasons.append("mfa_zero_or_negative_duration")
        if midpoint_delta > review_delta_seconds:
            reasons.append("midpoint_delta_over_threshold")
        pairs.append({
            "index": index,
            "token": token,
            "qwenText": qwen.get("text"),
            "qwenStart": round(q_start, 6),
            "qwenEnd": round(q_end, 6),
            "mfaText": mfa.get("text"),
            "mfaStart": round(m_start, 6),
            "mfaEnd": round(m_end, 6),
            "startAbsDeltaSeconds": round(start_delta, 6),
            "endAbsDeltaSeconds": round(end_delta, 6),
            "midpointAbsDeltaSeconds": round(midpoint_delta, 6),
            "durationAbsDeltaSeconds": round(duration_delta, 6),
            "reviewReasons": reasons,
        })
    comparison = {
        "normalizedTokenSequenceExactMatch": True,
        "comparedWordCount": len(pairs),
        "reviewDeltaSeconds": review_delta_seconds,
        "wordPairsRequiringReview": sum(bool(pair["reviewReasons"]) for pair in pairs),
        "absoluteBoundaryDeltaSeconds": {
            "start": timing_summary(starts),
            "end": timing_summary(ends),
            "midpoint": timing_summary(midpoints),
            "duration": timing_summary(durations),
        },
        "midpointDeltaCounts": {
            "over50ms": sum(value > 0.05 for value in midpoints),
            "over100ms": sum(value > 0.10 for value in midpoints),
            "over250ms": sum(value > 0.25 for value in midpoints),
        },
        "qwen": qwen_validation,
        "mfa": mfa_validation,
        "structuralResult": (
            "mfa_pass_qwen_fail" if mfa_validation["structurallyValid"] and not qwen_validation["structurallyValid"]
            else "both_pass" if mfa_validation["structurallyValid"] and qwen_validation["structurallyValid"]
            else "both_fail" if not mfa_validation["structurallyValid"] and not qwen_validation["structurallyValid"]
            else "qwen_pass_mfa_fail"
        ),
        "timingAccuracyWinner": None,
        "timingAccuracyReason": "Independent human-reviewed word boundary Gold was not supplied.",
    }
    return comparison, pairs


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_tsv(path: Path, pairs: list[dict]) -> None:
    fields = list(pairs[0])
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for pair in pairs:
            writer.writerow({**pair, "reviewReasons": ",".join(pair["reviewReasons"])})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--asr", type=Path, required=True)
    parser.add_argument("--qwen-alignment", type=Path, required=True)
    parser.add_argument("--mfa-segments", type=Path, required=True)
    parser.add_argument("--mfa-runtime", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--review-delta-seconds", type=float, default=0.08)
    args = parser.parse_args()
    if args.review_delta_seconds < 0:
        raise ValueError("Review delta must be nonnegative")
    for path in (args.audio, args.asr, args.qwen_alignment, args.mfa_segments):
        if not path.is_file():
            raise ValueError(f"Required comparison input is missing: {path}")

    asr = json.loads(args.asr.read_text(encoding="utf-8"))
    qwen = json.loads(args.qwen_alignment.read_text(encoding="utf-8"))
    mfa_segments = json.loads(args.mfa_segments.read_text(encoding="utf-8"))
    frozen_text = str(asr.get("text", ""))
    comparison, pairs = compare(
        frozen_text,
        list(qwen.get("words", [])),
        flatten_mfa_words(mfa_segments),
        args.review_delta_seconds,
    )
    mfa_runtime = None
    if args.mfa_runtime:
        if not args.mfa_runtime.is_file():
            raise ValueError(f"MFA runtime receipt is missing: {args.mfa_runtime}")
        mfa_runtime = json.loads(args.mfa_runtime.read_text(encoding="utf-8"))
    report = {
        "schemaVersion": SCHEMA,
        "status": "machine_comparison_requires_human_gold",
        "humanWordBoundaryGold": "not_supplied",
        "input": {
            "audioPath": str(args.audio.resolve()),
            "audioSha256": sha256(args.audio),
            "asrPath": str(args.asr.resolve()),
            "asrSha256": sha256(args.asr),
            "frozenTextSha256": text_sha256(frozen_text),
            "normalizedTokenCount": len(normalized_tokens(frozen_text)),
        },
        "qwen": {
            "alignmentPath": str(args.qwen_alignment.resolve()),
            "alignmentSha256": sha256(args.qwen_alignment),
            "model": qwen.get("model"),
            "inferenceReceipt": qwen.get("inferenceReceipt"),
        },
        "mfa": {
            "segmentsPath": str(args.mfa_segments.resolve()),
            "segmentsSha256": sha256(args.mfa_segments),
            "runtimeReceipt": mfa_runtime,
        },
        "comparison": comparison,
        "reviewPairs": [pair for pair in pairs if pair["reviewReasons"]],
        "limitations": [
            "Boundary agreement is not accuracy; both aligners can agree on an incorrect boundary.",
            "The frozen transcript is an ASR candidate and has not been proven complete or verbatim.",
            "This is one 60-second historical sermon excerpt, not the reported 2026-09-20 playback segment.",
        ],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / "comparison-report.json", report)
    write_tsv(args.out / "word-comparison.tsv", pairs)
    print(json.dumps({
        "status": report["status"],
        "structuralResult": comparison["structuralResult"],
        "words": comparison["comparedWordCount"],
        "qwenInvalid": comparison["qwen"]["invalidWordCount"],
        "mfaInvalid": comparison["mfa"]["invalidWordCount"],
        "midpointDelta": comparison["absoluteBoundaryDeltaSeconds"]["midpoint"],
        "report": str((args.out / "comparison-report.json").resolve()),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
