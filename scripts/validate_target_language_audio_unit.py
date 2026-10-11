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
import os
from pathlib import Path
import subprocess
from typing import Any, Callable
import wave

try:
    from scripts import prepare_target_language_speech_job as speech
    from scripts import sermon_sentence_interpretation as identity
    from scripts import clip_timeline_map as timeline_map
except ImportError:  # Direct execution via ``python scripts/...``.
    import prepare_target_language_speech_job as speech
    import sermon_sentence_interpretation as identity
    import clip_timeline_map as timeline_map


RECEIPT_SCHEMA = "sermon-target-language-audio-unit-receipt-v1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _load_job(path: Path, *, strict_rubric: dict[str, Any] | None = None) -> dict[str, Any]:
    _require(path.is_file(), f"Missing speech job: {path}")
    job = json.loads(path.read_text(encoding="utf-8"))
    speech.validate_speech_job_schema(job)
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
    basis = inputs[speech.text_basis_input_key(job)]
    speech.validate_target_candidate(source, anchor, candidate,
                                     require_human_approval=not speech.machine_basis.is_text_waiver(basis))
    speech.validate_policy_binding(candidate, policy, strict_rubric=strict_rubric)
    _require(speech.validate_text_release_basis(source, anchor, candidate, basis)
             == speech.expected_text_policy(job) == job["renderContract"]["textPolicy"],
             "Speech job version differs from the candidate's release basis")
    adapter = {"schemaVersion": speech.ADAPTER_SCHEMA, "targetLocale": job["targetLocale"]} | {
        key: value for key, value in job["adapter"].items() if key != "configSha256"
    }
    speech.validate_adapter(
        adapter, job["targetLocale"], inputs["speakerRegistry"],
        clip_voice_authorization=inputs.get("clipVoiceAuthorization"),
        source_voice_authorization=inputs.get("sourceVoiceAuthorization"),
        clip_voice_capability=inputs.get("clipVoiceCapability"),
        source_package=source, candidate=candidate)
    if "clipTimelineMap" in inputs:
        timeline_map.validate(inputs["clipTimelineMap"], source, anchor)
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


class ValidatedJobContext:
    """Attempt-local strict admission; detect dependency writes before every unit.

    Hash all transitive artifact references at admission and completion. Stat
    identities are checked between units, including ctime (mtime restoration
    cannot conceal writes). This object is never persisted or accepted from JSON.
    """
    def __init__(self, path: Path, *, strict_rubric=None, extra_paths=(), extra_directories=()):
        self.path = path.resolve()
        self.files = {}
        self.aliases = {}
        self.directories = {Path(p).absolute(): self._inventory(Path(p).absolute()) for p in extra_directories}
        self.strict_rubric = strict_rubric
        self.strict_rubric_sha256 = identity.json_sha256(strict_rubric) if strict_rubric is not None else None
        pending = [self.path, *extra_paths,
                   *[root / name for root, names in self.directories.items() for name in names]]
        json_paths = {self.path}
        while pending:
            locator = Path(pending.pop()).absolute()
            source = locator.resolve()
            self.aliases[locator] = source
            if source in self.files:
                continue
            before = self._stat(source)
            digest = identity.sha256(source)
            value = None
            if source in json_paths or source.suffix == ".json":
                try:
                    value = json.loads(source.read_text(encoding="utf-8"))
                except (UnicodeError, json.JSONDecodeError):
                    pass
            self.files[source] = (before, digest)
            self._require_stat(source, before)
            def walk(value):
                if isinstance(value, dict):
                    if isinstance(value.get("path"), str) and "sha256" in value:
                        child = Path(value["path"])
                        # Historical runtime provenance can name a library on
                        # another host. It is not a live validation dependency.
                        if child.is_absolute() and (child.is_file() or "jsonSha256" in value):
                            _require(child.is_file() and identity.sha256(child) == value["sha256"],
                                     f"Frozen dependency hash differs: {child}")
                            if "jsonSha256" in value:
                                json_paths.add(child.resolve())
                            pending.append(child)
                    for item in value.values(): walk(item)
                elif isinstance(value, list):
                    for item in value: walk(item)
            walk(value)
        self.job = _load_job(self.path, strict_rubric=strict_rubric)
        self.job_file_sha256 = self.files[self.path][1]
        self.job_json_sha256 = identity.json_sha256(self.job)
        self.check()

    @staticmethod
    def _inventory(root):
        _require(root.is_dir(), f"Checkpoint directory unavailable: {root}")
        seen, paths = set(), []
        for current, dirs, files in os.walk(root, followlinks=True):
            resolved = Path(current).resolve()
            _require(resolved not in seen, f"Checkpoint directory aliases form a cycle or duplicate: {current}")
            seen.add(resolved)
            dirs.sort()
            paths.extend(str((Path(current) / name).relative_to(root)) for name in files)
        return tuple(sorted(paths))

    @staticmethod
    def _stat(path):
        st = path.stat()
        return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)

    def _require_stat(self, path, expected):
        _require(self._stat(path) == expected, f"Frozen dependency changed: {path}")

    def check(self, *, full=False):
        for locator, resolved in self.aliases.items():
            _require(locator.resolve() == resolved, f"Frozen dependency alias changed: {locator}")
        for root, names in self.directories.items():
            _require(self._inventory(root) == names, f"Frozen checkpoint directory changed: {root}")
        _require((identity.json_sha256(self.strict_rubric) if self.strict_rubric is not None else None)
                 == self.strict_rubric_sha256, "Frozen strict rubric changed")
        for path, (stat, digest) in self.files.items():
            self._require_stat(path, stat)
            if full:
                _require(identity.sha256(path) == digest, f"Frozen dependency changed: {path}")
        _require(identity.json_sha256(self.job) == self.job_json_sha256,
                 "Prevalidated job context was mutated")


