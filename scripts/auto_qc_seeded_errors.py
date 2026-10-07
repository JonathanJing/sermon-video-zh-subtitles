#!/usr/bin/env python3
"""Seeded-error calibration: prove the machine QC catches planted errors.

With no human reviewer, the only evidence that machine QC is good enough is
that it reliably finds errors we know are there. This harness plants typical
errors into an already published (clean) candidate and its unit audio, runs
the same QC code, and records detection per error kind plus the false-positive
rate on the clean material. ``machine_quality_waiver.py`` refuses a waiver
unless a calibration for the current QC implementation meets its minimums.

Text kinds: wrong_number, added_reference, wrong_book, english_leak,
placeholder, dropped_name, dropped_half, semantic_negation, added_number (a
spelled count the English never said), wrong_ordinal (an ordinal the English
did not say: "the first love" as "the second", or a "Second," the English never
said), swapped_quantity (two quantities trade places). Audio kinds: stretched (the 2026-10-04
u172 class), silent, clipped, truncated, and wrong_sentence (another unit's
audio under this unit's text, which only the ASR path can catch). Meaning
errors without a surface signal (for example a flipped negation) are only
reachable through back-translation, so a calibration without the
back-translation transport is marked ``semanticChecksIncluded=false`` and
cannot enable a waiver; without an ASR transport wrong_sentence has no trials.

A seeded trial counts as detected only when the mutated item gains a problem
its clean version did not have (for wrong_sentence: a confirmed ASR mismatch),
so baseline false positives are never credited as detections. The calibration
records the back-translation and ASR runtime identities it ran with; a waiver
requires the QC receipts to name the same ones.
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
from scripts import target_audio_auto_qc as audio_qc
from scripts import target_text_auto_qc as text_qc
from scripts.language_review_plugins import auto_qc_text_common as rules

TEXT_KINDS = waiver.TEXT_KINDS
AUDIO_KINDS = waiver.AUDIO_KINDS
SPOKEN_KINDS = waiver.SPOKEN_KINDS
# The first negation found is removed or reversed (않으십니다 -> 으십니다 reads as an affirmation).
NEGATIONS = {"zh-Hans": (("没有", "有"), ("不", "")),
             "ko": (("지 않", ""), ("없", "있"), ("안 ", "")),
             "es": ((" no ", " "), ("nunca", "siempre"), ("No ", ""))}
ADDED_REFERENCE = {"zh-Hans": "（约翰福音3章16节）", "ko": " (요한복음 3장 16절)", "es": " (Juan 3:16)"}
# A spelled count the English never said: digits would be caught by the surface
# screen, so this trial needs the back-translation check.
ADDED_NUMBER = {"zh-Hans": "（共五人）", "ko": " (모두 다섯 명)", "es": " (cinco en total)"}
# Ordinals have no reliable surface screen ("first" is often 起初, 처음, primero
# lugar), so the back-translation check must catch a changed one. A matching
# target ordinal moves up by one; a group whose English says no ordinal gains one.
ORDINAL_SHIFTS = {
    "zh-Hans": ((r"第一", "第二"), (r"第二", "第三"), (r"第三", "第四")),
    "ko": ((r"첫\s*번째", "두 번째"), (r"첫째", "둘째"), (r"두\s*번째", "세 번째"), (r"둘째", "셋째"),
           (r"세\s*번째", "네 번째"), (r"셋째", "넷째")),
    "es": ((r"\bprimero\b", "segundo"), (r"\bprimera\b", "segunda"), (r"\bprimer\b", "segundo"),
           (r"\bsegundo\b", "tercer"), (r"\bsegunda\b", "tercera"),
           (r"\btercero\b", "cuarto"), (r"\btercera\b", "cuarta"), (r"\btercer\b", "cuarto")),
}
ORDINAL_FORMS = {"zh-Hans": {1: ("第一",), 2: ("第二",), 3: ("第三",)},
                 "ko": {1: ("첫", "첫째"), 2: ("두 번째", "둘째"), 3: ("세 번째", "셋째")},
                 "es": {1: ("primer",), 2: ("segund",), 3: ("tercer",)}}
ENGLISH_ORDINALS = {word: value for value, word in enumerate(
    ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"), start=1)}
ADDED_ORDINAL = {"zh-Hans": "第二，", "ko": "둘째, ", "es": "En segundo lugar, "}
# An omission small enough to stay inside the length envelope is only the
# judge's to catch, so dropped_half is credited on a back-translation issue alone
# (a length failure on the same trial does not count); its trials still run.
JUDGE_CREDITED_KINDS = ("dropped_half",)
# Kinds only the back-translation check may detect: a surface failure is not credited.
SEMANTIC_KINDS = ("semantic_negation", "added_number", "wrong_ordinal", "swapped_quantity")
# The book a wrong_book mutation substitutes (Romans when the citation is already John).
OTHER_BOOK = {"zh-Hans": ("约翰福音", "罗马书"), "ko": ("요한복음", "로마서"), "es": ("Juan", "Romanos")}


def _fold_es(text: str, locale: str) -> str:
    return text.casefold() if locale == "es" else text


def _semantic_hit(new: set[str]) -> bool:
    """A new major back-translation issue; the judge failing to answer is not one."""
    return any(problem.startswith("back_translation ") and problem != "back_translation judge failed"
               for problem in new)


def _number_forms(locale: str, value: int | str) -> list[str]:
    if isinstance(value, str):  # A digit decimal ("2.5"; Spanish may write "2,5").
        return [value, value.replace(".", ",")] if locale == "es" else [value]
    forms = [str(value)]
    if locale == "ko":
        forms += [rules.korean_sino(value), *rules.korean_native(value)]
    elif locale == "es":
        forms.append(rules.spanish_words(value))
    else:
        forms.append(rules.chinese_numeral(value))
    return sorted(set(forms), key=len, reverse=True)


def mutate_text(group: dict, kind: str, locale: str, policy: dict | None) -> str | None:
    """Return a mutated target text, or None when the kind does not apply."""
    english, text = group["english"], group["targetText"]
    if kind == "semantic_negation":
        # Flip a target negation without changing names, numbers, references or
        # script. Only groups with source negation supply this semantic trial.
        if not re.search(r"\b(?:not|never)\b", english, re.I):
            return None
        markers = {"zh-Hans": (("不是", "是"), ("不会", "会"), ("没有", "已经")),
                   "ko": (("더럽히지 않은", "더럽힌"), ("두지 않으십니다", "두십니다"),
                          ("아니라", "이며")),
                   "es": ((" no ", " sí "),)}[locale]
        for negative, positive in markers:
            if negative in text:
                return text.replace(negative, positive, 1)
        return None
    if kind == "wrong_number":
        # Citations are the reference screen's; a quantity sharing a cited value is still one.
        said, pairs = rules.english_without_citations(english)
        masked = rules.target_without_citations(text, locale, pairs)
        for value in rules.english_numbers(said):
            for form in _number_forms(locale, value):
                # Skip one-character word forms (세, 三): replacing them would
                # usually corrupt an unrelated word instead of the number.
                at = masked.find(form)
                if at >= 0 and (form.isdigit() or len(form) > 1):
                    # A decimal loses its separator (2.5 -> 25); an integer shifts by 7.
                    wrong = re.sub(r"[.,]", "", form) if isinstance(value, str) else str(value + 7)
                    return text[:at] + wrong + text[at + len(form):]
        return None
    if kind == "swapped_quantity":
        # Two English quantities trade places ("two sons and three daughters" as
        # "three sons and two daughters"): every number survives, so only meaning catches it.
        said, pairs = rules.english_without_citations(english)
        masked = rules.target_without_citations(text, locale, pairs)
        found = []
        for value in dict.fromkeys(value for value in rules.english_numbers(said) if isinstance(value, int)):
            for form in _number_forms(locale, value):
                at = masked.find(form)
                # One-character word forms (세, 三) would usually hit an unrelated word.
                if at >= 0 and (form.isdigit() or len(form) > 1) and all(
                        at + len(form) <= start or at >= start + len(other) for start, other in found):
                    found.append((at, form))
                    break
            if len(found) == 2:
                (first, left), (second, right) = sorted(found)
                return (text[:first] + right + text[first + len(left):second] + left
                        + text[second + len(right):])
        return None
    if kind == "added_number":
        return None if rules.english_number_values(english) else text + ADDED_NUMBER[locale]
    if kind == "wrong_ordinal":
        said = {value for word in re.findall(r"[a-z]+", english.casefold())
                for value in [ENGLISH_ORDINALS.get(word)] if value}
        if not said:
            return ADDED_ORDINAL[locale] + (text[:1].lower() + text[1:] if locale == "es" else text)
        for value in sorted(said):
            if value in ORDINAL_FORMS[locale] and any(form in _fold_es(text, locale)
                                                      for form in ORDINAL_FORMS[locale][value]):
                for pattern, replacement in ORDINAL_SHIFTS[locale]:
                    match = re.search(pattern, text, re.I)
                    if match:
                        return text[:match.start()] + replacement + text[match.end():]
        return None
    if kind == "added_reference":
        pairs, chapters = rules.english_references(english)
        return None if pairs or chapters else text + ADDED_REFERENCE[locale]
    if kind == "wrong_book":
        cited = {(c, v) for code, c, v in rules.english_book_citations(english) if code}
        for code, chapter, verse, (start, end) in rules.book_citations(text, locale):
            if (chapter, verse) in cited:
                john, romans = OTHER_BOOK[locale]
                return text[:start] + (romans if code == "JOH" else john) + text[end:]
        return None
    if kind == "english_leak":
        return english if len(re.findall(r"[A-Za-z]+", english)) >= 6 else None
    if kind == "placeholder":
        return text + " TODO"
    if kind == "dropped_name":
        if policy is None:
            return None
        for kind_name in ("properNames", "seriesNames"):
            for term in policy["terminology"][kind_name]:
                target = term.get("target")
                if (target and term.get("reviewStatus") != "pending" and target in text
                        and re.search(r"(?<!\w)" + re.escape(term["source"]) + r"(?!\w)", english, re.I)):
                    return text.replace(target, "", 1)
        return None
    if kind == "dropped_half":
        if text_qc.length_ratio(group) is None:
            return None
        cut = len(text) // 2
        boundary = max(text.rfind(mark, 0, cut + 1) for mark in "，,。.、 ")
        return text[:boundary if boundary > len(text) // 4 else cut].rstrip()
    raise ValueError(f"Unknown text kind: {kind}")


def mutate_audio(samples: list[float], rate: int, kind: str) -> tuple[list[float], int]:
    if kind == "stretched":
        return samples * 20, rate
    if kind == "silent":
        return [0.0] * len(samples), rate
    if kind == "clipped":
        return [max(-1.0, min(1.0, value * 30)) for value in samples], rate
    if kind == "truncated":
        return samples[:max(1, len(samples) // 4)], rate
    raise ValueError(f"Unknown audio kind: {kind}")


def mutate_spoken(group: dict, kind: str, locale: str, others: list[dict]) -> str | None:
    """A seeded error in a condensed spoken group, or None when the kind does not apply.

    Dropping redundancy is what condensation is allowed to do, so these kinds
    change what is said instead: another group's content, an added sentence,
    a reversed negation, or a dropped clause (the claim, call or attribution
    a condenser could mislabel as an allowed aside)."""
    text = group["targetText"]
    other = next((row["targetText"] for row in others
                  if row["groupId"] != group["groupId"] and row["targetText"] not in text), None)
    if kind == "swapped_content":
        return other
    if kind == "added_content":
        return None if other is None else text + ("" if locale == "zh-Hans" else " ") + other
    if kind == "flipped_negation":
        for old, new in NEGATIONS[locale]:
            if old in text:
                return text.replace(old, new, 1)
        return None
    if kind == "dropped_claim":
        clauses = [clause for clause in re.findall(r"[^，。；！？,.;!?]+[，。；！？,.;!?]*\s*", text) if clause.strip()]
        if len(clauses) < 2:
            return None
        longest = max(range(len(clauses)), key=lambda index: len(clauses[index]))
        return "".join(clauses[:longest] + clauses[longest + 1:]).strip().rstrip("，,；;、")
    raise ValueError(f"Unknown spoken kind: {kind}")


def calibrate_spoken(groups: list[dict], locale: str, *, policy: dict | None = None, call=None,
                     max_trials: int = 30) -> dict:
    """Seeded errors in the condensed groups of a clean spoken candidate.

    ``groups`` are its text QC groups (``spoken_condensation.qc_groups``); only
    those carrying ``condensation`` are mutated, and the others supply the
    swapped and added content."""
    condensed = [group for group in groups if group.get("condensation")]
    if not condensed:
        raise ValueError("Spoken calibration needs condensed spoken groups")
    kinds, false_positives, clean = {}, 0, {}
    for group in condensed:
        problems, _ = text_qc.group_problems(group, locale, policy=policy, median=None, call=call)
        clean[group["groupId"]] = set(problems)
        false_positives += bool(problems)
    for kind in SPOKEN_KINDS:
        trials = detected = 0
        misses = []
        for group in condensed:
            if trials >= max_trials:
                break
            mutated = mutate_spoken(group, kind, locale, groups)
            if mutated is None or mutated == group["targetText"]:
                continue
            trials += 1
            problems, _ = text_qc.group_problems({**group, "targetText": mutated}, locale,
                                                 policy=policy, median=None, call=call)
            # Every spoken kind is a meaning change: a name or number screen also
            # failing it does not show that the back-translation check sees it.
            if _semantic_hit(set(problems) - clean[group["groupId"]]):
                detected += 1
            elif len(misses) < 5:
                misses.append(group["groupId"])
        kinds[kind] = {"trials": trials, "detected": detected, "rate": _rate(detected, trials),
                       "missedGroupIds": misses}
    return {"kinds": kinds, "cleanChecked": len(condensed), "cleanFalsePositives": false_positives}


def _rate(detected: int, trials: int) -> float:
    return round(detected / trials, 6) if trials else 0.0


def calibrate_text(groups: list[dict], locale: str, *, policy: dict | None = None, call=None,
                   max_trials: int = 30) -> dict:
    median = text_qc.candidate_length_median(groups)
    kinds, false_positives, clean_checked, clean = {}, 0, 0, {}
    for group in groups:
        problems, _ = text_qc.group_problems(group, locale, policy=policy, median=median, call=call)
        clean[group["groupId"]] = set(problems)
        clean_checked += 1
        false_positives += bool(problems)
    for kind in TEXT_KINDS:
        trials = detected = 0
        misses = []
        for group in groups:
            if trials >= max_trials:
                break
            mutated = mutate_text(group, kind, locale, policy)
            if mutated is None or mutated == group["targetText"]:
                continue
            if kind in SEMANTIC_KINDS:
                # Do not let a surface or length failure satisfy this trial.
                surface, _ = text_qc.group_problems({**group, "targetText": mutated}, locale,
                                                  policy=policy, median=median)
                baseline_surface, _ = text_qc.group_problems(group, locale, policy=policy, median=median)
                if set(surface) - set(baseline_surface):
                    continue
            trials += 1
            problems, _ = text_qc.group_problems({**group, "targetText": mutated}, locale,
                                                 policy=policy, median=median, call=call)
            new = set(problems) - clean[group["groupId"]]
            hit = _semantic_hit(new) if kind in SEMANTIC_KINDS + JUDGE_CREDITED_KINDS else bool(new)
            if hit:
                detected += 1
            elif len(misses) < 5:
                misses.append(group["groupId"])
        kinds[kind] = {"trials": trials, "detected": detected, "rate": _rate(detected, trials),
                       "missedGroupIds": misses}
    return {"kinds": kinds, "cleanChecked": clean_checked, "cleanFalsePositives": false_positives}


def _asr_row(unit: dict, wav: bytes, locale: str, asr, threshold: float) -> dict:
    """A unit row whose ASR opinions are freshly computed for ``wav`` under the unit's text."""
    primary = asr("primary", wav, unit["text"], locale)
    opinions = {"primary": primary}
    if not audio_qc.transcript_agrees(unit["text"], primary["recognized"], locale, threshold):
        opinions["secondary"] = asr("secondary", wav, unit["text"], locale)
    return {**unit, "wav": wav, "asr": opinions}


