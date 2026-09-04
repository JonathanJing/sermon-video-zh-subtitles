#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.asr_gold import prepare_review_queue


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a pending human word-level ASR Gold review queue.")
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    records = prepare_review_queue(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records), encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "cases": len(records), "status": "pending_human_review"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
