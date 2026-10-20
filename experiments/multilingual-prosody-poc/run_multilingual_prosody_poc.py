#!/usr/bin/env python3
"""Prepare, render, and assemble a minimal same-model Layer 3 prosody POC.

The first pass preserves source-unit boundaries and audible inter-unit pauses.
It deliberately does not claim word-level emphasis transfer or duration-controlled
TTS. Generated speech remains natural-rate and is measured after synthesis.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
from pathlib import Path
import wave
from typing import Any


PLAN_SCHEMA = "sermon-target-language-prosody-poc-plan-v1"


def canonical_sha(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(anchor_path: Path, candidate_path: Path, out: Path) -> dict[str, Any]:
    if out.exists():
        raise ValueError(f"POC plan already exists: {out}")
    anchor = read_object(anchor_path)
    candidate = read_object(candidate_path)
    if anchor.get("schemaVersion") != "sermon-sentence-anchor-manifest-v2":
        raise ValueError("Prosody POC requires clause-stable Layer 1 anchors")
    if candidate.get("schemaVersion") != "sermon-target-language-candidate-v2":
        raise ValueError("Prosody POC requires a Layer 2 target-language candidate")
    if candidate.get("anchorManifestSha256") != canonical_sha(anchor):
        raise ValueError("Layer 2 candidate belongs to another anchor manifest")

    source_units = anchor.get("sourceUnits")
    if not isinstance(source_units, list) or not source_units:
        raise ValueError("Anchor manifest has no source units")
    source_by_id = {unit.get("sourceUnitId"): unit for unit in source_units}
    source_order = {unit.get("sourceUnitId"): index for index, unit in enumerate(source_units)}
    pairs: list[tuple[str, str]] = []
    for group in candidate.get("groups", []):
        source_ids = group.get("sourceUnitIds")
        utterances = group.get("targetUtterances")
        coverage = group.get("coverage")
        if not (isinstance(source_ids, list) and isinstance(utterances, list)
                and isinstance(coverage, list) and len(source_ids) == len(utterances) == len(coverage)):
            raise ValueError("Every target utterance must map one-to-one to a source unit")
        if [item.get("sourceUnitId") for item in coverage] != source_ids:
            raise ValueError("Layer 2 coverage differs from source-unit order")
        for source_id, utterance, item in zip(source_ids, utterances, coverage):
            text = str(utterance).strip()
            if source_id not in source_by_id or not text or item.get("targetText") != text:
                raise ValueError(f"Invalid source/target unit mapping: {source_id}")
            pairs.append((source_id, text))
    if not pairs or len({source_id for source_id, _ in pairs}) != len(pairs):
        raise ValueError("Prosody POC needs unique mapped source units")
    indexes = [source_order[source_id] for source_id, _ in pairs]
    if indexes != sorted(indexes):
        raise ValueError("Mapped source units are not in timeline order")

    first_start = float(source_by_id[pairs[0][0]]["start"])
    last_end = float(source_by_id[pairs[-1][0]]["end"])
    units = []
    for index, (source_id, text) in enumerate(pairs):
        source = source_by_id[source_id]
        start, end = float(source["start"]), float(source["end"])
        source_pause = float(source.get("boundary", {}).get("pauseAfterSeconds", 0))
        units.append({
            "unitIndex": index,
            "sourceUnitId": source_id,
            "sourceStartSeconds": start,
            "sourceEndSeconds": end,
            "sourceSpeechDurationSeconds": round(end - start, 6),
            "sourcePauseAfterSeconds": source_pause,
            "assemblyPauseAfterSeconds": 0.0 if index == len(pairs) - 1 else source_pause,
            "targetText": text,
            "targetTextSha256": hashlib.sha256(text.encode()).hexdigest(),
            "targetDurationBudgetSeconds": round(end - start, 6),
            "outputRelativePath": f"units/unit-{index:04d}.wav",
        })
    plan = {
        "schemaVersion": PLAN_SCHEMA,
        "scope": "layer_3_unit_pacing_and_pause_shadow_poc",
        "status": "prepared_current_model_render_pending",
        "productionEligible": False,
        "humanApproval": False,
        "targetLocale": candidate["targetLocale"],
        "anchorManifestJsonSha256": canonical_sha(anchor),
        "targetLanguageCandidateJsonSha256": canonical_sha(candidate),
        "sourceWindow": {
            "startSeconds": first_start,
            "endSeconds": last_end,
            "durationSeconds": round(last_end - first_start, 6),
        },
        "renderContract": {
            "adapterPolicy": "reuse_registered_qwen3_tts_sft_checkpoint",
            "generationMode": "one_call_per_source_unit",
            "candidateCount": 1,
            "ratePolicy": "natural_no_time_stretch",
            "pacePolicy": "measure_against_source_unit_after_generation",
            "pausePolicy": "deterministic_copy_of_layer1_inter_unit_pauses",
            "emphasisPolicy": "out_of_scope_for_minimal_poc",
        },
        "acceptanceTargets": {
            "unitEndAbsoluteErrorSeconds": 0.4,
            "fullDecodeRequired": True,
            "semanticScreeningRequired": True,
            "humanListeningRequired": True,
        },
        "units": units,
        "limitations": [
            "no_word_level_emphasis_transfer",
            "no_duration_conditioned_tts",
            "no_time_stretch",
            "machine_reviewed_translation_human_review_pending",
        ],
    }
    write_json(out, plan)
    return plan


def render(plan_path: Path, checkpoint: Path, expected_checkpoint_sha256: str,
           speaker_key: str, model_language: str, out: Path, *, device: str,
           dtype_name: str, attention: str | None, seed: int) -> dict[str, Any]:
    if out.exists():
        raise ValueError(f"Render directory already exists: {out}")
    plan = read_object(plan_path)
    if plan.get("schemaVersion") != PLAN_SCHEMA:
        raise ValueError("Unsupported prosody POC plan")
    weights = checkpoint / "model.safetensors"
    config_path = checkpoint / "config.json"
    if not weights.is_file() or not config_path.is_file():
        raise ValueError("Qwen speaker checkpoint is incomplete")
    if file_sha(weights) != expected_checkpoint_sha256:
        raise ValueError("Qwen speaker checkpoint hash differs from the registered identity")
    config = read_object(config_path)
    if speaker_key not in config.get("talker_config", {}).get("spk_id", {}):
        raise ValueError(f"Speaker key is absent from checkpoint: {speaker_key}")

    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    out.mkdir(parents=True)
    dtype = torch.bfloat16 if dtype_name == "bfloat16" else torch.float32
    model_args: dict[str, Any] = {"device_map": device, "dtype": dtype}
    if attention:
        model_args["attn_implementation"] = attention
    model = Qwen3TTSModel.from_pretrained(str(checkpoint), **model_args)
    tracks = []
    try:
        for unit in plan["units"]:
            destination = out / unit["outputRelativePath"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            torch.manual_seed(seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(seed)
            generation_args: dict[str, Any] = {
                "text": unit["targetText"],
                "language": model_language,
                "speaker": speaker_key,
                "temperature": 0.7,
                "repetition_penalty": 1.05,
                "max_new_tokens": 768,
            }
            if unit.get("instruct"):
                generation_args["instruct"] = unit["instruct"]
            wavs, sample_rate = model.generate_custom_voice(**generation_args)
            samples = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
            duration = len(samples) / sample_rate
            if not np.isfinite(samples).all() or not 0.2 < duration < 45:
                raise ValueError(f"Suspicious unit audio: {unit['sourceUnitId']}")
            sf.write(destination, samples, sample_rate, subtype="PCM_24")
            tracks.append({
                "unitIndex": unit["unitIndex"],
                "sourceUnitId": unit["sourceUnitId"],
                "file": unit["outputRelativePath"],
                "sha256": file_sha(destination),
                "durationSeconds": round(duration, 6),
                "sampleRate": sample_rate,
                "instructSha256": (hashlib.sha256(unit["instruct"].encode()).hexdigest()
                                   if unit.get("instruct") else None),
            })
    finally:
        del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    manifest = {
        "schemaVersion": "sermon-target-language-prosody-poc-render-v1",
        "status": "rendered_current_qwen_model_human_review_pending",
        "productionEligible": False,
        "planJsonSha256": canonical_sha(plan),
        "checkpointSha256": expected_checkpoint_sha256,
        "speakerKey": speaker_key,
        "modelLanguage": model_language,
        "seed": seed,
        "ratePolicy": "natural_no_time_stretch",
        "instructPolicy": "optional_unit_instruction_bound_by_hash",
        "tracks": tracks,
    }
    write_json(out / "render-manifest.json", manifest)
    return manifest


def tune(plan_path: Path, schedule_path: Path, out: Path, *, threshold: float = 0.4) -> dict[str, Any]:
    if out.exists():
        raise ValueError(f"Tuned POC plan already exists: {out}")
    plan = read_object(plan_path)
    schedule = read_object(schedule_path)
    if plan.get("schemaVersion") != PLAN_SCHEMA:
        raise ValueError("Unsupported prosody POC plan")
    if schedule.get("schemaVersion") != "sermon-target-language-prosody-poc-schedule-v1":
        raise ValueError("Unsupported baseline prosody schedule")
    rows = {row["sourceUnitId"]: row for row in schedule.get("units", [])}
    if set(rows) != {unit["sourceUnitId"] for unit in plan["units"]}:
        raise ValueError("Baseline schedule coverage differs from the POC plan")
    tuned = json.loads(json.dumps(plan))
    tuned["status"] = "prepared_same_model_pace_instruction_render_pending"
    tuned["baselineScheduleJsonSha256"] = canonical_sha(schedule)
    tuned["renderContract"]["pacePolicy"] = "same_model_duration_feedback_instruction_v1"
    for unit in tuned["units"]:
        delta = float(rows[unit["sourceUnitId"]]["speechDurationDeltaSeconds"])
        unit["baselineSpeechDurationDeltaSeconds"] = delta
        if delta > threshold:
            unit["instruct"] = "Speak slightly faster while remaining clear and natural."
        elif delta < -threshold:
            unit["instruct"] = "Speak more slowly and deliberately while remaining natural."
    tuned["limitations"] = list(dict.fromkeys(tuned["limitations"] + [
        "same_model_pace_instruction_is_not_duration_control",
    ]))
    write_json(out, tuned)
    return tuned


def assemble(plan_path: Path, unit_dir: Path, out: Path) -> dict[str, Any]:
    if out.exists():
        raise ValueError(f"Assembly directory already exists: {out}")
    plan = read_object(plan_path)
    if plan.get("schemaVersion") != PLAN_SCHEMA:
        raise ValueError("Unsupported prosody POC plan")
    out.mkdir(parents=True)
    track_path = out / "audio.wav"
    schedule_rows = []
    cursor_frames = 0
    audio_format: tuple[int, int, int, str, str] | None = None
    source_origin = float(plan["sourceWindow"]["startSeconds"])
    with wave.open(str(track_path), "wb") as writer:
        for unit in plan["units"]:
            source = unit_dir / unit["outputRelativePath"]
            with wave.open(str(source), "rb") as reader:
                current_format = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(),
                                  reader.getcomptype(), reader.getcompname())
                if current_format[0] != 1 or current_format[3] != "NONE":
                    raise ValueError(f"Unit WAV must be mono PCM: {source}")
                if audio_format is None:
                    audio_format = current_format
                    writer.setparams((current_format[0], current_format[1], current_format[2],
                                      0, current_format[3], current_format[4]))
                elif current_format != audio_format:
                    raise ValueError("Unit WAV formats differ")
                frames = reader.readframes(reader.getnframes())
                speech_frames = reader.getnframes()
            assert audio_format is not None
            sample_rate, sample_width = audio_format[2], audio_format[1]
            start = cursor_frames / sample_rate
            writer.writeframes(frames)
            cursor_frames += speech_frames
            speech_end = cursor_frames / sample_rate
            pause_frames = round(float(unit["assemblyPauseAfterSeconds"]) * sample_rate)
            writer.writeframes(b"\x00" * pause_frames * sample_width)
            cursor_frames += pause_frames
            expected_end = float(unit["sourceEndSeconds"]) - source_origin
            schedule_rows.append({
                "unitIndex": unit["unitIndex"],
                "sourceUnitId": unit["sourceUnitId"],
                "startSeconds": round(start, 6),
                "speechEndSeconds": round(speech_end, 6),
                "endSeconds": round(cursor_frames / sample_rate, 6),
                "actualSpeechDurationSeconds": round(speech_frames / sample_rate, 6),
                "sourceSpeechDurationSeconds": unit["sourceSpeechDurationSeconds"],
                "speechDurationDeltaSeconds": round(speech_frames / sample_rate - float(unit["sourceSpeechDurationSeconds"]), 6),
                "sourceExpectedSpeechEndSeconds": round(expected_end, 6),
                "speechEndLagSeconds": round(speech_end - expected_end, 6),
                "insertedPauseSeconds": round(pause_frames / sample_rate, 6),
                "text": unit["targetText"],
            })
    with wave.open(str(track_path), "rb") as decoded:
        expected_bytes = decoded.getnframes() * decoded.getnchannels() * decoded.getsampwidth()
        decoded_bytes = decoded.readframes(decoded.getnframes())
        if len(decoded_bytes) != expected_bytes or decoded.readframes(1):
            raise ValueError("Assembled PCM WAV did not fully decode")
    schedule = {
        "schemaVersion": "sermon-target-language-prosody-poc-schedule-v1",
        "timingKind": "measured_unit_audio_with_source_pause_assembly",
        "targetLocale": plan["targetLocale"],
        "ratePolicy": "natural_no_time_stretch",
        "trackDurationSeconds": round(cursor_frames / audio_format[2], 6) if audio_format else 0,
        "units": schedule_rows,
    }
    write_json(out / "schedule.json", schedule)
    manifest = {
        "schemaVersion": "sermon-target-language-prosody-poc-assembly-v1",
        "status": "assembled_and_fully_decoded_human_review_pending",
        "productionEligible": False,
        "humanApproval": False,
        "planJsonSha256": canonical_sha(plan),
        "track": {"path": "audio.wav", "sha256": file_sha(track_path)},
        "fullDecode": "pass",
        "schedule": {"path": "schedule.json", "jsonSha256": canonical_sha(schedule)},
        "metrics": {
            "maxAbsoluteSpeechDurationDeltaSeconds": round(max(abs(row["speechDurationDeltaSeconds"]) for row in schedule_rows), 6),
            "maxAbsoluteSpeechEndLagSeconds": round(max(abs(row["speechEndLagSeconds"]) for row in schedule_rows), 6),
        },
        "humanListeningStatus": "pending",
        "limitations": plan["limitations"],
    }
    write_json(out / "assembly-manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_cmd = commands.add_parser("prepare")
    prepare_cmd.add_argument("--anchor", type=Path, required=True)
    prepare_cmd.add_argument("--candidate", type=Path, required=True)
    prepare_cmd.add_argument("--out", type=Path, required=True)
    render_cmd = commands.add_parser("render")
    render_cmd.add_argument("--plan", type=Path, required=True)
    render_cmd.add_argument("--checkpoint", type=Path, required=True)
    render_cmd.add_argument("--expected-checkpoint-sha256", required=True)
    render_cmd.add_argument("--speaker-key", required=True)
    render_cmd.add_argument("--model-language", required=True)
    render_cmd.add_argument("--out", type=Path, required=True)
    render_cmd.add_argument("--device", default="cuda:0")
    render_cmd.add_argument("--dtype", choices=("bfloat16", "float32"), default="bfloat16")
    render_cmd.add_argument("--attention", default="sdpa")
    render_cmd.add_argument("--seed", type=int, default=42)
    tune_cmd = commands.add_parser("tune")
    tune_cmd.add_argument("--plan", type=Path, required=True)
    tune_cmd.add_argument("--baseline-schedule", type=Path, required=True)
    tune_cmd.add_argument("--out", type=Path, required=True)
    tune_cmd.add_argument("--threshold", type=float, default=0.4)
    assemble_cmd = commands.add_parser("assemble")
    assemble_cmd.add_argument("--plan", type=Path, required=True)
    assemble_cmd.add_argument("--unit-dir", type=Path, required=True)
    assemble_cmd.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.anchor, args.candidate, args.out)
    elif args.command == "render":
        result = render(args.plan, args.checkpoint, args.expected_checkpoint_sha256,
                        args.speaker_key, args.model_language, args.out,
                        device=args.device, dtype_name=args.dtype, attention=args.attention, seed=args.seed)
    elif args.command == "tune":
        result = tune(args.plan, args.baseline_schedule, args.out, threshold=args.threshold)
    else:
        result = assemble(args.plan, args.unit_dir, args.out)
    print(json.dumps({"status": result["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
