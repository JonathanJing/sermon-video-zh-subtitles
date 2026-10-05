#!/usr/bin/env python3
"""Resume a human-approved Layer 3 speech job and assemble a natural 1x clip track.

The job directory is the artifact root. Render cache records are clip, text,
adapter, checkpoint, settings, and implementation bound. No ASR or human review
is inferred from rendering. A schedule that exceeds the clip leaves diagnostics
and fully decoded units, but no release manifest.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import ExitStack
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
from typing import Any, Callable
import wave as wave_module

try:
    from scripts import build_target_language_audio_package as package
    from scripts import four_layer_measure as measure
    from scripts import render_multilingual_voice_demos as demos
    from scripts import sermon_accounting as accounting
    from scripts import sermon_sentence_interpretation as identity
    from scripts import validate_target_language_audio_unit as integrity
    from scripts import dev_audio_test_profile as dev_profile
    from scripts import target_audio_recovery as recovery
    from scripts import target_audio_anomaly as anomaly
    from scripts import dev_audio_test_receipts as dev_receipts
    from scripts import spark_tts_replica_pool as replica_pool
    from scripts.spark_tts_window_scheduler import ParallelBatchEngine
except ImportError:
    import build_target_language_audio_package as package
    import four_layer_measure as measure
    import render_multilingual_voice_demos as demos
    import sermon_accounting as accounting
    import sermon_sentence_interpretation as identity
    import validate_target_language_audio_unit as integrity
    import dev_audio_test_profile as dev_profile
    import target_audio_recovery as recovery
    import target_audio_anomaly as anomaly
    import dev_audio_test_receipts as dev_receipts
    import spark_tts_replica_pool as replica_pool
    from spark_tts_window_scheduler import ParallelBatchEngine


VERSION = "sermon-formal-target-speech-render-v1"
# Observability-only edits must not invalidate already rendered sound. The
# accounting execution identity still records the current file's actual hash.
RENDERER_SOUND_IDENTITY_SHA256 = "fef7604882470137f46f1b01fbd06c7c3c9a07166da91003243608785fa47f0b"
DEFAULT_POLICY = {"reactionLagSeconds": 0.05, "interUtteranceGapSeconds": 0.05,
                  "maxEndLagSeconds": 8.0}
BATCH_SIZES = (1, 2, 4, 8)
BATCH_SEED_POLICY = "base_plus_fixed_window_start_ordered_full_window_v2"
BATCH_CACHED_UNIT_POLICY = "replay_full_bound_window_when_units_are_missing_v1"
LEGACY_BATCH_SEED_POLICY = "base_plus_fixed_window_start_ordered_missing_units_v1"
LEGACY_BATCH_CACHED_UNIT_POLICY = "exclude_committed_or_admitted_reuse"
COMPATIBLE_BATCH_REPAIR_IMPLEMENTATION_SHA256 = {
    # Strict receipt snapshots, diagnostics and recovery do not change sampling.
    "948b3174bad368e8f80381beaca0d519299d16a927e50add934cb2111a90ebb2",
    "a86c470ed8f2efb7b94f62cc5451e0f3e6af9a15d13110d86086489daeedd58c",
    # Direct dev parent: serial full-window inputs and sampling are unchanged.
    "085f8d21ab1263b96a32a0361582470dc8a1a6bab71b22383796fe90180d32b2",
    # Direct parent: lossless diagnostic snapshots do not change model inputs,
    # sampling, ordered full-window replay, or sound identity.
    "bf7fee0c5f9f4abcc24dfc5334fe0d95d9aba60db0a0de0a08b3d8a00d5d0a42"
}


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
    pending = _evidence_paths(inputs)
    references = []
    seen: dict[str, dict[str, Any]] = {}
    while pending:
        ref = pending.pop(0)
        original = ref["path"]
        if original in seen:
            require(seen[original] == ref, f"Conflicting mapped evidence: {original}")
            continue
        seen[original] = ref
        original = Path(ref["path"])
        staged = Path(aliases.get(str(original), str(original)))
        require(original.is_absolute() and staged.is_absolute() and staged.is_file()
                and identity.sha256(staged) == ref["sha256"],
                f"Mapped evidence missing or hash mismatch: {original}")
        if "jsonSha256" in ref:
            value = json.loads(staged.read_text(encoding="utf-8"))
            require(identity.json_sha256(value) == ref["jsonSha256"],
                    f"Mapped evidence JSON hash mismatch: {original}")
            pending.extend(_evidence_paths(value))
        references.append(ref)
    # Only after all hash checks pass may aliases be made visible to legacy
    # validators that dereference absolute paths from the unchanged job JSON.
    for ref in references:
        original = Path(ref["path"])
        staged = Path(aliases.get(str(original), str(original)))
        if original.exists():
            require(original.is_file() and identity.sha256(original) == ref["sha256"],
                    f"Existing source path differs from mapped evidence: {original}")
            continue
        require(str(original) in aliases, f"No path-map entry for inaccessible job path: {original}")
        original.parent.mkdir(parents=True, exist_ok=True)
        original.symlink_to(staged)


def checkpoint_directories(job_path, checkpoint_map_path, *, assembly_only=False):
    if assembly_only:
        return []
    job = package.read_object(job_path)
    mapping = package.read_object(checkpoint_map_path)
    choices = [row for row in mapping.get("checkpoints", [])
               if row.get("speakerId") == job["adapter"]["speakerId"]]
    require(len(choices) == 1 and isinstance(choices[0].get("path"), str),
            "Checkpoint map must bind one model directory")
    return [Path(choices[0]["path"]).absolute()]


def checked_context(paths: dict[str, Path], checkpoint_map_path: Path,
                    operation_policies_path: Path, *,
                    strict_rubric: dict[str, Any] | None = None,
                    assembly_only: bool = False) -> dict[str, Any]:
    required = ("source", "anchor", "candidate", "job", "adapter", "policy",
                "human_receipt", "registry", "clip_timeline_map")
    require(all(name in paths and paths[name].is_file() for name in required),
            "Missing formal Layer 3 input")
    require(("clip_voice_authorization" in paths) != ("source_voice_authorization" in paths),
            "Formal Layer 3 requires exactly one source-bound voice authorization")
    data = {name: package.read_object(path) for name, path in paths.items()}
    package.validate_job(data["source"], data["anchor"], data["candidate"],
                         data["job"], data["adapter"], data["policy"],
                         data["human_receipt"], data["registry"],
                         data.get("clip_voice_authorization"),
                         data.get("clip_voice_capability"), data["clip_timeline_map"], paths,
                         source_voice_authorization=data.get("source_voice_authorization"),
                         strict_rubric=strict_rubric)
    if strict_rubric is not None:
        data["strict_rubric"] = strict_rubric
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
    if assembly_only:
        # No model bytes are consumed on this path. All cached sound identities
        # and WAV receipts still pass admission; a cache miss cannot load a model.
        require(isinstance(mapping.get("path"), str) and mapping["path"], "Missing checkpoint locator")
        checkpoint = Path(mapping["path"])
        require(job["adapter"]["conditioningSha256"] == adapter["conditioningSha256"],
                "Cached checkpoint identity differs from speech job")
    else:
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
        require(len(wavs) == 1, "TTS returned an incomplete or extra scalar output")
        return wavs[0], sample_rate

    def batch(self, requests: list[dict[str, Any]], *, seed: int) -> list[dict[str, Any]]:
        self.torch.manual_seed(seed)
        if self.torch.cuda.is_available():
            self.torch.cuda.manual_seed_all(seed)
        kwargs = {"text": [row["text"] for row in requests],
                  "language": [row["language"] for row in requests],
                  "speaker": [row["speaker"] for row in requests],
                  "temperature": 0.7, "repetition_penalty": 1.05, "max_new_tokens": 768}
        if any(row["instruct"] for row in requests):
            kwargs["instruct"] = [row["instruct"] or "" for row in requests]
        wavs, sample_rate = self.model.generate_custom_voice(**kwargs)
        require(len(wavs) == len(requests), "TTS batch output cardinality differs")
        return [{"identity": row["identity"], "wave": wav, "sampleRate": sample_rate}
                for row, wav in zip(requests, wavs)]


class SparkQwenSynthesizer(QwenSynthesizer):
    """Match the measured Spark worker's CPU settings and completed GPU timing."""
    def __init__(self, *args, **kwargs):
        os.environ["OMP_NUM_THREADS"] = "4"
        os.environ["MKL_NUM_THREADS"] = "4"
        import torch
        torch.set_num_threads(4)
        torch.set_num_interop_threads(1)
        super().__init__(*args, **kwargs)
        torch.cuda.synchronize()

    def batch(self, requests, *, seed):
        values = super().batch(requests, seed=seed)
        self.torch.cuda.synchronize()
        return values


