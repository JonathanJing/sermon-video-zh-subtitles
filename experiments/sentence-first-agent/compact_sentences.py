#!/usr/bin/env python3
"""Compress over-budget Chinese sentences to the sync budget (experiment only)."""
from __future__ import annotations
import argparse, json, re, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coherence_core as C  # noqa: E402

SYSTEM = """把给定的中文口播句压缩到不超过 maxChars 个汉字，保持自然口语。
必须保留：否定、数字、人名/称谓、经文出处、因果关系和全部论点。
只删重复、填充词和同义复述；不要改写成另一句话，不要漏信息。
只返回 JSON：{"id":"原 id","target":"压缩后的中文"}。"""

def compress(client, row, unit, max_chars, names):
    user = {"id": row["id"], "english": unit["english"], "target": row["target"],
            "maxChars": max_chars, "names": names}
    for attempt in range(2):
        result = client(SYSTEM, user)
        target = result.get("target")
        if isinstance(target, str) and target.strip():
            value = target.strip()
            if C.chinese_chars(value) <= max_chars * (1.05 if attempt == 0 else 1.0):
                missing = [t for t in C.number_tokens(unit["english"])
                           if t not in value and not C.target_has_number(value, t)]
                if not missing:
                    return row["id"], value
        user = dict(user, previousFailure="too long or missing number; shorten further")
    return row["id"], row["target"]

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--ratio", type=float, default=0.9)
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()
    sentences = {u["id"]: u for u in C.read_jsonl(args.run / "sentences.jsonl")}
    rows = C.read_jsonl(args.run / "translations.jsonl")
    slices = {r["id"]: float(r["budgetSeconds"]) for r in json.loads((args.run / "slices/slices.json").read_text())}
    glossary = json.loads((args.run / "coherence-E/glossary.json").read_text())
    names = [e.get("target") for e in glossary.get("people", []) if e.get("target")]
    client = C.DeepSeek(args.run / "compaction-cache", execute=args.execute)
    targets = []
    for row in rows:
        chars = C.chinese_chars(row["target"])
        limit = max(1, int(slices[row["id"]] * 4.95 * args.ratio))
        if chars > limit:
            targets.append((row, limit))
    with ThreadPoolExecutor(6) as pool:
        results = dict(pool.map(lambda item: compress(client, item[0], sentences[item[0]["id"]],
                                                     item[1], names), targets))
    changed = 0
    for row in rows:
        value = results.get(row["id"])
        if value and value != row["target"]:
            row["target"] = value
            row["reviewNote"] = "compacted to sync budget"
            changed += 1
    C.write_jsonl(args.run / "translations.jsonl", rows)
    (args.run / "review.json").write_text(json.dumps(
        {"locale": "zh-Hans", "speaker": "eric_pilot", "charsPerSecond": 4.95,
         "revisions": {}, "notes": {}, "spokenForms": {}}, ensure_ascii=False, indent=2) + "\n")
    C.write_json(args.run / "compaction.json",
                 {"ratio": args.ratio, "considered": len(targets), "changed": changed,
                  "cost": client.ledger()})
    print(json.dumps({"considered": len(targets), "changed": changed, "cost": client.ledger()},
                     ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
