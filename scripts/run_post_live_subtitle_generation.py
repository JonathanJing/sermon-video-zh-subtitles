#!/usr/bin/env python3
"""Run the post-live weekly offline subtitle pipeline from captured live-source state."""

from __future__ import annotations

import argparse
import concurrent.futures
from contextvars import copy_context
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.cloud import access_secret, read_gcs_bytes, upload_file_to_gcs  # noqa: E402
from backend.observability import log_event, stable_hash, url_summary  # noqa: E402
from scripts import live_source_monitor, post_live_run_status  # noqa: E402
from scripts import series_terminology
from scripts.sermon_accounting import accounting_session, stage as accounting_stage


SERMON_PIPELINE_SCRIPT = REPO_ROOT / "scripts" / "sermon_pipeline.py"
MOBILE_PDF_SCRIPT = REPO_ROOT / "scripts" / "render_mobile_pdf_from_srt.py"
READING_EDITION_SCRIPT = REPO_ROOT / "scripts" / "build_sermon_reading_edition_with_openai.py"
SERMON_INTERPRETATION_SCRIPT = REPO_ROOT / "scripts" / "generate_notes_with_openai.py"
REVIEW_PROMPTS_SCRIPT = REPO_ROOT / "scripts" / "review_prompts.py"
DEFAULT_WORK_ROOT = Path("/tmp/sermon-post-live-subtitles")
POST_LIVE_STATES = {"was_live"}
READING_EDITION_DIRNAME = "reading-edition-v2"
SERMON_INTERPRETATION_DIRNAME = "sermon-interpretation"
INPUT_IDENTITY_SCHEMA_VERSION = 2


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
    parser.add_argument(
        "--live-url",
        help="Supervisor-locked livestream URL; when present, it overrides mutable discovery state.",
    )
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
    parser.add_argument("--source-text-review", type=Path, help="Hash-bound English source corrections; preserves the original ASR evidence.")
    parser.add_argument("--export-sunday-context", action="store_true")
    parser.add_argument("--source-service-date", help="Verified source date (YYYY-MM-DD); otherwise use archive release timestamp.")
    parser.add_argument("--zh-model", default="gpt-6-astra")
    parser.add_argument("--en-correction-model", default="gpt-6-astra")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high"), default="medium")
    parser.add_argument(
        "--reference-model",
        "--gpt4o-model",
        dest="reference_model",
        default="gpt-transcribe",
    )
    parser.add_argument("--fingerprint-precompute", action="store_true",
                        default=os.environ.get("SERMON_FINGERPRINT_PRECOMPUTE") == "1")
    parser.add_argument("--asr-workers", type=int, choices=range(1, 9), default=2)
    parser.add_argument("--pdf-workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--dubbing-config", type=Path, default=os.environ.get("SERMON_DUBBING_CONFIG"),
                        help="Optional configured dubbing candidate overlap after reviewed text and outline; no publication.")
    parser.add_argument("--timing-model", default="whisper-1")
    parser.add_argument(
        "--output-mode",
        choices=("reading", "subtitles"),
        default="reading",
        help="Reading mode skips Whisper and produces the reviewed reading PDF only.",
    )
    parser.add_argument("--reading-edition-provider", choices=("openai", "codex"), default="openai")
    parser.add_argument("--reading-edition-model", default="gpt-6-astra")
    parser.add_argument("--reading-edition-reasoning-effort", choices=("low", "medium", "high"), default="medium")
    parser.add_argument("--reading-review-manifest", type=Path, help="Standard reviewed corrections for the reading builder; existing edit caches are preserved.")
    parser.add_argument("--reading-aligner", choices=("mfa", "legacy"), default="mfa")
    from scripts.mfa_spark import add_arguments
    add_arguments(parser)
    from scripts.mfa_backend import add_arguments as add_backend_arguments
    add_backend_arguments(parser)
    parser.add_argument("--mfa-executable", default=os.environ.get("MFA_EXECUTABLE", "mfa"))
    parser.add_argument("--mfa-dictionary", type=Path, default=os.environ.get("MFA_DICTIONARY"))
    parser.add_argument("--mfa-acoustic-model", type=Path, default=os.environ.get("MFA_ACOUSTIC_MODEL"))
    parser.add_argument("--mfa-g2p-model", type=Path, default=os.environ.get("MFA_G2P_MODEL"))
    parser.add_argument("--mfa-spoken-forms", type=Path, default=os.environ.get("MFA_SPOKEN_FORMS"))
    parser.add_argument("--reading-segment-target-chars", type=int, default=420)
    parser.add_argument("--reading-preferred-seconds", type=float, default=24.0)
    parser.add_argument("--reading-preferred-english-chars", type=int, default=420)
    parser.add_argument("--reading-hard-seconds", type=float, default=55.0)
    parser.add_argument("--reading-hard-english-chars", type=int, default=840)
    parser.add_argument(
        "--interpretation-model",
        "--companion-model",
        dest="interpretation_model",
        default="gpt-6-astra",
    )
    parser.add_argument(
        "--interpretation-reasoning-effort",
        "--companion-reasoning-effort",
        dest="interpretation_reasoning_effort",
        choices=("low", "medium", "high"),
        default="medium",
    )
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
    args = parser.parse_args()
    if args.source_text_review and args.output_mode != "reading":
        parser.error("--source-text-review is supported only with --output-mode reading")
    if args.reading_review_manifest and args.output_mode != "reading":
        parser.error("--reading-review-manifest is supported only with --output-mode reading")
    return args


