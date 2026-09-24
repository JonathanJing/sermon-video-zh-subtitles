#!/usr/bin/env python3
"""Pre-render machine-reviewed target text while human translation review is pending.

This is a preview/cache lane outside canonical Layer 3. It creates no speech job,
audio package, synchronized track, human approval, or release eligibility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

try:
    from scripts import prepare_target_language_speech_job as speech
    from scripts import render_formal_target_language_speech as formal
    from scripts import render_multilingual_voice_demos as demos
    from scripts import sermon_sentence_interpretation as identity
    from scripts import validate_target_language_audio_unit as integrity
except ImportError:
    import prepare_target_language_speech_job as speech
    import render_formal_target_language_speech as formal
    import render_multilingual_voice_demos as demos
    import sermon_sentence_interpretation as identity
    import validate_target_language_audio_unit as integrity


MANIFEST_VERSION = "sermon-speculative-target-speech-v1"
UNIT_VERSION = "sermon-speculative-target-speech-unit-v1"


def checked_context(paths: dict[str, Path], checkpoint_map_path: Path,
                    operation_policies_path: Path) -> dict[str, Any]:
    required = ("source", "anchor", "candidate", "policy", "adapter", "registry")
    formal.require(all(name in paths and paths[name].is_file() for name in required),
                   "Missing speculative speech input")
    data = {name: formal.package.read_object(paths[name]) for name in required}
    source, anchor, candidate = data["source"], data["anchor"], data["candidate"]
    speech._validate_schema(candidate, "sermon-target-language-candidate-v2.schema.json",
                            "target candidate")
    speech.validate_target_candidate(source, anchor, candidate,
                                     require_human_approval=False)
    formal.require(candidate["status"] == "machine_review_pass_human_review_pending"
                   and candidate["humanReview"]["translation"] == "pending",
                   "Speculative speech requires machine-pass, human-pending translation")
    speech.validate_policy_binding(candidate, data["policy"])
    adapter, registry = data["adapter"], data["registry"]
    speech.validate_adapter(adapter, candidate["targetLocale"], registry,
                            source_package=source, candidate=candidate)
    formal.require(adapter["adapterId"] == "qwen3_tts_sft"
                   and adapter["authorizationPurpose"] in
                   {"multilingual_voice_demo", "chinese_dubbing"},
                   "Speculative speech requires a registered demo/Chinese voice purpose")
    policies = formal.package.read_object(operation_policies_path)
    formal.require(all(isinstance(policies.get(name), dict)
                       and identity.json_sha256(policies[name]) == adapter[field]
                       for name, field in (("normalization", "normalizationPolicySha256"),
                                           ("asrScreening", "asrScreeningPolicySha256"),
                                           ("subtitle", "subtitlePolicySha256"))),
                   "Speculative speech operation policy differs from adapter")
    formal.require(policies["normalization"].get("policy")
                   == "exact_human_approved_target_text_no_rewrite",
                   "Speculative speech may not rewrite target text")
    mapping = demos.read_object(checkpoint_map_path, "checkpoint map")
    formal.require(mapping.get("schemaVersion") == "sermon-speaker-checkpoint-map-v1",
                   "Unsupported checkpoint map")
    speakers = [row for row in registry["speakers"]
                if row["speakerId"] == adapter["speakerId"]]
    entries = [row for row in mapping.get("checkpoints", [])
               if row.get("speakerId") == adapter["speakerId"]]
    formal.require(len(speakers) == len(entries) == 1
                   and entries[0].get("checkpointRef") == adapter["conditioningRef"]
                   == speakers[0]["checkpoint"]["checkpointRef"],
                   "Speculative checkpoint mapping differs from registry")
    checkpoint = demos.validate_checkpoint({
        "checkpointPath": entries[0].get("path"),
        "checkpointSha256": adapter["conditioningSha256"],
        "speakerKey": adapter["speakerKey"], "speakerId": adapter["speakerId"],
    })
    data["checkpoint"] = checkpoint
    data["checkpointMapFileSha256"] = identity.sha256(checkpoint_map_path)
    data["operationPoliciesFileSha256"] = identity.sha256(operation_policies_path)
    return data


def sound_identity(context: dict[str, Any], index: int, *, seed: int,
                   dtype: str, attention: str | None,
                   instruct: str | None) -> dict[str, Any]:
    adapter, candidate = context["adapter"], context["candidate"]
    group = candidate["groups"][index]
    all_fields = {
        "unitIndex": index,
        "sourceJsonSha256": identity.json_sha256(context["source"]),
        "anchorJsonSha256": identity.json_sha256(context["anchor"]),
        "translationPolicySha256": candidate["translationPolicySha256"],
        "adapterId": adapter["adapterId"], "model": adapter["model"],
        "modelRevision": adapter["modelRevision"],
        "conditioningRef": adapter["conditioningRef"],
        "checkpointMapFileSha256": context["checkpointMapFileSha256"],
        "operationPoliciesFileSha256": context["operationPoliciesFileSha256"],
        "checkpointSha256": adapter["conditioningSha256"],
        "speakerId": adapter["speakerId"], "speakerKey": adapter["speakerKey"],
        "targetLocale": candidate["targetLocale"],
        "languageParameter": adapter["languageParameter"],
        "groupId": group["translationGroupId"],
        "sourceUnitIds": group["sourceUnitIds"],
        "textSha256": hashlib.sha256(group["targetText"].encode()).hexdigest(),
        "rendererSha256": identity.sha256(Path(formal.__file__)),
        "seed": seed, "temperature": 0.7, "repetitionPenalty": 1.05,
        "maxNewTokens": 768, "dtype": dtype, "attention": attention,
        "deliveryInstruction": instruct, "ratePolicy": "natural_no_time_stretch",
    }
    return {key: all_fields[key] for key in formal.SPECULATIVE_MATCH_FIELDS}


def render(paths: dict[str, Path], checkpoint_map_path: Path,
           operation_policies_path: Path, out: Path, *,
           group_ids: list[str] | None = None, seed: int = 42,
           device: str = "cuda:0", dtype: str = "bfloat16",
           attention: str | None = "sdpa", instruct: str | None = None,
           synth_factory: Callable[..., Any] = formal.QwenSynthesizer) -> dict[str, Any]:
    context = checked_context(paths, checkpoint_map_path, operation_policies_path)
    candidate = context["candidate"]
    groups = candidate["groups"]
    available = {group["translationGroupId"] for group in groups}
    selected = set(group_ids) if group_ids is not None else available
    formal.require(bool(selected) and selected <= available
                   and (group_ids is None or len(group_ids) == len(selected)),
                   "Unknown, empty, or duplicate speculative group selection")
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    snapshot_path = out / "candidate.json"
    evidence_snapshots = {name: out / f"{name}.json" for name in
                          ("source", "anchor", "policy", "adapter", "registry")}
    manifest = {
        "schemaVersion": MANIFEST_VERSION, "status": "preview_only",
        "synthesisEligible": False, "releaseEligible": False,
        "targetLocale": candidate["targetLocale"],
        "candidateJsonSha256": identity.json_sha256(candidate),
        "sourceJsonSha256": identity.json_sha256(context["source"]),
        "anchorJsonSha256": identity.json_sha256(context["anchor"]),
        "translationPolicySha256": candidate["translationPolicySha256"],
    }
    if manifest_path.exists():
        formal.require(formal.package.read_object(manifest_path) == manifest
                       and snapshot_path.is_file()
                       and identity.json_sha256(formal.package.read_object(snapshot_path))
                       == manifest["candidateJsonSha256"]
                       and all(path.is_file()
                               and formal.package.read_object(path) == context[name]
                               for name, path in evidence_snapshots.items()),
                       "Existing speculative output belongs to another candidate")
    else:
        formal.require(not snapshot_path.exists() and not (out / "units").exists()
                       and not (out / "receipts").exists()
                       and not any(path.exists() for path in evidence_snapshots.values()),
                       "Uncommitted speculative output cannot be adopted")
        formal.write_json_atomic(snapshot_path, candidate)
        for name, path in evidence_snapshots.items():
            formal.write_json_atomic(path, context[name])
        formal.write_json_atomic(manifest_path, manifest)
    model = None
    rendered = []
    for index, group in enumerate(groups):
        if group["translationGroupId"] not in selected:
            continue
        expected = sound_identity(context, index, seed=seed, dtype=dtype,
                                  attention=attention, instruct=instruct)
        wav_path = out / f"units/unit-{index:04d}.wav"
        receipt_path = out / f"receipts/unit-{index:04d}.json"
        partial = wav_path.with_suffix(".partial.wav")
        if wav_path.exists() or receipt_path.exists():
            formal.require(receipt_path.is_file(),
                           "Uncommitted speculative unit cannot be reused")
            receipt = formal.package.read_object(receipt_path)
            formal.require(receipt.get("schemaVersion") == UNIT_VERSION
                           and receipt.get("status") == "preview_only"
                           and receipt.get("candidateJsonSha256")
                           == manifest["candidateJsonSha256"]
                           and receipt.get("soundIdentity") == expected,
                           "Speculative unit identity changed")
            if not wav_path.exists():
                formal.require(partial.is_file()
                               and receipt.get("audioSha256") == identity.sha256(partial),
                               "Committed speculative partial audio is missing or changed")
                integrity.probe_full_decode(partial)
                os.replace(partial, wav_path)
            formal.require(not partial.exists()
                           and receipt.get("audioSha256") == identity.sha256(wav_path),
                           "Speculative unit identity or audio changed")
            integrity.probe_full_decode(wav_path)
        else:
            wav_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            formal.require(not partial.exists(), "Uncommitted speculative audio exists")
            if model is None:
                model = synth_factory(context["checkpoint"], device=device, dtype=dtype,
                                      attention=attention, instruct=instruct)
            samples, rate = model(group["targetText"],
                                  context["adapter"]["languageParameter"],
                                  context["adapter"]["speakerKey"], seed=seed + index)
            formal.write_pcm16(partial, samples, int(rate))
            decoded = integrity.probe_full_decode(partial)
            receipt = {
                "schemaVersion": UNIT_VERSION, "status": "preview_only",
                "candidateJsonSha256": manifest["candidateJsonSha256"],
                "soundIdentity": expected, "audioSha256": identity.sha256(partial),
                "durationSeconds": decoded["durationSeconds"], "fullDecode": "pass",
            }
            formal.write_json_atomic(receipt_path, receipt)
            os.replace(partial, wav_path)
        rendered.append(group["translationGroupId"])
    return {"status": "preview_only", "targetLocale": candidate["targetLocale"],
            "renderedGroupIds": rendered, "out": str(out)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "anchor", "candidate", "policy", "adapter", "registry"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--checkpoint-map", type=Path, required=True)
    parser.add_argument("--audio-operation-policies", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--group-id", action="append", dest="group_ids")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", choices=("bfloat16", "float32"), default="bfloat16")
    parser.add_argument("--attention", default="sdpa")
    parser.add_argument("--instruct")
    args = parser.parse_args()
    paths = {name: getattr(args, name) for name in
             ("source", "anchor", "candidate", "policy", "adapter", "registry")}
    print(json.dumps(render(paths, args.checkpoint_map,
                            args.audio_operation_policies, args.out,
                            group_ids=args.group_ids, seed=args.seed,
                            device=args.device, dtype=args.dtype,
                            attention=args.attention, instruct=args.instruct),
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
