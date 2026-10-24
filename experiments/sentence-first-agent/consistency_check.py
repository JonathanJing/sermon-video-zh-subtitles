#!/usr/bin/env python3
"""Post-merge translation consistency check for one sentence-first locale.

The 2026-10-23 run showed three cross-part drifts that a per-part translator cannot see:
Korean address mixed ``당신`` and ``여러분``; century/number spellings differed between parts;
verified names had variant spellings. This check runs after ``translate_parts.py merge`` and
writes a report the agent must resolve before ``build_speech.py``:

* address: preferred vs forbidden forms, share and mixed sentence ids;
* terms: an episode glossary of wrong -> right variants (``--rules`` JSON);
* numbers: target text still containing digits, and whether ``review.spokenForms`` covers it.

It is advisory (exit 0 with warnings). The rules file is per episode; the defaults cover the
address forms of ko/es. Example:

  consistency_check.py --run artifacts/sentence-first-agent/<run> --rules glossary.json

  {"terms": [{"wrong": ["에릭 가이어", "Eric Guyer"], "right": ["에릭 가이거"]}],
   "address": {"preferred": ["여러분"], "forbidden": ["당신"]},
   "numberPolicy": "flag_digits"}
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DEFAULT_RULES = {
    "ko": {"address": {"preferred": ["여러분"], "forbidden": ["당신"]}},
    "es": {"address": {"preferred": ["ustedes"], "forbidden": ["vosotros"]}},
    "zh-Hans": {},
}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def effective_targets(run: Path) -> tuple[dict, dict]:
    translations = {t["id"]: t.get("target", "") for t in load_jsonl(run / "translations.jsonl")}
    review = json.loads((run / "review.json").read_text(encoding="utf-8"))
    for sid, revision in (review.get("revisions") or {}).items():
        if revision.get("target"):
            translations[sid] = revision["target"]
    return translations, review


def check(run: Path, rules: dict, locale: str | None = None) -> dict:
    translations, review = effective_targets(run)
    locale = locale or review.get("locale") or "unknown"
    merged = dict(DEFAULT_RULES.get(locale, {}))
    merged.update(rules or {})
    address = merged.get("address") or {}
    preferred = address.get("preferred") or []
    forbidden = address.get("forbidden") or []
    preferred_ids = [sid for sid, text in translations.items() if any(p in text for p in preferred)]
    forbidden_ids = [sid for sid, text in translations.items() if any(f in text for f in forbidden)]
    total = len(preferred_ids) + len(forbidden_ids)
    share = round(len(preferred_ids) / total, 3) if total else None
    min_share = float(address.get("minPreferredShare", 0.8))
    address_ok = share is None or share >= min_share

    term_findings = []
    for term in merged.get("terms") or []:
        wrong = term.get("wrong") or []
        right = term.get("right") or []
        bad_ids = [sid for sid, text in translations.items() if any(w in text for w in wrong)]
        if bad_ids:
            term_findings.append({"wrong": wrong, "right": right, "ids": bad_ids})

    digit_ids = [sid for sid, text in translations.items() if re.search(r"\d", text)]
    spoken = review.get("spokenForms") or {}
    spoken_text = " ".join(spoken.keys())
    uncovered = [sid for sid in digit_ids
                 if not any(form in translations[sid] for form in spoken) and translations[sid] not in spoken_text]
    report = {
        "schemaVersion": "sentence-first-consistency-v1",
        "locale": locale,
        "address": {"preferred": preferred, "forbidden": forbidden, "preferredIds": len(preferred_ids),
                    "forbiddenIds": len(forbidden_ids), "mixed": forbidden_ids, "share": share,
                    "minPreferredShare": min_share, "status": "pass" if address_ok else "warn"},
        "terms": term_findings,
        "numbers": {"digitIds": digit_ids, "spokenForms": sorted(spoken), "uncoveredIds": uncovered,
                    "status": "pass" if not digit_ids else "warn"},
        "status": "pass" if (address_ok and not term_findings and not digit_ids) else "warn",
    }
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--rules", type=Path)
    p.add_argument("--locale")
    p.add_argument("--out", type=Path)
    a = p.parse_args(argv)
    rules = json.loads(a.rules.read_text(encoding="utf-8")) if a.rules else {}
    _mark(a.run, "l2.consistency", "started")
    report = check(a.run, rules, a.locale)
    _mark(a.run, "l2.consistency", "finished")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if a.out:
        a.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
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
