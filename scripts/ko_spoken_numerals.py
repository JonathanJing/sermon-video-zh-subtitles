#!/usr/bin/env python3
"""Korean spoken form for chapter, verse and psalm numbers.

In explicit Bible-book citations Korean reads 장, 절 and Psalm 편 with Sino-Korean numerals
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
    from scripts.language_review_plugins.auto_qc_text_common import korean_sino, _KO_BOOK_CODES
except ModuleNotFoundError:  # run as scripts/ko_spoken_numerals.py
    import sermon_sentence_interpretation as identity
    from language_review_plugins.auto_qc_text_common import korean_sino, _KO_BOOK_CODES

RULE = "ko-sino-chapter-verse-numerals-v2"
INSTRUCTIONS_SCHEMA = "sermon-unit-delivery-instructions-v2"
# Only an explicit Bible book anchors a citation. Keep subsequent adjacent
# chapter/verse/psalm numbers in that chain; never infer context across prose.
# Ordinary counters (photos 장, films 편) and bare numbers remain unchanged.
_NUMBER = r"\d{1,3}(?:\s*[-~–]\s*\d{1,3})?\s*"
_BOOK = "|".join(re.escape(name) for name in sorted(_KO_BOOK_CODES, key=len, reverse=True) if name != "시편")
_DELIMITERS = (("", ""), ("(", ")"), ("[", "]"), ("（", "）"), ("［", "］"))
_COPULAR_ENDINGS = r"(?:이다|이었다|이었다고|이었지만|이었는데|이었으나|이었으면|이었어요|이었죠|이었네요|이었으므로|이었으니까|이었으며|이겠다|이겠습니다|이겠지만|이겠죠|이겠네요|이더라|이더라도|이라|이니|인가|인가요|인데요|인지|이냐|이라고|입니다|이라면|인데|이고|이지만|이라서|이에요|이죠|이네요|이어서|이니까|이므로|이며|이었고|이었습니다|이야|이라고는)"
_PARTICLES = r"(?:" + _COPULAR_ENDINGS + r"|이든|이|처럼|마저|조차|마다|에서는|에서도|에서부터|부터는|부터만|부터도|까지는|까지만|까지도|에는|에도|으로는|으로도|에서|부터|까지|으로|이나|과|와|및|을|를|의|은|는|에|도|만|로)(?![가-힣A-Za-z])"
_RANGE_PARTICLE = r"(?:부터|에서|까지)(?:\s*(?:" + _COPULAR_ENDINGS + r"|였어요|였다|였고|였지만|였는데|예요|라고|의|를|을|은|는|도|만))?(?![가-힣A-Za-z])"
_PARTICLES = r"(?:" + _RANGE_PARTICLE + "|" + _PARTICLES + ")"
_COUNTER_END = r"(?=$|[^가-힣A-Za-z0-9]|" + _PARTICLES + r"|" + _NUMBER + r"(?:장|절|편))"
_CONNECTOR = r"(?:에서부터|부터는|부터만|부터도|이나|이든|과|와|및|부터|에서|,|[-~–])"
_CHAIN = r"(?:\s*" + _CONNECTOR + r"?\s*" + _NUMBER + r"{counter}" + _COUNTER_END + r")*(?![\d])"
_CITATIONS = tuple(
    re.compile(r"(?<![가-힣A-Za-z0-9])(?:" + book + r")\s*" + re.escape(opening) + r"\s*" + _NUMBER
               + counter + _COUNTER_END + _CHAIN.replace("{counter}", counter)
               + ((r"(?:\s*" + _RANGE_PARTICLE + r")?\s*" + re.escape(closing)) if closing else ""))
    for book, counter in ((_BOOK, r"(?:장|절)"), ("시편", r"(?:장|절|편)"))
    for opening, closing in _DELIMITERS
)
_REFERENCE = re.compile(r"(\d{1,3})(?:(\s*[-~–]\s*)(\d{1,3}))?(\s*)(장|절|편)")


def spoken_form(text: str) -> str:
    def spell(match: re.Match) -> str:
        first, dash, second, space, counter = match.groups()
        numbers = korean_sino(int(first)) + (dash + korean_sino(int(second)) if second else "")
        return numbers + space + counter
    for citation in _CITATIONS:
        text = citation.sub(lambda match: _REFERENCE.sub(spell, match.group()), text)
    return text


def equivalent(approved: str, spoken: str) -> bool:
    """True when ``spoken`` is ``approved`` with only this rule applied, ignoring punctuation and spacing."""
    def normalized(value: str) -> str:
        # A punctuation allowlist keeps audible symbols such as %, +, $, /,
        # and range/ratio markers significant, even when Unicode calls them
        # punctuation (for example % is category Po).
        punctuation = ".,!?;…，。！？；、\"'“”‘’「」『』()[]（）"
        def numeric_separator(index, char):
            return (char in ".,，．٫٬" and value[:index].rstrip()[-1:].isdigit()
                    and value[index + 1:].lstrip()[:1].isdigit())
        return "".join(char for index, char in enumerate(value)
                       if numeric_separator(index, char)
                       or (not char.isspace() and char not in punctuation))
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
