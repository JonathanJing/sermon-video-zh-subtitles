#!/usr/bin/env python3
"""Materialize a verified, audio-only corpus from the selective-audit media cache."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=Path("data/reports/sermon-parallel-corpus-splits-v1/split-manifest.json"),
    )
    parser.add_argument(
        "--caption-source-root",
        type=Path,
        default=Path("data/derived/sermon-caption-source-v1"),
    )
    parser.add_argument(
        "--media-cache",
        type=Path,
        default=Path("data/work/sermon-selective-audio-audit-v1/audio"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/raw/mariners-sermon-training-audio-v1"),
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("data/reports/mariners-sermon-training-audio-v1"),
    )
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=codec_type,codec_name,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    audio = [stream for stream in payload.get("streams", []) if stream.get("codec_type") == "audio"]
    video = [stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video"]
    if len(audio) != 1:
        raise RuntimeError(f"Expected exactly one audio stream in {path}; found {len(audio)}")
    return {
        "durationSeconds": round(float(payload["format"]["duration"]), 3),
        "sizeBytes": int(payload["format"]["size"]),
        "audioCodec": audio[0].get("codec_name"),
        "sampleRate": int(audio[0]["sample_rate"]) if audio[0].get("sample_rate") else None,
        "channels": audio[0].get("channels"),
        "videoStreamCount": len(video),
    }


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def atomic_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def locate_media(media_cache: Path, video_id: str) -> Path:
    matches = sorted(path for path in media_cache.glob(f"{video_id}.*") if path.is_file())
    if len(matches) != 1:
        raise RuntimeError(f"Expected one cached source for {video_id}; found {len(matches)}")
    return matches[0]


def materialize(source: Path, destination: Path, source_probe: dict) -> str:
    if destination.exists():
        return "reused_verified_output"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source_probe["videoStreamCount"] == 0 and source.suffix.lower() == destination.suffix.lower():
        try:
            os.link(source, destination)
            return "hardlinked_audio_only_source"
        except OSError:
            shutil.copy2(source, destination)
            return "copied_audio_only_source"
    temporary = destination.with_name(
        f".{destination.stem}.tmp-{os.getpid()}{destination.suffix}"
    )
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-c:a",
                "copy",
                str(temporary),
            ],
            check=True,
        )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return "remuxed_audio_stream_without_reencoding"


def materialization_method(source: Path, destination: Path, source_probe: dict) -> str:
    if source_probe["videoStreamCount"] != 0:
        return "remuxed_audio_stream_without_reencoding"
    if source.suffix.lower() != destination.suffix.lower():
        return "remuxed_audio_stream_without_reencoding"
    if destination.exists() and source.stat().st_ino == destination.stat().st_ino:
        return "hardlinked_audio_only_source"
    return "copied_audio_only_source"


def main() -> int:
    args = parse_args()
    manifest = read_json(args.split_manifest)
    assignments = [row for row in manifest["assignments"] if row["split"] in {"train", "dev"}]
    rows: list[dict] = []
    missing: list[str] = []
    for assignment in assignments:
        video_id = assignment["videoId"]
        source_report_path = args.caption_source_root / video_id / "run-report.json"
        if not source_report_path.is_file():
            missing.append(video_id)
            continue
        source_report = read_json(source_report_path)
        if source_report.get("sourceQualityDisposition") != "teacher_ready":
            continue
        source = locate_media(args.media_cache, video_id)
        source_info = probe(source)
        suffix = ".m4a" if source_info["audioCodec"] == "aac" else ".webm"
        destination = args.output_root / video_id / f"{video_id}{suffix}"
        action = "planned"
        if args.execute:
            action = materialize(source, destination, source_info)
            output_info = probe(destination)
            if output_info["videoStreamCount"] != 0:
                raise RuntimeError(f"Output unexpectedly contains video: {destination}")
            if output_info["audioCodec"] != source_info["audioCodec"]:
                raise RuntimeError(f"Audio codec changed for {video_id}")
            if abs(output_info["durationSeconds"] - source_info["durationSeconds"]) > 0.25:
                raise RuntimeError(f"Duration mismatch for {video_id}")
        else:
            output_info = None
        rows.append(
            {
                "schemaVersion": "mariners-sermon-training-audio-v1",
                "videoId": video_id,
                "split": assignment["split"],
                "sourceQualityDisposition": "teacher_ready",
                "rightsStatus": assignment.get("rightsStatus", "unconfirmed"),
                "trainingEligibility": "blocked",
                "trainingBlockers": [
                    "source_training_rights_unconfirmed",
                    "gpt_external_student_distillation_not_authorized",
                ],
                "sourcePath": str(source),
                "sourceSha256": sha256(source),
                "source": source_info,
                "outputPath": str(destination),
                "outputSha256": sha256(destination) if args.execute else None,
                "output": output_info,
                "materialization": materialization_method(source, destination, source_info),
                "runAction": action,
                "audioReencoded": False,
            }
        )
    if missing:
        raise RuntimeError(f"Missing caption source reports: {missing}")
    if len(rows) != 133:
        raise RuntimeError(f"Expected 133 teacher-ready sources; found {len(rows)}")
    total_seconds = round(sum((row["output"] or row["source"])["durationSeconds"] for row in rows), 3)
    report = {
        "schemaVersion": "mariners-sermon-training-audio-report-v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "completed_and_verified" if args.execute else "planned",
        "videoCount": len(rows),
        "splitCounts": {
            "train": sum(row["split"] == "train" for row in rows),
            "dev": sum(row["split"] == "dev" for row in rows),
        },
        "durationSeconds": total_seconds,
        "durationHours": round(total_seconds / 3600, 3),
        "outputBytes": sum((row["output"] or {}).get("sizeBytes", 0) for row in rows),
        "audioReencodedCount": 0,
        "outputWithVideoStreamCount": sum((row["output"] or {}).get("videoStreamCount", 0) for row in rows),
        "manifestRowCount": len(rows),
        "sourceReconciliationIncluded": False,
        "testPocIncluded": False,
        "trainingEligibility": "blocked",
        "trainingBlockers": [
            "source_training_rights_unconfirmed",
            "gpt_external_student_distillation_not_authorized",
        ],
    }
    atomic_jsonl(args.report_dir / "manifest.jsonl", rows)
    atomic_json(args.report_dir / "run-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
