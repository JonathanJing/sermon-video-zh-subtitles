#!/usr/bin/env python3
"""Resume a human-approved Layer 3 speech job and assemble a natural 1x clip track.

The job directory is the artifact root. Render cache records are clip, text,
adapter, checkpoint, settings, and implementation bound. No ASR or human review
is inferred from rendering. A schedule that exceeds the clip leaves diagnostics
and fully decoded units, but no release manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from typing import Any, Callable
import wave as wave_module

try:
    from scripts import build_target_language_audio_package as package
    from scripts import render_multilingual_voice_demos as demos
    from scripts import sermon_sentence_interpretation as identity
    from scripts import validate_target_language_audio_unit as integrity
except ImportError:
    import build_target_language_audio_package as package
    import render_multilingual_voice_demos as demos
    import sermon_sentence_interpretation as identity
    import validate_target_language_audio_unit as integrity


VERSION = "sermon-formal-target-speech-render-v1"
DEFAULT_POLICY = {"reactionLagSeconds": 0.05, "interUtteranceGapSeconds": 0.05,
                  "maxEndLagSeconds": 8.0}


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2).encode() + b"\n"
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.",
                                     suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def artifact(root: Path, path: Path, *, json_artifact: bool = False) -> dict[str, str]:
    resolved = path.resolve()
    require(resolved.is_relative_to(root.resolve()) and path.is_file(),
            f"Artifact is outside render root: {path}")
    result = {"path": str(resolved.relative_to(root.resolve())),
              "sha256": identity.sha256(path)}
    if json_artifact:
        result["jsonSha256"] = identity.json_sha256(package.read_object(path))
    return result


def validate_operation_policies(policies: dict[str, Any], adapter: dict[str, Any],
                                job: dict[str, Any]) -> None:
    expected = (("normalization", "normalizationPolicySha256"),
                ("asrScreening", "asrScreeningPolicySha256"),
                ("subtitle", "subtitlePolicySha256"))
    require(all(isinstance(policies.get(name), dict)
                and identity.json_sha256(policies[name]) == adapter.get(field) == job["adapter"].get(field)
                for name, field in expected),
            "Audio operation policy content differs from speech adapter/job hashes")
    require(policies["normalization"].get("policy") == "exact_human_approved_target_text_no_rewrite",
            "Renderer requires exact approved text policy")


def _evidence_paths(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for item in value for row in _evidence_paths(item)]
    if not isinstance(value, dict):
        return []
    rows = [value] if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str) else []
    return rows + [row for item in value.values() for row in _evidence_paths(item)]


def materialize_path_map(job_path: Path, path_map_path: Path) -> None:
    """Link staged files at immutable job paths inside an isolated container.

    The original job bytes stay untouched. Every staged file is checked against
    the bound file hash (and JSON hash where supplied) before any path is linked.
    Existing original paths may only be reused when their bytes match.
    """
    mapping = package.read_object(path_map_path)
    require(mapping.get("schemaVersion") == "sermon-deployment-path-map-v1"
            and isinstance(mapping.get("paths"), dict), "Invalid deployment path map")
    aliases = mapping["paths"]
    job = package.read_object(job_path)
    inputs = job.get("inputs", {})
    require(isinstance(inputs, dict), "Speech job has no bound inputs")
    references = _evidence_paths(inputs)
    staged_documents = []
    for ref in references:
        original = ref["path"]
        staged = Path(aliases.get(original, original))
        require(Path(original).is_absolute() and staged.is_absolute() and staged.is_file()
                and identity.sha256(staged) == ref["sha256"],
                f"Mapped speech input missing or hash mismatch: {original}")
        value = json.loads(staged.read_text(encoding="utf-8"))
        if "jsonSha256" in ref:
            require(identity.json_sha256(value) == ref["jsonSha256"],
                    f"Mapped speech JSON input mismatch: {original}")
        staged_documents.append(value)
    nested = [ref for document in staged_documents for ref in _evidence_paths(document)]
    for ref in references + nested:
        original = Path(ref["path"])
        staged = Path(aliases.get(str(original), str(original)))
        require(original.is_absolute() and staged.is_absolute() and staged.is_file()
                and identity.sha256(staged) == ref["sha256"],
                f"Mapped evidence missing or hash mismatch: {original}")
        if "jsonSha256" in ref:
            require(identity.json_sha256(json.loads(staged.read_text(encoding="utf-8"))) == ref["jsonSha256"],
                    f"Mapped evidence JSON hash mismatch: {original}")
    # Only after all hash checks pass may aliases be made visible to legacy
    # validators that dereference absolute paths from the unchanged job JSON.
    for ref in references + nested:
        original = Path(ref["path"])
        staged = Path(aliases.get(str(original), str(original)))
        if original.exists():
            require(original.is_file() and identity.sha256(original) == ref["sha256"],
                    f"Existing source path differs from mapped evidence: {original}")
            continue
        require(str(original) in aliases, f"No path-map entry for inaccessible job path: {original}")
        original.parent.mkdir(parents=True, exist_ok=True)
        original.symlink_to(staged)


def checked_context(paths: dict[str, Path], checkpoint_map_path: Path,
                    operation_policies_path: Path) -> dict[str, Any]:
    required = ("source", "anchor", "candidate", "job", "adapter", "policy",
                "human_receipt", "registry", "clip_voice_authorization", "clip_timeline_map")
    require(all(name in paths and paths[name].is_file() for name in required),
            "Missing formal Layer 3 input")
    data = {name: package.read_object(path) for name, path in paths.items()}
    package.validate_job(data["source"], data["anchor"], data["candidate"],
                         data["job"], data["adapter"], data["policy"],
                         data["human_receipt"], data["registry"],
                         data["clip_voice_authorization"],
                         data.get("clip_voice_capability"), data["clip_timeline_map"], paths)
    adapter, registry, job = data["adapter"], data["registry"], data["job"]
    policies = package.read_object(operation_policies_path)
    validate_operation_policies(policies, adapter, job)
    require(adapter["adapterId"] == "qwen3_tts_sft", "Unsupported formal TTS adapter")
    checkpoint_map = demos.read_object(checkpoint_map_path, "checkpoint map")
    require(checkpoint_map.get("schemaVersion") == "sermon-speaker-checkpoint-map-v1",
            "Unsupported checkpoint map")
    speakers = [row for row in registry["speakers"]
                if row["speakerId"] == adapter["speakerId"]]
    mappings = [row for row in checkpoint_map.get("checkpoints", [])
                if row.get("speakerId") == adapter["speakerId"]]
    require(len(speakers) == len(mappings) == 1, "Speaker/checkpoint mapping is not unique")
    speaker, mapping = speakers[0], mappings[0]
    require(mapping.get("checkpointRef") == adapter["conditioningRef"]
            == speaker["checkpoint"]["checkpointRef"]
            and speaker["checkpoint"]["checkpointSha256"] == adapter["conditioningSha256"],
            "Checkpoint map/adapter/registry identity mismatch")
    task = {"checkpointPath": mapping.get("path"), "checkpointSha256": adapter["conditioningSha256"],
            "speakerKey": adapter["speakerKey"], "speakerId": adapter["speakerId"]}
    checkpoint = demos.validate_checkpoint(task)
    require(job["adapter"]["conditioningSha256"] == identity.sha256(checkpoint / "model.safetensors"),
            "Live checkpoint weights differ from speech job")
    data["checkpoint"] = checkpoint
    data["checkpointMapFileSha256"] = identity.sha256(checkpoint_map_path)
    data["operationPoliciesFileSha256"] = identity.sha256(operation_policies_path)
    return data


class QwenSynthesizer:
    def __init__(self, checkpoint: Path, *, device: str, dtype: str,
                 attention: str | None, instruct: str | None = None):
        import torch
        from qwen_tts import Qwen3TTSModel
        self.torch = torch
        self.instruct = instruct
        kwargs: dict[str, Any] = {"device_map": device,
                                  "dtype": torch.bfloat16 if dtype == "bfloat16" else torch.float32}
        if attention:
            kwargs["attn_implementation"] = attention
        self.model = Qwen3TTSModel.from_pretrained(str(checkpoint), **kwargs)

    def __call__(self, text: str, language: str, speaker: str, *, seed: int) -> tuple[Any, int]:
        self.torch.manual_seed(seed)
        if self.torch.cuda.is_available():
            self.torch.cuda.manual_seed_all(seed)
        kwargs = {"text": text, "language": language, "speaker": speaker,
                  "temperature": 0.7, "repetition_penalty": 1.05, "max_new_tokens": 768}
        if self.instruct:
            kwargs["instruct"] = self.instruct
        wavs, sample_rate = self.model.generate_custom_voice(**kwargs)
        return wavs[0], sample_rate


def _intent(context: dict[str, Any], paths: dict[str, Path], index: int, *, seed: int,
            dtype: str, attention: str | None, instruct: str | None) -> dict[str, Any]:
    job, adapter = context["job"], context["adapter"]
    unit = job["units"][index]
    return {
        "schemaVersion": VERSION, "unitIndex": index,
        "jobJsonSha256": identity.json_sha256(job),
        "jobFileSha256": identity.sha256(paths["job"]),
        "sourceJsonSha256": identity.json_sha256(context["source"]),
        "anchorJsonSha256": identity.json_sha256(context["anchor"]),
        "translationPolicySha256": context["candidate"]["translationPolicySha256"],
        "candidateJsonSha256": identity.json_sha256(context["candidate"]),
        "adapterFileSha256": identity.sha256(paths["adapter"]),
        "adapterId": adapter["adapterId"], "model": adapter["model"],
        "modelRevision": adapter["modelRevision"],
        "conditioningRef": adapter["conditioningRef"],
        "checkpointMapFileSha256": context["checkpointMapFileSha256"],
        "operationPoliciesFileSha256": context["operationPoliciesFileSha256"],
        "checkpointSha256": adapter["conditioningSha256"],
        "speakerId": adapter["speakerId"], "speakerKey": adapter["speakerKey"],
        "targetLocale": job["targetLocale"],
        "languageParameter": adapter["languageParameter"],
        "groupId": unit["translationGroupId"],
        "sourceUnitIds": unit["sourceUnitIds"],
        "textSha256": hashlib.sha256(unit["text"].encode()).hexdigest(),
        "rendererSha256": identity.sha256(Path(__file__)),
        "seed": seed, "temperature": 0.7, "repetitionPenalty": 1.05,
        "maxNewTokens": 768, "dtype": dtype, "attention": attention,
        "deliveryInstruction": instruct,
        "ratePolicy": "natural_no_time_stretch",
    }


SPECULATIVE_MATCH_FIELDS = (
    "unitIndex", "sourceJsonSha256", "anchorJsonSha256", "translationPolicySha256",
    "adapterId", "model", "modelRevision", "conditioningRef",
    "checkpointMapFileSha256", "operationPoliciesFileSha256", "checkpointSha256",
    "speakerId", "speakerKey", "targetLocale", "languageParameter", "groupId",
    "sourceUnitIds", "textSha256", "rendererSha256", "seed", "temperature",
    "repetitionPenalty", "maxNewTokens", "dtype", "attention",
    "deliveryInstruction", "ratePolicy",
)


def _reusable_speculative_audio(previous_root: Path, unit: dict[str, Any], index: int,
                                expected: dict[str, Any]) -> Path | None:
    """Admit only the same sound from an explicitly non-formal pre-render lane."""
    manifest_path = previous_root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Speculative render manifest is missing")
    manifest = package.read_object(manifest_path)
    require(manifest.get("schemaVersion") == "sermon-speculative-target-speech-v1"
            and manifest.get("status") == "preview_only"
            and manifest.get("synthesisEligible") is False
            and manifest.get("releaseEligible") is False,
            "Speculative render cannot claim formal eligibility")
    snapshot_path = previous_root / "candidate.json"
    require(snapshot_path.is_file()
            and snapshot_path.resolve().is_relative_to(previous_root.resolve()),
            "Speculative candidate snapshot is missing")
    snapshot = package.read_object(snapshot_path)
    evidence = {}
    for name in ("source", "anchor", "policy", "adapter", "registry"):
        evidence_path = previous_root / f"{name}.json"
        require(evidence_path.is_file()
                and evidence_path.resolve().is_relative_to(previous_root.resolve()),
                f"Speculative {name} snapshot is missing")
        evidence[name] = package.read_object(evidence_path)
    package.speech.validate_target_candidate(evidence["source"], evidence["anchor"],
                                             snapshot, require_human_approval=False)
    require(snapshot.get("status") == "machine_review_pass_human_review_pending"
            and snapshot.get("humanReview", {}).get("translation") == "pending",
            "Speculative candidate was not human-pending")
    package.speech.validate_policy_binding(snapshot, evidence["policy"])
    package.speech.validate_adapter(evidence["adapter"], snapshot["targetLocale"],
                                    evidence["registry"],
                                    source_package=evidence["source"], candidate=snapshot)
    require(evidence["adapter"].get("authorizationPurpose")
            in {"multilingual_voice_demo", "chinese_dubbing"},
            "Speculative voice purpose was not authorized")
    require(identity.json_sha256(snapshot) == manifest.get("candidateJsonSha256")
            and identity.json_sha256(evidence["source"]) == manifest.get("sourceJsonSha256")
            and identity.json_sha256(evidence["anchor"]) == manifest.get("anchorJsonSha256")
            and snapshot["translationPolicySha256"] == manifest.get("translationPolicySha256")
            and manifest.get("sourceJsonSha256") == expected["sourceJsonSha256"]
            and manifest.get("anchorJsonSha256") == expected["anchorJsonSha256"]
            and manifest.get("translationPolicySha256") == expected["translationPolicySha256"]
            and manifest.get("targetLocale") == expected["targetLocale"],
            "Speculative candidate or source binding changed")
    groups = snapshot.get("groups", [])
    require(isinstance(groups, list) and index < len(groups)
            and isinstance(groups[index], dict),
            "Speculative candidate has no matching unit")
    receipt_path = previous_root / f"receipts/unit-{index:04d}.json"
    wav_path = previous_root / f"units/unit-{index:04d}.wav"
    if not receipt_path.exists() and not wav_path.exists():
        return None
    require(receipt_path.is_file() and wav_path.is_file()
            and all(path.resolve().is_relative_to(previous_root.resolve())
                    for path in (receipt_path, wav_path)),
            f"Incomplete speculative unit: {unit['translationGroupId']}")
    receipt = package.read_object(receipt_path)
    sound = receipt.get("soundIdentity")
    require(receipt.get("schemaVersion") == "sermon-speculative-target-speech-unit-v1"
            and receipt.get("status") == "preview_only"
            and isinstance(sound, dict)
            and manifest.get("candidateJsonSha256") == receipt.get("candidateJsonSha256")
            and receipt.get("audioSha256") == identity.sha256(wav_path),
            f"Speculative audio evidence changed: {unit['translationGroupId']}")
    require(groups[index].get("translationGroupId") == sound.get("groupId")
            and groups[index].get("sourceUnitIds") == sound.get("sourceUnitIds")
            and isinstance(groups[index].get("targetText"), str)
            and hashlib.sha256(groups[index]["targetText"].encode()).hexdigest()
            == sound.get("textSha256"),
            "Speculative receipt differs from candidate snapshot")
    # A revised translation may retain only units with exactly the same sound
    # identity. All formal review, authorization and package checks ran first.
    if sound != {key: expected[key] for key in SPECULATIVE_MATCH_FIELDS}:
        return None
    integrity.probe_full_decode(wav_path)
    return wav_path


def _reusable_audio(previous_root: Path, unit: dict[str, Any], index: int,
                    expected: dict[str, Any]) -> Path | None:
    """Use old bytes only after validating their original render evidence."""
    old_intent_path = previous_root / f"receipts/unit-{index:04d}.intent.json"
    old_commit_path = previous_root / f"receipts/unit-{index:04d}.render.json"
    old_audio_path = previous_root / unit["outputRelativePath"]
    require(all(path.resolve().is_relative_to(previous_root.resolve())
                for path in (old_intent_path, old_commit_path, old_audio_path)),
            "Previous render evidence escapes its directory")
    if not any(path.exists() for path in (old_intent_path, old_commit_path, old_audio_path)):
        return None
    require(all(path.is_file() for path in (old_intent_path, old_commit_path, old_audio_path)),
            f"Incomplete previous render evidence: {unit['translationGroupId']}")
    old_intent = package.read_object(old_intent_path)
    old_commit = package.read_object(old_commit_path)
    require(old_commit.get("identity") == old_intent
            and old_commit.get("audioSha256") == identity.sha256(old_audio_path),
            f"Previous render evidence or audio changed: {unit['translationGroupId']}")
    whole_job_fields = {"jobJsonSha256", "jobFileSha256", "candidateJsonSha256"}
    old_unit_identity = {key: value for key, value in old_intent.items()
                         if key not in whole_job_fields}
    new_unit_identity = {key: value for key, value in expected.items()
                         if key not in whole_job_fields}
    if old_unit_identity != new_unit_identity:
        return None
    integrity.probe_full_decode(old_audio_path)
    return old_audio_path


def write_pcm16(path: Path, samples: Any, rate: int) -> None:
    """Encode model float output as an unaltered-rate mono PCM waveform."""
    if hasattr(samples, "detach"):
        samples = samples.detach().cpu().reshape(-1).tolist()
    elif hasattr(samples, "reshape"):
        samples = samples.reshape(-1).tolist()
    values = [float(item) for item in samples]
    require(isinstance(rate, int) and rate > 0 and values
            and all(math.isfinite(item) and -1 <= item <= 1 for item in values)
            and 0.05 < len(values) / rate < 90,
            "Generated audio is empty, non-finite, clipped or implausible")
    pcm = struct.pack("<" + "h" * len(values),
                      *(max(-32768, min(32767, round(item * 32767))) for item in values))
    with wave_module.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)


def render_units(context: dict[str, Any], paths: dict[str, Path], root: Path,
                 checkpoint_map_path: Path, *, seed: int = 42, device: str = "cuda:0",
                 dtype: str = "bfloat16", attention: str | None = "sdpa",
                 instruct: str | None = None,
                 reuse_from: Path | None = None,
                 speculative_from: Path | None = None,
                 synth_factory: Callable[..., Any] = QwenSynthesizer) -> list[dict[str, Any]]:
    job, adapter = context["job"], context["adapter"]
    if reuse_from is not None:
        require(reuse_from.is_dir() and reuse_from.resolve() != root.resolve(),
                "Previous render root must be a distinct existing directory")
    if speculative_from is not None:
        require(speculative_from.is_dir() and speculative_from.resolve() != root.resolve(),
                "Speculative render root must be a distinct existing directory")
    model = None
    rows = []
    for index, unit in enumerate(job["units"]):
        wav_path = root / unit["outputRelativePath"]
        receipt_path = root / f"receipts/unit-{index:04d}.json"
        intent_path = root / f"receipts/unit-{index:04d}.intent.json"
        commit_path = root / f"receipts/unit-{index:04d}.render.json"
        expected = _intent(context, paths, index, seed=seed, dtype=dtype,
                           attention=attention, instruct=instruct)
        if intent_path.exists():
            require(package.read_object(intent_path) == expected,
                    f"Cached render identity differs: {unit['translationGroupId']}")
        else:
            require(not any(path.exists() for path in (wav_path, receipt_path, commit_path)),
                    f"Orphaned audio/receipt cannot be reused: {unit['translationGroupId']}")
            write_json_atomic(intent_path, expected)
        if commit_path.exists():
            commit = package.read_object(commit_path)
            require(commit.get("identity") == expected,
                    f"Cached audio identity or hash changed: {unit['translationGroupId']}")
            if not wav_path.exists():
                partial = wav_path.with_suffix(".partial.wav")
                require(partial.is_file() and commit.get("audioSha256") == identity.sha256(partial),
                        f"Committed partial audio is missing or changed: {unit['translationGroupId']}")
                os.replace(partial, wav_path)
            require(commit.get("audioSha256") == identity.sha256(wav_path),
                    f"Cached audio identity or hash changed: {unit['translationGroupId']}")
        else:
            require(not wav_path.exists(), f"Uncommitted audio cannot be reused: {wav_path}")
            wav_path.parent.mkdir(parents=True, exist_ok=True)
            partial = wav_path.with_suffix(".partial.wav")
            previous = (_reusable_audio(reuse_from, unit, index, expected)
                        if reuse_from is not None else None)
            if previous is None and speculative_from is not None:
                previous = _reusable_speculative_audio(speculative_from, unit, index, expected)
            if previous is not None:
                shutil.copyfile(previous, partial)
            else:
                if model is None:
                    model = synth_factory(context["checkpoint"], device=device, dtype=dtype,
                                          attention=attention, instruct=instruct)
                wavs, rate = model(unit["text"], adapter["languageParameter"],
                                   adapter["speakerKey"], seed=seed + index)
                # A partial belongs to this same intent and is safe to replace on resume.
                write_pcm16(partial, wavs, int(rate))
            integrity.probe_full_decode(partial)
            commit = {"identity": expected, "audioSha256": identity.sha256(partial)}
            write_json_atomic(commit_path, commit)
            os.replace(partial, wav_path)
        if receipt_path.exists():
            integrity.validate_receipt(paths["job"], index, wav_path,
                                       package.read_object(receipt_path))
        else:
            receipt = integrity.build_receipt(paths["job"], index, wav_path)
            write_json_atomic(receipt_path, receipt)
        receipt = package.read_object(receipt_path)
        rows.append({"textGroupId": unit["translationGroupId"],
                     "targetTextSha256": expected["textSha256"],
                     "audio": artifact(root, wav_path),
                     "durationSeconds": receipt["durationSeconds"],
                     "receipt": artifact(root, receipt_path, json_artifact=True)})
    return rows


def schedule(context: dict[str, Any], rows: list[dict[str, Any]],
             policy: dict[str, float]) -> dict[str, Any]:
    anchor = {u["sourceUnitId"]: u for u in context["anchor"]["sourceUnits"]}
    offset = context["clip_timeline_map"]["anchorOffsetSeconds"]
    clip_duration = context["clip_timeline_map"]["clipDurationSeconds"]
    cursor = 0.0
    entries = []
    issues = []
    for index, (group, row) in enumerate(zip(context["candidate"]["groups"], rows)):
        source_ids = group["sourceUnitIds"]
        earliest = float(anchor[source_ids[0]]["start"]) - offset
        source_end = float(anchor[source_ids[-1]]["end"]) - offset
        start = max(earliest + policy["reactionLagSeconds"],
                    cursor + (policy["interUtteranceGapSeconds"] if index else 0.0))
        end = start + row["durationSeconds"]
        entry = {"textGroupId": group["translationGroupId"], "sourceUnitIds": source_ids,
                 "plannedStart": round(start, 6), "plannedEnd": round(end, 6)}
        entries.append(entry)
        if end > clip_duration + 1e-6 or end - source_end > policy["maxEndLagSeconds"] + 1e-6:
            issues.append({"unitIndex": index, "textGroupId": group["translationGroupId"],
                           "plannedEnd": round(end, 6), "sourceEnd": round(source_end, 6),
                           "clipDuration": clip_duration,
                           "maxEndLagSeconds": policy["maxEndLagSeconds"]})
        cursor = end
    return {"targetLocale": context["job"]["targetLocale"],
            "timingKind": "measured_target_audio",
            "status": "pass" if not issues else "fail", "issues": issues,
            "trackDurationSeconds": clip_duration, "policy": policy,
            "entries": entries}


def assemble(context: dict[str, Any], paths: dict[str, Path], root: Path,
             rows: list[dict[str, Any]], *, policy: dict[str, float] | None = None,
             track_format: str = "wav") -> dict[str, Any]:
    policy = DEFAULT_POLICY.copy() if policy is None else policy.copy()
    require(all(isinstance(value, (float, int)) and not isinstance(value, bool)
                and math.isfinite(value) and value >= 0 for value in policy.values())
            and set(policy) == set(DEFAULT_POLICY), "Invalid schedule policy")
    require(track_format in {"wav", "mp3"}, "Unsupported formal track format")
    locale = context["job"]["targetLocale"]
    locale_root = root / "languages" / locale
    schedule_path = locale_root / "synchronization/schedule.json"
    captions_path = locale_root / "synchronization/captions.json"
    wav_path = locale_root / "audio/track.wav"
    track_path = locale_root / f"audio/track.{track_format}"
    manifest_path = root / "render-manifest.json"
    if manifest_path.exists():
        existing = package.read_object(manifest_path)
        require(Path(existing["track"]["path"]).suffix == f".{track_format}",
                "Cached render uses a different track format")
        package.build_package(paths, manifest_path, root)
        return existing
    plan = schedule(context, rows, policy)
    if plan["status"] != "pass":
        write_json_atomic(root / "render-diagnostics.json", {
            "schemaVersion": "sermon-formal-render-diagnostics-v1", "status": "schedule_overflow",
            "jobJsonSha256": identity.json_sha256(context["job"]),
            "targetLocale": locale, "schedule": plan})
        raise ValueError(f"Measured target audio exceeds 1x clip schedule: {plan['issues'][0]}")
    clip_duration = context["clip_timeline_map"]["clipDurationSeconds"]
    sample_rate = None
    channels = None
    waves = []
    for row in rows:
        audio = root / row["audio"]["path"]
        with wave_module.open(str(audio), "rb") as handle:
            rate = handle.getframerate()
            width = handle.getsampwidth()
            channel_count = handle.getnchannels()
            signal = handle.readframes(handle.getnframes())
            require(len(signal) == handle.getnframes() * channel_count * width,
                    f"Unit cannot be fully decoded: {audio}")
        require(signal and width == 2, f"Unit must be non-empty PCM16: {audio}")
        if sample_rate is None:
            sample_rate, channels = rate, channel_count
        require(rate == sample_rate and channel_count == channels,
                "Units differ in sample rate or channel count; renderer does not resample")
        waves.append(signal)
    length = round(clip_duration * sample_rate)
    track = bytearray(length * channels * 2)
    for entry, encoded in zip(plan["entries"], waves):
        start = round(entry["plannedStart"] * sample_rate)
        require(start + len(encoded) // (channels * 2) <= length,
                f"Sample-exact unit exceeds clip length: {entry['textGroupId']}")
        offset = start * channels * 2
        track[offset:offset + len(encoded)] = encoded
    # No time stretching, truncation, loudness normalization, or omitted units.
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    partial = wav_path.with_suffix(".partial.wav")
    with wave_module.open(str(partial), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(track)
    integrity.probe_full_decode(partial)
    if wav_path.exists():
        require(identity.sha256(wav_path) == identity.sha256(partial),
                "Existing track differs from newly assembled 1x audio")
        partial.unlink()
    else:
        os.replace(partial, wav_path)
    if track_format == "mp3":
        partial_mp3 = track_path.with_suffix(".partial.mp3")
        encoded = subprocess.run([
            "ffmpeg", "-nostdin", "-xerror", "-v", "error", "-y",
            "-i", str(wav_path), "-map", "0:a:0", "-ac", "1",
            "-c:a", "libmp3lame", "-b:a", "64k", "-write_xing", "0",
            "-map_metadata", "-1", "-f", "mp3", str(partial_mp3),
        ], capture_output=True, text=True, check=False)
        require(encoded.returncode == 0 and partial_mp3.is_file(),
                f"Formal MP3 encode failed: {encoded.stderr[:400]}")
        integrity.probe_full_decode(partial_mp3)
        if track_path.exists():
            require(identity.sha256(track_path) == identity.sha256(partial_mp3),
                    "Existing compressed track differs from new render")
            partial_mp3.unlink()
        else:
            os.replace(partial_mp3, track_path)
    plan["trackDurationSeconds"] = integrity.probe_full_decode(track_path)["durationSeconds"]
    captions = {"cues": [{"textGroupId": group["translationGroupId"],
                         "text": group["targetText"],
                         "start": entry["plannedStart"], "end": entry["plannedEnd"]}
                        for group, entry in zip(context["candidate"]["groups"], plan["entries"])]}
    for path, value in ((schedule_path, plan), (captions_path, captions)):
        if path.exists():
            require(package.read_object(path) == value, f"Existing artifact differs: {path}")
        else:
            write_json_atomic(path, value)
    attestation_path = Path(context["clip_voice_authorization"]["userRightsAttestation"]["path"])
    auth_path = root / "review/user-rights-attestation.json"
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    if auth_path.exists():
        require(identity.sha256(auth_path) == identity.sha256(attestation_path),
                "Cached user rights attestation changed")
    else:
        auth_path.write_bytes(attestation_path.read_bytes())
    adapter = context["adapter"]
    manifest = {
        "schemaVersion": package.RENDER_SCHEMA,
        "targetLocale": locale,
        "englishSourcePackageJsonSha256": identity.json_sha256(context["source"]),
        "targetLanguageCandidateJsonSha256": identity.json_sha256(context["candidate"]),
        "targetLanguageSpeechJobJsonSha256": identity.json_sha256(context["job"]),
        "clipTimelineMapJsonSha256": identity.json_sha256(context["clip_timeline_map"]),
        "voice": {"targetLocale": locale, "provider": adapter["provider"],
                  "model": adapter["model"], "modelRevision": adapter["modelRevision"],
                  "voice": adapter["voice"], "speakerId": adapter["speakerId"],
                  "checkpointSha256": adapter["conditioningSha256"],
                  "authorizationStatus": "authorized", "targetLocaleCapability": "reviewed"},
        "voiceAuthorization": artifact(root, auth_path, json_artifact=True),
        "units": rows, "track": artifact(root, track_path),
        "schedule": artifact(root, schedule_path, json_artifact=True),
        "captions": artifact(root, captions_path),
        "machineScreening": {"status": "not_run", "model": None, "coverage": 0.0},
    }
    write_json_atomic(manifest_path, manifest)
    return manifest


def render(paths: dict[str, Path], checkpoint_map_path: Path,
           operation_policies_path: Path, *, path_map_path: Path | None = None,
           reuse_from: Path | None = None,
           speculative_from: Path | None = None,
           seed: int = 42,
           device: str = "cuda:0", dtype: str = "bfloat16",
           attention: str | None = "sdpa", instruct: str | None = None,
           policy: dict[str, float] | None = None, track_format: str = "wav",
           synth_factory: Callable[..., Any] = QwenSynthesizer) -> dict[str, Any]:
    if path_map_path is not None:
        materialize_path_map(paths["job"], path_map_path)
    context = checked_context(paths, checkpoint_map_path, operation_policies_path)
    root = paths["job"].parent.resolve()
    rows = render_units(context, paths, root, checkpoint_map_path, seed=seed,
                        device=device, dtype=dtype, attention=attention, instruct=instruct,
                        reuse_from=reuse_from,
                        speculative_from=speculative_from,
                        synth_factory=synth_factory)
    return assemble(context, paths, root, rows, policy=policy, track_format=track_format)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "anchor", "candidate", "job", "adapter", "policy"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--human-review-receipt", dest="human_receipt", type=Path, required=True)
    parser.add_argument("--speaker-registry", dest="registry", type=Path, required=True)
    parser.add_argument("--clip-voice-authorization", dest="clip_voice_authorization",
                        type=Path, required=True)
    parser.add_argument("--clip-voice-capability", dest="clip_voice_capability", type=Path)
    parser.add_argument("--clip-timeline-map", dest="clip_timeline_map", type=Path, required=True)
    parser.add_argument("--checkpoint-map", type=Path, required=True)
    parser.add_argument("--audio-operation-policies", type=Path, required=True)
    parser.add_argument("--path-map", type=Path,
                        help="Exact original absolute path to staged container file map")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", choices=("bfloat16", "float32"), default="bfloat16")
    parser.add_argument("--attention", default="sdpa")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--instruct", help="Frozen natural delivery instruction; never edits approved text")
    parser.add_argument("--reaction-lag-seconds", type=float, default=0.05)
    parser.add_argument("--inter-utterance-gap-seconds", type=float, default=0.05)
    parser.add_argument("--max-end-lag-seconds", type=float, default=8.0)
    parser.add_argument("--track-format", choices=("wav", "mp3"), default="wav",
                        help="Use reviewed 64 kbps mono MP3 for a full-length web release")
    parser.add_argument("--reuse-from", type=Path,
                        help="Previously validated render directory for unchanged units")
    parser.add_argument("--speculative-from", type=Path,
                        help="Preview-only unit audio; formal human and rights gates still run first")
    args = parser.parse_args()
    paths = {name: getattr(args, name) for name in ("source", "anchor", "candidate",
                                                   "job", "adapter", "policy", "human_receipt",
                                                   "registry", "clip_voice_authorization",
                                                   "clip_timeline_map")}
    if args.clip_voice_capability:
        paths["clip_voice_capability"] = args.clip_voice_capability
    policy = {"reactionLagSeconds": args.reaction_lag_seconds,
              "interUtteranceGapSeconds": args.inter_utterance_gap_seconds,
              "maxEndLagSeconds": args.max_end_lag_seconds}
    result = render(paths, args.checkpoint_map, args.audio_operation_policies,
                    path_map_path=args.path_map, reuse_from=args.reuse_from,
                    speculative_from=args.speculative_from,
                    seed=args.seed, device=args.device,
                    dtype=args.dtype, attention=args.attention, instruct=args.instruct,
                    policy=policy, track_format=args.track_format)
    print(json.dumps({"status": "candidate", "targetLocale": result["targetLocale"],
                      "renderManifest": str((paths["job"].parent / "render-manifest.json").resolve()),
                      "machineScreening": "not_run", "humanListeningReview": "pending"},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
