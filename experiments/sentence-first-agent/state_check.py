#!/usr/bin/env python3
"""Recompute a DeepSeek stage's state from events.jsonl + done.jsonl and compare.

The live state file is a projection of the event stream. This tool rebuilds that
projection and reports counters that disagree, so a double-counted resume or a
lost window shows up as a mismatch instead of being read as progress.

  python3 $EXP/state_check.py --run $RUN/coherence-<tag> --label translate
  python3 $EXP/state_check.py --run $RUN --label trim --write     # repair the file
"""
from __future__ import annotations

import argparse
import json
import sys
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--label")
    parser.add_argument("--write", action="store_true", help="overwrite the state file with the rebuilt counters")
    parser.add_argument("--ignore-status", action="store_true", help="compare counters only")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    rebuilt = C.rebuild_state(args.run, args.label)
    if not rebuilt:
        print(f"{args.run}: no events.jsonl; nothing to rebuild")
        return 1
    label = rebuilt["label"]
    path = state_path(args.run, label)
    live = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    mismatches = C.state_mismatches(live, rebuilt, ignore_status=args.ignore_status)
    if args.write:
        merged = {**live, **{key: rebuilt[key] for key in rebuilt}}
        merged["summary"] = live.get("summary", {})
        merged["rebuiltAt"] = rebuilt.get("lastEvent")
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.json:
        print(json.dumps({"label": label, "state": str(path), "rebuilt": rebuilt,
                          "mismatches": mismatches, "written": bool(args.write)}, ensure_ascii=False))
    else:
        print(f"{label}: {path}")
        print(f"live    {json.dumps({k: live.get(k) for k in ('status','calls','hits','failed','windowsDone','unitsDone','validationFailures','costUsd')}, ensure_ascii=False)}")
        print(f"rebuilt {json.dumps({k: rebuilt.get(k) for k in ('status','calls','hits','failed','windowsDone','unitsDone','validationFailures','costUsd')}, ensure_ascii=False)}")
        if mismatches:
            print("MISMATCH")
            for line in mismatches:
                print("  " + line)
        else:
            print("consistent")
    if mismatches and not args.write:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
