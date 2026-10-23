#!/usr/bin/env python3
"""Classify back-transcription score mismatches so review attention goes to real issues.

The 2026-10-23 review sheets mixed ASR artifacts with content errors: ``Guau``/``Wow``,
``Sí``/``C``, ``阿们``/``阿门``, ``十九世纪``/``19世纪``, ``邦``/``帮`` are not narration
mistakes; names, negation and different content are. This module:

* normalizes case/punctuation/spaces;
* recognizes locale variant pairs (``--rules`` / built-in es examples);
* recognizes number-form differences (Arabic digits vs spelled numbers);
* recognizes short homophones by edit distance (CJK/1-2 character lines);
* otherwise classifies ``content``.

``asr_triage.py`` writes a report; ``review_player.py`` uses the same classifier to split its
``asr_variant`` / ``asr_content`` flags.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

DEFAULT_VARIANTS = {
    "es": [["Guau", "Wow"], ["Sí", "C"], ["Sí", "Si"]],
    "zh-Hans": [],
    "ko": [],
}
NUMBER_WORDS = {
    "zh-Hans": "〇零一二三四五六七八九十百千万两",
    "ko": "영일이삼사오육칠팔구십백천만",
    "es": "unouna dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince "
          "dieciséis diecisiete dieciocho diecinueve veinte treinta cuarenta cincuenta sesenta setenta "
          "ochenta noventa cien mil",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff\uac00-\ud7af]+", "", text)


def strip_numbers(text: str, locale: str) -> str:
    words = NUMBER_WORDS.get(locale, "")
    out = re.sub(r"[0-9]+", "", text)
    for ch in set(words):
        out = out.replace(ch, "")
    for word in re.findall(r"[a-záéíóúñü]+", words):
        out = out.replace(word, "")
    return out


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def classify(expected: str, recognized: str, locale: str = "", variants: list[list[str]] | None = None) -> str:
    e, r = normalize(expected), normalize(recognized)
    if not e or not r:
        return "empty"
    if e == r:
        return "identical"
    pairs = variants if variants is not None else DEFAULT_VARIANTS.get(locale, [])
    for pair in pairs:
        pe, pr = normalize(pair[0]), normalize(pair[1])
        if (e, r) in {(pe, pr), (pr, pe)}:
            return "variant"
    if strip_numbers(e, locale) == strip_numbers(r, locale) and (e != strip_numbers(e, locale) or r != strip_numbers(r, locale)):
        return "number_form"
    if edit_distance(e, r) <= 2 and min(len(e), len(r)) <= 6:
        return "homophone"
    return "content"


def triage(report: dict, locale: str = "", variants: list[list[str]] | None = None) -> dict:
    rows = []
    for item in report.get("sentences", []):
        cls = classify(item.get("expected", ""), item.get("recognized", ""), locale, variants)
        rows.append({"id": item["id"], "similarity": item.get("similarity"), "class": cls,
                     "expected": item.get("expected", ""), "recognized": item.get("recognized", "")})
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["class"]] = counts.get(row["class"], 0) + 1
    variant_ids = [r["id"] for r in rows if r["class"] in ("identical", "variant", "number_form", "homophone")]
    content_ids = [r["id"] for r in rows if r["class"] == "content"]
    return {"schemaVersion": "sentence-first-asr-triage-v1", "locale": locale, "counts": counts,
            "variantIds": variant_ids, "contentIds": content_ids, "rows": rows,
            "status": "pass" if not content_ids else "review"}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--locale")
    p.add_argument("--rules", type=Path)
    p.add_argument("--out", type=Path)
    a = p.parse_args(argv)
    _mark(a.run, "l3.asr-triage", "started")
    report = json.loads((a.run / "asr-report.json").read_text(encoding="utf-8"))
    locale = a.locale or json.loads((a.run / "review.json").read_text(encoding="utf-8")).get("locale", "")
    variants = None
    if a.rules:
        variants = json.loads(a.rules.read_text(encoding="utf-8")).get("variants")
    result = triage(report, locale, variants)
    _mark(a.run, "l3.asr-triage", "finished")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=1))
    out = a.out or (a.run / "asr-triage.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

def _mark(run, stage: str, event: str) -> None:
    try:
        from runlog import mark
    except ImportError:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from runlog import mark
    mark(run, stage, event)
