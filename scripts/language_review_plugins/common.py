"""Small, auditable checks shared by single-locale Layer 2 review plugins."""
from __future__ import annotations

import re
import unicodedata
from hashlib import sha256


def result(check_id: str, ok: bool, evidence: str) -> dict[str, str]:
    return {"checkId": check_id, "status": "pass" if ok else "fail", "evidence": evidence}


def normalized_quote(value: str) -> str:
    """Ignore display punctuation only; preserve every scripture letter and digit."""
    return "".join(char for char in unicodedata.normalize("NFKC", value)
                   if not char.isspace() and not unicodedata.category(char).startswith("P"))


def has_unsafe_speech_markup(utterances: list[str], *, max_chars: int = 180) -> bool:
    if not utterances or len(utterances) > 4:
        return True
    return any(
        not text.strip() or len(text) > max_chars or "\n" in text or "\r" in text
        or bool(re.search(r"<[^>]*>|\[[^]]+\]|\{[^}]+\}", text))
        or any(unicodedata.category(char) in {"Cc", "Cs"} for char in text)
        for text in utterances
    )


def explicit_series_errors(policy: dict, english_units: list[dict], target_text: str) -> list[str]:
    """Check only explicit full-title mentions within this group, never book names."""
    english = " ".join(unit["english"] for unit in english_units)
    errors = []
    for term in policy["terminology"]["seriesNames"]:
        source = term["source"]
        title_context = re.search(r"\b(?:series|series called|titled|entitled)\b.{0,80}"
                                  + re.escape(source), english, flags=re.IGNORECASE)
        if title_context and (term["reviewStatus"] == "pending" or not term["target"]
                              or term["target"] not in target_text):
            errors.append(source)
    return errors


def unresolved_locale_policy(policy: dict, expected_edition: str) -> list[str]:
    reasons = []
    scripture = policy.get("scripture", {})
    if scripture.get("editionId") != expected_edition:
        reasons.append("wrong scripture edition")
    if scripture.get("citationUseStatus") != "project_source_reviewed":
        reasons.append("citation use evidence pending")
    if scripture.get("quoteCheckPolicy") != "source_bound_exact_quote":
        reasons.append("source-bound quote policy pending")
    for kind in ("seriesNames", "properNames"):
        if any(term.get("reviewStatus") == "pending" or not term.get("target")
               for term in policy.get("terminology", {}).get(kind, [])):
            reasons.append(f"{kind} review pending")
    return reasons


SOURCE_SHA256 = "4d645ff0aad0b55b2eb913fd0749ebcb3bed010ddfc037e89e1f8a98f44a227b"
QUOTE_2_UNIT = "block-12-u002"
QUOTE_3_LEAD = ("block-13-u007", "block-14-u001")
QUOTE_3_GROUP = ("block-14-u002", "block-14-u003")
ENGLISH_QUOTES = {
    QUOTE_2_UNIT: "You've abandoned the love you had at first.",
    "block-13-u007": "There are a few.",
    "block-14-u001": "There's not many.",
    "block-14-u002": "There's just a few of you.",
    "block-14-u003": "Who have not defiled their clothes.",
}


def source_bound_scripture_review(
    policy: dict, english_units: list[dict], group: dict, *, edition: str,
    excerpt_2: tuple[str, str], excerpt_3: tuple[str, str],
    few_pattern: str, not_many_pattern: str,
) -> tuple[bool, str]:
    """Validate this clip's approved quote boundaries and exact edition excerpts.

    The 3:4 quotation is an allowed two-source-unit group because Korean and
    Spanish quote word order differs from English. Its two preceding source
    units remain the speaker's repeated emphasis. This mechanical allocation
    still requires full human candidate review.
    """
    ids = group["sourceUnitIds"]
    text = group["targetText"]
    scripture = policy["scripture"]
    problems = []
    if group.get("englishSourcePackageJsonSha256") != SOURCE_SHA256:
        problems.append("unknown English Source Package hash")
    if scripture.get("editionId") != edition:
        problems.append("wrong scripture edition")
    if scripture.get("citationUseStatus") != "project_source_reviewed":
        problems.append("citation rights and attribution evidence pending")
    if scripture.get("quoteCheckPolicy") != "source_bound_exact_quote":
        problems.append("source-bound quote policy pending")
    if [row.get("sourceUnitId") for row in english_units] != ids:
        problems.append("source unit identity differs from English anchor")
    if any(id_ in ENGLISH_QUOTES and english_units[index].get("english") != ENGLISH_QUOTES[id_]
           for index, id_ in enumerate(ids) if index < len(english_units)):
        problems.append("approved English quote unit text changed")
    for excerpt, digest in (excerpt_2, excerpt_3):
        if sha256(excerpt.encode("utf-8")).hexdigest() != digest:
            problems.append("pinned edition excerpt hash changed")
    normalized = normalized_quote(text).casefold()
    quote_2 = normalized_quote(excerpt_2[0]).casefold()
    quote_3 = normalized_quote(excerpt_3[0]).casefold()
    touches_quote = set(ids) & {QUOTE_2_UNIT, *QUOTE_3_LEAD, *QUOTE_3_GROUP}
    if QUOTE_2_UNIT in ids:
        if ids != [QUOTE_2_UNIT] or normalized != quote_2:
            problems.append("REV 2:4 must be one exact quotation group")
    elif set(ids) & set(QUOTE_3_GROUP):
        if ids != list(QUOTE_3_GROUP) or normalized != quote_3:
            problems.append("REV 3:4 exact excerpt must occupy both trailing quote units together")
    elif ids == [QUOTE_3_LEAD[0]]:
        if not re.search(few_pattern, text, re.I) or quote_3 in normalized:
            problems.append("first speaker emphasis must say a few without using the exact quote")
    elif ids == [QUOTE_3_LEAD[1]]:
        if not re.search(not_many_pattern, text, re.I) or quote_3 in normalized:
            problems.append("second speaker emphasis must say not many without using the exact quote")
    elif touches_quote:
        problems.append("approved REV 3:4 source units were grouped across quote boundary")
    elif quote_2 in normalized or quote_3 in normalized:
        problems.append("exact edition quotation appeared outside approved source units")
    return not problems, "; ".join(problems) if problems else (
        f"Exact {edition} quotation boundary and excerpt hash passed for source-bound units; "
        "speaker repetition remains separate; full text review remains pending")


