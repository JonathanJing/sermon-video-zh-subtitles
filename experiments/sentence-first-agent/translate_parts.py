#!/usr/bin/env python3
"""Split a run's sentences into parts for parallel translator subagents, and merge their outputs.

  split  write <run>/translate/input-<k>.jsonl: id, speaker, english, 3 sentences before, 2 after,
         and (with --reference-run) the already approved translation of the same sentence
  merge  join <run>/translate/output-<k>.jsonl into translations.jsonl in sentence order, refuse a
         missing, extra or empty row, and list revised rows and rows that still contain digits

Each subagent gets one input file and writes the matching output file, one row per sentence:
{"id", "locale", "target", "reviewNote"} with reviewNote "pass" or "revised: …" after its own
second-pass review. 2026-10-22: 746 sentences in 4 parts per locale took 2.0–3.6 minutes a part.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_rows(path: Path, items: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in items), encoding="utf-8")


def split(run: Path, parts: int, reference: Path | None, names: dict[str, str]) -> None:
    sent = rows(run / "sentences.jsonl")
    approved = {r["id"]: r["target"] for r in rows(reference / "translations.jsonl")} if reference else {}
    work = run / "translate"
    work.mkdir(exist_ok=True)
    size = -(-len(sent) // parts)
    for k in range(parts):
        part = []
        for i in range(k * size, min((k + 1) * size, len(sent))):
            s = sent[i]
            row = {"id": s["id"], "english": s["english"],
                   "before": [x["english"] for x in sent[max(0, i - 3):i]],
                   "after": [x["english"] for x in sent[i + 1:i + 3]]}
            if s.get("speakerId"):
                row["speaker"] = names.get(s["speakerId"], s["speakerId"])
            if approved:
                row["reference"] = approved[s["id"]]
            part.append(row)
        if part:
            write_rows(work / f"input-{k + 1}.jsonl", part)
            print(f"part {k + 1}: {part[0]['id']}–{part[-1]['id']} ({len(part)})")


def merge(run: Path, locale: str) -> None:
    sent = rows(run / "sentences.jsonl")
    outputs = sorted((run / "translate").glob("output-*.jsonl"), key=lambda p: int(p.stem.split("-")[1]))
    merged = [r for path in outputs for r in rows(path)]
    if [r["id"] for r in merged] != [s["id"] for s in sent]:
        raise SystemExit("output ids differ from sentences.jsonl (missing, extra or out of order)")
    bad = [r["id"] for r in merged if r.get("locale") != locale or not str(r.get("target", "")).strip()]
    if bad:
        raise SystemExit(f"wrong locale or empty target: {bad[:10]}")
    write_rows(run / "translations.jsonl", merged)
    revised = [r["id"] for r in merged if r.get("reviewNote", "pass") != "pass"]
    print(f"{locale}: {len(merged)} rows, {len(revised)} revised: {' '.join(revised)}")
    for r in merged:
        if re.search(r"\d", r["target"]):
            print(f"  digits {r['id']}: {r['target'][:120]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("split")
    s.add_argument("--run", type=Path, required=True)
    s.add_argument("--parts", type=int, default=4)
    s.add_argument("--reference-run", type=Path, help="run whose translations.jsonl is an approved reference")
    s.add_argument("--name", action="append", default=[], metavar="SPEAKERID=LABEL",
                   help="speaker label shown to the translator, e.g. john_thomas='JT (John Thomas)'")
    m = sub.add_parser("merge")
    m.add_argument("--run", type=Path, required=True)
    m.add_argument("--locale", required=True)
    args = parser.parse_args()
    if args.command == "split":
        split(args.run, args.parts, args.reference_run, dict(n.split("=", 1) for n in args.name))
    else:
        merge(args.run, args.locale)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
