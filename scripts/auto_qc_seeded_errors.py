#!/usr/bin/env python3
"""Seeded-error calibration: prove the machine QC catches planted errors.

With no human reviewer, the only evidence that machine QC is good enough is
that it reliably finds errors we know are there. This harness plants typical
errors into an already published (clean) candidate and its unit audio, runs
the same QC code, and records detection per error kind plus the false-positive
rate on the clean material. ``machine_quality_waiver.py`` refuses a waiver
unless a calibration for the current QC implementation meets its minimums.

Text kinds: wrong_number, added_reference, english_leak, placeholder,
dropped_name, dropped_half. Audio kinds: stretched (the 2026-10-04 u172 class),
silent, clipped, truncated. Meaning errors without a surface signal (for
example a flipped negation) are only reachable through back-translation, so a
calibration without the back-translation transport is marked
``semanticChecksIncluded=false`` and cannot enable a waiver.
"""
from __future__ import annotations

import argparse
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

TEXT_KINDS = ("wrong_number", "added_reference", "english_leak", "placeholder", "dropped_name", "dropped_half")
AUDIO_KINDS = ("stretched", "silent", "clipped", "truncated")
ADDED_REFERENCE = {"zh-Hans": "（约翰福音3章16节）", "ko": " (요한복음 3장 16절)", "es": " (Juan 3:16)"}


def _number_forms(locale: str, value: int) -> list[str]:
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
    if kind == "wrong_number":
        pairs, _ = rules.english_references(english)
        protected = {value for pair in pairs for value in pair}
        for value in rules.english_numbers(english):
            if value in protected:
                continue
            for form in _number_forms(locale, value):
                # Skip one-character word forms (세, 三): replacing them would
                # usually corrupt an unrelated word instead of the number.
                if form in text and (form.isdigit() or len(form) > 1):
                    return text.replace(form, str(value + 7), 1)
        return None
    if kind == "added_reference":
        pairs, chapters = rules.english_references(english)
        return None if pairs or chapters else text + ADDED_REFERENCE[locale]
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


def _rate(detected: int, trials: int) -> float:
    return round(detected / trials, 6) if trials else 0.0


def calibrate_text(groups: list[dict], locale: str, *, policy: dict | None = None, call=None,
                   max_trials: int = 30) -> dict:
    median = text_qc.candidate_length_median(groups)
    kinds, false_positives, clean_checked = {}, 0, 0
    for group in groups:
        problems, _ = text_qc.group_problems(group, locale, policy=policy, median=median, call=call)
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
            trials += 1
            problems, _ = text_qc.group_problems({**group, "targetText": mutated}, locale,
                                                 policy=policy, median=median, call=call)
            if problems:
                detected += 1
            elif len(misses) < 5:
                misses.append(group["groupId"])
        kinds[kind] = {"trials": trials, "detected": detected, "rate": _rate(detected, trials),
                       "missedGroupIds": misses}
    return {"kinds": kinds, "cleanChecked": clean_checked, "cleanFalsePositives": false_positives}


def calibrate_audio(units: list[dict], locale: str, *, max_trials: int = 30) -> dict:
    decoded = [audio_qc.decode_pcm16(unit["wav"]) for unit in units]
    base = [{**unit, "metrics": audio_qc.signal_metrics(*pcm)} for unit, pcm in zip(units, decoded)]
    clean = audio_qc.screen(base, locale)
    false_positives = sum(row["status"] == "fail" for row in clean["results"])
    kinds = {}
    for kind in AUDIO_KINDS:
        trials = detected = 0
        misses = []
        for index, (samples, rate) in enumerate(decoded[:max_trials]):
            mutated = audio_qc.signal_metrics(*mutate_audio(samples, rate, kind))
            rows = list(base)
            rows[index] = {**base[index], "metrics": mutated}
            result = audio_qc.screen(rows, locale)["results"][index]
            trials += 1
            if result["status"] == "fail":
                detected += 1
            elif len(misses) < 5:
                misses.append(units[index]["groupId"])
        kinds[kind] = {"trials": trials, "detected": detected, "rate": _rate(detected, trials),
                       "missedGroupIds": misses}
    return {"kinds": kinds, "cleanChecked": len(units), "cleanFalsePositives": false_positives}


def calibrate(locale: str, groups: list[dict], units: list[dict] | None = None, *,
              policy: dict | None = None, call=None, max_trials: int = 30) -> dict:
    text = calibrate_text(groups, locale, policy=policy, call=call, max_trials=max_trials)
    audio = calibrate_audio(units, locale, max_trials=max_trials) if units else None
    kinds = {f"text.{k}": v for k, v in text["kinds"].items()}
    if audio is not None:
        kinds.update({f"audio.{k}": v for k, v in audio["kinds"].items()})
    trials = sum(row["trials"] for row in kinds.values())
    detected = sum(row["detected"] for row in kinds.values())
    clean = text["cleanChecked"] + (audio["cleanChecked"] if audio else 0)
    positives = text["cleanFalsePositives"] + (audio["cleanFalsePositives"] if audio else 0)
    return {"schemaVersion": waiver.CALIBRATION_SCHEMA, "locale": locale,
            "implementationSha256": waiver.implementation_sha256(),
            "semanticChecksIncluded": call is not None, "audioIncluded": audio is not None,
            "kinds": kinds, "trials": trials, "detected": detected,
            "overallDetectionRate": _rate(detected, trials),
            "cleanChecked": clean, "cleanFalsePositives": positives,
            "cleanFalsePositiveRate": _rate(positives, clean), "humanApproval": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path,
                        help="{locale, groups:[{groupId, english, targetText}], units?:[{groupId, text, "
                             "sourceSeconds, wavPath}], policy?}")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--max-trials", type=int, default=30)
    args = parser.parse_args()
    value = json.loads(args.input.read_text(encoding="utf-8"))
    units = None
    if value.get("units"):
        units = [{**{k: v for k, v in unit.items() if k != "wavPath"},
                  "wav": Path(unit["wavPath"]).read_bytes()} for unit in value["units"]]
    # The back-translation transport is wired by the production owner; this
    # offline entry records semanticChecksIncluded=false and cannot unlock a waiver.
    receipt = calibrate(value["locale"], value["groups"], units, policy=value.get("policy"),
                        max_trials=args.max_trials)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: receipt[key] for key in ("overallDetectionRate", "cleanFalsePositiveRate",
                                                     "semanticChecksIncluded")}))


if __name__ == "__main__":
    main()
