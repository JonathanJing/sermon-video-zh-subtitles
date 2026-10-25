#!/usr/bin/env python3
"""Redacted comparison of the memory A/B arms: numbers and hashes only, no sermon text."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics

GIB = 1024**3


def arm_report(summary):
    series = summary["series"]
    by_worker = {}
    for row in series:
        by_worker.setdefault(row["worker"], []).append(row)
    workers = {}
    for worker, rows in sorted(by_worker.items()):
        cuda = [r["cuda"] for r in rows if r.get("cuda")]
        workers[worker] = {
            "windows": len(rows),
            "reservedGiB": [round(c["reservedBytes"] / GIB, 2) for c in cuda],
            "allocatedGiB": [round(c["allocatedBytes"] / GIB, 2) for c in cuda],
            "maxReservedGiB": round(max(c["maxReservedBytes"] for c in cuda) / GIB, 2) if cuda else None,
            "rssGiB": [round(r["workerRssBytes"] / GIB, 2) for r in rows if r.get("workerRssBytes")],
        }
    mem = [r["memAvailableBytes"] / GIB for r in series if r.get("memAvailableBytes")]
    releases = [r["releaseSeconds"] for r in series if r.get("releaseSeconds") is not None]
    gens = [r["generationSeconds"] for r in series]
    return {
        "arm": summary["arm"], "status": summary.get("status", "complete_diagnostic"), "cudaAllocConf": summary.get("cudaAllocConf"), "releaseCudaCache": summary["releaseCudaCache"],
        "replicas": summary["replicas"], "batchSize": summary["batchSize"], "rounds": summary["rounds"],
        "units": summary["units"], "windows": summary["windows"], "torchVersion": summary.get("torchVersion"),
        "modelLoadBarrierSeconds": round(summary["modelLoadBarrierSeconds"], 1),
        "totalWallSeconds": round(summary["totalWallSeconds"], 1),
        "windowGenerationSeconds": {"median": round(statistics.median(gens), 1), "max": round(max(gens), 1), "sum": round(sum(gens), 1)},
        "releaseSeconds": {"n": len(releases), "median": round(statistics.median(releases), 3) if releases else None,
                           "max": round(max(releases), 3) if releases else None},
        "memAvailableGiB": {k: round(v, 2) for k, v in summary["memAvailableGiB"].items()},
        "memAvailableGiBPerResult": [round(m, 1) for m in mem],
        "memDrainGiBFirstToLastResult": round(mem[0] - mem[-1], 2) if len(mem) > 1 else None,
        "workers": workers,
    }


def tripped_summary(arm_dir):
    """A run that stopped at the reserve wrote only events.json; rebuild the fields the report needs."""
    events = json.loads((arm_dir / "spark-output" / "events.json").read_text())
    ready = next(e for e in events if e["kind"] == "pool_ready")
    results = [e for e in events if e["kind"] == "result"]
    trip = [e for e in events if e["kind"] == "reserve_failure"]
    config = json.loads((arm_dir / "runner-config.json").read_text())["command"]
    return {
        "arm": arm_dir.name, "cudaAllocConf": ready.get("cudaAllocConf"), "releaseCudaCache": ready.get("releaseCudaCache"),
        "replicas": ready["replicas"], "batchSize": 8, "rounds": int(config[config.index("--rounds") + 1]),
        "units": len(results) * 8, "windows": len(results), "status": "reserve_tripped" if trip else "incomplete",
        "modelLoadBarrierSeconds": max(e["loadSeconds"] for e in events if e["kind"] == "ready"),
        "totalWallSeconds": events[-1]["timestamp"] - events[0]["timestamp"],
        "memAvailableGiB": {"beforeLoad": float("nan"), "afterLoad": ready["memAvailableBytes"] / GIB,
                            "minimum": min(e["memAvailableBytes"] for e in events if e.get("memAvailableBytes")) / GIB,
                            "afterClose": float("nan")},
        "series": [{"index": e["index"], "worker": e["worker"], "timestamp": e["timestamp"],
                    "generationSeconds": e["generationSeconds"], "releaseSeconds": e.get("releaseSeconds"),
                    "memAvailableBytes": e.get("memAvailableBytes"), "workerRssBytes": (e.get("memory") or {}).get("rssBytes"),
                    "cuda": (e.get("memory") or {}).get("cuda")} for e in results],
        "rows": [],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True, help="Local run directory holding <arm>/spark-output/summary.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    arms, hashes = {}, {}
    for arm_dir in sorted(p for p in args.runs.iterdir() if (p / "spark-output" / "events.json").is_file()):
        summary_path = arm_dir / "spark-output" / "summary.json"
        if summary_path.is_file():
            summary = json.loads(summary_path.read_text())
            hashes[summary["arm"]] = {row["index"]: row["sha256"] for row in summary["rows"]}
        else:
            summary = tripped_summary(arm_dir)
        arms[summary["arm"]] = arm_report(summary)
    baseline = hashes.get("baseline", {})
    identical = {arm: (sum(1 for i, h in rows.items() if baseline.get(i) == h), len(rows))
                 for arm, rows in hashes.items() if arm != "baseline"}
    report = {"schemaVersion": "spark-tts-memory-ab-comparison-v1", "scope": "diagnostic_only", "releaseEligible": False,
              "sample": "2026-10-03 single-speaker 64-sentence sample (sunday-production-8x8), repeated rounds",
              "arms": arms, "wavSha256IdenticalToBaseline": {arm: {"identical": n, "total": t} for arm, (n, t) in identical.items()}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    for arm, row in arms.items():
        m = row["memAvailableGiB"]
        print(f"{arm:11s} load={row['modelLoadBarrierSeconds']:5.1f}s wall={row['totalWallSeconds']:6.1f}s "
              f"gen median={row['windowGenerationSeconds']['median']:5.1f}s mem before/afterLoad/min/afterClose="
              f"{m['beforeLoad']:.1f}/{m['afterLoad']:.1f}/{m['minimum']:.1f}/{m['afterClose']:.1f} GiB "
              f"drain={row['memDrainGiBFirstToLastResult']} GiB release={row['releaseSeconds']['median']}")
    print("wav identical to baseline:", report["wavSha256IdenticalToBaseline"])


if __name__ == "__main__":
    main()
