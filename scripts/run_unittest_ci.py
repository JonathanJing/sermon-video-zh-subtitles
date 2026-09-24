"""Run the root unittest suite with per-module timing and optional CI sharding."""

from __future__ import annotations

import argparse
import json
import sys
import time
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def cases_in(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases_in(item)
        else:
            yield item


def module_name(case: unittest.TestCase) -> str:
    # unittest discover -s tests imports root test files by their stem.
    return case.id().split(".", 1)[0]


def shard_assignments(modules: list[str], weights: dict[str, float], count: int) -> dict[str, int]:
    """Place slow modules first so every shard gets a similar estimated runtime."""
    totals = [0.0] * count
    assignments = {}
    for module in sorted(modules, key=lambda name: (-weights.get(name, 1.0), name)):
        shard = min(range(count), key=lambda index: (totals[index], index))
        assignments[module] = shard
        totals[shard] += weights.get(module, 1.0)
    return assignments


class TimedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.module_seconds = defaultdict(float)
        self.module_tests = defaultdict(int)
        self._started = {}

    def startTest(self, test):
        self._started[id(test)] = time.monotonic()
        super().startTest(test)

    def stopTest(self, test):
        self.module_seconds[module_name(test)] += time.monotonic() - self._started.pop(id(test))
        self.module_tests[module_name(test)] += 1
        super().stopTest(test)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="Write module timings as JSON")
    parser.add_argument("--weights", type=Path, help="Prior module timing report for sharding")
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--shard-count", type=int)
    args = parser.parse_args()
    if (args.shard_index is None) != (args.shard_count is None):
        parser.error("--shard-index and --shard-count must be supplied together")
    if args.shard_count is not None and (
        args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count
    ):
        parser.error("shard index must be between 0 and shard count - 1")

    loader = unittest.TestLoader()
    discovered = list(cases_in(loader.discover(str(ROOT / "tests"), pattern="test_*.py")))
    modules = sorted({module_name(case) for case in discovered})
    if not discovered:
        raise SystemExit("No root tests discovered")

    if args.weights:
        previous = json.loads(args.weights.read_text(encoding="utf-8"))
        weights = {
            name: max(0.001, float(data["seconds"]))
            for name, data in previous["modules"].items()
        }
    else:
        weights = {}

    if args.shard_count is not None:
        assigned = shard_assignments(modules, weights, args.shard_count)
        selected = [case for case in discovered if assigned[module_name(case)] == args.shard_index]
        if not selected:
            raise SystemExit(f"Shard {args.shard_index} has no tests")
        print(
            f"Shard {args.shard_index + 1}/{args.shard_count}: "
            f"{len(selected)} tests from {len({module_name(case) for case in selected})} modules",
            flush=True,
        )
    else:
        selected = discovered
        print(f"Full root suite: {len(selected)} tests from {len(modules)} modules", flush=True)

    started = time.monotonic()
    result = unittest.TextTestRunner(resultclass=TimedResult).run(unittest.TestSuite(selected))
    report = {
        "schemaVersion": 1,
        "shardIndex": args.shard_index,
        "shardCount": args.shard_count,
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "testsRun": result.testsRun,
        "successful": result.wasSuccessful(),
        "modules": {
            name: {
                "seconds": round(result.module_seconds[name], 3),
                "tests": result.module_tests[name],
            }
            for name in sorted(result.module_seconds)
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for name, data in sorted(report["modules"].items(), key=lambda item: -item[1]["seconds"])[:10]:
        print(f"{data['seconds']:7.2f}s  {data['tests']:4d}  {name}", flush=True)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