def drop_key_word(text: str, locale: str) -> str | None:
    """``text`` without its first negation or number, as a dub that dropped it would be heard."""
    from scripts.screen_target_language_audio_units import ES_NUMBERS, NEGATIONS, ZH_NUMERALS
    if locale == "es":
        words = "|".join(sorted({*NEGATIONS["es"], *ES_NUMBERS}, key=len, reverse=True))
        pattern = r"\d+(?:[.,:]\d+)*|(?<![^\W\d_])(?:" + words + r")(?![^\W\d_])"
        match = re.search(pattern, text, flags=re.IGNORECASE)
    else:
        # Korean 안 negates only as its own word (안 갑니다), not inside 동안 or 평안.
        markers = [r"(?<![가-힣])안(?=\s)" if marker == "안" else re.escape(marker)
                   for marker in sorted(NEGATIONS[locale], key=len, reverse=True)]
        numerals = "[" + ZH_NUMERALS + "]+|" if locale == "zh-Hans" else ""
        match = re.search("|".join(markers) + "|" + numerals + r"\d+", text)
    if match is None:
        return None
    return re.sub(r"\s{2,}", " ", text[:match.start()] + text[match.end():]).strip()


def calibrate_audio(units: list[dict], locale: str, *, asr=None, max_trials: int = 30) -> dict:
    """``asr(role, wav, text, locale) -> opinion`` (see ``target_audio_auto_qc.asr_opinion``)
    is the production ASR transport; without it wrong_sentence has no trials."""
    threshold = audio_qc.THRESHOLDS["asrMinSimilarity"]
    if asr is not None:
        units = [_asr_row(unit, unit["wav"], locale, asr, threshold) for unit in units]
    units = [{key: value for key, value in unit.items() if key != "metrics"} for unit in units]
    decoded = [audio_qc.decode_pcm16(unit["wav"]) for unit in units]
    base = list(units)
    clean = audio_qc.screen(base, locale)["results"]
    false_positives = sum(row["status"] == "fail" for row in clean)
    kinds, models = {}, {"primary": set(), "secondary": set()}

    def note_runtime(row: dict) -> None:
        for role in ("primary", "secondary"):
            if row[f"asr{role.title()}Model"] is not None:
                models[role].add(json.dumps([row[f"asr{role.title()}Model"], row[f"asr{role.title()}SettingsSha256"]],
                                            sort_keys=True))

    for row in clean:
        note_runtime(row)
    for kind in AUDIO_KINDS:
        trials = detected = 0
        misses = []
        for index, (samples, rate) in enumerate(decoded[:max_trials]):
            rows = list(base)
            if kind == "wrong_sentence":
                # Another sentence's audio; identical bytes would not be a wrong sentence.
                other = next((units[(index + j) % len(units)] for j in range(1, len(units))
                              if units[(index + j) % len(units)]["text"] != units[index]["text"]
                              and units[(index + j) % len(units)]["wav"] != units[index]["wav"]), None)
                if asr is None or other is None:
                    continue
                wav = other["wav"]
                rows[index] = _asr_row(units[index], wav, locale, asr, threshold)
            elif kind == "dropped_key_word":
                # A dub that lost one "not" or number still scores high on the ratio; the
                # ASR hears what the dub said, so its transcript lacks that word.
                if asr is None or drop_key_word(units[index]["asr"]["primary"]["recognized"], locale) is None:
                    continue

                def omitting(role, wav, text, asr_locale):
                    opinion = asr(role, wav, text, asr_locale)
                    heard = drop_key_word(opinion["recognized"], asr_locale) or opinion["recognized"]
                    return {**opinion, "recognized": heard,
                            "similarity": audio_qc.transcript_similarity(text, heard, asr_locale)}
                rows[index] = _asr_row(units[index], units[index]["wav"], locale, omitting, threshold)
            else:
                # The screen decodes the mutated bytes, as it would a real faulty render.
                rows[index] = {**base[index], "wav": audio_qc.encode_pcm16(*mutate_audio(samples, rate, kind))}
            result = audio_qc.screen(rows, locale)["results"][index]
            note_runtime(result)
            trials += 1
            new = set(result["issues"]) - set(clean[index]["issues"])
            hit = ("asr_mismatch_confirmed" in new if kind in ("wrong_sentence", "dropped_key_word")
                   else bool(new))
            if result["status"] == "fail" and hit:
                detected += 1
            elif len(misses) < 5:
                misses.append(units[index]["groupId"])
        kinds[kind] = {"trials": trials, "detected": detected, "rate": _rate(detected, trials),
                       "missedGroupIds": misses}
    if any(len(values) > 1 for values in models.values()):
        raise ValueError("ASR transport reported more than one model or runtime per role during calibration")
    runtime = {role: json.loads(next(iter(values))) if values else [None, None] for role, values in models.items()}
    calibrated = runtime["primary"][0] is not None
    return {"kinds": kinds, "cleanChecked": len(units), "cleanFalsePositives": false_positives,
            "asrIdentity": {role: value[0] for role, value in runtime.items()} if calibrated else None,
            "asrSettingsSha256": {role: value[1] for role, value in runtime.items()} if calibrated else None}