def _intent(context: dict[str, Any], paths: dict[str, Path], index: int, *, seed: int,
            dtype: str, attention: str | None, instruct: str | None,
            spoken_text: str | None = None, batch_size: int = 1,
            device: str = "cuda:0", batch_window_sha256: str | None = None,
            replicas: int = 1) -> dict[str, Any]:
    job, adapter = context["job"], context["adapter"]
    unit = job["units"][index]
    result = {
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
        "rendererSha256": RENDERER_SOUND_IDENTITY_SHA256,
        "seed": seed, "temperature": 0.7, "repetitionPenalty": 1.05,
        "maxNewTokens": 768, "dtype": dtype, "attention": attention,
        "deliveryInstruction": instruct,
        "ratePolicy": "natural_no_time_stretch",
    }
    if spoken_text is not None:
        result["spokenTextSha256"] = hashlib.sha256(spoken_text.encode()).hexdigest()
    if batch_size != 1:
        start = index // batch_size * batch_size
        result.update(batchSize=batch_size, batchSeedPolicy=BATCH_SEED_POLICY,
                      batchExecutionDevice=device,
                      batchImplementationSha256=identity.sha256(Path(__file__)),
                      batchWindowInputsSha256=batch_window_sha256,
                      batchWindowStart=start,
                      batchWindowUnitIndices=list(range(start, min(start + batch_size, len(job["units"])))),
                      batchCachedUnitPolicy=BATCH_CACHED_UNIT_POLICY)
    if replicas != 1:
        result.update(schemaVersion="sermon-formal-target-speech-render-v2",
                      replicaCount=replicas,
                      replicaPolicy="spark_single_speaker_fixed_windows_v1",
                      replicaImplementationSha256=identity.json_sha256({
                          "pool": identity.sha256(Path(replica_pool.__file__)),
                          "scheduler": identity.sha256(Path(__file__).with_name("spark_tts_window_scheduler.py"))}))
    return result


SPECULATIVE_MATCH_FIELDS = (
    "unitIndex", "sourceJsonSha256", "anchorJsonSha256", "translationPolicySha256",
    "adapterId", "model", "modelRevision", "conditioningRef",
    "checkpointMapFileSha256", "operationPoliciesFileSha256", "checkpointSha256",
    "speakerId", "speakerKey", "targetLocale", "languageParameter", "groupId",
    "sourceUnitIds", "textSha256", "rendererSha256", "seed", "temperature",
    "repetitionPenalty", "maxNewTokens", "dtype", "attention",
    "deliveryInstruction", "ratePolicy",
)

# This renderer revision added per-unit spoken forms and delivery instructions.
# For an old unit with no spoken-form override, unchanged text, instruction,
# model settings and a verified audio hash preserve the same sound intent.
COMPATIBLE_NO_SPOKEN_FORM_RENDERER_SHA256 = {
    "7975b13796b0269adfad1b5188f981102eb9359c7d2627e0ebbfd69c0f97b56c"
}
# This revision changes only how a preview snapshot's demo voice capability is
# checked during admission. It does not change the synthesis inputs or sound.
COMPATIBLE_PREVIEW_ADMISSION_RENDERER_SHA256 = {
    "462f63dfd3cc215ce923c187d9904ab89145a587a732a7ed1b5f6a9d41fb7985"
}
# The direct dev parent used its complete file hash before sound identity was
# stabilized. Its synthesis inputs are unchanged by the merge's accounting edits.
COMPATIBLE_INTEGRATED_PARENT_RENDERER_SHA256 = {
    "e17cd486a63c792bb36b0fcdecab1e02b66fac9c6fd8005f4a9363f3eaffe3d5"
}


def _same_integrated_parent_sound_intent(actual: dict[str, Any],
                                         expected: dict[str, Any]) -> bool:
    return (actual.get("rendererSha256") in COMPATIBLE_INTEGRATED_PARENT_RENDERER_SHA256
            and {key: value for key, value in actual.items() if key != "rendererSha256"}
            == {key: value for key, value in expected.items() if key != "rendererSha256"})


def _same_compatible_batch_repair_intent(actual: dict[str, Any],
                                         expected: dict[str, Any]) -> bool:
    """Keep safe full-window cache entries across the resume-membership repair."""
    if actual.get("batchImplementationSha256") not in COMPATIBLE_BATCH_REPAIR_IMPLEMENTATION_SHA256:
        return False
    old = dict(actual)
    new = dict(expected)
    old.pop("batchImplementationSha256", None)
    new.pop("batchImplementationSha256", None)
    # The prior pool differs only in reserve-failure telemetry.
    if old.get("replicaImplementationSha256") == "fcbfe1c288a0d525e172edc47eff957305fbe0c65085d12617870bfa5b12fdfc":
        old["replicaImplementationSha256"] = new.get("replicaImplementationSha256")
    if old.get("batchSeedPolicy") == LEGACY_BATCH_SEED_POLICY:
        old["batchSeedPolicy"] = new.get("batchSeedPolicy")
    if old.get("batchCachedUnitPolicy") == LEGACY_BATCH_CACHED_UNIT_POLICY:
        old["batchCachedUnitPolicy"] = new.get("batchCachedUnitPolicy")
    return old == new


