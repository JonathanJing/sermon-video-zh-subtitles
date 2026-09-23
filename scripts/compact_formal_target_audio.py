#!/usr/bin/env python3
"""Reuse verified raw Layer 3 units, removing only measured leading silence.

The input render directory is immutable. A new job directory receives the same
job bytes, shortened WAVs, fresh unit integrity receipts and a trim evidence
sidecar. No words, playback speed, or source/candidate text are changed.
"""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import wave

try:
    from scripts import render_formal_target_language_speech as renderer
    from scripts import validate_target_language_audio_unit as integrity
    from scripts import sermon_sentence_interpretation as identity
except ImportError:
    import render_formal_target_language_speech as renderer
    import validate_target_language_audio_unit as integrity
    import sermon_sentence_interpretation as identity


SCHEMA = "sermon-formal-leading-silence-trim-v1"
EDGE_SCHEMA = "sermon-formal-edge-silence-trim-v1"
THRESHOLD = 0.01
PADDING_SECONDS = 0.06
WINDOW_SECONDS = 0.01
MAX_TRIM_SECONDS = 0.75


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def trimmed_samples(path: Path, *, padding_seconds: float = PADDING_SECONDS,
                    trim_trailing: bool = False) -> tuple[bytes, int, float, float, float]:
    require(0.02 <= padding_seconds <= PADDING_SECONDS,
            "Speech-edge padding must remain between 20 and 60 ms")
    info = integrity.probe_pcm_wav(path)
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    values = array("h")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    window = max(1, round(rate * WINDOW_SECONDS))
    first_active = last_active_end = None
    for start in range(0, len(values), window):
        block = values[start:start + window]
        rms = math.sqrt(sum(sample * sample for sample in block) / len(block)) / 32768
        if rms >= THRESHOLD:
            if first_active is None:
                first_active = start
            last_active_end = min(len(values), start + window)
    require(first_active is not None, f"No audible speech energy: {path}")
    removed = min(max(0, first_active - round(padding_seconds * rate)),
                  round(MAX_TRIM_SECONDS * rate))
    trailing = (min(max(0, len(values) - last_active_end - round(padding_seconds * rate)),
                    round(MAX_TRIM_SECONDS * rate)) if trim_trailing else 0)
    require(removed + trailing < len(values), "Trim would remove entire unit")
    remainder = values[removed:len(values) - trailing if trailing else len(values)]
    if sys.byteorder != "little":
        remainder.byteswap()
    return remainder.tobytes(), rate, removed / rate, trailing / rate, info["durationSeconds"]


