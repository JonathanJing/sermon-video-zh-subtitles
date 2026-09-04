#!/usr/bin/env python3
"""Promote exact-chunk GPT-Transcribe text into a model-reviewed ASR reference."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHUNK_ID_RE = re.compile(r"timeline_chunk_(\d+)\.m4a$")

CRITICAL_TERMS = [
    "Abraham",
    "Bible",
    "Christ",
    "Christian",
    "Church",
    "God",
    "Holy Spirit",
    "Jesus",
    "Mariners",
    "Messiah",
    "Nehemiah",
    "Revelation",
    "Rooted",
    "Scripture",
    "baptism",
    "communion",
    "faith",
    "gospel",
    "grace",
    "resurrection",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.casefold())


def contains_term(text: str, term: str) -> bool:
    words = normalize_words(text)
    term_words = normalize_words(term)
    return bool(term_words) and any(
        words[index : index + len(term_words)] == term_words
        for index in range(len(words) - len(term_words) + 1)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("data/benchmarks/live-sermon-translation-v1/local-asr-benchmark-v1.json"),
    )
    parser.add_argument(
        "--queue",
        type=Path,
        default=Path(
            "data/benchmarks/live-sermon-translation-v1/local-asr-gold-annotation-queue-v1.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "data/benchmarks/live-sermon-translation-v1/local-asr-model-reviewed-reference-v1.json"
        ),
    )
    args = parser.parse_args()
    config_path = (REPO_ROOT / args.config).resolve()
    queue_path = (REPO_ROOT / args.queue).resolve()
    output_path = (REPO_ROOT / args.output).resolve()
    config = json.loads(config_path.read_text())
    queue = json.loads(queue_path.read_text())
    sources = {
        source["sourceGroupId"]: source for source in config["goldDataset"]["candidateSources"]
    }

    timeline_cache: dict[str, tuple[dict[int, dict], dict]] = {}
    output_items: list[dict] = []
    for item in queue["items"]:
        source = sources[item["sourceGroupId"]]
        if source["sourceGroupId"] not in timeline_cache:
            timeline_path = (REPO_ROOT / source["timelineChunksPath"]).resolve()
            report_path = (REPO_ROOT / source["timelineReportPath"]).resolve()
            report = json.loads(report_path.read_text())
            if report.get("transcriptionModel") != "gpt-transcribe":
                raise SystemExit(f"Unexpected timeline transcription model: {report_path}")
            timeline = json.loads(timeline_path.read_text())
            timeline_cache[source["sourceGroupId"]] = (
                {int(row["id"]): row for row in timeline},
                {
                    "sourceGroupId": source["sourceGroupId"],
                    "timelineChunksPath": source["timelineChunksPath"],
                    "timelineChunksSha256": sha256_file(timeline_path),
                    "timelineReportPath": source["timelineReportPath"],
                    "timelineReportSha256": sha256_file(report_path),
                    "transcriptionModel": "gpt-transcribe",
                },
            )
        timeline_by_id, _ = timeline_cache[source["sourceGroupId"]]
        match = CHUNK_ID_RE.search(item["audioPath"])
        if not match:
            raise SystemExit(f"Cannot parse timeline chunk id: {item['audioPath']}")
        chunk_id = int(match.group(1))
        reference = timeline_by_id[chunk_id]
        if abs(float(reference["duration"]) - float(item["durationSeconds"])) > 0.05:
            raise SystemExit(f"Reference/audio duration mismatch: {item['id']}")
        reference_text = reference.get("text", "").strip()
        speech_expected = bool(re.findall(r"[A-Za-z0-9]", reference_text))
        terms = [term for term in CRITICAL_TERMS if contains_term(reference_text, term)]
        output_items.append(
            {
                "id": item["id"],
                "sermonId": item["sourceGroupId"],
                "audioPath": item["audioPath"],
                "audioSha256": item["audioSha256"],
                "durationSeconds": item["durationSeconds"],
                "referenceStatus": "model_reviewed_reference",
                "referenceText": reference_text,
                "speechExpected": speech_expected,
                "criticalTerms": terms,
                "referenceProvenance": {
                    "model": "gpt-transcribe",
                    "timelineChunkId": chunk_id,
                    "timelineStartSeconds": reference["start"],
                    "timelineEndSeconds": reference["end"],
                    "humanGoldClaimed": False,
                },
            }
        )

    source_receipts = [receipt for _, receipt in timeline_cache.values()]
    payload = {
        "schemaVersion": "local-asr-audio-manifest-v1",
        "datasetId": "BENCH-LIVE-ST-ASR-MODEL-REVIEWED-REFERENCE-V1",
        "purpose": "quality_scoring_against_exact_chunk_gpt_transcribe_reference",
        "referencePolicy": "model_reviewed_reference_not_human_gold",
        "createdAt": config["goldDataset"]["queueCreatedAt"],
        "translationUntouchedTestIncluded": False,
        "sourceReceipts": source_receipts,
        "items": output_items,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "datasetId": payload["datasetId"],
                "itemCount": len(output_items),
                "speechItemCount": sum(item["speechExpected"] for item in output_items),
                "criticalTermAnnotationCount": sum(len(item["criticalTerms"]) for item in output_items),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
