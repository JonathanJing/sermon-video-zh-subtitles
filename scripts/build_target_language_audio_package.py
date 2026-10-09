#!/usr/bin/env python3
"""Build a fail-closed Layer 3 package from measured, hash-bound render evidence.

The renderer and ASR are separate producers. This command never synthesizes,
alters approved text, schedules speech, or grants human listening approval.
All paths in the render manifest are relative to its artifact root.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import difflib
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

try:
    from scripts import sermon_accounting as accounting
    from scripts import prepare_target_language_speech_job as speech
    from scripts import sermon_sentence_interpretation as interpretation
    from scripts import clip_timeline_map as timeline_map
    from scripts import validate_target_language_audio_unit as unit_integrity
    from scripts import screen_target_language_audio_units as audio_screen
except ImportError:
    import sermon_accounting as accounting
    import prepare_target_language_speech_job as speech
    import sermon_sentence_interpretation as interpretation
    import clip_timeline_map as timeline_map
    import validate_target_language_audio_unit as unit_integrity
    import screen_target_language_audio_units as audio_screen


SCHEMA = "sermon-target-language-audio-package-v1"
RENDER_SCHEMA = "sermon-target-language-render-manifest-v1"
RECEIPT_SCHEMA = unit_integrity.RECEIPT_SCHEMA
EPSILON = 0.035
MP3_CONTAINER_PADDING_SECONDS = 0.10


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_sha256(value: object) -> str:
    return interpretation.json_sha256(value)


def checked_path(root: Path, relative: object) -> Path:
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(),
            "Artifact path must be relative")
    path = (root / relative).resolve()
    require(path.is_relative_to(root.resolve()) and path.is_file() and path.stat().st_size > 0,
            f"Artifact is missing or escapes root: {relative}")
    return path


def checked_artifact(root: Path, value: object, *, json_artifact: bool = False) -> dict[str, str]:
    require(isinstance(value, dict), "Artifact receipt must be an object")
    path = checked_path(root, value.get("path"))
    require(file_sha256(path) == value.get("sha256"), f"Artifact SHA-256 mismatch: {path}")
    result = {"path": str(path), "sha256": value["sha256"]}
    if json_artifact:
        require(json_sha256(read_object(path)) == value.get("jsonSha256"),
                f"Artifact JSON SHA-256 mismatch: {path}")
        result["jsonSha256"] = value["jsonSha256"]
    return result


def probe_audio(path: Path) -> tuple[float, int, int]:
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,sample_rate,channels", "-of", "json", str(path),
        ], capture_output=True, text=True, check=True, timeout=90)
        info = json.loads(result.stdout)
        streams = [item for item in info.get("streams", []) if item.get("codec_type") == "audio"]
        require(len(streams) == 1, f"Expected exactly one audio stream: {path}")
        duration = float(info.get("format", {}).get("duration", 0))
        sample_rate = int(streams[0].get("sample_rate", 0))
        channels = int(streams[0].get("channels", 0))
        require(math.isfinite(duration) and duration > 0 and sample_rate > 0 and channels > 0,
                f"Invalid audio stream: {path}")
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(path),
                        "-f", "null", "-"], capture_output=True, text=True, check=True, timeout=300)
        return duration, sample_rate, channels
    except FileNotFoundError:
        decoded = unit_integrity.probe_pcm_wav(path)
        return decoded["durationSeconds"], decoded["sampleRate"], decoded["channels"]
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError(f"Audio probe/full decode failed: {path}: {exc}") from exc


def near(actual: float, expected: object, label: str) -> None:
    require(isinstance(expected, (int, float)) and not isinstance(expected, bool)
            and math.isfinite(expected) and abs(actual - expected) <= EPSILON,
            f"{label} differs from measured audio")


def validate_anchor_exception(source: dict[str, Any], anchor: dict[str, Any],
                              candidate: dict[str, Any], paths: dict[str, Path]) -> bool:
    """Accept only the separately recorded, hash-bound single scripture exception."""
    path = paths.get("anchor_exception_receipt")
    if path is None:
        return False
    receipt = read_object(path)
    version = receipt.get("schemaVersion")
    schema_name = {"sermon-human-anchor-exception-receipt-v1": "sermon-human-anchor-exception-receipt-v1.schema.json",
                   "sermon-human-anchor-exception-receipt-v2": "sermon-human-anchor-exception-receipt-v2.schema.json"}.get(version)
    require(schema_name is not None, "Unsupported anchor exception receipt")
    schema = read_object(Path(__file__).parents[1] / "schemas" / schema_name)
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt))
    require(not errors, f"Anchor exception receipt schema error: {errors[0].message if errors else ''}")
    locale = candidate.get("targetLocale")
    require(locale in {"zh-Hans", "ko", "es"}, "Anchor exception locale is unsupported")
    require((version == "sermon-human-anchor-exception-receipt-v1" and locale == "zh-Hans")
            or (version == "sermon-human-anchor-exception-receipt-v2" and receipt.get("targetLocale") == locale),
            "Anchor exception is not bound to this locale")
    for key, name, value in (("englishSourcePackage", "source", source),
                             ("anchorManifest", "anchor", anchor)):
        require(receipt[key]["sha256"] == file_sha256(paths[name])
                and receipt[key]["jsonSha256"] == json_sha256(value),
                f"Anchor exception binding mismatch: {key}")
    if version == "sermon-human-anchor-exception-receipt-v2":
        require(receipt["candidate"]["sha256"] == file_sha256(paths["candidate"])
                and receipt["candidate"]["jsonSha256"] == json_sha256(candidate),
                "Anchor exception binding mismatch: candidate")
    issues = anchor.get("issues")
    require(source.get("anchors", {}).get("issueCount") == 1
            and isinstance(issues, list) and len(issues) == 1,
            "Anchor exception requires exactly one unresolved anchor issue")
    issue = issues[0]
    require(issue == receipt["acceptedIssue"]
            and issue.get("type") == "clause_unit_exceeds_target_without_safe_boundary"
            and issue.get("sourceSentenceId") == "0-s202"
            and issue.get("maximumSeconds") == 8.0
            and issue.get("durationSeconds") == 9.199951
            and issue.get("english") == "‘Don’t harm the earth or the sea or the trees until we seal the servants of our God on their foreheads.’",
            "Anchor exception differs from the authorized complete scripture sentence")
    return True


def validate_job(source: dict[str, Any], anchor: dict[str, Any], candidate: dict[str, Any],
                 job: dict[str, Any], adapter: dict[str, Any], policy: dict[str, Any],
                 human_receipt: dict[str, Any], registry: dict[str, Any],
                 clip_voice_authorization: dict[str, Any] | None,
                 clip_voice_capability: dict[str, Any] | None,
                 clip_timeline: dict[str, Any],
                 paths: dict[str, Path], *,
                 source_voice_authorization: dict[str, Any] | None = None,
                 strict_rubric: dict[str, Any] | None = None) -> None:
    machine = speech.machine_basis.is_text_waiver(human_receipt)
    speech.validate_target_candidate(source, anchor, candidate, require_human_approval=not machine)
    anchor_exception = validate_anchor_exception(source, anchor, candidate, paths)
    review = source.get("review", {})
    window = source.get("source", {}).get("approvedWindow", {})
    require(review.get("humanApproval") is True
            and all(review.get("checks", {}).get(check) == "approved" for check in (
                "sourceIdentity", "transcriptCompleteness", "wordAlignment",
                "sentenceAndPauseBoundaries"))
            and window.get("status") == "approved"
            and window.get("humanApproval") is True
            and (source.get("anchors", {}).get("issueCount") == 0 or anchor_exception),
            "English Source Package lacks source/window/anchor human gates")
    speech.validate_policy_binding(candidate, policy, strict_rubric=strict_rubric)
    text_policy = speech.validate_text_release_basis(source, anchor, candidate, human_receipt)
    speech.validate_adapter(adapter, candidate["targetLocale"], registry,
                            clip_voice_authorization=clip_voice_authorization,
                            source_voice_authorization=source_voice_authorization,
                            clip_voice_capability=clip_voice_capability,
                            source_package=source, candidate=candidate)
    timeline_map.validate(clip_timeline, source, anchor)
    speech.validate_speech_job_schema(job)
    require(speech.expected_text_policy(job) == text_policy,
            "Speech job version differs from the candidate's release basis")
    require(job.get("schemaVersion") in speech.SPEECH_JOB_SCHEMAS
            and job.get("targetLocale") == candidate["targetLocale"]
            and job.get("status") == "prepared_for_target_language_speech"
            and job.get("synthesisEligible") is True
            and job.get("releaseEligible") is False,
            "Speech job is not eligible for formal synthesis")
    require(adapter.get("capabilityStatus") == "verified", "Unverified speech adapter")
    require((clip_voice_capability is None) == ("clipVoiceCapability" not in job.get("inputs", {})),
            "Speech job clip capability input presence mismatch")
    require((clip_voice_authorization is None) != (source_voice_authorization is None),
            "Formal audio requires exactly one source-bound voice authorization")
    authorization_key = ("clipVoiceAuthorization", "clip_voice_authorization") if clip_voice_authorization else (
        "sourceVoiceAuthorization", "source_voice_authorization")
    require(("clipVoiceAuthorization" in job.get("inputs", {})) == (clip_voice_authorization is not None)
            and ("sourceVoiceAuthorization" in job.get("inputs", {})) == (source_voice_authorization is not None),
            "Speech job voice authorization input presence mismatch")
    bindings = (("englishSourcePackage", "source"), ("anchorManifest", "anchor"),
                      ("targetLanguageCandidate", "candidate"),
                      (speech.text_basis_input_key(job), "human_receipt"),
                      ("targetLanguagePolicy", "policy"), ("speakerRegistry", "registry"),
                      authorization_key,
                      ("clipTimelineMap", "clip_timeline_map"))
    if clip_voice_capability is not None:
        bindings += (("clipVoiceCapability", "clip_voice_capability"),)
    for key, name in bindings:
        bound = job.get("inputs", {}).get(key, {})
        value = {"source": source, "anchor": anchor, "candidate": candidate,
                 "human_receipt": human_receipt, "policy": policy, "registry": registry,
                 "clip_voice_authorization": clip_voice_authorization,
                 "source_voice_authorization": source_voice_authorization,
                 "clip_voice_capability": clip_voice_capability,
                 "clip_timeline_map": clip_timeline}[name]
        require(bound.get("sha256") == file_sha256(paths[name])
                and bound.get("jsonSha256") == json_sha256(value),
                f"Speech job input mismatch: {key}")
    bound_adapter = job.get("adapter", {})
    require(bound_adapter.get("configSha256") == file_sha256(paths["adapter"]),
            "Speech job adapter hash mismatch")
    for key in ("adapterId", "adapterVersion", "provider", "model", "modelRevision",
                "voice", "speakerId", "speakerKey", "conditioningRef", "conditioningSha256",
                "registryJsonSha256", "authorizationPurpose", "authorizationEvidenceSha256",
                "capabilityEvidenceSha256", "languageParameter",
                "capabilityStatus", "normalizationPolicySha256", "asrScreeningPolicySha256",
                "subtitlePolicySha256"):
        require(bound_adapter.get(key) == adapter.get(key), f"Speech job adapter field mismatch: {key}")
    render = job.get("renderContract", {})
    require(render.get("ratePolicy") == "natural_no_time_stretch"
            and render.get("textPolicy") == text_policy
            and render.get("playbackRate") == 1.0
            and render.get("postProcessing") == "none_before_measurement",
            "Speech job render contract mismatch")
    locale = candidate["targetLocale"]
    require(job.get("outputContract", {}).get("languageRoot") == f"languages/{locale}",
            "Speech job language root mismatch")
    expected = candidate["groups"]
    require(len(job.get("units", [])) == len(expected), "Speech job unit count mismatch")
    for index, (unit, group) in enumerate(zip(job["units"], expected)):
        require(unit.get("unitIndex") == index
                and unit.get("translationGroupId") == group["translationGroupId"]
                and unit.get("sourceUnitIds") == group["sourceUnitIds"]
                and unit.get("text") == group["targetText"]
                and unit.get("outputRelativePath") == f"languages/{locale}/audio/unit-{index:04d}.wav",
                f"Speech job unit differs from approved text: {index}")


def validate_schedule(schedule: dict[str, Any], candidate: dict[str, Any], anchor: dict[str, Any],
                      durations: list[float], track_duration: float,
                      anchor_offset_seconds: float, clip_duration_seconds: float, *,
                      track_format: str = "wav") -> None:
    require(schedule.get("targetLocale") == candidate["targetLocale"],
            "Schedule locale mismatch")
    require(schedule.get("timingKind") == "measured_target_audio",
            "Schedule must use measured target audio timing")
    require(schedule.get("status") == "pass" and schedule.get("issues") == [],
            "Schedule has unresolved issues")
    require(track_format in {"wav", "mp3"}, "Unsupported track format")
    # Older ffprobe counts MP3 encoder padding even when Xing/LAME metadata
    # gives the exact presentation duration. The source PCM is checked below.
    track_tolerance = MP3_CONTAINER_PADDING_SECONDS if track_format == "mp3" else EPSILON
    scheduled_duration = schedule.get("trackDurationSeconds")
    require(isinstance(scheduled_duration, (int, float))
            and not isinstance(scheduled_duration, bool)
            and math.isfinite(scheduled_duration)
            and abs(track_duration - scheduled_duration) <= track_tolerance,
            "Schedule track duration differs from measured audio")
    require(track_duration <= clip_duration_seconds + track_tolerance
            and scheduled_duration <= clip_duration_seconds + track_tolerance,
            "Dubbed track exceeds approved 1x source clip duration")
    policy = schedule.get("policy", {})
    reaction = policy.get("reactionLagSeconds")
    gap = policy.get("interUtteranceGapSeconds")
    max_lag = policy.get("maxEndLagSeconds")
    require(all(isinstance(x, (int, float)) and not isinstance(x, bool)
                and math.isfinite(x) and x >= 0 for x in (reaction, gap, max_lag)),
            "Schedule policy is invalid")
    entries = schedule.get("entries")
    require(isinstance(entries, list) and len(entries) == len(durations),
            "Schedule group count mismatch")
    anchors = {unit["sourceUnitId"]: unit for unit in anchor.get("sourceUnits", [])}
    cursor = 0.0
    for index, (entry, group, duration) in enumerate(zip(entries, candidate["groups"], durations)):
        require(isinstance(entry, dict)
                and entry.get("textGroupId") == group["translationGroupId"]
                and entry.get("sourceUnitIds") == group["sourceUnitIds"],
                f"Schedule mapping mismatch at {index}")
        source_start = float(anchors[group["sourceUnitIds"][0]]["start"]) - anchor_offset_seconds
        source_end = float(anchors[group["sourceUnitIds"][-1]]["end"]) - anchor_offset_seconds
        start = max(source_start + reaction, cursor + (gap if index else 0.0))
        end = start + duration
        near(start, entry.get("plannedStart"), f"Schedule start {index}")
        near(end, entry.get("plannedEnd"), f"Schedule end {index}")
        require(end - source_end <= max_lag + EPSILON, f"Schedule overflow at {index}")
        require(end <= clip_duration_seconds + EPSILON,
                f"Schedule exceeds approved 1x source clip at {index}")
        require(end <= track_duration + EPSILON, f"Schedule exceeds track at {index}")
        cursor = end


def validate_captions(captions: dict[str, Any], candidate: dict[str, Any],
                      schedule: dict[str, Any], track_duration: float) -> None:
    cues = captions.get("cues")
    require(isinstance(cues, list) and len(cues) == len(candidate["groups"]),
            "Caption cue count mismatch")
    previous_end = 0.0
    for index, (cue, group, entry) in enumerate(zip(cues, candidate["groups"], schedule["entries"])):
        require(isinstance(cue, dict)
                and cue.get("textGroupId") == group["translationGroupId"]
                and cue.get("text") == group["targetText"],
                f"Caption text/mapping mismatch at {index}")
        start, end = cue.get("start"), cue.get("end")
        require(isinstance(start, (int, float)) and isinstance(end, (int, float))
                and not isinstance(start, bool) and not isinstance(end, bool)
                and math.isfinite(start) and math.isfinite(end)
                and previous_end <= start < end <= track_duration + EPSILON,
                f"Caption order/bounds mismatch at {index}")
        near(float(entry["plannedStart"]), start, f"Caption start {index}")
        near(float(entry["plannedEnd"]), end, f"Caption end {index}")
        previous_end = end


def build_package(paths: dict[str, Path], render_manifest_path: Path, artifact_root: Path, *,
                  strict_rubric: dict[str, Any] | None = None) -> dict[str, Any]:
    source, anchor, candidate, job, adapter, policy, human_receipt, registry, clip_timeline = (
        read_object(paths[key]) for key in ("source", "anchor", "candidate", "job",
                                           "adapter", "policy", "human_receipt", "registry",
                                           "clip_timeline_map")
    )
    clip_auth = read_object(paths["clip_voice_authorization"]) if paths.get("clip_voice_authorization") else None
    source_auth = read_object(paths["source_voice_authorization"]) if paths.get("source_voice_authorization") else None
    clip_cap = read_object(paths["clip_voice_capability"]) if paths.get("clip_voice_capability") else None
    validate_job(source, anchor, candidate, job, adapter, policy, human_receipt, registry,
                 clip_auth, clip_cap, clip_timeline, paths,
                 source_voice_authorization=source_auth, strict_rubric=strict_rubric)
    job_file_sha256 = file_sha256(paths["job"])
    manifest = read_object(render_manifest_path)
    locale = candidate["targetLocale"]
    job_hash = json_sha256(job)
    voice = manifest.get("voice", {})
    require(manifest.get("schemaVersion") == RENDER_SCHEMA
            and manifest.get("targetLocale") == locale
            and manifest.get("englishSourcePackageJsonSha256") == json_sha256(source)
            and manifest.get("targetLanguageCandidateJsonSha256") == json_sha256(candidate)
            and manifest.get("targetLanguageSpeechJobJsonSha256") == job_hash
            and manifest.get("clipTimelineMapJsonSha256") == json_sha256(clip_timeline),
            "Render manifest source, candidate, job or locale mismatch")
    require(isinstance(voice, dict) and voice.get("targetLocale") == locale
            and voice.get("provider") == adapter["provider"]
            and voice.get("model") == adapter["model"]
            and voice.get("modelRevision") == adapter["modelRevision"]
            and voice.get("voice") == adapter["voice"]
            and voice.get("speakerId") == adapter["speakerId"]
            and voice.get("checkpointSha256") == adapter["conditioningSha256"]
            and voice.get("authorizationStatus") == "authorized"
            and voice.get("targetLocaleCapability") == "reviewed"
            and adapter["capabilityStatus"] == "verified",
            "Voice/checkpoint authorization or locale capability missing")
    authorization_artifact = checked_artifact(
        artifact_root, manifest.get("voiceAuthorization"), json_artifact=True)
    authorization_receipt = source_auth if source_auth is not None else clip_auth
    require(authorization_artifact["sha256"] == authorization_receipt["userRightsAttestation"]["sha256"]
            and authorization_artifact["jsonSha256"] == authorization_receipt["userRightsAttestation"]["jsonSha256"],
            "Render voice authorization differs from speech job receipt")
    authorization = read_object(Path(authorization_artifact["path"]))
    approval_time = authorization.get("recordedAt" if source_auth is not None else "attestedAt")
    try:
        parsed_approval_time = datetime.fromisoformat(approval_time.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("Voice authorization approval time is invalid") from exc
    if source_auth is not None:
        speech._validate_schema(authorization,
                                authorization["schemaVersion"] + ".schema.json",
                                "source voice user attestation")
        require(authorization["sourceId"] == source["source"]["sourceId"]
                and authorization["sourceMediaSha256"] == source["source"]["media"]["sha256"]
                and authorization["approvedWindow"]["startSeconds"]
                == source["source"]["approvedWindow"]["startSeconds"]
                and authorization["approvedWindow"]["endSeconds"]
                == source["source"]["approvedWindow"]["endSeconds"]
                and locale in authorization["targetLocales"]
                and parsed_approval_time.tzinfo is not None,
                "Voice authorization is not bound to this complete source media and locale")
    else:
        require(authorization.get("schemaVersion") == "sermon-clip-user-rights-attestation-v1"
                and isinstance(authorization.get("scope"), str)
                and authorization["scope"].endswith("-dev-app-and-audio_only")
                and authorization.get("englishSourcePackageJsonSha256") == json_sha256(source)
                and locale in authorization.get("targetLocales", [])
                and authorization.get("speakerId") == voice.get("speakerId")
                and authorization.get("voiceCheckpointSha256") == voice["checkpointSha256"]
                and authorization.get("permissionClaimed") is True
                and isinstance(authorization.get("userStatement"), str)
                and bool(authorization["userStatement"].strip())
                and parsed_approval_time.tzinfo is not None,
                "Voice authorization is not bound to this clip, locale and checkpoint")
    package_voice = {key: voice[key] for key in (
        "provider", "model", "checkpointSha256", "targetLocaleCapability", "authorizationStatus")}
    rows = manifest.get("units")
    require(isinstance(rows, list) and len(rows) == len(job["units"]),
            "Render unit count mismatch")
    units: list[dict[str, Any]] = []
    durations: list[float] = []
    for index, (row, job_unit) in enumerate(zip(rows, job["units"])):
        unit_started = time.monotonic()
        accounting.record_workload("layer3.unit_validation_started", {
            "jobSha256": job_hash, "unitIndex": index, "validationStarted": True})
        group_id = job_unit["translationGroupId"]
        text_hash = hashlib.sha256(job_unit["text"].encode("utf-8")).hexdigest()
        require(isinstance(row, dict) and row.get("textGroupId") == group_id
                and row.get("targetTextSha256") == text_hash,
                f"Render unit text/order mismatch at {index}")
        audio = checked_artifact(artifact_root, row.get("audio"))
        expected_path = (artifact_root / job_unit["outputRelativePath"]).resolve()
        require(Path(audio["path"]) == expected_path, f"Unit audio path mismatch at {index}")
        duration, sample_rate, channels = probe_audio(Path(audio["path"]))
        near(duration, row.get("durationSeconds"), f"Unit duration {index}")
        receipt_artifact = checked_artifact(artifact_root, row.get("receipt"), json_artifact=True)
        receipt = read_object(Path(receipt_artifact["path"]))
        require(receipt.get("schemaVersion") == RECEIPT_SCHEMA,
                f"Unsupported unit receipt schema at {index}")
        unit_integrity.validate_receipt(
            paths["job"], index, Path(audio["path"]), receipt,
            validated_job=job, validated_job_file_sha256=job_file_sha256)
        require(receipt["translationGroupId"] == group_id
                and receipt["targetTextSha256"] == text_hash
                and receipt["audioSha256"] == audio["sha256"]
                and receipt["sampleRate"] == sample_rate
                and receipt["channels"] == channels,
                f"Unit receipt identity or measured format mismatch at {index}")
        near(duration, receipt.get("durationSeconds"), f"Unit receipt duration {index}")
        units.append({"textGroupId": group_id, "targetTextSha256": text_hash,
                      "audio": audio, "durationSeconds": round(duration, 6)})
        durations.append(duration)
        accounting.record_workload("layer3.unit_validation_completed", {
            "jobSha256": job_hash, "unitIndex": index, "audioSha256": audio["sha256"],
            "receiptSha256": receipt_artifact["sha256"], "fullDecodePassed": True,
            "validationCompleted": True, "validationElapsedSeconds": time.monotonic() - unit_started,
            "timingScope": "current_execution"})
    if "silenceTrimEvidence" in manifest:
        trim_artifact = checked_artifact(artifact_root, manifest["silenceTrimEvidence"],
                                         json_artifact=True)
        trim = read_object(Path(trim_artifact["path"]))
        edge_mode = trim.get("schemaVersion") == "sermon-formal-edge-silence-trim-v1"
        require(trim.get("schemaVersion") in {
                    "sermon-formal-leading-silence-trim-v1",
                    "sermon-formal-edge-silence-trim-v1"}
                and trim.get("status") == "measured_silence_removed"
                and trim.get("targetLocale") == locale
                and trim.get("targetLanguageSpeechJobJsonSha256") == job_hash
                and trim.get("sourceJobFileSha256") == file_sha256(paths["job"])
                and trim.get("humanListeningStatus") == "pending"
                and isinstance(trim.get("units"), list)
                and len(trim["units"]) == len(units),
                "Speech-edge silence trim evidence differs from formal job")
        if edge_mode:
            require(isinstance(trim.get("trimTrailing"), bool)
                    and isinstance(trim.get("paddingSeconds"), (int, float))
                    and 0.02 <= trim["paddingSeconds"] <= 0.06
                    and isinstance(trim.get("interUtteranceGapSeconds"), (int, float))
                    and 0 <= trim["interUtteranceGapSeconds"] <= 0.05
                    and isinstance(trim.get("reactionLagSeconds", 0.05), (int, float))
                    and 0 <= trim.get("reactionLagSeconds", 0.05) <= 0.05,
                    "Edge trim parameters are invalid")
        for index, (entry, unit) in enumerate(zip(trim["units"], units)):
            require(entry.get("unitIndex") == index
                    and entry.get("textGroupId") == unit["textGroupId"]
                    and entry.get("audioSha256") == unit["audio"]["sha256"]
                    and isinstance(entry.get("sourceAudioSha256"), str)
                    and len(entry["sourceAudioSha256"]) == 64
                    and isinstance(entry.get("removedLeadingSeconds"), (int, float))
                    and 0 <= entry["removedLeadingSeconds"] <= 0.75,
                    f"Leading silence trim evidence differs from unit {index}")
            if edge_mode:
                require(isinstance(entry.get("removedTrailingSeconds"), (int, float))
                        and 0 <= entry["removedTrailingSeconds"] <= 0.75
                        and isinstance(entry.get("originalDurationSeconds"), (int, float))
                        and abs(entry["originalDurationSeconds"] -
                                entry["removedLeadingSeconds"] -
                                entry["removedTrailingSeconds"] -
                                unit["durationSeconds"]) <= 0.002,
                        f"Edge silence trim duration differs from unit {index}")
    track = checked_artifact(artifact_root, manifest.get("track"))
    track_duration, _, _ = probe_audio(Path(track["path"]))
    track_format = Path(track["path"]).suffix.removeprefix(".").lower()
    require(track_format in {"wav", "mp3"}, "Unsupported formal track format")
    if track_format == "mp3":
        pcm_track = Path(track["path"]).with_suffix(".wav")
        require(pcm_track.is_file(), "MP3 source PCM track is missing")
        pcm_duration, _, _ = probe_audio(pcm_track)
        require(abs(pcm_duration - clip_timeline["clipDurationSeconds"]) <= EPSILON,
                "MP3 source PCM differs from approved 1x source clip duration")
    schedule_artifact = checked_artifact(artifact_root, manifest.get("schedule"), json_artifact=True)
    captions_artifact = checked_artifact(artifact_root, manifest.get("captions"))
    locale_root = (artifact_root / "languages" / locale).resolve()
    for label, item in (("track", track), ("schedule", schedule_artifact),
                        ("captions", captions_artifact)):
        require(Path(item["path"]).is_relative_to(locale_root),
                f"{label} belongs to another locale")
    schedule = read_object(Path(schedule_artifact["path"]))
    if "silenceTrimEvidence" in manifest and trim.get("schemaVersion") == "sermon-formal-edge-silence-trim-v1":
        require(schedule["policy"]["interUtteranceGapSeconds"] == trim["interUtteranceGapSeconds"]
                and schedule["policy"]["reactionLagSeconds"] == trim.get("reactionLagSeconds", 0.05),
                "Edge trim schedule policy differs from evidence")
    captions = read_object(Path(captions_artifact["path"]))
    validate_schedule(schedule, candidate, anchor, durations, track_duration,
                      clip_timeline["anchorOffsetSeconds"],
                      clip_timeline["clipDurationSeconds"], track_format=track_format)
    validate_captions(captions, candidate, schedule, track_duration)
    screen = manifest.get("machineScreening", {})
    require(isinstance(screen, dict) and screen.get("status") in {"not_run", "pass", "requires_review", "fail"}
            and isinstance(screen.get("coverage"), (int, float))
            and 0 <= screen["coverage"] <= 1,
            "Invalid machine screening")
    if screen["status"] == "pass":
        require(isinstance(screen.get("model"), str) and screen["model"]
                and screen["coverage"] == 1.0, "Machine pass requires full measured coverage")
        screening_artifact = checked_artifact(
            artifact_root, manifest.get("machineScreeningReceipt"), json_artifact=True)
        screening = read_object(Path(screening_artifact["path"]))
        speech._validate_schema(screening, speech.audio_screening_schema_file(screening),
                                "audio screening receipt")
        require(screening.get("schemaVersion") in speech.AUDIO_SCREENING_VERSIONS
                and screening.get("targetLocale") == locale
                and screening.get("targetLanguageSpeechJobJsonSha256") == job_hash
                and screening.get("trackSha256") == track["sha256"]
                and screening.get("status") == "pass"
                and screening.get("model") == screen["model"]
                and screening.get("coverage") == 1.0
                and screening.get("reviewedGroupIds") == [unit["textGroupId"] for unit in units]
                and screening.get("unitAudioSha256s") == [unit["audio"]["sha256"] for unit in units],
                "Machine screening receipt does not cover this exact audio set")
        require(len(screening["results"]) == len(units),
                "Machine screening result count differs from audio units")
        for index, (result, unit, job_unit) in enumerate(zip(
                screening["results"], units, job["units"])):
            expected_tokens = audio_screen.tokens(job_unit["text"], locale)
            actual_tokens = audio_screen.tokens(result["recognized"], locale)
            similarity = round(difflib.SequenceMatcher(
                None, expected_tokens, actual_tokens, autojunk=False).ratio(), 6)
            require(result["textGroupId"] == unit["textGroupId"]
                    and result["targetTextSha256"] == unit["targetTextSha256"]
                    and result["audioSha256"] == unit["audio"]["sha256"]
                    and result["status"] == "pass"
                    and result["similarity"] == similarity
                    and similarity >= screening["minSimilarity"]
                    and (len(expected_tokens) >= 4 or expected_tokens == actual_tokens),
                    f"Machine screening result is incomplete or below threshold: {index}")
    else:
        require(screen.get("status") != "fail", "Failed machine screening cannot produce package")
    status = "machine_screened" if screen["status"] == "pass" else "candidate"
    package = {
        "schemaVersion": SCHEMA,
        "packageId": f"target-audio-{locale}-{json_sha256(manifest)[:24]}",
        "englishSourcePackageJsonSha256": json_sha256(source),
        "targetLanguageCandidateJsonSha256": json_sha256(candidate),
        "targetLanguageSpeechJobJsonSha256": job_hash,
        "targetLocale": locale,
        "status": status,
        "ratePolicy": "natural_no_time_stretch",
        "voice": package_voice,
        "units": units,
        "track": track,
        "captions": captions_artifact,
        "schedule": schedule_artifact,
        "machineScreening": {key: screen.get(key) for key in ("status", "model", "coverage")},
        "humanReview": {"status": "pending", "humanApproval": False, "reviewedBy": None,
                        "reviewedAt": None, "fullPlayback": "pending"},
        "issues": [],
    }
    package["downstreamInvalidationKey"] = json_sha256(package)
    schema_path = Path(__file__).parents[1] / "schemas" / "sermon-target-language-audio-package-v1.schema.json"
    errors = list(Draft202012Validator(read_object(schema_path), format_checker=FormatChecker()).iter_errors(package))
    require(not errors, f"Audio Package schema error: {errors[0].message if errors else ''}")
    # Recheck the bound inputs once after the batch so a mid-run change still
    # fails, without rehashing the source video for every audio unit.
    validate_job(source, anchor, candidate, job, adapter, policy, human_receipt, registry,
                 clip_auth, clip_cap, clip_timeline, paths,
                 source_voice_authorization=source_auth, strict_rubric=strict_rubric)
    require(file_sha256(paths["job"]) == job_file_sha256,
            "Speech job changed during audio package build")
    return package


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "anchor", "candidate", "job", "adapter", "policy"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--anchor-exception-receipt", type=Path,
                        help="Hash-bound human acceptance of the single complete scripture anchor")
    parser.add_argument("--strict-rubric", type=Path, help="Explicit frozen rubric for strict-v3 policy validation")
    parser.add_argument("--human-review-receipt", dest="human_receipt", type=Path, required=True)
    parser.add_argument("--speaker-registry", dest="registry", type=Path, required=True)
    authorization = parser.add_mutually_exclusive_group(required=True)
    authorization.add_argument("--clip-voice-authorization", dest="clip_voice_authorization", type=Path)
    authorization.add_argument("--source-voice-authorization", dest="source_voice_authorization", type=Path)
    parser.add_argument("--clip-voice-capability", dest="clip_voice_capability", type=Path)
    parser.add_argument("--clip-timeline-map", dest="clip_timeline_map",
                        type=Path, required=True)
    parser.add_argument("--render-manifest", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), "Audio Package output is immutable; choose a new path")
    paths = {name: getattr(args, name) for name in ("source", "anchor", "candidate", "job",
                                                  "adapter", "policy", "human_receipt", "registry")}
    if args.anchor_exception_receipt:
        paths["anchor_exception_receipt"] = args.anchor_exception_receipt
    if args.clip_voice_authorization:
        paths["clip_voice_authorization"] = args.clip_voice_authorization
    if args.source_voice_authorization:
        paths["source_voice_authorization"] = args.source_voice_authorization
    if args.clip_voice_capability:
        paths["clip_voice_capability"] = args.clip_voice_capability
    paths["clip_timeline_map"] = args.clip_timeline_map
    package = build_package(paths, args.render_manifest, args.artifact_root,
                            strict_rubric=read_object(args.strict_rubric) if args.strict_rubric else None)
    sidecar = args.out.with_name(args.out.name + ".anchor-exception.json")
    if args.anchor_exception_receipt:
        require(not sidecar.exists(), "Anchor exception sidecar is immutable")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.anchor_exception_receipt:
        evidence = {"schemaVersion": "sermon-audio-anchor-exception-evidence-v1",
                    "audioPackageJsonSha256": json_sha256(package),
                    "receiptPath": str(args.anchor_exception_receipt.resolve()),
                    "receiptSha256": file_sha256(args.anchor_exception_receipt),
                    "receipt": read_object(args.anchor_exception_receipt)}
        sidecar.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": package["status"], "targetLocale": package["targetLocale"],
                      "package": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
