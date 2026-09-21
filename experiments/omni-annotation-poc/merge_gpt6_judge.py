#!/usr/bin/env python3
"""Validate and merge GPT-6 sentence-judge batches."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


VERDICTS = {"supported", "unsupported", "uncertain"}
BOUNDARIES = {"supported", "uncertain"}
TYPES = {None, "transition", "scripture_reading", "sermon_explanation", "other"}
SCRIPTURE = VERDICTS | {"not_applicable"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--batch", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    packet = json.loads(args.packet.read_text(encoding="utf-8"))
    expected = {item["sentenceId"]: item for window in packet["windows"]
                for item in window["sentenceProposals"]}
    judgments: list[dict] = []
    summaries: list[dict] = []
    limitations: list[str] = []
    errors: list[str] = []
    for path in args.batch:
        batch = json.loads(path.read_text(encoding="utf-8"))
        if batch.get("reviewState") != "machine_judge_candidate":
            errors.append(f"{path}: invalid reviewState")
        if batch.get("humanGold") is not False or batch.get("releaseEligible") is not False:
            errors.append(f"{path}: invalid release flags")
        judgments.extend(batch.get("sentenceJudgments") or [])
        summaries.extend(batch.get("windowSummaries") or [])
        limitations.extend(batch.get("limitations") or [])
    seen: set[str] = set()
    for item in judgments:
        sentence_id = item.get("sentenceId")
        if sentence_id not in expected:
            errors.append(f"unknown sentenceId: {sentence_id}")
            continue
        if sentence_id in seen:
            errors.append(f"duplicate sentenceId: {sentence_id}")
        seen.add(sentence_id)
        if item.get("verdict") not in VERDICTS or item.get("categoryVerdict") not in VERDICTS:
            errors.append(f"invalid verdict: {sentence_id}")
        if item.get("boundaryVerdict") not in BOUNDARIES:
            errors.append(f"invalid boundary verdict: {sentence_id}")
        if item.get("suggestedType") not in TYPES:
            errors.append(f"invalid suggestedType: {sentence_id}")
        if item.get("scriptureReferenceVerdict") not in SCRIPTURE:
            errors.append(f"invalid scripture verdict: {sentence_id}")
        if (expected[sentence_id]["wordTimingStatus"] == "uncertain"
                and item.get("boundaryVerdict") != "uncertain"):
            errors.append(f"uncertain timing promoted: {sentence_id}")
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            errors.append(f"missing reason: {sentence_id}")
    missing = sorted(set(expected) - seen)
    if missing:
        errors.append(f"missing sentenceIds: {','.join(missing)}")
    counts = Counter(item.get("verdict") for item in judgments)
    output = {
        "schemaVersion": "sermon-sidecar-judge-v1",
        "reviewState": "machine_judge_candidate",
        "humanGold": False, "releaseEligible": False,
        "input": {"path": str(args.packet.resolve())},
        "counts": {"sentences": len(judgments), **dict(counts)},
        "sentenceJudgments": judgments,
        "windowSummaries": summaries,
        "limitations": list(dict.fromkeys(limitations)),
        "validationErrors": errors,
    }
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "counts": output["counts"],
                      "validationErrors": errors}, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
