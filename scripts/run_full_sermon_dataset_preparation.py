#!/usr/bin/env python3
"""Prepare the full sermon dataset through captions, translation, and selective audio audit.

The runner is deliberately resumable and conservative.  A dry-run plan is the
default.  Billable GPT-Transcribe work is limited to flagged or sampled
segments; shared-Codex Terra/Sol work and ASR require separate confirmations.
No model output is labelled human approved or Gold.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import difflib
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


SCHEMA_VERSION = "sermon-caption-selective-audio-pipeline-v1"
DEFAULT_SPLIT_MANIFEST = Path("data/reports/sermon-parallel-corpus-splits-v1/split-manifest.json")
DEFAULT_RAW_ROOT = Path("data/raw/mariners-sermon-captions-v1")
DEFAULT_EXISTING_SEGMENT_ROOT = Path("data/derived/sermon-parallel-corpus-expansion-v1")
DEFAULT_SOURCE_ROOT = Path("data/derived/sermon-caption-source-v1")
DEFAULT_TEACHER_OUT_ROOT = Path("data/derived/sermon-terra-sol-dataset-preparation-v1")
DEFAULT_WORK_ROOT = Path("data/work/sermon-selective-audio-audit-v1")
DEFAULT_REPORT_DIR = Path("data/reports/sermon-caption-selective-audio-pipeline-v1")
DEFAULT_COLLECTOR_ROOT = Path(
    "/Users/jonathan_jing/SynologyDrive/GitHub/Active/account-video-transcript-collector"
)
DEFAULT_API_KEY_ENV_FILE = DEFAULT_COLLECTOR_ROOT / ".env"
DEFAULT_ASR_MODEL = "gpt-transcribe"
DEFAULT_ASR_PRICE_PER_MINUTE_USD = 0.0045
DEFAULT_AUDIO_AUDIT_SAMPLE_RATE = 0.05
DEFAULT_AUDIO_AUDIT_PADDING_MS = 750
DEFAULT_CAPTION_SPARSE_WORDS_PER_SECOND = 0.6
DEFAULT_MAX_SPARSE_SEGMENT_SHARE = 0.10
DEFAULT_ASR_PROMPT = (
    "English Christian sermon. Transcribe verbatim in English; do not summarize or translate. "
    "Preserve Bible book names, chapter and verse numbers, people, places, negation, repetitions, "
    "and incomplete spoken phrases. Do not invent speech during silence or clipped audio."
)
DEFAULT_SPLITS = ("train", "dev")
SECRET_RE = re.compile(r"(?:sk-|sess-|eyJ)[A-Za-z0-9._-]+")
WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)?")
TERMINAL_RE = re.compile(r"[.!?][\"')\]]*$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def caption_quality_profile(segments: list[dict[str, Any]]) -> dict[str, Any]:
    if not segments:
        raise RuntimeError("Cannot profile an empty caption source")
    total_words = 0
    total_duration_seconds = 0.0
    sparse_segment_count = 0
    for segment in segments:
        duration_seconds = max(
            0.001,
            (int(segment.get("endMs") or 0) - int(segment.get("startMs") or 0)) / 1000,
        )
        word_count = len(WORD_RE.findall(compact(segment.get("en"))))
        total_words += word_count
        total_duration_seconds += duration_seconds
        if word_count / duration_seconds < DEFAULT_CAPTION_SPARSE_WORDS_PER_SECOND:
            sparse_segment_count += 1
    sparse_share = sparse_segment_count / len(segments)
    requires_reconciliation = (
        sparse_segment_count > 0 and sparse_share >= DEFAULT_MAX_SPARSE_SEGMENT_SHARE
    )
    return {
        "overallWordsPerSecond": round(total_words / total_duration_seconds, 4),
        "sparseWordsPerSecondThreshold": DEFAULT_CAPTION_SPARSE_WORDS_PER_SECOND,
        "maxSparseSegmentShare": DEFAULT_MAX_SPARSE_SEGMENT_SHARE,
        "sparseSegmentCount": sparse_segment_count,
        "sparseSegmentShare": round(sparse_share, 4),
        "disposition": (
            "requires_source_reconciliation" if requires_reconciliation else "teacher_ready"
        ),
    }


def require_teacher_ready_source(receipt: dict[str, Any], video_id: str) -> None:
    if receipt.get("sourceQualityDisposition") != "teacher_ready":
        raise RuntimeError(f"{video_id}: caption source requires reconciliation before Terra/Sol")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise RuntimeError(f"Expected JSON object at {path}:{line_number}")
        rows.append(item)
    return rows


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    temporary.replace(path)


def load_assignments(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    rows = payload.get("assignments") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"Split manifest contains no assignments: {path}")
    ids = [str(row.get("videoId") or "") for row in rows]
    if any(not video_id for video_id in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("Split manifest contains empty or duplicate video IDs")
    return rows


def select_assignments(
    rows: list[dict[str, Any]],
    *,
    splits: set[str],
    video_ids: list[str],
    max_videos: int,
) -> list[dict[str, Any]]:
    by_id = {str(row["videoId"]): row for row in rows}
    if video_ids:
        missing = [video_id for video_id in video_ids if video_id not in by_id]
        if missing:
            raise RuntimeError("Unknown video IDs: " + ", ".join(missing))
        selected = [by_id[video_id] for video_id in dict.fromkeys(video_ids)]
        wrong_split = [str(row["videoId"]) for row in selected if str(row.get("split")) not in splits]
        if wrong_split:
            raise RuntimeError("Requested video IDs are outside selected splits: " + ", ".join(wrong_split))
    else:
        selected = [row for row in rows if str(row.get("split")) in splits]
    if max_videos:
        selected = selected[:max_videos]
    return selected


def build_plan(
    rows: list[dict[str, Any]],
    *,
    split_manifest: Path,
    raw_root: Path,
    existing_segment_root: Path,
    calibration_root: Path,
    asr_price_per_minute: float,
    audio_audit_sample_rate: float,
) -> dict[str, Any]:
    duration_seconds = sum(float(row.get("durationSeconds") or 0) for row in rows)
    minutes = duration_seconds / 60
    segment_count = 0
    segment_duration_seconds = 0.0
    preteacher_selected_count = 0
    preteacher_selected_duration_seconds = 0.0
    source_quality_counts: Counter[str] = Counter()
    source_reconciliation_video_ids: list[str] = []
    for row in rows:
        segments, _ = prepare_caption_segments(
            assignment=row,
            raw_root=raw_root,
            existing_segment_root=existing_segment_root,
            segment_limit=0,
        )
        segment_count += len(segments)
        source_quality = caption_quality_profile(segments)
        source_quality_counts[source_quality["disposition"]] += 1
        if source_quality["disposition"] == "requires_source_reconciliation":
            source_reconciliation_video_ids.append(str(row["videoId"]))
        segment_duration_seconds += sum(
            max(0, int(item["endMs"]) - int(item["startMs"])) / 1000 for item in segments
        )
        for item in segments:
            probe = {**item, "severity": "pass", "categories": [], "potentialAsrIssues": []}
            if audio_audit_reasons(probe, sample_rate=audio_audit_sample_rate):
                preteacher_selected_count += 1
                preteacher_selected_duration_seconds += max(
                    0, int(item["endMs"]) - int(item["startMs"])
                ) / 1000

    calibration_rows: list[dict[str, Any]] = []
    if calibration_root.is_dir():
        for path in sorted(calibration_root.glob("*/model-second-pass-audit.jsonl")):
            calibration_rows.extend(read_jsonl(path))
    calibration_counts = Counter(
        str(item.get("severity") or (item.get("result") or {}).get("severity") or "unknown")
        for item in calibration_rows
    )
    calibration_total = sum(calibration_counts.values())
    observed_audio_rate = (
        calibration_counts.get("needs_audio_review", 0) / calibration_total
        if calibration_total
        else 0.15
    )
    preteacher_segment_share = preteacher_selected_count / segment_count if segment_count else 0.0
    preteacher_duration_share = (
        preteacher_selected_duration_seconds / segment_duration_seconds
        if segment_duration_seconds
        else 0.0
    )
    projected_audit_share = (
        preteacher_duration_share + (1 - preteacher_duration_share) * observed_audio_rate
    )
    projected_audit_minutes = segment_duration_seconds / 60 * projected_audit_share
    projected_upper_share = min(1.0, preteacher_duration_share + observed_audio_rate)
    projected_upper_minutes = segment_duration_seconds / 60 * projected_upper_share
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "dry_run_only",
        "selectedVideoCount": len(rows),
        "splitCounts": dict(sorted(Counter(str(row.get("split")) for row in rows).items())),
        "durationHours": round(duration_seconds / 3600, 3),
        "captionSegmentCount": segment_count,
        "captionSegmentDurationHours": round(segment_duration_seconds / 3600, 3),
        "captionSourceQuality": {
            "dispositionCounts": dict(sorted(source_quality_counts.items())),
            "sourceReconciliationVideoIds": source_reconciliation_video_ids,
            "sparseWordsPerSecondThreshold": DEFAULT_CAPTION_SPARSE_WORDS_PER_SECOND,
            "maxSparseSegmentShare": DEFAULT_MAX_SPARSE_SEGMENT_SHARE,
        },
        "selectiveAudioAudit": {
            "calibrationSegmentCount": calibration_total,
            "calibrationSeverityCounts": dict(sorted(calibration_counts.items())),
            "observedNeedsAudioReviewRate": round(observed_audio_rate, 4),
            "passSampleRate": audio_audit_sample_rate,
            "preTeacherSelectedSegmentCount": preteacher_selected_count,
            "preTeacherSelectedMinutes": round(preteacher_selected_duration_seconds / 60, 2),
            "preTeacherSelectedSegmentShare": round(preteacher_segment_share, 4),
            "preTeacherSelectedDurationShare": round(preteacher_duration_share, 4),
            "projectedAuditShare": round(projected_audit_share, 4),
            "projectedAuditMinutes": round(projected_audit_minutes, 2),
            "projectedAsrCostUsd": round(projected_audit_minutes * asr_price_per_minute, 2),
            "projectedUpperAuditShare": round(projected_upper_share, 4),
            "projectedUpperAuditMinutes": round(projected_upper_minutes, 2),
            "projectedUpperAsrCostUsd": round(
                projected_upper_minutes * asr_price_per_minute, 2
            ),
            "postTeacherExactCountPending": True,
        },
        "fullAudioUpperBoundMinutes": round(minutes, 2),
        "fullAudioUpperBoundCostUsd": round(minutes * asr_price_per_minute, 2),
        "asrModel": DEFAULT_ASR_MODEL,
        "asrPricePerMinuteUsdAssumption": asr_price_per_minute,
        "teacherModels": {
            "translator": {"model": "gpt-5.6-terra", "reasoningEffort": "high"},
            "reviewer": {"model": "gpt-5.6-sol", "reasoningEffort": "high"},
        },
        "sourceSplitManifest": str(split_manifest),
        "sourceSplitManifestSha256": sha256_file(split_manifest),
        "trainingEligibility": "blocked",
        "trainingBlockers": [
            "source_training_rights_unconfirmed",
            "gpt_external_student_distillation_not_authorized",
        ],
        "generatedAt": utc_now(),
    }


def load_api_key(env_file: Path | None) -> tuple[str, str]:
    process_value = os.environ.get("OPENAI_API_KEY", "").strip()
    if process_value:
        return process_value, "process_environment"
    if env_file is None or not env_file.is_file():
        raise RuntimeError("No usable OPENAI_API_KEY was found in the process or selected env file")
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() == "OPENAI_API_KEY" and len(value.strip().strip('"').strip("'")) > 8:
            return value.strip().strip('"').strip("'"), "existing_env_file"
    raise RuntimeError("Selected env file does not contain a usable OPENAI_API_KEY")


def require_tools(names: Iterable[str] = ("yt-dlp", "ffmpeg", "ffprobe", "codex")) -> dict[str, str]:
    found: dict[str, str] = {}
    for name in names:
        value = shutil.which(name)
        if not value:
            raise RuntimeError(f"Required executable not found: {name}")
        found[name] = value
    return found


def find_existing_audio(audio_dir: Path, video_id: str) -> Path | None:
    for path in sorted(audio_dir.glob(f"{video_id}.*")):
        if path.is_file() and not path.name.endswith((".part", ".ytdl")):
            return path
    return None


def audio_download_command(
    *,
    yt_dlp: str,
    url: str,
    output_template: Path,
    format_selector: str = "ba/bestaudio",
    extractor_args: str | None = None,
) -> list[str]:
    command = [
        yt_dlp,
        "--ignore-config",
        "--no-cache-dir",
        "--no-playlist",
        "--no-mtime",
        "--continue",
        "-f",
        format_selector,
        "-o",
        str(output_template),
    ]
    if extractor_args:
        command.extend(["--extractor-args", extractor_args])
    command.append(url)
    return command


def download_audio(
    *,
    manifest: dict[str, Any],
    audio_dir: Path,
    yt_dlp: str,
) -> tuple[Path, str]:
    video_id = str(manifest["asset"]["id"])
    existing = find_existing_audio(audio_dir, video_id)
    if existing:
        return existing, "reused"
    audio_dir.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    selectors = (
        ("ba/bestaudio", None, "downloaded_audio_only"),
        # YouTube may require a GVS PO token for separate android_vr audio URLs.
        # Public combined format 18 is the credential-free fallback; ffmpeg reads
        # only its audio stream when making the selective audit clips.
        ("18", None, "downloaded_public_format_18_fallback"),
        # Some older public videos expose combined format 18 to the mobile web
        # client even when the default client returns an expired/forbidden URL.
        (
            "18",
            "youtube:player_client=mweb",
            "downloaded_public_mweb_format_18_fallback",
        ),
        # For embeddable public videos, this client currently exposes ordinary
        # HTTPS audio without account cookies when default android_vr URLs are
        # rejected by GVS enforcement.
        (
            "140/251/ba/bestaudio",
            "youtube:player_client=web_embedded",
            "downloaded_public_web_embedded_fallback",
        ),
    )
    for selector, extractor_args, status in selectors:
        command = audio_download_command(
            yt_dlp=yt_dlp,
            url=str(manifest["asset"]["url"]),
            output_template=audio_dir / f"{video_id}.%(ext)s",
            format_selector=selector,
            extractor_args=extractor_args,
        )
        completed = subprocess.run(
            command, text=True, capture_output=True, check=False, timeout=1800
        )
        downloaded = find_existing_audio(audio_dir, video_id)
        if completed.returncode == 0 and downloaded:
            return downloaded, status
        last_line = (
            completed.stderr.strip().splitlines()[-1]
            if completed.stderr.strip()
            else "yt-dlp failed"
        )
        label = f"{selector} ({extractor_args})" if extractor_args else selector
        failures.append(f"{label}: {SECRET_RE.sub('REDACTED', last_line)}")
    raise RuntimeError("; ".join(failures))


def clip_command(
    *,
    ffmpeg: str,
    audio_path: Path,
    clip_path: Path,
    start_ms: int,
    end_ms: int,
) -> list[str]:
    duration = max(0.001, (end_ms - start_ms) / 1000)
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start_ms / 1000:.3f}",
        "-i",
        str(audio_path),
        "-t",
        f"{duration:.3f}",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "32k",
        str(clip_path),
    ]


def prepare_caption_segments(
    *,
    assignment: dict[str, Any],
    raw_root: Path,
    existing_segment_root: Path,
    segment_limit: int,
) -> tuple[list[dict[str, Any]], str]:
    video_id = str(assignment["videoId"])
    existing_path = existing_segment_root / video_id / "segments.en.jsonl"
    if existing_path.is_file():
        rows = read_jsonl(existing_path)
        origin = "existing_semantic_segments"
    else:
        cues_path = raw_root / video_id / "normalized" / "cues.youtube-auto.jsonl"
        cues = read_jsonl(cues_path)
        rows = build_semantic_segments(
            video_id=video_id,
            cues=cues,
            start_index=0,
            end_index=len(cues) - 1,
            split=str(assignment["split"]),
        )
        origin = "full_video_caption_timeline"
    if segment_limit:
        rows = rows[:segment_limit]
    if not rows:
        raise RuntimeError(f"{video_id}: no caption segments selected")
    return rows, origin


def build_semantic_segments(
    *,
    video_id: str,
    cues: list[dict[str, Any]],
    start_index: int,
    end_index: int,
    split: str,
    preferred_chars: int = 420,
    preferred_ms: int = 24_000,
    hard_chars: int = 840,
    hard_ms: int = 55_000,
) -> list[dict[str, Any]]:
    selected = cues[start_index : end_index + 1]
    segments: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        text = compact(" ".join(str(item.get("text") or "") for item in current))
        segment_id = f"{video_id}_seg_{len(segments) + 1:04d}"
        segments.append(
            {
                "schemaVersion": SCHEMA_VERSION,
                "id": segment_id,
                "sermonId": video_id,
                "split": split,
                "startMs": int(current[0]["startMs"]),
                "endMs": int(current[-1]["endMs"]),
                "cueIds": [str(item["cueId"]) for item in current],
                "en": text,
                "sourceTextSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "sourceCaptionKind": "youtube_automatic",
                "sourceReviewStatus": "unreviewed_raw",
                "prefixOrigin": "historical_youtube_auto_not_real_emissions",
            }
        )
        current.clear()

    for cue in selected:
        current.append(cue)
        text = compact(" ".join(str(item.get("text") or "") for item in current))
        duration_ms = int(current[-1]["endMs"]) - int(current[0]["startMs"])
        at_sentence_end = bool(TERMINAL_RE.search(text))
        preferred = len(text) >= preferred_chars or duration_ms >= preferred_ms
        hard = len(text) >= hard_chars or duration_ms >= hard_ms
        if hard or preferred and at_sentence_end:
            flush()
    flush()
    for index, segment in enumerate(segments):
        segment["previousSegmentId"] = segments[index - 1]["id"] if index else None
        segment["nextSegmentId"] = segments[index + 1]["id"] if index + 1 < len(segments) else None
    return segments


def caption_source_profile(
    *, video_id: str, segment_origin: str, segments: list[dict[str, Any]]
) -> str:
    return stable_hash(
        {
            "videoId": video_id,
            "segmentOrigin": segment_origin,
            "segments": [
                {
                    "id": row["id"],
                    "startMs": row["startMs"],
                    "endMs": row["endMs"],
                    "captionEn": compact(row.get("en")),
                }
                for row in segments
            ],
        }
    )


def materialize_caption_source(
    *,
    assignment: dict[str, Any],
    manifest: dict[str, Any],
    segments: list[dict[str, Any]],
    source_dir: Path,
    segment_origin: str,
) -> dict[str, Any]:
    video_id = str(assignment["videoId"])
    profile = caption_source_profile(
        video_id=video_id, segment_origin=segment_origin, segments=segments
    )
    source_quality = caption_quality_profile(segments)
    report_path = source_dir / "run-report.json"
    if report_path.is_file():
        previous = read_json(report_path)
        previous_profile = previous.get("inputProfileSha256")
        if previous_profile and previous_profile != profile:
            raise RuntimeError(
                f"{video_id}: existing caption source has a different input profile; use a new --source-root"
            )
    rows = []
    for segment in segments:
        caption = compact(segment.get("en"))
        rows.append(
            {
                **segment,
                "schemaVersion": SCHEMA_VERSION,
                "split": str(assignment["split"]),
                "captionEn": caption,
                "en": caption,
                "sourceTextSha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(),
                "sourceCaptionKind": str(assignment.get("captionKind") or "youtube_automatic"),
                "sourceReviewStatus": "youtube_caption_primary_model_unreviewed",
                "segmentOrigin": segment_origin,
                "prefixOrigin": "historical_youtube_auto_not_real_emissions",
                "audioAuditStatus": "not_selected_yet",
                "sourceQualityDisposition": source_quality["disposition"],
            }
        )
    write_jsonl(source_dir / "segments.en.jsonl", rows)
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "caption_source_prepared",
        "videoId": video_id,
        "split": str(assignment["split"]),
        "title": manifest["asset"].get("title"),
        "speaker": assignment.get("speaker"),
        "sourceDurationSeconds": assignment.get("durationSeconds"),
        "captionSegmentCount": len(rows),
        "segmentOrigin": segment_origin,
        "sourceQuality": source_quality,
        "sourceQualityDisposition": source_quality["disposition"],
        "teacherPipelineEligibility": (
            "eligible" if source_quality["disposition"] == "teacher_ready" else "blocked"
        ),
        "inputProfileSha256": profile,
        "sourceSegmentsSha256": sha256_file(source_dir / "segments.en.jsonl"),
        "audioDownloaded": False,
        "gptTranscribeCalled": False,
        "humanApprovalClaimed": False,
        "trainingEligibility": "blocked",
        "trainingBlockers": [
            "source_training_rights_unconfirmed",
            "gpt_external_student_distillation_not_authorized",
        ],
        "generatedAt": utc_now(),
    }
    write_json(report_path, report)
    return report


def prepare_caption_source(
    *, assignment: dict[str, Any], args: argparse.Namespace
) -> dict[str, Any]:
    video_id = str(assignment["videoId"])
    manifest_path = args.raw_root / video_id / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"{video_id}: source manifest is missing")
    manifest = read_json(manifest_path)
    if manifest.get("status") != "ok" or manifest.get("asset", {}).get("visibility") != "public":
        raise RuntimeError(f"{video_id}: source is not verified public/complete")
    segments, segment_origin = prepare_caption_segments(
        assignment=assignment,
        raw_root=args.raw_root,
        existing_segment_root=args.existing_segment_root,
        segment_limit=args.segment_limit,
    )
    return materialize_caption_source(
        assignment=assignment,
        manifest=manifest,
        segments=segments,
        source_dir=args.source_root / video_id,
        segment_origin=segment_origin,
    )


def cut_audio_segments(
    *,
    video_id: str,
    audio_path: Path,
    segments: list[dict[str, Any]],
    clips_dir: Path,
    ffmpeg: str,
    padding_ms: int = 0,
) -> list[dict[str, Any]]:
    clips_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        target_start_ms = int(segment["startMs"])
        target_end_ms = int(segment["endMs"])
        if target_end_ms <= target_start_ms:
            raise RuntimeError(f"{segment['id']}: invalid audio interval")
        start_ms = max(0, target_start_ms - padding_ms)
        end_ms = target_end_ms + padding_ms
        clip_path = clips_dir / f"{segment['id']}.mp3"
        if not clip_path.is_file() or clip_path.stat().st_size == 0:
            completed = subprocess.run(
                clip_command(
                    ffmpeg=ffmpeg,
                    audio_path=audio_path,
                    clip_path=clip_path,
                    start_ms=start_ms,
                    end_ms=end_ms,
                ),
                text=True,
                capture_output=True,
                check=False,
                timeout=180,
            )
            if completed.returncode != 0 or not clip_path.is_file() or clip_path.stat().st_size == 0:
                message = SECRET_RE.sub("REDACTED", completed.stderr[-1000:])
                raise RuntimeError(f"{segment['id']}: ffmpeg clip failed: {message}")
        chunks.append(
            {
                "asset_id": video_id,
                "chunk_index": index,
                "chunk_path": str(clip_path),
                "start_seconds": start_ms / 1000,
                "end_seconds": end_ms / 1000,
                "duration_seconds": (end_ms - start_ms) / 1000,
                "target_start_seconds": target_start_ms / 1000,
                "target_end_seconds": target_end_ms / 1000,
            }
        )
    return chunks


def load_transcribe_module(collector_root: Path) -> Any:
    source_root = collector_root / "src"
    module_path = source_root / "account_video_collector" / "transcribe_openai.py"
    if not module_path.is_file():
        raise RuntimeError(f"Existing transcription module not found: {module_path}")
    source = str(source_root)
    if source not in sys.path:
        sys.path.insert(0, source)
    return importlib.import_module("account_video_collector.transcribe_openai")


def normalized_words(value: str) -> list[str]:
    return [match.group(0).lower().replace("’", "'") for match in WORD_RE.finditer(value)]


def asr_quality(caption: str, transcript: str, duration_seconds: float) -> dict[str, Any]:
    caption_words = normalized_words(caption)
    asr_words = normalized_words(transcript)
    visible = re.findall(r"\S+", transcript)
    english_ratio = len(asr_words) / len(visible) if visible else 0.0
    similarity = difflib.SequenceMatcher(a=caption_words, b=asr_words, autojunk=False).ratio()
    length_ratio = len(asr_words) / max(1, len(caption_words))
    fatal: list[str] = []
    warnings: list[str] = []
    if duration_seconds >= 2 and len(asr_words) < 3:
        fatal.append("asr_text_too_short")
    if english_ratio < 0.55:
        fatal.append("asr_english_ratio_too_low")
    if not 0.35 <= length_ratio <= 3.0:
        fatal.append("asr_caption_length_ratio_outlier")
    if similarity < 0.55:
        warnings.append("caption_asr_disagreement")
    return {
        "status": "excluded" if fatal else ("pass_with_warning" if warnings else "pass"),
        "captionAsrWordSimilarity": round(similarity, 4),
        "asrCaptionWordLengthRatio": round(length_ratio, 4),
        "asrEnglishTokenRatio": round(english_ratio, 4),
        "fatalIssues": fatal,
        "warnings": warnings,
    }


def stable_sample(segment_id: str, rate: float) -> bool:
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    value = int(hashlib.sha256(segment_id.encode("utf-8")).hexdigest()[:16], 16)
    return value / float(0xFFFFFFFFFFFFFFFF) < rate


def audio_audit_reasons(segment: dict[str, Any], *, sample_rate: float) -> list[str]:
    reasons: list[str] = []
    severity = str(segment.get("severity") or "")
    categories = {str(value) for value in (segment.get("categories") or [])}
    if severity == "needs_audio_review":
        reasons.append("sol_needs_audio_review")
    if "source_asr" in categories:
        reasons.append("sol_source_asr_category")
    if segment.get("potentialAsrIssues"):
        reasons.append("terra_potential_asr_issue")

    text = compact(segment.get("captionEn") or segment.get("en"))
    duration = max(0.001, (int(segment.get("endMs") or 0) - int(segment.get("startMs") or 0)) / 1000)
    word_rate = len(normalized_words(text)) / duration
    if word_rate < 0.6 or word_rate > 5.5:
        reasons.append("caption_word_rate_outlier")
    if re.search(r"\[(?:music|applause|laughter)|♪|>>", text, re.IGNORECASE):
        reasons.append("caption_non_speech_or_speaker_marker")
    if not reasons and severity == "pass" and stable_sample(str(segment["id"]), sample_rate):
        reasons.append("deterministic_pass_sample")
    return reasons


def select_audio_audit_segments(
    final_segments: list[dict[str, Any]], *, sample_rate: float
) -> list[dict[str, Any]]:
    selected = []
    for segment in final_segments:
        reasons = audio_audit_reasons(segment, sample_rate=sample_rate)
        if reasons:
            selected.append({**segment, "audioAuditReasons": reasons})
    return selected


def materialize_selective_audio_audit(
    *,
    final_segments: list[dict[str, Any]],
    selected_segments: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    transcript_results: list[Any],
    teacher_dir: Path,
    audio_path: Path,
    asr_model: str,
    credential_source: str,
    input_profile_sha256: str,
) -> dict[str, Any]:
    if len(selected_segments) != len(chunks):
        raise RuntimeError("Selected segment and audio chunk counts differ")
    result_by_index = {int(item.chunk_index): item for item in transcript_results}
    if len(result_by_index) != len(transcript_results):
        raise RuntimeError("Transcription results contain duplicate chunk indexes")
    source_audio_sha256 = sha256_file(audio_path)
    audit_rows: list[dict[str, Any]] = []
    decisions: dict[str, dict[str, Any]] = {}
    for index, (segment, chunk) in enumerate(zip(selected_segments, chunks)):
        result = result_by_index.get(index)
        transcript_path = Path(result.transcript_txt_path) if result is not None else Path()
        transcript = (
            compact(transcript_path.read_text(encoding="utf-8"))
            if result is not None
            and result.status in {"transcribed", "skipped_existing"}
            and transcript_path.is_file()
            else ""
        )
        caption = compact(segment.get("captionEn") or segment.get("en"))
        quality = asr_quality(caption, transcript, float(chunk["duration_seconds"]))
        if result is None or result.status == "failed":
            quality = {
                **quality,
                "status": "excluded",
                "fatalIssues": [*quality["fatalIssues"], "transcription_failed"],
            }
        similarity = float(quality["captionAsrWordSimilarity"])
        if quality["status"] == "excluded":
            decision = "excluded_audio_transcription_invalid"
        elif similarity >= 0.72:
            decision = "audio_evidence_supports_caption"
        else:
            decision = "excluded_caption_asr_disagreement"
        clip_path = Path(chunk["chunk_path"])
        evidence = {
            "sourceAudioSha256": source_audio_sha256,
            "clipSha256": sha256_file(clip_path),
            "targetStartMs": int(segment["startMs"]),
            "targetEndMs": int(segment["endMs"]),
            "clipStartMs": round(float(chunk["start_seconds"]) * 1000),
            "clipEndMs": round(float(chunk["end_seconds"]) * 1000),
            "transcriptionModel": asr_model,
            "transcriptArtifactSha256": sha256_file(transcript_path) if transcript_path.is_file() else None,
            "humanListeningCompleted": False,
        }
        audit = {
            "schemaVersion": SCHEMA_VERSION,
            "segmentId": str(segment["id"]),
            "audioAuditReasons": segment["audioAuditReasons"],
            "captionEn": caption,
            "gptTranscribeEn": transcript,
            "asrQuality": quality,
            "decision": decision,
            "audioEvidence": evidence,
            "humanApprovalClaimed": False,
        }
        audit_rows.append(audit)
        decisions[str(segment["id"])] = audit

    merged: list[dict[str, Any]] = []
    for segment in final_segments:
        audit = decisions.get(str(segment["id"]))
        if audit is None:
            merged.append(
                {
                    **segment,
                    "audioAuditStatus": "not_selected_by_policy",
                    "audioAuditSelectionReasons": [],
                    "reviewStatus": "model_reviewed_not_selected_for_audio",
                    "qualityTier": "model_reviewed_candidate",
                    "datasetCandidateEligibility": "candidate",
                    "trainingEligibility": "blocked",
                    "trainingBlockers": [
                        "source_training_rights_unconfirmed",
                        "gpt_external_student_distillation_not_authorized",
                    ],
                }
            )
            continue
        supported = audit["decision"] == "audio_evidence_supports_caption"
        blockers = [
            "source_training_rights_unconfirmed",
            "gpt_external_student_distillation_not_authorized",
        ]
        if supported:
            merged.append(
                {
                    **segment,
                    "audioAuditStatus": "completed_model_only_supports_caption",
                    "audioAudit": audit,
                    "reviewStatus": "audio_audit_supported_model_candidate",
                    "qualityTier": "model_reviewed_candidate",
                    "datasetCandidateEligibility": "candidate",
                    "trainingEligibility": "blocked",
                    "trainingBlockers": blockers,
                }
            )
        else:
            merged.append(
                {
                    **segment,
                    "audioAuditStatus": audit["decision"],
                    "audioAudit": audit,
                    "reviewStatus": "excluded_requires_source_reconciliation",
                    "qualityTier": "excluded_unresolved_audio",
                    "datasetCandidateEligibility": "excluded",
                    "trainingEligibility": "blocked",
                    "trainingBlockers": [
                        *blockers,
                        (
                            "audio_transcription_invalid_unresolved"
                            if audit["decision"] == "excluded_audio_transcription_invalid"
                            else "caption_asr_disagreement_unresolved"
                        ),
                    ],
                }
            )

    write_jsonl(teacher_dir / "selective-audio-audit.jsonl", audit_rows)
    write_jsonl(teacher_dir / "segments.selective-audio-audited.jsonl", merged)
    decision_counts = Counter(str(item["decision"]) for item in audit_rows)
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "selective_audio_audit_completed",
        "videoId": final_segments[0].get("sermonId") if final_segments else None,
        "selectedSegmentCount": len(selected_segments),
        "totalSegmentCount": len(final_segments),
        "decisionCounts": dict(sorted(decision_counts.items())),
        "inputProfileSha256": input_profile_sha256,
        "asrModel": asr_model,
        "credentialSource": credential_source,
        "apiKeyMaterialIncluded": False,
        "humanApprovalClaimed": False,
        "trainingEligibility": "blocked",
        "generatedAt": utc_now(),
    }
    write_json(teacher_dir / "selective-audio-audit-report.json", report)
    return report


def teacher_command(
    *,
    python: str,
    video_id: str,
    source_root: Path,
    out_root: Path,
    batch_size: int,
    timeout_seconds: int,
) -> list[str]:
    return [
        python,
        str(REPO_ROOT / "scripts" / "run_codex_conversation_sermon_translation.py"),
        f"--video-id={video_id}",
        "--source-root",
        str(source_root),
        "--out-root",
        str(out_root),
        "--translate-model",
        "gpt-5.6-terra",
        "--review-model",
        "gpt-5.6-sol",
        "--translate-reasoning-effort",
        "high",
        "--review-reasoning-effort",
        "high",
        "--segment-limit",
        "0",
        "--batch-size",
        str(batch_size),
        "--timeout-seconds",
        str(timeout_seconds),
        "--confirm-shared-codex-usage",
    ]


def clean_teacher_environment() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    env.pop("CODEX_API_KEY", None)
    return env


def run_teacher(
    *,
    video_id: str,
    source_root: Path,
    out_root: Path,
    batch_size: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    command = teacher_command(
        python=sys.executable,
        video_id=video_id,
        source_root=source_root,
        out_root=out_root,
        batch_size=batch_size,
        timeout_seconds=timeout_seconds,
    )
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        env=clean_teacher_environment(),
    )
    if completed.returncode != 0:
        message = SECRET_RE.sub("REDACTED", completed.stderr[-2000:])
        raise RuntimeError(f"Terra/Sol teacher pipeline failed: {message}")
    report_path = out_root / video_id / "run-report.json"
    if not report_path.is_file():
        raise RuntimeError("Teacher pipeline completed without run-report.json")
    return read_json(report_path)


def process_selective_audio_audit(
    *,
    assignment: dict[str, Any],
    args: argparse.Namespace,
    tools: dict[str, str],
    api_key: str,
    credential_source: str,
) -> dict[str, Any]:
    video_id = str(assignment["videoId"])
    manifest_path = args.raw_root / video_id / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"{video_id}: source manifest is missing")
    manifest = read_json(manifest_path)
    if manifest.get("status") != "ok" or manifest.get("asset", {}).get("visibility") != "public":
        raise RuntimeError(f"{video_id}: source is not verified public/complete")
    teacher_dir = args.teacher_out_root / video_id
    final_path = teacher_dir / "segments.codex.final.jsonl"
    if not final_path.is_file():
        raise RuntimeError(f"{video_id}: Terra/Sol final segments are not prepared")
    final_segments = read_jsonl(final_path)
    selected_segments = select_audio_audit_segments(
        final_segments, sample_rate=args.audio_audit_sample_rate
    )
    input_profile_sha256 = stable_hash(
        {
            "videoId": video_id,
            "asrModel": args.asr_model,
            "asrPrompt": args.asr_prompt,
            "paddingMs": args.audio_audit_padding_ms,
            "sampleRate": args.audio_audit_sample_rate,
            "segments": [
                {
                    "id": row["id"],
                    "startMs": row["startMs"],
                    "endMs": row["endMs"],
                    "captionEn": compact(row.get("captionEn") or row.get("en")),
                    "reasons": row["audioAuditReasons"],
                }
                for row in selected_segments
            ],
        }
    )
    if not selected_segments:
        write_jsonl(teacher_dir / "selective-audio-audit.jsonl", [])
        merged = [
            {
                **segment,
                "audioAuditStatus": "not_selected_by_policy",
                "audioAuditSelectionReasons": [],
                "reviewStatus": "model_reviewed_not_selected_for_audio",
                "qualityTier": "model_reviewed_candidate",
                "datasetCandidateEligibility": "candidate",
                "trainingEligibility": "blocked",
                "trainingBlockers": [
                    "source_training_rights_unconfirmed",
                    "gpt_external_student_distillation_not_authorized",
                ],
            }
            for segment in final_segments
        ]
        write_jsonl(teacher_dir / "segments.selective-audio-audited.jsonl", merged)
        report = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "selective_audio_audit_no_segments_selected",
            "videoId": video_id,
            "selectedSegmentCount": 0,
            "totalSegmentCount": len(final_segments),
            "inputProfileSha256": input_profile_sha256,
            "apiKeyMaterialIncluded": False,
            "humanApprovalClaimed": False,
            "trainingEligibility": "blocked",
            "generatedAt": utc_now(),
        }
        write_json(teacher_dir / "selective-audio-audit-report.json", report)
        return report
    video_work = args.work_root / video_id
    audio_path, _ = download_audio(
        manifest=manifest,
        audio_dir=args.work_root / "audio",
        yt_dlp=tools["yt-dlp"],
    )
    chunks = cut_audio_segments(
        video_id=video_id,
        audio_path=audio_path,
        segments=selected_segments,
        clips_dir=video_work / "profiles" / input_profile_sha256 / "clips",
        ffmpeg=tools["ffmpeg"],
        padding_ms=args.audio_audit_padding_ms,
    )
    profile_work = video_work / "profiles" / input_profile_sha256
    write_jsonl(profile_work / "audio-segments.jsonl", chunks)
    transcriber = load_transcribe_module(args.collector_root)
    transcript_results = transcriber.transcribe_chunks(
        chunks,
        transcripts_dir=profile_work / "transcripts",
        api_key=api_key,
        model=args.asr_model,
        language="en",
        languages=(),
        max_workers=args.asr_workers,
        retries=args.asr_retries,
        prompt=args.asr_prompt,
        keywords=(),
    )
    return materialize_selective_audio_audit(
        final_segments=final_segments,
        selected_segments=selected_segments,
        chunks=chunks,
        transcript_results=transcript_results,
        teacher_dir=teacher_dir,
        audio_path=audio_path,
        asr_model=args.asr_model,
        credential_source=credential_source,
        input_profile_sha256=input_profile_sha256,
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    assignments = load_assignments(args.split_manifest)
    selected = select_assignments(
        assignments,
        splits=set(args.split),
        video_ids=args.video_id,
        max_videos=args.max_videos,
    )
    plan = build_plan(
        selected,
        split_manifest=args.split_manifest,
        raw_root=args.raw_root,
        existing_segment_root=args.existing_segment_root,
        calibration_root=args.calibration_root,
        asr_price_per_minute=args.asr_price_per_minute,
        audio_audit_sample_rate=args.audio_audit_sample_rate,
    )
    args.report_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.report_dir / "latest-plan.json", plan)
    if not args.execute:
        return plan
    if args.max_videos == 0 and not args.video_id and not args.confirm_full_run:
        raise RuntimeError("A full selected-split run requires --confirm-full-run")

    need_caption = args.stage in {"prepare-caption", "all"}
    need_asr = args.stage in {"audio-audit", "all"}
    need_teacher = args.stage in {"translate-review", "all"}
    if need_asr and not args.confirm_billable_asr:
        raise RuntimeError("ASR execution requires --confirm-billable-asr")
    if need_teacher and not args.confirm_shared_codex_usage:
        raise RuntimeError("Teacher execution requires --confirm-shared-codex-usage")

    tool_names: list[str] = ["codex"] if need_teacher else []
    if need_asr:
        tool_names.extend(["yt-dlp", "ffmpeg", "ffprobe"])
    tools = require_tools(tool_names)
    api_key = ""
    credential_source = "not_used"
    if need_asr:
        api_key, credential_source = load_api_key(args.api_key_env_file)

    results: list[dict[str, Any]] = []
    for index, assignment in enumerate(selected, 1):
        video_id = str(assignment["videoId"])
        item: dict[str, Any] = {"videoId": video_id, "split": assignment.get("split")}
        try:
            if need_caption:
                item["captionSource"] = prepare_caption_source(
                    assignment=assignment, args=args
                )
            if need_teacher:
                source_report = args.source_root / video_id / "run-report.json"
                if not source_report.is_file():
                    raise RuntimeError(f"{video_id}: caption English source is not prepared")
                source_receipt = read_json(source_report)
                require_teacher_ready_source(source_receipt, video_id)
                item["teacher"] = run_teacher(
                    video_id=video_id,
                    source_root=args.source_root,
                    out_root=args.teacher_out_root,
                    batch_size=args.teacher_batch_size,
                    timeout_seconds=args.teacher_timeout_seconds,
                )
            if need_asr:
                item["selectiveAudioAudit"] = process_selective_audio_audit(
                    assignment=assignment,
                    args=args,
                    tools=tools,
                    api_key=api_key,
                    credential_source=credential_source,
                )
            item["status"] = "completed"
        except Exception as exc:  # noqa: BLE001 - record and continue the resumable batch.
            item["status"] = "failed"
            item["error"] = SECRET_RE.sub("REDACTED", str(exc))[-2000:]
        results.append(item)
        print(f"dataset progress: {index}/{len(selected)} video={video_id} status={item['status']}", flush=True)

    failed = [item for item in results if item["status"] == "failed"]
    report = {
        **plan,
        "status": "completed" if not failed else "completed_with_failures",
        "stage": args.stage,
        "completedVideoCount": len(results) - len(failed),
        "failedVideoCount": len(failed),
        "results": results,
        "credentialSource": credential_source,
        "apiKeyMaterialIncluded": False,
        "humanApprovalClaimed": False,
        "finishedAt": utc_now(),
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_json(args.report_dir / f"batch-{stamp}.json", report)
    write_json(args.report_dir / "latest.json", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split-manifest", type=Path, default=DEFAULT_SPLIT_MANIFEST)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--existing-segment-root", type=Path, default=DEFAULT_EXISTING_SEGMENT_ROOT)
    parser.add_argument("--calibration-root", type=Path, default=DEFAULT_EXISTING_SEGMENT_ROOT)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--teacher-out-root", type=Path, default=DEFAULT_TEACHER_OUT_ROOT)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--collector-root", type=Path, default=DEFAULT_COLLECTOR_ROOT)
    parser.add_argument("--api-key-env-file", type=Path, default=DEFAULT_API_KEY_ENV_FILE)
    parser.add_argument("--split", action="append", choices=("train", "dev", "test", "poc"), default=[])
    parser.add_argument("--video-id", action="append", default=[])
    parser.add_argument("--max-videos", type=int, default=1, help="0 selects every video in the requested splits")
    parser.add_argument("--segment-limit", type=int, default=0, help="0 processes every segment in each selected video")
    parser.add_argument(
        "--stage",
        choices=("prepare-caption", "translate-review", "audio-audit", "all"),
        default="all",
    )
    parser.add_argument("--asr-model", default=DEFAULT_ASR_MODEL)
    parser.add_argument("--asr-prompt", default=DEFAULT_ASR_PROMPT)
    parser.add_argument("--asr-workers", type=int, default=3)
    parser.add_argument("--asr-retries", type=int, default=3)
    parser.add_argument("--asr-price-per-minute", type=float, default=DEFAULT_ASR_PRICE_PER_MINUTE_USD)
    parser.add_argument(
        "--audio-audit-sample-rate", type=float, default=DEFAULT_AUDIO_AUDIT_SAMPLE_RATE
    )
    parser.add_argument(
        "--audio-audit-padding-ms", type=int, default=DEFAULT_AUDIO_AUDIT_PADDING_MS
    )
    parser.add_argument("--teacher-batch-size", type=int, default=6)
    parser.add_argument("--teacher-timeout-seconds", type=int, default=1200)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-full-run", action="store_true")
    parser.add_argument("--confirm-billable-asr", action="store_true")
    parser.add_argument("--confirm-shared-codex-usage", action="store_true")
    args = parser.parse_args(argv)
    if args.max_videos < 0 or args.segment_limit < 0:
        parser.error("--max-videos and --segment-limit must be non-negative")
    if not 1 <= args.asr_workers <= 8 or not 1 <= args.asr_retries <= 8:
        parser.error("ASR workers/retries must be between 1 and 8")
    if not 1 <= args.teacher_batch_size <= 8:
        parser.error("--teacher-batch-size must be between 1 and 8")
    if args.asr_price_per_minute < 0:
        parser.error("--asr-price-per-minute must be non-negative")
    if not 0 <= args.audio_audit_sample_rate <= 1:
        parser.error("--audio-audit-sample-rate must be between 0 and 1")
    if not 0 <= args.audio_audit_padding_ms <= 5000:
        parser.error("--audio-audit-padding-ms must be between 0 and 5000")
    args.split = args.split or list(DEFAULT_SPLITS)
    for name in (
        "split_manifest",
        "raw_root",
        "existing_segment_root",
        "calibration_root",
        "source_root",
        "teacher_out_root",
        "work_root",
        "report_dir",
        "collector_root",
        "api_key_env_file",
    ):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, resolve(value))
    if not args.split_manifest.is_file():
        parser.error(f"split manifest does not exist: {args.split_manifest}")
    return args


if __name__ == "__main__":
    try:
        print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2, sort_keys=True))
    except Exception as exc:  # noqa: BLE001 - CLI emits a concise, secret-scrubbed failure.
        raise SystemExit(SECRET_RE.sub("REDACTED", str(exc))) from None
