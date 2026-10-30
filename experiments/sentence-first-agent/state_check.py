#!/usr/bin/env python3
"""Recompute DeepSeek stage state from events.jsonl + done.jsonl and check it.

The live state file is a projection of the event stream. This tool rebuilds that
projection and reports counters that disagree, so a double-counted resume or a
lost window shows up as a mismatch instead of being read as progress.

  python3 $EXP/state_check.py --run $RUN/coherence-<tag> --label translate
  python3 $EXP/state_check.py --run $RUN --all --source-run $RUN --record
  python3 $EXP/state_check.py --run $RUN --label translate --write     # repair the file
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coherence_core as C  # noqa: E402


def state_path(run: Path, label: str) -> Path:
    for name in (f"state-{label}.json", "state.json"):
        path = run / name
        if path.is_file():
            return path
    return run / f"state-{label}.json"


def labels_in(run: Path) -> list[str]:
    return sorted({row.get("label") for row in C.read_events(run) if row.get("label")})


def check(run: Path, label: str, write: bool, ignore_status: bool) -> dict:
    rebuilt = C.rebuild_state(run, label)
    if not rebuilt:
        return {"label": label, "ok": False, "error": "no events"}
    path = state_path(run, label)
    live = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    mismatches = C.state_mismatches(live, rebuilt, ignore_status=ignore_status)
    repaired = 0
    if write:
        repaired = len(mismatches)
        merged = {**live, **{key: rebuilt[key] for key in rebuilt}}
        merged["summary"] = live.get("summary", {})
        merged["rebuiltAt"] = rebuilt.get("lastEvent")
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
        mismatches = []
    return {"label": label, "path": str(path), "ok": not mismatches, "mismatches": mismatches,
            "repaired": repaired,
            "live": {key: live.get(key) for key in ("status", "calls", "hits", "failed",
                                                    "windowsDone", "unitsDone", "validationFailures")},
            "rebuilt": {key: rebuilt.get(key) for key in ("status", "calls", "hits", "failed",
                                                          "windowsDone", "unitsDone", "validationFailures")}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--label")
    parser.add_argument("--all", action="store_true", help="check every label found in events.jsonl")
    parser.add_argument("--source-run", type=Path, help="for --missing: the run whose sentences must be covered")
    parser.add_argument("--missing", action="store_true", help="list sentences the translate stage has not covered")
    parser.add_argument("--record", action="store_true", help="write state-check.json into the run directory")
    parser.add_argument("--write", action="store_true", help="overwrite each state file with the rebuilt counters")
    parser.add_argument("--ignore-status", action="store_true", help="compare counters only")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    labels = [args.label] if args.label else labels_in(args.run)
    if not labels:
        print(f"{args.run}: no events.jsonl; nothing to check")
        return 1
    results = [check(args.run, label, args.write, args.ignore_status) for label in labels]
    missing = []
    if args.missing and args.source_run:
        missing = C.missing_units(args.run, args.source_run, "translate")
    payload = {"run": str(args.run), "consistent": all(item["ok"] for item in results),
               "labels": results, "missing": missing}
    if args.record:
        payload["checkedAt"] = datetime.now(timezone.utc).isoformat()
        (args.run / "state-check.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        for item in results:
            if item.get("error"):
                print(f"{item['label']}: {item['error']}")
                continue
            suffix = f"  repaired {item['repaired']} differences" if item.get("repaired") else ""
            print(f"{item['label']}: {'consistent' if item['ok'] else 'MISMATCH'}  "
                  f"windows={item['rebuilt']['windowsDone']} units={item['rebuilt']['unitsDone']}  "
                  f"calls={item['rebuilt']['calls']} hits={item['rebuilt']['hits']}  "
                  f"status={item['rebuilt']['status']}{suffix}")
            for line in item["mismatches"]:
                print("  " + line)
        if args.missing and args.source_run:
            print(f"uncovered sentences: {len(missing)}" + (f"  first: {missing[:8]}" if missing else ""))
        if args.record:
            print(f"wrote {args.run / 'state-check.json'}")
    return 0 if payload["consistent"] and not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
