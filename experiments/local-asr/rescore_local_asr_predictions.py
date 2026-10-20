#!/usr/bin/env python3
"""Rescore frozen ASR predictions against a revised reference manifest."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_local_asr_benchmark import (  # noqa: E402
    SCORABLE_REFERENCE_STATUSES,
    contains_term,
    edit_distance,
    normalize_words,
    percentile,
    sha256_file,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = (REPO_ROOT / args.manifest).resolve()
    source_run = (REPO_ROOT / args.source_run).resolve()
    output_dir = (REPO_ROOT / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(manifest_path.read_text())
    items = {item["id"]: item for item in manifest["items"]}
    source_report_path = source_run / "run-report.json"
    source_predictions_path = source_run / "predictions.jsonl"
    source_report = json.loads(source_report_path.read_text())
    if source_report["predictionsSha256"] != sha256_file(source_predictions_path):
        raise SystemExit("Source predictions hash mismatch")
    source_predictions = [
        json.loads(line) for line in source_predictions_path.read_text().splitlines() if line
    ]
    if {row["id"] for row in source_predictions} != set(items):
        raise SystemExit("Source predictions and revised manifest item sets differ")

    predictions = []
    for source in source_predictions:
        item = items[source["id"]]
        transcript = source["transcript"]
        speech_expected = item.get("speechExpected", True)
        row = {
            **source,
            "referenceStatus": item["referenceStatus"],
            "speechExpected": speech_expected,
            "nonempty": bool(normalize_words(transcript)),
        }
        row["outputValid"] = bool(
            row["exitCode"] == 0
            and row["parseError"] is None
            and (row["nonempty"] or not speech_expected)
        )
        if item["referenceStatus"] not in SCORABLE_REFERENCE_STATUSES:
            raise SystemExit(f"Unscorable revised reference: {item['id']}")
        reference_words = normalize_words(item["referenceText"])
        row["wordErrorCount"] = edit_distance(reference_words, normalize_words(transcript))
        row["referenceWordCount"] = len(reference_words)
        row["criticalTermHits"] = sum(
            contains_term(transcript, term) for term in item.get("criticalTerms", [])
        )
        row["criticalTermCount"] = len(item.get("criticalTerms", []))
        predictions.append(row)

    prediction_path = output_dir / "predictions.jsonl"
    prediction_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in predictions)
    )
    latencies = [row["latencySeconds"] for row in predictions]
    rtfs = [row["rtf"] for row in predictions]
    reference_words = sum(row["referenceWordCount"] for row in predictions)
    term_count = sum(row["criticalTermCount"] for row in predictions)
    silence_items = [row for row in predictions if not row["speechExpected"]]
    human_gold = [row for row in predictions if row["referenceStatus"] == "human_gold"]
    model_reviewed = [
        row for row in predictions if row["referenceStatus"] == "model_reviewed_reference"
    ]
    gpt_reaudited = [
        row for row in predictions if row["referenceStatus"] == "gpt_reaudited_reference"
    ]
    report = {
        **source_report,
        "manifest": str(manifest_path.relative_to(REPO_ROOT)),
        "manifestSha256": sha256_file(manifest_path),
        "rescoreOnly": True,
        "sourceRun": str(source_run.relative_to(REPO_ROOT)),
        "sourceRunReportSha256": sha256_file(source_report_path),
        "itemCount": len(predictions),
        "successCount": sum(row["outputValid"] for row in predictions),
        "nonemptyCount": sum(row["nonempty"] for row in predictions),
        "emptyExpectedSpeechCount": sum(
            row["speechExpected"] and not row["nonempty"] for row in predictions
        ),
        "errorCount": sum(not row["outputValid"] for row in predictions),
        "latencySeconds": {
            "mean": round(statistics.mean(latencies), 4),
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "max": round(max(latencies), 4),
        },
        "rtf": {
            "mean": round(statistics.mean(rtfs), 4),
            "p50": percentile(rtfs, 0.50),
            "p95": percentile(rtfs, 0.95),
            "max": round(max(rtfs), 4),
        },
        "quality": {
            "status": "scored_mixed_reference_tiers",
            "scoredItemCount": len(predictions),
            "humanGoldItemCount": len(human_gold),
            "modelReviewedReferenceItemCount": len(model_reviewed),
            "gptReauditedReferenceItemCount": len(gpt_reaudited),
            "wer": round(
                sum(row["wordErrorCount"] for row in predictions) / reference_words, 6
            ),
            "criticalTermRecall": round(
                sum(row["criticalTermHits"] for row in predictions) / term_count, 6
            ),
            "silenceItemCount": len(silence_items),
            "silenceHallucinationCount": sum(row["nonempty"] for row in silence_items),
        },
        "performanceInterpretation": source_report["performanceInterpretation"]
        + " Predictions were rescored without rerunning inference.",
        "predictionsSha256": sha256_file(prediction_path),
    }
    (output_dir / "run-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(report["quality"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
