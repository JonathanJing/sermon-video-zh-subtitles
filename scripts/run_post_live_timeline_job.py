#!/usr/bin/env python3
"""Download a completed livestream and stop at the operator timeline-review gate."""

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

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.cloud import (  # noqa: E402
    access_secret,
    download_file_from_gcs,
    read_gcs_text,
    upload_file_to_gcs,
    write_gcs_text,
)
from backend.config import upcoming_sunday  # noqa: E402
from backend.observability import log_event, url_summary  # noqa: E402
from scripts import (  # noqa: E402
    build_multistage_post_live_timeline,
    live_source_monitor,
    run_post_live_subtitle_generation,
    post_live_run_status,
    youtube_data_api,
)


DEFAULT_STATE_URI = "gs://sermon-zh-artifacts-ai-for-god/sundays/live-source-monitor/backend-state.json"
DEFAULT_BUCKET = "sermon-zh-artifacts-ai-for-god"
DEFAULT_WORK_ROOT = Path("/tmp/sermon-post-live-subtitles")


def main() -> int:
    args = parse_args()
    report = run_job(args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(public_report(report), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {
        "waiting_for_source",
        "waiting_for_matching_sunday",
        "waiting_for_post_live",
        "waiting_for_download_access",
        "requires_operator_review",
        "already_requires_operator_review",
    } else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sunday", help="Sunday slice date. Defaults to the upcoming/current Sunday in APP_TIMEZONE.")
    parser.add_argument("--state-file", default=DEFAULT_STATE_URI)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--out", default="/tmp/sermon-post-live-subtitles/job-report.json")
    parser.add_argument("--gcs-bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--gcs-prefix", default="sundays")
    parser.add_argument("--api-key-secret")
    parser.add_argument("--discord-bot-token-secret")
    parser.add_argument("--discord-channel-id")
    parser.add_argument("--notify-sendgrid-secret")
    parser.add_argument("--notify-recipients-secret")
    parser.add_argument("--notify-sender-secret")
    parser.add_argument("--chunk-seconds", type=float, default=120.0, help="Coarse timeline chunk size.")
    parser.add_argument("--transition-chunk-seconds", type=float, default=30.0)
    parser.add_argument("--fine-chunk-seconds", type=float, default=5.0)
    parser.add_argument("--wide-margin-seconds", type=float, default=180.0)
    parser.add_argument("--fine-zone-radius-seconds", type=float, default=75.0)
    parser.add_argument("--timeline-model", default="gpt-transcribe")
    parser.add_argument("--classifier-model", default="gpt-5.6")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high"), default="high")
    parser.add_argument("--audio-format", default="bestaudio[ext=m4a]/bestaudio")
    parser.add_argument("--yt-dlp", default="yt-dlp")
    parser.add_argument("--youtube-cookies-secret")
    parser.add_argument("--youtube-api-key-secret")
    parser.add_argument("--allow-non-post-live", action="store_true")
    parser.set_defaults(persist_run_status=True)
    return parser.parse_args()


def run_job(
    args: argparse.Namespace,
    *,
    metadata_loader: Callable[[str], dict[str, Any] | None] | None = None,
    runner: Callable[..., Any] | None = None,
    uploader: Callable[[str | Path, str], None] = upload_file_to_gcs,
    marker_reader: Callable[[str], dict[str, Any] | None] | None = None,
    marker_writer: Callable[[str, str], None] = write_gcs_text,
    notifier: Callable[[argparse.Namespace, dict[str, Any]], dict[str, Any]] | None = None,
    handoff_reader: Callable[[str], dict[str, Any] | None] | None = None,
    gcs_downloader: Callable[[str, str | Path], Path] = download_file_from_gcs,
) -> dict[str, Any]:
    sunday = args.sunday or upcoming_sunday().isoformat()
    state = live_source_monitor.read_state(args.state_file)
    source = run_post_live_subtitle_generation.selected_source_from_state(state)
    live_url = run_post_live_subtitle_generation.live_url_from_state(state, source)
    checked_at = datetime.now(timezone.utc).isoformat()
    base = {
        "schemaVersion": 1,
        "status": "waiting_for_source",
        "stage": "post_live_timeline_job",
        "sunday": sunday,
        "checkedAt": checked_at,
        "stateFile": args.state_file,
        "liveSource": url_summary(live_url) if live_url else None,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }
    if not live_url:
        return finish({**base, "reason": "captured_state_has_no_live_url"})
    if state.get("lastSunday") and state.get("lastSunday") != sunday:
        return finish({
            **base,
            "status": "waiting_for_matching_sunday",
            "reason": f"captured state is for {state.get('lastSunday')}",
        })

    slug = run_post_live_subtitle_generation.slug_for(argparse.Namespace(slug=None), live_url)
    prefix = "/".join(part.strip("/") for part in [args.gcs_prefix, sunday, "post-live-subtitles", slug])
    run_root = args.work_root / sunday / slug
    run_status_path = run_root / "run-status.json"
    run_status_uri = f"gs://{args.gcs_bucket}/{prefix}/run-status.json"
    run_status = load_local_status(run_status_path, sunday, live_url)
    run_status = post_live_run_status.update_stage(run_status, sunday, "source_saved", "complete", source_url=live_url)
    persist_status(run_status, run_status_path, run_status_uri, args, marker_writer)

    cookies_path = materialize_youtube_cookies(args.youtube_cookies_secret, args.work_root)
    if metadata_loader:
        metadata = metadata_loader(live_url)
        metadata_diagnostics = {"selectedProvider": "injected-metadata-loader", "fallbackUsed": False}
    else:
        metadata, metadata_diagnostics = youtube_metadata_with_data_api(
            live_url,
            api_key_secret=args.youtube_api_key_secret,
            yt_dlp=args.yt_dlp,
            cookies_path=cookies_path,
        )
    if not (run_post_live_subtitle_generation.is_post_live_ready(metadata) or args.allow_non_post_live):
        run_status = post_live_run_status.update_stage(
            run_status, sunday, "archive_ready", "blocked", reason="livestream_not_finished"
        )
        persist_status(run_status, run_status_path, run_status_uri, args, marker_writer)
        return finish({
            **base,
            "status": "waiting_for_post_live",
            "reason": "live source is not post_live/was_live yet",
            "metadata": run_post_live_subtitle_generation.safe_metadata(metadata),
            "metadataDiagnostics": metadata_diagnostics,
        })

    run_status = post_live_run_status.update_stage(run_status, sunday, "archive_ready", "complete")
    persist_status(run_status, run_status_path, run_status_uri, args, marker_writer)
    marker_uri = f"gs://{args.gcs_bucket}/{prefix}/timeline/job-report.json"
    existing = (marker_reader or read_optional_gcs_json)(marker_uri)
    if existing and existing.get("status") == "requires_operator_review":
        notification = existing.get("notification") or {}
        if notification.get("status") != "sent" and args.discord_bot_token_secret and args.discord_channel_id:
            existing["notification"] = (notifier or send_discord_notification)(args, existing)
            marker_writer(marker_uri, json.dumps(existing, ensure_ascii=False, indent=2, sort_keys=True))
        return finish({**existing, "status": "already_requires_operator_review", "deduped": True})

    handoff_uri = f"gs://{args.gcs_bucket}/{prefix}/download/local-download-manifest.json"
    handoff = (handoff_reader or read_optional_gcs_json)(handoff_uri)
    handoff_audio = handoff.get("audio") if isinstance(handoff, dict) and handoff.get("status") == "complete" else None
    handoff_audio_uri = handoff_audio.get("gcsUri") if isinstance(handoff_audio, dict) else None
    run_status = post_live_run_status.update_stage(run_status, sunday, "downloaded", "running")
    persist_status(run_status, run_status_path, run_status_uri, args, marker_writer)
    if isinstance(handoff_audio_uri, str) and handoff_audio_uri.startswith("gs://"):
        suffix = Path(handoff_audio_uri).suffix or ".m4a"
        audio_path = gcs_downloader(handoff_audio_uri, run_root / "download" / f"source_audio{suffix}")
        audio_uri = handoff_audio_uri
        download_source = "local-gcs-handoff"
    else:
        audio_template = run_root / "download" / "source_audio.%(ext)s"
        actual_runner = runner or __import__("subprocess").run
        download_started = time.monotonic()
        try:
            audio_path = run_post_live_subtitle_generation.download_archive_audio(
                live_url,
                audio_template,
                args.audio_format,
                args.yt_dlp,
                actual_runner,
                cookies_path=cookies_path,
            )
        except Exception as exc:
            run_status = post_live_run_status.update_stage(
                run_status,
                sunday,
                "downloaded",
                "blocked",
                reason="youtube_download_authorization_required",
                duration_seconds=time.monotonic() - download_started,
            )
            persist_status(run_status, run_status_path, run_status_uri, args, marker_writer)
            blocked_report = {
                **base,
                "status": "waiting_for_download_access",
                "reason": "youtube_metadata_ready_but_archive_download_failed",
                "metadata": run_post_live_subtitle_generation.safe_metadata(metadata),
                "metadataDiagnostics": metadata_diagnostics,
                "localHandoffGcsUri": handoff_uri,
                "localHandoffReady": False,
                "downloadDiagnostics": {
                    "downloader": "yt-dlp",
                    "cookiesConfigured": bool(cookies_path),
                    "errorClass": exc.__class__.__name__,
                },
                "nextAction": "Run run_local_post_live_download.py or configure --youtube-cookies-secret.",
                "runStatusGcsUri": run_status_uri,
            }
            blocked_report["notification"] = (notifier or send_discord_notification)(args, blocked_report)
            return finish(blocked_report)
        audio_uri = f"gs://{args.gcs_bucket}/{prefix}/download/{audio_path.name}"
        uploader(audio_path, audio_uri)
        download_source = "cloud-youtube-direct"

    run_status = post_live_run_status.update_stage(
        run_status,
        sunday,
        "downloaded",
        "complete",
        artifact=audio_uri,
        duration_seconds=(time.monotonic() - download_started) if "download_started" in locals() else 0.0,
    )
    persist_status(run_status, run_status_path, run_status_uri, args, marker_writer)

    timeline_outdir = run_root / "timeline"
    timeline_path = timeline_outdir / "report.json"
    timeline_args = argparse.Namespace(
        input=audio_path,
        out=timeline_path,
        outdir=timeline_outdir,
        coarse_chunk_seconds=args.chunk_seconds,
        transition_chunk_seconds=args.transition_chunk_seconds,
        fine_chunk_seconds=args.fine_chunk_seconds,
        wide_margin_seconds=args.wide_margin_seconds,
        fine_zone_radius_seconds=args.fine_zone_radius_seconds,
        transcription_model=args.timeline_model,
        classifier_model=args.classifier_model,
        reasoning_effort=args.reasoning_effort,
        api_key_secret=args.api_key_secret,
    )
    timeline = build_multistage_post_live_timeline.build_multistage_timeline(timeline_args)
    timeline_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    timeline_uri = f"gs://{args.gcs_bucket}/{prefix}/timeline/report.json"
    uploader(timeline_path, timeline_uri)
    stage_artifact_uris = {}
    for relative in (
        "coarse_120s/timeline_chunks.json",
        "transition_30s/timeline_chunks.json",
        "start_fine_5s/timeline_chunks.json",
        "end_fine_5s/timeline_chunks.json",
        "classifier/coarse.json",
        "classifier/transition.json",
        "classifier/exact.json",
    ):
        artifact_path = timeline_outdir / relative
        if artifact_path.exists():
            uri = f"gs://{args.gcs_bucket}/{prefix}/timeline/{relative}"
            uploader(artifact_path, uri)
            stage_artifact_uris[relative] = uri

    suggested = (timeline.get("analysis") or {}).get("suggestedWindow")
    report = {
        **base,
        "status": "requires_operator_review",
        "stage": "timeline_probed",
        "metadata": run_post_live_subtitle_generation.safe_metadata(metadata),
        "metadataDiagnostics": metadata_diagnostics,
        "slug": slug,
        "sourceUrl": live_url,
        "downloadedAudio": str(audio_path),
        "audioGcsUri": audio_uri,
        "downloadSource": download_source,
        "localHandoffGcsUri": handoff_uri,
        "timelineGcsUri": timeline_uri,
        "runStatusGcsUri": run_status_uri,
        "timelineStageArtifactGcsUris": stage_artifact_uris,
        "suggestedWindow": suggested,
        "reviewInstructions": (
            "Open the completed livestream, independently verify sermon start/end, then compare with suggestedWindow. "
            "Only confirmed local audio times may be used for generate-reviewed."
        ),
        "completedAt": datetime.now(timezone.utc).isoformat(),
    }
    report["notification"] = (notifier or send_discord_notification)(args, report)
    marker_writer(marker_uri, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return finish(report)


def read_optional_gcs_json(uri: str) -> dict[str, Any] | None:
    try:
        return json.loads(read_gcs_text(uri))
    except Exception as exc:
        if exc.__class__.__name__ in {"NotFound", "NoSuchKey"} or "404" in str(exc):
            return None
        raise


def materialize_youtube_cookies(secret_name: str | None, work_root: Path) -> Path | None:
    if not secret_name:
        return None
    value = access_secret(secret_name)
    path = work_root / ".secrets" / "youtube.cookies.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def load_local_status(path: Path, sunday: str, live_url: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("sunday") == sunday:
            return payload
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return post_live_run_status.new_status(sunday, source_url=live_url)


def persist_status(
    payload: dict[str, Any],
    path: Path,
    uri: str,
    args: argparse.Namespace,
    writer: Callable[[str, str], None],
) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if getattr(args, "persist_run_status", False):
        writer(uri, text)


def youtube_metadata(live_url: str, *, yt_dlp: str, cookies_path: Path | None) -> dict[str, Any] | None:
    command = [
        yt_dlp,
        "--dump-single-json",
        "--skip-download",
        "--no-warnings",
        "--quiet",
        "--no-playlist",
        "--js-runtimes",
        "node",
    ]
    if cookies_path:
        command.extend(["--cookies", str(cookies_path)])
    command.append(live_url)
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=60)
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def youtube_metadata_with_data_api(
    live_url: str,
    *,
    api_key_secret: str | None,
    yt_dlp: str,
    cookies_path: Path | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    video_id = live_source_monitor.youtube_video_id_from_url(live_url)
    data_api_error = None
    if api_key_secret and video_id:
        try:
            api_key = access_secret(api_key_secret)
            metadata = youtube_data_api.video_metadata(video_id, api_key=api_key)
            if metadata:
                return metadata, {
                    "selectedProvider": "youtube-data-api-v3",
                    "fallbackUsed": False,
                    "videoFound": True,
                }
            data_api_error = "video_not_found_or_not_public"
        except Exception as exc:
            data_api_error = f"{exc.__class__.__name__}: {str(exc)[:300]}"
    elif api_key_secret:
        data_api_error = "video_id_not_found_in_url"
    else:
        data_api_error = "youtube_api_key_secret_not_configured"

    metadata = youtube_metadata(live_url, yt_dlp=yt_dlp, cookies_path=cookies_path)
    return metadata, {
        "selectedProvider": "yt-dlp" if metadata else None,
        "fallbackUsed": True,
        "dataApiError": data_api_error,
    }


def send_discord_notification(args: argparse.Namespace, report: dict[str, Any]) -> dict[str, Any]:
    window = report.get("suggestedWindow") or {}
    if report.get("status") == "waiting_for_download_access":
        lines = [
            "⚠️ **直播录像已结束，但云端下载授权失败**",
            f"日期：{report.get('sunday')}",
            f"直播：{(report.get('liveSource') or {}).get('host', 'YouTube')}",
            f"交接位置：`{report.get('localHandoffGcsUri')}`",
            "下一步：本机运行 run_local_post_live_download.py；上传完成后云任务会自动续跑，无需重做已完成阶段。",
        ]
    else:
        lines = [
            "🔔 **主日直播已结束，完整音频与时间轴已准备好**",
            f"日期：{report.get('sunday')}",
            f"直播：{report.get('sourceUrl')}",
            f"机器建议证道窗口：{window.get('startTimecode') or '未识别'} → {window.get('endTimecode') or '未识别'}",
            f"完整音频：`{report.get('audioGcsUri')}`",
            f"时间轴报告：`{report.get('timelineGcsUri')}`",
            "请人工观看录像，独立记录证道开始和结束时间，再与机器建议比较。确认后才能启动 generate-reviewed。",
        ]
    content = "\n".join(lines)
    if not args.discord_bot_token_secret or not args.discord_channel_id:
        return live_source_monitor.send_sendgrid_notification(
            getattr(args, "notify_sendgrid_secret", None),
            getattr(args, "notify_recipients_secret", None),
            getattr(args, "notify_sender_secret", None),
            {"title": lines[0].replace("**", "").strip("🔔⚠️ "), "message": content},
        )
    token = access_secret(args.discord_bot_token_secret)
    response = requests.post(
        f"https://discord.com/api/v10/channels/{args.discord_channel_id}/messages",
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
        json={"content": content},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return {"status": "sent", "messageId": payload.get("id"), "channelId": args.discord_channel_id}


def finish(report: dict[str, Any]) -> dict[str, Any]:
    log_event(
        "post_live_timeline_job_checked",
        component="post-live-timeline-job",
        sunday=report.get("sunday"),
        status=report.get("status"),
        liveSource=report.get("liveSource"),
        timelineGcsUri=report.get("timelineGcsUri"),
    )
    return report


def public_report(report: dict[str, Any]) -> dict[str, Any]:
    return {**report, "apiKeyMaterialIncluded": False, "secretResourceNamesIncluded": False}


if __name__ == "__main__":
    raise SystemExit(main())
