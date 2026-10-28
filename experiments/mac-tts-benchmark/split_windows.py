#!/usr/bin/env python3
"""Split a speech table into complete batch windows for two-way Mac TTS.

The formal batch policy seeds a window with ``base seed + original window start``.
To keep every sentence's seed and window membership identical to a single-process
run, windows are assigned round-robin to workers; a shard is the concatenation of
complete windows in original order. No shard renumbers sentences or restarts the
seed at its own local zero.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def plan(rows: list[dict], *, workers: int, batch_size: int, base_seed: int = 42) -> dict:
    if workers < 1:
        raise ValueError("workers must be positive")
    if batch_size not in (1, 2, 4, 8):
        raise ValueError("batch_size must be 1, 2, 4 or 8")
    if not rows:
        raise ValueError("speech table is empty")
    shards = [[] for _ in range(workers)]
    windows = []
    for start in range(0, len(rows), batch_size):
        window = rows[start:start + batch_size]
        seed = base_seed + start
        worker = (start // batch_size) % workers
        for offset, row in enumerate(window):
            shards[worker].append({**row, "_originalIndex": start + offset,
                                   "windowStart": start, "seed": seed})
        windows.append({"windowStart": start, "seed": seed, "worker": worker,
                        "size": len(window), "ids": [row.get("id") for row in window],
                        "complete": len(window) == batch_size})
    manifest = {
        "schemaVersion": "sermon-mac-tts-shards-v1",
        "baseSeed": base_seed, "batchSize": batch_size, "workers": workers,
        "sentenceCount": len(rows), "windows": windows,
        "shards": [{"worker": index, "sentences": len(shard),
                    "seeds": sorted({row["seed"] for row in shard})}
                   for index, shard in enumerate(shards)],
        "seedPolicy": "base seed + original window start; unchanged by sharding",
    }
    return {"shards": shards, "manifest": manifest}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speech", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.speech.read_text(encoding="utf-8").splitlines() if line.strip()]
    result = plan(rows, workers=args.workers, batch_size=args.batch_size, base_seed=args.seed)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for index, shard in enumerate(result["shards"]):
        path = args.out_dir / f"shard-{index}.jsonl"
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in shard) + "\n",
                        encoding="utf-8")
    (args.out_dir / "manifest.json").write_text(
        json.dumps(result["manifest"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result["manifest"][k] for k in ("sentenceCount", "workers", "batchSize", "baseSeed")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
