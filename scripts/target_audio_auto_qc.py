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

``check_track`` runs once the track is assembled: the PCM master must be the
screened unit audio placed by the schedule, and an MP3 track must follow it.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import io
import json
import math
import operator
from pathlib import Path
import statistics
import subprocess
import sys
import wave

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import machine_quality_waiver as waiver
from scripts import machine_repair_ledger as ledger
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
    "maxLeadingSilenceSeconds": 1.0,
    "maxTrailingSilenceSeconds": 1.5,
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
        # Edge silence adds lag without lowering the silence ratio much.
        if metrics["leadingSilenceSeconds"] > thresholds["maxLeadingSilenceSeconds"]:
            found.append(f"leading_silence: {metrics['leadingSilenceSeconds']:.2f}s")
        if metrics["trailingSilenceSeconds"] > thresholds["maxTrailingSilenceSeconds"]:
            found.append(f"trailing_silence: {metrics['trailingSilenceSeconds']:.2f}s")
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


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def transcript_similarity(text: str, recognized: str, locale: str) -> float:
    """The calibrated screener's score of what an ASR heard against the expected text."""
    # Lazy: the screener imports the speech-job module, which reaches this one.
    from scripts.screen_target_language_audio_units import score
    return score(text, recognized, locale, 1.0)[0]


def asr_opinion(recognized: str, *, audio: bytes, text: str, locale: str, model: str, settings: dict,
                model_revision: str | None = None) -> dict:
    """An ASR result bound to the exact audio bytes, expected text, model and runtime.

    The opinion keeps what the ASR heard; its similarity is always the
    screener's score of that transcript, never a number the transport reports,
    so QC and the waiver can rescore it.

    ``settings`` is the normalized ASR runtime behind the score: backend,
    language and prompt options, decoding, cache namespace and similarity
    scoring. Its hash joins the calibrated identity, so the same model run
    another way does not reuse the calibration. For the primary role, use
    :func:`screening_asr_settings` of the screening receipt the score came from.
    """
    if not isinstance(settings, dict) or not settings:
        raise ValueError("An ASR opinion needs its runtime settings")
    if not isinstance(recognized, str):
        raise ValueError("An ASR opinion needs the recognized transcript")
    return {"similarity": transcript_similarity(text, recognized, locale), "recognized": recognized,
            "audioSha256": _sha256(audio),
            "textSha256": _sha256(text.encode("utf-8")), "model": model,
            "modelRevision": model_revision, "settingsSha256": waiver.json_sha256(settings)}


def screening_asr_settings(screening: dict) -> dict:
    """The primary ASR runtime a full-package screening receipt records.

    Only a v2 receipt records its runtime (batching, decoding, device, inference
    runtime, screener implementation, scoring); a v1 receipt cannot back a
    machine waiver. The recorded settings must hash to the receipt's
    ``asrSettingsSha256`` and agree with its top-level model and threshold.
    """
    if not isinstance(screening, dict) or screening.get("schemaVersion") != "sermon-target-language-audio-screening-v2":
        raise ValueError("ASR screening does not record its runtime settings; rescreen with screening v2")
    settings = screening.get("asrSettings")
    if (not isinstance(settings, dict) or not settings
            or screening.get("asrSettingsSha256") != waiver.json_sha256(settings)
            or settings.get("model") != screening.get("model")
            or settings.get("modelRevision") != screening.get("modelRevision")
            or settings.get("minSimilarity") != screening.get("minSimilarity")
            or settings.get("batchSize") != screening.get("transcriptionBatchSize", 1)):
        raise ValueError("ASR screening runtime settings disagree with the receipt")
    return settings


def _model(opinion: dict | None) -> dict | None:
    return None if opinion is None else {"model": opinion["model"], "modelRevision": opinion.get("modelRevision")}


