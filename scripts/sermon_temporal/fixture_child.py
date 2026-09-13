"""Synthetic TERM-resistant child for actual nested process-group cancellation QA."""
import argparse
import os
from pathlib import Path
import signal
import sys
import time

from scripts.sermon_execution_harness import atomic_json, bounded_process
from .fixtures import fixture_root
from .local_io import process_identity, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--depth", type=int, default=1)
    args = parser.parse_args()
    root = fixture_root(args.root)
    config = read_json(root / "config.json")
    if (config.get("schemaVersion") != "sermon-temporal-fixture-v1" or config.get("fixtureOnly") is not True
            or config.get("nestedCancellationFixture") is not True or not 0 < args.duration <= 120
            or not 1 <= args.depth <= 3):
        raise ValueError("Nested cancellation child is restricted to explicit synthetic fixtures")
    if args.depth == 1:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    atomic_json(root / f"nested-child-{args.depth}.json", {"fixtureOnly": True, "pid": os.getpid(),
        "process_identity": process_identity(os.getpid()), "ignoresSigterm": args.depth == 1, "status": "running"})
    if args.depth == 1:
        time.sleep(args.duration)
    else:
        bounded_process([sys.executable, "-m", "scripts.sermon_temporal.fixture_child", "--root", str(root),
            "--duration", str(args.duration), "--depth", str(args.depth - 1)], timeout=args.duration + 5 * args.depth,
            check=True)


if __name__ == "__main__":
    main()
