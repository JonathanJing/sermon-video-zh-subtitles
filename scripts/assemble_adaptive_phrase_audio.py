#!/usr/bin/env python3
"""Assemble phrase TTS against source phrase-start anchors using dynamic silence.

Each target phrase keeps its measured speech unchanged.  Before every phrase,
the scheduler inserts only enough silence to reach that phrase's Layer 1 start
anchor.  If earlier target speech has already crossed the anchor, it inserts no
silence and records an overrun for later repair; it never time-stretches or cuts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import wave
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_multilingual_prosody_poc import PLAN_SCHEMA, canonical_sha, file_sha, read_object, write_json


def assemble(plan_path: Path, unit_dir: Path, out: Path) -> dict[str, Any]:
    if out.exists():
        raise ValueError(f"Adaptive assembly directory already exists: {out}")
    plan = read_object(plan_path)
    if plan.get("schemaVersion") != PLAN_SCHEMA:
        raise ValueError("Adaptive assembly requires a compatible phrase plan")
    units = plan.get("units")
    if not isinstance(units, list) or len(units) < 2:
        raise ValueError("Adaptive assembly requires at least two phrases")
    parent_ids: list[str] = []
    closed_parents: set[str] = set()
    active_parent: str | None = None
    for unit in units:
        parent = unit.get("parentSourceUnitId")
        if not isinstance(parent, str) or not parent:
            raise ValueError("Every phrase must bind to a parent source unit")
        if parent != active_parent:
            if parent in closed_parents:
                raise ValueError("Phrases for each parent source unit must be contiguous")
            if active_parent is not None:
                closed_parents.add(active_parent)
            parent_ids.append(parent)
            active_parent = parent

    audio_rows = []
    audio_format: tuple[int, int, int, str, str] | None = None
    for unit in units:
        source = unit_dir / unit["outputRelativePath"]
        with wave.open(str(source), "rb") as reader:
            current_format = (
                reader.getnchannels(), reader.getsampwidth(), reader.getframerate(),
                reader.getcomptype(), reader.getcompname(),
            )
            if current_format[0] != 1 or current_format[3] != "NONE":
                raise ValueError(f"Phrase WAV must be mono PCM: {source}")
            if audio_format is None:
                audio_format = current_format
            elif current_format != audio_format:
                raise ValueError("Phrase WAV formats differ")
            frame_count = reader.getnframes()
            frames = reader.readframes(frame_count)
            if reader.readframes(1):
                raise ValueError(f"Phrase WAV has unread trailing frames: {source}")
        audio_rows.append((unit, frames, frame_count))
    assert audio_format is not None

    out.mkdir(parents=True)
    track_path = out / "audio.wav"
    sample_width, sample_rate = audio_format[1], audio_format[2]
    source_origin = float(plan["sourceWindow"]["startSeconds"])
    acoustic_pause_policy = plan.get("renderContract", {}).get("pausePolicy") == "measured_layer1_pause_only_capped_by_source_gap"
    cursor_frames = 0
    schedule_rows = []
    with wave.open(str(track_path), "wb") as writer:
        writer.setparams((audio_format[0], sample_width, sample_rate, 0, audio_format[3], audio_format[4]))
        previous_unit = None
        for unit, frames, speech_frames in audio_rows:
            expected_start = float(unit["sourceStartSeconds"]) - source_origin
            expected_start_frames = round(expected_start * sample_rate)
            available_frames = max(0, expected_start_frames - cursor_frames)
            same_sentence = previous_unit is not None and unit["parentSourceUnitId"] == previous_unit["parentSourceUnitId"]
            pause_evidence = unit.get("sourcePauseEvidence")
            if acoustic_pause_policy and previous_unit is not None:
                if not pause_evidence:
                    raise ValueError(f"Boundary lacks Layer 1 pause evidence: {unit['sourceUnitId']}")
                classification = pause_evidence.get("classification")
                if same_sentence and classification != "supported_pause_candidate":
                    raise ValueError(f"Intra-sentence pause lacks Layer 1 acoustic evidence: {unit['sourceUnitId']}")
                if classification == "supported_pause_candidate":
                    source_pause_frames = round(float(pause_evidence["measuredLowEnergyOverlapSeconds"]) * sample_rate)
                elif same_sentence:
                    raise ValueError(f"Intra-sentence pause lacks Layer 1 acoustic evidence: {unit['sourceUnitId']}")
                elif classification == "alignment_gap_only":
                    # A sentence-level no-word gap can be masked by background
                    # sound. Retain its measured alignment span as a candidate
                    # and flag it for source listening rather than claiming
                    # that the low-energy detector confirmed it.
                    source_pause_frames = round(float(pause_evidence["alignmentGapSeconds"]) * sample_rate)
                else:
                    source_pause_frames = 0
                minimum_pause_frames = (min(source_pause_frames, round(0.2 * sample_rate))
                                        if classification == "supported_pause_candidate" else 0)
                pause_frames = max(minimum_pause_frames, min(available_frames, source_pause_frames))
            else:
                pause_frames = available_frames
            if pause_frames:
                writer.writeframes(b"\x00" * pause_frames * sample_width)
                cursor_frames += pause_frames
            start = cursor_frames / sample_rate
            raw_start_lag = start - expected_start
            overrun = raw_start_lag if raw_start_lag > (1 / sample_rate) else 0.0
            writer.writeframes(frames)
            cursor_frames += speech_frames
            speech_end = cursor_frames / sample_rate
            schedule_rows.append({
                "unitIndex": unit["unitIndex"],
                "sourceUnitId": unit["sourceUnitId"],
                "parentSourceUnitId": unit["parentSourceUnitId"],
                "expectedStartSeconds": round(expected_start, 6),
                "startSeconds": round(start, 6),
                "startLagSeconds": round(raw_start_lag, 6),
                "speechEndSeconds": round(speech_end, 6),
                "actualSpeechDurationSeconds": round(speech_frames / sample_rate, 6),
                "insertedPauseBeforeSeconds": round(pause_frames / sample_rate, 6),
                "sourcePauseEvidence": pause_evidence if acoustic_pause_policy and previous_unit is not None else None,
                "overrunBeforeSeconds": round(overrun, 6),
                "pauseDecision": ("acoustic_pause_preserved_after_overrun" if acoustic_pause_policy and same_sentence and not available_frames
                                  else "source_pause_capped" if acoustic_pause_policy and previous_unit is not None and pause_frames < available_frames
                                  else "source_pause_applied" if acoustic_pause_policy and previous_unit is not None and pause_frames
                                  else "source_no_pause" if acoustic_pause_policy and previous_unit is not None
                                  else "anchor_fill" if pause_frames else "overrun_no_pause" if overrun else "on_anchor"),
                "text": unit["targetText"],
            })
            previous_unit = unit

    with wave.open(str(track_path), "rb") as decoded:
        expected_bytes = decoded.getnframes() * decoded.getnchannels() * decoded.getsampwidth()
        decoded_bytes = decoded.readframes(decoded.getnframes())
        if len(decoded_bytes) != expected_bytes or decoded.readframes(1):
            raise ValueError("Adaptive PCM WAV did not fully decode")

    duration = cursor_frames / sample_rate
    source_duration = float(plan["sourceWindow"]["durationSeconds"])
    sentence_rows = []
    for parent_index, parent_id in enumerate(parent_ids):
        rows = [row for row in schedule_rows if row["parentSourceUnitId"] == parent_id]
        source_units = [unit for unit in units if unit["parentSourceUnitId"] == parent_id]
        next_start = (next(row["startSeconds"] for row in schedule_rows
                           if row["parentSourceUnitId"] == parent_ids[parent_index + 1])
                      if parent_index + 1 < len(parent_ids) else round(duration, 6))
        sentence_rows.append({
            "sourceUnitId": parent_id,
            "startSeconds": rows[0]["startSeconds"],
            "speechEndSeconds": rows[-1]["speechEndSeconds"],
            "endSeconds": next_start,
            "sourceStartSeconds": round(float(source_units[0]["sourceStartSeconds"]) - source_origin, 6),
            "sourceEndSeconds": round(float(source_units[-1].get(
                "sourceEndSeconds", source_units[-1]["sourceStartSeconds"]
            )) - source_origin, 6),
            "text": "".join(unit["targetText"] for unit in source_units),
        })
    schedule = {
        "schemaVersion": "sermon-target-language-adaptive-phrase-schedule-v1",
        "timingKind": ("measured_phrase_audio_with_layer1_acoustic_pause_caps" if acoustic_pause_policy
                       else "measured_phrase_audio_with_source_start_anchor_fill"),
        "targetLocale": plan["targetLocale"],
        "parentSourceUnitIds": parent_ids,
        "displayText": "".join(unit["targetText"] for unit in units),
        "sourceDurationSeconds": source_duration,
        "trackDurationSeconds": round(duration, 6),
        "sentenceEndLagSeconds": round(duration - source_duration, 6),
        "sentences": sentence_rows,
        "units": schedule_rows,
    }
    if acoustic_pause_policy:
        schedule["pauseEvidenceJsonSha256"] = plan["pauseEvidenceJsonSha256"]
        schedule["sourceMediaSha256"] = plan["sourceMediaSha256"]
    if len(parent_ids) == 1:
        schedule["parentSourceUnitId"] = parent_ids[0]
    write_json(out / "schedule.json", schedule)
    manifest = {
        "schemaVersion": "sermon-target-language-adaptive-phrase-assembly-v1",
        "status": "assembled_and_fully_decoded_human_review_pending",
        "productionEligible": False,
        "humanApproval": False,
        "planJsonSha256": canonical_sha(plan),
        "track": {"path": "audio.wav", "sha256": file_sha(track_path)},
        "fullDecode": "pass",
        "schedule": {"path": "schedule.json", "jsonSha256": canonical_sha(schedule)},
        "metrics": {
            "maxAbsolutePhraseStartLagSeconds": round(max(abs(row["startLagSeconds"]) for row in schedule_rows), 6),
            "sentenceEndLagSeconds": schedule["sentenceEndLagSeconds"],
            "overrunPhraseCount": sum(row["overrunBeforeSeconds"] > 0 for row in schedule_rows),
            "sentenceCount": len(sentence_rows),
            "phraseCount": len(schedule_rows),
            "acousticSupportedInternalPauseCount": sum(
                index > 0 and row["parentSourceUnitId"] == schedule_rows[index - 1]["parentSourceUnitId"]
                and row["sourcePauseEvidence"] is not None for index, row in enumerate(schedule_rows)
            ),
        },
        "ratePolicy": "measured_natural_phrase_audio_no_time_stretch",
        "pausePolicy": ("intra_sentence_only_with_layer1_measured_low_energy_capped_by_source_gap"
                        if acoustic_pause_policy else "dynamic_silence_to_next_layer1_phrase_start_anchor"),
        "humanListeningStatus": "pending",
    }
    write_json(out / "assembly-manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--unit-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = assemble(args.plan, args.unit_dir, args.out)
    print(json.dumps({"status": result["status"], "metrics": result["metrics"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
