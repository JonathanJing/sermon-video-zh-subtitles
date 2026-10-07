#!/usr/bin/env python3
"""Per-unit machine audio QC and the per-sentence repair ladder.

Runs right after each unit is synthesized, before the rolling schedule, so one
anomalous unit (2026-10-04 u172: a 2.96 s source rendered as 61 s) is isolated
and resynthesized instead of pushing every later sentence past the 8 s lag
target. Checks read only decoded PCM, the unit text and its source span; they
never edit audio or text and never grant human approval.

Repair ladder (Jony, 2026-10-06): a failing sentence is repaired twice, then
twice more, for at most four attempts. Attempts 1-2 resynthesize the same text
with a new seed; attempts 3-4 send a targeted spoken-text revision through the
normal Layer 2 chain before synthesizing again. After that the sentence is
published subtitle-only (no dub). The ladder counts per sentence, never per
sermon.
"""
from __future__ import annotations

import argparse
import array
import io
import json
import math
from pathlib import Path
import statistics
import sys
import wave

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.target_audio_predicted_schedule import speech_units

SCHEMA = "sermon-target-audio-auto-qc-v1"
REPAIR_LADDER = ("resynthesize_new_seed", "resynthesize_new_seed",
                 "revise_spoken_text", "revise_spoken_text")
MAX_REPAIR_ATTEMPTS = len(REPAIR_LADDER)
THRESHOLDS = {
    "frameSeconds": 0.02,
    "silenceDbfs": -45.0,
    "nearSilentRmsDbfs": -40.0,
    "maxSilenceRatio": 0.6,
    "maxInternalSilenceSeconds": 2.5,
    "maxClippingRatio": 0.002,
    "maxRatePerMedian": 2.5,
    "minRatePerMedian": 0.35,
    "minExcessSeconds": 3.0,
    "maxSourceRatio": 4.0,
    "minSourceExcessSeconds": 6.0,
    "asrMinSimilarity": 0.88,
}


def decode_pcm16(data: bytes) -> tuple[list[float], int]:
    """Decode a PCM16 WAV to mono floats in [-1, 1]."""
    with wave.open(io.BytesIO(data), "rb") as stream:
        if stream.getsampwidth() != 2:
            raise ValueError("Only PCM16 WAV is supported")
        channels, rate = stream.getnchannels(), stream.getframerate()
        samples = array.array("h", stream.readframes(stream.getnframes()))
    if sys.byteorder == "big":
        samples.byteswap()
    if channels > 1:
        mono = [sum(samples[i:i + channels]) / channels for i in range(0, len(samples), channels)]
    else:
        mono = list(samples)
    return [value / 32768.0 for value in mono], rate


def encode_pcm16(samples: list[float], rate: int) -> bytes:
    values = array.array("h", (max(-32768, min(32767, round(value * 32767))) for value in samples))
    if sys.byteorder == "big":
        values.byteswap()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(values.tobytes())
    return buffer.getvalue()


def _dbfs(value: float) -> float:
    return -120.0 if value <= 1e-6 else 20 * math.log10(value)


def signal_metrics(samples: list[float], rate: int, thresholds: dict = THRESHOLDS) -> dict:
    if rate <= 0:
        raise ValueError("Invalid sample rate")
    duration = len(samples) / rate
    if not samples:
        return {"durationSeconds": 0.0, "rmsDbfs": -120.0, "peakDbfs": -120.0, "clippingRatio": 0.0,
                "silenceRatio": 1.0, "leadingSilenceSeconds": 0.0, "trailingSilenceSeconds": 0.0,
                "longestInternalSilenceSeconds": 0.0}
    frame = max(1, round(thresholds["frameSeconds"] * rate))
    silent = []
    for start in range(0, len(samples), frame):
        chunk = samples[start:start + frame]
        silent.append(_dbfs(math.sqrt(sum(v * v for v in chunk) / len(chunk))) < thresholds["silenceDbfs"])
    leading = next((i for i, quiet in enumerate(silent) if not quiet), len(silent))
    trailing = next((i for i, quiet in enumerate(reversed(silent)) if not quiet), len(silent))
    longest = run = 0
    for quiet in silent[leading:len(silent) - trailing]:
        run = run + 1 if quiet else 0
        longest = max(longest, run)
    seconds_per_frame = frame / rate
    return {
        "durationSeconds": round(duration, 6),
        "rmsDbfs": round(_dbfs(math.sqrt(sum(v * v for v in samples) / len(samples))), 3),
        "peakDbfs": round(_dbfs(max(abs(v) for v in samples)), 3),
        "clippingRatio": round(sum(abs(v) >= 0.999 for v in samples) / len(samples), 6),
        "silenceRatio": round(sum(silent) / len(silent), 6),
        "leadingSilenceSeconds": round(leading * seconds_per_frame, 6),
        "trailingSilenceSeconds": round(trailing * seconds_per_frame, 6),
        "longestInternalSilenceSeconds": round(longest * seconds_per_frame, 6),
    }