def run_post_live_generation(
    args: argparse.Namespace,
    *,
    metadata_loader: Callable[[str], dict[str, Any] | None] | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, Any]:
    if args.plan_only or args.dry_run:
        return _run_post_live_generation(args, metadata_loader=metadata_loader, runner=runner)
    with series_terminology.pinned_catalog(args.work_root / args.sunday / "series-terminology.snapshot.json"), accounting_session(args.work_root / args.sunday / "accounting", "saturday_generation", {"sunday": args.sunday}) as accounting:
        report = _run_post_live_generation(args, metadata_loader=metadata_loader, runner=runner)
        report["accounting"] = accounting
        return report


def _run_post_live_generation(
    args: argparse.Namespace,
    *,
    metadata_loader=None,
    runner=subprocess.run,
) -> dict[str, Any]:
    if not hasattr(args, "reference_model"):
        args.reference_model = getattr(args, "gpt4o_model", "gpt-transcribe")
    if not hasattr(args, "output_mode"):
        args.output_mode = "reading"
    if getattr(args, "source_text_review", None) and args.output_mode != "reading":
        raise ValueError("--source-text-review is supported only with --output-mode reading")
    reading_review_manifest_identity(args)
    if not hasattr(args, "content_scope"):
        args.content_scope = None
    state = live_source_monitor.read_state(args.state_file)
    source = selected_source_from_state(state)
    locked_live_url = str(getattr(args, "live_url", "") or "").strip()
    live_url = locked_live_url or live_url_from_state(state, source)
    if locked_live_url:
        source = {
            **source,
            "url": locked_live_url,
            "urlHash": stable_hash(locked_live_url),
        }
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
    if (
        not locked_live_url
        and state.get("lastSunday")
        and state.get("lastSunday") != args.sunday
    ):
        return {
            **base_report,
            "status": "waiting_for_matching_sunday",
            "reason": f"captured state is for {state.get('lastSunday')}",
        }

    with accounting_stage("source_metadata"):
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
    interpretation_command = build_sermon_interpretation_command(
        args,
        pipeline_outdir,
        metadata=metadata,
        source=source,
    )
    delivery_reading_pdf = pipeline_outdir / delivery_pdf_filename(args, metadata=metadata, source=source)
    delivery_interpretation_pdf = pipeline_outdir / interpretation_delivery_pdf_filename(
        args,
        metadata=metadata,
        source=source,
    )
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
        "sermonInterpretationCommand": interpretation_command,
        "deliveryReadingPdf": str(delivery_reading_pdf),
        "deliverySermonInterpretationPdf": str(delivery_interpretation_pdf),
        "outputMode": args.output_mode,
        "contentScope": args.content_scope or "legacy_unspecified",
        "outputs": expected_outputs(pipeline_outdir, args.output_mode),
    }
    if args.plan_only or args.dry_run:
        log_post_live_event(report)
        return report

    stage_durations: dict[str, float] = {}
    started = time.monotonic()
    run_status = post_live_run_status.update_stage(run_status, args.sunday, "downloaded", "running")
    write_run_status(run_status_path, run_status)
    try:
        expected_duration = archive_expected_duration(metadata)
        audio_path = newest_downloaded_audio(audio_template.parent)
        if audio_path:
            with accounting_stage("download", cache_hit=True):
                validate_archive_audio(audio_path, expected_duration_seconds=expected_duration)
                stage_durations["downloaded"] = 0.0
        else:
            with accounting_stage("download"):
                audio_path = download_archive_audio(
                    live_url,
                    audio_template,
                    args.audio_format,
                    args.yt_dlp,
                    runner,
                    cookies_path=args.youtube_cookies,
                    expected_duration_seconds=expected_duration,
                )
            stage_durations["downloaded"] = time.monotonic() - started
    except ArchiveAudioValidationError as exc:
        run_status = post_live_run_status.update_stage(
            run_status, args.sunday, "downloaded", "failed", reason=str(exc),
            duration_seconds=time.monotonic() - started,
        )
        run_status = post_live_run_status.mark_terminal(
            run_status, args.sunday, "failed", stage="downloaded", reason=str(exc),
        )
        write_run_status(run_status_path, run_status)
        raise
    run_status = post_live_run_status.update_stage(
        run_status, args.sunday, "downloaded", "complete", artifact=str(audio_path),
        duration_seconds=stage_durations["downloaded"],
    )
    write_run_status(run_status_path, run_status)
    set_openai_api_key(args)
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
    interpretation_command = build_sermon_interpretation_command(
        args,
        pipeline_outdir,
        metadata=metadata,
        source=source,
    )
    delivery_reading_pdf = pipeline_outdir / delivery_pdf_filename(args, metadata=metadata, source=source)
    delivery_interpretation_pdf = pipeline_outdir / interpretation_delivery_pdf_filename(
        args,
        metadata=metadata,
        source=source,
    )
    core_outputs = (
        ("sermon_zh_relative.srt", "sermon_en_relative.srt", "summary.json")
        if args.output_mode == "subtitles"
        else ("segments_timed_en_corrected.json", "segments_timed_zh.json", "summary.json")
    )
    review_cache_ready = source_review_cache_ready(args, pipeline_outdir)
    core_ready = review_cache_ready and all((pipeline_outdir / name).exists() for name in core_outputs) and pipeline_summary_matches(
        pipeline_outdir / "summary.json",
        output_mode=args.output_mode,
        reference_model=args.reference_model,
        reading_segment_target_chars=getattr(args, "reading_segment_target_chars", 420),
        expected_input_fingerprint=pipeline_input_fingerprint,
        reading_aligner=getattr(args, "reading_aligner", "mfa"),
        expected_alignment_backend=pipeline_input_identity.get("mfa", {}).get("backend"),
    )
    if core_ready:
        with accounting_stage("pipeline", cache_hit=True):
            stage_durations["pipeline"] = 0.0
    else:
        started = time.monotonic()
        with accounting_stage("pipeline", billing="orchestrator"):
            run_command(pipeline_command, runner)
        # A runtime failure can select Spark after the initial local preflight.
        # Bind the completed backend receipt, never label that run as local.
        completed_summary_path = pipeline_outdir / "summary.json"
        if completed_summary_path.is_file():
            completed_summary = json.loads(completed_summary_path.read_text())
            actual_runtime = completed_summary.get("readingAlignmentRuntime")
            if args.output_mode == "reading" and actual_runtime:
                pipeline_input_identity["mfa"] = actual_runtime
                pipeline_input_fingerprint = stable_payload_hash(pipeline_input_identity)
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
        with accounting_stage("mobile_pdf"):
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
    manifest_cache_ready = reading_review_cache_ready(args, reading_outdir)
    reading_ready = manifest_cache_ready and all(
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
        with accounting_stage("reading_edition", cache_hit=True):
            stage_durations["reviewed"] = 0.0
    else:
        started = time.monotonic()
        run_status = post_live_run_status.update_stage(run_status, args.sunday, "reviewed", "running")
        write_run_status(run_status_path, run_status)
        with accounting_stage("reading_edition", billing="orchestrator"):
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
    dubbing_config = getattr(args, "dubbing_config", None)
    if dubbing_config:
        pdf_durations, pdf_wall_seconds, dubbing_candidate = run_pdf_and_dubbing_branches(
            reading_pdf_command, interpretation_command, runner,
            config_path=Path(dubbing_config), week=args.sunday, run_root=run_root,
            workers=getattr(args, "pdf_workers", 2),
        )
        report["dubbingCandidate"] = dubbing_candidate
    else:
        pdf_durations, pdf_wall_seconds = run_pdf_branches(
            reading_pdf_command, interpretation_command, runner,
            workers=getattr(args, "pdf_workers", 2),
        )
    stage_durations.update(pdf_durations)
    stage_durations["pdf_branches_wall"] = pdf_wall_seconds
    stage_durations["pdf_qa"] = stage_durations["mobile_pdf"] + pdf_wall_seconds
    qa_paths = [
        pipeline_outdir / "sermon_zh_en_reading.qa.json",
        pipeline_outdir / "sermon_interpretation_zh.qa.json",
    ]
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
    delivery_paths = [
        *create_delivery_pdf_copy(
            pipeline_outdir / "sermon_zh_en_reading.pdf",
            delivery_reading_pdf,
        ),
        *create_delivery_pdf_copy(
            pipeline_outdir / "sermon_interpretation_zh.pdf",
            delivery_interpretation_pdf,
        ),
    ]
    if getattr(args, "export_sunday_context", False):
        with accounting_stage("context_pack"):
            context = export_sunday_context(args, run_root, metadata, live_url)
        report["sundayContext"] = context
        delivery_paths.extend(Path(path) for path in context["paths"].values())
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
    with accounting_stage("publication", billing="cloud"):
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
            "sermonInterpretationCommand": interpretation_command,
            "deliveryReadingPdf": str(delivery_reading_pdf),
            "deliverySermonInterpretationPdf": str(delivery_interpretation_pdf),
            "sermonInterpretationInsights": str(
                pipeline_outdir / SERMON_INTERPRETATION_DIRNAME / "insights" / "openai-notes.json"
            ),
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


def export_sunday_context(
    args: argparse.Namespace, run_root: Path, metadata: dict[str, Any], live_url: str,
) -> dict[str, Any]:
    from scripts.export_saturday_live_context import export_context

    source_date = getattr(args, "source_service_date", None)
    if source_date:
        source_date = date.fromisoformat(source_date).isoformat()
    else:
        timestamp = metadata.get("release_timestamp")
        if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool) or timestamp <= 0:
            raise RuntimeError("Sunday context requires archive release_timestamp or --source-service-date")
        source_date = datetime.fromtimestamp(timestamp, ZoneInfo("America/Los_Angeles")).date().isoformat()
    return export_context(
        run_root=run_root,
        output_dir=run_root / "pipeline" / "sunday-context",
        target_sunday=args.sunday,
        source_service_date=source_date,
        message_key=live_url,
        message_match_status="unknown",
        source_id=slug_for(args, live_url),
    )


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
        "--asr-workers",
        str(getattr(args, "asr_workers", 2)),
        "--output-mode",
        args.output_mode,
        "--en-correction-model",
        args.en_correction_model,
        "--zh-model",
        args.zh_model,
        "--reasoning-effort",
        args.reasoning_effort,
    ]
    if getattr(args, "fingerprint_precompute", False):
        command.append("--fingerprint-precompute")
    if args.output_mode == "subtitles":
        command.extend(["--timing-model", args.timing_model])
    else:
        command.extend(
            [
                "--reading-segment-target-chars",
                str(getattr(args, "reading_segment_target_chars", 420)),
            ]
        )
    if args.output_mode == "reading":
        command.extend(["--reading-aligner", getattr(args, "reading_aligner", "mfa")])
        if getattr(args, "reading_aligner", "mfa") == "mfa":
            from scripts.mfa_backend import options
            backend = options(args)
            command.append("--mfa-spark-fallback" if backend["allow_spark_fallback"] else "--no-mfa-spark-fallback")
            for key, value in backend["spark_options"].items():
                key = {"mfa_executable":"executable", "dictionary_path":"dictionary"}.get(key, key)
                if key == "spoken_forms_path":
                    continue
                if value:
                    command.extend(["--mfa-spark-" + key.replace("_", "-"), str(value)])
            command.extend(["--mfa-executable", getattr(args, "mfa_executable", os.environ.get("MFA_EXECUTABLE", "mfa"))])
            for name in ("dictionary", "acoustic_model", "g2p_model", "spoken_forms"):
                value = getattr(args, "mfa_" + name, None) or os.environ.get("MFA_" + name.upper())
                if value:
                    command.extend(["--mfa-" + name.replace("_", "-"), str(value)])
    if args.end_time:
        command.extend(["--end-time", args.end_time])
    if args.glossary:
        command.extend(["--glossary", str(args.glossary)])
    if getattr(args, "source_text_review", None):
        command.extend(["--source-text-review", str(args.source_text_review)])
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
    command = [
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
    if getattr(args, "reading_review_manifest", None):
        command.extend(["--review-manifest", str(args.reading_review_manifest)])
    return command


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


def build_sermon_interpretation_command(
    args: argparse.Namespace,
    pipeline_outdir: Path,
    *,
    metadata: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
) -> list[str]:
    sermon_title, speaker = reading_pdf_metadata(args, metadata=metadata, source=source)
    interpretation_dir = pipeline_outdir / SERMON_INTERPRETATION_DIRNAME
    command = [
        sys.executable,
        str(SERMON_INTERPRETATION_SCRIPT),
        "--srt-input",
        str(pipeline_outdir / READING_EDITION_DIRNAME / "sermon_zh_reading_revised.srt"),
        "--secondary-srt-input",
        str(pipeline_outdir / READING_EDITION_DIRNAME / "sermon_en_reading_revised.srt"),
        "--srt-lang",
        "zh",
        "--out-dir",
        str(interpretation_dir / "insights"),
        "--model-output-dir",
        str(interpretation_dir / "model-output"),
        "--pdf-out",
        str(pipeline_outdir / "sermon_interpretation_zh.pdf"),
        "--pdf-qa-out",
        str(pipeline_outdir / "sermon_interpretation_zh.qa.json"),
        "--model",
        str(getattr(args, "interpretation_model", "gpt-6-astra")),
        "--reasoning-effort",
        str(getattr(args, "interpretation_reasoning_effort", "medium")),
        "--sermon-title",
        sermon_title,
        "--sermon-date",
        args.sunday,
        "--source-label",
        "本材料基于所选直播归档版本整理；其他周日场次的具体措辞可能不同。",
    ]
    if speaker:
        command.extend(["--speaker", speaker])
    return command


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


def interpretation_delivery_pdf_filename(
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
        "证道解读",
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
    expected_duration_seconds: float | None = None,
) -> Path:
    output_template.parent.mkdir(parents=True, exist_ok=True)
    existing = newest_downloaded_audio(output_template.parent)
    if existing:
        validate_archive_audio(existing, expected_duration_seconds=expected_duration_seconds)
        return existing
    if any(path.is_file() and any(suffix.startswith((".part", ".ytdl")) for suffix in path.suffixes)
           for path in output_template.parent.glob("source_audio.*")):
        raise ArchiveAudioValidationError("Partial download files preserved. " + ARCHIVE_RECOVERY)
    command = [
        yt_dlp,
        "--no-playlist",
        "--abort-on-unavailable-fragments",
        "--no-overwrites",
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
    audio_path = newest_downloaded_audio(output_template.parent)
    if audio_path is None:
        raise ArchiveAudioValidationError("yt-dlp returned success without a finished media file. " + ARCHIVE_RECOVERY)
    validate_archive_audio(audio_path, expected_duration_seconds=expected_duration_seconds)
    return audio_path


ARCHIVE_AUDIO_SUFFIXES = {".m4a", ".mp4", ".webm", ".mp3", ".ogg", ".opus", ".wav", ".flac", ".aac", ".mka", ".mkv", ".oga", ".mov"}
ARCHIVE_RECOVERY = (
    "Refresh the finished archive metadata and download into a new directory with "
    "--abort-on-unavailable-fragments; verify its full duration before retrying. "
    "Existing media and partial files have not been deleted or overwritten."
)


class ArchiveAudioValidationError(RuntimeError):
    """The archive is not proven complete; no paid ASR or complete upload is allowed."""


def archive_expected_duration(metadata: dict[str, Any] | None) -> float:
    value = (metadata or {}).get("duration")
    if isinstance(value, bool):
        value = None
    try:
        duration = float(value)
    except (TypeError, ValueError):
        duration = 0.0
    if not math.isfinite(duration) or duration <= 0:
        raise ArchiveAudioValidationError("Finished archive metadata has no valid duration. " + ARCHIVE_RECOVERY)
    return duration


def is_archive_audio_file(path: Path) -> bool:
    return (path.is_file() and path.suffix.lower() in ARCHIVE_AUDIO_SUFFIXES
            and not any(suffix.lower().startswith((".part", ".ytdl")) for suffix in path.suffixes))


def probe_archive_audio(path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
             "-of", "json", str(path)],
            check=True, capture_output=True, text=True, timeout=30,
        )
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ArchiveAudioValidationError("Archive audio could not be probed. " + ARCHIVE_RECOVERY) from exc


def validate_archive_audio(path: Path, *, expected_duration_seconds: float | None = None) -> None:
    if not is_archive_audio_file(path) or path.stat().st_size == 0:
        raise ArchiveAudioValidationError("Archive path is not a nonempty finished media file. " + ARCHIVE_RECOVERY)
    probe = probe_archive_audio(path)
    try:
        duration = float(probe.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        duration = 0.0
    if (not math.isfinite(duration) or duration <= 0
            or not any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))):
        raise ArchiveAudioValidationError("Archive has no valid audio stream and duration. " + ARCHIVE_RECOVERY)
    if expected_duration_seconds is not None:
        expected = archive_expected_duration({"duration": expected_duration_seconds})
        # Allow small archive remux/tail differences, never minutes of missing fragments.
        tolerance = min(15.0, max(5.0, expected * 0.002))
        if abs(duration - expected) > tolerance:
            raise ArchiveAudioValidationError(
                f"Archive duration mismatch: measured {duration:.3f}s, expected {expected:.3f}s "
                f"(tolerance {tolerance:.3f}s). " + ARCHIVE_RECOVERY
            )


