#!/usr/bin/env python3
"""Two-speaker, multi-replica TTS pool for one locale (sentence-first line).

The formal 8x8 path is single-speaker; the sentence-first line can share one pool across
both speakers: ``--voice key=checkpoint`` for each speaker, ``--replicas N`` model
processes (split proportionally; 4+4 for N=8 and a balanced two-speaker locale) and
``--batch-size 8``. Each worker is a ``tts_sentences.py`` process on its own shard; the
shared ``tts-log.jsonl``/``tts-batches.jsonl`` stay append-only.

Runs inside the Spark container; ``spark_run.sh --steps tts-pool`` mounts each checkpoint
at ``/checkpoint-<key>``. The GPU memory check is the caller's responsibility; the formal
8x8 measurement (8 replicas, 64 sentences in 56.81 s, 38.43 GiB min available) is the
reference.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def plan_workers(rows: list[dict], voices: dict[str, str], replicas: int, batch_size: int = 8) -> dict:
    keys = list(voices)
    by = {k: [r for r in rows if r.get("speaker") == k] for k in keys}
    total = sum(len(v) for v in by.values())
    reps = max(1, int(replicas))
    if not total:
        return {"workers": [], "replicas": 0, "bySpeaker": {k: 0 for k in keys}}
    alloc = {k: (max(1, round(reps * len(by[k]) / total)) if by[k] else 0) for k in keys}
    while sum(alloc.values()) > reps:
        candidates = [k for k in alloc if alloc[k] > 1]
        k = max(candidates, key=lambda x: alloc[x])
        alloc[k] -= 1
    while sum(alloc.values()) < reps:
        candidates = [k for k in keys if by[k]]
        k = max(candidates, key=lambda x: len(by[k]) / alloc[x])
        alloc[k] += 1
    workers = []
    for k in keys:
        v, n = by[k], alloc[k]
        if not v or n < 1:
            continue
        size = max(1, (len(v) + n - 1) // n)
        for i in range(n):
            chunk = v[i * size:(i + 1) * size]
            if chunk:
                workers.append({"speaker": k, "checkpoint": voices[k], "shard": i,
                                "ids": [r["id"] for r in chunk]})
    return {"workers": workers, "replicas": len(workers), "bySpeaker": {k: len(v) for k, v in by.items()},
            "batchSize": batch_size}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--speech", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--voice", action="append", required=True, metavar="SPEAKER_KEY=CHECKPOINT")
    p.add_argument("--replicas", type=int, default=8)
    p.add_argument("--batch-size", type=int, default=8)
    a = p.parse_args(argv)
    rows = [json.loads(line) for line in a.speech.read_text(encoding="utf-8").splitlines() if line.strip()]
    voices = {}
    for item in a.voice:
        key, sep, path = item.partition("=")
        if not sep or not key or not path:
            raise SystemExit("--voice must be SPEAKER_KEY=CHECKPOINT")
        voices[key] = path
    plan = plan_workers(rows, voices, a.replicas, a.batch_size)
    print(json.dumps({k: v for k, v in plan.items() if k != "workers"}, ensure_ascii=False), flush=True)
    if not plan["workers"]:
        return 0
    a.out.mkdir(parents=True, exist_ok=True)
    shard_dir = a.out / "pool-shards"
    shard_dir.mkdir(exist_ok=True)
    tts = Path(__file__).resolve().parent / "tts_sentences.py"
    procs = []
    for i, worker in enumerate(plan["workers"]):
        ids = set(worker["ids"])
        shard = shard_dir / f"worker-{i}.jsonl"
        shard.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows if r["id"] in ids) + "\n",
                         encoding="utf-8")
        log = (a.out / f"pool-worker-{i}.log").open("w", encoding="utf-8")
        cmd = [sys.executable, str(tts), "--speech", str(shard), "--checkpoint", worker["checkpoint"],
               "--out", str(a.out), "--batch-size", str(a.batch_size), "--only-speaker", worker["speaker"]]
        procs.append((i, subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT), log))
    failed = []
    for i, proc, log in procs:
        rc = proc.wait()
        log.close()
        if rc:
            failed.append(i)
    print(json.dumps({"workers": len(plan["workers"]), "failed": failed}, ensure_ascii=False), flush=True)
    if failed:
        raise SystemExit(f"pool workers failed: {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
