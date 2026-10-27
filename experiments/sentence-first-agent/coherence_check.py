#!/usr/bin/env python3
"""Deterministic checks for a sentence-first coherence arm (experiment only)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coherence_core as C  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--arm-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--budget-cps", type=float, default=4.95)
    args = parser.parse_args()
    sentences = C.read_jsonl(args.source_run / "sentences.jsonl")
    translations = C.read_jsonl(args.arm_dir / "translations.jsonl")
    flags = C.continuation_flags(sentences)
    slices = {row["id"]: float(row.get("budgetSeconds") or 0)
              for row in json.loads((args.source_run / "slices" / "slices.json").read_text())}
    glossary = json.loads((args.arm_dir / "glossary.json").read_text())
    hard, warnings = [], []
    if [row["id"] for row in translations] != [row["id"] for row in sentences]:
        hard.append("translation ids/order differ from sentences")
    by_id = {row["id"]: row["target"] for row in translations}
    english = {unit["id"]: unit["english"] for unit in sentences}
    for unit in sentences:
        target = by_id.get(unit["id"], "")
        if not target.strip():
            hard.append(f"{unit['id']}: empty target")
            continue
        if len(target) and len(re.findall(r"[A-Za-z]", target)) > len(target) * 0.3:
            warnings.append({"id": unit["id"], "kind": "english_like",
                             "detail": "target has a high Latin-letter share"})
        budget = slices.get(unit["id"], 0)
        estimate = C.chinese_chars(target) / args.budget_cps if budget else 0
        if budget and estimate > budget * 1.1:
            warnings.append({"id": unit["id"], "kind": "budget",
                             "detail": f"{estimate:.2f}s > {budget:.2f}s"})
        if flags[unit["id"]]["continuesPrevious"]:
            previous = by_id.get(f"s{int(unit['id'][1:]) - 1:04d}")
            if previous and previous.rstrip().endswith(("。", "！", "？")):
                warnings.append({"id": unit["id"], "kind": "continuation_break",
                                 "detail": "previous target ends a sentence"})
        for token in C.number_tokens(english[unit["id"]]):
            if token not in target and not C.target_has_number(target, token):
                warnings.append({"id": unit["id"], "kind": "number", "detail": f"missing {token}"})
        lowered = english[unit["id"]].casefold()
        for entry in glossary.get("people", []):
            source = str(entry.get("source", ""))
            if source and source.casefold() in lowered and entry.get("target") not in target:
                warnings.append({"id": unit["id"], "kind": "name",
                                 "detail": f"{source} -> {entry.get('target')}"})
    report = {"schemaVersion": "sentence-first-coherence-check-v1",
              "units": len(sentences), "hardFailures": hard, "warnings": warnings,
              "budgetOverruns": sum(1 for w in warnings if w["kind"] == "budget"),
              "continuationBreaks": sum(1 for w in warnings if w["kind"] == "continuation_break")}
    out = args.out or (args.arm_dir / "coherence-check.json")
    C.write_json(out, report)
    print(json.dumps({k: report[k] for k in ("units", "budgetOverruns", "continuationBreaks")},
                     ensure_ascii=False), "hard", len(hard), "warnings", len(warnings))
    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
