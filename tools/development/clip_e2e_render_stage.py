#!/usr/bin/env python3
"""Run clip_e2e_spark.py render as one lanes stage and judge it by committed units.

The formal renderer exits 1 when the raw render's 1x schedule overflows the clip; that is the
known, expected outcome before compaction (the compact and screen stages decide). A stage
runner only sees the exit code, so this wrapper runs the render dispatch, then succeeds only
when the dispatch outcome is known terminal and every unit of the job has a committed render
receipt in the copied-back output. Anything else (reserve trip, refused inputs, unknown
outcome) fails the stage and leaves the dispatch files for reconciliation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("render_args", nargs=argparse.REMAINDER,
                        help="Everything after -- goes to clip_e2e_spark.py render (do not repeat --job)")
    args = parser.parse_args(argv)
    rest = args.render_args[1:] if args.render_args[:1] == ["--"] else args.render_args
    local_out = args.job.resolve().parent.parent
    job = json.loads(args.job.read_text(encoding="utf-8"))
    completed = subprocess.run([sys.executable, str(ROOT / "tools/development/clip_e2e_spark.py"), "render",
                                "--job", str(args.job.resolve()), *rest], cwd=str(ROOT))
    result_path = local_out / "dispatch.result.json"
    if not result_path.is_file():
        print(json.dumps({"status": "failed", "reason": "no_dispatch_result", "exitCode": completed.returncode}))
        return 5
    result = json.loads(result_path.read_text(encoding="utf-8"))
    receipts = sorted((local_out / "spark-output/speech-job/receipts").glob("unit-*.render.json"))
    committed, units = len(receipts), len(job["units"])
    ok = result.get("outcome") == "known_terminal" and result.get("exitCode") in (0, 1) and committed == units
    summary = {"status": "completed" if ok else "failed", "dispatchExitCode": result.get("exitCode"),
               "outcome": result.get("outcome"), "committedUnits": committed, "units": units}
    (local_out / "render-stage.result.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    return 0 if ok else 5


if __name__ == "__main__":
    sys.exit(main())
