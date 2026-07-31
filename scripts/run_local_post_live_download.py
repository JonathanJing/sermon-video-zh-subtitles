#!/usr/bin/env python3
"""Download completed YouTube replay media locally and hand it to Cloud Run through GCS."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.cloud import access_secret, upload_file_to_gcs, write_gcs_text  # noqa: E402
from backend.config import upcoming_sunday  # noqa: E402
from scripts import live_source_monitor, run_post_live_subtitle_generation, sermon_pipeline, youtube_data_api  # noqa: E402


DEFAULT_STATE_URI = "gs://sermon-zh-artifacts-ai-for-god/sundays/live-source-monitor/backend-state.json"
DEFAULT_BUCKET = "sermon-zh-artifacts-ai-for-god"
SUCCESS_STATUSES = {"complete", "already_complete", "waiting_for_post_live", "missing_source"}


def main() -> int:
    args = parse_args()
    report = run_local_download(args)
    out = resolve_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code_for_status(report["status"])


def exit_code_for_status(status: str) -> int:
    """Treat expected Sunday polling states as successful no-ops."""
    return 0 if status in SUCCESS_STATUSES else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sunday")
    parser.add_argument("--state-file", default=DEFAULT_STATE_URI)
    parser.add_argument("--live-url")
    parser.add_argument("--youtube-streams-url", default="https://www.youtube.com/@marinerschurch/streams")
    parser.add_argument("--timezone", default="America/Los_Angeles")
    parser.add_argument("--work-root", type=Path, default=Path("artifacts/local-post-live-download"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/local-post-live-download/report.json"))
    parser.add_argument("--gcs-bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--gcs-prefix", default="sundays")
    parser.add_argument("--youtube-api-key-secret", required=True)
    parser.add_argument("--youtube-cookies", type=Path)
    parser.add_argument("--yt-dlp", default="yt-dlp")
    parser.add_argument("--audio-format", default="bestaudio[ext=m4a]/bestaudio")
    parser.add_argument("--video-format", default="bestvideo[height<=1080]+bestaudio/best[height<=1080]")
    parser.add_argument("--existing-audio", type=Path)
    parser.add_argument("--existing-video", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def run_local_download(args: argparse.Namespace) -> dict[str, Any]:
    sunday = args.sunday or upcoming_sunday().isoformat()
    state = live_source_monitor.read_state(args.state_file) if not args.live_url else {}
    source = run_post_live_subtitle_generation.selected_source_from_state(state)
    live_url = args.live_url or run_post_live_subtitle_generation.live_url_from_state(state, source)
    api_key = access_secret(args.youtube_api_key_secret)
    if not live_url:
        live_url = discover_sunday_video(
            sunday,
            streams_url=args.youtube_streams_url,
            timezone_name=args.timezone,
            api_key=api_key,
        )
    if not live_url:
        return {"schemaVersion": 1, "status": "missing_source", "sunday": sunday}
    video_id = live_source_monitor.youtube_video_id_from_url(live_url)
    if not video_id:
        raise RuntimeError("YouTube video id could not be parsed from --live-url/state")
    metadata = youtube_data_api.video_metadata(
        video_id,
        api_key=api_key,
    )
    if not run_post_live_subtitle_generation.is_post_live_ready(metadata):
        return {
            "schemaVersion": 1,
            "status": "waiting_for_post_live",
            "sunday": sunday,
            "sourceUrl": live_url,
            "metadata": run_post_live_subtitle_generation.safe_metadata(metadata),
        }

    slug = run_post_live_subtitle_generation.slug_for(argparse.Namespace(slug=None), live_url)
    run_root = resolve_path(args.work_root) / sunday / slug
    download_dir = run_root / "download"
    download_dir.mkdir(parents=True, exist_ok=True)
    local_manifest = download_dir / "local-download-manifest.json"
    if local_manifest.exists() and not args.force:
        existing = json.loads(local_manifest.read_text(encoding="utf-8"))
        if isinstance(existing, dict) and existing.get("status") == "complete":
            return {
                **existing,
                "status": "already_complete",
                "localManifest": display_path(local_manifest),
            }
    audio_path = prepare_audio(args, live_url, download_dir)
    video_path = prepare_video(args, live_url, download_dir)
    prefix = "/".join(part.strip("/") for part in [args.gcs_prefix, sunday, "post-live-subtitles", slug])
    audio_uri = f"gs://{args.gcs_bucket}/{prefix}/download/{audio_path.name}"
    video_uri = f"gs://{args.gcs_bucket}/{prefix}/download/{video_path.name}"
    upload_file_to_gcs(audio_path, audio_uri)
    upload_file_to_gcs(video_path, video_uri)
    manifest_uri = f"gs://{args.gcs_bucket}/{prefix}/download/local-download-manifest.json"
    manifest = {
        "schemaVersion": 1,
        "status": "complete",
        "handoffKind": "local-download-to-gcs",
        "sunday": sunday,
        "slug": slug,
        "sourceUrl": live_url,
        "metadata": run_post_live_subtitle_generation.safe_metadata(metadata),
        "audio": media_evidence(audio_path, audio_uri),
        "video": media_evidence(video_path, video_uri),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "apiKeyMaterialIncluded": False,
        "cookieMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }
    local_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    write_gcs_text(manifest_uri, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return {**manifest, "manifestGcsUri": manifest_uri, "localManifest": display_path(local_manifest)}


def discover_sunday_video(
    sunday: str,
    *,
    streams_url: str,
    timezone_name: str,
    api_key: str,
    urls_loader=live_source_monitor.youtube_stream_watch_urls_from_tab,
    metadata_loader=youtube_data_api.video_metadata,
) -> str | None:
    candidates = []
    for url in urls_loader(streams_url)[:8]:
        video_id = live_source_monitor.youtube_video_id_from_url(url)
        if not video_id:
            continue
        try:
            metadata = metadata_loader(video_id, api_key=api_key)
        except Exception:
            continue
        if not metadata:
            continue
        timestamp = metadata.get("actual_start_time") or metadata.get("scheduled_start_time")
        if not timestamp or local_date(str(timestamp), timezone_name) != sunday:
            continue
        state_rank = {"is_live": 3, "was_live": 2, "is_upcoming": 1}.get(str(metadata.get("live_status")), 0)
        candidates.append((state_rank, str(timestamp), url))
    if not candidates:
        return None
    return max(candidates)[2]


def local_date(value: str, timezone_name: str) -> str | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    except (ValueError, TypeError):
        return None


def prepare_audio(args: argparse.Namespace, live_url: str, download_dir: Path) -> Path:
    if args.existing_audio:
        source = resolve_path(args.existing_audio)
        destination = download_dir / f"source_audio{source.suffix}"
        if source != destination:
            shutil.copy2(source, destination)
        return destination
    template = download_dir / "source_audio.%(ext)s"
    if args.force:
        for path in download_dir.glob("source_audio.*"):
            path.unlink()
    return run_post_live_subtitle_generation.download_archive_audio(
        live_url,
        template,
        args.audio_format,
        args.yt_dlp,
        subprocess.run,
        cookies_path=resolve_path(args.youtube_cookies) if args.youtube_cookies else None,
    )


def prepare_video(args: argparse.Namespace, live_url: str, download_dir: Path) -> Path:
    destination = download_dir / "source_video.mp4"
    if args.existing_video:
        source = resolve_path(args.existing_video)
        if source != destination:
            shutil.copy2(source, destination)
        return destination
    if destination.exists() and not args.force:
        return destination
    command = [
        args.yt_dlp,
        "--no-playlist",
        "--js-runtimes",
        "node",
        "-f",
        args.video_format,
        "--merge-output-format",
        "mp4",
        "-o",
        str(destination),
    ]
    if args.youtube_cookies:
        command.extend(["--cookies", str(resolve_path(args.youtube_cookies))])
    command.append(live_url)
    subprocess.run(command, check=True)
    if not destination.exists():
        raise RuntimeError("yt-dlp completed but source_video.mp4 was not created")
    return destination


def media_evidence(path: Path, uri: str) -> dict[str, Any]:
    return {
        "gcsUri": uri,
        "fileName": path.name,
        "sizeBytes": path.stat().st_size,
        "durationSeconds": round(sermon_pipeline.ffprobe_duration(path), 3),
        "sha256": sha256_file(path),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