def newest_downloaded_audio(download_dir: Path) -> Path | None:
    files = sorted(
        (
            path
            for path in download_dir.glob("source_audio.*")
            if is_archive_audio_file(path)
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
    reading_aligner: str = "mfa",
    expected_alignment_backend: str | None = None,
) -> bool:
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    models = summary.get("models") if isinstance(summary, dict) else None
    fingerprint = summary.get("sourceFingerprintPrecompute") if isinstance(summary, dict) else None
    if fingerprint:
        try:
            if file_content_identity(Path(fingerprint["path"]))["sha256"] != fingerprint["sha256"]:
                return False
        except (OSError, KeyError, TypeError):
            return False
    matches = (
        summary.get("outputMode") == output_mode
        and isinstance(models, dict)
        and models.get("referenceAsr") == reference_model
    )
    if output_mode == "reading":
        matches = matches and summary.get("readingSegmentTargetCharacters") == max(
            120, int(reading_segment_target_chars)
        )
    if output_mode == "reading":
        matches = matches and summary.get("readingAligner", "legacy") == reading_aligner
    if expected_alignment_backend is not None:
        matches = matches and summary.get("readingAlignmentBackend") == expected_alignment_backend
    if expected_input_fingerprint is not None:
        matches = matches and summary.get("pipelineInputFingerprint") == expected_input_fingerprint
    return matches


def source_review_cache_ready(args: argparse.Namespace, pipeline_outdir: Path) -> bool:
    """Verify review evidence before cache reuse, without modifying raw ASR."""
    review = getattr(args, "source_text_review", None)
    if review is None:
        return True
    if args.output_mode != "reading":
        raise ValueError("--source-text-review is supported only with --output-mode reading")
    if getattr(args, "reading_aligner", "mfa") == "mfa":
        # Reviewed text must be realigned, so checking apply_review alone cannot
        # certify timing. Re-enter the pipeline and its hash-bound MFA caches.
        return False
    raw_path = pipeline_outdir / "segments_timed_en_raw.json"
    audio_path = pipeline_outdir / "source_clip.m4a"
    asr_path = pipeline_outdir / "asr_reference.json"
    if not asr_path.is_file():
        asr_path = pipeline_outdir / "asr_reference_chunks.json"
    if not all(path.is_file() for path in (raw_path, audio_path, asr_path)):
        return False
    from scripts.sermon_source_text_review import apply_review

    raw_segments = json.loads(raw_path.read_text(encoding="utf-8"))
    corrected, _ = apply_review(raw_segments, review, audio_path, asr_path)
    from scripts.sermon_pipeline import clean_text, ffprobe_duration, reference_chunks_to_reading_segments

    asr = json.loads(asr_path.read_text(encoding="utf-8"))
    if asr_path.name == "asr_reference.json":
        if not isinstance(asr, dict):
            raise ValueError("Bound single-request ASR must be an object")
        duration = round(ffprobe_duration(audio_path), 3)
        chunks = [{"id": 0, "start": 0.0, "end": duration, "duration": duration,
            "text": clean_text(asr.get("text", "")), "usage": asr.get("usage"), "detectedLanguages": asr.get("languages", [])}]
    else:
        if not isinstance(asr, list):
            raise ValueError("Bound chunked ASR must be an array")
        chunks = asr
    expected_raw = reference_chunks_to_reading_segments(
        chunks, target_chars=max(120, int(getattr(args, "reading_segment_target_chars", 420))))
    if raw_segments != expected_raw:
        raise ValueError("Raw reading segments differ from the bound ASR and current segment target")
    corrected_path = pipeline_outdir / "segments_timed_en_corrected.json"
    return corrected_path.is_file() and json.loads(corrected_path.read_text(encoding="utf-8")) == corrected


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
    identity = {
        "schemaVersion": INPUT_IDENTITY_SCHEMA_VERSION,
        "seriesTerminology": series_terminology.context(),
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
            "seriesTerminology": file_content_identity(Path(series_terminology.__file__)),
        },
    }
    if args.output_mode == "reading":
        aligner = getattr(args, "reading_aligner", "mfa")
        identity["readingAligner"] = aligner
        identity["schemaVersion"] = 5  # Bind selected local or Spark runtime before whole-pipeline cache reuse.
        if aligner == "mfa":
            from scripts.mfa_backend import preflight, options
            identity["mfa"] = preflight(**options(args))
            identity["mfaBackend"] = file_content_identity(REPO_ROOT / "scripts" / "mfa_backend.py")
            identity["mfaTransport"] = file_content_identity(REPO_ROOT / "scripts" / "mfa_spark.py")
    if getattr(args, "fingerprint_precompute", False):
        identity["fingerprintPrecompute"] = {
            "script": file_content_identity(REPO_ROOT / "experiments/sermon-dubbing-poc/build_fingerprint_index.mjs"),
            "algorithm": file_content_identity(REPO_ROOT / "experiments/sermon-dubbing-poc/web/fingerprint-core.mjs"),
        }
    if getattr(args, "source_text_review", None):
        identity["sourceTextReview"] = file_content_identity(args.source_text_review)
    return identity


