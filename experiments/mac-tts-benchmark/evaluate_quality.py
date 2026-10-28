#!/usr/bin/env python3
"""Objective quality report for a Mac TTS benchmark run: local MLX ASR + signal metrics.

The ASR score is a diagnostic only (machine listening is retired as a production gate).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics

from scripts import tongxing_host  # noqa: F401  binds the production audio rules
from tongxing_production.review import asr_scoring


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--speech", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--transcripts", type=Path)
    parser.add_argument("--locale", default="zh-Hans")
    parser.add_argument("--language", default="Chinese")
    args = parser.parse_args()

    speech = {row["id"]: row for row in read_jsonl(args.speech)}
    log = read_jsonl(args.run / "tts-log.jsonl")
    transcripts = {row["id"]: row["recognized"] for row in read_jsonl(args.transcripts)} if args.transcripts else None
    if transcripts is None:
        from mlx_audio.stt.utils import load_model
        asr = load_model(str(args.checkpoint))
    rows, failures = [], []
    for entry in log:
        recognized = transcripts[entry["id"]] if transcripts is not None else asr.generate(
            str(args.run / "units" / f"{entry['id']}.wav"), language=args.language, max_tokens=512).text
        expected = speech[entry["id"]]["spokenText"]
        similarity, differences, passed = asr_scoring.score(expected, recognized, args.locale, 0.88)
        row = {"id": entry["id"], "similarity": similarity, "passed": passed,
               "audioSeconds": entry["audioSeconds"], "estimatedSeconds": entry.get("estimatedSeconds"),
               "wallSeconds": entry["wallSeconds"], "recognized": recognized,
               "differences": differences[:5]}
        rows.append(row)
        if not passed:
            failures.append(row)
    if transcripts is None:
        import mlx.core as mx
        mx.clear_cache()
    similarities = [row["similarity"] for row in rows]
    ratios = [row["audioSeconds"] / row["estimatedSeconds"] for row in rows
              if row.get("estimatedSeconds")]
    peaks = [entry["peak"] for entry in log]
    clipped = sum(entry["clipped"] for entry in log)
    report = {
        "schemaVersion": "sermon-mac-tts-quality-v1",
        "run": str(args.run), "locale": args.locale, "units": len(rows),
        "asrSimilarity": {"mean": round(statistics.mean(similarities), 4) if similarities else None,
                          "min": round(min(similarities), 4) if similarities else None,
                          "passRate088": round(sum(row["passed"] for row in rows) / len(rows), 4) if rows else None},
        "durationRatioVsEstimate": {"mean": round(statistics.mean(ratios), 4) if ratios else None,
                                    "p95": round(sorted(ratios)[max(0, int(len(ratios) * 0.95) - 1)], 4) if ratios else None},
        "signal": {"peakMax": max(peaks) if peaks else None, "clippedSamples": clipped},
        "failures": failures,
        "rows": rows,
    }
    (args.run / "quality.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("units", "asrSimilarity", "durationRatioVsEstimate", "signal")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
