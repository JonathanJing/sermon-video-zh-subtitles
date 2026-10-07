#!/usr/bin/env python3
"""Candidate-level machine text QC for a machine quality waiver.

Adds two checks the per-group plugin cannot make, then applies the same
per-sentence repair ladder as audio:

* **Length outliers.** Target/English length ratio against the candidate's own
  median, catching truncated or runaway groups regardless of locale.
* **Back-translation.** One call renders the target text back into English
  without seeing the source; a second call compares that with the frozen
  English and reports omissions, additions, negation, number, name, scripture
  and meaning shifts. The translator/reviewer chain never sees this path, so it
  adds independent evidence even when the same model family is used.

The model transport is injected (``call(role, system, user, schema) -> dict``)
so this module performs no network access itself and tests use fakes. It never
edits text and never grants human approval.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import unicodedata

from scripts.language_review_plugins import auto_qc_text_common as rules

SCHEMA = "sermon-target-text-auto-qc-v1"
TEXT_REPAIR_LADDER = ("revise_translation",) * 4
MAX_TEXT_REPAIR_ATTEMPTS = len(TEXT_REPAIR_LADDER)
LANGUAGE_NAMES = {"zh-Hans": "Simplified Chinese", "ko": "Korean", "es": "Spanish"}
ISSUE_KINDS = ("omission", "addition", "negation", "number", "name", "scripture_reference", "meaning_shift")
BACK_TRANSLATION_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["english"],
    "properties": {"english": {"type": "string"}},
}
COMPARISON_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["status", "issues"],
    "properties": {
        "status": {"enum": ["pass", "fail"]},
        "issues": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["kind", "severity", "english", "backTranslation"],
            "properties": {"kind": {"enum": list(ISSUE_KINDS)}, "severity": {"enum": ["major", "minor"]},
                           "english": {"type": "string"}, "backTranslation": {"type": "string"}}}},
    },
}
BACK_SYSTEM = ("You translate one passage of a church sermon from {language} into plain English. "
               "Translate exactly what is written. Do not add, omit, explain or correct anything, "
               "and keep numbers, names and Bible references exactly as written. "
               "You will not see the original English. Return JSON {{\"english\": ...}}.")
COMPARE_SYSTEM = ("Compare an ORIGINAL English sermon passage with an independent BACK-TRANSLATION "
                  "of its {language} rendering. Report only differences in meaning a listener would "
                  "notice: omission, addition, negation, number, name, scripture_reference, meaning_shift. "
                  "Ignore wording, word order, register and natural paraphrase. Severity is major when "
                  "a fact, claim, instruction or theological point changes; otherwise minor. "
                  "status is fail when any major issue exists. Return JSON matching the schema.")


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _length(text: str) -> int:
    return sum(1 for char in unicodedata.normalize("NFKC", text) if char.isalnum())


LENGTH_BOUNDS = {"low": 0.5, "high": 2.0, "minEnglishChars": 25}


def length_ratio(group: dict) -> float | None:
    english = _length(group["english"])
    return None if english < LENGTH_BOUNDS["minEnglishChars"] else _length(group["targetText"]) / english


def candidate_length_median(groups: list[dict]) -> float | None:
    ratios = [ratio for ratio in map(length_ratio, groups) if ratio is not None]
    return statistics.median(ratios) if len(ratios) >= 5 else None


def length_problem(group: dict, median: float | None) -> str | None:
    ratio = length_ratio(group)
    if median is None or ratio is None:
        return None
    relative = ratio / median
    if LENGTH_BOUNDS["low"] <= relative <= LENGTH_BOUNDS["high"]:
        return None
    return f"length ratio {relative:.2f}x candidate median"


def deterministic_problems(group: dict, locale: str, policy: dict | None) -> list[str]:
    english, text = group["english"], group["targetText"]
    pairs, _ = rules.english_references(english)
    problems = rules.script_problems(text, locale) + rules.untranslated_problems(english, text, locale)
    problems += rules.scripture_reference_problems(english, text, locale)
    problems += rules.number_problems(english, text, locale, pairs)
    if policy is not None:
        problems += rules.name_problems(policy, english, text)
    return problems


def back_translation_requests(group: dict, locale: str) -> dict:
    language = LANGUAGE_NAMES[locale]
    back = {"role": "back_translator", "system": BACK_SYSTEM.format(language=language),
            "user": group["targetText"], "schema": BACK_TRANSLATION_SCHEMA}
    return {"backTranslation": back, "backTranslationRequestSha256": _sha(back)}


def comparison_request(group: dict, locale: str, back_translation: str) -> dict:
    request = {"role": "back_translation_judge",
               "system": COMPARE_SYSTEM.format(language=LANGUAGE_NAMES[locale]),
               "user": json.dumps({"ORIGINAL": group["english"], "BACK-TRANSLATION": back_translation},
                                  ensure_ascii=False),
               "schema": COMPARISON_SCHEMA}
    return {**request, "requestSha256": _sha(request)}


def validate_comparison(value: dict) -> dict:
    if (not isinstance(value, dict) or set(value) != {"status", "issues"}
            or value["status"] not in {"pass", "fail"} or not isinstance(value["issues"], list)):
        raise ValueError("Back-translation comparison does not match its schema")
    for issue in value["issues"]:
        if (not isinstance(issue, dict) or set(issue) != {"kind", "severity", "english", "backTranslation"}
                or issue["kind"] not in ISSUE_KINDS or issue["severity"] not in {"major", "minor"}):
            raise ValueError("Back-translation comparison issue does not match its schema")
    major = [issue for issue in value["issues"] if issue["severity"] == "major"]
    # A judge cannot pass a group while reporting a major meaning change.
    return {"status": "fail" if major or value["status"] == "fail" else "pass",
            "majorIssues": major, "minorIssues": [i for i in value["issues"] if i["severity"] == "minor"]}


def back_translate(group: dict, locale: str, call) -> dict:
    requests = back_translation_requests(group, locale)
    back = requests["backTranslation"]
    output = call(back["role"], back["system"], back["user"], back["schema"])
    if not isinstance(output, dict) or set(output) != {"english"} or not isinstance(output["english"], str) \
            or not output["english"].strip():
        raise ValueError("Back-translation output does not match its schema")
    compare = comparison_request(group, locale, output["english"])
    verdict = validate_comparison(call(compare["role"], compare["system"], compare["user"], compare["schema"]))
    return {"backTranslation": output["english"],
            "requestSha256s": [requests["backTranslationRequestSha256"], compare["requestSha256"]],
            **verdict}


def group_problems(group: dict, locale: str, *, policy: dict | None, median: float | None,
                   call=None) -> tuple[list[str], dict | None]:
    problems = deterministic_problems(group, locale, policy)
    length = length_problem(group, median)
    if length:
        problems.append(length)
    semantic = back_translate(group, locale, call) if call is not None else None
    if semantic is not None and semantic["status"] == "fail":
        problems += [f"back_translation {issue['kind']}: {issue['english']} -> {issue['backTranslation']}"
                     for issue in semantic["majorIssues"]] or ["back_translation judge failed"]
    return problems, semantic


def screen(groups: list[dict], locale: str, *, policy: dict | None = None, call=None,
           prior_failed_attempts: dict[str, int] | None = None) -> dict:
    """Screen a whole candidate. ``groups``: ``[{groupId, english, targetText}]``.

    Without ``call`` the back-translation result is ``not_run`` and the group
    cannot reach ``pass``: semantic evidence is required for a waiver.
    """
    if locale not in LANGUAGE_NAMES:
        raise ValueError(f"Unsupported locale: {locale}")
    prior = prior_failed_attempts or {}
    median = candidate_length_median(groups)
    results = []
    for group in groups:
        problems, semantic = group_problems(group, locale, policy=policy, median=median, call=call)
        failed = prior.get(group["groupId"], 0)
        if problems:
            status = "fail"
            action = TEXT_REPAIR_LADDER[failed] if failed < MAX_TEXT_REPAIR_ATTEMPTS else "source_text_fallback"
            failed += 1
        elif semantic is None:
            status, action = "pending_back_translation", "run_back_translation"
        else:
            status, action = "pass", "keep"
        results.append({"groupId": group["groupId"], "status": status, "problems": problems,
                        "backTranslation": semantic, "failedAttempts": failed, "nextAction": action,
                        "targetTextSha256": hashlib.sha256(group["targetText"].encode("utf-8")).hexdigest()})
    return {"schemaVersion": SCHEMA, "locale": locale, "maxRepairAttempts": MAX_TEXT_REPAIR_ATTEMPTS,
            "lengthBounds": LENGTH_BOUNDS, "candidateLengthMedian": median,
            "status": "pass" if all(r["status"] == "pass" for r in results) else "requires_repair",
            "repairGroupIds": [r["groupId"] for r in results if r["nextAction"] == "revise_translation"],
            "sourceTextFallbackGroupIds": [r["groupId"] for r in results
                                           if r["nextAction"] == "source_text_fallback"],
            "results": results, "humanApproval": False, "mutatesText": False}