def bound_opinion(opinion: dict | None, audio_sha: str | None, text: str,
                  locale: str) -> tuple[dict | None, bool]:
    """``(opinion, stale)``: an opinion about other audio or text counts as not run;
    a current one must score as its own transcript does."""
    text_sha = _sha256(text.encode("utf-8"))
    if opinion is None:
        return None, False
    if (not isinstance(opinion, dict) or not isinstance(opinion.get("model"), str) or not opinion["model"]
            or type(opinion.get("similarity")) not in (int, float)
            or opinion.get("modelRevision") is not None and not isinstance(opinion["modelRevision"], str)
            or not isinstance(opinion.get("recognized"), str)
            or not isinstance(opinion.get("settingsSha256"), str) or len(opinion["settingsSha256"]) != 64):
        raise ValueError("An ASR opinion needs similarity, recognized, audioSha256, textSha256, model "
                         "and settingsSha256")
    if opinion.get("audioSha256") != audio_sha or opinion.get("textSha256") != text_sha:
        return None, True
    if opinion["similarity"] != transcript_similarity(text, opinion["recognized"], locale):
        raise ValueError("An ASR similarity must be the score of its own transcript")
    return opinion, False


def next_action(failed_attempts: int) -> str:
    """Next step for a sentence that has failed ``failed_attempts`` times."""
    if type(failed_attempts) is not int or failed_attempts < 0:
        raise ValueError("Failed attempt count must be a non-negative integer")
    return REPAIR_LADDER[failed_attempts] if failed_attempts < MAX_REPAIR_ATTEMPTS else "subtitle_only"


def screen(units: list[dict], locale: str, thresholds: dict = THRESHOLDS, *,
           repair_position: dict | None = None) -> dict:
    """Screen one render attempt. Each unit: ``{groupId, text, sourceSeconds,
    wav (bytes), asr: {primary, secondary?}, sourceUnitIds?}``,
    where each ASR opinion comes from :func:`asr_opinion`.

    ``repair_position`` is the audio repair ledger head
    (``machine_repair_ledger.position``); failed attempts count from it per
    frozen English unit (``sourceUnitIds`` is then required), and the receipt
    must be appended there. Without it counts start at zero and the receipt
    cannot back a waiver.

    Acoustic metrics are always decoded from the unit's WAV bytes, never taken
    from the caller, so they describe the audio the result is bound to. An
    opinion counts only for the exact audio bytes and text it names, so a
    score kept from an earlier render is ignored. A unit without a current
    primary opinion has had no content check and stays ``pending_primary_asr``
    instead of passing on acoustics alone."""
    rows = []
    for unit in units:
        if "priorFailedAttempts" in unit:
            raise ValueError("Failed attempts come from the repair ledger, not from the caller")
        if not isinstance(unit.get("wav"), (bytes, bytearray)) or "metrics" in unit:
            raise ValueError("Audio QC decodes each unit's WAV bytes; supplied metrics are not accepted")
        # The source-ratio check needs the real span; the waiver compares it with the frozen anchor.
        source = unit.get("sourceSeconds")
        if isinstance(source, bool) or not isinstance(source, (int, float)) or not math.isfinite(source) or source <= 0:
            raise ValueError(f"Unit source span must be a positive number of seconds: {unit.get('groupId')}")
        rows.append({**unit, "metrics": signal_metrics(*decode_pcm16(unit["wav"]), thresholds)})
    all_issues = unit_issues(rows, locale, thresholds)
    results = []
    for row, issues in zip(rows, all_issues):
        issues = list(issues)
        if "asrPrimary" in row or "asrSecondary" in row:
            raise ValueError("Bare ASR scores are not accepted; pass asr opinions bound to the audio")
        # The waiver binds these exact bytes and both ASR opinions.
        audio_sha = _sha256(row["wav"])
        text_sha = _sha256(row["text"].encode("utf-8"))
        primary, primary_stale = bound_opinion((row.get("asr") or {}).get("primary"), audio_sha, row["text"], locale)
        secondary, secondary_stale = bound_opinion((row.get("asr") or {}).get("secondary"), audio_sha,
                                                   row["text"], locale)
        if primary and secondary and _model(primary) == _model(secondary):
            raise ValueError("The secondary ASR must be a different model from the primary")
        asr = None
        if primary is not None:
            asr = asr_decision(primary["similarity"], None if secondary is None else secondary["similarity"],
                               thresholds["asrMinSimilarity"])
            if asr == "fail":
                issues.append("asr_mismatch_confirmed")
        prior = ledger.prior(repair_position, row.get("sourceUnitIds"))
        if issues:
            status, action = "fail", next_action(prior)
        elif asr is None:
            status, action = "pending_primary_asr", "run_primary_asr"
        elif asr == "needs_secondary_asr":
            status, action = "pending_secondary_asr", "run_secondary_asr"
        else:
            status, action = "pass", "keep"
        results.append({"groupId": row["groupId"], "status": status, "issues": issues,
                        "asrDecision": asr, "asrPrimary": None if primary is None else primary["similarity"],
                        "asrSecondary": None if secondary is None else secondary["similarity"],
                        "asrPrimaryRecognized": None if primary is None else primary["recognized"],
                        "asrSecondaryRecognized": None if secondary is None else secondary["recognized"],
                        "asrPrimaryModel": _model(primary), "asrSecondaryModel": _model(secondary),
                        "asrPrimarySettingsSha256": None if primary is None else primary["settingsSha256"],
                        "asrSecondarySettingsSha256": None if secondary is None else secondary["settingsSha256"],
                        "staleAsr": [name for name, stale in (("primary", primary_stale),
                                                              ("secondary", secondary_stale)) if stale],
                        "audioSha256": audio_sha, "textSha256": text_sha,
                        "sourceSeconds": float(row["sourceSeconds"]),
                        "failedAttempts": prior + (status == "fail"), "sourceUnitIds": row.get("sourceUnitIds"),
                        "nextAction": action, "metrics": row["metrics"]})
    return {"schemaVersion": SCHEMA, "locale": locale, "thresholds": thresholds,
            "implementationSha256": waiver.implementation_sha256(),
            "maxRepairAttempts": MAX_REPAIR_ATTEMPTS, "repairLedger": repair_position,
            "status": "pass" if all(r["status"] == "pass" for r in results) else "requires_repair",
            "subtitleOnlyGroupIds": [r["groupId"] for r in results if r["nextAction"] == "subtitle_only"],
            "repairGroupIds": [r["groupId"] for r in results if r["nextAction"] in REPAIR_LADDER],
            "results": results, "humanApproval": False, "mutatesAudio": False}


