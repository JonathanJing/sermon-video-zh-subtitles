#!/usr/bin/env python3
"""Run the post-live weekly offline subtitle pipeline from captured live-source state."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.cloud import access_secret, upload_file_to_gcs  # noqa: E402
from backend.observability import log_event, url_summary  # noqa: E402
from scripts import live_source_monitor, post_live_run_status  # noqa: E402


SERMON_PIPELINE_SCRIPT = REPO_ROOT / "scripts" / "sermon_pipeline.py"
MOBILE_PDF_SCRIPT = REPO_ROOT / "scripts" / "render_mobile_pdf_from_srt.py"
READING_EDITION_SCRIPT = REPO_ROOT / "scripts" / "build_sermon_reading_edition_with_openai.py"
DEFAULT_WORK_ROOT = Path("/tmp/sermon-post-live-subtitles")
POST_LIVE_STATES = {"was_live"}
READING_EDITION_DIRNAME = "reading-edition-v2"


def main() -> int:
    args = parse_args()
    report = run_post_live_generation(args)
    out = resolve_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"completed", "planned", "waiting_for_post_live"} else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sunday", required=True, help="Sunday slice date, YYYY-MM-DD.")
    parser.add_argument("--state-file", required=True, help="live_source_monitor state path or gs:// URI.")
    parser.add_argument("--out", type=Path, default=Path("artifacts/post-live-subtitle-generation/report.json"))
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--slug")
    parser.add_argument("--start-time", help="Absolute sermon start in the full downloaded media.")
    parser.add_argument("--end-time", help="Absolute sermon end in the full downloaded media.")
    parser.add_argument("--glossary", type=Path)
    parser.add_argument("--zh-model", default="gpt-5.6")
    parser.add_argument("--en-correction-model", default="gpt-5.6")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high"), default="high")
    parser.add_argument("--gpt4o-model", default="gpt-4o-transcribe")
    parser.add_argument("--timing-model", default="whisper-1")
    parser.add_argument("--reading-edition-provider", choices=("openai", "codex"), default="openai")
    parser.add_argument("--reading-edition-model", default="gpt-5.6-sol")
    parser.add_argument("--reading-edition-reasoning-effort", choices=("low", "medium", "high"), default="high")
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
    run_status = post_live_run_status.update_stage(run_status, args.sunday, "archive_ready", "complete")
    write_run_status(run_status_path, run_status)
    audio_template = run_root / "download" / "source_audio.%(ext)s"
    pipeline_outdir = run_root / "pipeline"
    reading_outdir = pipeline_outdir / READING_EDITION_DIRNAME
    pipeline_command = build_pipeline_command(args, run_root / "download", pipeline_outdir, live_url)
    mobile_pdf_command = build_mobile_pdf_command(args, pipeline_outdir, live_url, metadata=metadata, source=source)
    reading_edition_command = build_reading_edition_command(args, pipeline_outdir)
    reading_pdf_command = build_reading_pdf_command(args, pipeline_outdir, live_url, metadata=metadata, source=source)
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
        "outputs": expected_outputs(pipeline_outdir),
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
    mobile_pdf_command = build_mobile_pdf_command(args, pipeline_outdir, live_url, metadata=metadata, source=source)
    reading_edition_command = build_reading_edition_command(args, pipeline_outdir)
    reading_pdf_command = build_reading_pdf_command(args, pipeline_outdir, live_url, metadata=metadata, source=source)
    core_ready = all(
        (pipeline_outdir / name).exists()
        for name in ("sermon_zh_relative.srt", "sermon_en_relative.srt", "summary.json")
    )
    if core_ready:
        stage_durations["pipeline"] = 0.0
    else:
        started = time.monotonic()
        run_command(pipeline_command, runner)
        stage_durations["pipeline"] = time.monotonic() - started
    for stage in ("clipped", "transcribed", "translated"):
        run_status = post_live_run_status.update_stage(
            run_status, args.sunday, stage, "complete", duration_seconds=stage_durations["pipeline"]
        )
    write_run_status(run_status_path, run_status)
    started = time.monotonic()
    run_command(mobile_pdf_command, runner)
    stage_durations["mobile_pdf"] = time.monotonic() - started
    reading_report_path = reading_outdir / "reading_quality_report.json"
    reading_ready = all(
        path.exists()
        for path in (
            reading_outdir / "sermon_zh_reading_revised.srt",
            reading_outdir / "sermon_en_reading_revised.srt",
            reading_report_path,
        )
    )
    if reading_ready:
        stage_durations["reviewed"] = 0.0
    else:
        started = time.monotonic()
        run_status = post_live_run_status.update_stage(run_status, args.sunday, "reviewed", "running")
        write_run_status(run_status_path, run_status)
        run_command(reading_edition_command, runner)
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
    qa_paths = [
        pipeline_outdir / "sermon_zh_mobile.qa.json",
        pipeline_outdir / "sermon_zh_en_reading.qa.json",
    ]
    qa_reports = [json.loads(path.read_text(encoding="utf-8")) for path in qa_paths]
    if any(report.get("status") != "pass" for report in qa_reports):
        run_status = post_live_run_status.update_stage(
            run_status, args.sunday, "pdf_qa", "blocked", reason="pdf_qa_needs_review",
            duration_seconds=stage_durations["pdf_qa"],
        )
        write_run_status(run_status_path, run_status)
        raise RuntimeError("PDF QA did not pass; inspect the generated *.qa.json reports")
    run_status = post_live_run_status.update_stage(
        run_status, args.sunday, "pdf_qa", "complete",
        artifact=str(pipeline_outdir / "sermon_zh_en_reading.qa.json"),
        duration_seconds=stage_durations["pdf_qa"],
    )
    write_run_status(run_status_path, run_status)
    uploaded = upload_outputs(args, pipeline_outdir)
    report.update(
        {
            "status": "completed",
            "downloadedAudio": str(audio_path),
            "pipelineCommand": pipeline_command,
            "mobilePdfCommand": mobile_pdf_command,
            "readingEditionCommand": reading_edition_command,
            "readingPdfCommand": reading_pdf_command,
            "readingQualityReport": str(reading_report_path),
            "uploaded": uploaded,
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
        "--gpt4o-model",
        args.gpt4o_model,
        "--timing-model",
        args.timing_model,
        "--en-correction-model",
        args.en_correction_model,
        "--zh-model",
        args.zh_model,
        "--reasoning-effort",
        args.reasoning_effort,
    ]
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
        mobile_pdf_title(args, live_url, metadata=metadata, source=source),
        "--subtitle",
        f"{args.sunday} 逐句中英字幕版",
        "--source-url",
        live_url,
        "--source-offset-seconds",
        str(timecode_to_seconds(args.start_time or "00:00:00")),
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
    ]


def build_reading_pdf_command(
    args: argparse.Namespace,
    pipeline_outdir: Path,
    live_url: str,
    *,
    metadata: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
) -> list[str]:
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
        mobile_pdf_title(args, live_url, metadata=metadata, source=source),
        "--subtitle",
        f"{args.sunday} 中英对照阅读版",
        "--source-url",
        live_url,
        "--source-offset-seconds",
        str(timecode_to_seconds(args.start_time or "00:00:00")),
    ]


def mobile_pdf_title(
    args: argparse.Namespace,
    live_url: str,
    *,
    metadata: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
) -> str:
    for candidate in [
        metadata.get("title") if metadata else None,
        source.get("title") if source else None,
    ]:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return slug_for(args, live_url)


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


def write_run_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def run_command(command: list[str], runner: Callable[..., subprocess.CompletedProcess]) -> None:
    runner(command, check=True)


def set_openai_api_key(args: argparse.Namespace) -> None:
    if os.environ.get("OPENAI_API_KEY"):
        return
    if not args.api_key_secret:
        return
    os.environ["OPENAI_API_KEY"] = access_secret(args.api_key_secret)


def expected_outputs(pipeline_outdir: Path) -> list[str]:
    return [
        str(pipeline_outdir / "sermon_zh_relative.srt"),
        str(pipeline_outdir / "sermon_zh_relative.vtt"),
        str(pipeline_outdir / "sermon_zh_mobile.pdf"),
        str(pipeline_outdir / "sermon_zh_en_reading.pdf"),
        str(pipeline_outdir / "sermon_zh_mobile.qa.json"),
        str(pipeline_outdir / "sermon_zh_en_reading.qa.json"),
        str(pipeline_outdir / READING_EDITION_DIRNAME / "reading_quality_report.json"),
        str(pipeline_outdir / READING_EDITION_DIRNAME / "sermon_zh_reading_revised.srt"),
        str(pipeline_outdir / READING_EDITION_DIRNAME / "sermon_en_reading_revised.srt"),
        str(pipeline_outdir / "full_video_zh_from_sermon.srt"),
        str(pipeline_outdir / "full_video_zh_from_sermon.vtt"),
        str(pipeline_outdir / "qa_report.json"),
        str(pipeline_outdir / "summary.json"),
    ]


def upload_outputs(args: argparse.Namespace, pipeline_outdir: Path) -> list[dict[str, str]]:
    if not args.gcs_bucket:
        return []
    slug = args.slug or "sermon"
    prefix = "/".join(part.strip("/") for part in [args.gcs_prefix, args.sunday, "post-live-subtitles", slug] if part)
    uploaded = []
    for path_text in expected_outputs(pipeline_outdir):
        path = Path(path_text)
        if not path.exists():
            continue
        destination = f"gs://{args.gcs_bucket}/{prefix}/{path.name}"
        upload_file_to_gcs(path, destination)
        uploaded.append({"localPath": str(path), "gcsUri": destination})
    return uploaded


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
