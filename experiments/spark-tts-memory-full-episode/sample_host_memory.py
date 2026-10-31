#!/usr/bin/env python3
"""Sample Spark host memory once per interval into JSONL until stopped (SIGTERM/SIGINT).

Runs on the Spark host next to a lanes run, so the curve also covers model loads, CPU
stages and the gaps between stages that the replica pool's own events do not see.
Each row: wall time, MemAvailable, MemTotal, SwapTotal-SwapFree, and GPU utilisation when
nvidia-smi answers (GB10 reports no memory figure, so none is read). Metadata only.
"""
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import time
from pathlib import Path

FIELDS = {"MemAvailable": "memAvailableBytes", "MemTotal": "memTotalBytes",
          "SwapTotal": "swapTotalBytes", "SwapFree": "swapFreeBytes"}


def read_meminfo(path: Path = Path("/proc/meminfo")) -> dict:
    row = {}
    for line in path.read_text().splitlines():
        key, _, rest = line.partition(":")
        if key in FIELDS:
            row[FIELDS[key]] = int(rest.split()[0]) * 1024
    return row


def gpu_util() -> float | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5)
        return float(out.stdout.split()[0]) if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="JSONL file to append samples to")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--no-gpu", action="store_true", help="Skip nvidia-smi")
    args = parser.parse_args(argv)
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    signal.signal(signal.SIGINT, lambda *_: stop.append(1))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as sink:
        while not stop:
            row = {"timestamp": time.time(), **read_meminfo()}
            if not args.no_gpu:
                row["gpuUtilPercent"] = gpu_util()
            sink.write(json.dumps(row) + "\n")
            sink.flush()
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