def unit_issues(units: list[dict], locale: str, thresholds: dict = THRESHOLDS) -> list[list[str]]:
    """Issues per unit: ``{text, sourceSeconds, metrics}``; rates are job-relative."""
    rates = []
    for unit in units:
        units_count = speech_units(unit["text"], locale)
        if units_count >= 3 and unit["metrics"]["durationSeconds"] > 0:
            rates.append(unit["metrics"]["durationSeconds"] / units_count)
    median_rate = statistics.median(rates) if len(rates) >= 5 else None
    issues = []
    for unit in units:
        metrics, found = unit["metrics"], []
        seconds, source = metrics["durationSeconds"], float(unit["sourceSeconds"])
        count = speech_units(unit["text"], locale)
        if median_rate is not None and count >= 3:
            expected = median_rate * count
            if (seconds > thresholds["maxRatePerMedian"] * expected
                    and seconds - expected > thresholds["minExcessSeconds"]):
                found.append(f"duration_anomaly: {seconds:.2f}s vs expected {expected:.2f}s")
            if seconds < thresholds["minRatePerMedian"] * expected:
                found.append(f"truncated: {seconds:.2f}s vs expected {expected:.2f}s")
        if (source > 0 and seconds > thresholds["maxSourceRatio"] * source
                and seconds - source > thresholds["minSourceExcessSeconds"]):
            found.append(f"source_ratio_anomaly: {seconds:.2f}s for {source:.2f}s source")
        if metrics["rmsDbfs"] < thresholds["nearSilentRmsDbfs"]:
            found.append(f"near_silent: {metrics['rmsDbfs']} dBFS")
        if metrics["silenceRatio"] > thresholds["maxSilenceRatio"]:
            found.append(f"excess_silence: {metrics['silenceRatio']:.2f}")
        if metrics["longestInternalSilenceSeconds"] > thresholds["maxInternalSilenceSeconds"]:
            found.append(f"long_internal_pause: {metrics['longestInternalSilenceSeconds']:.2f}s")
        if metrics["clippingRatio"] > thresholds["maxClippingRatio"]:
            found.append(f"clipping: {metrics['clippingRatio']:.4f}")
        issues.append(found)
    return issues


def asr_decision(primary: float, secondary: float | None, threshold: float = THRESHOLDS["asrMinSimilarity"]) -> str:
    """Two-level back-ASR: the small ASR flags, a stronger ASR confirms.

    ``pass``: primary agrees, or the stronger ASR agrees (a small-ASR miss).
    ``needs_secondary_asr``: primary disagrees and no second opinion yet.
    ``fail``: both disagree, so the audio is treated as wrong.
    """
    for value in (primary, secondary):
        if value is not None and not 0 <= value <= 1:
            raise ValueError("ASR similarity must be within [0, 1]")
    if primary >= threshold:
        return "pass"
    if secondary is None:
        return "needs_secondary_asr"
    return "pass" if secondary >= threshold else "fail"


def next_action(failed_attempts: int) -> str:
    """Next step for a sentence that has failed ``failed_attempts`` times."""
    if type(failed_attempts) is not int or failed_attempts < 0:
        raise ValueError("Failed attempt count must be a non-negative integer")
    return REPAIR_LADDER[failed_attempts] if failed_attempts < MAX_REPAIR_ATTEMPTS else "subtitle_only"


def screen(units: list[dict], locale: str, thresholds: dict = THRESHOLDS) -> dict:
    """Screen one render attempt. Each unit: ``{groupId, text, sourceSeconds,
    wav (bytes) or metrics, asrPrimary?, asrSecondary?, priorFailedAttempts?}``."""
    rows = []
    for unit in units:
        metrics = unit.get("metrics")
        if metrics is None:
            metrics = signal_metrics(*decode_pcm16(unit["wav"]), thresholds)
        rows.append({**unit, "metrics": metrics})
    all_issues = unit_issues(rows, locale, thresholds)
    results = []
    for row, issues in zip(rows, all_issues):
        issues = list(issues)
        asr = None
        if row.get("asrPrimary") is not None:
            asr = asr_decision(row["asrPrimary"], row.get("asrSecondary"), thresholds["asrMinSimilarity"])
            if asr == "fail":
                issues.append("asr_mismatch_confirmed")
        prior = int(row.get("priorFailedAttempts", 0))
        if issues:
            status, action = "fail", next_action(prior)
        elif asr == "needs_secondary_asr":
            status, action = "pending_secondary_asr", "run_secondary_asr"
        else:
            status, action = "pass", "keep"
        results.append({"groupId": row["groupId"], "status": status, "issues": issues,
                        "asrDecision": asr, "failedAttempts": prior + (status == "fail"),
                        "nextAction": action, "metrics": row["metrics"]})
    return {"schemaVersion": SCHEMA, "locale": locale, "thresholds": thresholds,
            "maxRepairAttempts": MAX_REPAIR_ATTEMPTS,
            "status": "pass" if all(r["status"] == "pass" for r in results) else "requires_repair",
            "subtitleOnlyGroupIds": [r["groupId"] for r in results if r["nextAction"] == "subtitle_only"],
            "repairGroupIds": [r["groupId"] for r in results if r["nextAction"] in REPAIR_LADDER],
            "results": results, "humanApproval": False, "mutatesAudio": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path,
                        help="{locale, units:[{groupId, text, sourceSeconds, wavPath, asrPrimary?, "
                             "asrSecondary?, priorFailedAttempts?}]}")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    value = json.loads(args.input.read_text(encoding="utf-8"))
    units = []
    for unit in value["units"]:
        unit = dict(unit)
        unit["wav"] = Path(unit.pop("wavPath")).read_bytes()
        units.append(unit)
    result = screen(units, value["locale"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("status", "repairGroupIds", "subtitleOnlyGroupIds")}))


if __name__ == "__main__":
    main()
