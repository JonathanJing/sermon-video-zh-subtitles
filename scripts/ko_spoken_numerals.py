#!/usr/bin/env python3
"""Korean spoken form for chapter, verse and psalm numbers.

Korean reads chapter and verse numbers with Sino-Korean numerals (8장 = 팔 장,
하박국 2장 = 이 장): in explicit Bible-book citations (장, 절 and Psalm 편), and for a bare
N장 or N절 in sermon prose ("look at chapter 8"), unless it counts objects (사진 2장). The TTS voice often reads Arabic digits with
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
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
    from tongxing_production.source import sentence_interpretation as identity
    from scripts.language_review_plugins.auto_qc_text_common import korean_sino, _KO_BOOK_CODES
except ModuleNotFoundError:  # run as scripts/ko_spoken_numerals.py
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
    from tongxing_production.source import sentence_interpretation as identity
    from language_review_plugins.auto_qc_text_common import korean_sino, _KO_BOOK_CODES

RULE_V2 = "ko-sino-chapter-verse-numerals-v2"
RULE_V3 = "ko-sino-chapter-verse-numerals-v3"
RULE = "ko-sino-chapter-verse-numerals-v4"
INSTRUCTIONS_SCHEMA = "sermon-unit-delivery-instructions-v2"
# Only an explicit Bible book anchors a citation. Keep subsequent adjacent
# chapter/verse/psalm numbers in that chain; never infer context across prose.
# Ordinary counters (photos 장, films 편) and bare numbers remain unchanged.
_NUMBER = r"\d{1,3}(?:\s*[-~–]\s*\d{1,3})?\s*"
_BOOK = "|".join(re.escape(name) for name in sorted(_KO_BOOK_CODES, key=len, reverse=True) if name != "시편")
_DELIMITERS = (("", ""), ("(", ")"), ("[", "]"), ("（", "）"), ("［", "］"))
_COPULAR_ENDINGS = r"(?:입니까|이었습니까|이다|이었다|이었다고|이었지만|이었는데|이었으나|이었으면|이었어요|이었죠|이었네요|이었으므로|이었으니까|이었으며|이겠다|이겠습니다|이겠지만|이겠죠|이겠네요|이더라|이더라도|이라|이니|인가|인가요|인데요|인지|이냐|이라고|입니다|이라면|인데|이고|이지만|이라서|이에요|이죠|이네요|이어서|이니까|이므로|이며|이었고|이었습니다|이야|이라고는)"
_PARTICLES = r"(?:" + _COPULAR_ENDINGS + r"|이든|이|처럼|마저|조차|마다|에서는|에서도|에서부터|부터는|부터만|부터도|까지는|까지만|까지도|에는|에도|으로는|으로도|에서|부터|까지|으로|이나|과|와|및|을|를|의|은|는|에|도|만|로)(?![가-힣A-Za-z])"
# Contract the complete registered copula family, rather than enumerating
# individual past endings after each range marker (이었습니다 -> 였습니다).
_RANGE_COPULAR_ENDINGS = _COPULAR_ENDINGS.replace("이었", "였").replace("이에요", "예요").replace("이라고", "라고")
_RANGE_PARTICLE = r"(?:부터|에서|까지)(?:\s*(?:" + _COPULAR_ENDINGS + "|" + _RANGE_COPULAR_ENDINGS + r"|의|를|을|은|는|도|만))?(?![가-힣A-Za-z])"
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
# v3 (2026-10-13, user decision): a sermon names chapters without the book ("8장의 맨 첫 절")
# and the voice then reads native numerals, so bare N장 and N절 are chapter and verse too.
# Bare N편 stays (films, poems), and so does a count right after a counted-object noun.
_COUNTED_NOUNS = ("사진", "종이", "편지", "카드", "표", "티켓", "지폐", "쪽지", "그림", "접시", "수건", "담요", "이불", "페이지")
_BARE = re.compile(r"(?<![\d.,:．٫٬，A-Za-z가-힣])(?<!(?:" + "|".join(n for n in _COUNTED_NOUNS if len(n) == 2) + r") )"
                   r"(?<!(?:" + "|".join(n for n in _COUNTED_NOUNS if len(n) == 1) + r") )"
                   + _NUMBER + r"(?:장|절)" + _COUNTER_END + _CHAIN.replace("{counter}", r"(?:장|절)"))
_COUNTED = re.compile(r"(?<![가-힣A-Za-z0-9])(?:" + "|".join(_COUNTED_NOUNS)
                      + r")(?:은|는|이|가|을|를|도|만|의|에서|에는|에도|으로|로)?\s*[(\[（［]?\s*" + _NUMBER
                      + r"(?:장|절|편)" + _COUNTER_END + _CHAIN.replace("{counter}", r"(?:장|절|편)")
                      + r"(?:\s*" + _RANGE_PARTICLE + r")?\s*[)\]）］]?")


_NUMERIC_TOKEN = re.compile(r"(?:\d+(?:\s*[.,:．٫٬，/／⁄∕+＋*＊×÷=＝^％%−]\s*\d+)+"
                            r"|(?<![\d])[-+＋−]\s*\d+)\s*(?:장|절)"
                            + _COUNTER_END + _CHAIN.replace("{counter}", r"(?:장|절)"))


# A bare counter after an arbitrary noun is ambiguous (서류 2장, not chapter 2).
# Keep the supported sermon entry points explicit rather than growing a noun blacklist.
# v3 froze the first list. v4 (2026-10-13 clip run, "그렇기 때문에 8장을 보면") adds
# connectives and adverbs, which never count objects, and lets a pause comma follow any
# introducer ("따라서, 3장").
_BARE_INTRODUCERS_V3 = frozenset({"그래서", "그러므로", "그리고", "이제", "먼저", "본문"})
_BARE_INTRODUCERS = _BARE_INTRODUCERS_V3 | {"본문은", "본문도", "때문에", "따라서", "그러니까", "그런데", "하지만",
                                            "그러나", "또", "또한", "다시", "이어서", "계속해서"}
_PAUSE_PUNCTUATION = ",，、"


def bare_context_allowed(text: str, start: int, end: int, *, rule: str = RULE) -> bool:
    introducers = _BARE_INTRODUCERS_V3 if rule == RULE_V3 else _BARE_INTRODUCERS
    prefix = text[:start].rstrip()
    if not prefix or prefix[-1] in ".!?。！？;；":
        return True
    # Opening quotation/bracket may delimit a chapter, but does not erase a noun.
    prefix = prefix.rstrip("(（[［\"'“‘ ")
    if not prefix or prefix[-1] in ".!?。！？;；":
        return True
    if rule != RULE_V3:
        prefix = prefix.rstrip(_PAUSE_PUNCTUATION + " ")
    previous = re.search(r"([가-힣A-Za-z]+)$", prefix)
    word = previous.group(1) if previous else ""
    if word in introducers or word in _KO_BOOK_CODES:
        return True
    # These existing sermon forms explicitly identify a verse/chapter context.
    return bool(re.match(r"의\s+맨\s+첫\s+절", text[end:])) or (word == "뒤" and text[start:end].endswith("절"))


def bare_citation_matches(text: str, *, rule: str = RULE):
    protected = [match.span() for pattern in (_COUNTED, _NUMERIC_TOKEN) for match in pattern.finditer(text)]
    return [match for match in _BARE.finditer(text)
            if not any(start <= match.start() < end for start, end in protected)
            and bare_context_allowed(text, match.start(), match.end(), rule=rule)]


def spoken_form_v2(text: str) -> str:
    """Frozen book-anchored v2 behavior for existing normalization-policy jobs."""
    return _spoken_form(text, bare_chapters=False)


def spoken_form_v3(text: str) -> str:
    """Frozen v3 behavior (first introducer list) for existing normalization-policy jobs."""
    return _spoken_form(text, bare_chapters=True, rule=RULE_V3)


def spoken_form(text: str) -> str:
    return _spoken_form(text, bare_chapters=True)


def _spoken_form(text: str, *, bare_chapters: bool, rule: str = RULE) -> str:
    def spell(match: re.Match) -> str:
        first, dash, second, space, counter = match.groups()
        numbers = korean_sino(int(first)) + (dash + korean_sino(int(second)) if second else "")
        return numbers + space + counter
    for citation in _CITATIONS:
        text = citation.sub(lambda match: _REFERENCE.sub(spell, match.group()), text)
    if not bare_chapters:
        return text
    matches = {match.span() for match in bare_citation_matches(text, rule=rule)}
    return _BARE.sub(lambda match: _REFERENCE.sub(spell, match.group())
                     if match.span() in matches else match.group(), text)


def equivalent(approved: str, spoken: str, *, rule: str = RULE) -> bool:
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
    spell = {RULE_V2: spoken_form_v2, RULE_V3: spoken_form_v3, RULE: spoken_form}[rule]
    return normalized(spell(approved)) == normalized(spoken) and spell(approved) != approved


def build(job: dict) -> dict | None:
    """The unit instructions for a Korean speech job, or ``None`` when no unit changes."""
    if job.get("targetLocale") != "ko":
        raise ValueError("Sino chapter numerals apply to Korean speech jobs only")
    # A job bound to a frozen rule keeps that rule's forms.
    bound = (job.get("adapter") or {}).get("normalizationPolicySha256")
    spell, rule = next(((spell, rule) for spell, rule in ((spoken_form_v2, RULE_V2), (spoken_form_v3, RULE_V3))
                        if bound == identity.json_sha256({"version": "v2", "policy": "exact_approved_text_with_registered_spoken_forms",
                                                          "spokenForms": {"ko": rule}})), (spoken_form, RULE))
    units = []
    for unit in job["units"]:
        spoken = spell(unit["text"])
        if spoken != unit["text"]:
            units.append({"translationGroupId": unit["translationGroupId"],
                          "approvedTextSha256": hashlib.sha256(unit["text"].encode()).hexdigest(),
                          "spokenText": spoken,
                          "operatorEvidence": f"{rule}: deterministic Sino-Korean reading of chapter/verse numbers"})
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
