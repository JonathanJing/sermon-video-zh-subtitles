#!/usr/bin/env python3
"""Run the post-live weekly offline subtitle pipeline from captured live-source state."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.cloud import access_secret, upload_file_to_gcs  # noqa: E402
from backend.observability import log_event, url_summary  # noqa: E402
from scripts import live_source_monitor  # noqa: E402


SERMON_PIPELINE_SCRIPT = REPO_ROOT / "scripts" / "sermon_pipeline.py"
MOBILE_PDF_SCRIPT = REPO_ROOT / "scripts" / "render_mobile_pdf_from_srt.py"
DEFAULT_WORK_ROOT = Path("/tmp/sermon-post-live-subtitles")
POST_LIVE_STATES = {"was_live"}


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
    parser.add_argument("--zh-model", default="gpt-5.5")
    parser.add_argument("--en-correction-model", default="gpt-5.4-mini")
    parser.add_argument("--gpt4o-model", default="gpt-4o-transcribe")
    parser.add_argument("--timing-model", default="whisper-1")
    parser.add_argument("--audio-format", default="bestaudio[ext=m4a]/bestaudio")
    parser.add_argument("--yt-dlp", default="yt-dlp")
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
    audio_template = run_root / "download" / "source_audio.%(ext)s"
    pipeline_outdir = run_root / "pipeline"
    pipeline_command = build_pipeline_command(args, run_root / "download", pipeline_outdir, live_url)
    mobile_pdf_command = build_mobile_pdf_command(args, pipeline_outdir, live_url)
    report = {
        **base_report,
        "status": "planned" if (args.plan_only or args.dry_run) else "running",
        "metadata": safe_metadata(metadata),
        "downloadTemplate": str(audio_template),
        "pipelineOutdir": str(pipeline_outdir),
        "pipelineCommand": pipeline_command,
        "mobilePdfCommand": mobile_pdf_command,
        "outputs": expected_outputs(pipeline_outdir),
    }
    if args.plan_only or args.dry_run:
        log_post_live_event(report)
        return report

    set_openai_api_key(args)
    audio_path = download_archive_audio(live_url, audio_template, args.audio_format, args.yt_dlp, runner)
    pipeline_command = build_pipeline_command(args, audio_path.parent, pipeline_outdir, live_url, audio_path=audio_path)
    mobile_pdf_command = build_mobile_pdf_command(args, pipeline_outdir, live_url)
    run_command(pipeline_command, runner)
    run_command(mobile_pdf_command, runner)
    uploaded = upload_outputs(args, pipeline_outdir)
    report.update(
        {
            "status": "completed",
            "downloadedAudio": str(audio_path),
            "pipelineCommand": pipeline_command,
            "mobilePdfCommand": mobile_pdf_command,
            "uploaded": uploaded,
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
    ]
    if args.end_time:
        command.extend(["--end-time", args.end_time])
    if args.glossary:
        command.extend(["--glossary", str(args.glossary)])
    return command


def build_mobile_pdf_command(args: argparse.Namespace, pipeline_outdir: Path, live_url: str) -> list[str]:
    return [
        sys.executable,
        str(MOBILE_PDF_SCRIPT),
        "--input",
        str(pipeline_outdir / "sermon_zh_relative.srt"),
        "--out",
        str(pipeline_outdir / "sermon_zh_mobile.pdf"),
        "--title",
        slug_for(args, live_url),
        "--subtitle",
        f"{args.sunday} sermon Chinese subtitles",
    ]


def download_archive_audio(
    live_url: str,
    output_template: Path,
    audio_format: str,
    yt_dlp: str,
    runner: Callable[..., subprocess.CompletedProcess],
) -> Path:
    output_template.parent.mkdir(parents=True, exist_ok=True)
    command = [
        yt_dlp,
        "--no-playlist",
        "-f",
        audio_format,
        "-o",
        str(output_template),
        live_url,
    ]
    run_command(command, runner)
    files = sorted(output_template.parent.glob("source_audio.*"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError("yt-dlp completed but no source_audio.* file was created")
    return files[0]


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
