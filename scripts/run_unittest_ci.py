"""Run the root unittest suite with per-module timing and optional CI sharding.

Shards split individual test cases, not whole modules, so one slow module can
spread across runners. Each shard keeps discovery order for the cases it runs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import unittest
from collections import Counter, defaultdict
import math
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
    return module_name_from_id(case.id())


def module_name_from_id(case_id: str) -> str:
    # Fixtures may import a test class through the tests package.
    return case_id.removeprefix("tests.").split(".", 1)[0]


def timing_weights(test_counts: dict[str, int], previous: dict) -> dict[str, float]:
    """Scale known timings by case count; estimate new modules from measured cost."""
    measured = previous["modules"]
    for data in measured.values():
        if not math.isfinite(float(data["seconds"])) or float(data["seconds"]) < 0 or int(data["tests"]) < 1:
            raise ValueError("Module timings must have finite nonnegative seconds and positive test counts")
    total_cases = sum(int(data["tests"]) for data in measured.values())
    if not total_cases:
        raise ValueError("No measured module timings")
    per_case = max(0.001, sum(float(data["seconds"]) for data in measured.values()) / total_cases)
    return {
        name: max(0.001, float(measured[name]["seconds"]) / int(measured[name]["tests"])) * count
        if name in measured else per_case * count
        for name, count in test_counts.items()
    }


# Cases at least this slow are reported by id, so one module's slow and fast
# cases can be spread separately.
SLOW_CASE_SECONDS = 5.0


def case_costs(
    case_ids: list[str], module_weights: dict[str, float], test_counts: dict[str, int],
    slow_cases: dict[str, float] | None = None,
) -> list[float]:
    """Estimate each discovered case from its slow-case timing or its module's remainder."""
    slow = {}
    for name, seconds in (slow_cases or {}).items():
        if not math.isfinite(float(seconds)) or float(seconds) < 0:
            raise ValueError("Slow case timings must be finite and nonnegative")
        slow[name.removeprefix("tests.")] = float(seconds)
    keys = [case_id.removeprefix("tests.") for case_id in case_ids]
    known, known_count = defaultdict(float), Counter()
    for key in keys:
        if key in slow:
            known[module_name_from_id(key)] += slow[key]
            known_count[module_name_from_id(key)] += 1
    costs = []
    for key in keys:
        module = module_name_from_id(key)
        if key in slow:
            costs.append(max(0.001, slow[key]))
            continue
        total = module_weights.get(module, float(test_counts[module]))
        remaining = test_counts[module] - known_count[module]
        costs.append(max(0.001, (total - known[module]) / remaining))
    return costs


def case_shard_assignments(case_ids: list[str], costs: list[float], count: int) -> list[int]:
    """Return a shard per discovered case, placing slow cases first.

    A test class imported by another module is discovered twice under one id;
    both copies still run, so assignment follows positions rather than ids.
    """
    totals = [0.0] * count
    assignments = [0] * len(case_ids)
    for position in sorted(range(len(case_ids)), key=lambda index: (-costs[index], case_ids[index], index)):
        shard = min(range(count), key=lambda index: (totals[index], index))
        assignments[position] = shard
        totals[shard] += costs[position]
    return assignments


class TimedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.module_seconds = defaultdict(float)
        self.module_tests = defaultdict(int)
        self.case_seconds = defaultdict(float)
        self.case_runs = Counter()
        self._started = {}

    def startTest(self, test):
        self._started[id(test)] = time.monotonic()
        super().startTest(test)

    def stopTest(self, test):
        elapsed = time.monotonic() - self._started.pop(id(test))
        self.module_seconds[module_name(test)] += elapsed
        self.case_seconds[test.id().removeprefix("tests.")] += elapsed
        self.case_runs[test.id().removeprefix("tests.")] += 1
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
    test_counts = Counter(module_name(case) for case in discovered)
    modules = sorted(test_counts)
    if not discovered:
        raise SystemExit("No root tests discovered")

    if args.weights:
        previous = json.loads(args.weights.read_text(encoding="utf-8"))
        weights = timing_weights(test_counts, previous)
        slow_cases = previous.get("slowCases", {})
        missing = sorted(set(modules) - previous["modules"].keys())
        if missing:
            print(f"Estimating {len(missing)} unprofiled modules from measured per-case cost", flush=True)
    else:
        weights, slow_cases = {}, {}

    if args.shard_count is not None:
        case_ids = [case.id() for case in discovered]
        assigned = case_shard_assignments(
            case_ids, case_costs(case_ids, weights, test_counts, slow_cases), args.shard_count
        )
        selected = [case for case, shard in zip(discovered, assigned) if shard == args.shard_index]
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
        # Seconds per run: a case discovered twice is reported once, at its average.
        "slowCases": {
            name: round(seconds / result.case_runs[name], 3)
            for name, seconds in sorted(result.case_seconds.items())
            if seconds / result.case_runs[name] >= SLOW_CASE_SECONDS
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for name, data in sorted(report["modules"].items(), key=lambda item: -item[1]["seconds"])[:10]:
        print(f"{data['seconds']:7.2f}s  {data['tests']:4d}  {name}", flush=True)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
