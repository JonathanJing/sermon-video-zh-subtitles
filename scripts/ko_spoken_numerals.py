#!/usr/bin/env python3
"""Korean spoken form for chapter, verse and psalm numbers.

Korean reads the number before 장, 절 and 편 with Sino-Korean numerals
(8장 = 팔 장, 하박국 2장 = 이 장). The TTS voice often reads Arabic digits with
native numerals instead (여덟 장, 두 장), which changes the meaning a listener
hears. ``spoken_form`` spells those numbers out in Sino-Korean for the dub only;
the approved text, captions and reading text keep the digits.

``build`` writes a ``sermon-unit-delivery-instructions-v2`` file that gives the
renderer this spoken form for every unit it changes, and nothing else.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

try:
    from scripts import sermon_sentence_interpretation as identity
    from scripts.language_review_plugins.auto_qc_text_common import korean_sino
except ModuleNotFoundError:  # run as scripts/ko_spoken_numerals.py
    import sermon_sentence_interpretation as identity
    from language_review_plugins.auto_qc_text_common import korean_sino

RULE = "ko-sino-chapter-verse-numerals-v1"
INSTRUCTIONS_SCHEMA = "sermon-unit-delivery-instructions-v2"
# A digit run, or a range of two, directly before a Sino-read scripture counter: 8장, 3장 16절,
# 16-17절, 시편 23편. A digit run inside a larger number (3,000장, 1.5장, 3:16) is left alone.
_REFERENCE = re.compile(r"(?<![\d.,:])(\d{1,3})(?:(\s*[-~–]\s*)(\d{1,3}))?(\s*)(장|절|편)(?![\d])")


def spoken_form(text: str) -> str:
    def spell(match: re.Match) -> str:
        first, dash, second, space, counter = match.groups()
        numbers = korean_sino(int(first)) + (dash + korean_sino(int(second)) if second else "")
        return numbers + space + counter
    return _REFERENCE.sub(spell, text)


def equivalent(approved: str, spoken: str) -> bool:
    """True when ``spoken`` is ``approved`` with only this rule applied, ignoring punctuation and spacing."""
    def normalized(value: str) -> str:
        return "".join(char for char in value if char.isalnum())
    return normalized(spoken_form(approved)) == normalized(spoken) and spoken_form(approved) != approved


def build(job: dict) -> dict | None:
    """The unit instructions for a Korean speech job, or ``None`` when no unit changes."""
    if job.get("targetLocale") != "ko":
        raise ValueError("Sino chapter numerals apply to Korean speech jobs only")
    units = []
    for unit in job["units"]:
        spoken = spoken_form(unit["text"])
        if spoken != unit["text"]:
            units.append({"translationGroupId": unit["translationGroupId"],
                          "approvedTextSha256": hashlib.sha256(unit["text"].encode()).hexdigest(),
                          "spokenText": spoken,
                          "operatorEvidence": f"{RULE}: deterministic Sino-Korean reading of chapter/verse numbers"})
    if not units:
        return None
    return {"schemaVersion": INSTRUCTIONS_SCHEMA, "targetLocale": "ko",
            "speechJobJsonSha256": identity.json_sha256(job), "units": units}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--job", type=Path, required=True, help="Korean speech job.json")
    parser.add_argument("--out", type=Path, required=True, help="New unit-instructions JSON")
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"{args.out} exists; unit instructions bind one job, choose a new path")
    document = build(json.loads(args.job.read_text()))
    if document is None:
        print(json.dumps({"status": "no_change", "units": 0}))
        return
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"status": "written", "units": len(document["units"]), "out": str(args.out)}))


if __name__ == "__main__":
    main()
