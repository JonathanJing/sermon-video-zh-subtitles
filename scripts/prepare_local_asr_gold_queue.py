#!/usr/bin/env python3
"""Freeze a deterministic, non-test ASR Gold annotation queue."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def duration_seconds(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def evenly_spaced(items: list[Path], count: int) -> list[Path]:
    if count <= 0 or count > len(items):
        raise ValueError(f"Cannot select {count} from {len(items)} items")
    if count == 1:
        return [items[len(items) // 2]]
    indices = [round(index * (len(items) - 1) / (count - 1)) for index in range(count)]
    if len(set(indices)) != count:
        raise ValueError("Even selection produced duplicate indices")
    return [items[index] for index in indices]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("data/benchmarks/live-sermon-translation-v1/local-asr-benchmark-v1.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "data/benchmarks/live-sermon-translation-v1/local-asr-gold-annotation-queue-v1.json"
        ),
    )
    args = parser.parse_args()
    config_path = (REPO_ROOT / args.config).resolve()
    output_path = (REPO_ROOT / args.output).resolve()
    config = json.loads(config_path.read_text())
    sources = config["goldDataset"]["candidateSources"]

    queue: list[dict] = []
    source_receipts: list[dict] = []
    for source in sources:
        approval_path = (REPO_ROOT / source["operatorApprovalPath"]).resolve()
        approval = json.loads(approval_path.read_text())
        if approval.get("status") != "approved" or not approval.get("humanApproval"):
            raise SystemExit(f"Source lacks explicit operator approval: {source['sourceGroupId']}")
        chunks = sorted((REPO_ROOT / source["chunkDirectory"]).glob("timeline_chunk_*.m4a"))
        selected = evenly_spaced(chunks, int(source["selectedClipCount"]))
        source_receipts.append(
            {
                "sourceGroupId": source["sourceGroupId"],
                "operatorApprovalPath": source["operatorApprovalPath"],
                "operatorApprovalSha256": sha256_file(approval_path),
                "availableClipCount": len(chunks),
                "selectedClipCount": len(selected),
                "selectionPolicy": "evenly_spaced_over_ordered_30_second_chunks",
            }
        )
        for sequence, audio_path in enumerate(selected, start=1):
            relative_audio = audio_path.relative_to(REPO_ROOT)
            queue.append(
                {
                    "id": f"{source['sourceGroupId']}_gold_{sequence:03d}",
                    "sourceGroupId": source["sourceGroupId"],
                    "audioPath": str(relative_audio),
                    "audioSha256": sha256_file(audio_path),
                    "durationSeconds": round(duration_seconds(audio_path), 3),
                    "referenceStatus": "needs_human_gold",
                    "humanReferenceText": None,
                    "speechExpected": None,
                    "criticalTerms": [],
                    "riskLabels": [],
                    "reviewedBy": None,
                    "reviewedAt": None,
                }
            )

    payload = {
        "schemaVersion": "local-asr-gold-annotation-queue-v1",
        "datasetId": "BENCH-LIVE-ST-ASR-DEV-GOLD-V1",
        "status": "needs_human_annotation",
        "createdAt": config["goldDataset"]["queueCreatedAt"],
        "selectionUse": "asr_model_vad_window_and_prompt_selection",
        "translationUntouchedTestIncluded": False,
        "modelGeneratedTextIsGold": False,
        "sourceReceipts": source_receipts,
        "itemCount": len(queue),
        "totalDurationMinutes": round(sum(item["durationSeconds"] for item in queue) / 60, 3),
        "items": queue,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: payload[key] for key in ["datasetId", "status", "itemCount", "totalDurationMinutes"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