def build_reading_input_identity(
    args: argparse.Namespace,
    pipeline_outdir: Path,
    *,
    pipeline_input_fingerprint: str,
) -> dict[str, Any]:
    identity = {
        "schemaVersion": INPUT_IDENTITY_SCHEMA_VERSION,
        "seriesTerminology": series_terminology.context(),
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
            "seriesTerminology": file_content_identity(Path(series_terminology.__file__)),
        },
    }
    manifest = reading_review_manifest_identity(args)
    if manifest is not None:
        identity["readingReviewManifest"] = manifest
    return identity


def reading_review_manifest_identity(args: argparse.Namespace) -> dict[str, Any] | None:
    path = getattr(args, "reading_review_manifest", None)
    if path is None:
        return None
    if args.output_mode != "reading":
        raise ValueError("--reading-review-manifest is supported only with --output-mode reading")
    _, identity = read_reading_review_manifest(path)
    return identity


def read_reading_review_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        contents = Path(path).read_bytes()
    except OSError as exc:
        raise ValueError("--reading-review-manifest must name an existing readable file") from exc
    manifest = json.loads(contents)
    if not isinstance(manifest, dict):
        raise ValueError("Reading review manifest must be a JSON object")
    corrections = manifest.get("corrections")
    if not isinstance(corrections, list) or not corrections:
        raise ValueError("Reading review manifest requires nonempty corrections")
    if any(not isinstance(item, dict) or item.get("field") != "zh" for item in corrections):
        raise ValueError("--reading-review-manifest supports only field='zh'; English requires --source-text-review")
    return manifest, {"exists": True, "sizeBytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def reading_review_cache_ready(args: argparse.Namespace, reading_outdir: Path) -> bool:
    """Validate standard manifest application and its receipt before reuse."""
    identity = reading_review_manifest_identity(args)
    if identity is None:
        return True
    manifest, current_identity = read_reading_review_manifest(args.reading_review_manifest)
    if current_identity != identity:
        raise ValueError("Reading review manifest changed during cache validation")
    final_path = reading_outdir / "reading_blocks.final.json"
    if not final_path.is_file():
        return False
    from scripts.build_sermon_reading_edition_with_openai import apply_review_manifest

    final = json.loads(final_path.read_text(encoding="utf-8"))
    reviewed, _ = apply_review_manifest(final, manifest)
    if reviewed != final:
        return False
    report_path = reading_outdir / "reading_quality_report.json"
    if not report_path.is_file():
        return False
    report = json.loads(report_path.read_text(encoding="utf-8"))
    recorded = report.get("reviewManifest") or {}
    return isinstance(recorded, dict) and recorded.get("sha256") == identity["sha256"]


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


def load_dubbing_producer_hook():
    directory = REPO_ROOT / "experiments" / "sermon-dubbing-poc"
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location("sermon_dubbing_producer_bridge", directory / "continue_saturday_dubbing.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.start_producer_candidate, module.CandidateNotReady


def run_frozen_interpretation_notes(command, runner):
    """Resume a hash-bound outline; never rewrite inputs of an existing synthesis job."""
    def option(flag):
        return command[command.index(flag) + 1]
    outdir = Path(option("--out-dir"))
    notes = outdir / "openai-notes.json"
    raw = Path(option("--model-output-dir")) / "openai-notes-output.jsonl"
    receipt_path = outdir / "producer-notes-cache.json"
    sources = {flag: file_content_identity(Path(option(flag)))
               for flag in ("--srt-input", "--secondary-srt-input")}
    if any(not item.get("exists") for item in sources.values()):
        raise RuntimeError("Frozen interpretation requires both reviewed SRT inputs")
    identity = {"schemaVersion": 1, "command": command, "sources": sources,
                "seriesTerminology": series_terminology.context(),
                "implementation": {"generator": file_content_identity(SERMON_INTERPRETATION_SCRIPT),
                                   "prompts": file_content_identity(REVIEW_PROMPTS_SCRIPT),
                                   "terminology": file_content_identity(Path(series_terminology.__file__))}}
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("identity") != identity or receipt.get("outputs") != {
                "notes": file_content_identity(notes), "raw": file_content_identity(raw)}:
            raise RuntimeError("Frozen interpretation inputs or outputs changed; preserve the existing dubbing job and inspect the notes receipt")
        with accounting_stage("interpretation", billing="orchestrator", cache_hit=True):
            return
    if notes.exists() or raw.exists():
        raise RuntimeError("Existing interpretation has no producer cache receipt; inspect it before creating a new dubbing job")
    from scripts.sermon_accounting import subprocess_environment
    with accounting_stage("interpretation", billing="orchestrator"):
        runner(command, check=True, env=subprocess_environment())
    outputs = {"notes": file_content_identity(notes), "raw": file_content_identity(raw)}
    if any(not item.get("exists") for item in outputs.values()):
        raise RuntimeError("Interpretation did not produce complete notes and model evidence")
    payload = json.loads(notes.read_text(encoding="utf-8"))
    if payload.get("status") != "ready":
        raise RuntimeError("Interpretation is not ready for frozen candidate preparation")
    receipt_path.write_text(json.dumps({"identity": identity, "outputs": outputs}, ensure_ascii=False, indent=2), encoding="utf-8")


def run_pdf_and_dubbing_branches(reading_command, interpretation_command, runner, *,
                                 config_path, week, run_root, workers=2, producer_hook=None):
    """Freeze notes before TTS; join all branches before any delivery publication."""
    if workers not in (1, 2):
        raise ValueError("PDF workers must be 1 or 2")
    if producer_hook is None:
        hook, not_ready_exception = load_dubbing_producer_hook()
    else:
        hook, not_ready_exception = producer_hook, getattr(producer_hook, "not_ready_exception", ())
    notes_command = list(interpretation_command)
    outputs = {}
    for flag in ("--pdf-out", "--pdf-qa-out"):
        index = notes_command.index(flag)
        outputs[flag] = notes_command[index + 1]
        del notes_command[index:index + 2]
    insights = Path(notes_command[notes_command.index("--out-dir") + 1]) / "openai-notes.json"
    render_command = [sys.executable, str(REPO_ROOT / "scripts" / "render_sermon_interpretation_pdf.py"),
                      "--input", str(insights), "--out", outputs["--pdf-out"], "--qa-out", outputs["--pdf-qa-out"]]
    from scripts.sermon_accounting import subprocess_environment

    def reading_branch():
        started = time.monotonic()
        with accounting_stage("reading_pdf"):
            runner(reading_command, check=True, env=subprocess_environment())
        return time.monotonic() - started

    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pdf_pool, \
         concurrent.futures.ThreadPoolExecutor(max_workers=1) as dubbing_pool:
        reading = pdf_pool.submit(copy_context().run, reading_branch)
        # workers=1 explicitly serializes PDF branches, but TTS may still overlap rendering.
        if workers == 1:
            reading.result()
        notes_started = time.monotonic()
        run_frozen_interpretation_notes(notes_command, runner)
        notes_elapsed = time.monotonic() - notes_started
        candidate = None
        try:
            dubbing = hook(config_path, week, run_root, dubbing_pool)
        except not_ready_exception as exc:
            # Ordinary missing voice/week configuration does not revoke reviewed PDF inputs.
            dubbing = None
            candidate = {"status": exc.status, "reason": exc.reason, "published": False}

        render_started = time.monotonic()
        with accounting_stage("interpretation_pdf"):
            runner(render_command, check=True, env=subprocess_environment())
        render_elapsed = time.monotonic() - render_started
        durations = {"reading_pdf": reading.result(), "sermon_interpretation_pdf": notes_elapsed + render_elapsed,
                     "interpretation_notes": notes_elapsed, "interpretation_render": render_elapsed}
        pdf_wall = time.monotonic() - started
        if dubbing is not None:
            candidate = dubbing.result()
            if not isinstance(candidate, dict) or candidate.get("status") != "waiting_conversation_review":
                raise RuntimeError("Dubbing candidate did not produce validated review evidence")
        durations["pdf_dubbing_wall"] = time.monotonic() - started
    return durations, pdf_wall, candidate


def run_pdf_branches(reading_command, interpretation_command, runner, *, workers=2):
    """Join both independent branches before QA/publication; retain completed artifacts on failure."""
    if workers not in (1, 2):
        raise ValueError("PDF workers must be 1 or 2")

    def run_branch(command, stage_name, billing):
        started = time.monotonic()
        with accounting_stage(stage_name, billing=billing):
            from scripts.sermon_accounting import subprocess_environment
            runner(command, check=True, env=subprocess_environment())
        return time.monotonic() - started

    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        reading = executor.submit(copy_context().run, run_branch, reading_command, "reading_pdf", "local")
        interpretation = executor.submit(copy_context().run, run_branch, interpretation_command, "interpretation", "orchestrator")
        # Executor exit waits for any already-running sibling before failure propagates.
        durations = {"reading_pdf": reading.result(), "sermon_interpretation_pdf": interpretation.result()}
    return durations, time.monotonic() - started


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
        str(pipeline_outdir / "sermon_interpretation_zh.pdf"),
        str(pipeline_outdir / "sermon_interpretation_zh.qa.json"),
        str(pipeline_outdir / SERMON_INTERPRETATION_DIRNAME / "insights" / "openai-notes.json"),
        str(pipeline_outdir / SERMON_INTERPRETATION_DIRNAME / "model-output" / "openai-notes-output.jsonl"),
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
