#!/usr/bin/env python3
"""Full-decode one Layer 3 audio unit and bind it to an immutable speech job.

This is an audio integrity gate. It does not synthesize, screen pronunciation,
schedule playback, or grant listening or release approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
from typing import Any, Callable

try:
    from scripts import prepare_target_language_speech_job as speech
    from scripts import sermon_sentence_interpretation as identity
except ImportError:  # Direct execution via ``python scripts/...``.
    import prepare_target_language_speech_job as speech
    import sermon_sentence_interpretation as identity


RECEIPT_SCHEMA = "sermon-target-language-audio-unit-receipt-v1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _load_job(path: Path) -> dict[str, Any]:
    _require(path.is_file(), f"Missing speech job: {path}")
    job = json.loads(path.read_text(encoding="utf-8"))
    speech._validate_schema(job, "sermon-target-language-speech-job-v2.schema.json", "speech job")
    _require(job["synthesisEligible"] is True
             and job["status"] == "prepared_for_target_language_speech",
             "Speech job is not eligible for formal synthesis")
    inputs = {}
    for name, artifact in job["inputs"].items():
        source_path = Path(artifact["path"])
        _require(source_path.is_file() and identity.sha256(source_path) == artifact["sha256"],
                 f"Speech job input changed: {name}")
        value = json.loads(source_path.read_text(encoding="utf-8"))
        _require(identity.json_sha256(value) == artifact["jsonSha256"],
                 f"Speech job JSON input changed: {name}")
        inputs[name] = value
    source = inputs["englishSourcePackage"]
    anchor = inputs["anchorManifest"]
    candidate = inputs["targetLanguageCandidate"]
    policy = inputs["targetLanguagePolicy"]
    speech._validate_schema(candidate, "sermon-target-language-candidate-v2.schema.json", "target candidate")
    speech.validate_target_candidate(source, anchor, candidate)
    speech.validate_policy_binding(candidate, policy)
    speech.validate_human_review_receipt(source, anchor, candidate, inputs["humanReviewReceipt"])
    adapter = {"schemaVersion": speech.ADAPTER_SCHEMA, "targetLocale": job["targetLocale"]} | {
        key: value for key, value in job["adapter"].items() if key != "configSha256"
    }
    speech.validate_adapter(adapter, job["targetLocale"], inputs["speakerRegistry"])
    _require(adapter["capabilityStatus"] == "verified"
             and job["targetLocale"] == candidate["targetLocale"],
             "Speech job adapter or locale is not verified")
    locale = job["targetLocale"]
    _require([unit["unitIndex"] for unit in job["units"]] == list(range(len(job["units"])))
             and len(job["units"]) == len(candidate["groups"])
             and all(unit["translationGroupId"] == group["translationGroupId"]
                     and unit["sourceUnitIds"] == group["sourceUnitIds"]
                     and unit["text"] == group["targetText"]
                     and unit["outputRelativePath"] == f"languages/{locale}/audio/unit-{index:04d}.wav"
                     for index, (unit, group) in enumerate(zip(job["units"], candidate["groups"]))),
             "Speech job units, approved text, or locale audio paths changed")
    return job


def _bound_audio(job_path: Path, job: dict[str, Any], unit_index: int, audio_path: Path) -> dict[str, Any]:
    _require(0 <= unit_index < len(job["units"]), "Audio unit index is out of range")
    unit = job["units"][unit_index]
    expected = (job_path.parent / unit["outputRelativePath"]).resolve()
    _require(audio_path.resolve() == expected, "Audio path differs from job unit path")
    _require(audio_path.is_file() and audio_path.stat().st_size > 0, "Audio unit is missing or empty")
    return unit


def probe_full_decode(audio_path: Path, *, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    """Require one usable audio stream and decode all frames with ffmpeg."""
    probe = runner([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,codec_name,sample_rate,channels",
        "-of", "json", str(audio_path),
    ], capture_output=True, text=True, check=True, timeout=300)
    data = json.loads(probe.stdout)
    streams = [row for row in data.get("streams", []) if row.get("codec_type") == "audio"]
    _require(len(streams) == 1, "Audio unit must have exactly one audio stream")
    stream = streams[0]
    try:
        duration = float(data["format"]["duration"])
        sample_rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Audio unit has incomplete metadata") from exc
    codec = stream.get("codec_name")
    _require(math.isfinite(duration) and duration > 0 and sample_rate > 0
             and channels > 0 and isinstance(codec, str) and codec,
             "Audio unit has invalid duration, sample rate, channels, or codec")
    runner(["ffmpeg", "-xerror", "-v", "error", "-i", str(audio_path), "-f", "null", "-"],
           capture_output=True, text=True, check=True, timeout=300)
    return {"codec": codec, "sampleRate": sample_rate, "channels": channels,
            "durationSeconds": duration}


def build_receipt(job_path: Path, unit_index: int, audio_path: Path, *,
                  runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    job = _load_job(job_path)
    unit = _bound_audio(job_path, job, unit_index, audio_path)
    metadata = probe_full_decode(audio_path, runner=runner)
    receipt = {
        "schemaVersion": RECEIPT_SCHEMA,
        "targetLocale": job["targetLocale"],
        "jobJsonSha256": identity.json_sha256(job),
        "jobFileSha256": identity.sha256(job_path),
        "unitIndex": unit_index,
        "translationGroupId": unit["translationGroupId"],
        "sourceUnitIds": unit["sourceUnitIds"],
        "targetTextSha256": hashlib.sha256(unit["text"].encode("utf-8")).hexdigest(),
        "audioRelativePath": unit["outputRelativePath"],
        "audioSha256": identity.sha256(audio_path),
        **metadata,
        "fullDecode": "pass",
        "humanListeningReview": "pending",
        "releaseEligible": False,
    }
    speech._validate_schema(receipt, "sermon-target-language-audio-unit-receipt-v1.schema.json",
                            "audio unit receipt")
    return receipt


def validate_receipt(job_path: Path, unit_index: int, audio_path: Path,
                     receipt: dict[str, Any], *,
                     runner: Callable[..., Any] = subprocess.run) -> None:
    """Reject a receipt copied from changed text, job, locale, path, or audio bytes."""
    speech._validate_schema(receipt, "sermon-target-language-audio-unit-receipt-v1.schema.json",
                            "audio unit receipt")
    job = _load_job(job_path)
    unit = _bound_audio(job_path, job, unit_index, audio_path)
    expected = {
        "targetLocale": job["targetLocale"],
        "jobJsonSha256": identity.json_sha256(job),
        "jobFileSha256": identity.sha256(job_path),
        "unitIndex": unit_index,
        "translationGroupId": unit["translationGroupId"],
        "sourceUnitIds": unit["sourceUnitIds"],
        "targetTextSha256": hashlib.sha256(unit["text"].encode("utf-8")).hexdigest(),
        "audioRelativePath": unit["outputRelativePath"],
        "audioSha256": identity.sha256(audio_path),
    }
    _require(all(receipt[key] == value for key, value in expected.items()),
             "Audio unit receipt belongs to another job, text, path, or audio")
    metadata = probe_full_decode(audio_path, runner=runner)
    _require(all(receipt[key] == value for key, value in metadata.items()),
             "Audio unit receipt metadata differs from fully decoded audio")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--unit-index", type=int, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    _require(not args.out.exists(), "Use a new receipt path; audio receipts are immutable")
    receipt = build_receipt(args.job, args.unit_index, args.audio)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    identity.write_json(args.out, receipt)
    print(json.dumps({"status": "full_decode_pass", "receipt": str(args.out.resolve()),
                      "audioSha256": receipt["audioSha256"]}))


if __name__ == "__main__":
    main()
