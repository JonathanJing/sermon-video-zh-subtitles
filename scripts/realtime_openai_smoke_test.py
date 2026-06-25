#!/usr/bin/env python3
"""Run a real OpenAI Realtime translation smoke test with an authorized audio file."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sys
from typing import Any
from urllib.parse import quote
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPT_DIR = REPO_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import realtime_media_worker  # noqa: E402
from validate_realtime_session import (  # noqa: E402
    parse_jsonl,
    read_text as read_validation_text,
    validate_realtime_session,
)


DEFAULT_OUT = Path("artifacts/realtime-openai-smoke/report.json")


def main() -> int:
    args = parse_args()
    report = run_smoke(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify authorized audio -> gpt-realtime-translate -> backend event stream."
    )
    parser.add_argument("--audio-file", type=Path, required=True, help="Short authorized speech audio file.")
    parser.add_argument("--api-key-secret", required=True, help="Secret Manager resource for the OpenAI API key.")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8080")
    parser.add_argument("--sunday", required=True)
    parser.add_argument("--admin-token")
    parser.add_argument("--internal-task-token")
    parser.add_argument("--max-audio-seconds", type=float, default=12.0)
    parser.add_argument("--target-language", default=realtime_media_worker.DEFAULT_TARGET_LANGUAGE)
    parser.add_argument("--model", default=realtime_media_worker.DEFAULT_REALTIME_MODEL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--worker-report-out", type=Path)
    parser.add_argument("--session-validation-out", type=Path)
    parser.add_argument(
        "--skip-session-validation",
        action="store_true",
        help="Do not validate the archived backend session JSONL after the smoke run.",
    )
    parser.add_argument("--event-log-dir", type=Path, default=realtime_media_worker.DEFAULT_EVENT_LOG_DIR)
    parser.add_argument(
        "--realtime-event-gcs-prefix",
        default=os.getenv("REALTIME_EVENT_GCS_PREFIX"),
        help="Optional GCS mirror prefix for realtime JSONL events.",
    )
    parser.add_argument("--sse-timeout-seconds", type=float, default=12.0)
    args = parser.parse_args()
    args.audio_file = resolve_repo_path(args.audio_file)
    args.out = resolve_repo_path(args.out)
    args.worker_report_out = resolve_repo_path(args.worker_report_out or (args.out.parent / "worker-report.json"))
    args.session_validation_out = resolve_repo_path(
        args.session_validation_out or (args.out.parent / "realtime-session-validation.json")
    )
    args.event_log_dir = resolve_repo_path(args.event_log_dir)
    if not args.audio_file.is_file():
        raise SystemExit(f"--audio-file not found: {args.audio_file}")
    return args


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    worker_args = worker_args_from_smoke_args(args)
    worker_report = realtime_media_worker.run_worker(worker_args)
    session_id = str(worker_report.get("sessionId") or "")
    sse_events = read_sse_events(
        backend_url=args.backend_url,
        session_id=session_id,
        timeout_seconds=args.sse_timeout_seconds,
        max_events=80,
    )
    caption_events = [
        event
        for event in sse_events
        if event.get("type") in {"caption_delta", "caption_final"}
        and str(event.get("source") or "").startswith("openai_")
    ]
    input_events = [
        event
        for event in sse_events
        if event.get("type") in {"input_transcript_delta", "input_transcript_final"}
        and str(event.get("source") or "").startswith("openai_")
    ]
    if caption_events and input_events:
        status = "ok"
    elif caption_events:
        status = "missing_input_transcript"
    else:
        status = "no_transcript"
    if worker_report.get("status") != "ok":
        status = "worker_failed"
    warnings: list[str] = []
    if caption_events and not input_events:
        warnings.append("openai_input_transcript_unavailable")
    realtime_events_uri = realtime_events_jsonl_uri(args=args, session_id=session_id)
    session_validation = run_session_validation(
        args=args,
        events_uri=realtime_events_uri,
        should_validate=worker_report.get("status") == "ok" and bool(realtime_events_uri),
    )
    if status == "ok" and session_validation and session_validation.get("status") != "ok":
        status = "validation_failed"
        warnings.append("session_validation_failed")
    report = {
        "schemaVersion": 1,
        "status": status,
        "sessionId": session_id,
        "model": args.model,
        "targetLanguage": args.target_language,
        "audio": {
            "file": safe_display_path(args.audio_file),
            "maxAudioSeconds": args.max_audio_seconds,
        },
        "workerReport": safe_display_path(args.worker_report_out),
        "realtimeEventsJsonl": realtime_events_uri,
        "sessionValidation": session_validation,
        "openaiRealtime": {
            "audioChunksSent": nested(worker_report, "openaiRealtime", "audioChunksSent"),
            "openaiEventsReceived": nested(worker_report, "openaiRealtime", "openaiEventsReceived"),
            "captionEventsPosted": nested(worker_report, "openaiRealtime", "captionEventsPosted"),
            "inputTranscriptEventsPosted": nested(worker_report, "openaiRealtime", "inputTranscriptEventsPosted"),
            "eventTypeCounts": nested(worker_report, "openaiRealtime", "eventTypeCounts"),
            "inputTranscriptSidecar": nested(worker_report, "openaiRealtime", "inputTranscriptSidecar"),
            "inputTranscriptFallback": nested(worker_report, "openaiRealtime", "inputTranscriptFallback"),
        },
        "sse": {
            "eventsRead": len(sse_events),
            "captionEvents": len(caption_events),
            "inputTranscriptEvents": len(input_events),
        },
        "inputTranscriptAvailable": bool(input_events),
        "warnings": warnings,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }
    return report


def run_session_validation(
    *,
    args: argparse.Namespace,
    events_uri: str | None,
    should_validate: bool,
) -> dict[str, Any]:
    out_path = args.session_validation_out
    if getattr(args, "skip_session_validation", False):
        return {"status": "skipped", "reason": "skip_session_validation", "report": safe_display_path(out_path)}
    if not should_validate or not events_uri:
        return {"status": "skipped", "reason": "session_events_unavailable", "report": safe_display_path(out_path)}
    try:
        raw_text = read_validation_text(events_uri)
        validation_report = validate_realtime_session(
            events=parse_jsonl(raw_text),
            raw_text=raw_text,
            events_uri=events_uri,
            expected_model=args.model,
            require_model_event=True,
            require_stable_correction=False,
            min_caption_events=1,
            min_input_events=1,
        )
    except (Exception, SystemExit) as exc:
        validation_report = {
            "schemaVersion": 1,
            "status": "failed",
            "eventsJsonl": events_uri,
            "failedChecks": ["session_validation_read_or_parse"],
            "error": str(exc)[:300],
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
        }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(validation_report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "status": validation_report.get("status"),
        "report": safe_display_path(out_path),
        "failedChecks": validation_report.get("failedChecks", []),
        "counts": validation_report.get("counts"),
    }


def worker_args_from_smoke_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        audio_file=args.audio_file,
        audio_url=None,
        youtube_url=None,
        replay_jsonl=None,
        sunday=args.sunday,
        backend_url=args.backend_url,
        session_id=None,
        event_token=None,
        create_backend_session=True,
        admin_token=args.admin_token,
        internal_task_token=args.internal_task_token,
        event_log_dir=args.event_log_dir,
        out_dir=realtime_media_worker.DEFAULT_OUT_DIR,
        report_out=args.worker_report_out,
        yt_dlp="yt-dlp",
        ffmpeg="ffmpeg",
        sample_rate=24000,
        model=args.model,
        target_language=args.target_language,
        dry_run=False,
        connect_openai=True,
        api_key_secret=args.api_key_secret,
        openai_api_key_env="OPENAI_API_KEY",
        openai_safety_identifier="sermon-realtime-smoke-test",
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


def read_sse_events(
    *,
    backend_url: str,
    session_id: str,
    timeout_seconds: float,
    max_events: int,
) -> list[dict[str, Any]]:
    if not session_id:
        return []
    url = f"{normalize_backend_url(backend_url)}/api/realtime/sessions/{quote(session_id)}/events?cursor=0"
    events: list[dict[str, Any]] = []
    try:
        with urlopen(url, timeout=timeout_seconds) as response:
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
                if len(events) >= max_events or has_openai_caption_and_input(events):
                    break
    except (TimeoutError, socket.timeout, OSError):
        return events
    return events


def has_openai_caption_and_input(events: list[dict[str, Any]]) -> bool:
    has_caption = any(
        event.get("type") in {"caption_delta", "caption_final"}
        and str(event.get("source") or "").startswith("openai_")
        for event in events
    )
    has_input = any(
        event.get("type") in {"input_transcript_delta", "input_transcript_final"}
        and str(event.get("source") or "").startswith("openai_")
        for event in events
    )
    return has_caption and has_input


def nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def normalize_backend_url(value: str) -> str:
    clean = str(value or "").strip().rstrip("/")
    if not clean.startswith(("http://", "https://")):
        raise SystemExit("--backend-url must start with http:// or https://")
    return clean


def realtime_events_jsonl_uri(*, args: argparse.Namespace, session_id: str) -> str | None:
    if not session_id:
        return None
    prefix = getattr(args, "realtime_event_gcs_prefix", None)
    if not prefix:
        return str(args.event_log_dir / f"{safe_path_component(session_id)}.jsonl")
    return realtime_events_gcs_uri(
        prefix=prefix,
        sunday=args.sunday,
        session_id=session_id,
    )


def realtime_events_gcs_uri(*, prefix: str | None, sunday: str, session_id: str) -> str | None:
    clean_prefix = str(prefix or "").strip().rstrip("/")
    if not clean_prefix or not session_id:
        return None
    if not clean_prefix.startswith("gs://"):
        raise SystemExit("--realtime-event-gcs-prefix must start with gs://")
    safe_sunday = safe_path_component(sunday or "unknown-sunday")
    safe_session = safe_path_component(session_id)
    return f"{clean_prefix}/{safe_sunday}/{safe_session}.jsonl"


def safe_path_component(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in str(value))[:80]


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