def calibration_inputs(groups: list[dict], units: list[dict] | None, spoken_groups: list[dict] | None,
                       policy: dict | None) -> dict:
    """What the calibration seeded, hashed as the QC receipts record it, so a waiver
    can check that the calibration exercised the artifacts it releases."""
    def text_rows(rows):
        return [{"groupId": row["groupId"], "englishSha256": _text_sha(row["english"]),
                 "targetTextSha256": _text_sha(row["targetText"])} for row in rows]

    return {"textGroupsSha256": waiver.text_inputs_sha256(text_rows(groups)),
            "spokenGroupsSha256": waiver.text_inputs_sha256(text_rows(spoken_groups)) if spoken_groups else None,
            "audioUnitsSha256": None if not units else waiver.audio_inputs_sha256(
                [{"groupId": unit["groupId"], "audioSha256": hashlib.sha256(unit["wav"]).hexdigest(),
                  "textSha256": _text_sha(unit["text"])} for unit in units]),
            "policyJsonSha256": None if policy is None else waiver.json_sha256(policy)}


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def calibrate(locale: str, groups: list[dict], units: list[dict] | None = None, *,
              policy: dict | None = None, call=None, identity: dict | None = None, asr=None,
              spoken_groups: list[dict] | None = None, max_trials: int = 30) -> dict:
    """``identity`` names the back-translation runtime behind ``call`` and is required with it.
    ``spoken_groups`` are the text QC groups of a clean spoken candidate with
    condensed groups; without them a calibration cannot back such a candidate."""
    if call is not None and identity is None:
        raise ValueError("A back-translation transport needs its semantic identity")
    bound = text_qc.semantic_identity(identity) if call is not None else None
    inputs = calibration_inputs(groups, units, spoken_groups, policy)
    text = calibrate_text(groups, locale, policy=policy, call=call, max_trials=max_trials)
    audio = calibrate_audio(units, locale, asr=asr, max_trials=max_trials) if units else None
    spoken = (calibrate_spoken(spoken_groups, locale, policy=policy, call=call, max_trials=max_trials)
              if spoken_groups else None)
    kinds = {f"text.{k}": v for k, v in text["kinds"].items()}
    if audio is not None:
        kinds.update({f"audio.{k}": v for k, v in audio["kinds"].items()})
    if spoken is not None:
        kinds.update({f"spoken.{k}": v for k, v in spoken["kinds"].items()})
    trials = sum(row["trials"] for row in kinds.values())
    detected = sum(row["detected"] for row in kinds.values())
    clean = text["cleanChecked"] + sum(part["cleanChecked"] for part in (audio, spoken) if part)
    positives = text["cleanFalsePositives"] + sum(part["cleanFalsePositives"] for part in (audio, spoken) if part)
    return {"schemaVersion": waiver.CALIBRATION_SCHEMA, "locale": locale,
            "implementationSha256": waiver.implementation_sha256(),
            "inputs": inputs,
            "semanticChecksIncluded": call is not None, "audioIncluded": audio is not None,
            "spokenIncluded": spoken is not None,
            "semanticIdentity": None if bound is None else bound["identity"],
            "semanticIdentitySha256": None if bound is None else bound["sha256"],
            "asrIdentity": None if audio is None else audio["asrIdentity"],
            "asrSettingsSha256": None if audio is None else audio["asrSettingsSha256"],
            "kinds": kinds, "trials": trials, "detected": detected,
            "overallDetectionRate": _rate(detected, trials),
            "cleanChecked": clean, "cleanFalsePositives": positives,
            "cleanFalsePositiveRate": _rate(positives, clean), "humanApproval": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path,
                        help="{locale, groups:[{groupId, english, targetText}], units?:[{groupId, text, "
                             "sourceSeconds, wavPath, asr?}], spokenGroups?:[spoken_condensation.py qc-groups "
                             "output], policy?}")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--max-trials", type=int, default=30)
    args = parser.parse_args()
    value = json.loads(args.input.read_text(encoding="utf-8"))
    units = None
    if value.get("units"):
        units = [{**{k: v for k, v in unit.items() if k != "wavPath"},
                  "wav": Path(unit["wavPath"]).read_bytes()} for unit in value["units"]]
    # The back-translation and ASR transports are wired by the production owner;
    # this offline entry records semanticChecksIncluded=false and no wrong_sentence
    # trials, so it cannot unlock a waiver.
    receipt = calibrate(value["locale"], value["groups"], units, policy=value.get("policy"),
                        spoken_groups=value.get("spokenGroups"), max_trials=args.max_trials)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: receipt[key] for key in ("overallDetectionRate", "cleanFalsePositiveRate",
                                                     "semanticChecksIncluded")}))


if __name__ == "__main__":
    main()
