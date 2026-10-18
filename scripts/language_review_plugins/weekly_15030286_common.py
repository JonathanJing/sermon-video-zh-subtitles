"""Source-bound deterministic screens for Resi media 15030286.

The frozen source split ``$1.5 million`` across two adjacent units.  Layer 2
must render the amount exactly once: the first unit carries the complete
amount and the second continues with the external firm.  The Spanish source
also names the official ``Seek the Good`` campaign in English; those exact
bound units may preserve the official title while all surrounding prose still
passes the ordinary untranslated-English screen. Official title evidence:
https://www.marinerschurch.org/seekthegood/
"""
from __future__ import annotations

import re

try:
    from scripts.language_review_plugins.auto_qc_text_common import (
        REQUIRED, added_number_problems, number_problems, result,
        review_auto_group, untranslated_problems,
    )
except ImportError:
    from language_review_plugins.auto_qc_text_common import (
        REQUIRED, added_number_problems, number_problems, result,
        review_auto_group, untranslated_problems,
    )


SOURCE_SHA256 = "137fed8486da0ec4ea22258035a230f30172be43a016faa4c382b410f830e3a9"
AMOUNT_LEAD = ("chunk-0000-u024", "And in fact, reports said that Calendly, they spent $1.")
AMOUNT_TAIL = ("chunk-0000-u025", "5 million on an external firm to design that logo.")
SEEK_THE_GOOD = {
    "chunk-0007-u015": "The bar is low, which, by the way, this is another reason why I love the Seek the Good season.",
    "chunk-0007-u017": "So I want to invite you, all of us across all of our congregations, to engage with Seek the Good.",
}


def _amount_present(text: str, locale: str) -> bool:
    patterns = {
        "es": r"(?:\$\s*)?\d|\b(?:un|uno|cinco)\b.{0,20}\bmill[oó]n(?:es)?\b|\bmill[oó]n(?:es)?\b|\bd[oó]lares?\b",
        "ko": r"\d|(?:백오십|오백|일점오)\s*만|달러",
        "zh-Hans": r"\d|[零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟萬億]+(?:点[零〇一二两三四五六七八九]+)?|美元",
    }
    return re.search(patterns[locale], text, re.I) is not None


def _amount_problems(locale: str, unit_id: str, english: str, target: str) -> list[str] | None:
    if (unit_id, english) == AMOUNT_LEAD:
        expected = "They spent 1.5 million dollars."
        return number_problems(expected, target, locale) + added_number_problems(expected, target, locale)
    if (unit_id, english) == AMOUNT_TAIL:
        return (["$1.5 million must be rendered once in the preceding bound unit, not repeated here"]
                if _amount_present(target, locale) else [])
    return None


def review_15030286_group(policy: dict, english_units: list[dict], group: dict, *,
                          locale: str, forbidden_register: str) -> list[dict[str, str]]:
    if group.get("englishSourcePackageJsonSha256") != SOURCE_SHA256:
        raise ValueError("15030286 plugin source package differs")
    reviews = review_auto_group(
        policy, english_units, group, locale=locale, forbidden_register=forbidden_register)
    if len(english_units) != 1:
        return reviews
    unit_id, english = english_units[0]["sourceUnitId"], english_units[0]["english"]
    target = group["targetText"]
    amount = _amount_problems(locale, unit_id, english, target)
    if amount is not None:
        reviews = [
            result("numbers", not amount,
                   "Source-bound $1.5 million spans u024/u025 and must be rendered exactly once"
                   + ("; " + "; ".join(amount) if amount else "; pass"))
            if row["checkId"] == "numbers" else row for row in reviews]
    if locale == "es" and SEEK_THE_GOOD.get(unit_id) == english:
        masked_english = english.replace("Seek the Good", "")
        masked_target = target.replace("Seek the Good", "")
        problems = ([] if "Seek the Good" in target else ["official title Seek the Good missing"])
        problems += untranslated_problems(masked_english, masked_target, "es")
        reviews = [
            result("untranslated_source", not problems,
                   "Official source-bound campaign title may remain Seek the Good; surrounding prose checked"
                   + ("; " + "; ".join(problems) if problems else "; pass"))
            if row["checkId"] == "untranslated_source" else row for row in reviews]
    return reviews
