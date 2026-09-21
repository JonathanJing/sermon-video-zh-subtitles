#!/usr/bin/env python3
"""Retry explicitly selected full-sermon windows under a new attempt identity."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--window", action="append", required=True)
    parser.add_argument("--attempt", default="retry1")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    root = args.manifest.resolve().parent
    by_id = {item["windowId"]: item for item in manifest["windows"]}
    runner = Path(__file__).resolve().parent / "run_gemini_live.py"
    failures = 0
    for window_id in args.window:
        item = by_id[window_id]
        case_id = f"{window_id}-{args.attempt}"
        command = [
            sys.executable, str(runner), "--env-file", str(args.env_file),
            "--model", args.model, "--prompt", str(root / item["paths"]["prompt"]),
            "--video", str(root / item["paths"]["video"]),
            "--audio", str(root / item["paths"]["audio"]),
            "--duration", str(item["durationSeconds"]), "--case-id", case_id,
            "--out", str(args.results), "--expected-audio-status", "matched",
        ]
        print(case_id, flush=True)
        if subprocess.run(command, check=False).returncode:
            failures += 1
    if failures:
        raise SystemExit(f"{failures} retry case(s) failed")


if __name__ == "__main__":
    main()