TRACK_CHECK_SCHEMA = "sermon-target-audio-track-check-v1"
# Envelope diagnostics alone cannot identify audio content. Compare decoded
# waveforms in every audible window as well, allowing only lossy-codec error.
TRACK_ENVELOPE = {"sampleRate": 12000, "windowSeconds": 0.05, "floorDbfs": -60.0,
                  "maxWindowDeltaDb": 6.0, "maxDeviantShare": 0.02, "maxLengthDeltaSeconds": 0.1,
                  "minWaveformCorrelation": 0.94, "maxRelativeWaveformError": 0.35,
                  "audibleDbfs": -40.0}


def _pcm16_frames(data: bytes) -> tuple[bytes, int, int]:
    with wave.open(io.BytesIO(data), "rb") as stream:
        if stream.getsampwidth() != 2 or stream.getcomptype() != "NONE":
            raise ValueError("Only PCM16 WAV is supported")
        return stream.readframes(stream.getnframes()), stream.getframerate(), stream.getnchannels()


def scheduled_track(entries: list[dict], units: list[bytes], length_frames: int) -> tuple[bytes, int, int]:
    """The PCM16 track the renderer must write: each unit at its planned start, silence elsewhere."""
    decoded = [_pcm16_frames(unit) for unit in units]
    formats = {(rate, channels) for _, rate, channels in decoded}
    if len(formats) != 1:
        raise ValueError("Units differ in sample rate or channel count")
    (rate, channels), = formats
    frame = channels * 2
    track = bytearray(length_frames * frame)
    for entry, (pcm, _, _) in zip(entries, decoded, strict=True):
        offset = round(entry["plannedStart"] * rate) * frame
        if offset < 0 or offset + len(pcm) > len(track):
            raise ValueError(f"Scheduled unit exceeds the track: {entry['textGroupId']}")
        track[offset:offset + len(pcm)] = pcm
    return bytes(track), rate, channels


def _mono_pcm(path: Path, rate: int) -> array.array:
    decoded = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(path), "-map", "0:a:0",
                              "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
                             capture_output=True, check=True, timeout=900).stdout
    samples = array.array("h")
    samples.frombytes(decoded[:len(decoded) - len(decoded) % 2])
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


