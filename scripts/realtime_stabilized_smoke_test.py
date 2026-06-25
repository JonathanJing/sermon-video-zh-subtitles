#!/usr/bin/env python3
"""Run realtime draft translation and one delayed stable-correction smoke pass."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPT_DIR = REPO_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import realtime_media_worker  # noqa: E402
import realtime_openai_smoke_test  # noqa: E402
from run_realtime_stabilizer_loop import filter_ready_candidates  # noqa: E402
from stabilize_realtime_deltas_with_openai import (  # noqa: E402
    DEFAULT_MODEL as DEFAULT_STABLE_MODEL,
    access_secret,
    batched,
    build_output,
    post_stable_corrections,
    stable_correction_candidates,
    stabilize_batch,
)
from validate_realtime_session import parse_jsonl, validate_realtime_session  # noqa: E402


DEFAULT_OUT = Path("artifacts/realtime-stabilized-smoke/report.json")
DEFAULT_STABLE_OUT_DIR = Path("artifacts/realtime-stabilized-smoke/stable-corrections")


def main() -> int:
    args = parse_args()
    report = run_stabilized_smoke(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify authorized audio -> gpt-realtime-translate draft events -> "
            "gpt-5.5-mini stable correction -> backend realtime event stream."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--audio-file", type=Path, help="Short authorized speech audio file.")
    source.add_argument("--audio-url", help="Authorized HTTP(S) audio stream URL.")
    source.add_argument("--youtube-url", help="Authorized YouTube live/archive URL.")
    parser.add_argument("--api-key-secret", required=True, help="Secret Manager resource for the OpenAI API key.")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8080")
    parser.add_argument("--sunday", required=True)
    parser.add_argument("--admin-token")
    parser.add_argument("--internal-task-token")
    parser.add_argument("--max-audio-seconds", type=float, default=12.0)
    parser.add_argument("--target-language", default=realtime_media_worker.DEFAULT_TARGET_LANGUAGE)
    parser.add_argument("--realtime-model", default=realtime_media_worker.DEFAULT_REALTIME_MODEL)
    parser.add_argument("--stable-model", default=DEFAULT_STABLE_MODEL)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-windows", type=int, default=12)
    parser.add_argument("--stable-min-age-seconds", type=float, default=0.0)
    parser.add_argument("--event-log-dir", type=Path, default=realtime_media_worker.DEFAULT_EVENT_LOG_DIR)
    parser.add_argument(
        "--realtime-event-gcs-prefix",
        default=os.getenv("REALTIME_EVENT_GCS_PREFIX"),
        help="Optional GCS mirror prefix for realtime JSONL events.",
    )
    parser.add_argument(
        "--read-events-from-gcs",
        action="store_true",
        help="Read realtime JSONL from the GCS mirror instead of the local event log.",
    )
    parser.add_argument("--sse-timeout-seconds", type=float, default=12.0)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--worker-report-out", type=Path)
    parser.add_argument("--stable-out-dir", type=Path, default=DEFAULT_STABLE_OUT_DIR)
    args = parser.parse_args()

    if args.audio_file:
        args.audio_file = resolve_repo_path(args.audio_file)
        if not args.audio_file.is_file():
            raise SystemExit(f"--audio-file not found: {args.audio_file}")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")
    if args.max_windows < 1:
        raise SystemExit("--max-windows must be >= 1")
    if args.stable_min_age_seconds < 0:
        raise SystemExit("--stable-min-age-seconds must be >= 0")
    if args.read_events_from_gcs and not args.realtime_event_gcs_prefix:
        raise SystemExit("--read-events-from-gcs requires --realtime-event-gcs-prefix")

    args.out = resolve_repo_path(args.out)
    args.worker_report_out = resolve_repo_path(args.worker_report_out or (args.out.parent / "worker-report.json"))
    args.stable_out_dir = resolve_repo_path(args.stable_out_dir)
    args.event_log_dir = resolve_repo_path(args.event_log_dir)
    return args


def run_stabilized_smoke(args: argparse.Namespace) -> dict[str, Any]:
    created = realtime_media_worker.create_backend_local_session(session_creation_args(args))
    session_id = str(created.get("sessionId") or "")
    event_token = str(created.get("eventToken") or "")
    if not session_id or not event_token:
        raise SystemExit("Backend did not return a realtime session id and event token.")

    worker_report = realtime_media_worker.run_worker(worker_args_from_args(args, session_id, event_token))
    sse_events = realtime_openai_smoke_test.read_sse_events(
        backend_url=args.backend_url,
        session_id=session_id,
        timeout_seconds=args.sse_timeout_seconds,
        max_events=120,
    )
    draft_caption_events = [
        event
        for event in sse_events
        if event.get("type") in {"caption_delta", "caption_final"}
        and str(event.get("source") or "").startswith("openai_realtime")
    ]
    draft_input_events = [
        event
        for event in sse_events
        if event.get("type") in {"input_transcript_delta", "input_transcript_final"}
        and str(event.get("source") or "").startswith("openai_realtime")
    ]

    events_uri = realtime_events_uri(args, session_id)
    raw_before = read_events_text(events_uri)
    events_before = parse_jsonl(raw_before)
    candidates = filter_ready_candidates(
        stable_correction_candidates(events_before, max_windows=args.max_windows),
        posted_ids=set(),
        min_age_seconds=args.stable_min_age_seconds,
        now=datetime.now(timezone.utc),
    )

    corrections: list[dict[str, Any]] = []
    api_key = access_secret(args.api_key_secret)
    for batch in batched(candidates, args.batch_size):
        corrections.extend(stabilize_batch(batch, api_key=api_key, model=args.stable_model))

    stable_output = build_output(
        input_jsonl=display_input_path(events_uri),
        model=args.stable_model,
        candidates=candidates,
        corrections=corrections,
        api_key_secret=args.api_key_secret,
    )
    args.stable_out_dir.mkdir(parents=True, exist_ok=True)
    stable_output_path = args.stable_out_dir / f"{safe_path_component(session_id)}.stable-corrections.json"
    stable_output_path.write_text(json.dumps(stable_output, ensure_ascii=False, indent=2), encoding="utf-8")

    posted = post_stable_corrections(
        output=stable_output,
        backend_url=args.backend_url,
        session_id=session_id,
        event_token=event_token,
        model=args.stable_model,
    )

    raw_after = read_events_text(events_uri)
    events_after = parse_jsonl(raw_after)
    validation = validate_realtime_session(
        events=events_after,
        raw_text=raw_after,
        events_uri=events_uri,
        expected_model=args.realtime_model,
        expected_stable_model=args.stable_model,
        require_model_event=True,
        require_stable_correction=True,
        min_caption_events=1,
        min_input_events=1,
    )

    status = "ok"
    if worker_report.get("status") != "ok":
        status = "worker_failed"
    elif not draft_caption_events or not draft_input_events:
        status = "no_realtime_draft"
    elif not posted:
        status = "no_stable_correction"
    elif validation.get("status") != "ok":
        status = "validation_failed"

    return {
        "schemaVersion": 1,
        "status": status,
        "sessionId": session_id,
        "sunday": args.sunday,
        "models": {
            "realtimeDraft": args.realtime_model,
            "stableCorrection": args.stable_model,
        },
        "audio": audio_report(args),
        "workerReport": safe_display_path(args.worker_report_out),
        "realtimeEventsJsonl": events_uri,
        "stableCorrection": {
            "candidateWindows": len(candidates),
            "correctedWindows": len(corrections),
            "postedStableCorrections": posted,
            "out": safe_display_path(stable_output_path),
        },
        "sse": {
            "eventsRead": len(sse_events),
            "draftCaptionEvents": len(draft_caption_events),
            "draftInputTranscriptEvents": len(draft_input_events),
        },
        "validation": validation,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def session_creation_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        sunday=args.sunday,
        model=args.realtime_model,
        target_language=args.target_language,
        backend_url=args.backend_url,
        admin_token=args.admin_token,
        internal_task_token=args.internal_task_token,
    )


def worker_args_from_args(args: argparse.Namespace, session_id: str, event_token: str) -> argparse.Namespace:
    return argparse.Namespace(
        audio_file=args.audio_file,
        audio_url=args.audio_url,
        youtube_url=args.youtube_url,
        replay_jsonl=None,
        sunday=args.sunday,
        backend_url=args.backend_url,
        session_id=session_id,
        event_token=event_token,
        create_backend_session=False,
        admin_token=args.admin_token,
        internal_task_token=args.internal_task_token,
        event_log_dir=args.event_log_dir,
        out_dir=realtime_media_worker.DEFAULT_OUT_DIR,
        report_out=args.worker_report_out,
        yt_dlp="yt-dlp",
        ffmpeg="ffmpeg",
        sample_rate=24000,
        model=args.realtime_model,
        target_language=args.target_language,
        dry_run=False,
        connect_openai=True,
        api_key_secret=args.api_key_secret,
        openai_api_key_env="OPENAI_API_KEY",
        openai_safety_identifier="sermon-realtime-stabilized-smoke-test",
        disable_input_transcript_sidecar=True,
        input_transcript_session_model=realtime_media_worker.DEFAULT_REALTIME_INPUT_TRANSCRIPT_SESSION_MODEL,
        input_transcript_model=realtime_media_worker.DEFAULT_REALTIME_INPUT_TRANSCRIPT_MODEL,
        input_transcript_language=realtime_media_worker.DEFAULT_REALTIME_INPUT_TRANSCRIPT_LANGUAGE,
        input_transcript_delay=realtime_media_worker.DEFAULT_REALTIME_INPUT_TRANSCRIPT_DELAY,
        input_transcript_commit_ms=2000,
        disable_input_transcript_audio_api_fallback=False,
        input_transcript_fallback_model=realtime_media_worker.DEFAULT_INPUT_TRANSCRIPT_FALLBACK_MODEL,
        chunk_ms=100,
        max_audio_seconds=args.max_audio_seconds,
        no_realtime_throttle=False,
        openai_close_timeout=20.0,
        prepare_audio=False,
        max_replay_events=200,
    )


def realtime_events_uri(args: argparse.Namespace, session_id: str) -> str:
    if args.read_events_from_gcs:
        return realtime_openai_smoke_test.realtime_events_jsonl_uri(
            prefix=args.realtime_event_gcs_prefix,
            sunday=args.sunday,
            session_id=session_id,
        )
    return str(args.event_log_dir / f"{safe_path_component(session_id)}.jsonl")


def read_events_text(uri: str) -> str:
    if uri.startswith("gs://"):
        completed = subprocess.run(["gcloud", "storage", "cat", uri], check=True, capture_output=True, text=True)
        return completed.stdout
    return Path(uri).read_text(encoding="utf-8")


def display_input_path(events_uri: str) -> Path:
    if events_uri.startswith("gs://"):
        return Path(f"gcs-{safe_path_component(events_uri)}.jsonl")
    return Path(events_uri)


def audio_report(args: argparse.Namespace) -> dict[str, Any]:
    if args.audio_file:
        return {
            "kind": "authorized_audio_file",
            "file": safe_display_path(args.audio_file),
            "maxAudioSeconds": args.max_audio_seconds,
        }
    if args.audio_url:
        return {
            "kind": "authorized_audio_url",
            "display": realtime_media_worker.redact_url(args.audio_url),
            "maxAudioSeconds": args.max_audio_seconds,
        }
    return {
        "kind": "authorized_youtube_source",
        "display": realtime_media_worker.redact_url(args.youtube_url),
        "maxAudioSeconds": args.max_audio_seconds,
    }


def safe_path_component(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in str(value))[:120]


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def safe_display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.name


if __name__ == "__main__":
    raise SystemExit(main())
