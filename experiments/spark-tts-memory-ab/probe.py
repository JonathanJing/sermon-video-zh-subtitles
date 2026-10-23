#!/usr/bin/env python3
"""Diagnostic Spark TTS memory probe: 8 resident replicas x batch 8 over the 2026-10-03
64-sentence sample, repeated for several rounds so each replica serves as many windows
as a full sermon. Records host MemAvailable and each worker's CUDA allocator counters
per window. Not a formal render: no speech job, receipts, review or release eligibility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import time

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.compute.spark_tts_replica_pool import ReplicaPool
from tongxing_production.compute.spark_tts_window_scheduler import ParallelBatchEngine
from tongxing_production.audio.renderer import SparkQwenSynthesizer, write_pcm16
from tongxing_production.audio import unit_integrity as integrity

GIB = 1024**3


def mem_available():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("MemAvailable unavailable")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True, help="2026-10-03 single-speaker sample inputs.json")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--arm", required=True)
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--replicas", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--release-cuda-cache", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    out = args.out
    out.mkdir(parents=True, exist_ok=False)
    inputs = json.loads(args.inputs.read_text())
    weights = args.checkpoint / "model.safetensors"
    checkpoint_sha = hashlib.sha256(weights.read_bytes()).hexdigest()
    assert checkpoint_sha == inputs["checkpointSha256"], "checkpoint differs from the sample's binding"
    sample = [row for batch in inputs["batches"]["8"] for row in batch]
    assert len(sample) == inputs["sampleUnitCount"] == 64
    requests = []
    for round_index in range(args.rounds):
        for row in sample:
            requests.append({"identity": {"orderedIndex": len(requests), "round": round_index,
                                          "sampleIndex": row["unitIndex"], "textSha256": row["textSha256"]},
                             "text": row["text"], "language": "Chinese", "speaker": inputs["speakerKey"],
                             "instruct": None})
    windows = {start: requests[start:start + args.batch_size] for start in range(0, len(requests), args.batch_size)}
    events = []
    events_path = out / "events.json"

    def telemetry(row):
        events.append(row)
        events_path.write_text(json.dumps(events, indent=1) + "\n")

    import torch
    before = mem_available()
    started = time.monotonic()
    rows, window_rows = [], []
    with ReplicaPool(args.checkpoint, factory=SparkQwenSynthesizer,
                     engine_kwargs={"device": "cuda:0", "dtype": "bfloat16", "attention": "sdpa"},
                     replicas=args.replicas, telemetry=telemetry,
                     release_cuda_cache=args.release_cuda_cache) as pool:
        dispatcher = ParallelBatchEngine(pool, windows, seed=args.seed, frozen_check=lambda: None)
        loaded = time.monotonic() - started
        after_load = mem_available()
        for start, window in windows.items():
            consumed_at = time.monotonic()
            values = dispatcher.batch(window, seed=args.seed + start)
            for offset, value in enumerate(values):
                index = start + offset
                path = out / "wav" / f"unit-{index:04d}.wav"
                path.parent.mkdir(exist_ok=True)
                write_pcm16(path, value["wave"], value["sampleRate"])
                decoded = integrity.probe_full_decode(path)
                rows.append({"index": index, "round": requests[index]["identity"]["round"],
                             "sampleIndex": requests[index]["identity"]["sampleIndex"],
                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), **decoded})
            window_rows.append({"start": start, "parentConsumeSeconds": time.monotonic() - consumed_at,
                                "generationSeconds": dispatcher.last_window_seconds,
                                "memAvailableBytesAfterCommit": mem_available(),
                                "elapsedSeconds": time.monotonic() - started})
        assert not dispatcher.submitted and not dispatcher.pending and pool.outstanding == 0
        minimum = pool.min_available_bytes
    total = time.monotonic() - started
    time.sleep(5)
    after_close = mem_available()
    results = [e for e in events if e.get("kind") == "result"]
    series = [{"index": e["index"], "worker": e["worker"], "timestamp": e["timestamp"],
               "generationSeconds": e["generationSeconds"], "releaseSeconds": e.get("releaseSeconds"),
               "memAvailableBytes": e.get("memAvailableBytes"), "parentRssBytes": e.get("parentRssBytes"),
               "workerRssBytes": (e.get("memory") or {}).get("rssBytes"),
               "cuda": (e.get("memory") or {}).get("cuda")} for e in results]
    summary = {
        "schemaVersion": "spark-tts-memory-probe-v1", "status": "complete_diagnostic", "releaseEligible": False,
        "arm": args.arm, "host": socket.gethostname(), "torchVersion": torch.__version__,
        "cudaAllocConf": os.environ.get("PYTORCH_CUDA_ALLOC_CONF"), "releaseCudaCache": args.release_cuda_cache,
        "replicas": args.replicas, "batchSize": args.batch_size, "rounds": args.rounds,
        "sampleUnits": len(sample), "units": len(rows), "windows": len(windows), "seedBase": args.seed,
        "checkpointSha256": checkpoint_sha, "sampleInputsSha256": hashlib.sha256(args.inputs.read_bytes()).hexdigest(),
        "memAvailableGiB": {"beforeLoad": before / GIB, "afterLoad": after_load / GIB, "minimum": minimum / GIB,
                            "afterClose": after_close / GIB},
        "modelLoadBarrierSeconds": loaded, "totalWallSeconds": total,
        "generationSecondsSum": sum(w["generationSeconds"] for w in window_rows),
        "windows_": window_rows, "series": series, "rows": rows,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("rows", "series", "windows_")}), flush=True)


if __name__ == "__main__":
    main()