def _bound_audio(job_path: Path, job: dict[str, Any], unit_index: int, audio_path: Path) -> dict[str, Any]:
    _require(0 <= unit_index < len(job["units"]), "Audio unit index is out of range")
    unit = job["units"][unit_index]
    expected = (job_path.parent / unit["outputRelativePath"]).resolve()
    _require(audio_path.resolve() == expected, "Audio path differs from job unit path")
    _require(audio_path.is_file() and audio_path.stat().st_size > 0, "Audio unit is missing or empty")
    return unit


def probe_full_decode(audio_path: Path, *, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    """Require one usable audio stream and decode all frames."""
    try:
        probe = runner([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,codec_name,sample_rate,channels",
        "-of", "json", str(audio_path),
        ], capture_output=True, text=True, check=True, timeout=300)
    except FileNotFoundError:
        return probe_pcm_wav(audio_path)
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
    try:
        runner(["ffmpeg", "-xerror", "-v", "error", "-i", str(audio_path), "-f", "null", "-"],
               capture_output=True, text=True, check=True, timeout=300)
    except FileNotFoundError:
        return probe_pcm_wav(audio_path)
    return {"codec": codec, "sampleRate": sample_rate, "channels": channels,
            "durationSeconds": duration}


def probe_pcm_wav(path: Path) -> dict[str, Any]:
    """Fully read the PCM16 WAV bytes when ffmpeg tools are unavailable."""
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            rate = handle.getframerate()
            frames = handle.getnframes()
            width = handle.getsampwidth()
            codec = handle.getcomptype()
            signal = handle.readframes(frames)
            _require(codec == "NONE" and width == 2 and channels == 1 and rate > 0
                     and frames > 0 and len(signal) == frames * channels * width,
                     "WAV full decode or PCM16 format failed")
            _require(not handle.readframes(1), "WAV has extra audio frames")
        return {"codec": "pcm_s16le", "sampleRate": rate, "channels": channels,
                "durationSeconds": frames / rate}
    except (OSError, EOFError, wave.Error) as exc:
        raise ValueError(f"WAV full decode failed: {path}: {exc}") from exc


def build_receipt(job_path: Path, unit_index: int, audio_path: Path, *,
                  runner: Callable[..., Any] = subprocess.run,
                  validated_job: dict[str, Any] | None = None,
                  validated_job_file_sha256: str | None = None,
                  strict_rubric: dict[str, Any] | None = None,
                  validated_context: ValidatedJobContext | None = None) -> dict[str, Any]:
    if validated_context is not None:
        _require(validated_context.path == job_path.resolve(), "Prevalidated context job path differs")
        validated_context.check()
        validated_job = validated_context.job
        validated_job_file_sha256 = validated_context.job_file_sha256
    job = _load_job(job_path, strict_rubric=strict_rubric) if validated_job is None else validated_job
    _require(validated_job is None or validated_job_file_sha256 is not None,
             "Prevalidated job requires its file hash")
    job_file_sha256 = (identity.sha256(job_path) if validated_job is None
                       else validated_job_file_sha256)
    unit = _bound_audio(job_path, job, unit_index, audio_path)
    metadata = probe_full_decode(audio_path, runner=runner)
    receipt = {
        "schemaVersion": RECEIPT_SCHEMA,
        "targetLocale": job["targetLocale"],
        "jobJsonSha256": identity.json_sha256(job),
        "jobFileSha256": job_file_sha256,
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
                     runner: Callable[..., Any] = subprocess.run,
                     validated_job: dict[str, Any] | None = None,
                     validated_job_file_sha256: str | None = None,
                     strict_rubric: dict[str, Any] | None = None,
                     validated_context: ValidatedJobContext | None = None) -> None:
    """Reject a receipt copied from changed text, job, locale, path, or audio bytes."""
    if validated_context is not None:
        _require(validated_context.path == job_path.resolve(), "Prevalidated context job path differs")
        validated_context.check()
        validated_job = validated_context.job
        validated_job_file_sha256 = validated_context.job_file_sha256
    speech._validate_schema(receipt, "sermon-target-language-audio-unit-receipt-v1.schema.json",
                            "audio unit receipt")
    job = _load_job(job_path, strict_rubric=strict_rubric) if validated_job is None else validated_job
    _require(validated_job is None or validated_job_file_sha256 is not None,
             "Prevalidated job requires its file hash")
    job_file_sha256 = (identity.sha256(job_path) if validated_job is None
                       else validated_job_file_sha256)
    unit = _bound_audio(job_path, job, unit_index, audio_path)
    expected = {
        "targetLocale": job["targetLocale"],
        "jobJsonSha256": identity.json_sha256(job),
        "jobFileSha256": job_file_sha256,
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
    parser.add_argument("--strict-rubric", type=Path, help="Explicit frozen rubric for strict-v3 policy validation")
    parser.add_argument("--unit-index", type=int, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    _require(not args.out.exists(), "Use a new receipt path; audio receipts are immutable")
    receipt = build_receipt(args.job, args.unit_index, args.audio,
                            strict_rubric=speech._load(args.strict_rubric) if args.strict_rubric else None)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    identity.write_json(args.out, receipt)
    print(json.dumps({"status": "full_decode_pass", "receipt": str(args.out.resolve()),
                      "audioSha256": receipt["audioSha256"]}))


if __name__ == "__main__":
    main()