def _envelope(samples: array.array, rate: int, settings: dict) -> list[float]:
    size = max(1, round(settings["windowSeconds"] * rate))
    floor, full_scale = settings["floorDbfs"], 32768.0 ** 2
    levels = []
    for start in range(0, len(samples), size):
        chunk = samples[start:start + size]
        power = sum(map(operator.mul, chunk, chunk)) / len(chunk)
        levels.append(max(floor, 10 * math.log10(power / full_scale)) if power > 0 else floor)
    return levels


def _waveform_comparison(reference: array.array, compressed: array.array, rate: int, settings: dict) -> dict:
    """Compare signal content, not its RMS envelope; reject any changed audible window.

    ffmpeg removes MP3 encoder delay from timestamped output. No arbitrary
    time shift or per-window gain normalization is allowed here: those could
    hide a replaced or moved phrase. Quiet codec ringing is below the audible
    floor; audible windows require both correlation and bounded sample error.
    """
    size = max(1, round(settings["windowSeconds"] * rate))
    floor_power = 32768.0 ** 2 * 10 ** (settings["audibleDbfs"] / 10)
    windows, failed, correlations, errors = 0, 0, [], []
    for start in range(0, max(len(reference), len(compressed)), size):
        left, right = reference[start:start + size], compressed[start:start + size]
        count = max(len(left), len(right))
        left_power, right_power = sum(v * v for v in left), sum(v * v for v in right)
        if max(left_power, right_power) / count < floor_power:
            continue
        windows += 1
        dot = sum(a * b for a, b in zip(left, right))
        correlation = dot / math.sqrt(left_power * right_power) if left_power and right_power else 0.0
        # Unpaired samples count as error, rather than disappearing at the end.
        error_power = max(0.0, left_power + right_power - 2 * dot)
        error = math.sqrt(error_power / max(left_power, floor_power * count))
        correlations.append(correlation)
        errors.append(error)
        if correlation < settings["minWaveformCorrelation"] or error > settings["maxRelativeWaveformError"]:
            failed += 1
    return {"audibleWindows": windows, "deviantWindows": failed,
            "minCorrelation": round(min(correlations, default=0.0), 6),
            "maxRelativeError": round(max(errors, default=0.0), 6)}


