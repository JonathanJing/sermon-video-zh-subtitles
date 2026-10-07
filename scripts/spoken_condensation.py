#!/usr/bin/env python3
"""Condense over-window spoken groups the way a simultaneous interpreter would.

Jony's 2026-10-07 decision: when a group's dub cannot end within the 8-second
lag target, the spoken script may drop redundancy. Subtitles and the reading
text keep the complete translation. Only groups the pre-TTS budget
(``target_audio_predicted_schedule.budget``) marks ``shorten`` are condensed.

A condensation may drop repetition, filler, restatement, asides and example
detail. It may not drop the main claim, a call or command, a negation, a
number, a name, a scripture reference or a quotation's speaker, and it may not
add anything. Every omission is declared as a span of the full translation
with its kind. Numbers, names and scripture references go through the same
deterministic checks as the full translation, and the spoken text must fit
the group's ``maxSpeechUnits``.

The model transport is injected (``call(role, system, user, schema) -> dict``),
so this module performs no network access and tests use fakes. Its record
exports a ``sermon-target-language-group-revision-brief-v1`` whose
``proposedTargetText`` feeds the normal Layer 2 chain
(``run_target_language_models.py --revision-brief``); the spoken candidate
that chain produces is then bound back with ``bind_spoken_candidate``, and
``qc_groups`` marks its condensed groups for the core-meaning text QC. Nothing
here edits the full candidate or grants approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import machine_quality_waiver as waiver
from scripts import target_audio_predicted_schedule as predicted
from scripts import target_text_auto_qc as text_qc
from scripts.language_review_plugins import auto_qc_text_common as rules

SCHEMA = "sermon-spoken-condensation-record-v1"
# v2 records the QC implementation that rechecked the spoken text; a waiver
# accepts only a binding checked by its own implementation.
BINDING_SCHEMA = "sermon-spoken-condensation-binding-v2"
REVISION_BRIEF_SCHEMA = "sermon-target-language-group-revision-brief-v1"
PROMPT_VERSION = "spoken-condensation-v1"
OMISSION_KINDS = ("repetition", "filler", "restatement", "aside", "example_detail")
MAX_ATTEMPTS = 2
LANGUAGE_NAMES = text_qc.LANGUAGE_NAMES
RESULT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["translationGroupId", "spokenText", "omissions"],
    "properties": {
        "translationGroupId": {"type": "string"},
        "spokenText": {"type": "string"},
        "omissions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["fullTextSpan", "kind"],
            "properties": {"fullTextSpan": {"type": "string"}, "kind": {"enum": list(OMISSION_KINDS)}}}},
    },
}
SYSTEM = ("You are a simultaneous interpreter preparing the {language} dub of a church sermon. "
          "The full {language} translation of this passage is too long for its time slot. "
          "Rewrite it as a shorter spoken version of at most {limit} speech units ({unit}). "
          "You may drop repetition, filler, restatement, asides and example detail. "
          "Keep the main claim, every call or command to the listeners, every negation, number, "
          "name and Bible reference, and who is quoted. Do not add anything that is not in the "
          "full translation. Keep the speaker's voice and register. "
          "List every dropped span exactly as it appears in the full translation, with its kind "
          "(repetition, filler, restatement, aside, example_detail). Return JSON matching the schema.")
UNIT_NAMES = {"zh-Hans": "Han characters", "ko": "Hangul syllables", "es": "syllables"}
# Rewording may shorten the kept text a little; beyond this the removal must be declared.
UNDECLARED_SLACK_UNITS, UNDECLARED_SLACK_SHARE = 3, 0.1


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def implementation_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def condenser_identity(identity: dict) -> dict:
    """The condensation runtime recorded with its hash.

    Held to the back-translation identity's standard: backend, model,
    modelRevision, cacheNamespace and non-empty settings, frozen as finite
    JSON, so another revision or decoding setup is another runtime.
    """
    message = "Condenser identity needs backend, model, modelRevision, cacheNamespace and settings as finite JSON"
    if not isinstance(identity, dict):
        raise ValueError(message)
    try:
        return text_qc.semantic_identity(identity)
    except ValueError as error:
        raise ValueError(message) from error


def requests(anchor: dict, candidate: dict, budget: dict) -> dict:
    """The condensation requests for one full candidate and its pre-TTS budget.

    The budget must have been computed from this candidate's own texts, in its
    group order; each request carries the English units the group covers.
    """
    locale = candidate.get("targetLocale")
    if locale not in LANGUAGE_NAMES or budget.get("locale") != locale:
        raise ValueError("Candidate and budget must share a supported locale")
    if budget.get("schemaVersion") != predicted.SCHEMA:
        raise ValueError("Unsupported pre-TTS budget")
    if candidate.get("anchorManifestSha256") != _sha(anchor):
        raise ValueError("Anchor manifest differs from the candidate's")
    english = {unit["sourceUnitId"]: unit["english"] for unit in anchor["sourceUnits"]}
    groups, planned = candidate["groups"], budget["groups"]
    if [row["gid"] for row in planned] != [group["translationGroupId"] for group in groups]:
        raise ValueError("Budget groups differ from the candidate's groups")
    out, cannot_fit = [], []
    for group, row in zip(groups, planned):
        if row["speechUnits"] != predicted.speech_units(group["targetText"], locale):
            raise ValueError(f"Budget was computed from other text: {group['translationGroupId']}")
        if row["action"] == "cannot_fit":
            cannot_fit.append(group["translationGroupId"])
        if row["action"] != "shorten":
            continue
        out.append({"translationGroupId": group["translationGroupId"], "sourceUnitIds": group["sourceUnitIds"],
                    "englishUnits": [{"sourceUnitId": unit_id, "english": english[unit_id]}
                                     for unit_id in group["sourceUnitIds"]],
                    "fullTargetText": group["targetText"], "fullSpeechUnits": row["speechUnits"],
                    "maxSpeechUnits": row["maxSpeechUnits"], "allowedSeconds": row["allowedSeconds"]})
    frozen = frozen_timing_problems(anchor, candidate, budget)
    if frozen:
        raise ValueError("Budget does not follow from the frozen source timing: " + "; ".join(frozen))
    return {"targetLocale": locale, "requests": out, "cannotFitGroupIds": cannot_fit}


TIMING_TOLERANCE_SECONDS = 0.001


def frozen_timing_problems(anchor: dict, candidate: dict, budget: dict) -> list[str]:
    """The budget's clip-relative source times must be the anchor's, shifted by one
    clip offset, and its actions and limits must follow from them and these texts."""
    units = {unit["sourceUnitId"]: unit for unit in anchor["sourceUnits"]}
    offsets = []
    for group, row in zip(candidate["groups"], budget["groups"]):
        first, last = units[group["sourceUnitIds"][0]], units[group["sourceUnitIds"][-1]]
        if not all(isinstance(unit.get(key), (int, float)) for unit in (first, last) for key in ("start", "end")):
            return [f"{group['translationGroupId']}: anchor lacks source timing"]
        if not all(isinstance(row.get(key), (int, float)) for key in ("sourceStart", "sourceEnd")):
            return [f"{group['translationGroupId']}: budget lacks source timing"]
        offsets.append(float(first["start"]) - row["sourceStart"])
        if abs((float(last["end"]) - float(first["start"])) - (row["sourceEnd"] - row["sourceStart"])) \
                > TIMING_TOLERANCE_SECONDS:
            return [f"{group['translationGroupId']}: source span differs from the anchor"]
    if max(offsets) - min(offsets) > TIMING_TOLERANCE_SECONDS:
        return ["groups are shifted by different clip offsets"]
    try:
        rebuilt = predicted.budget(
            budget["sourceSeconds"],
            [{"gid": group["translationGroupId"], "sourceStart": row["sourceStart"],
              "sourceEnd": row["sourceEnd"], "text": group["targetText"]}
             for group, row in zip(candidate["groups"], budget["groups"])],
            budget["rate"], budget["policy"], synthesis_identity=budget["rate"]["synthesisIdentity"],
            target_end_lag_seconds=budget["targetEndLagSeconds"])
    except (KeyError, TypeError, ValueError) as error:
        return [f"budget cannot be recomputed: {error}"]
    return [] if rebuilt == budget else ["actions or limits differ from a recomputed budget"]


def prompt(request: dict, locale: str, problems: list[str] | None = None) -> dict:
    system = SYSTEM.format(language=LANGUAGE_NAMES[locale], limit=request["maxSpeechUnits"],
                           unit=UNIT_NAMES[locale])
    user = {"translationGroupId": request["translationGroupId"],
            "english": " ".join(unit["english"] for unit in request["englishUnits"]),
            "fullTranslation": request["fullTargetText"], "maxSpeechUnits": request["maxSpeechUnits"]}
    if problems:
        user["previousAttemptProblems"] = problems
    return {"system": system, "user": json.dumps(user, ensure_ascii=False), "schema": RESULT_SCHEMA}


def spoken_problems(request: dict, spoken: str, omissions: list[dict] | None, locale: str,
                    policy: dict | None) -> list[str]:
    """Deterministic checks of one condensed spoken text against its request."""
    problems = []
    if not isinstance(spoken, str) or not spoken.strip():
        return ["spoken text is empty"]
    if spoken.strip() == request["fullTargetText"].strip():
        problems.append("spoken text is the full translation")
    units = predicted.speech_units(spoken, locale)
    if units > request["maxSpeechUnits"]:
        problems.append(f"{units:g} speech units exceed the budget of {request['maxSpeechUnits']}")
    if not isinstance(omissions, list):
        problems.append("omissions must be declared as a list")
    else:
        if not omissions:
            problems.append("no omissions declared")
        full, declared, claimed = request["fullTargetText"], 0.0, []
        for omission in omissions:
            span = omission.get("fullTextSpan") if isinstance(omission, dict) else None
            if not (isinstance(span, str) and span.strip() and span in full):
                problems.append(f"omission is not a span of the full translation: {span!r}")
            elif omission.get("kind") not in OMISSION_KINDS:
                problems.append(f"omission kind not allowed: {omission.get('kind')!r}")
            elif spoken.count(span) >= full.count(span):
                problems.append(f"declared omission is still in the spoken text: {span!r}")
            else:
                # Each declaration claims its own removed occurrence: one filler listed
                # twice, or spans that overlap, cannot add up to cover another cut.
                removed_count = full.count(span) - spoken.count(span)
                starts = [match.start() for match in re.finditer("(?=" + re.escape(span) + ")", full)]
                free = [start for start in starts
                        if all(start + len(span) <= left or start >= right for left, right in claimed)]
                if not free or sum(full[left:right] == span for left, right in claimed) >= removed_count:
                    problems.append(f"omission declared twice or overlapping another: {span!r}")
                else:
                    claimed.append((free[0], free[0] + len(span)))
                    declared += predicted.speech_units(span, locale)
        # The declared spans must account for what was removed; an undeclared cut
        # (a call, an attribution) cannot hide behind an unrelated declared span.
        removed = predicted.speech_units(full, locale) - units
        slack = max(UNDECLARED_SLACK_UNITS, UNDECLARED_SLACK_SHARE * predicted.speech_units(full, locale))
        if not problems and removed > declared + slack:
            problems.append(f"{removed:g} speech units removed but only {declared:g} declared")
    group = {"english": " ".join(unit["english"] for unit in request["englishUnits"]), "targetText": spoken}
    problems += text_qc.deterministic_problems(group, locale, policy)
    return problems


def _condense_one(request: dict, locale: str, policy: dict | None, call) -> dict:
    problems: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        asked = prompt(request, locale, problems)
        output = call("condenser", asked["system"], asked["user"], asked["schema"])
        if (not isinstance(output, dict) or set(output) != set(RESULT_SCHEMA["required"])
                or output.get("translationGroupId") != request["translationGroupId"]
                or not isinstance(output.get("omissions"), list)):
            problems = ["condenser output does not match the schema"]
            continue
        problems = spoken_problems(request, output["spokenText"], output["omissions"], locale, policy)
        if not problems:
            return {"status": "condensed", "attempts": attempt, "spokenText": output["spokenText"],
                    "spokenSpeechUnits": predicted.speech_units(output["spokenText"], locale),
                    "omissions": [{"fullTextSpan": row["fullTextSpan"], "kind": row["kind"]}
                                  for row in output["omissions"]], "problems": []}
    return {"status": "failed", "attempts": MAX_ATTEMPTS, "spokenText": None, "spokenSpeechUnits": None,
            "omissions": [], "problems": problems}


def condense(anchor: dict, candidate: dict, budget: dict, *, call, identity: dict,
             policy: dict | None = None) -> dict:
    """Condense every ``shorten`` group. A group still failing after
    ``MAX_ATTEMPTS`` stays ``failed``: its spoken text remains the full
    translation and the dub falls back to subtitles for it."""
    asked = requests(anchor, candidate, budget)
    locale = asked["targetLocale"]
    runtime = condenser_identity(identity)
    groups = []
    for request in asked["requests"]:
        result = _condense_one(request, locale, policy, call)
        groups.append({"translationGroupId": request["translationGroupId"],
                       "sourceUnitIds": request["sourceUnitIds"],
                       "fullTargetTextSha256": _text_sha(request["fullTargetText"]),
                       "fullSpeechUnits": request["fullSpeechUnits"],
                       "maxSpeechUnits": request["maxSpeechUnits"], **result})
    failed = [row["translationGroupId"] for row in groups if row["status"] == "failed"]
    return {"schemaVersion": SCHEMA, "targetLocale": locale,
            "status": "condensed" if not failed else "condensed_with_failures",
            "englishSourcePackageJsonSha256": candidate["englishSourcePackageJsonSha256"],
            "anchorManifestSha256": candidate["anchorManifestSha256"],
            "translationPolicySha256": candidate["translationPolicySha256"],
            "fullCandidateJsonSha256": _sha(candidate), "budgetJsonSha256": _sha(budget),
            "synthesisIdentity": budget["rate"]["synthesisIdentity"],
            "condenserIdentity": runtime["identity"], "condenserIdentitySha256": runtime["sha256"],
            "promptVersion": PROMPT_VERSION, "implementationSha256": implementation_sha256(),
            "groups": groups, "failedGroupIds": failed, "cannotFitGroupIds": asked["cannotFitGroupIds"],
            "modelCalls": sum(row["attempts"] for row in groups),
            "humanApproval": False, "mutatesFullCandidate": False}


def _check_record(record: dict, candidate: dict) -> None:
    if record.get("schemaVersion") != SCHEMA or record.get("humanApproval") is not False:
        raise ValueError("Unsupported condensation record")
    if record.get("fullCandidateJsonSha256") != _sha(candidate):
        raise ValueError("Condensation record belongs to another full candidate")


def revision_brief(record: dict, candidate: dict) -> dict:
    """The Layer 2 revision brief for the condensed groups; failed groups keep the full text."""
    _check_record(record, candidate)
    condensed = [row for row in record["groups"] if row["status"] == "condensed"]
    if not condensed:
        raise ValueError("No condensed group to brief")
    return {"schemaVersion": REVISION_BRIEF_SCHEMA, "targetLocale": record["targetLocale"],
            "englishSourcePackageJsonSha256": record["englishSourcePackageJsonSha256"],
            "anchorManifestSha256": record["anchorManifestSha256"],
            "translationPolicySha256": record["translationPolicySha256"],
            "groups": [{"translationGroupId": row["translationGroupId"], "sourceUnitIds": row["sourceUnitIds"],
                        "priorTargetTextSha256": row["fullTargetTextSha256"],
                        "proposedTargetText": row["spokenText"]} for row in condensed]}


def bind_spoken_candidate(record: dict, anchor: dict, candidate: dict, spoken: dict,
                          policy: dict | None = None) -> dict:
    """Bind the spoken candidate the Layer 2 chain produced from the brief.

    Uncondensed groups must keep the full text. A condensed group's final text
    must match its recorded proposal and pass the budget, omission-span and
    deterministic checks again. Review changes require a renewed condensation
    record for that final text before it can bind.
    """
    _check_record(record, candidate)
    locale = record["targetLocale"]
    if (spoken.get("targetLocale") != locale or [(g["translationGroupId"], g["sourceUnitIds"])
                                                 for g in spoken["groups"]]
            != [(g["translationGroupId"], g["sourceUnitIds"]) for g in candidate["groups"]]):
        raise ValueError("Spoken candidate covers other groups than the full candidate")
    for key in ("englishSourcePackageJsonSha256", "anchorManifestSha256", "translationPolicySha256"):
        if spoken.get(key) != candidate.get(key):
            raise ValueError(f"Spoken candidate has another {key}")
    english = {unit["sourceUnitId"]: unit["english"] for unit in anchor["sourceUnits"]}
    condensed = {row["translationGroupId"]: row for row in record["groups"] if row["status"] == "condensed"}
    rows, issues = [], []
    for full, final in zip(candidate["groups"], spoken["groups"]):
        group_id, text = full["translationGroupId"], final["targetText"]
        row = condensed.get(group_id)
        if row is None:
            if text != full["targetText"]:
                issues.append(f"{group_id}: an uncondensed group differs from the full translation")
            continue
        request = {"translationGroupId": group_id, "fullTargetText": full["targetText"],
                   "maxSpeechUnits": row["maxSpeechUnits"],
                   "englishUnits": [{"sourceUnitId": unit_id, "english": english[unit_id]}
                                    for unit_id in full["sourceUnitIds"]]}
        problems = spoken_problems(request, text, row.get("omissions"), locale, policy)
        if text != row["spokenText"]:
            problems.append("review changed the spoken text; a renewed condensation record is required")
        issues += [f"{group_id}: {problem}" for problem in problems]
        rows.append({"translationGroupId": group_id, "finalSpokenTextSha256": _text_sha(text),
                     "finalSpeechUnits": predicted.speech_units(text, locale),
                     "changedByReview": text != row["spokenText"], "problems": problems})
    return {"schemaVersion": BINDING_SCHEMA, "targetLocale": locale, "status": "fail" if issues else "pass",
            "issues": issues, "condensationRecordJsonSha256": _sha(record),
            "fullCandidateJsonSha256": record["fullCandidateJsonSha256"],
            "spokenCandidateJsonSha256": _sha(spoken), "groups": rows,
            "implementationSha256": waiver.implementation_sha256(), "humanApproval": False}


def qc_groups(binding: dict, anchor: dict, spoken: dict) -> list[dict]:
    """Text QC input (``target_text_auto_qc.screen``) for a bound spoken candidate.

    Only the groups the passing binding covers carry ``condensation``, so only
    they are judged by the core-meaning rubric."""
    if binding.get("schemaVersion") != BINDING_SCHEMA or binding.get("status") != "pass":
        raise ValueError("Spoken candidate binding did not pass")
    if binding.get("spokenCandidateJsonSha256") != _sha(spoken):
        raise ValueError("Binding belongs to another spoken candidate")
    english = {unit["sourceUnitId"]: unit["english"] for unit in anchor["sourceUnits"]}
    condensed = {row["translationGroupId"] for row in binding["groups"]}
    rows = []
    for group in spoken["groups"]:
        row = {"groupId": group["translationGroupId"], "targetText": group["targetText"],
               "sourceUnitIds": list(group["sourceUnitIds"]),
               "english": " ".join(english[unit_id] for unit_id in group["sourceUnitIds"])}
        if group["translationGroupId"] in condensed:
            row["condensation"] = {"condensationRecordJsonSha256": binding["condensationRecordJsonSha256"],
                                   "fullCandidateJsonSha256": binding["fullCandidateJsonSha256"]}
        rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    brief = sub.add_parser("brief", help="Export the Layer 2 revision brief of a condensation record")
    bind = sub.add_parser("bind", help="Bind the spoken candidate produced from the brief")
    for command in (brief, bind):
        command.add_argument("--record", required=True, type=Path)
        command.add_argument("--candidate", required=True, type=Path)
        command.add_argument("--out", required=True, type=Path)
    qc = sub.add_parser("qc-groups", help="Write the text QC groups of a bound spoken candidate")
    qc.add_argument("--binding", required=True, type=Path)
    qc.add_argument("--out", required=True, type=Path)
    for command in (bind, qc):
        command.add_argument("--anchor", required=True, type=Path)
        command.add_argument("--spoken-candidate", required=True, type=Path)
    bind.add_argument("--policy", type=Path)
    args = parser.parse_args()

    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))
    if args.command == "brief":
        value = revision_brief(read(args.record), read(args.candidate))
    elif args.command == "bind":
        value = bind_spoken_candidate(read(args.record), read(args.anchor), read(args.candidate),
                                      read(args.spoken_candidate), read(args.policy) if args.policy else None)
    else:
        value = qc_groups(read(args.binding), read(args.anchor), read(args.spoken_candidate))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


if __name__ == "__main__":
    main()
