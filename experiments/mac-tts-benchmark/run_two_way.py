#!/usr/bin/env python3
"""Run two 1-replica x batch-8 TTS workers on this Mac, with shared original seeds.

Each worker gets complete batch windows, round-robin by original window order, so a
sentence keeps exactly the seed it would have in a single-process run: base 42 plus
its original window start. This is a benchmark/production-aid path, not the formal
renderer: it produces WAVs only and leaves packaging and human review to their own
gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from split_windows import plan


def available_gib() -> float:
    output = subprocess.check_output(["vm_stat"], text=True)
    page = int(re.search(r"page size of (\d+) bytes", output).group(1))
    pages = {key: int(value) for key, value in re.findall(r"^([^:\n]+):\s+(\d+)\.", output, re.M)}
    total = sum(pages.get(key, 0) for key in ("Pages free", "Pages inactive", "Pages speculative"))
    return total * page / 2**30


def file_sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speech", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-available-gib", type=float, default=24.0,
                        help="Refuse to start when free+inactive+speculative is below this")
    parser.add_argument("--expected-checkpoint-sha256", help="Verify model.safetensors before loading")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.speech.read_text(encoding="utf-8").splitlines() if line.strip()]
    planned = plan(rows, workers=2, batch_size=args.batch_size, base_seed=args.seed)
    manifest = planned["manifest"]
    args.out.mkdir(parents=True, exist_ok=True)
    occupied = [args.out / f"worker-{index}" for index in range(2)] + [args.out / "two-way-summary.json"]
    if not args.dry_run and any(path.exists() for path in occupied):
        raise SystemExit(f"{args.out} already holds worker output; choose a new run directory")
    shards_dir = args.out / "shards"
    shards_dir.mkdir(exist_ok=True)
    shard_paths = []
    for index, shard in enumerate(planned["shards"]):
        path = shards_dir / f"shard-{index}.jsonl"
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in shard) + "\n",
                        encoding="utf-8")
        shard_paths.append(path)
    (shards_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    weights = args.checkpoint / "model.safetensors"
    if not weights.is_file():
        raise SystemExit(f"checkpoint has no model.safetensors: {args.checkpoint}")
    if args.expected_checkpoint_sha256:
        actual = file_sha256(weights)
        if actual != args.expected_checkpoint_sha256:
            raise SystemExit(f"checkpoint sha256 differs: {actual}")
    memory = available_gib()
    if memory < args.min_available_gib and not args.dry_run:
        raise SystemExit(f"only {memory:.1f} GiB free+inactive+speculative; need {args.min_available_gib}")
    print(json.dumps({"availableGiB": round(memory, 1), "workers": 2, "batchSize": args.batch_size,
                      "sentences": len(rows), "windowSeeds": len({w["seed"] for w in manifest["windows"]})}),
          flush=True)

    commands = []
    for index, path in enumerate(shard_paths):
        commands.append([sys.executable, str(Path(__file__).with_name("run_mac_tts.py")),
                         "--speech", str(path), "--checkpoint", str(args.checkpoint),
                         "--out", str(args.out / f"worker-{index}"),
                         "--batch-size", str(args.batch_size), "--seed", str(args.seed)])
    for command in commands:
        print("WORKER", " ".join(command), flush=True)
    if args.dry_run:
        return 0

    started = time.monotonic()
    processes = [subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                 for command in commands]
    codes = [process.wait() for process in processes]
    wall = round(time.monotonic() - started, 3)
    if any(codes):
        raise SystemExit(f"worker exit codes: {codes}")

    workers = []
    for index in range(2):
        summary = json.loads((args.out / f"worker-{index}" / "summary.json").read_text())
        expected = manifest["shards"][index]["seeds"]
        if sorted(set(summary["seeds"])) != expected:
            raise SystemExit(f"worker {index} seeds differ from the manifest")
        units = len(list((args.out / f"worker-{index}" / "units").glob("*.wav")))
        if units != manifest["shards"][index]["sentences"]:
            raise SystemExit(f"worker {index} wrote {units} units, expected {manifest['shards'][index]['sentences']}")
        workers.append({"worker": index, "sentences": summary["sentenceCount"],
                        "audioSeconds": summary["audioSeconds"], "synthesisWallSeconds": summary["synthesisWallSeconds"],
                        "realTimeFactor": summary["realTimeFactor"], "seeds": expected,
                        "seedsSha256": hashlib.sha256(json.dumps(expected).encode()).hexdigest()})
    total_audio = sum(row["audioSeconds"] for row in workers)
    result = {"schemaVersion": "sermon-mac-tts-two-way-v1", "workers": workers,
              "sentenceCount": len(rows), "audioSeconds": round(total_audio, 3),
              "wallSeconds": wall, "aggregateRealTimeFactor": round(wall / total_audio, 4),
              "seedPolicy": manifest["seedPolicy"], "manifest": str(shards_dir / "manifest.json"),
              "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    (args.out / "two-way-summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("sentenceCount", "audioSeconds", "wallSeconds",
                                             "aggregateRealTimeFactor")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
