#!/usr/bin/env python3
"""Sample macOS process-tree memory, swap, memory pressure, and thermal state."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import signal
import subprocess
import time


STOP_REQUESTED = False


def request_stop(_signum: int, _frame: object) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, action="append", required=True, help="Root PID; descendants are included")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--duration-seconds", type=float, required=True)
    args = parser.parse_args()
    if any(pid < 1 for pid in args.pid) or args.interval_seconds <= 0 or args.duration_seconds <= 0:
        parser.error("PID, interval, and duration must be positive")
    return args


def run_text(command: list[str]) -> str:
    return subprocess.run(command, check=False, capture_output=True, text=True).stdout.strip()


def process_snapshot(root_pids: list[int]) -> dict[str, object]:
    rows = []
    for line in run_text(["ps", "-axo", "pid=,ppid=,rss=,command="]).splitlines():
        match = re.match(r"\s*(\d+)\s+(\d+)\s+(\d+)\s+(.*)", line)
        if match:
            rows.append({"pid": int(match.group(1)), "ppid": int(match.group(2)), "rssKiB": int(match.group(3)), "command": match.group(4)})
    selected = set(root_pids)
    changed = True
    while changed:
        changed = False
        for row in rows:
            if row["ppid"] in selected and row["pid"] not in selected:
                selected.add(int(row["pid"]))
                changed = True
    processes = [row for row in rows if row["pid"] in selected]
    return {
        "rootPids": root_pids,
        "observedPids": sorted(selected),
        "rssKiB": sum(int(row["rssKiB"]) for row in processes),
        "processes": processes,
    }


def swap_used_bytes() -> int | None:
    output = run_text(["sysctl", "-n", "vm.swapusage"])
    match = re.search(r"used\s*=\s*([0-9.]+)([KMG])", output)
    if not match:
        return None
    scale = {"K": 1024, "M": 1024**2, "G": 1024**3}[match.group(2)]
    return round(float(match.group(1)) * scale)


def free_memory_percent() -> int | None:
    output = run_text(["memory_pressure", "-Q"])
    match = re.search(r"System-wide memory free percentage:\s*(\d+)%", output)
    return int(match.group(1)) if match else None


def thermal_snapshot() -> dict[str, int]:
    result: dict[str, int] = {}
    for line in run_text(["pmset", "-g", "therm"]).splitlines():
        match = re.match(r"\s*([A-Za-z_]+)\s*=\s*(\d+)", line)
        if match:
            result[match.group(1)] = int(match.group(2))
    return result


def main() -> int:
    args = parse_args()
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with args.output.open("a", encoding="utf-8") as output:
        try:
            while not STOP_REQUESTED:
                elapsed = time.monotonic() - started
                if elapsed > args.duration_seconds:
                    break
                item = {
                    "schemaVersion": "macbook-resource-sample-v1",
                    "sampledAt": datetime.now(timezone.utc).isoformat(),
                    "elapsedSeconds": round(elapsed, 3),
                    "processTree": process_snapshot(args.pid),
                    "swapUsedBytes": swap_used_bytes(),
                    "systemFreeMemoryPercent": free_memory_percent(),
                    "thermal": thermal_snapshot(),
                }
                output.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
                output.flush()
                time.sleep(args.interval_seconds)
        except KeyboardInterrupt:
            pass
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
