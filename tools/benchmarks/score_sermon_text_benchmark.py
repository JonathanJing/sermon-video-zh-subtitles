#!/usr/bin/env python3
"""Score reference-blind sermon predictions after generation has completed."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from sacrebleu.metrics import BLEU, CHRF


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--reference", type=Path, action="append", required=True)
    parser.add_argument("--system-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    args = parse_args()
    predictions = load_jsonl(args.predictions)
    references: dict[str, dict[str, Any]] = {}
    for path in args.reference:
        for row in load_jsonl(path):
            segment_id = str(row["id"])
            if segment_id in references:
                raise ValueError(f"duplicate reference segment: {segment_id}")
            references[segment_id] = row
    prediction_ids = [str(row["segmentId"]) for row in predictions]
    if len(prediction_ids) != len(set(prediction_ids)):
        raise ValueError("duplicate prediction segment IDs")
    if set(prediction_ids) != set(references):
        missing = sorted(set(references) - set(prediction_ids))
        extra = sorted(set(prediction_ids) - set(references))
        raise ValueError(f"prediction/reference coverage mismatch: missing={missing[:5]} extra={extra[:5]}")
    if any(row.get("error") or not str(row.get("translation") or "").strip() for row in predictions):
        raise ValueError("predictions contain errors or empty translations")
    if any(str(row.get("english")) != str(references[str(row["segmentId"])]["en"]) for row in predictions):
        raise ValueError("prediction English text differs from the frozen reference input")

    bleu = BLEU(tokenize="zh", effective_order=True)
    chrf = CHRF(char_order=6, word_order=0, beta=2)

    def score(rows: list[dict[str, Any]]) -> tuple[float, float, int, int, float]:
        candidates = [str(row["translation"]) for row in rows]
        targets = [str(references[str(row["segmentId"])]["zh"]) for row in rows]
        terms = [
            term["zh"]
            for row in rows
            for term in references[str(row["segmentId"])].get("properNouns", [])
            if term.get("zh")
        ]
        hits = sum(
            term["zh"] in str(row["translation"])
            for row in rows
            for term in references[str(row["segmentId"])].get("properNouns", [])
            if term.get("zh")
        )
        recall = round(100 * hits / len(terms), 4) if terms else 0.0
        return (
            round(bleu.corpus_score(candidates, [targets]).score, 4),
            round(chrf.corpus_score(candidates, [targets]).score, 4),
            hits,
            len(terms),
            recall,
        )

    bleu_score, chrf_score, hits, annotations, recall = score(predictions)
    per_sermon = []
    for sermon_id in sorted({str(row["sermonId"]) for row in predictions}):
        rows = [row for row in predictions if str(row["sermonId"]) == sermon_id]
        sermon_bleu, sermon_chrf, sermon_hits, sermon_annotations, sermon_recall = score(rows)
        per_sermon.append({
            "sermonId": sermon_id,
            "segmentCount": len(rows),
            "bleuZh": sermon_bleu,
            "chrf2": sermon_chrf,
            "strictAnnotatedTermHitCount": sermon_hits,
            "strictAnnotatedTermCount": sermon_annotations,
            "strictAnnotatedTermRecallPercent": sermon_recall,
        })
    result = {
        "schemaVersion": "live-sermon-text-automatic-metrics-v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "systemId": args.system_id,
        "referenceUsedForGeneration": False,
        "referenceUsedForScoring": True,
        "referenceStatus": "sol_reviewed_audio_audited_not_human_gold",
        "predictionSha256": sha256_file(args.predictions),
        "tool": {"name": "sacrebleu", "version": "2.5.1"},
        "metrics": {
            "bleuSignature": bleu.get_signature().format(),
            "chrfSignature": chrf.get_signature().format(),
            "bleuZh": bleu_score,
            "chrf2": chrf_score,
            "strictAnnotatedTermRecall": {
                "definition": "Count of properNouns[].zh exact substrings present in the candidate divided by all annotated occurrences. Valid variants are not credited.",
                "hitCount": hits,
                "annotationCount": annotations,
                "percent": recall,
            },
        },
        "perSermon": per_sermon,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
