"""Chinese Layer 2 screen for the Sep 27 Drive sermon.

The eight Revelation references below are candidate locations, not approvals.
The production entry point fails the CUV check until a source-bound human
boundary receipt is embedded after review and this plugin is rehashed.
"""
from __future__ import annotations

import re
from functools import lru_cache

try:
    from scripts.cuv_scripture import CuvError, CuvLibrary
    from scripts.language_review_plugins.common import (
        explicit_series_errors, has_unsafe_speech_markup, result,
    )
except ImportError:  # Direct producer execution from scripts/.
    from cuv_scripture import CuvError, CuvLibrary
    from language_review_plugins.common import (
        explicit_series_errors, has_unsafe_speech_markup, result,
    )


PLUGIN_ID = "zh-Hans-weekly-cuv-v1"
PLUGIN_VERSION = "2026-09-27-boundary-review-pending-v1"
REQUIRED = ["spoken_chinese", "cuv_exact_quote", "number_name_reading", "tts_segmentation"]
CUV_EDITION_ID = "cmn-cu89s"

# Candidate scripture locations in the 31:31 Drive clip. This list grants no
# quote permission; every candidate needs a human direct/partial/paraphrase
# decision bound to the final English Source Package and anchor manifest.
CANDIDATE_VERSES = {
    "rev-4-2-3": {"REV 4:2", "REV 4:3", "REV 4:2-3"},
    "rev-4-8": {"REV 4:8"},
    "rev-4-10-11": {"REV 4:10", "REV 4:11", "REV 4:10-11"},
    "rev-5-1-4": {"REV 5:1", "REV 5:2", "REV 5:3", "REV 5:4", "REV 5:1-4"},
    "rev-5-5": {"REV 5:5"},
    "rev-5-6": {"REV 5:6"},
    "rev-5-9-10": {"REV 5:9", "REV 5:10", "REV 5:9-10"},
    "rev-5-12": {"REV 5:12"},
}

# Set this only from the user's review of the final anchor's eight boundaries.
# Required receipt fields are validated below. Its data becomes part of the
# plugin implementation hash; the current machine worksheet is insufficient.
APPROVED_BOUNDARY_REVIEW: dict | None = None


@lru_cache(maxsize=1)
def _library() -> CuvLibrary:
    return CuvLibrary.from_path()


def _approved_parts(policy: dict, approval: dict | None) -> tuple[dict[str, list[dict]], str]:
    """Validate a human receipt, then index its exact CUV fragments by unit."""
    scope = policy.get("sourceScope", {})
    if not isinstance(approval, dict) or approval.get("humanApproval") is not True:
        return {}, "No human-reviewed quote-boundary receipt is embedded"
    if (approval.get("decision") != "approved"
            or approval.get("approvedBy") != "user"
            or approval.get("englishSourcePackageJsonSha256")
            != scope.get("englishSourcePackageJsonSha256")
            or approval.get("anchorManifestJsonSha256")
            != scope.get("anchorManifestSha256")):
        return {}, "Human boundary receipt belongs to another source or is not approved"
    decisions = approval.get("decisions")
    if (not isinstance(decisions, list) or len(decisions) != len(CANDIDATE_VERSES)
            or {row.get("candidateId") for row in decisions if isinstance(row, dict)}
            != set(CANDIDATE_VERSES)):
        return {}, "Human boundary receipt does not decide all eight candidates"
    parts_by_unit: dict[str, list[dict]] = {}
    try:
        for decision in decisions:
            kind = decision["classification"]
            parts = decision["parts"]
            if kind not in {"direct_quote", "partial_direct_quote", "speaker_paraphrase"}:
                raise ValueError("unknown boundary classification")
            if not isinstance(parts, list) or (kind == "speaker_paraphrase") != (not parts):
                raise ValueError("quote parts do not match classification")
            allowed = CANDIDATE_VERSES[decision["candidateId"]]
            for part in parts:
                unit_id = part["sourceUnitId"]
                start, end = part["englishStart"], part["englishEnd"]
                reference, excerpt = part["reference"], part["cuvExcerpt"]
                if not all(isinstance(value, str) and value.strip()
                           for value in (unit_id, start, end, reference, excerpt)):
                    raise ValueError("empty approved boundary field")
                if reference not in allowed:
                    raise ValueError("scripture reference outside reviewed candidate")
                selected = _library().lookup(reference, excerpt=excerpt)
                if (selected["text"] != excerpt or selected["textSha256"]
                        != part["cuvExcerptSha256"]):
                    raise ValueError("approved excerpt differs from pinned CUV")
                parts_by_unit.setdefault(unit_id, []).append(part)
    except (CuvError, KeyError, TypeError, ValueError):
        return {}, "Human boundary receipt or pinned CUV excerpt is invalid"
    return parts_by_unit, "Human boundary receipt and pinned CUV excerpts match this source"