def review_scoped_locale_group(
    policy: dict, english_units: list[dict], group: dict, *, locale: str,
    required: list[str], edition: str, excerpt_2: tuple[str, str],
    excerpt_3: tuple[str, str], few_pattern: str, not_many_pattern: str,
    script_pattern: str, register_forbidden: str,
    names: dict[str, str], numbers: dict[str, tuple[str, ...]],
) -> list[dict[str, str]]:
    if (policy.get("targetLocale") != locale
            or policy.get("languageReview", {}).get("requiredChecks") != required):
        raise ValueError(f"{locale} plugin and policy checks differ")
    text = group["targetText"]
    english = " ".join(unit["english"] for unit in english_units)
    series_errors = explicit_series_errors(policy, english_units, text)
    natural_ok = bool(re.search(script_pattern, text)) and not series_errors
    natural_ok = natural_ok and not re.search(r"\b(?:TODO|TBD|PLACEHOLDER)\b", text, re.I)
    register_ok = not re.search(register_forbidden, text, re.I)
    name_errors = [source for source, target in names.items()
                   if re.search(r"\b" + re.escape(source) + r"\b", english, re.I)
                   and target.casefold() not in text.casefold()]
    if re.search(r"\b(?:Revelation chapter|book of Revelation)\b", english, re.I):
        book_name = "요한계시록" if locale == "ko" else "Apocalipsis"
        if book_name.casefold() not in text.casefold():
            name_errors.append("Revelation as a biblical book")
    if "Ian Duguid" in english:
        term = next((row for row in policy["terminology"]["properNames"]
                     if row["source"] == "Ian Duguid"), None)
        if (not term or term["reviewStatus"] == "pending"
                or not term["target"] or term["target"] not in text):
            name_errors.append("Ian Duguid: clip-scoped reviewed rendering missing")
    name_errors.extend(series_errors)
    missing_numbers = [number for number, forms in numbers.items()
                       if re.search(r"(?<!\w)" + re.escape(number) + r"(?!\w)", english, re.I)
                       and not any(form.casefold() in text.casefold() for form in forms)]
    scripture_ok, scripture_evidence = source_bound_scripture_review(
        policy, english_units, group, edition=edition,
        excerpt_2=excerpt_2, excerpt_3=excerpt_3,
        few_pattern=few_pattern, not_many_pattern=not_many_pattern,
    )
    first, second, third, fourth, fifth, sixth = required
    return [
        result(first, bool(natural_ok),
               "Script/explicit-series screen only; native fluency and complete meaning need human review"),
        result(second, register_ok,
               "Obvious register mismatch screen only; full register review remains human"),
        result(third, not name_errors,
               "Source-mentioned names and explicit series titles checked"
               + (f"; missing: {name_errors}" if name_errors else "")),
        result(fourth, scripture_ok, scripture_evidence),
        result(fifth, not missing_numbers,
               "Explicit numeral token screen only; spoken number reading remains human review"
               + (f"; missing: {missing_numbers}" if missing_numbers else "")),
        result(sixth, not has_unsafe_speech_markup(group["targetUtterances"]),
               "Structural utterance screen only; Layer 3 must test audio and prosody"),
    ]