def compact_unit(source_job: Path, destination_job: Path, index: int,
                 *, expected_job_hash: str, padding_seconds: float = PADDING_SECONDS,
                 trim_trailing: bool = False) -> dict:
    job = json.loads(source_job.read_text(encoding="utf-8"))
    unit = job["units"][index]
    source_root, destination_root = source_job.parent, destination_job.parent
    raw = source_root / unit["outputRelativePath"]
    receipt = source_root / f"receipts/unit-{index:04d}.json"
    intent = source_root / f"receipts/unit-{index:04d}.intent.json"
    commit = source_root / f"receipts/unit-{index:04d}.render.json"
    require(all(path.is_file() for path in (raw, receipt, intent, commit)),
            f"Raw committed unit missing: {index}")
    integrity.validate_receipt(source_job, index, raw,
                               json.loads(receipt.read_text(encoding="utf-8")))
    source_intent = json.loads(intent.read_text(encoding="utf-8"))
    source_commit = json.loads(commit.read_text(encoding="utf-8"))
    raw_sha = identity.sha256(raw)
    require(source_commit.get("identity") == source_intent
            and source_commit.get("audioSha256") == raw_sha
            and source_intent.get("jobJsonSha256") == expected_job_hash
            and source_intent.get("groupId") == unit["translationGroupId"]
            and source_intent.get("textSha256") == hashlib.sha256(unit["text"].encode()).hexdigest(),
            f"Raw render intent or commit changed: {index}")
    compacted_bytes, rate, removed_seconds, removed_trailing, original_duration = trimmed_samples(
        raw, padding_seconds=padding_seconds, trim_trailing=trim_trailing)
    output = destination_root / unit["outputRelativePath"]
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        with wave.open(str(output), "rb") as handle:
            require(handle.readframes(handle.getnframes()) == compacted_bytes,
                    f"Compacted audio changed on resume: {index}")
    else:
        partial = output.with_suffix(".partial.wav")
        with wave.open(str(partial), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(compacted_bytes)
        integrity.probe_pcm_wav(partial)
        os.replace(partial, output)
    output_receipt = destination_root / f"receipts/unit-{index:04d}.json"
    if output_receipt.exists():
        integrity.validate_receipt(destination_job, index, output,
                                   json.loads(output_receipt.read_text(encoding="utf-8")))
    else:
        renderer.write_json_atomic(output_receipt,
                                   integrity.build_receipt(destination_job, index, output))
    item = json.loads(output_receipt.read_text(encoding="utf-8"))
    result = {"unitIndex": index, "textGroupId": unit["translationGroupId"],
            "sourceAudioSha256": raw_sha, "audioSha256": identity.sha256(output),
            "removedLeadingSeconds": round(removed_seconds, 6),
            "originalDurationSeconds": round(original_duration, 6),
            "durationSeconds": item["durationSeconds"],
            "manifestUnit": {"textGroupId": unit["translationGroupId"],
                             "targetTextSha256": hashlib.sha256(unit["text"].encode()).hexdigest(),
                             "audio": renderer.artifact(destination_root, output),
                             "durationSeconds": item["durationSeconds"],
                             "receipt": renderer.artifact(destination_root, output_receipt,
                                                          json_artifact=True)}}
    if trim_trailing or padding_seconds != PADDING_SECONDS:
        result["removedTrailingSeconds"] = round(removed_trailing, 6)
    return result


def compact(paths: dict[str, Path], source_job: Path, destination_root: Path,
            checkpoint_map: Path, operation_policies: Path, *, path_map: Path | None = None,
            padding_seconds: float = PADDING_SECONDS, trim_trailing: bool = False,
            inter_utterance_gap_seconds: float = renderer.DEFAULT_POLICY["interUtteranceGapSeconds"],
            reaction_lag_seconds: float = renderer.DEFAULT_POLICY["reactionLagSeconds"]) -> dict:
    require(0 <= inter_utterance_gap_seconds <= renderer.DEFAULT_POLICY["interUtteranceGapSeconds"],
            "Silence compaction cannot expand the inter-utterance gap")
    require(0 <= reaction_lag_seconds <= renderer.DEFAULT_POLICY["reactionLagSeconds"],
            "Reaction lag must remain within the tested schedule policy")
    require(source_job.is_file(), "Raw job missing")
    destination_job = destination_root / "job.json"
    destination_root.mkdir(parents=True, exist_ok=True)
    if destination_job.exists():
        require(identity.sha256(destination_job) == identity.sha256(source_job),
                "Destination job differs from raw job")
    else:
        shutil.copy2(source_job, destination_job)
    if path_map:
        renderer.materialize_path_map(destination_job, path_map)
    adapted_paths = dict(paths, job=destination_job)
    context = renderer.checked_context(adapted_paths, checkpoint_map, operation_policies)
    job_hash = identity.json_sha256(context["job"])
    rows = [compact_unit(source_job, destination_job, index, expected_job_hash=job_hash,
                         padding_seconds=padding_seconds, trim_trailing=trim_trailing)
            for index in range(len(context["job"]["units"]))]
    edge_mode = trim_trailing or padding_seconds != PADDING_SECONDS
    receipt = {"schemaVersion": EDGE_SCHEMA if edge_mode else SCHEMA,
               "status": "measured_silence_removed",
               "targetLocale": context["job"]["targetLocale"],
               "targetLanguageSpeechJobJsonSha256": job_hash,
               "sourceJobFileSha256": identity.sha256(source_job),
               "thresholdRms": THRESHOLD, "paddingSeconds": padding_seconds,
               "windowSeconds": WINDOW_SECONDS, "maxTrimSeconds": MAX_TRIM_SECONDS,
               "units": [{key: value for key, value in row.items() if key != "manifestUnit"}
                         for row in rows], "humanListeningStatus": "pending"}
    if edge_mode:
        receipt["trimTrailing"] = trim_trailing
        receipt["interUtteranceGapSeconds"] = inter_utterance_gap_seconds
        receipt["reactionLagSeconds"] = reaction_lag_seconds
    trim_path = destination_root / "review/leading-silence-trim.json"
    if trim_path.exists():
        require(json.loads(trim_path.read_text(encoding="utf-8")) == receipt,
                "Existing trim evidence differs")
    else:
        renderer.write_json_atomic(trim_path, receipt)
    policy = dict(renderer.DEFAULT_POLICY,
                  interUtteranceGapSeconds=inter_utterance_gap_seconds,
                  reactionLagSeconds=reaction_lag_seconds)
    manifest = renderer.assemble(context, adapted_paths, destination_root,
                                 [row["manifestUnit"] for row in rows], policy=policy)
    manifest["silenceTrimEvidence"] = renderer.artifact(destination_root, trim_path,
                                                        json_artifact=True)
    renderer.write_json_atomic(destination_root / "render-manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "anchor", "candidate", "adapter", "policy"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--human-review-receipt", dest="human_receipt", type=Path, required=True)
    parser.add_argument("--speaker-registry", dest="registry", type=Path, required=True)
    parser.add_argument("--clip-voice-authorization", dest="clip_voice_authorization", type=Path, required=True)
    parser.add_argument("--clip-voice-capability", dest="clip_voice_capability", type=Path)
    parser.add_argument("--clip-timeline-map", dest="clip_timeline_map", type=Path, required=True)
    parser.add_argument("--source-job", type=Path, required=True)
    parser.add_argument("--destination-root", type=Path, required=True)
    parser.add_argument("--checkpoint-map", type=Path, required=True)
    parser.add_argument("--audio-operation-policies", type=Path, required=True)
    parser.add_argument("--path-map", type=Path)
    parser.add_argument("--trim-trailing", action="store_true")
    parser.add_argument("--padding-seconds", type=float, default=PADDING_SECONDS)
    parser.add_argument("--inter-utterance-gap-seconds", type=float,
                        default=renderer.DEFAULT_POLICY["interUtteranceGapSeconds"])
    parser.add_argument("--reaction-lag-seconds", type=float,
                        default=renderer.DEFAULT_POLICY["reactionLagSeconds"])
    args = parser.parse_args()
    paths = {name: getattr(args, name) for name in ("source", "anchor", "candidate", "adapter",
                                                   "policy", "human_receipt", "registry",
                                                   "clip_voice_authorization", "clip_timeline_map")}
    if args.clip_voice_capability:
        paths["clip_voice_capability"] = args.clip_voice_capability
    manifest = compact(paths, args.source_job, args.destination_root, args.checkpoint_map,
                       args.audio_operation_policies, path_map=args.path_map,
                       padding_seconds=args.padding_seconds,
                       trim_trailing=args.trim_trailing,
                       inter_utterance_gap_seconds=args.inter_utterance_gap_seconds,
                       reaction_lag_seconds=args.reaction_lag_seconds)
    print(json.dumps({"status": "candidate", "locale": manifest["targetLocale"],
                      "trimmedUnits": len(manifest["units"]),
                      "track": manifest["track"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