def _review_group(policy: dict, english_units: list[dict], group: dict,
                  approval: dict | None) -> list[dict[str, str]]:
    if (policy.get("targetLocale") != "zh-Hans"
            or policy.get("languageReview", {}).get("requiredChecks") != REQUIRED):
        raise ValueError("Chinese weekly CUV policy differs from plugin")
    source_scope = policy.get("sourceScope", {})
    scripture = policy.get("scripture", {})
    ids = [unit.get("sourceUnitId") for unit in english_units]
    english = " ".join(unit.get("english", "") for unit in english_units)
    text = group["targetText"]
    source_hash = source_scope.get("englishSourcePackageJsonSha256")
    anchor_hash = source_scope.get("anchorManifestSha256")
    source_bound = (
        isinstance(source_hash, str) and re.fullmatch(r"[a-f0-9]{64}", source_hash) is not None
        and isinstance(anchor_hash, str) and re.fullmatch(r"[a-f0-9]{64}", anchor_hash) is not None
        and group.get("englishSourcePackageJsonSha256") == source_hash
        and group.get("sourceUnitIds") == ids
        and bool(ids) and len(ids) == len(set(ids))
    )
    parts_by_unit, boundary_reason = _approved_parts(policy, approval)
    quote_ok = (source_bound and bool(parts_by_unit)
                and scripture.get("editionId") == CUV_EDITION_ID
                and scripture.get("citationUseStatus") == "project_source_reviewed"
                and scripture.get("quoteCheckPolicy") == "source_bound_exact_quote")
    if quote_ok:
        for unit in english_units:
            uttered = unit["english"]
            for part in parts_by_unit.get(unit["sourceUnitId"], []):
                start = uttered.find(part["englishStart"])
                end = uttered.find(part["englishEnd"], start)
                if (start < 0 or end < start
                        or text.count(part["cuvExcerpt"]) != 1):
                    quote_ok = False
                    boundary_reason = "Exact English span or CUV excerpt is missing or repeated"
                    break
            if not quote_ok:
                break
    if quote_ok:
        approved_here = {part["cuvExcerpt"] for unit_id in ids
                         for part in parts_by_unit.get(unit_id, [])}
        if any(excerpt in text and excerpt not in approved_here
               for parts in parts_by_unit.values() for excerpt in
               (part["cuvExcerpt"] for part in parts)
               if len(excerpt) >= 12):
            quote_ok = False
            boundary_reason = "CUV excerpt appears outside its approved English unit"
    series_errors = explicit_series_errors(policy, english_units, text)
    spoken_ok = bool(re.search(r"[\u3400-\u9fff]", text)) and not series_errors
    spoken_ok = spoken_ok and not re.search(r"\b(?:TODO|TBD|PLACEHOLDER)\b", text, re.I)
    missing_names = [term["source"] for term in policy["terminology"]["properNames"]
                     if term["source"].casefold() in english.casefold()
                     and (term["reviewStatus"] == "pending" or not term["target"]
                          or term["target"] not in text)]
    digits = re.findall(r"(?<!\w)(?:\d{1,3}(?:,\d{3})+|\d+)(?!\w)", english)
    lost_digits = [number for number in digits if number not in text]
    number_name_ok = not missing_names and not lost_digits
    # The CUV display text itself contains [圣] and [永]. Strip only bracket
    # tokens that occur inside an approved excerpt for the speech-markup screen;
    # other bracketed markup remains unsafe.
    approved_brackets = {match.group() for unit_id in ids
                         for part in parts_by_unit.get(unit_id, [])
                         for match in re.finditer(r"\[[^]]+\]", part["cuvExcerpt"])} if quote_ok else set()
    spoken_utterances = list(group["targetUtterances"])
    for bracket in approved_brackets:
        spoken_utterances = [utterance.replace(bracket, bracket[1:-1])
                             for utterance in spoken_utterances]
    return [
        result(REQUIRED[0], spoken_ok, "Han, placeholder, and explicit series-title screen only"),
        result(REQUIRED[1], quote_ok, boundary_reason if source_bound else
               "English Source Package or unit identity differs"),
        result(REQUIRED[2], bool(number_name_ok),
               "Only explicit digits and reviewed name forms checked; meaning needs Sol and human review"
               + (f"; missing digits: {lost_digits}" if lost_digits else "")
               + (f"; missing names: {missing_names}" if missing_names else "")),
        result(REQUIRED[3], not has_unsafe_speech_markup(spoken_utterances),
               "Markup and utterance length screen only; audio remains Layer 3"),
    ]


def review_group(policy: dict, english_units: list[dict], group: dict) -> list[dict[str, str]]:
    return _review_group(policy, english_units, group, APPROVED_BOUNDARY_REVIEW)
