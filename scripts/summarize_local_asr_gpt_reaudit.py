#!/usr/bin/env python3
"""Summarize reference deltas from a GPT-Transcribe ASR re-audit."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_local_asr_benchmark import edit_distance, normalize_words, sha256_file  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirmation-queue", type=Path, required=True)
    args = parser.parse_args()
    results_path = (REPO_ROOT / args.results).resolve()
    queue_path = (REPO_ROOT / args.queue).resolve()
    queue = json.loads(queue_path.read_text())
    queue_by_id = {row["id"]: row for row in queue["items"]}
    rows = [json.loads(line) for line in results_path.read_text().splitlines() if line]
    output_rows = []
    for row in rows:
        old_words = normalize_words(row["modelReviewedReferenceText"])
        new_words = normalize_words(row["gptReauditText"])
        error_count = edit_distance(old_words, new_words)
        delta = error_count / max(len(old_words), 1)
        disposition = (
            "exact_repeat_supported"
            if error_count == 0
            else "gpt_reaudited_minor_delta_requires_human_confirmation"
            if delta <= 0.10
            else "gpt_reaudited_major_delta_requires_human_confirmation"
        )
        output_rows.append(
            {
                "id": row["id"],
                "referenceWordCount": len(old_words),
                "reauditWordCount": len(new_words),
                "wordEditCount": error_count,
                "referenceDeltaRate": round(delta, 6),
                "disposition": disposition,
                "humanListeningCompleted": False,
            }
        )
    counts = Counter(row["disposition"] for row in output_rows)
    payload = {
        "schemaVersion": "local-asr-gpt-reaudit-summary-v1",
        "status": "gpt_reaudit_completed_human_confirmation_pending",
        "results": str(results_path.relative_to(REPO_ROOT)),
        "resultsSha256": sha256_file(results_path),
        "itemCount": len(output_rows),
        "dispositionCounts": dict(sorted(counts.items())),
        "humanGoldClaimed": False,
        "items": output_rows,
    }
    output_path = (REPO_ROOT / args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    confirmation_items = []
    result_by_id = {row["id"]: row for row in rows}
    for summary in output_rows:
        if summary["disposition"] == "exact_repeat_supported":
            continue
        source = queue_by_id[summary["id"]]
        result = result_by_id[summary["id"]]
        confirmation_items.append(
            {
                "id": summary["id"],
                "sermonId": source["sermonId"],
                "audioPath": source["audioPath"],
                "audioSha256": source["audioSha256"],
                "durationSeconds": source["durationSeconds"],
                "originalModelReviewedReferenceText": result["modelReviewedReferenceText"],
                "gptReauditText": result["gptReauditText"],
                "candidateModelTranscripts": result["modelTranscripts"],
                "referenceDeltaRate": summary["referenceDeltaRate"],
                "disposition": summary["disposition"],
                "humanReferenceText": None,
                "humanAudioClass": None,
                "reviewer": None,
                "reviewStatus": "needs_human_listening_confirmation",
            }
        )
    confirmation_payload = {
        "schemaVersion": "local-asr-human-confirmation-queue-v1",
        "status": "needs_human_listening_confirmation",
        "sourceSummary": str(output_path.relative_to(REPO_ROOT)),
        "sourceSummarySha256": sha256_file(output_path),
        "itemCount": len(confirmation_items),
        "durationMinutes": round(
            sum(item["durationSeconds"] for item in confirmation_items) / 60, 3
        ),
        "items": confirmation_items,
    }
    confirmation_path = (REPO_ROOT / args.confirmation_queue).resolve()
    confirmation_path.parent.mkdir(parents=True, exist_ok=True)
    confirmation_path.write_text(
        json.dumps(confirmation_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(payload["dispositionCounts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
