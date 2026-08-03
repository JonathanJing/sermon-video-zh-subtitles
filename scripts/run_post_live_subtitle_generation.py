#!/usr/bin/env python3
"""Run the post-live weekly offline subtitle pipeline from captured live-source state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.cloud import access_secret, read_gcs_bytes, upload_file_to_gcs  # noqa: E402
from backend.observability import log_event, stable_hash, url_summary  # noqa: E402
from scripts import live_source_monitor, post_live_run_status  # noqa: E402


SERMON_PIPELINE_SCRIPT = REPO_ROOT / "scripts" / "sermon_pipeline.py"
MOBILE_PDF_SCRIPT = REPO_ROOT / "scripts" / "render_mobile_pdf_from_srt.py"
READING_EDITION_SCRIPT = REPO_ROOT / "scripts" / "build_sermon_reading_edition_with_openai.py"
REVIEW_PROMPTS_SCRIPT = REPO_ROOT / "scripts" / "review_prompts.py"
DEFAULT_WORK_ROOT = Path("/tmp/sermon-post-live-subtitles")
POST_LIVE_STATES = {"was_live"}
READING_EDITION_DIRNAME = "reading-edition-v2"
INPUT_IDENTITY_SCHEMA_VERSION = 1


def main() -> int:
    args = parse_args()
    try:
        report = run_post_live_generation(args)
    except Exception as exc:
        reconcile_failed_run_status(args, exc)
        raise
    out = resolve_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"completed", "planned", "waiting_for_post_live"} else 2


def reconcile_failed_run_status(args: argparse.Namespace, exc: Exception) -> None:
    try:
        state = live_source_monitor.read_state(args.state_file)
        source = selected_source_from_state(state)
        live_url = live_url_from_state(state, source)
        if not live_url:
            return
        run_root = args.work_root / args.sunday / slug_for(args, live_url)
        path = run_root / "run-status.json"
        payload = load_run_status(path, args.sunday, live_url)
        if payload.get("status") != "running":
            return
        stage = str(payload.get("currentStage") or "source_saved")
        payload = post_live_run_status.mark_terminal(
            payload,
            args.sunday,
            "failed",
            stage=stage,
            reason=f"{exc.__class__.__name__}: {str(exc)[:400]}",
        )
        write_run_status(path, payload)
    except Exception:
        # Never mask the original production failure with reconciliation work.
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sunday", required=True, help="Sunday slice date, YYYY-MM-DD.")
    parser.add_argument("--state-file", required=True, help="live_source_monitor state path or gs:// URI.")
    parser.add_argument("--out", type=Path, default=Path("artifacts/post-live-subtitle-generation/report.json"))
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--slug")
    parser.add_argument("--start-time", help="Absolute sermon start in the full downloaded media.")
    parser.add_argument("--end-time", help="Absolute sermon end in the full downloaded media.")
    parser.add_argument("--sermon-title", help="Operator-confirmed sermon title for the reading PDF.")
    parser.add_argument("--speaker", help="Operator-confirmed sermon speaker for the reading PDF.")
    parser.add_argument(
        "--content-scope",
        choices=("sermon_only", "sermon_plus_response"),
        default=None,
        help="Operator-approved publication scope for the selected time window.",
    )
    parser.add_argument(
        "--approval-evidence",
        type=Path,
        help="Durable operator-window-approval.json already validated by the supervisor.",
    )
    parser.add_argument("--glossary", type=Path)
    parser.add_argument("--zh-model", default="gpt-5.6")
    parser.add_argument("--en-correction-model", default="gpt-5.6")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high"), default="high")
    parser.add_argument(
        "--reference-model",
        "--gpt4o-model",
        dest="reference_model",
        default="gpt-transcribe",
    )
    parser.add_argument("--timing-model", default="whisper-1")
    parser.add_argument(
        "--output-mode",
        choices=("reading", "subtitles"),
        default="reading",
        help="Reading mode skips Whisper and produces the reviewed reading PDF only.",
    )
    parser.add_argument("--reading-edition-provider", choices=("openai", "codex"), default="openai")
    parser.add_argument("--reading-edition-model", default="gpt-5.6-sol")
    parser.add_argument("--reading-edition-reasoning-effort", choices=("low", "medium", "high"), default="high")
    parser.add_argument("--reading-segment-target-chars", type=int, default=420)
    parser.add_argument("--reading-preferred-seconds", type=float, default=24.0)
    parser.add_argument("--reading-preferred-english-chars", type=int, default=420)
    parser.add_argument("--reading-hard-seconds", type=float, default=55.0)
    parser.add_argument("--reading-hard-english-chars", type=int, default=840)
    parser.add_argument("--audio-format", default="bestaudio[ext=m4a]/bestaudio")
    parser.add_argument("--yt-dlp", default="yt-dlp")
    parser.add_argument("--youtube-cookies", type=Path, help="Netscape cookies.txt used only for yt-dlp access.")
    parser.add_argument("--metadata-json", type=Path, help="Use saved yt-dlp metadata instead of probing live.")
    parser.add_argument("--api-key-secret", help="Secret Manager resource for OPENAI_API_KEY.")
    parser.add_argument("--gcs-bucket")
    parser.add_argument("--gcs-prefix", default="sundays")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Do not download media or run OpenAI pipeline.")
    parser.add_argument("--allow-non-post-live", action="store_true")
    return parser.parse_args()


def run_post_live_generation(
    args: argparse.Namespace,
    *,
    metadata_loader: Callable[[str], dict[str, Any] | None] | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, Any]:
    if not hasattr(args, "reference_model"):
        args.reference_model = getattr(args, "gpt4o_model", "gpt-transcribe")
    if not hasattr(args, "output_mode"):
        args.output_mode = "reading"
    if not hasattr(args, "content_scope"):
        args.content_scope = None
    state = live_source_monitor.read_state(args.state_file)
    source = selected_source_from_state(state)
    live_url = live_url_from_state(state, source)
    checked_at = datetime.now(timezone.utc).isoformat()
    base_report = {
        "schemaVersion": 1,
        "status": "waiting_for_source",
        "sunday": args.sunday,
        "checkedAt": checked_at,
        "stateFile": str(args.state_file),
        "source": public_source(source),
        "liveSource": url_summary(live_url) if live_url else None,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }
    if not live_url:
        return {**base_report, "reason": "captured_state_has_no_live_url"}
    if state.get("lastSunday") and state.get("lastSunday") != args.sunday:
        return {
            **base_report,
            "status": "waiting_for_matching_sunday",
            "reason": f"captured state is for {state.get('lastSunday')}",
        }

    metadata = load_metadata(args, live_url, metadata_loader)
    post_live_ready = is_post_live_ready(metadata) or args.allow_non_post_live
    if not post_live_ready:
        report = {
            **base_report,
            "status": "waiting_for_post_live",
            "reason": "live source is not post_live/was_live yet",
            "metadata": safe_metadata(metadata),
        }
        log_post_live_event(report)
        return report

    run_root = args.work_root / args.sunday / slug_for(args, live_url)
    run_status_path = run_root / "run-status.json"
    run_status = load_run_status(run_status_path, args.sunday, live_url)
    run_status = post_live_run_status.update_stage(run_status, args.sunday, "source_saved", "complete")
    run_status = record_approval_stage(run_status, args, live_url=live_url)
    run_status = post_live_run_status.update_stage(run_status, args.sunday, "archive_ready", "complete")
    write_run_status(run_status_path, run_status)
    audio_template = run_root / "download" / "source_audio.%(ext)s"
    pipeline_outdir = run_root / "pipeline"
    reading_outdir = pipeline_outdir / READING_EDITION_DIRNAME
    pipeline_command = build_pipeline_command(args, run_root / "download", pipeline_outdir, live_url)
    mobile_pdf_command = (
        build_mobile_pdf_command(args, pipeline_outdir, live_url, metadata=metadata, source=source)
        if args.output_mode == "subtitles"
        else None
    )
    reading_edition_command = build_reading_edition_command(args, pipeline_outdir)
    reading_pdf_command = build_reading_pdf_command(args, pipeline_outdir, live_url, metadata=metadata, source=source)
    delivery_reading_pdf = pipeline_outdir / delivery_pdf_filename(args, metadata=metadata, source=source)
    report = {
        **base_report,
        "status": "planned" if (args.plan_only or args.dry_run) else "running",
        "metadata": safe_metadata(metadata),
        "downloadTemplate": str(audio_template),
        "pipelineOutdir": str(pipeline_outdir),
        "readingEditionOutdir": str(reading_outdir),
        "pipelineCommand": pipeline_command,
        "mobilePdfCommand": mobile_pdf_command,
        "readingEditionCommand": reading_edition_command,
        "readingPdfCommand": reading_pdf_command,
        "deliveryReadingPdf": str(delivery_reading_pdf),
        "outputMode": args.output_mode,
        "contentScope": args.content_scope or "legacy_unspecified",
        "outputs": expected_outputs(pipeline_outdir, args.output_mode),
    }
    if args.plan_only or args.dry_run:
        log_post_live_event(report)
        return report

    set_openai_api_key(args)
    stage_durations: dict[str, float] = {}
    audio_path = newest_downloaded_audio(audio_template.parent)
    if audio_path:
        stage_durations["downloaded"] = 0.0
    else:
        started = time.monotonic()
        run_status = post_live_run_status.update_stage(run_status, args.sunday, "downloaded", "running")
        write_run_status(run_status_path, run_status)
        audio_path = download_archive_audio(
            live_url,
            audio_template,
            args.audio_format,
            args.yt_dlp,
            runner,
            cookies_path=args.youtube_cookies,
        )
        stage_durations["downloaded"] = time.monotonic() - started
    run_status = post_live_run_status.update_stage(
        run_status, args.sunday, "downloaded", "complete", artifact=str(audio_path),
        duration_seconds=stage_durations["downloaded"],
    )
    write_run_status(run_status_path, run_status)
    pipeline_command = build_pipeline_command(args, audio_path.parent, pipeline_outdir, live_url, audio_path=audio_path)
    pipeline_input_identity = build_pipeline_input_identity(args, audio_path)
    pipeline_input_fingerprint = stable_payload_hash(pipeline_input_identity)
    mobile_pdf_command = (
        build_mobile_pdf_command(args, pipeline_outdir, live_url, metadata=metadata, source=source)
        if args.output_mode == "subtitles"
        else None
    )
    reading_edition_command = build_reading_edition_command(args, pipeline_outdir)
    reading_pdf_command = build_reading_pdf_command(args, pipeline_outdir, live_url, metadata=metadata, source=source)
    delivery_reading_pdf = pipeline_outdir / delivery_pdf_filename(args, metadata=metadata, source=source)
    core_outputs = (
        ("sermon_zh_relative.srt", "sermon_en_relative.srt", "summary.json")
        if args.output_mode == "subtitles"
        else ("segments_timed_en_corrected.json", "segments_timed_zh.json", "summary.json")
    )
    core_ready = all((pipeline_outdir / name).exists() for name in core_outputs) and pipeline_summary_matches(
        pipeline_outdir / "summary.json",
        output_mode=args.output_mode,
        reference_model=args.reference_model,
        reading_segment_target_chars=getattr(args, "reading_segment_target_chars", 420),
        expected_input_fingerprint=pipeline_input_fingerprint,
    )
    if core_ready:
        stage_durations["pipeline"] = 0.0
    else:
        started = time.monotonic()
        run_command(pipeline_command, runner)
        record_input_identity(
            pipeline_outdir / "summary.json",
            fingerprint_key="pipelineInputFingerprint",
            identity_key="pipelineInputIdentity",
            identity=pipeline_input_identity,
        )
        stage_durations["pipeline"] = time.monotonic() - started
    for stage in ("clipped", "transcribed", "translated"):
        run_status = post_live_run_status.update_stage(
            run_status, args.sunday, stage, "complete", duration_seconds=stage_durations["pipeline"]
        )
    write_run_status(run_status_path, run_status)
    if mobile_pdf_command:
        started = time.monotonic()
        run_command(mobile_pdf_command, runner)
        stage_durations["mobile_pdf"] = time.monotonic() - started
    else:
        stage_durations["mobile_pdf"] = 0.0
    reading_report_path = reading_outdir / "reading_quality_report.json"
    reading_input_identity = build_reading_input_identity(
        args,
        pipeline_outdir,
        pipeline_input_fingerprint=pipeline_input_fingerprint,
    )
    reading_input_fingerprint = stable_payload_hash(reading_input_identity)
    reading_ready = all(
        path.exists()
        for path in (
            reading_outdir / "sermon_zh_reading_revised.srt",
            reading_outdir / "sermon_en_reading_revised.srt",
            reading_report_path,
        )
    ) and reading_report_matches_inputs(
        reading_report_path,
        args,
        expected_input_fingerprint=reading_input_fingerprint,
    )
    if reading_ready:
        stage_durations["reviewed"] = 0.0
    else:
        started = time.monotonic()
        run_status = post_live_run_status.update_stage(run_status, args.sunday, "reviewed", "running")
        write_run_status(run_status_path, run_status)
        run_command(reading_edition_command, runner)
        record_input_identity(
            reading_report_path,
            fingerprint_key="readingInputFingerprint",
            identity_key="readingInputIdentity",
            identity=reading_input_identity,
        )
        stage_durations["reviewed"] = time.monotonic() - started
    reading_report = json.loads(reading_report_path.read_text(encoding="utf-8"))
    if reading_report.get("status") != "pass":
        run_status = post_live_run_status.update_stage(
            run_status,
            args.sunday,
            "reviewed",
            "blocked",
            reason="reading_quality_needs_review",
            artifact=str(reading_report_path),
            duration_seconds=stage_durations["reviewed"],
        )
        write_run_status(run_status_path, run_status)
        raise RuntimeError("Reading edition quality report did not pass; inspect reading_quality_report.json")
    run_status = post_live_run_status.update_stage(
        run_status,
        args.sunday,
        "reviewed",
        "complete",
        artifact=str(reading_report_path),
        duration_seconds=stage_durations["reviewed"],
    )
    write_run_status(run_status_path, run_status)
    started = time.monotonic()
    run_command(reading_pdf_command, runner)
    stage_durations["reading_pdf"] = time.monotonic() - started
    stage_durations["pdf_qa"] = stage_durations["mobile_pdf"] + stage_durations["reading_pdf"]
    qa_paths = [pipeline_outdir / "sermon_zh_en_reading.qa.json"]
    if args.output_mode == "subtitles":
        qa_paths.insert(0, pipeline_outdir / "sermon_zh_mobile.qa.json")
    qa_reports = [json.loads(path.read_text(encoding="utf-8")) for path in qa_paths]
    if any(report.get("status") != "pass" for report in qa_reports):
        run_status = post_live_run_status.update_stage(
            run_status, args.sunday, "pdf_qa", "blocked", reason="pdf_qa_needs_review",
            duration_seconds=stage_durations["pdf_qa"],
        )
        write_run_status(run_status_path, run_status)
        raise RuntimeError("PDF QA did not pass; inspect the generated *.qa.json reports")
    delivery_paths = create_delivery_pdf_copy(
        pipeline_outdir / "sermon_zh_en_reading.pdf",
        delivery_reading_pdf,
    )
    report["outputs"] = [*report["outputs"], *(str(path) for path in delivery_paths)]
    run_status = post_live_run_status.update_stage(
        run_status, args.sunday, "pdf_qa", "complete",
        artifact=str(pipeline_outdir / "sermon_zh_en_reading.qa.json"),
        duration_seconds=stage_durations["pdf_qa"],
    )
    write_run_status(run_status_path, run_status)
    run_status = post_live_run_status.update_stage(
        run_status,
        args.sunday,
        "publication",
        "running",
    )
    write_run_status(run_status_path, run_status)
    uploaded = upload_outputs(args, pipeline_outdir, args.output_mode, extra_paths=delivery_paths)
    publication = publication_report(uploaded, gcs_configured=bool(args.gcs_bucket))
    if publication["status"] not in {"pass", "not_configured"}:
        raise RuntimeError("Published artifact hashes did not match local outputs")
    run_status = post_live_run_status.update_stage(
        run_status,
        args.sunday,
        "publication",
        "complete",
    )
    run_status = post_live_run_status.mark_terminal(
        run_status,
        args.sunday,
        "complete",
        stage="publication",
    )
    write_run_status(run_status_path, run_status)
    report.update(
        {
            "status": "completed",
            "downloadedAudio": str(audio_path),
            "pipelineCommand": pipeline_command,
            "mobilePdfCommand": mobile_pdf_command,
            "readingEditionCommand": reading_edition_command,
            "readingPdfCommand": reading_pdf_command,
            "deliveryReadingPdf": str(delivery_reading_pdf),
            "readingQualityReport": str(reading_report_path),
            "pipelineInputFingerprint": pipeline_input_fingerprint,
            "readingInputFingerprint": reading_input_fingerprint,
            "uploaded": uploaded,
            "publication": publication,
            "runStatus": str(run_status_path),
            "stageDurationsSeconds": {key: round(value, 3) for key, value in stage_durations.items()},
            "retryCounts": {
                stage: max(0, int(data.get("attempts") or 0) - 1)
                for stage, data in run_status.get("stages", {}).items()
            },
            "completedAt": datetime.now(timezone.utc).isoformat(),
        }
    )
    log_post_live_event(report)
    return report


def selected_source_from_state(state: dict[str, Any]) -> dict[str, Any]:
    source = state.get("lastSelectedSource")
    return source if isinstance(source, dict) else {}


def live_url_from_state(state: dict[str, Any], source: dict[str, Any]) -> str | None:
    request = state.get("lastGenerationRequest")
    if isinstance(request, dict) and request.get("liveUrl"):
        return str(request["liveUrl"])
    if source.get("url"):
        return str(source["url"])
    return None


def public_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": source.get("kind"),
        "service": source.get("service"),
        "state": source.get("state"),
        "title": source.get("title"),
        "urlHash": source.get("urlHash"),
        "actualStartAt": source.get("actualStartAt"),
    }


def load_metadata(
    args: argparse.Namespace,
    live_url: str,
    metadata_loader: Callable[[str], dict[str, Any] | None] | None,
) -> dict[str, Any] | None:
    if args.metadata_json:
        return json.loads(resolve_path(args.metadata_json).read_text(encoding="utf-8"))
    if metadata_loader:
        return metadata_loader(live_url)
    return live_source_monitor.youtube_video_metadata(live_url)


def is_post_live_ready(metadata: dict[str, Any] | None) -> bool:
    if not metadata:
        return False
    return live_source_monitor.state_from_youtube_metadata(metadata) in POST_LIVE_STATES


def safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not metadata:
        return None
    keys = [
        "id",
        "title",
        "sermon_title",
        "sermonTitle",
        "message_title",
        "messageTitle",
        "speaker",
        "preacher",
        "sermon_speaker",
        "sermonSpeaker",
        "live_status",
        "media_type",
        "availability",
        "is_live",
        "was_live",
        "release_timestamp",
        "timestamp",
        "duration",
        "webpage_url",
        "actual_start_time",
        "actual_end_time",
        "scheduled_start_time",
        "metadata_provider",
    ]
    return {key: metadata.get(key) for key in keys if key in metadata}


def slug_for(args: argparse.Namespace, live_url: str) -> str:
    if args.slug:
        return args.slug
    video_id = live_url.rstrip("/").split("v=")[-1].split("&")[0]
    return f"sermon_{video_id}" if video_id else "sermon"


def build_pipeline_command(
    args: argparse.Namespace,
    download_dir: Path,
    pipeline_outdir: Path,
    live_url: str,
    *,
    audio_path: Path | None = None,
) -> list[str]:
    input_path = audio_path or download_dir / "source_audio.m4a"
    command = [
        sys.executable,
        str(SERMON_PIPELINE_SCRIPT),
        "--input",
        str(input_path),
        "--start-time",
        args.start_time or "00:00:00",
        "--slug",
        slug_for(args, live_url),
        "--outdir",
        str(pipeline_outdir),
        "--reference-model",
        args.reference_model,
        "--output-mode",
        args.output_mode,
        "--en-correction-model",
        args.en_correction_model,
        "--zh-model",
        args.zh_model,
        "--reasoning-effort",
        args.reasoning_effort,
    ]
    if args.output_mode == "subtitles":
        command.extend(["--timing-model", args.timing_model])
    else:
        command.extend(
            [
                "--reading-segment-target-chars",
                str(getattr(args, "reading_segment_target_chars", 420)),
            ]
        )
    if args.end_time:
        command.extend(["--end-time", args.end_time])
    if args.glossary:
        command.extend(["--glossary", str(args.glossary)])
    return command


def build_mobile_pdf_command(
    args: argparse.Namespace,
    pipeline_outdir: Path,
    live_url: str,
    *,
    metadata: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
) -> list[str]:
    sermon_title, speaker = reading_pdf_metadata(args, metadata=metadata, source=source)
    return [
        sys.executable,
        str(MOBILE_PDF_SCRIPT),
        "--input",
        str(pipeline_outdir / "sermon_zh_relative.srt"),
        "--secondary-input",
        str(pipeline_outdir / "sermon_en_relative.srt"),
        "--out",
        str(pipeline_outdir / "sermon_zh_mobile.pdf"),
        "--title",
        sermon_title,
        "--subtitle",
        "逐句中英字幕版",
        "--sermon-date",
        args.sunday,
        "--sermon-window",
        sermon_window_label(args),
        "--source-url",
        live_url,
        "--source-offset-seconds",
        str(timecode_to_seconds(args.start_time or "00:00:00")),
        *([] if not speaker else ["--speaker", speaker]),
    ]


def build_reading_edition_command(
    args: argparse.Namespace,
    pipeline_outdir: Path,
) -> list[str]:
    return [
        sys.executable,
        str(READING_EDITION_SCRIPT),
        "--source-pipeline",
        str(pipeline_outdir),
        "--outdir",
        str(pipeline_outdir / READING_EDITION_DIRNAME),
        "--provider",
        args.reading_edition_provider,
        "--model",
        args.reading_edition_model,
        "--reasoning-effort",
        args.reading_edition_reasoning_effort,
        "--passes",
        "2",
        "--preferred-seconds",
        str(getattr(args, "reading_preferred_seconds", 24.0)),
        "--preferred-english-chars",
        str(getattr(args, "reading_preferred_english_chars", 420)),
        "--hard-seconds",
        str(getattr(args, "reading_hard_seconds", 55.0)),
        "--hard-english-chars",
        str(getattr(args, "reading_hard_english_chars", 840)),
    ]


def build_reading_pdf_command(
    args: argparse.Namespace,
    pipeline_outdir: Path,
    live_url: str,
    *,
    metadata: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
) -> list[str]:
    sermon_title, speaker = reading_pdf_metadata(args, metadata=metadata, source=source)
    return [
        sys.executable,
        str(MOBILE_PDF_SCRIPT),
        "--layout",
        "reading",
        "--input",
        str(pipeline_outdir / READING_EDITION_DIRNAME / "sermon_zh_reading_revised.srt"),
        "--secondary-input",
        str(pipeline_outdir / READING_EDITION_DIRNAME / "sermon_en_reading_revised.srt"),
        "--out",
        str(pipeline_outdir / "sermon_zh_en_reading.pdf"),
        "--title",
        sermon_title,
        "--subtitle",
        "中英对照阅读版",
        "--sermon-date",
        args.sunday,
        "--sermon-window",
        sermon_window_label(args),
        "--source-url",
        live_url,
        "--source-offset-seconds",
        str(timecode_to_seconds(args.start_time or "00:00:00")),
        *([] if not speaker else ["--speaker", speaker]),
    ]


def mobile_pdf_title(
    args: argparse.Namespace,
    live_url: str,
    *,
    metadata: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
) -> str:
    return reading_pdf_metadata(args, metadata=metadata, source=source)[0]


def reading_pdf_metadata(
    args: argparse.Namespace,
    *,
    metadata: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
) -> tuple[str, str | None]:
    explicit_title = str(getattr(args, "sermon_title", "") or "").strip()
    explicit_speaker = str(getattr(args, "speaker", "") or "").strip()
    structured_title = ""
    structured_speaker = ""

    for payload in (metadata or {}, source or {}):
        for key in ("sermon_title", "sermonTitle", "message_title", "messageTitle"):
            candidate = payload.get(key)
            if isinstance(candidate, str) and candidate.strip():
                structured_title = candidate.strip()
                break
        for key in ("speaker", "preacher", "sermon_speaker", "sermonSpeaker"):
            candidate = payload.get(key)
            if isinstance(candidate, str) and candidate.strip():
                structured_speaker = candidate.strip()
                break
        if structured_title:
            break

    published_title = str((metadata or {}).get("title") or "").strip()
    parsed_title, parsed_speaker = parse_published_sermon_title(published_title)
    title = explicit_title or structured_title or parsed_title
    speaker = explicit_speaker or structured_speaker or parsed_speaker or None
    if not title:
        title = "主日证道"
    return title, speaker


def parse_published_sermon_title(value: str) -> tuple[str, str]:
    title = value.strip()
    if not title or is_generic_service_title(title):
        return "", ""
    match = re.match(r"^(?P<title>.+?)\s+-\s+(?P<speaker>[^|]+?)\s*\|\s*Mariners Church\s*$", title, re.I)
    if match:
        return match.group("title").strip(), match.group("speaker").strip()
    return title, ""


def is_generic_service_title(value: str) -> bool:
    normalized = value.lower()
    generic_markers = (
        "worship service",
        "join us now",
        "mariners online",
        "live service",
        "sunday service",
        "saturday service",
        "manual authorized source",
        "已捕获直播链接",
    )
    return any(marker in normalized for marker in generic_markers)


def sermon_window_label(args: argparse.Namespace) -> str:
    start = str(getattr(args, "start_time", "") or "").strip()
    end = str(getattr(args, "end_time", "") or "").strip()
    if start and end:
        return f"{start}-{end}"
    return start or end


def delivery_pdf_filename(
    args: argparse.Namespace,
    *,
    metadata: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
) -> str:
    title, speaker = reading_pdf_metadata(args, metadata=metadata, source=source)
    components = [
        args.sunday,
        filename_component(title),
        filename_component(speaker) if speaker else "",
        "中英对照阅读版",
    ]
    return "-".join(component for component in components if component) + ".pdf"


def filename_component(value: str, *, max_length: int = 72) -> str:
    cleaned = re.sub(r"[^\w\u3400-\u9fff]+", "-", value, flags=re.UNICODE).strip("-_")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned[:max_length].rstrip("-") or "sermon"


def timecode_to_seconds(value: str) -> float:
    parts = [float(part) for part in value.strip().split(":")]
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours = 0.0
        minutes, seconds = parts
    else:
        raise ValueError(f"Expected HH:MM:SS or MM:SS timecode, got {value!r}")
    return hours * 3600 + minutes * 60 + seconds


def download_archive_audio(
    live_url: str,
    output_template: Path,
    audio_format: str,
    yt_dlp: str,
    runner: Callable[..., subprocess.CompletedProcess],
    *,
    cookies_path: Path | None = None,
) -> Path:
    output_template.parent.mkdir(parents=True, exist_ok=True)
    command = [
        yt_dlp,
        "--no-playlist",
        "--js-runtimes",
        "node",
        "-f",
        audio_format,
        "-o",
        str(output_template),
    ]
    if cookies_path:
        command.extend(["--cookies", str(cookies_path)])
    command.append(live_url)
    run_command(command, runner)
    files = sorted(output_template.parent.glob("source_audio.*"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError("yt-dlp completed but no source_audio.* file was created")
    return files[0]


def newest_downloaded_audio(download_dir: Path) -> Path | None:
    files = sorted(
        (
            path
            for path in download_dir.glob("source_audio.*")
            if path.is_file() and path.suffix not in {".part", ".ytdl"}
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def load_run_status(path: Path, sunday: str, live_url: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("sunday") == sunday:
            return payload
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return post_live_run_status.new_status(sunday, source_url=live_url)


def record_approval_stage(
    run_status: dict[str, Any],
    args: argparse.Namespace,
    *,
    live_url: str,
) -> dict[str, Any]:
    evidence_path = getattr(args, "approval_evidence", None)
    if evidence_path is None:
        return run_status
    path = resolve_path(evidence_path)
    try:
        approval = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Cannot read validated approval evidence: {exc}") from exc
    valid = bool(
        isinstance(approval, dict)
        and approval.get("status") == "approved"
        and approval.get("humanApproval") is True
        and approval.get("sunday") == args.sunday
        and approval.get("sourceUrlHash") == stable_hash(live_url)
        and approval.get("contentScope") == getattr(args, "content_scope", None)
        and approval.get("startTime") == getattr(args, "start_time", None)
        and approval.get("endTime") == getattr(args, "end_time", None)
    )
    if not valid:
        raise RuntimeError("Validated approval evidence does not match generation arguments")
    return post_live_run_status.update_stage(
        run_status,
        args.sunday,
        "approval",
        "complete",
        artifact=str(path),
    )


def write_run_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def pipeline_summary_matches(
    path: Path,
    *,
    output_mode: str,
    reference_model: str,
    reading_segment_target_chars: int = 420,
    expected_input_fingerprint: str | None = None,
) -> bool:
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    models = summary.get("models") if isinstance(summary, dict) else None
    matches = (
        summary.get("outputMode") == output_mode
        and isinstance(models, dict)
        and models.get("referenceAsr") == reference_model
    )
    if output_mode == "reading":
        matches = matches and summary.get("readingSegmentTargetCharacters") == max(
            120, int(reading_segment_target_chars)
        )
    if expected_input_fingerprint is not None:
        matches = matches and summary.get("pipelineInputFingerprint") == expected_input_fingerprint
    return matches


def reading_layout_targets(args: argparse.Namespace) -> dict[str, float | int]:
    return {
        "preferredSeconds": float(getattr(args, "reading_preferred_seconds", 24.0)),
        "preferredEnglishCharacters": int(getattr(args, "reading_preferred_english_chars", 420)),
        "hardSeconds": float(getattr(args, "reading_hard_seconds", 55.0)),
        "hardEnglishCharacters": int(getattr(args, "reading_hard_english_chars", 840)),
        "targetBilingualBlocksPerMobilePage": 2,
    }


def reading_report_matches_inputs(
    path: Path,
    args: argparse.Namespace,
    *,
    expected_input_fingerprint: str | None = None,
) -> bool:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    matches = report.get("status") == "pass" and report.get("layoutTargets") == reading_layout_targets(args)
    if expected_input_fingerprint is not None:
        matches = matches and report.get("readingInputFingerprint") == expected_input_fingerprint
    return matches


def file_content_identity(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        return {"exists": False}
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return {"exists": False}
    return {
        "exists": True,
        "sizeBytes": stat.st_size,
        "sha256": digest.hexdigest(),
    }


def build_pipeline_input_identity(args: argparse.Namespace, audio_path: Path) -> dict[str, Any]:
    return {
        "schemaVersion": INPUT_IDENTITY_SCHEMA_VERSION,
        "sourceAudio": file_content_identity(audio_path),
        "sermonWindow": {
            "startTime": args.start_time or "00:00:00",
            "endTime": args.end_time,
        },
        "glossary": file_content_identity(args.glossary),
        "outputMode": args.output_mode,
        "models": {
            "referenceAsr": args.reference_model,
            "timingAsr": args.timing_model if args.output_mode == "subtitles" else None,
            "englishCorrection": args.en_correction_model,
            "chineseTranslation": args.zh_model,
            "reasoningEffort": args.reasoning_effort,
        },
        "readingSegmentTargetCharacters": (
            max(120, int(getattr(args, "reading_segment_target_chars", 420)))
            if args.output_mode == "reading"
            else None
        ),
        "implementation": {
            "sermonPipeline": file_content_identity(SERMON_PIPELINE_SCRIPT),
            "reviewPrompts": file_content_identity(REVIEW_PROMPTS_SCRIPT),
        },
    }


def build_reading_input_identity(
    args: argparse.Namespace,
    pipeline_outdir: Path,
    *,
    pipeline_input_fingerprint: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": INPUT_IDENTITY_SCHEMA_VERSION,
        "pipelineInputFingerprint": pipeline_input_fingerprint,
        "sourceArtifacts": {
            "englishCorrected": file_content_identity(pipeline_outdir / "segments_timed_en_corrected.json"),
            "chineseDraft": file_content_identity(pipeline_outdir / "segments_timed_zh.json"),
        },
        "editing": {
            "provider": args.reading_edition_provider,
            "model": args.reading_edition_model,
            "reasoningEffort": args.reading_edition_reasoning_effort,
            "passes": 2,
        },
        "layoutTargets": reading_layout_targets(args),
        "implementation": {
            "readingEdition": file_content_identity(READING_EDITION_SCRIPT),
        },
    }


def stable_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_input_identity(
    path: Path,
    *,
    fingerprint_key: str,
    identity_key: str,
    identity: dict[str, Any],
) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Cannot record input identity in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Cannot record input identity in non-object JSON: {path}")
    payload[fingerprint_key] = stable_payload_hash(identity)
    payload[identity_key] = identity
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def run_command(command: list[str], runner: Callable[..., subprocess.CompletedProcess]) -> None:
    runner(command, check=True)


def set_openai_api_key(args: argparse.Namespace) -> None:
    if os.environ.get("OPENAI_API_KEY"):
        return
    if not args.api_key_secret:
        return
    os.environ["OPENAI_API_KEY"] = access_secret(args.api_key_secret)


def expected_outputs(pipeline_outdir: Path, output_mode: str = "reading") -> list[str]:
    outputs = [
        str(pipeline_outdir / "sermon_zh_en_reading.pdf"),
        str(pipeline_outdir / "sermon_zh_en_reading.qa.json"),
        str(pipeline_outdir / READING_EDITION_DIRNAME / "reading_quality_report.json"),
        str(pipeline_outdir / READING_EDITION_DIRNAME / "sermon_zh_reading_revised.srt"),
        str(pipeline_outdir / READING_EDITION_DIRNAME / "sermon_en_reading_revised.srt"),
        str(pipeline_outdir / "asr_reference.json"),
        str(pipeline_outdir / "asr_reference_chunks.json"),
        str(pipeline_outdir / "segments_timed_en_corrected.json"),
        str(pipeline_outdir / "segments_timed_zh.json"),
        str(pipeline_outdir / "qa_report.json"),
        str(pipeline_outdir / "summary.json"),
    ]
    if output_mode == "subtitles":
        outputs.extend(
            [
                str(pipeline_outdir / "sermon_zh_relative.srt"),
                str(pipeline_outdir / "sermon_zh_relative.vtt"),
                str(pipeline_outdir / "sermon_zh_mobile.pdf"),
                str(pipeline_outdir / "sermon_zh_mobile.qa.json"),
                str(pipeline_outdir / "full_video_zh_from_sermon.srt"),
                str(pipeline_outdir / "full_video_zh_from_sermon.vtt"),
            ]
        )
    return outputs


def create_delivery_pdf_copy(source_pdf: Path, delivery_pdf: Path) -> list[Path]:
    delivery_pdf.parent.mkdir(parents=True, exist_ok=True)
    paths = [delivery_pdf]
    if source_pdf.resolve() != delivery_pdf.resolve():
        shutil.copy2(source_pdf, delivery_pdf)
    source_qa = source_pdf.with_suffix(".qa.json")
    delivery_qa = delivery_pdf.with_suffix(".qa.json")
    if source_qa.exists():
        if source_qa.resolve() != delivery_qa.resolve():
            shutil.copy2(source_qa, delivery_qa)
        paths.append(delivery_qa)
    return paths


def upload_outputs(
    args: argparse.Namespace,
    pipeline_outdir: Path,
    output_mode: str = "reading",
    *,
    extra_paths: list[Path] | None = None,
    uploader: Callable[[str | Path, str], None] | None = None,
    gcs_reader: Callable[[str], bytes] | None = None,
) -> list[dict[str, Any]]:
    if not args.gcs_bucket:
        return []
    uploader = uploader or upload_file_to_gcs
    gcs_reader = gcs_reader or read_gcs_bytes
    slug = args.slug or "sermon"
    prefix = "/".join(part.strip("/") for part in [args.gcs_prefix, args.sunday, "post-live-subtitles", slug] if part)
    uploaded = []
    paths = [Path(path_text) for path_text in expected_outputs(pipeline_outdir, output_mode)]
    paths.extend(extra_paths or [])
    for path in dict.fromkeys(paths):
        if not path.exists():
            continue
        try:
            relative = path.relative_to(pipeline_outdir)
        except ValueError:
            relative = Path(path.name)
        destination = f"gs://{args.gcs_bucket}/{prefix}/pipeline/{relative.as_posix()}"
        local_bytes = path.read_bytes()
        local_sha256 = hashlib.sha256(local_bytes).hexdigest()
        uploader(path, destination)
        remote_bytes = gcs_reader(destination)
        remote_sha256 = hashlib.sha256(remote_bytes).hexdigest()
        if len(local_bytes) != len(remote_bytes) or local_sha256 != remote_sha256:
            raise RuntimeError(f"GCS upload verification failed for {destination}")
        uploaded.append(
            {
                "localPath": str(path),
                "gcsUri": destination,
                "sizeBytes": len(local_bytes),
                "localSize": len(local_bytes),
                "gcsSize": len(remote_bytes),
                "localSha256": local_sha256,
                "gcsSha256": remote_sha256,
                "status": "pass",
            }
        )
    return uploaded


def publication_report(
    uploaded: list[dict[str, Any]],
    *,
    gcs_configured: bool,
) -> dict[str, Any]:
    if not gcs_configured:
        return {"status": "not_configured", "artifactCount": 0}
    passed = bool(uploaded) and all(item.get("status") == "pass" for item in uploaded)
    return {
        "status": "pass" if passed else "failed",
        "artifactCount": len(uploaded),
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "artifacts": uploaded,
    }


def log_post_live_event(report: dict[str, Any]) -> None:
    log_event(
        "post_live_subtitle_generation_checked",
        component="post-live-subtitles",
        sunday=report.get("sunday"),
        status=report.get("status"),
        liveSource=report.get("liveSource"),
        pipelineOutdir=report.get("pipelineOutdir"),
    )


def resolve_path(path: Path | str) -> Path:
    value = Path(path)
    return value if value.is_absolute() else REPO_ROOT / value


if __name__ == "__main__":
    raise SystemExit(main())
