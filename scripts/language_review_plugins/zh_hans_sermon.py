"""Source-bound Chinese screen for the approved Sep 20 sermon fragment.

Only the two approved CUV quotation boundaries are recognized. This is a
deterministic screen, not a native speaker's content, cadence, or audio review.
Future source packages need their own approved quotation map and plugin version.
"""
from __future__ import annotations

import hashlib
import re

try:
    from scripts.language_review_plugins.common import (
        explicit_series_errors, has_unsafe_speech_markup, normalized_quote, result,
    )
except ImportError:  # Direct scripts/produce_target_language_candidate.py execution.
    from language_review_plugins.common import (
        explicit_series_errors, has_unsafe_speech_markup, normalized_quote, result,
    )

PLUGIN_ID = "zh-Hans-sermon-v1"
PLUGIN_VERSION = "2026-09-20-source-bound-v1"
SOURCE_SHA256 = "4d645ff0aad0b55b2eb913fd0749ebcb3bed010ddfc037e89e1f8a98f44a227b"
CUV_SOURCE_CONTENT_SHA256 = "9c43dacae44a16ce5fb56bb42ba3afde9f8facfe1eaf1b9ebba6a9b76c8cb80f"
APPROVED_EXCERPTS = {
    "REV 2:4": ("你把起初的爱心离弃了", "7384f60a9c169425d4ceaa023f3d3c5d53bf0638d765d809798b324a98938cd4"),
    "REV 3:4": ("你还有几名是未曾污秽自己衣服的", "0da72b6ff0332c5ab2ee4cd73ad5220fb0e5292ac7deab1e201dd16f20eae231"),
}

# These are pieces of the exact excerpts approved for REV 2:4 and REV 3:4.
# The speaker's repetitions remain separate; no ordinary paraphrase is replaced.
QUOTED_UNITS = {
    "block-12-u002": ("You've abandoned the love you had at first.", "你把起初的爱心离弃了"),
    "block-14-u002": ("There's just a few of you.", "你还有几名"),
    "block-14-u003": ("Who have not defiled their clothes.", "是未曾污秽自己衣服的"),
}
PARAPHRASE_UNITS = {
    "block-12-u004": "你把起初的爱心离弃了",
    "block-14-u013": "你还有几名是未曾污秽自己衣服的",
}
ENGLISH_NUMBERS = {
    "three": ("三", "3"), "seven": ("七", "7"),
    "five": ("五", "5"), "two": ("二", "两", "2"),
    "2": ("二", "两", "2"), "3": ("三", "3"),
    "4": ("四", "4"),
    "44": ("四十四", "44"),
}


def review_group(policy: dict, english_units: list[dict], group: dict) -> list[dict[str, str]]:
    required = ["spoken_chinese", "cuv_exact_quote", "number_name_reading", "tts_segmentation"]
    if policy.get("targetLocale") != "zh-Hans" or policy.get("languageReview", {}).get("requiredChecks") != required:
        raise ValueError("Chinese plugin and policy checks differ")
    source_ok = group.get("englishSourcePackageJsonSha256") == SOURCE_SHA256
    ids = group["sourceUnitIds"]
    text = group["targetText"]
    quote_units = set(ids) & set(QUOTED_UNITS)
    scripture = policy["scripture"]
    excerpt_hashes_valid = all(hashlib.sha256(excerpt.encode("utf-8")).hexdigest() == digest
                               for excerpt, digest in APPROVED_EXCERPTS.values())
    excerpt_parts_valid = (QUOTED_UNITS["block-12-u002"][1] == APPROVED_EXCERPTS["REV 2:4"][0]
                           and QUOTED_UNITS["block-14-u002"][1]
                           + QUOTED_UNITS["block-14-u003"][1] == APPROVED_EXCERPTS["REV 3:4"][0])
    quote_ok = (source_ok and scripture["editionId"] == "CUV"
                and scripture["citationUseStatus"] == "project_source_reviewed"
                and scripture["quoteCheckPolicy"] == "source_bound_exact_quote"
                and excerpt_hashes_valid and excerpt_parts_valid
                and bool(english_units) and len(english_units) == len(ids))
    quote_reason = ("Approved CUV quote boundary checked against source unit and exact excerpt; "
                    f"pinned corpus content SHA256 {CUV_SOURCE_CONTENT_SHA256}")
    if quote_units:
        # A quotation mixed with speaker commentary cannot be proven by a
        # group-level target string. Require one source unit per quote group.
        quote_ok = quote_ok and len(ids) == 1 and ids[0] in QUOTED_UNITS
        if quote_ok:
            english, exact = QUOTED_UNITS[ids[0]]
            quote_ok = english_units[0]["english"] == english and normalized_quote(text) == exact
        quote_reason = ("Direct CUV quote must occupy its approved source unit exactly; "
                        f"pinned corpus content SHA256 {CUV_SOURCE_CONTENT_SHA256}")
    if any(unit_id in PARAPHRASE_UNITS for unit_id in ids):
        for unit_id in ids:
            if unit_id in PARAPHRASE_UNITS and normalized_quote(text) == PARAPHRASE_UNITS[unit_id]:
                quote_ok = False
                quote_reason = "Speaker paraphrase must not be relabeled as an exact CUV quote"
    if not quote_units and any(normalized_quote(utterance) in (
            "你把起初的爱心离弃了", "你还有几名是未曾污秽自己衣服的")
            for utterance in group["targetUtterances"]):
        quote_ok = False
        quote_reason = "Exact CUV quotation appeared outside the approved source boundary"

    series_errors = explicit_series_errors(policy, english_units, text)
    spoken_ok = bool(re.search(r"[\u3400-\u9fff]", text)) and not series_errors
    spoken_ok = spoken_ok and not re.search(r"\b(?:TODO|TBD|PLACEHOLDER)\b", text, re.I)
    english = " ".join(unit["english"] for unit in english_units)
    missing_numbers = [number for number, forms in ENGLISH_NUMBERS.items()
                       if re.search(r"(?<!\w)" + re.escape(number) + r"(?!\w)", english, re.I)
                       and not any(form in text for form in forms)]
    missing_names = [name for name in ("Ian Duguid",)
                     if name in english and not any(
                         term["source"] == name and term["reviewStatus"] != "pending"
                         and term["target"] and term["target"] in text
                         for term in policy["terminology"]["properNames"])]
    number_ok = not missing_numbers and not missing_names and not re.search(r"\[[^]]+\]", text)
    segments_ok = not has_unsafe_speech_markup(group["targetUtterances"])
    return [
        result("spoken_chinese", spoken_ok,
               "Deterministic Han/explicit-series screen only; human fluency review remains pending"
               + (f"; missing series title: {series_errors}" if series_errors else "")),
        result("cuv_exact_quote", quote_ok, quote_reason if source_ok else
               "No approved CUV quote map for this English Source Package hash"),
        result("number_name_reading", bool(number_ok),
               "Explicit numeral token screen only; names and spoken reading need human review"
               + (f"; missing numerals: {missing_numbers}" if missing_numbers else "")
               + (f"; unreviewed names: {missing_names}" if missing_names else "")),
        result("tts_segmentation", segments_ok,
               "No markup, control characters, empty or oversized utterances; prosody requires Layer 3 review"),
    ]