def check_track(package: dict, *, decode=_mono_pcm, settings: dict = TRACK_ENVELOPE) -> dict:
    """Prove the package track is the scheduled placement of its screened unit audio.

    Unit QC and ASR look at unit WAVs; this binds them to the assembled track.
    The PCM master (the track itself, or the ``.wav`` beside an MP3) must equal
    the units placed at their planned starts, sample for sample. An MP3 track
    must then preserve that master's decoded waveform in every audible window."""
    def read(artifact: dict, label: str) -> bytes:
        data = Path(artifact["path"]).read_bytes()
        if _sha256(data) != artifact["sha256"]:
            raise ValueError(f"{label} bytes differ from the package")
        return data

    schedule_bytes = read(package["schedule"], "Schedule")
    schedule = json.loads(schedule_bytes)
    if waiver.json_sha256(schedule) != package["schedule"]["jsonSha256"]:
        raise ValueError("Schedule JSON differs from the package")
    entries, units = schedule["entries"], package["units"]
    if [entry["textGroupId"] for entry in entries] != [unit["textGroupId"] for unit in units]:
        raise ValueError("Schedule entries differ from the package units")
    track_path = Path(package["track"]["path"])
    read(package["track"], "Track")
    master_path = track_path if track_path.suffix.lower() == ".wav" else track_path.with_suffix(".wav")
    master = master_path.read_bytes()
    master_pcm, rate, channels = _pcm16_frames(master)
    expected, unit_rate, unit_channels = scheduled_track(
        entries, [read(unit["audio"], f"Unit {unit['textGroupId']} audio") for unit in units],
        len(master_pcm) // (channels * 2))
    issues = []
    if (unit_rate, unit_channels) != (rate, channels) or expected != master_pcm:
        issues.append("pcm_track_differs_from_scheduled_units")
    envelope = waveform = None
    if master_path != track_path:
        low = settings["sampleRate"]
        reference_pcm, compressed_pcm = (decode(path, low) for path in (master_path, track_path))
        waveform = _waveform_comparison(reference_pcm, compressed_pcm, low, settings)
        reference, compressed = (_envelope(pcm, low, settings) for pcm in (reference_pcm, compressed_pcm))
        count = min(len(reference), len(compressed))
        deltas = [abs(a - b) for a, b in zip(reference[:count], compressed[:count])]
        deviant = sum(delta > settings["maxWindowDeltaDb"] for delta in deltas)
        envelope = {"windows": count, "deviantWindows": deviant, "maxDeltaDb": round(max(deltas, default=0.0), 3),
                    "lengthDeltaSeconds": round(abs(len(reference) - len(compressed)) * settings["windowSeconds"], 3)}
        if (not count or deviant > settings["maxDeviantShare"] * count
                or not waveform["audibleWindows"] or waveform["deviantWindows"]):
            issues.append("compressed_track_differs_from_pcm_master")
        if envelope["lengthDeltaSeconds"] > settings["maxLengthDeltaSeconds"] + settings["windowSeconds"]:
            issues.append("compressed_track_length_differs")
    return {"schemaVersion": TRACK_CHECK_SCHEMA, "status": "fail" if issues else "pass", "issues": issues,
            "targetLocale": package["targetLocale"],
            "targetLanguageAudioPackageJsonSha256": waiver.json_sha256(package),
            "trackSha256": package["track"]["sha256"], "pcmMasterSha256": _sha256(master),
            "scheduleJsonSha256": package["schedule"]["jsonSha256"],
            "unitAudioSha256s": [unit["audio"]["sha256"] for unit in units],
            "method": {"pcm": "sample_exact_scheduled_placement",
                       "compressed": None if envelope is None else "decoded_waveform"},
            "settings": settings, "envelope": envelope, "waveform": waveform,
            "implementationSha256": waiver.implementation_sha256(), "humanApproval": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track-package", type=Path,
                        help="Audio package JSON: check its assembled track instead of screening units")
    parser.add_argument("--input", type=Path,
                        help="{locale, units:[{groupId, text, sourceSeconds, wavPath, asr:{primary, "
                             "secondary?}, sourceUnitIds}]}; each ASR opinion is {similarity, recognized, "
                             "audioSha256, textSha256, model, modelRevision?, settingsSha256}")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--repair-ledger-root", type=Path,
                        help="Durable repair ledger root; with --source and --anchor, counts failed attempts "
                             "from it and appends this run (required for a waiver)")
    parser.add_argument("--source", type=Path, help="English source package the audio was rendered from")
    parser.add_argument("--anchor", type=Path, help="Frozen anchor manifest of that source")
    args = parser.parse_args()
    if (args.track_package is None) == (args.input is None):
        parser.error("pass exactly one of --input or --track-package")
    if args.track_package is not None:
        result = check_track(json.loads(args.track_package.read_text(encoding="utf-8")))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        print(json.dumps({key: result[key] for key in ("status", "issues")}))
        return
    value = json.loads(args.input.read_text(encoding="utf-8"))
    units = []
    for unit in value["units"]:
        unit = dict(unit)
        unit["wav"] = Path(unit.pop("wavPath")).read_bytes()
        units.append(unit)
    repair_lineage = position = None
    if args.repair_ledger_root is not None:
        if args.source is None or args.anchor is None:
            parser.error("--repair-ledger-root needs --source and --anchor")
        repair_lineage = ledger.lineage("audio", value["locale"],
                                        waiver.json_sha256(json.loads(args.source.read_text(encoding="utf-8"))),
                                        waiver.json_sha256(json.loads(args.anchor.read_text(encoding="utf-8"))))
        position = ledger.position(repair_lineage, ledger.load(args.repair_ledger_root, repair_lineage))
    result = screen(units, value["locale"], repair_position=position)
    if repair_lineage is not None:
        # Claim the ledger position first: a concurrent run from the same head fails here.
        ledger.append(args.repair_ledger_root, repair_lineage, result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("status", "repairGroupIds", "subtitleOnlyGroupIds")}))


if __name__ == "__main__":
    main()
