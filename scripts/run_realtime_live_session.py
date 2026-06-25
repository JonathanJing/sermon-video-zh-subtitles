#!/usr/bin/env python3
"""Run a live realtime caption session with delayed stable corrections."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPT_DIR = REPO_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import realtime_media_worker  # noqa: E402
import realtime_openai_smoke_test  # noqa: E402
from run_realtime_stabilizer_loop import filter_ready_candidates, read_state, write_state  # noqa: E402
from stabilize_realtime_deltas_with_openai import (  # noqa: E402
    DEFAULT_MODEL as DEFAULT_STABLE_MODEL,
    access_secret,
    batched,
    build_output,
    post_stable_corrections,
    stable_correction_candidates,
    stabilize_batch,
    validate_stable_correction_model,
)
from validate_realtime_session import parse_jsonl  # noqa: E402


DEFAULT_OUT = Path("artifacts/realtime-live-session/report.json")
DEFAULT_STABLE_OUT_DIR = Path("artifacts/realtime-live-session/stable-corrections")


def main() -> int:
    args = parse_args()
    report = run_live_session(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a backend realtime session, stream an authorized live audio source through "
            "gpt-realtime-translate, and run gpt-5.4-mini stable corrections on saved deltas."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--audio-file", type=Path, help="Authorized local audio file, usually for rehearsal.")
    source.add_argument("--audio-url", help="Authorized HTTP(S) live audio source.")
    source.add_argument("--youtube-url", help="Authorized YouTube live URL.")
    parser.add_argument("--api-key-secret", required=True, help="Secret Manager resource for the OpenAI API key.")
    parser.add_argument("--backend-url", required=True, help="Backend/Cloud Run base URL.")
    parser.add_argument("--sunday", required=True)
    parser.add_argument("--admin-token")
    parser.add_argument("--internal-task-token")
    parser.add_argument("--target-language", default=realtime_media_worker.DEFAULT_TARGET_LANGUAGE)
    parser.add_argument("--realtime-model", default=realtime_media_worker.DEFAULT_REALTIME_MODEL)
    parser.add_argument("--stable-model", default=DEFAULT_STABLE_MODEL)
    parser.add_argument("--max-audio-seconds", type=float, help="Optional cap for rehearsals and smoke runs.")
    parser.add_argument("--event-log-dir", type=Path, default=realtime_media_worker.DEFAULT_EVENT_LOG_DIR)
    parser.add_argument(
        "--realtime-event-gcs-prefix",
        default=os.getenv("REALTIME_EVENT_GCS_PREFIX"),
        help="Optional GCS mirror prefix for realtime JSONL events.",
    )
    parser.add_argument(
        "--read-events-from-gcs",
        action="store_true",
        help="Read realtime JSONL from the GCS mirror instead of a local event log.",
    )
    parser.add_argument("--stable-min-age-seconds", type=float, default=4.0)
    parser.add_argument("--stabilizer-interval-seconds", type=float, default=6.0)
    parser.add_argument("--stabilizer-batch-size", type=int, default=4)
    parser.add_argument("--stabilizer-max-windows", type=int, default=40)
    parser.add_argument(
        "--max-stabilizer-iterations",
        type=int,
        default=0,
        help="Optional cap while the worker is still running; 0 means keep going until the worker exits.",
    )
    parser.add_argument("--final-stabilizer-iterations", type=int, default=2)
    parser.add_argument(
        "--require-stable-correction",
        action="store_true",
        help="Fail the report if no stable correction is posted during this run.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--worker-report-out", type=Path)
    parser.add_argument("--stable-out-dir", type=Path, default=DEFAULT_STABLE_OUT_DIR)
    parser.add_argument("--state-file", type=Path)
    args = parser.parse_args()

    if args.audio_file:
        args.audio_file = resolve_repo_path(args.audio_file)
        if not args.audio_file.is_file():
            raise SystemExit(f"--audio-file not found: {args.audio_file}")
    realtime_media_worker.validate_realtime_translation_model(args.realtime_model, args.target_language)
    validate_stable_correction_model(args.stable_model)
    if args.max_audio_seconds is not None and args.max_audio_seconds <= 0:
        raise SystemExit("--max-audio-seconds must be > 0")
    if args.read_events_from_gcs and not args.realtime_event_gcs_prefix:
        raise SystemExit("--read-events-from-gcs requires --realtime-event-gcs-prefix")
    if args.stable_min_age_seconds < 0:
        raise SystemExit("--stable-min-age-seconds must be >= 0")
    if args.stabilizer_interval_seconds <= 0:
        raise SystemExit("--stabilizer-interval-seconds must be > 0")
    if args.stabilizer_batch_size < 1:
        raise SystemExit("--stabilizer-batch-size must be >= 1")
    if args.stabilizer_max_windows < 1:
        raise SystemExit("--stabilizer-max-windows must be >= 1")
    if args.max_stabilizer_iterations < 0:
        raise SystemExit("--max-stabilizer-iterations must be >= 0")
    if args.final_stabilizer_iterations < 0:
        raise SystemExit("--final-stabilizer-iterations must be >= 0")

    args.out = resolve_repo_path(args.out)
    args.worker_report_out = resolve_repo_path(args.worker_report_out or (args.out.parent / "worker-report.json"))
    args.stable_out_dir = resolve_repo_path(args.stable_out_dir)
    args.state_file = resolve_repo_path(args.state_file or (args.stable_out_dir / "stabilizer-state.json"))
    args.event_log_dir = resolve_repo_path(args.event_log_dir)
    return args


def run_live_session(args: argparse.Namespace) -> dict[str, Any]:
    audio = audio_report(args)
    created = realtime_media_worker.create_backend_local_session(
        session_creation_args(args),
        audio_source_kind=str(audio["kind"]),
    )
    session_id = str(created.get("sessionId") or "")
    event_token = str(created.get("eventToken") or "")
    if not session_id or not event_token:
        raise SystemExit("Backend did not return a realtime session id and event token.")

    events_uri = realtime_events_uri(args, session_id)
    api_key = access_secret(args.api_key_secret)
    worker_result: dict[str, Any] = {}
    worker_error: list[str] = []
    worker_thread = threading.Thread(
        target=run_worker_thread,
        kwargs={
            "args": worker_args_from_args(args, session_id, event_token),
            "result": worker_result,
            "error": worker_error,
        },
        daemon=True,
    )
    worker_thread.start()

    iteration_reports: list[dict[str, Any]] = []
    iteration_count = 0
    while worker_thread.is_alive():
        iteration_count += 1
        iteration_reports.append(safe_run_stabilizer_iteration(args, api_key, session_id, event_token, events_uri))
        if args.max_stabilizer_iterations and iteration_count >= args.max_stabilizer_iterations:
            break
        time.sleep(args.stabilizer_interval_seconds)

    worker_thread.join()
    for index in range(args.final_stabilizer_iterations):
        iteration_reports.append(safe_run_stabilizer_iteration(args, api_key, session_id, event_token, events_uri))
        if index < args.final_stabilizer_iterations - 1 and args.stabilizer_interval_seconds:
            time.sleep(args.stabilizer_interval_seconds)

    posted = sum(int(report.get("postedStableCorrections") or 0) for report in iteration_reports)
    worker_report = worker_result.get("report") if isinstance(worker_result.get("report"), dict) else None
    failed_iterations = [report for report in iteration_reports if report.get("status") == "failed"]

    status = "ok"
    if worker_error:
        status = "worker_failed"
    elif not worker_report or worker_report.get("status") != "ok":
        status = "worker_failed"
    elif args.require_stable_correction and failed_iterations:
        status = "stabilizer_failed"
    elif args.require_stable_correction and posted <= 0:
        status = "no_stable_correction"

    return {
        "schemaVersion": 1,
        "status": status,
        "sessionId": session_id,
        "sunday": args.sunday,
        "models": {
            "realtimeDraft": args.realtime_model,
            "stableCorrection": args.stable_model,
        },
        "audio": audio,
        "worker": compact_worker_report(worker_report, worker_error),
        "workerReport": safe_display_path(args.worker_report_out),
        "realtimeEventsJsonl": events_uri,
        "stableCorrection": {
            "iterations": len(iteration_reports),
            "postedStableCorrections": posted,
            "stateFile": safe_display_path(args.state_file),
            "outDir": safe_display_path(args.stable_out_dir),
            "lastReports": iteration_reports[-5:],
            "warnings": stable_correction_warnings(iteration_reports, require_stable_correction=args.require_stable_correction),
        },
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def safe_run_stabilizer_iteration(
    args: argparse.Namespace,
    api_key: str,
    session_id: str,
    event_token: str,
    events_uri: str,
) -> dict[str, Any]:
    try:
        return run_stabilizer_iteration(args, api_key, session_id, event_token, events_uri)
    except SystemExit as exc:
        return stabilizer_failure_report(session_id=session_id, events_uri=events_uri, error=str(exc))
    except Exception as exc:  # pragma: no cover - defensive live-session boundary
        return stabilizer_failure_report(session_id=session_id, events_uri=events_uri, error=str(exc))


def stabilizer_failure_report(*, session_id: str, events_uri: str, error: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "status": "failed",
        "sessionId": session_id,
        "eventsJsonl": safe_uri(events_uri),
        "error": sanitize_live_error(error),
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def stable_correction_warnings(
    reports: list[dict[str, Any]],
    *,
    require_stable_correction: bool,
) -> list[str]:
    if require_stable_correction:
        return []
    if any(report.get("status") == "failed" for report in reports):
        return ["stable_correction_failed_non_blocking"]
    return []


def sanitize_live_error(value: str) -> str:
    text = str(value or "unknown error")
    text = text.replace("\n", " ")
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-REDACTED", text)
    text = re.sub(
        r"projects/[^/\s]+/secrets/[^/\s]+(?:/versions/[^/\s]+)?",
        "projects/REDACTED/secrets/REDACTED/versions/REDACTED",
        text,
    )
    return text[:300]


def run_worker_thread(*, args: argparse.Namespace, result: dict[str, Any], error: list[str]) -> None:
    try:
        result["report"] = realtime_media_worker.run_worker(args)
    except Exception as exc:  # pragma: no cover - defensive boundary for live runner
        error.append(sanitize_live_error(str(exc)))


def run_stabilizer_iteration(
    args: argparse.Namespace,
    api_key: str,
    session_id: str,
    event_token: str,
    events_uri: str,
) -> dict[str, Any]:
    try:
        raw_text = read_events_text(events_uri)
        events = parse_jsonl(raw_text)
    except (FileNotFoundError, subprocess.CalledProcessError, SystemExit) as exc:
        return {
            "schemaVersion": 1,
            "status": "no_events_yet",
            "sessionId": session_id,
            "eventsJsonl": safe_uri(events_uri),
            "reason": str(exc)[:160],
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
        }
    except OSError as exc:
        return {
            "schemaVersion": 1,
            "status": "failed",
            "sessionId": session_id,
            "eventsJsonl": safe_uri(events_uri),
            "error": str(exc)[:160],
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
        }

    state = read_state(args.state_file)
    all_candidates = stable_correction_candidates(events, max_windows=args.stabilizer_max_windows)
    candidates = filter_ready_candidates(
        all_candidates,
        posted_ids=set(state.get("postedSegmentIds") or []),
        min_age_seconds=args.stable_min_age_seconds,
        now=datetime.now(timezone.utc),
    )
    corrections: list[dict[str, Any]] = []
    for batch in batched(candidates, args.stabilizer_batch_size):
        corrections.extend(stabilize_batch(batch, api_key=api_key, model=args.stable_model))

    output = build_output(
        input_jsonl=display_input_path(events_uri),
        model=args.stable_model,
        candidates=candidates,
        corrections=corrections,
        api_key_secret=args.api_key_secret,
    )
    args.stable_out_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.stable_out_dir / f"{safe_path_component(session_id)}.stable-corrections.latest.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    posted = 0
    if corrections:
        posted = post_stable_corrections(
            output=output,
            backend_url=args.backend_url,
            session_id=session_id,
            event_token=event_token,
            model=args.stable_model,
        )
    if posted:
        posted_ids = set(state.get("postedSegmentIds") or [])
        posted_ids.update(item["id"] for item in corrections)
        write_state(
            args.state_file,
            {
                "schemaVersion": 1,
                "sessionId": session_id,
                "model": args.stable_model,
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "postedSegmentIds": sorted(posted_ids),
            },
        )

    return {
        "schemaVersion": 1,
        "status": "ok",
        "sessionId": session_id,
        "eventsJsonl": safe_uri(events_uri),
        "candidateWindows": len(all_candidates),
        "readyWindows": len(candidates),
        "correctedWindows": len(corrections),
        "postedStableCorrections": posted,
        "out": safe_display_path(output_path),
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
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
        openai_safety_identifier="sermon-realtime-live-session",
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


def compact_worker_report(report: dict[str, Any] | None, errors: list[str]) -> dict[str, Any]:
    if errors:
        return {"status": "failed", "errors": errors, "apiKeyMaterialIncluded": False, "secretResourceNamesIncluded": False}
    if not report:
        return {"status": "missing", "apiKeyMaterialIncluded": False, "secretResourceNamesIncluded": False}
    keys = [
        "schemaVersion",
        "status",
        "sessionId",
        "eventsPosted",
        "source",
        "openaiRealtime",
        "apiKeyMaterialIncluded",
        "secretResourceNamesIncluded",
    ]
    compact = {key: report[key] for key in keys if key in report}
    compact["apiKeyMaterialIncluded"] = False
    compact["secretResourceNamesIncluded"] = False
    return compact


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


def safe_uri(uri: str) -> str:
    if uri.startswith("gs://"):
        return uri
    return Path(uri).name


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
