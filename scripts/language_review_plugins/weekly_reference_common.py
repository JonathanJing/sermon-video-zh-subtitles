"""Structural screens for source-bound, reference-only sermon translations.

These checks do not establish translation accuracy, Bible wording, or native
fluency. The independent model reviewer and full human text review remain
mandatory. A policy binds the exact English package and approved terms.
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


def review_reference_only_group(
    policy: dict, english_units: list[dict], group: dict, *,
    locale: str, required: list[str], script_pattern: str,
    forbidden_register: str, forbidden_edition_claim: str,
) -> list[dict[str, str]]:
    if (policy.get("targetLocale") != locale
            or policy.get("languageReview", {}).get("requiredChecks") != required):
        raise ValueError(f"{locale} weekly reference-only policy differs from plugin")
    text = group["targetText"]
    english = " ".join(unit["english"] for unit in english_units)
    ids = [unit.get("sourceUnitId") for unit in english_units]
    scope = policy.get("sourceScope", {})
    scripture = policy["scripture"]
    source_hash = scope.get("englishSourcePackageJsonSha256")
    source_bound = (
        isinstance(source_hash, str)
        and re.fullmatch(r"[a-f0-9]{64}", source_hash) is not None
        and group.get("englishSourcePackageJsonSha256") == source_hash
        and group.get("sourceUnitIds") == ids
        and bool(ids) and len(ids) == len(set(ids))
    )
    reference_only = (
        source_bound and scripture.get("editionId") is None
        and scripture.get("citationUseStatus") == "project_source_reviewed"
        and scripture.get("quoteCheckPolicy") == "references_only"
        and not re.search(forbidden_edition_claim, text, re.I)
    )
    series_errors = explicit_series_errors(policy, english_units, text)
    marker = bool(re.search(r"\b(?:TODO|TBD|PLACEHOLDER)\b", text))
    natural_screen = bool(re.search(script_pattern, text)) and not marker and not series_errors
    register_screen = not re.search(forbidden_register, text, re.I)
    missing_names = [
        term["source"] for term in policy["terminology"]["properNames"]
        if term["source"].casefold() in english.casefold()
        and (term["reviewStatus"] == "pending" or not term["target"]
             or term["target"].casefold() not in text.casefold())
    ]
    # Numeral and scripture meaning are reviewed by Sol and the human reader.
    # This deterministic check catches only a lost explicit Arabic numeral.
    numerals = re.findall(r"(?<!\w)\d+(?!\w)", english)
    lost_digits = [number for number in numerals if number not in text]
    segmentation_screen = not has_unsafe_speech_markup(group["targetUtterances"])
    evidence = ("Exact English package/unit identity and reference-only policy checked; "
                "no edition quotation is claimed; semantic accuracy and citation display await full review")
    if not reference_only:
        evidence = "Source identity, reference-only policy, or no-edition claim differs"
    return [
        result(required[0], natural_screen,
               "Target script, placeholder, and explicit series-title screen only; native fluency needs human review"),
        result(required[1], register_screen,
               "Obvious register mismatch screen only; nuance needs human review"),
        result(required[2], not missing_names,
               "Policy-bound source-mentioned names checked" +
               (f"; missing reviewed forms: {missing_names}" if missing_names else "")),
        result(required[3], reference_only, evidence),
        result(required[4], not lost_digits,
               "Arabic numeral preservation screen only; spoken number meaning needs Sol and human review" +
               (f"; missing explicit digits: {lost_digits}" if lost_digits else "")),
        result(required[5], segmentation_screen,
               "Utterance markup and length screen; audio and prosody remain Layer 3"),
    ]
