#!/usr/bin/env python3
"""Summarize round-two Omni matrix outputs without claiming human accuracy."""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def load_results(directory: Path) -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.result.json"))]


def summarize_provider(name: str, directory: Path) -> dict:
    results = load_results(directory)
    conditions: dict[str, list[dict]] = {}
    for result in results:
        condition = result["caseId"].split("--", 1)[1]
        conditions.setdefault(condition, []).append(result)
    condition_summary = {}
    for condition, items in sorted(conditions.items()):
        latencies = [float(item["latencySeconds"]) for item in items]
        condition_summary[condition] = {
            "observed": len(items),
            "validationPass": sum(not item["validationErrors"] for item in items),
            "validationFail": sum(bool(item["validationErrors"]) for item in items),
            "latencyMedianSeconds": round(statistics.median(latencies), 3),
            "latencyMinSeconds": round(min(latencies), 3),
            "latencyMaxSeconds": round(max(latencies), 3),
        }
    baseline = []
    for result in conditions.get("av-transcript", []):
        analysis = result.get("analysis") or {}
        baseline.append({
            "sampleId": result["caseId"].split("--", 1)[0],
            "latencySeconds": result["latencySeconds"],
            "validationErrors": result["validationErrors"],
            "audioStatus": analysis.get("audio_status"),
            "events": [{key: event.get(key) for key in
                        ("start_seconds", "end_seconds", "type", "scripture_ref")}
                       for event in analysis.get("events", [])],
            "pauseCandidates": [{key: pause.get(key) for key in
                                 ("at_seconds", "duration_seconds", "kind")}
                                for pause in analysis.get("pause_candidates", [])],
        })
    return {
        "provider": name, "resultDirectory": str(directory.resolve()),
        "resultCount": len(results), "conditions": condition_summary,
        "baselineCandidates": baseline,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--provider", action="append", required=True,
                        help="NAME=RESULT_DIRECTORY")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    providers = []
    for spec in args.provider:
        name, raw_directory = spec.split("=", 1)
        providers.append(summarize_provider(name, Path(raw_directory)))
    gold_states = []
    root = args.manifest.resolve().parent
    for sample in manifest["samples"]:
        gold = json.loads((root / sample["paths"]["humanGold"]).read_text(encoding="utf-8"))
        gold_states.append(gold.get("reviewState"))
    summary = {
        "schemaVersion": "sermon-omni-round2-summary-v1",
        "reviewState": "machine_results_complete_human_gold_pending",
        "manifest": str(args.manifest.resolve()),
        "sampleCount": manifest["sampleCount"],
        "matrixCaseCount": manifest["caseCount"],
        "humanGoldComplete": sum(state == "complete" for state in gold_states),
        "humanGoldPending": sum(state != "complete" for state in gold_states),
        "providers": providers,
        "limitations": [
            "Validation pass checks schema and harness-fixed modality truth, not semantic accuracy.",
            "Event and pause accuracy remains unscored until operator listening Gold is complete.",
            "Qwen ran a three-sample discriminative subset, not the full twelve-sample matrix.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.out), "providers": len(providers),
                      "humanGoldPending": summary["humanGoldPending"]}))


if __name__ == "__main__":
    main()
