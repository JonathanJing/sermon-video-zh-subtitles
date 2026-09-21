#!/usr/bin/env python3
"""Prepare and verify natural-rate TTS for sentence-anchored interpretation.

The existing weekly Qwen renderer remains the synthesis implementation.  This
adapter freezes the semantic candidate into an immutable render job, then
turns fully decoded per-group WAVs into the measured-audio candidate consumed
by ``sermon_sentence_interpretation.py``.  It never changes the reviewed text,
time-stretches audio, or treats machine synthesis as human acceptance.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
from typing import Any, Callable

try:
    from scripts import sermon_sentence_interpretation as interpretation
except ImportError:  # Direct execution via ``python scripts/...``.
    import sermon_sentence_interpretation as interpretation


JOB_SCHEMA = "sermon-sentence-natural-tts-job-v1"
AUDIO_RECEIPT_SCHEMA = "sermon-sentence-natural-tts-audio-receipt-v1"
METRICS_SCHEMA = "sermon-sentence-natural-tts-metrics-v1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _semantic_groups(anchor: dict[str, Any], semantic: dict[str, Any]) -> list[dict[str, Any]]:
    _require(interpretation.is_supported_anchor_manifest(anchor), "Unsupported anchor manifest")
    _require(semantic.get("schemaVersion") == "sermon-sentence-semantic-candidate-v1",
             "Unsupported semantic candidate")
    _require(semantic.get("status") == "model_review_pass_tts_and_human_review_pending",
             "Semantic candidate has not passed independent machine review")
    _require(semantic.get("anchorManifestSha256") == interpretation.json_sha256(anchor),
             "Semantic candidate belongs to another anchor manifest")
    groups = semantic.get("groups")
    _require(isinstance(groups, list) and groups, "Semantic candidate has no groups")
    expected = [unit["sourceUnitId"] for unit in anchor.get("sourceUnits", [])]
    assigned = [unit_id for group in groups for unit_id in group.get("sourceUnitIds", [])]
    _require(assigned == expected, "Semantic candidate must cover every source unit exactly once")
    for group in groups:
        chinese = str(group.get("chinese", "")).strip()
        utterances = group.get("chineseUtterances")
        _require(chinese and isinstance(utterances, list)
                 and chinese == "".join(str(text).strip() for text in utterances),
                 f"Invalid reviewed Chinese: {group.get('translationGroupId')}")
        review = group.get("review", {})
        _require(review.get("status") == "pass",
                 f"Semantic review is not pass: {group.get('translationGroupId')}")
    return groups


def prepare_job(anchor_path: Path, semantic_path: Path, checkpoint: Path, out: Path, *,
                speaker_key: str = "eric_pilot", speaker: str = "Eric Geiger") -> dict[str, Any]:
    _require(not out.exists(), "Use a new TTS job directory; prior jobs are immutable")
    _require(anchor_path.is_file() and semantic_path.is_file(), "Anchor or semantic input is missing")
    _require((checkpoint / "model.safetensors").is_file(), "TTS checkpoint weights are missing")
    _require((checkpoint / "config.json").is_file(), "TTS checkpoint config is missing")
    anchor = _load_json(anchor_path)
    semantic = _load_json(semantic_path)
    groups = _semantic_groups(anchor, semantic)
    config = _load_json(checkpoint / "config.json")
    speakers = config.get("talker_config", {}).get("spk_id", {})
    _require(speaker_key in speakers, f"Checkpoint does not contain speaker key: {speaker_key}")
    gap = float(anchor["policy"]["interUtteranceGapSeconds"])
    units_by_id = {unit["sourceUnitId"]: unit for unit in anchor["sourceUnits"]}
    units = []
    for index, group in enumerate(groups):
        source_ids = list(group["sourceUnitIds"])
        first = units_by_id[source_ids[0]]
        units.append({
            "id": index,
            "blockId": first["referenceChunkId"],
            "translationGroupId": group["translationGroupId"],
            "sourceUnitIds": source_ids,
            "text": group["chinese"],
            "gapAfterSeconds": gap,
        })
    job = {
        # The renderer accepts the weekly v1 envelope; the purpose-specific
        # contract below prevents this POC from masquerading as a weekly job.
        "schemaVersion": "sermon-weekly-dubbing-job-v1",
        "purposeSchemaVersion": JOB_SCHEMA,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "status": "prepared_for_natural_rate_tts",
        "releaseEligible": False,
        "voice": {
            "speaker": speaker,
            "speakerKey": speaker_key,
            "checkpointSha256": sha256(checkpoint / "model.safetensors"),
            "model": "Qwen3-TTS-12Hz-1.7B-CustomVoice-finetuned",
        },
        "inputs": {
            "anchorManifest": {"path": str(anchor_path.resolve()), "sha256": sha256(anchor_path)},
            "semanticCandidate": {"path": str(semantic_path.resolve()), "sha256": sha256(semantic_path)},
        },
        "renderContract": {
            "textPolicy": "exact_reviewed_chinese",
            "ratePolicy": interpretation.RATE_POLICY,
            "playbackRate": 1.0,
            "postProcessing": "none_before_measurement",
            "humanListeningReview": "pending",
        },
        "units": units,
    }
    out.mkdir(parents=True)
    write_json(out / "job.json", job)
    return job


def _run(argv: list[str], *, process_runner: Callable[..., Any] = subprocess.run) -> Any:
    return process_runner(argv, capture_output=True, text=True, check=True, timeout=300)


def probe_and_decode(path: Path, *, process_runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    _require(path.is_file() and path.stat().st_size > 0, f"Missing audio: {path}")
    result = _run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,codec_name,sample_rate,channels",
        "-of", "json", str(path),
    ], process_runner=process_runner)
    data = json.loads(result.stdout)
    streams = [stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"]
    duration = float(data.get("format", {}).get("duration", 0))
    _require(math.isfinite(duration) and duration > 0 and streams, f"No usable audio: {path}")
    _run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
         process_runner=process_runner)
    return {"durationSeconds": duration, "streams": streams, "fullDecode": "pass"}


def _model_receipt(role: str, semantic: dict[str, Any]) -> dict[str, Any]:
    source = semantic.get(role, {})
    batches = source.get("batchReceipts")
    _require(isinstance(batches, list) and batches, f"Missing {role} batch receipts")
    response_ids = [str(item.get("responseId", "")).strip() for item in batches]
    _require(all(response_ids), f"Missing {role} response ID")
    receipt = {
        "model": source.get("model"),
        "promptVersion": source.get("promptVersion"),
        "requestId": "batch-set:" + json_sha256(response_ids),
        "responseIds": response_ids,
        "batchReceipts": batches,
    }
    return receipt


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return round(ordered[index], 6)


def _metrics(anchor: dict[str, Any], candidate: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    unit_by_id = {unit["sourceUnitId"]: unit for unit in anchor["sourceUnits"]}
    durations = [float(group["audio"]["durationSeconds"]) for group in candidate["groups"]]
    source_spans = []
    ratios = []
    characters = []
    group_rows = []
    for group in candidate["groups"]:
        selected = [unit_by_id[unit_id] for unit_id in group["sourceUnitIds"]]
        source_span = float(selected[-1]["end"]) - float(selected[0]["start"])
        duration = float(group["audio"]["durationSeconds"])
        source_spans.append(source_span)
        ratios.append(duration / source_span)
        characters.append(len(group["chinese"]))
        group_rows.append({
            "translationGroupId": group["translationGroupId"],
            "referenceChunkId": selected[0]["referenceChunkId"],
            "sourceSeconds": source_span,
            "audioSeconds": duration,
        })
    schedule = report.get("schedule", [])
    schedule_by_id = {row["translationGroupId"]: row for row in schedule}
    end_lags = [float(row["endLagSeconds"]) for row in schedule]
    limit = float(anchor["policy"]["maxEndLagSeconds"])
    over = [row for row in schedule if float(row["endLagSeconds"]) > limit + 0.001]
    blocks: dict[str, list[dict[str, Any]]] = {}
    for row in group_rows:
        combined = {**row, **schedule_by_id.get(row["translationGroupId"], {})}
        blocks.setdefault(row["referenceChunkId"], []).append(combined)
    block_metrics = [{
        "referenceChunkId": block_id,
        "translationGroups": len(rows),
        "ttsSeconds": round(sum(row["audioSeconds"] for row in rows), 6),
        "englishMeaningUnitSeconds": round(sum(row["sourceSeconds"] for row in rows), 6),
        "groupsOverLagLimit": sum(float(row.get("endLagSeconds", 0)) > limit + 0.001 for row in rows),
        "maxEndLagSeconds": round(max(float(row.get("endLagSeconds", 0)) for row in rows), 6),
    } for block_id, rows in blocks.items()]
    worst = sorted(schedule, key=lambda row: float(row["endLagSeconds"]), reverse=True)[:10]
    return {
        "schemaVersion": METRICS_SCHEMA,
        "status": "measured_natural_rate_tts_human_listening_pending",
        "releaseEligible": False,
        "counts": {
            "translationGroups": len(durations),
            "fullyDecodedAudioFiles": len(durations),
            "chineseCharacters": sum(characters),
            "groupsOverLagLimit": len(over),
        },
        "audio": {
            "totalSpeechSeconds": round(sum(durations), 6),
            "medianGroupSeconds": round(statistics.median(durations), 6),
            "p95GroupSeconds": _quantile(durations, 0.95),
            "maxGroupSeconds": round(max(durations), 6),
            "charactersPerSecond": round(sum(characters) / sum(durations), 6),
            "playbackRate": 1.0,
            "ratePolicy": interpretation.RATE_POLICY,
        },
        "sourceComparison": {
            "totalEnglishMeaningUnitSeconds": round(sum(source_spans), 6),
            "ttsToEnglishSpanRatio": round(sum(durations) / sum(source_spans), 6),
            "medianGroupDurationRatio": round(statistics.median(ratios), 6),
            "p95GroupDurationRatio": _quantile(ratios, 0.95),
        },
        "rollingSchedule": {
            "policy": report.get("schedulePolicy"),
            "maxAllowedEndLagSeconds": limit,
            "medianEndLagSeconds": round(statistics.median(end_lags), 6) if end_lags else None,
            "p95EndLagSeconds": _quantile(end_lags, 0.95),
            "maxEndLagSeconds": report.get("maxObservedEndLagSeconds"),
            "groupsOverLimit": [row["translationGroupId"] for row in over],
            "worstGroups": worst,
            "blocks": block_metrics,
        },
        "validation": {
            "status": report["status"],
            "candidateReadyForHumanReview": report["candidateReadyForHumanReview"],
            "checks": report["checks"],
        },
        "pending": ["human_bilingual_review", "natural_speech_and_pronunciation_review", "full_playback_review"],
    }


def finalize(anchor_path: Path, semantic_path: Path, job_path: Path, render: Path, out: Path, *,
             process_runner: Callable[..., Any] = subprocess.run) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    anchor = _load_json(anchor_path)
    semantic = _load_json(semantic_path)
    semantic_groups = _semantic_groups(anchor, semantic)
    job = _load_json(job_path)
    _require(job.get("purposeSchemaVersion") == JOB_SCHEMA, "Not a sentence natural-TTS job")
    _require(job.get("renderContract", {}).get("ratePolicy") == interpretation.RATE_POLICY
             and job.get("renderContract", {}).get("playbackRate") == 1.0,
             "Render job is not natural-rate audio")
    _require(job["inputs"]["anchorManifest"]["sha256"] == sha256(anchor_path)
             and job["inputs"]["semanticCandidate"]["sha256"] == sha256(semantic_path),
             "Render job inputs changed")
    _require(len(job.get("units", [])) == len(semantic_groups), "Render job group count changed")
    identity = _load_json(render / "identity.json")
    render_report = _load_json(render / "report.json")
    _require(identity.get("jobSha256") == sha256(job_path), "Render identity belongs to another job")
    _require(render_report.get("jobSha256") == identity.get("jobSha256")
             and render_report.get("status") == "complete_candidate_render",
             "TTS render is incomplete or stale")
    combined = render / "chinese.raw.wav"
    _require(render_report.get("sha256") == sha256(combined), "Combined render hash changed")
    combined_probe = probe_and_decode(combined, process_runner=process_runner)

    candidate_groups = []
    receipts = []
    for index, (semantic_group, unit) in enumerate(zip(semantic_groups, job["units"])):
        _require(unit.get("translationGroupId") == semantic_group.get("translationGroupId")
                 and unit.get("sourceUnitIds") == semantic_group.get("sourceUnitIds")
                 and unit.get("text") == semantic_group.get("chinese"),
                 f"TTS unit text or source binding changed: {index}")
        wav = render / f"unit-{index:04d}.wav"
        renderer_receipt_path = wav.with_suffix(".json")
        renderer_receipt = _load_json(renderer_receipt_path)
        _require(renderer_receipt.get("unit") == unit and renderer_receipt.get("identity") == identity,
                 f"Renderer receipt changed: {index}")
        _require(renderer_receipt.get("sha256") == sha256(wav), f"Audio hash changed: {index}")
        probed = probe_and_decode(wav, process_runner=process_runner)
        recorded = float(renderer_receipt.get("durationSeconds", 0))
        _require(abs(probed["durationSeconds"] - recorded) <= 0.01,
                 f"Measured duration differs from renderer receipt: {index}")
        audio_receipt = {
            "schemaVersion": AUDIO_RECEIPT_SCHEMA,
            "translationGroupId": unit["translationGroupId"],
            "sourceUnitIds": unit["sourceUnitIds"],
            "text": unit["text"],
            "textSha256": hashlib.sha256(unit["text"].encode()).hexdigest(),
            "audio": {
                "path": str(wav.resolve()),
                "sha256": sha256(wav),
                **probed,
            },
            "rendererReceipt": {
                "path": str(renderer_receipt_path.resolve()),
                "sha256": sha256(renderer_receipt_path),
            },
            "ratePolicy": interpretation.RATE_POLICY,
            "playbackRate": 1.0,
            "humanListeningReview": "pending",
        }
        receipt_path = out / "audio-receipts" / f"group-{index:04d}.json"
        write_json(receipt_path, audio_receipt)
        receipts.append(audio_receipt)
        group = copy.deepcopy(semantic_group)
        group["audio"] = {
            "text": group["chinese"],
            "durationSeconds": round(probed["durationSeconds"], 6),
            "ratePolicy": interpretation.RATE_POLICY,
            "playbackRate": 1.0,
            "receiptSha256": sha256(receipt_path),
        }
        candidate_groups.append(group)

    candidate = {
        "schemaVersion": interpretation.CANDIDATE_SCHEMA,
        "anchorManifestSha256": interpretation.json_sha256(anchor),
        "translator": _model_receipt("translator", semantic),
        "reviewer": _model_receipt("reviewer", semantic),
        "groups": candidate_groups,
        "humanReview": {
            "humanApproval": False,
            "reviewer": None,
            "reviewedAt": None,
            "reviewedSourceUnitIds": [],
            "englishTranscriptCompleteness": "pending",
            "sentenceAndPauseBoundaries": "pending",
            "translationCompleteness": "pending",
            "naturalSpeechAndPronunciation": "pending",
            "fullPlayback": "pending",
        },
        "tts": {
            "jobPath": str(job_path.resolve()),
            "jobSha256": sha256(job_path),
            "renderIdentitySha256": sha256(render / "identity.json"),
            "renderReportSha256": sha256(render / "report.json"),
            "combinedAudio": {"path": str(combined.resolve()), "sha256": sha256(combined), **combined_probe},
            "decodedAudioFiles": len(receipts) + 1,
            "humanListeningReview": "pending",
        },
    }
    out.mkdir(parents=True, exist_ok=True)
    candidate_path = out / "interpretation-candidate.json"
    write_json(candidate_path, candidate)
    report = interpretation.validate_candidate(anchor, candidate)
    write_json(out / "validation-report.json", report)
    metrics = _metrics(anchor, candidate, report)
    write_json(out / "tts-metrics.json", metrics)
    return candidate, report, metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="Freeze reviewed Chinese into an immutable Qwen TTS job")
    prepare.add_argument("--anchor-manifest", type=Path, required=True)
    prepare.add_argument("--semantic-candidate", type=Path, required=True)
    prepare.add_argument("--checkpoint", type=Path, required=True)
    prepare.add_argument("--out", type=Path, required=True)
    prepare.add_argument("--speaker-key", default="eric_pilot")
    prepare.add_argument("--speaker", default="Eric Geiger")
    finish = sub.add_parser("finalize", help="Full-decode audio and build a measured interpretation candidate")
    finish.add_argument("--anchor-manifest", type=Path, required=True)
    finish.add_argument("--semantic-candidate", type=Path, required=True)
    finish.add_argument("--job", type=Path, required=True)
    finish.add_argument("--render", type=Path, required=True)
    finish.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        job = prepare_job(args.anchor_manifest, args.semantic_candidate, args.checkpoint, args.out,
                          speaker_key=args.speaker_key, speaker=args.speaker)
        print(json.dumps({"job": str(args.out / "job.json"), "units": len(job["units"])}, ensure_ascii=False))
        return 0
    _, report, metrics = finalize(
        args.anchor_manifest, args.semantic_candidate, args.job, args.render, args.out,
    )
    print(json.dumps({
        "candidate": str(args.out / "interpretation-candidate.json"),
        "status": report["status"],
        "maxEndLagSeconds": metrics["rollingSchedule"]["maxEndLagSeconds"],
        "groupsOverLimit": metrics["counts"]["groupsOverLagLimit"],
    }, ensure_ascii=False))
    return 0 if report["candidateReadyForHumanReview"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
