#!/usr/bin/env python3
"""Predict target-language speech length before TTS and budget spoken text.

The 8-second end lag is the product's simultaneous-interpretation listening
target. Today it is only measured after a whole-locale render, so a long group
forces a Layer 3 -> Layer 2 loop. This module fits a per-locale speech rate
from already measured units (for example the 2026-10-04 formal renders), then
runs the formal rolling scheduler on predicted durations. It returns, per
group, a speech-unit budget that a spoken-candidate revision can target before
any synthesis. Predictions are planning evidence only: measured audio still
goes through the unchanged formal schedule, and nothing here edits text,
audio or approvals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import render_formal_target_language_speech as formal
from scripts import target_audio_timing_plan as timing

SCHEMA = "sermon-target-audio-predicted-schedule-v1"
RATE_SCHEMA = "sermon-target-speech-rate-v1"
EPSILON = 1e-6
# Speech-job adapter fields that change how long the same text sounds. A rate
# fitted under one identity is never used to budget another.
SYNTHESIS_IDENTITY_FIELDS = (
    "adapterId", "adapterVersion", "configSha256", "provider", "model", "modelRevision",
    "voice", "speakerId", "conditioningSha256", "languageParameter", "normalizationPolicySha256",
)


def synthesis_identity(job: dict) -> dict:
    """The synthesis identity of one speech job (targetLocale plus adapter fields)."""
    adapter = job.get("adapter") or {}
    missing = [field for field in SYNTHESIS_IDENTITY_FIELDS if not adapter.get(field)]
    if not job.get("targetLocale") or missing:
        raise ValueError(f"Speech job lacks synthesis identity fields: {missing or ['targetLocale']}")
    return {"targetLocale": job["targetLocale"], **{field: adapter[field] for field in SYNTHESIS_IDENTITY_FIELDS}}


def _check_identity(identity: dict, locale: str) -> None:
    if (not isinstance(identity, dict) or set(identity) != {"targetLocale", *SYNTHESIS_IDENTITY_FIELDS}
            or not all(isinstance(value, str) and value for value in identity.values())):
        raise ValueError("Synthesis identity must carry exactly the speech-job identity fields")
    if identity["targetLocale"] != locale:
        raise ValueError("Synthesis identity belongs to another locale")


def speech_units(text: str, locale: str) -> float:
    """Locale proxy for spoken length: syllables (ko/es) or Han characters (zh)."""
    if not isinstance(text, str):
        raise ValueError("Speech text must be a string")
    latin_words = re.findall(r"[A-Za-z]+", text) if locale != "es" else []
    digits = len(re.findall(r"\d", text))
    if locale == "ko":
        base = sum("가" <= char <= "힣" for char in text)
    elif locale == "zh-Hans":
        base = sum("一" <= char <= "鿿" for char in text)
    elif locale == "es":
        folded = text.casefold()
        base = len(re.findall(r"[aeiouáéíóúü]+", folded)) + len(re.findall(r"\by\b", folded))
    else:
        raise ValueError(f"Unsupported speech-rate locale: {locale}")
    # Each digit is read as roughly 1.5 syllables; a Latin word in ko/zh as two.
    return float(base + 1.5 * digits + 2 * len(latin_words))


def fit_rate(rows: list[dict], locale: str, *, synthesis_identity: dict) -> dict:
    """Least-squares seconds = intercept + secondsPerUnit * units on inlier rows.

    ``rows`` are units measured under ``synthesis_identity``:
    ``{"text": str, "audioSeconds": float, "audioSha256": str}``. The rate
    records that identity and a hash of the measurements it was fitted from.
    Rows whose per-unit rate is outside 0.5x-2x of the median are excluded so a
    61-second synthesis anomaly cannot skew the model. ``p90Factor`` is the 90th
    percentile of measured/predicted on inliers and makes budgets conservative.
    """
    _check_identity(synthesis_identity, locale)
    points, measurements = [], []
    for row in rows:
        units, seconds = speech_units(row.get("text"), locale), row.get("audioSeconds")
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("Measured audioSeconds must be positive")
        if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("audioSha256"))):
            raise ValueError("Each measured unit needs the audioSha256 it was measured from")
        measurements.append({"text": row["text"], "audioSeconds": seconds, "audioSha256": row["audioSha256"]})
        if units >= 3:
            points.append((units, float(seconds)))
    if len(points) < 20:
        raise ValueError("At least 20 measured units with 3+ speech units are required")
    median_rate = statistics.median(seconds / units for units, seconds in points)
    inliers = [(u, s) for u, s in points if 0.5 * median_rate <= s / u <= 2 * median_rate]
    mean_u = statistics.fmean(u for u, _ in inliers)
    mean_s = statistics.fmean(s for _, s in inliers)
    variance = sum((u - mean_u) ** 2 for u, _ in inliers)
    slope = sum((u - mean_u) * (s - mean_s) for u, s in inliers) / variance if variance else median_rate
    intercept = mean_s - slope * mean_u
    if slope <= 0:
        slope, intercept = median_rate, 0.0
    intercept = max(0.0, intercept)
    factors = sorted(s / (intercept + slope * u) for u, s in inliers)
    p90 = factors[min(len(factors) - 1, math.ceil(0.9 * len(factors)) - 1)]
    measurement_sha = hashlib.sha256(json.dumps(measurements, ensure_ascii=False, sort_keys=True,
                                                separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"schemaVersion": RATE_SCHEMA, "locale": locale, "secondsPerUnit": round(slope, 6),
            "interceptSeconds": round(intercept, 6), "p90Factor": round(max(1.0, p90), 6),
            "fittedUnits": len(inliers), "excludedOutliers": len(points) - len(inliers),
            "synthesisIdentity": dict(synthesis_identity), "measurementSha256": measurement_sha,
            "measuredUnits": len(measurements)}


def predict_seconds(text: str, rate: dict, *, conservative: bool = True) -> float:
    seconds = rate["interceptSeconds"] + rate["secondsPerUnit"] * speech_units(text, rate["locale"])
    return seconds * (rate["p90Factor"] if conservative else 1.0)


def max_units_for(seconds: float, rate: dict) -> int:
    usable = seconds / rate["p90Factor"] - rate["interceptSeconds"]
    return max(0, math.floor(usable / rate["secondsPerUnit"]))


def budget(source_seconds: float, groups: list[dict], rate: dict, policy: dict | None = None,
           *, synthesis_identity: dict, target_end_lag_seconds: float = 4.0) -> dict:
    """Greedy rolling schedule on predicted durations with per-group budgets.

    ``groups``: ordered ``{"gid", "sourceStart", "sourceEnd", "text"}`` with
    clip-relative source times. A group whose predicted end passes
    ``sourceEnd + maxEndLagSeconds`` (or the clip end) gets ``action=shorten``
    and the largest speech-unit count that fits; later groups are planned as if
    that revision lands, so one long group no longer cascades lag downstream.
    A shortened group is budgeted to end ``target_end_lag_seconds`` after its
    source (never past the hard limit), leaving headroom for the next group
    instead of spending the whole 8-second allowance on one sentence.

    ``synthesis_identity`` is the identity of the job being budgeted; a rate
    fitted under any other identity is refused.
    """
    if rate.get("schemaVersion") != RATE_SCHEMA:
        raise ValueError("Unsupported speech-rate artifact")
    _check_identity(synthesis_identity, rate.get("locale"))
    if rate.get("synthesisIdentity") != synthesis_identity:
        raise ValueError("Speech rate was fitted under another synthesis identity; refit it for this job")
    policy = dict(formal.DEFAULT_POLICY if policy is None else policy)
    if set(policy) != set(formal.DEFAULT_POLICY):
        raise ValueError("Invalid schedule policy fields")
    if not groups:
        raise ValueError("Groups are required")
    if not 0 < target_end_lag_seconds <= policy["maxEndLagSeconds"]:
        raise ValueError("Target end lag must be positive and within the hard maximum")
    locale = rate["locale"]
    cursor, planned, rows = 0.0, [], []
    for index, group in enumerate(groups):
        start_source, end_source = float(group["sourceStart"]), float(group["sourceEnd"])
        units = speech_units(group["text"], locale)
        predicted = predict_seconds(group["text"], rate)
        start = max(start_source + policy["reactionLagSeconds"],
                    cursor + (policy["interUtteranceGapSeconds"] if index else 0.0))
        limit = min(end_source + policy["maxEndLagSeconds"], source_seconds)
        allowed = limit - start
        action, duration, max_units = "keep", predicted, None
        if start + predicted > limit + EPSILON:
            aim = min(limit, end_source + target_end_lag_seconds)
            allowed = aim - start if aim - start >= 1.0 else limit - start
            max_units = max_units_for(allowed, rate) if allowed > 0 else 0
            action = "shorten" if max_units >= 1 else "cannot_fit"
            duration = max(allowed, 0.05)
        cursor = start + duration
        rows.append({"gid": group["gid"], "sourceStart": start_source, "sourceEnd": end_source,
                     "audioSeconds": round(duration, 6)})
        planned.append({"gid": group["gid"], "action": action,
                        "sourceStart": start_source, "sourceEnd": end_source,
                        "speechUnits": units, "predictedSeconds": round(predicted, 6),
                        "plannedStart": round(start, 6), "allowedSeconds": round(allowed, 6),
                        "maxSpeechUnits": max_units,
                        "shortenBySpeechUnits": None if max_units is None else max(0.0, units - max_units)})
    check = timing.plan(source_seconds, rows, policy, locale=locale)
    shorten = [row["gid"] for row in planned if row["action"] == "shorten"]
    impossible = [row["gid"] for row in planned if row["action"] == "cannot_fit"]
    return {"schemaVersion": SCHEMA, "locale": locale, "sourceSeconds": source_seconds,
            "policy": policy, "rate": rate,
            "targetEndLagSeconds": target_end_lag_seconds,
            "status": "fits" if not shorten and not impossible else
                      ("requires_spoken_revision" if not impossible else "cannot_fit"),
            "shortenGroupIds": shorten, "cannotFitGroupIds": impossible,
            "budgetedScheduleStatus": check["formalScheduleStatus"],
            "budgetedMaxLagViolations": check["maxLagViolations"],
            "groups": planned, "modelCalls": 0, "humanApproval": False,
            "mutatesText": False, "mutatesAudio": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fit", "budget"))
    parser.add_argument("--input", required=True, type=Path,
                        help="fit: {locale, rows:[{text, audioSeconds, audioSha256}]}; "
                             "budget: {sourceSeconds, groups:[...], policy?}")
    parser.add_argument("--speech-job", required=True, type=Path,
                        help="fit: the job whose units were measured; budget: the job being budgeted")
    parser.add_argument("--rate", type=Path, help="Speech-rate JSON from the fit command")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    value = json.loads(args.input.read_text(encoding="utf-8"))
    identity = synthesis_identity(json.loads(args.speech_job.read_text(encoding="utf-8")))
    if args.command == "fit":
        result = fit_rate(value["rows"], value["locale"], synthesis_identity=identity)
    else:
        if args.rate is None:
            parser.error("budget requires --rate")
        result = budget(value["sourceSeconds"], value["groups"],
                        json.loads(args.rate.read_text(encoding="utf-8")), value.get("policy"),
                        synthesis_identity=identity)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: result.get(key) for key in ("status", "locale", "shortenGroupIds")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
