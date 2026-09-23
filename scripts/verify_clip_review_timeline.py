#!/usr/bin/env python3
"""Check that a clip review table shows original-recording times for each anchor."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


ROW = re.compile(r"^\| `([^`]+)` \| (\d+:\d{2}(?:\.\d+)?)–(\d+:\d{2}(?:\.\d+)?) \|")


def seconds(value: str) -> float:
    minutes, remainder = value.split(":", 1)
    return int(minutes) * 60 + float(remainder)


def verify(anchor: dict, markdown: str, *, original_sermon_start: float,
           clip_start: float, clip_end: float, tolerance: float = 0.03) -> int:
    units = anchor["sourceUnits"]
    rows = [match.groups() for line in markdown.splitlines()
            if (match := ROW.match(line))]
    if [row[0] for row in rows] != [unit["sourceUnitId"] for unit in units]:
        raise ValueError("Review table must cover every anchor in source order")
    if abs(original_sermon_start + float(units[0]["start"]) - clip_start) > tolerance:
        raise ValueError("First anchor does not match selected clip start")
    if abs(original_sermon_start + float(units[-1]["end"]) - clip_end) > tolerance:
        raise ValueError("Last anchor does not match selected clip end")
    for unit, (_, start, end) in zip(units, rows):
        expected_start = original_sermon_start + float(unit["start"])
        expected_end = original_sermon_start + float(unit["end"])
        if abs(seconds(start) - expected_start) > tolerance or abs(seconds(end) - expected_end) > tolerance:
            raise ValueError(f"Review table has a timebase mismatch at {unit['sourceUnitId']}")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor-manifest", required=True, type=Path)
    parser.add_argument("--review-markdown", required=True, type=Path)
    parser.add_argument("--original-sermon-start-seconds", required=True, type=float)
    parser.add_argument("--clip-absolute-start-seconds", required=True, type=float)
    parser.add_argument("--clip-absolute-end-seconds", required=True, type=float)
    args = parser.parse_args()
    count = verify(json.loads(args.anchor_manifest.read_text(encoding="utf-8")),
                   args.review_markdown.read_text(encoding="utf-8"),
                   original_sermon_start=args.original_sermon_start_seconds,
                   clip_start=args.clip_absolute_start_seconds,
                   clip_end=args.clip_absolute_end_seconds)
    print(json.dumps({"status": "pass", "checkedSourceUnits": count}))


if __name__ == "__main__":
    main()