def _generation_batch_matches(commit: dict[str, Any], intent: dict[str, Any]) -> bool:
    generation = commit.get("generationBatch")
    indices = intent.get("batchWindowUnitIndices")
    seed, start = intent.get("seed"), intent.get("batchWindowStart")
    if (not isinstance(generation, dict) or not isinstance(indices, list)
            or type(seed) is not int or type(start) is not int
            or generation.get("unitIndices") != indices
            or generation.get("seed") != seed + start
            or generation.get("batchSize") != intent.get("batchSize")):
        return False
    policy = generation.get("seedPolicy")
    return policy in {intent.get("batchSeedPolicy"), LEGACY_BATCH_SEED_POLICY, BATCH_SEED_POLICY}


def _spoken_equivalent(approved: str, spoken: str) -> bool:
    """Allow only punctuation and the confirmed Revelation 3:16 reading."""
    def normalized(value: str) -> str:
        value = re.sub(r"第3章第16节|3:16|第三章第十六节", "第三章第十六节", value)
        return "".join(char for char in value if char.isalnum())
    return normalized(approved) == normalized(spoken)


def unit_instructions(job: dict[str, Any], path: Path | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    document = package.read_object(path)
    require(document.get("schemaVersion") == "sermon-unit-delivery-instructions-v1"
            and document.get("targetLocale") == job["targetLocale"]
            and document.get("speechJobJsonSha256") == identity.json_sha256(job)
            and isinstance(document.get("units"), list)
            and document["units"], "Unit delivery instruction identity differs")
    allowed = {unit["translationGroupId"]: unit for unit in job["units"]}
    result: dict[str, dict[str, str]] = {}
    for row in document["units"]:
        group = row.get("translationGroupId")
        instruction = row.get("instruction")
        require(group in allowed and group not in result
                and row.get("approvedTextSha256") == hashlib.sha256(allowed[group]["text"].encode()).hexdigest()
                and isinstance(instruction, str) and instruction.strip()
                and isinstance(row.get("operatorEvidence"), str) and row["operatorEvidence"].strip(),
                "Unit delivery instruction lacks approved text or operator evidence")
        spoken = row.get("spokenText")
        if spoken is not None:
            require(job["targetLocale"] == "zh-Hans" and isinstance(spoken, str)
                    and spoken.strip() and _spoken_equivalent(allowed[group]["text"], spoken),
                    "Spoken form changes approved words or unsupported locale")
        result[group] = {"instruction": instruction.strip()}
        if spoken is not None:
            result[group]["spokenText"] = spoken.strip()
    return result


def _reusable_speculative_audio(previous_root: Path, unit: dict[str, Any], index: int,
                                expected: dict[str, Any], *, strict_rubric=None) -> Path | None:
    """Admit only the same sound from an explicitly non-formal pre-render lane."""
    if expected.get("spokenTextSha256") is not None or expected.get("batchSize", 1) != 1:
        return None
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
    package.speech.validate_policy_binding(snapshot, evidence["policy"], strict_rubric=strict_rubric)
    package.speech.validate_adapter(evidence["adapter"], snapshot["targetLocale"],
                                    evidence["registry"],
                                    source_package=evidence["source"], candidate=snapshot,
                                    preview_only=True)
    require(evidence["adapter"].get("authorizationPurpose") == "multilingual_voice_demo"
            or (snapshot["targetLocale"] == "zh-Hans"
                and evidence["adapter"].get("authorizationPurpose") == "chinese_dubbing"),
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
    require(isinstance(groups, list), "Speculative candidate groups are malformed")
    if index >= len(groups):
        return None
    require(isinstance(groups[index], dict),
            "Speculative candidate unit is malformed")
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
    expected_sound = {key: expected[key] for key in SPECULATIVE_MATCH_FIELDS}
    if sound != expected_sound:
        previous_renderer = sound.get("rendererSha256")
        # Preview receipts bind the renderer file hash, while formal intents
        # keep the stable sound identity across observability-only edits.
        if (previous_renderer not in COMPATIBLE_PREVIEW_ADMISSION_RENDERER_SHA256
                and previous_renderer not in COMPATIBLE_INTEGRATED_PARENT_RENDERER_SHA256
                and previous_renderer != identity.sha256(Path(__file__))):
            return None
        expected_sound["rendererSha256"] = previous_renderer
        if sound != expected_sound:
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
    if expected.get("batchSize", 1) != 1 and not _generation_batch_matches(old_commit, old_intent):
        return None
    whole_job_fields = {"jobJsonSha256", "jobFileSha256", "candidateJsonSha256"}
    old_unit_identity = {key: value for key, value in old_intent.items()
                         if key not in whole_job_fields}
    new_unit_identity = {key: value for key, value in expected.items()
                         if key not in whole_job_fields}
    if old_unit_identity != new_unit_identity:
        if _same_integrated_parent_sound_intent(old_unit_identity, new_unit_identity):
            integrity.probe_full_decode(old_audio_path)
            return old_audio_path
        if _same_compatible_batch_repair_intent(old_unit_identity, new_unit_identity):
            integrity.probe_full_decode(old_audio_path)
            return old_audio_path
        previous_renderer = old_unit_identity.get("rendererSha256")
        old_unit_identity.pop("rendererSha256", None)
        new_unit_identity.pop("rendererSha256", None)
        if (previous_renderer not in COMPATIBLE_NO_SPOKEN_FORM_RENDERER_SHA256
                or old_intent.get("spokenTextSha256") is not None
                or expected.get("spokenTextSha256") is not None
                or old_unit_identity != new_unit_identity):
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


def _batch_admission(context, paths, root, *, seed, dtype, attention, instruct, device,
                     instructions_by_group, batch_size, reuse_from, speculative_from,
                     window_hashes, replicas=1):
    """Freeze/check every unit before a batched call can synthesize future units."""
    job, adapter = context["job"], context["adapter"]
    require(identity.json_sha256(package.read_object(paths["job"])) == identity.json_sha256(job),
            "Batch job differs from the checked input")
    requests, reusable, window_requests, pending_intents = {}, {}, {}, []
    groups, outputs = set(), set()
    for index, unit in enumerate(job["units"]):
        group = unit["translationGroupId"]
        require(isinstance(unit.get("text"), str) and unit["text"].strip()
                and group not in groups and unit["outputRelativePath"] not in outputs,
                "TTS batch units require unique groups/outputs and nonempty text")
        groups.add(group)
        outputs.add(unit["outputRelativePath"])
        wav = root / unit["outputRelativePath"]
        require(wav.resolve().is_relative_to(root.resolve()), "TTS batch unit escapes render root")
        overrides = (instructions_by_group or {}).get(group, {})
        instruction = overrides.get("instruction", instruct)
        spoken = overrides.get("spokenText")
        expected = _intent(context, paths, index, seed=seed, dtype=dtype,
                           attention=attention, instruct=instruction, spoken_text=spoken,
                           batch_size=batch_size, device=device,
                           batch_window_sha256=window_hashes[index // batch_size * batch_size], replicas=replicas)
        request = {"identity": expected, "text": spoken or unit["text"],
                   "language": adapter["languageParameter"],
                   "speaker": adapter["speakerKey"], "instruct": instruction}
        window_requests[index] = request
        intent_path = root / f"receipts/unit-{index:04d}.intent.json"
        commit_path = root / f"receipts/unit-{index:04d}.render.json"
        receipt_path = root / f"receipts/unit-{index:04d}.json"
        if intent_path.exists():
            stored_intent = package.read_object(intent_path)
            require(stored_intent == expected
                    or _same_compatible_batch_repair_intent(stored_intent, expected),
                    f"Cached render identity differs: {group}")
        else:
            require(not any(path.exists() for path in (wav, commit_path, receipt_path)),
                    f"Orphaned audio/receipt cannot be reused: {group}")
            pending_intents.append((intent_path, expected))
        if commit_path.exists():
            commit = package.read_object(commit_path)
            audio = wav if wav.exists() else wav.with_suffix(".partial.wav")
            stored_intent = package.read_object(intent_path)
            require(commit.get("identity") == stored_intent and audio.is_file()
                    and commit.get("audioSha256") == identity.sha256(audio),
                    f"Cached audio identity or hash changed: {group}")
            require(_generation_batch_matches(commit, stored_intent),
                    f"Cached batch generation did not preserve its full window: {group}")
            if receipt_path.exists():
                if audio != wav:
                    # Recover only bytes already bound by the immutable commit.
                    os.replace(audio, wav)
                integrity.validate_receipt(paths["job"], index, wav,
                    package.read_object(receipt_path),
                    validated_job=job, validated_job_file_sha256=expected["jobFileSha256"],
                    **({"strict_rubric": context["strict_rubric"]}
                       if context.get("strict_rubric") is not None else {}))
            continue
        require(not wav.exists(), f"Uncommitted audio cannot be reused: {wav}")
        previous = (_reusable_audio(reuse_from, unit, index, expected)
                    if reuse_from is not None else None)
        # Preview scalar audio deliberately cannot satisfy a batch sound intent.
        reusable[index] = previous
        if previous is None:
            requests[index] = request
    for path, expected in pending_intents:
        write_json_atomic(path, expected)
    return requests, reusable, window_requests


class _BatchedUnitSynthesizer:
    """Replay each complete bound window, then return only missing waveforms."""
    def __init__(self, engine, requests, *, window_requests, seed, batch_size, job_path):
        require(callable(getattr(engine, "batch", None)), "TTS engine has no batch method")
        self.engine, self.requests = engine, requests
        self.window_requests = window_requests
        self.seed, self.batch_size, self.job_path = seed, batch_size, job_path
        self.frozen_job_sha = identity.sha256(job_path)
        self.remaining = list(requests)
        self.outputs = {}
        self.last_generation = None
        self.last_generation_trigger_index = None
        self.instruct = None

    def __call__(self, text, language, speaker, *, seed):
        require(self.remaining, "TTS batch received an extra unit call")
        index = self.remaining[0]
        request = self.requests[index]
        require((text, language, speaker, seed) == (
            request["text"], request["language"], request["speaker"], self.seed + index),
            "TTS batch unit request order or input differs")
        require(identity.sha256(self.job_path) == self.frozen_job_sha,
                "Frozen TTS batch job changed before synthesis")
        if index not in self.outputs:
            require(not self.outputs, "TTS batch window was not fully consumed")
            start = index // self.batch_size * self.batch_size
            indices = list(range(start, min(start + self.batch_size, len(self.window_requests))))
            require(all(i in self.window_requests for i in indices),
                    "TTS batch window is missing a bound member")
            batch = [self.window_requests[i] for i in indices]
            batch_seed = self.seed + start
            values = self.engine.batch(copy.deepcopy(batch), seed=batch_seed)
            require(isinstance(values, list) and len(values) == len(batch),
                    "TTS batch output cardinality differs")
            for row, expected in zip(values, batch):
                require(isinstance(row, dict) and row.get("identity") == expected["identity"]
                        and "wave" in row and isinstance(row.get("sampleRate"), int)
                        and row["sampleRate"] > 0,
                        "TTS batch output identity/order or sample rate differs")
            require(identity.sha256(self.job_path) == self.frozen_job_sha,
                    "Frozen TTS batch job changed during synthesis")
            generation = {"unitIndices": indices, "seed": batch_seed,
                          "seedPolicy": BATCH_SEED_POLICY, "batchSize": self.batch_size}
            self.last_generation_trigger_index = index
            self.outputs = {i: (row, generation) for i, row in zip(indices, values)
                            if i in self.requests}
        value, self.last_generation = self.outputs.pop(index)
        self.remaining.pop(0)
        return value["wave"], value["sampleRate"]


def _render_units(context: dict[str, Any], paths: dict[str, Path], root: Path,
                 checkpoint_map_path: Path, *, seed: int = 42, device: str = "cuda:0",
                 dtype: str = "bfloat16", attention: str | None = "sdpa",
                 instruct: str | None = None,
                 instructions_by_group: dict[str, dict[str, str]] | None = None,
                 reuse_from: Path | None = None,
                 speculative_from: Path | None = None,
                 batch_size: int = 1, replicas: int = 1,
                 assembly_only: bool = False, max_synthesis_units: int | None = None,
                 model_resources: ExitStack,
                 synth_factory: Callable[..., Any] = QwenSynthesizer,
                 predecessor_spans: tuple[str, ...] = (),
                 completion_spans: list[str] | None = None) -> list[dict[str, Any]]:
    job, adapter = context["job"], context["adapter"]
    validated = context.get("receiptContext")
    if validated is not None:
        require(validated.job == job, "Cached render identity differs: prevalidated job")
    missing = [i for i, unit in enumerate(job["units"])
               if not (root / f"receipts/unit-{i:04d}.render.json").is_file()]
    if assembly_only:
        require(not missing, f"Assembly-only requires all committed units; missing: {missing}")
    if max_synthesis_units is not None:
        require(type(max_synthesis_units) is int and max_synthesis_units >= 0,
                "Invalid synthesis unit budget")
        require(type(batch_size) is int and batch_size in BATCH_SIZES, "Invalid batch size")
        starts = {i // batch_size * batch_size for i in missing}
        generated = sum(min(batch_size, len(job["units"]) - start) for start in starts)
        require(generated <= max_synthesis_units, "Synthesis unit budget exceeded at locked admission")
    require(type(replicas) is int and replicas in (1, 8), "TTS replicas must be 1 or 8")
    if replicas == 8:
        require(batch_size == 8 and device == "cuda:0" and dtype == "bfloat16"
                and attention == "sdpa", "Spark production requires 8 replicas, batch8, CUDA:0/BF16/SDPA")
        require(all(u.get("speakerId", adapter["speakerId"]) == adapter["speakerId"]
                    for u in job["units"]),
                "Spark replica production requires a single speaker")
    require(type(batch_size) is int and batch_size in BATCH_SIZES,
            "TTS batch size must be 1, 2, 4 or 8")
    if reuse_from is not None:
        require(reuse_from.is_dir() and reuse_from.resolve() != root.resolve(),
                "Previous render root must be a distinct existing directory")
    if speculative_from is not None:
        require(speculative_from.is_dir() and speculative_from.resolve() != root.resolve(),
                "Speculative render root must be a distinct existing directory")
    reusable_batches = None
    window_hashes = {}
    if batch_size != 1:
        for start in range(0, len(job["units"]), batch_size):
            inputs = []
            for index in range(start, min(start + batch_size, len(job["units"]))):
                unit = job["units"][index]
                overrides = (instructions_by_group or {}).get(unit["translationGroupId"], {})
                inputs.append({"unitIndex": index, "groupId": unit["translationGroupId"],
                    "sourceUnitIds": unit["sourceUnitIds"], "text": unit["text"],
                    "spokenText": overrides.get("spokenText"),
                    "instruction": overrides.get("instruction", instruct),
                    "language": adapter["languageParameter"], "speaker": adapter["speakerKey"]})
            window_hashes[start] = identity.json_sha256(inputs)
        requests, reusable_batches, window_requests = _batch_admission(
            context, paths, root, seed=seed, dtype=dtype, attention=attention,
            instruct=instruct, device=device, instructions_by_group=instructions_by_group,
            batch_size=batch_size, reuse_from=reuse_from, speculative_from=speculative_from,
            window_hashes=window_hashes, replicas=replicas)
        original_factory = synth_factory
        def synth_factory(*args, **kwargs):
            if replicas == 1:
                engine = original_factory(*args, **kwargs)
            else:
                frozen = identity.sha256(paths["job"])
                def frozen_check():
                    require(identity.sha256(paths["job"]) == frozen,
                            "Frozen TTS batch job changed before/during synthesis")
                starts = sorted({index // batch_size * batch_size for index in requests})
                windows = {start: [window_requests[i] for i in range(start,
                    min(start + batch_size, len(job["units"])))] for start in starts}
                runtime_path = root / "replica-runtime.json"
                runtime = {"schemaVersion": "sermon-spark-tts-replica-runtime-v1",
                    "status": "running", "replicas": replicas, "batchSize": batch_size,
                    "jobSha256": frozen, "reserveGiB": 24,
                    "rendererSha256": identity.sha256(Path(__file__)),
                    "poolSha256": identity.sha256(Path(replica_pool.__file__)), "events": []}
                def event(row):
                    runtime["events"].append(row)
                    write_json_atomic(runtime_path, runtime)
                def finish_runtime():
                    runtime["status"] = "closed"
                    write_json_atomic(runtime_path, runtime)
                model_resources.callback(finish_runtime)
                worker_factory = SparkQwenSynthesizer if original_factory is QwenSynthesizer else original_factory
                pool = replica_pool.ReplicaPool(args[0], factory=worker_factory,
                    engine_kwargs=kwargs, replicas=replicas, telemetry=event)
                model_resources.callback(pool.close)
                engine = ParallelBatchEngine(pool, windows, seed=seed, frozen_check=frozen_check)
            return _BatchedUnitSynthesizer(engine, requests,
                window_requests=window_requests, seed=seed, batch_size=batch_size,
                job_path=paths["job"])
    model = None
    model_load_span = None
    previous_receipts = accounting.bounded_dependencies(
        "layer3.unit_admission_join", predecessor_spans, work_unit_id="l3.unit_admission_join")
    rows = []
    for index, unit in enumerate(job["units"]):
        overrides = (instructions_by_group or {}).get(unit["translationGroupId"], {})
        unit_instruct = overrides.get("instruction", instruct)
        spoken_text = overrides.get("spokenText")
        wav_path = root / unit["outputRelativePath"]
        receipt_path = root / f"receipts/unit-{index:04d}.json"
        intent_path = root / f"receipts/unit-{index:04d}.intent.json"
        commit_path = root / f"receipts/unit-{index:04d}.render.json"
        stage_name = f"layer3.unit.{job['targetLocale']}.{index:04d}"
        unit_metrics = {"unitIndex": index, "reusedCurrent": commit_path.exists(),
                        "reusedPrior": False, "reusedPreview": False,
                        "synthesized": False}
        with accounting.stage(stage_name, cache_hit=commit_path.exists()):
            work_unit = f"l3.{job['targetLocale']}.{index:04d}"
            has_commit = commit_path.exists()
            with accounting.stage(f"layer3.cache_admission.{job['targetLocale']}.{index:04d}",
                                  work_unit_id=work_unit + ".cache_admission",
                                  depends_on=previous_receipts) as admission_span:
                expected = _intent(context, paths, index, seed=seed, dtype=dtype,
                                   attention=attention, instruct=unit_instruct,
                                   spoken_text=spoken_text, batch_size=batch_size, device=device,
                                   batch_window_sha256=window_hashes.get(index // batch_size * batch_size), replicas=replicas)
                if intent_path.exists():
                    stored_intent = package.read_object(intent_path)
                    require(stored_intent == expected
                            or _same_integrated_parent_sound_intent(stored_intent, expected)
                            or _same_compatible_batch_repair_intent(stored_intent, expected),
                            f"Cached render identity differs: {unit['translationGroupId']}")
                    render_identity = stored_intent
                else:
                    require(not any(path.exists() for path in (wav_path, receipt_path, commit_path)),
                            f"Orphaned audio/receipt cannot be reused: {unit['translationGroupId']}")
                    write_json_atomic(intent_path, expected)
                    render_identity = expected
                if has_commit:
                    commit = package.read_object(commit_path)
                    require(commit.get("identity") == stored_intent,
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
                    previous = (reusable_batches[index] if reusable_batches is not None else
                                _reusable_audio(reuse_from, unit, index, expected)
                                if reuse_from is not None else None)
                    unit_metrics["reusedPrior"] = previous is not None
                    if previous is None and speculative_from is not None:
                        previous = _reusable_speculative_audio(speculative_from, unit, index, expected,
                            strict_rubric=context.get("strict_rubric"))
                        unit_metrics["reusedPreview"] = previous is not None
            if not has_commit:
                if partial.exists():
                    anomaly.preserve(root, job, index, reason="uncommitted_partial_before_replacement",
                                     audio_relative_path=str(partial.relative_to(root)))
                if previous is not None:
                    with accounting.stage(f"layer3.reuse.{job['targetLocale']}.{index:04d}", work_unit_id=work_unit + ".reuse",
                                          cache_hit=True, depends_on=[admission_span]) as audio_span:
                        shutil.copyfile(previous, partial)
                else:
                    unit_metrics["synthesized"] = True
                    # Loading is a separate deterministic leaf. Nesting it under
                    # synthesis would hide the first model call in leaf reports.
                    if model is None:
                        with accounting.stage(f"layer3.model_load.{job['targetLocale']}",
                                              depends_on=[admission_span],
                                              work_unit_id=f"l3.{job['targetLocale']}.model_load") as model_load_span:
                            model = synth_factory(context["checkpoint"], device=device, dtype=dtype,
                                                  attention=attention, instruct=unit_instruct)
                    else:
                        model.instruct = unit_instruct
                    with measure.producer_substage("unit_synthesis", billing="local"):
                        with accounting.stage(f"layer3.synthesis.{job['targetLocale']}.{index:04d}", billing="local",
                                              executor_type="production_model", work_unit_id=work_unit + ".synthesis",
                                              depends_on=[admission_span, model_load_span] if model_load_span else [admission_span]) as audio_span:
                            wavs, rate = model(spoken_text or unit["text"], adapter["languageParameter"],
                                               adapter["speakerKey"], seed=seed + index)
                            if (batch_size != 1
                                    and model.last_generation_trigger_index == index):
                                unit_metrics["batchInvocationUnitIndices"] = (
                                    model.last_generation["unitIndices"])
                            # A partial belongs to this same intent and is safe to replace on resume.
                            write_pcm16(partial, wavs, int(rate))
                with measure.producer_substage("audio_validation", billing="local"):
                    with accounting.stage(f"layer3.validation.{job['targetLocale']}.{index:04d}", work_unit_id=work_unit + ".validation",
                                          depends_on=[audio_span] if audio_span else None) as validation_span:
                        try:
                            decoded = integrity.probe_full_decode(partial)
                        except Exception as error:
                            anomaly.preserve(root, job, index,
                                reason=f"full_decode_failed:{type(error).__name__}",
                                audio_relative_path=str(partial.relative_to(root)))
                            raise
                    measure.record_substage_metrics({"audioSeconds": decoded["durationSeconds"]})
                with accounting.stage(f"layer3.commit.{job['targetLocale']}.{index:04d}",
                                      work_unit_id=work_unit + ".commit", depends_on=[validation_span]) as commit_span:
                    commit = {"identity": render_identity, "audioSha256": identity.sha256(partial)}
                    if batch_size != 1 and unit_metrics["synthesized"]:
                        commit["generationBatch"] = model.last_generation
                    elif batch_size != 1 and unit_metrics["reusedPrior"]:
                        previous_commit = package.read_object(
                            reuse_from / f"receipts/unit-{index:04d}.render.json")
                        commit["generationBatch"] = previous_commit["generationBatch"]
                    write_json_atomic(commit_path, commit)
                    os.replace(partial, wav_path)
            with accounting.stage(f"layer3.receipt.{job['targetLocale']}.{index:04d}",
                                  work_unit_id=work_unit + ".receipt",
                                  depends_on=[admission_span if has_commit else commit_span]) as receipt_span:
                if receipt_path.exists():
                    integrity.validate_receipt(paths["job"], index, wav_path,
                                               package.read_object(receipt_path),
                                               validated_context=validated,
                                               **({"strict_rubric": context["strict_rubric"]}
                                                  if context.get("strict_rubric") is not None else {}))
                else:
                    receipt = integrity.build_receipt(paths["job"], index, wav_path,
                        validated_context=validated,
                        **({"strict_rubric": context["strict_rubric"]}
                           if context.get("strict_rubric") is not None else {}))
                    write_json_atomic(receipt_path, receipt)
                receipt = package.read_object(receipt_path)
                rows.append({"textGroupId": unit["translationGroupId"],
                             "targetTextSha256": expected["textSha256"],
                             "audio": artifact(root, wav_path),
                             "durationSeconds": receipt["durationSeconds"],
                             "receipt": artifact(root, receipt_path, json_artifact=True)})
            # Expose measured prefix risk while generation is still running.
            # The original eight-second target is retained even when assembly
            # later consumes a separately authorized publication exception.
            prefix_plan = schedule(context, rows, DEFAULT_POLICY)
            anomaly.preserve_timing_risk(root, context, rows, prefix_plan, indices=[len(rows) - 1])
            prefix_diagnostics = recovery.diagnose(context, rows, prefix_plan)
            prefix_diagnostics["coverageUnits"] = len(rows)
            prefix_diagnostics["totalUnits"] = len(job["units"])
            write_json_atomic(root / "early-unit-timing-diagnostics.json", prefix_diagnostics)
            unit_metrics["audioSeconds"] = receipt["durationSeconds"]
            accounting.record_workload(stage_name, unit_metrics)
        # Parent admission/validation/commits remain ordered. Replica compute
        # overlaps and is recorded separately in replica-runtime.json.
        previous_receipts = [receipt_span]
    if completion_spans is not None:
        completion_spans.extend(previous_receipts)
    require(len(rows) == len(job["units"]) and (batch_size == 1 or model is None
            or (not model.remaining and not model.outputs)), "TTS batch unit coverage is incomplete")
    if validated is not None:
        validated.check(full=True)
    return rows


def render_units(context, paths, root, checkpoint_map_path, **kwargs):
    """A single writer owns the artifact root, even on failure or cached replay."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".formal-render.lock").open("a") as lock, ExitStack() as resources:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Formal render root is already in use") from exc
        return _render_units(context, paths, root, checkpoint_map_path,
                             model_resources=resources, **kwargs)


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


def assemble_pcm16_track(plan: dict[str, Any], signals: list[bytes],
                         sample_rate: int, channels: int, clip_duration: float) -> bytes:
    """Place decoded PCM16 units on the 1x timeline without granting release status."""
    require(plan.get("status") == "pass"
            and len(plan.get("entries", [])) == len(signals)
            and type(sample_rate) is int and sample_rate > 0
            and type(channels) is int and channels > 0
            and isinstance(clip_duration, (int, float))
            and math.isfinite(clip_duration) and clip_duration > 0,
            "Invalid PCM16 assembly inputs")
    frame_bytes = channels * 2
    length = round(clip_duration * sample_rate)
    track = bytearray(length * frame_bytes)
    for entry, encoded in zip(plan["entries"], signals):
        require(bool(encoded) and len(encoded) % frame_bytes == 0,
                f"Invalid PCM16 unit: {entry['textGroupId']}")
        start = round(entry["plannedStart"] * sample_rate)
        require(start >= 0 and start + len(encoded) // frame_bytes <= length,
                f"Sample-exact unit exceeds clip length: {entry['textGroupId']}")
        offset = start * frame_bytes
        track[offset:offset + len(encoded)] = encoded
    return bytes(track)


def assemble(context: dict[str, Any], paths: dict[str, Path], root: Path,
             rows: list[dict[str, Any]], *, policy: dict[str, float] | None = None,
             track_format: str = "wav", predecessor_spans: tuple[str, ...] = (),
             completion_spans: list[str] | None = None) -> dict[str, Any]:
    existing = None
    locale = context["job"]["targetLocale"]
    dependencies = accounting.bounded_dependencies(
        "layer3.assembly_join", predecessor_spans, work_unit_id=f"l3.{locale}.assembly_join")
    with accounting.stage("layer3.assembly_admission", depends_on=dependencies,
                          cache_hit=(root / "render-manifest.json").is_file(),
                          work_unit_id=f"l3.{locale}.assembly_admission") as admission_span:
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
            accounting.record_workload("layer3.cached_manifest", {
                "renderManifestSha256": identity.sha256(manifest_path),
                "jobSha256": identity.json_sha256(context["job"]),
                "checkpointSha256": context["adapter"]["conditioningSha256"],
                "cacheHit": True})
    if existing is not None:
        if completion_spans is not None:
            completion_spans.append(admission_span)
        return existing
    with measure.producer_substage("schedule_sync", billing="local"):
        with accounting.stage("layer3.schedule", depends_on=[admission_span],
                              work_unit_id=f"l3.{locale}.schedule") as schedule_span:
            plan = schedule(context, rows, policy)
            anomaly.preserve_timing_risk(root, context, rows, plan)
            write_json_atomic(root / "unit-timing-diagnostics.json", recovery.diagnose(context, rows, plan))
        measure.record_substage_metrics({
            "overLimitUnits": len(plan["issues"]),
            "clipDurationSeconds": context["clip_timeline_map"]["clipDurationSeconds"],
            "plannedDurationSeconds": plan["entries"][-1]["plannedEnd"] if plan["entries"] else 0,
        })
        if plan["status"] != "pass":
            with accounting.stage("layer3.schedule_rejection", depends_on=[schedule_span],
                                  work_unit_id=f"l3.{locale}.schedule_rejection"):
                write_json_atomic(root / "render-diagnostics.json", {
                    "schemaVersion": "sermon-formal-render-diagnostics-v1", "status": "schedule_overflow",
                    "jobJsonSha256": identity.json_sha256(context["job"]),
                    "targetLocale": locale, "schedule": plan})
                raise ValueError(f"Measured target audio exceeds 1x clip schedule: {plan['issues'][0]}")
    with accounting.stage("layer3.track_assembly", depends_on=[schedule_span],
                          work_unit_id=f"l3.{locale}.track_assembly") as track_span:
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
        track = assemble_pcm16_track(plan, waves, sample_rate, channels, clip_duration)
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
                "-c:a", "libmp3lame", "-b:a", "64k", "-write_xing", "1",
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
    with accounting.stage("layer3.manifest_commit", depends_on=[track_span],
                          work_unit_id=f"l3.{locale}.manifest_commit") as manifest_span:
        captions = {"cues": [{"textGroupId": group["translationGroupId"],
                             "text": group["targetText"],
                             "start": entry["plannedStart"], "end": entry["plannedEnd"]}
                            for group, entry in zip(context["candidate"]["groups"], plan["entries"])]}
        for path, value in ((schedule_path, plan), (captions_path, captions)):
            if path.exists():
                require(package.read_object(path) == value, f"Existing artifact differs: {path}")
            else:
                write_json_atomic(path, value)
        authorization = context.get("source_voice_authorization") or context["clip_voice_authorization"]
        attestation_path = Path(authorization["userRightsAttestation"]["path"])
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
    if completion_spans is not None:
        completion_spans.append(manifest_span)
    return manifest


def _render(paths: dict[str, Path], checkpoint_map_path: Path,
           operation_policies_path: Path, *, path_map_path: Path | None = None,
           reuse_from: Path | None = None,
           speculative_from: Path | None = None,
           quarantine_units: tuple[int, ...] = (), quarantine_reason: str | None = None,
           assembly_only: bool = False, max_synthesis_units: int | None = None,
           expected_dependency_hashes: dict[str, str] | None = None,
           seed: int = 42, batch_size: int = 1, replicas: int = 1,
           device: str = "cuda:0", dtype: str = "bfloat16",
           attention: str | None = "sdpa", instruct: str | None = None,
           unit_instructions_path: Path | None = None,
           policy: dict[str, float] | None = None, track_format: str = "wav",
           synth_factory: Callable[..., Any] = QwenSynthesizer,
           progress_ledger: Path | None = None,
           strict_rubric: dict[str, Any] | None = None,
           model_resources: ExitStack) -> dict[str, Any]:
    dependencies = []
    if path_map_path is not None:
        with accounting.stage("layer3.materialize_inputs", depends_on=[],
                              work_unit_id="l3.materialize_inputs") as materialize_span:
            materialize_path_map(paths["job"], path_map_path)
        dependencies = [materialize_span]
    with accounting.stage("layer3.validate_inputs", depends_on=dependencies,
                          work_unit_id="l3.validate_inputs") as validation_span:
        model_directories = checkpoint_directories(paths["job"], checkpoint_map_path, assembly_only=assembly_only)
        receipt_context = integrity.ValidatedJobContext(paths["job"], strict_rubric=strict_rubric,
            extra_directories=model_directories,
            extra_paths=[*paths.values(), checkpoint_map_path, operation_policies_path,
                         *([unit_instructions_path] if unit_instructions_path is not None else [])])
        if expected_dependency_hashes is not None:
            current = {str(path): digest for path, (_, digest) in receipt_context.files.items()}
            require(set(current) <= set(expected_dependency_hashes)
                    and all(expected_dependency_hashes[path] == digest for path, digest in current.items()),
                    "Frozen adapter dependency closure changed before renderer admission")
            require(all(Path(path).is_file() and identity.sha256(Path(path)) == digest
                        for path, digest in expected_dependency_hashes.items()),
                    "Frozen adapter dependency changed before renderer admission")
        context = checked_context(paths, checkpoint_map_path, operation_policies_path,
            assembly_only=assembly_only,
            **({"strict_rubric": strict_rubric} if strict_rubric is not None else {}))
        require(assembly_only or context["checkpoint"].resolve() in {p.resolve() for p in model_directories},
                "Validated checkpoint differs from frozen model directory")
        receipt_context.check()
        context["receiptContext"] = receipt_context
        instructions_by_group = unit_instructions(context["job"], unit_instructions_path)
        root = paths["job"].parent.resolve()
        require(not (assembly_only and quarantine_units), "Quarantine repair cannot use assembly-only")
        require(len(set(quarantine_units)) == len(quarantine_units), "Duplicate quarantine units")
        require(not quarantine_units or (isinstance(quarantine_reason, str) and quarantine_reason.strip()),
                "Quarantine requires an explicit reason")
        for index in quarantine_units:
            recovery.quarantine_unit(root, context["job"], index, reason=quarantine_reason or "")
    completed_units = []
    with accounting.stage("layer3.render_units"), ExitStack() as synthesis_resources:
        rows = _render_units(context, paths, root, checkpoint_map_path, seed=seed,
                            model_resources=synthesis_resources, assembly_only=assembly_only,
                            max_synthesis_units=max_synthesis_units,
                            device=device, dtype=dtype, attention=attention, instruct=instruct,
                            instructions_by_group=instructions_by_group,
                            reuse_from=reuse_from,
                            speculative_from=speculative_from,
                            batch_size=batch_size, replicas=replicas,
                            synth_factory=synth_factory, predecessor_spans=(validation_span,),
                            completion_spans=completed_units)
    with accounting.stage("layer3.assemble"):
        return assemble(context, paths, root, rows, policy=policy, track_format=track_format,
                        predecessor_spans=tuple(completed_units))


def render(paths, checkpoint_map_path, operation_policies_path, **kwargs):
    root = paths["job"].parent.resolve()
    with (root / ".formal-render.lock").open("a") as lock, ExitStack() as resources:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Formal render root is already in use") from exc
        return _render(paths, checkpoint_map_path, operation_policies_path,
                       model_resources=resources, **kwargs)


def render_accounted(paths: dict[str, Path], checkpoint_map_path: Path,
                     operation_policies_path: Path, *, progress_ledger: Path | None = None,
                     **kwargs: Any) -> dict[str, Any]:
    locale = package.read_object(paths["job"])["targetLocale"]
    with measure.producer_step(progress_ledger, f"L3-02@{locale}", locale=locale) as metrics:
        metrics["speechUnits"] = len(package.read_object(paths["job"]).get("units") or [])
        with accounting.accounting_session(paths["job"].parent / "accounting",
                                           "layer3_formal_render",
                                           evidence_directory=paths["job"].parent):
            result = render(paths, checkpoint_map_path, operation_policies_path, **kwargs)
        metrics["doneUnits"] = len(result["units"])
    return result


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "anchor", "candidate", "job", "adapter", "policy"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--strict-rubric", type=Path, help="Explicit frozen rubric for strict-v3 policy validation")
    parser.add_argument("--human-review-receipt", dest="human_receipt", type=Path, required=True)
    parser.add_argument("--speaker-registry", dest="registry", type=Path, required=True)
    authorization = parser.add_mutually_exclusive_group(required=True)
    authorization.add_argument("--clip-voice-authorization", dest="clip_voice_authorization", type=Path)
    authorization.add_argument("--source-voice-authorization", dest="source_voice_authorization", type=Path)
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
    parser.add_argument("--batch-size", type=int, choices=BATCH_SIZES, default=None,
                        help="Production default1; Dev profile default2. Use a new render root when changing it")
    parser.add_argument("--spark-production", action="store_true",
                        help="New single-speaker Spark jobs: 8 resident replicas x batch8")
    parser.add_argument("--replicas", type=int, choices=(1, 8), default=None,
                        help="Default1 for existing jobs; Spark production uses8")
    dev_profile.add_arguments(parser)
    parser.add_argument("--instruct", help="Frozen natural delivery instruction; never edits approved text")
    parser.add_argument("--unit-instructions", type=Path,
                        help="Source-bound per-unit pronunciation and pause instructions")
    parser.add_argument("--reaction-lag-seconds", type=float, default=0.05)
    parser.add_argument("--inter-utterance-gap-seconds", type=float, default=0.05)
    parser.add_argument("--max-end-lag-seconds", type=float, default=8.0)
    parser.add_argument("--track-format", choices=("wav", "mp3"), default="wav",
                        help="Use reviewed 64 kbps mono MP3 for a full-length web release")
    parser.add_argument("--max-synthesis-units", type=int,
                        help="Bound generated units including full-window batch replay")
    parser.add_argument("--quarantine-unit", type=int, action="append", default=[],
                        help="Preserve anomalous WAV/receipts before explicit unit repair")
    parser.add_argument("--quarantine-reason")
    parser.add_argument("--assembly-only", action="store_true",
                        help="Require complete committed cache; never initialize a synthesizer")
    parser.add_argument("--reuse-from", type=Path,
                        help="Previously validated render directory for unchanged units")
    parser.add_argument("--speculative-from", type=Path,
                        help="Preview-only unit audio; formal human and rights gates still run first")
    parser.add_argument("--progress-ledger", type=Path,
                        help="Bind render and per-unit timing to this week's four-layer ledger")
    args = parser.parse_args(argv)
    if args.spark_production:
        require(not args.dev_test and args.dev_test_profile is None,
                "Spark production cannot use a Dev test profile")
        require(args.batch_size in (None, 8) and args.replicas in (None, 8),
                "Spark production requires replicas8 and batch8")
        args.batch_size, args.replicas = 8, 8
    else:
        args.replicas = 1 if args.replicas is None else args.replicas
    require(not args.dev_test or args.replicas == 1,
            "Dev test profile does not admit replica production")
    dev_settings = dev_profile.resolve("tts", enabled=args.dev_test,
        profile_path=args.dev_test_profile, batch_size=args.batch_size)
    args.batch_size = dev_settings["batchSize"]
    dev_receipt_path = args.job.parent / f"dev-test-tts-b{args.batch_size}.json"
    if dev_settings["profile"] is not None:
        dev_receipts.check_destination(dev_receipt_path, dev_settings)
    paths = {name: getattr(args, name) for name in ("source", "anchor", "candidate",
                                                   "job", "adapter", "policy", "human_receipt",
                                                   "registry",
                                                   "clip_timeline_map")}
    if args.clip_voice_authorization:
        paths["clip_voice_authorization"] = args.clip_voice_authorization
    if args.source_voice_authorization:
        paths["source_voice_authorization"] = args.source_voice_authorization
    if args.clip_voice_capability:
        paths["clip_voice_capability"] = args.clip_voice_capability
    policy = {"reactionLagSeconds": args.reaction_lag_seconds,
              "interUtteranceGapSeconds": args.inter_utterance_gap_seconds,
              "maxEndLagSeconds": args.max_end_lag_seconds}
    result = render_accounted(
        paths, args.checkpoint_map, args.audio_operation_policies,
        progress_ledger=args.progress_ledger,
        path_map_path=args.path_map, reuse_from=args.reuse_from,
        speculative_from=args.speculative_from,
        quarantine_units=tuple(args.quarantine_unit), quarantine_reason=args.quarantine_reason,
        assembly_only=args.assembly_only, max_synthesis_units=args.max_synthesis_units, seed=args.seed, batch_size=args.batch_size, replicas=args.replicas, device=args.device,
        dtype=args.dtype, attention=args.attention, instruct=args.instruct,
        unit_instructions_path=args.unit_instructions,
        policy=policy, track_format=args.track_format,
        strict_rubric=package.read_object(args.strict_rubric) if args.strict_rubric else None)
    if dev_settings["profile"] is not None:
        dev_receipts.write(dev_settings, paths["job"].parent / "render-manifest.json", dev_receipt_path)
    print(json.dumps({"status": "candidate", "targetLocale": result["targetLocale"],
                      "renderManifest": str((paths["job"].parent / "render-manifest.json").resolve()),
                      "machineScreening": "not_run", "humanListeningReview": "pending",
                      **({"devTestConsumptionReceipt": str(dev_receipt_path.resolve())}
                         if dev_settings["profile"] is not None else {})},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
