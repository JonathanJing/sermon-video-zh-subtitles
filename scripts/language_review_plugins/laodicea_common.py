"""Deterministic reference-only screens for the approved Laodicea clip.

These checks do not establish native fluency, exact Bible edition wording, or
human translation approval. The full candidate must still be read by a human.
"""
from __future__ import annotations

import re

try:
    from scripts.language_review_plugins.common import (
        explicit_series_errors, has_unsafe_speech_markup, result,
    )
except ImportError:
    from language_review_plugins.common import (
        explicit_series_errors, has_unsafe_speech_markup, result,
    )


SOURCE_SHA256 = "4b674f74755e5268fb5356fc2b10184e41c68c357f899b43e1d0500ce53d4c27"


def review_reference_group(policy: dict, english_units: list[dict], group: dict,
                           *, locale: str, required: list[str], edition: str,
                           script_pattern: str, register_forbidden: str,
                           chapter_forms: tuple[str, ...], verse_forms: tuple[str, ...],
                           names: dict[str, tuple[str, ...]]) -> list[dict[str, str]]:
    if (policy.get("targetLocale") != locale
            or policy.get("languageReview", {}).get("requiredChecks") != required):
        raise ValueError(f"{locale} plugin and policy checks differ")
    ids = group["sourceUnitIds"]
    text = group["targetText"]
    english = " ".join(unit["english"] for unit in english_units)
    series_errors = explicit_series_errors(policy, english_units, text)
    natural = (bool(re.search(script_pattern, text)) and not series_errors
               and not re.search(r"\b(?:TODO|TBD|PLACEHOLDER)\b", text))
    register = not re.search(register_forbidden, text, re.I)
    name_errors = [name for name, forms in names.items()
                   if re.search(r"\b" + re.escape(name) + r"\b", english, re.I)
                   and not any(form.casefold() in text.casefold() for form in forms)]
    scripture = policy["scripture"]
    scripture_ok = (group.get("englishSourcePackageJsonSha256") == SOURCE_SHA256
                    and scripture["editionId"] == edition
                    and scripture["citationUseStatus"] == "project_source_reviewed"
                    and scripture["quoteCheckPolicy"] == "references_only"
                    and [unit.get("sourceUnitId") for unit in english_units] == ids)
    if "block-15-u002" in ids:
        scripture_ok = scripture_ok and any(form in text for form in chapter_forms)
        scripture_ok = scripture_ok and any(form in text for form in verse_forms)
    numbers_ok = True
    if re.search(r"\bchapter 3\b", english, re.I):
        numbers_ok = any(form in text for form in chapter_forms)
    if re.search(r"\bverse 16\b", english, re.I):
        numbers_ok = numbers_ok and any(form in text for form in verse_forms)
    segment_ok = not has_unsafe_speech_markup(group["targetUtterances"])
    evidence = ("Approved English Source Package and Revelation 3:16 reference-only policy checked; "
                "no exact edition quotation is asserted, full text review pending")
    if not scripture_ok:
        evidence = "Source package, edition, reference-only policy, or Revelation 3:16 reference differs"
    if locale == "zh-Hans":
        return [
            result(required[0], natural, "Han script and explicit-series screen only; human fluency review pending"),
            result(required[1], scripture_ok, evidence),
            result(required[2], numbers_ok and not name_errors,
                   "Explicit numerals and names only; spoken reading needs human review"
                   + (f"; missing names: {name_errors}" if name_errors else "")),
            result(required[3], segment_ok, "Structural utterance screen; audio and prosody remain Layer 3"),
        ]
    common = [
        result(required[0], natural, "Script and explicit-series screen only; human fluency review pending"),
        result(required[1], register, "Obvious register mismatch screen only"),
        result(required[2], not name_errors,
               "Source-mentioned names checked" + (f"; missing: {name_errors}" if name_errors else "")),
        result(required[3], scripture_ok, evidence),
        result(required[4], numbers_ok, "Explicit chapter/verse numerals only; spoken reading needs human review"),
        result(required[5], segment_ok, "Structural utterance screen; audio and prosody remain Layer 3"),
    ]
    return common
