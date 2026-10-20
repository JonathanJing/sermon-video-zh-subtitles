#!/usr/bin/env python3
"""Server-side realtime media worker scaffold.

This worker is the Cloud Run producer counterpart to the browser WebRTC path.
It validates an authorized audio source, optionally prepares normalized audio,
and writes sanitized realtime events to the same backend session event contract
used by the public caption view.
"""

from __future__ import annotations

import argparse
import base64
import mimetypes
import os
import json
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.realtime import (  # noqa: E402
    DEFAULT_REALTIME_MODEL,
    DEFAULT_TARGET_LANGUAGE,
    RealtimeEventArchive,
    RealtimeSessionStore,
    realtime_translation_policy_error,
    resolve_openai_api_key,
)


DEFAULT_EVENT_LOG_DIR = Path("/tmp/sermon-realtime-events")
DEFAULT_OUT_DIR = Path("artifacts/realtime-media-worker")
DEFAULT_REALTIME_INPUT_TRANSCRIPT_SESSION_MODEL = "gpt-realtime-2"
DEFAULT_REALTIME_INPUT_TRANSCRIPT_MODEL = "gpt-realtime-whisper"
DEFAULT_REALTIME_INPUT_TRANSCRIPT_LANGUAGE = "en"
DEFAULT_REALTIME_INPUT_TRANSCRIPT_DELAY = "low"
DEFAULT_INPUT_TRANSCRIPT_FALLBACK_MODEL = "gpt-4o-transcribe"
ALLOWED_AUDIO_SUFFIXES = {".aac", ".m4a", ".mp3", ".mp4", ".opus", ".wav", ".webm"}
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
OPENAI_REALTIME_WS_BASE = "wss://api.openai.com/v1/realtime"
OPENAI_TRANSLATION_WS_BASE = "wss://api.openai.com/v1/realtime/translations"
STREAM_READY_KINDS = {"authorized_audio_file", "authorized_audio_url", "authorized_youtube_source"}


@dataclass(frozen=True)
class AudioSourcePlan:
    kind: str
    source: str
    display_source: str
    normalized_audio_path: Path | None
    commands: list[list[str]]
    warnings: list[str]


@dataclass
class LocalSink:
    store: RealtimeSessionStore
    session_id: str

    def emit(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.store.append_event(self.session_id, payload)


@dataclass
class BackendSink:
    backend_url: str
    session_id: str
    event_token: str

    def emit(self, payload: dict[str, Any]) -> dict[str, Any]:
        return post_backend_event(
            backend_url=self.backend_url,
            session_id=self.session_id,
            event_token=self.event_token,
            payload=payload,
        )


def main() -> int:
    report = run_worker(parse_args())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare an authorized audio source and publish realtime caption events."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--audio-file", type=Path, help="Authorized local audio file for server-side ingestion.")
    source.add_argument("--audio-url", help="Authorized HTTP(S) audio stream URL for server-side ingestion.")
    source.add_argument("--youtube-url", help="Authorized YouTube live/archive URL.")
    source.add_argument("--replay-jsonl", type=Path, help="Replay saved realtime JSONL events into a session.")
    parser.add_argument("--sunday", required=True, help="Service Sunday, e.g. 2026-06-28.")
    parser.add_argument("--backend-url", help="Backend/Cloud Run base URL. If omitted, writes local JSONL only.")
    parser.add_argument("--session-id", help="Existing realtime session id for backend posting.")
    parser.add_argument("--event-token", help="Realtime event token for backend posting.")
    parser.add_argument(
        "--create-backend-session",
        action="store_true",
        help="Create a backend local realtime session before posting events.",
    )
    parser.add_argument("--admin-token", help="Operator admin bearer token for backend session creation.")
    parser.add_argument("--internal-task-token", help="Internal task token for backend session creation.")
    parser.add_argument("--event-log-dir", type=Path, default=DEFAULT_EVENT_LOG_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-out", type=Path, help="Optional JSON report path for smoke-test evidence.")
    parser.add_argument("--yt-dlp", default="yt-dlp")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--sample-rate", type=int, default=24000)
    parser.add_argument("--model", default=DEFAULT_REALTIME_MODEL)
    parser.add_argument("--target-language", default=DEFAULT_TARGET_LANGUAGE)
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without writing events or running commands.")
    parser.add_argument(
        "--connect-openai",
        action="store_true",
        help="Stream source audio to OpenAI Realtime translation over server-side WebSocket.",
    )
    parser.add_argument(
        "--api-key-secret",
        help="Secret Manager resource for the OpenAI API key. If omitted, OPENAI_API_KEY is used.",
    )
    parser.add_argument(
        "--openai-api-key-env",
        default="OPENAI_API_KEY",
        help="Environment variable containing the OpenAI API key when --api-key-secret is not used.",
    )
    parser.add_argument(
        "--openai-safety-identifier",
        default="sermon-realtime-media-worker",
        help="Privacy-preserving OpenAI-Safety-Identifier header value.",
    )
    parser.add_argument(
        "--enable-input-transcript-sidecar",
        dest="disable_input_transcript_sidecar",
        action="store_false",
        help="Experimentally enable a parallel realtime transcription sidecar for English input transcript deltas.",
    )
    parser.add_argument(
        "--disable-input-transcript-sidecar",
        dest="disable_input_transcript_sidecar",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.set_defaults(disable_input_transcript_sidecar=True)
    parser.add_argument(
        "--input-transcript-session-model",
        default=DEFAULT_REALTIME_INPUT_TRANSCRIPT_SESSION_MODEL,
        help="Realtime session model used for the transcription-only sidecar.",
    )
    parser.add_argument("--input-transcript-model", default=DEFAULT_REALTIME_INPUT_TRANSCRIPT_MODEL)
    parser.add_argument("--input-transcript-language", default=DEFAULT_REALTIME_INPUT_TRANSCRIPT_LANGUAGE)
    parser.add_argument(
        "--input-transcript-delay",
        default=DEFAULT_REALTIME_INPUT_TRANSCRIPT_DELAY,
        choices=["minimal", "low", "medium", "high", "xhigh"],
    )
    parser.add_argument(
        "--input-transcript-commit-ms",
        type=int,
        default=2000,
        help="Commit realtime transcription audio every N milliseconds to produce English deltas.",
    )
    parser.add_argument(
        "--disable-input-transcript-audio-api-fallback",
        action="store_true",
        help="Disable gpt-4o-transcribe fallback when realtime input transcript deltas are unavailable.",
    )
    parser.add_argument("--input-transcript-fallback-model", default=DEFAULT_INPUT_TRANSCRIPT_FALLBACK_MODEL)
    parser.add_argument("--chunk-ms", type=int, default=100, help="PCM16 audio chunk size sent to OpenAI.")
    parser.add_argument("--max-audio-seconds", type=float, help="Optional cap for live smoke tests.")
    parser.add_argument(
        "--no-realtime-throttle",
        action="store_true",
        help="Send prepared audio as fast as possible instead of pacing chunks in wall-clock time.",
    )
    parser.add_argument("--openai-close-timeout", type=float, default=20.0)
    parser.add_argument(
        "--prepare-audio",
        action="store_true",
        help="Run the source preparation command. Network access is only used for --youtube-url.",
    )
    parser.add_argument("--max-replay-events", type=int, default=200)
    args = parser.parse_args()
    if args.sample_rate < 8000:
        raise SystemExit("--sample-rate must be at least 8000")
    if args.max_replay_events < 1:
        raise SystemExit("--max-replay-events must be >= 1")
    if args.chunk_ms < 20:
        raise SystemExit("--chunk-ms must be at least 20")
    if args.input_transcript_commit_ms < args.chunk_ms:
        raise SystemExit("--input-transcript-commit-ms must be >= --chunk-ms")
    validate_realtime_translation_model(args.model, args.target_language)
    validate_input_transcript_fallback_model(args.input_transcript_fallback_model)
    if args.connect_openai and args.replay_jsonl:
        raise SystemExit("--connect-openai requires --audio-file or --youtube-url, not --replay-jsonl")
    return args


def validate_realtime_translation_model(model: str, target_language: str) -> None:
    policy_error = realtime_translation_policy_error(model, target_language)
    if policy_error:
        raise SystemExit(policy_error["message"])


def validate_input_transcript_fallback_model(model: str) -> None:
    if model != DEFAULT_INPUT_TRANSCRIPT_FALLBACK_MODEL:
        raise SystemExit("Realtime input transcript fallback must use gpt-4o-transcribe.")


def run_worker(args: argparse.Namespace) -> dict[str, Any]:
    plan = build_audio_source_plan(args)
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "status": "planned" if args.dry_run else "started",
        "sunday": args.sunday,
        "model": args.model,
        "targetLanguage": args.target_language,
        "source": {
            "kind": plan.kind,
            "display": plan.display_source,
            "authorizationAssumption": "operator-provided-authorized-source",
        },
        "normalizedAudioPath": safe_display_path(plan.normalized_audio_path) if plan.normalized_audio_path else None,
        "commands": redact_commands_for_report(plan.commands),
        "warnings": plan.warnings,
        "eventsPosted": 0,
    }
    if args.connect_openai:
        report["openaiRealtime"] = {
            "enabled": True,
            "websocketEndpoint": OPENAI_TRANSLATION_WS_BASE,
            "inputAudioFormat": f"pcm16/{args.sample_rate}Hz/mono",
            "chunkMs": args.chunk_ms,
            "inputTranscriptSidecar": {
                "enabled": not args.disable_input_transcript_sidecar,
                "websocketEndpoint": OPENAI_REALTIME_WS_BASE,
                "sessionModel": args.input_transcript_session_model,
                "model": args.input_transcript_model,
                "language": args.input_transcript_language,
                "delay": args.input_transcript_delay,
                "commitMs": args.input_transcript_commit_ms,
            },
            "inputTranscriptFallback": {
                "enabled": not args.disable_input_transcript_audio_api_fallback,
                "model": args.input_transcript_fallback_model,
            },
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
        }
    if args.dry_run:
        write_report_if_requested(args, report)
        return report

    sink = make_sink(args, plan)
    report["sessionId"] = sink.session_id
    report["eventArchivePath"] = archive_path_for_sink(args, sink)

    emit_worker_event(
        sink,
        event_type="media_worker_started",
        text=f"Realtime media worker started for {plan.kind}.",
        args=args,
        source=plan.kind,
    )
    report["eventsPosted"] += 1

    if args.prepare_audio and plan.commands:
        run_commands(plan.commands)

    if plan.kind in STREAM_READY_KINDS or plan.kind == "replay_jsonl":
        emit_worker_event(
            sink,
            event_type="replay_source_ready" if plan.kind == "replay_jsonl" else "audio_source_ready",
            text=f"Realtime source ready: {plan.display_source}.",
            args=args,
            source=plan.kind,
        )
        report["eventsPosted"] += 1

    if args.replay_jsonl:
        replayed = replay_events(resolve_repo_path(args.replay_jsonl), sink, args.max_replay_events)
        report["eventsPosted"] += replayed
        report["replayedEvents"] = replayed

    if args.connect_openai:
        api_key = resolve_openai_api_key(
            os.getenv(args.openai_api_key_env),
            args.api_key_secret,
        )
        realtime_stats = relay_openai_translation(
            args=args,
            plan=plan,
            sink=sink,
            api_key=api_key,
        )
        report["openaiRealtime"] = {
            "enabled": True,
            **realtime_stats,
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
        }
        report["eventsPosted"] += int(realtime_stats.get("captionEventsPosted") or 0)
        report["eventsPosted"] += int(realtime_stats.get("inputTranscriptEventsPosted") or 0)

    emit_worker_event(
        sink,
        event_type="media_worker_completed",
        text=f"Realtime media worker completed for {plan.kind}.",
        args=args,
        source=plan.kind,
    )
    report["eventsPosted"] += 1
    report["status"] = "ok"
    write_report_if_requested(args, report)
    return report


def build_audio_source_plan(args: argparse.Namespace) -> AudioSourcePlan:
    out_dir = resolve_repo_path(args.out_dir)
    normalized_audio_path = out_dir / "source.normalized.wav"
    warnings = []
    if args.connect_openai:
        warnings.append(
            "OpenAI Realtime WebSocket relay is enabled; validate with the real authorized audio source before Sunday production."
        )
    else:
        warnings.append(
            "OpenAI Realtime WebSocket relay is disabled unless --connect-openai is set; "
            "the worker can still publish lifecycle/replay events for end-to-end UI testing."
        )

    if args.audio_file:
        audio_file = resolve_repo_path(args.audio_file)
        validate_audio_file(audio_file)
        command = [
            args.ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            str(audio_file),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(args.sample_rate),
            "-f",
            "wav",
            str(normalized_audio_path),
        ]
        return AudioSourcePlan(
            kind="authorized_audio_file",
            source=str(audio_file),
            display_source=safe_display_path(audio_file),
            normalized_audio_path=normalized_audio_path,
            commands=[command],
            warnings=warnings,
        )

    if args.audio_url:
        validate_audio_url(args.audio_url)
        warnings.append("Authorized audio stream URLs may contain short-lived access tokens; reports redact query strings.")
        return AudioSourcePlan(
            kind="authorized_audio_url",
            source=args.audio_url,
            display_source=redact_url(args.audio_url),
            normalized_audio_path=None,
            commands=[],
            warnings=warnings,
        )

    if args.youtube_url:
        validate_youtube_url(args.youtube_url)
        raw_template = out_dir / "youtube-source.%(ext)s"
        command = [
            args.yt_dlp,
            "-f",
            "ba/bestaudio",
            "--no-playlist",
            "--extract-audio",
            "--audio-format",
            "wav",
            "-o",
            str(raw_template),
            args.youtube_url,
        ]
        warnings.append("YouTube source access must follow the venue's authorization and platform terms.")
        return AudioSourcePlan(
            kind="authorized_youtube_source",
            source=args.youtube_url,
            display_source=redact_url(args.youtube_url),
            normalized_audio_path=out_dir / "youtube-source.wav",
            commands=[command],
            warnings=warnings,
        )

    replay_jsonl = resolve_repo_path(args.replay_jsonl)
    if not replay_jsonl.is_file():
        raise SystemExit(f"--replay-jsonl not found: {replay_jsonl}")
    return AudioSourcePlan(
        kind="replay_jsonl",
        source=str(replay_jsonl),
        display_source=safe_display_path(replay_jsonl),
        normalized_audio_path=None,
        commands=[],
        warnings=warnings,
    )


def make_sink(args: argparse.Namespace, plan: AudioSourcePlan) -> LocalSink | BackendSink:
    if args.backend_url:
        session_id = args.session_id
        event_token = args.event_token
        if args.create_backend_session:
            created = create_backend_local_session(args, audio_source_kind=plan.kind)
            session_id = created["sessionId"]
            event_token = created["eventToken"]
        if not session_id or not event_token:
            raise SystemExit("--backend-url requires --session-id and --event-token, or --create-backend-session")
        return BackendSink(normalize_backend_url(args.backend_url), session_id, event_token)

    archive = RealtimeEventArchive(resolve_repo_path(args.event_log_dir))
    store = RealtimeSessionStore(archive)
    session = store.create(
        sunday=args.sunday,
        model=args.model,
        target_language=args.target_language,
        audio_source_kind=plan.kind,
    )
    return LocalSink(store, session.session_id)


def emit_worker_event(
    sink: LocalSink | BackendSink,
    *,
    event_type: str,
    text: str,
    args: argparse.Namespace,
    source: str,
) -> dict[str, Any]:
    return sink.emit(
        {
            "type": event_type,
            "text": text,
            "source": source,
            "sunday": args.sunday,
            "model": args.model,
            "targetLanguage": args.target_language,
        }
    )


def replay_events(path: Path, sink: LocalSink | BackendSink, max_events: int) -> int:
    count = 0
    for row in read_jsonl(path):
        if count >= max_events:
            break
        if not isinstance(row, dict):
            continue
        payload = {**row}
        payload.pop("id", None)
        payload.pop("sessionId", None)
        payload.pop("createdAt", None)
        payload.setdefault("source", "server_media_worker_replay")
        sink.emit(payload)
        count += 1
    return count


def relay_openai_translation(
    *,
    args: argparse.Namespace,
    plan: AudioSourcePlan,
    sink: LocalSink | BackendSink,
    api_key: str,
    ws_factory: Callable[[str, list[str]], Any] | None = None,
    popen_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    translation_ws = connect_openai_translation_ws(
        api_key=api_key,
        model=args.model,
        safety_identifier=args.openai_safety_identifier,
        ws_factory=ws_factory,
    )
    stats: dict[str, Any] = {
        "model": args.model,
        "targetLanguage": args.target_language,
        "audioChunksSent": 0,
        "bytesSent": 0,
        "openaiEventsReceived": 0,
        "captionEventsPosted": 0,
        "inputTranscriptEventsPosted": 0,
        "eventTypeCounts": {},
        "inputTranscriptSidecar": {
            "enabled": not args.disable_input_transcript_sidecar,
            "sessionModel": args.input_transcript_session_model,
            "model": args.input_transcript_model,
            "language": args.input_transcript_language,
            "delay": args.input_transcript_delay,
            "commitMs": args.input_transcript_commit_ms,
        },
        "inputTranscriptFallback": {
            "enabled": not args.disable_input_transcript_audio_api_fallback,
            "model": args.input_transcript_fallback_model,
            "eventsPosted": 0,
        },
    }
    translation_ws.send(
        json.dumps(
            {
                "type": "session.update",
                "session": {
                    "audio": {
                        "output": {
                            "language": args.target_language,
                        },
                    },
                },
            }
        )
    )
    transcription_ws = None
    if not args.disable_input_transcript_sidecar:
        transcription_ws = connect_openai_realtime_ws(
            api_key=api_key,
            model=args.input_transcript_session_model,
            safety_identifier=args.openai_safety_identifier,
            ws_factory=ws_factory,
        )
        transcription_ws.send(json.dumps(build_transcription_session_update(args)))
    receive_thread = threading.Thread(
        target=receive_openai_events,
        kwargs={"ws": translation_ws, "sink": sink, "stats": stats},
        daemon=True,
    )
    receive_thread.start()
    transcription_receive_thread = None
    if transcription_ws is not None:
        transcription_receive_thread = threading.Thread(
            target=receive_openai_events,
            kwargs={
                "ws": transcription_ws,
                "sink": sink,
                "stats": stats,
                "source": "openai_realtime_transcription_ws",
            },
            daemon=True,
        )
        transcription_receive_thread.start()

    proc = open_audio_pcm_process(args=args, plan=plan, popen_factory=popen_factory)
    chunk_size = pcm_chunk_size(args.sample_rate, args.chunk_ms)
    max_bytes = int(args.sample_rate * 2 * args.max_audio_seconds) if args.max_audio_seconds else None
    transcript_commit_bytes = int(args.sample_rate * 2 * (args.input_transcript_commit_ms / 1000))
    sent_bytes = 0
    transcript_uncommitted_bytes = 0
    try:
        while True:
            if max_bytes is not None and sent_bytes >= max_bytes:
                break
            read_size = chunk_size if max_bytes is None else min(chunk_size, max_bytes - sent_bytes)
            if read_size <= 0:
                break
            chunk = proc.stdout.read(read_size)
            if not chunk:
                break
            sent_bytes += len(chunk)
            encoded_audio = base64.b64encode(chunk).decode("ascii")
            translation_ws.send(
                json.dumps(
                    {
                        "type": "session.input_audio_buffer.append",
                        "audio": encoded_audio,
                    }
                )
            )
            if transcription_ws is not None:
                if send_ws_json(
                    transcription_ws,
                    {
                        "type": "input_audio_buffer.append",
                        "audio": encoded_audio,
                    },
                    stats["inputTranscriptSidecar"],
                ):
                    transcript_uncommitted_bytes += len(chunk)
                    if transcript_uncommitted_bytes >= transcript_commit_bytes:
                        if send_ws_json(
                            transcription_ws,
                            {"type": "input_audio_buffer.commit"},
                            stats["inputTranscriptSidecar"],
                        ):
                            transcript_uncommitted_bytes = 0
                else:
                    close_ws(transcription_ws)
                    transcription_ws = None
            stats["audioChunksSent"] += 1
            stats["bytesSent"] += len(chunk)
            if not args.no_realtime_throttle:
                time.sleep(args.chunk_ms / 1000)
    finally:
        wait_for_process(proc)

    if transcription_ws is not None and transcript_uncommitted_bytes > 0:
        send_ws_json(
            transcription_ws,
            {"type": "input_audio_buffer.commit"},
            stats["inputTranscriptSidecar"],
        )
    translation_ws.send(json.dumps({"type": "session.close"}))
    receive_thread.join(args.openai_close_timeout)
    close_ws(translation_ws)
    if receive_thread.is_alive():
        stats["warning"] = "OpenAI realtime receive loop did not close before timeout."
    if transcription_ws is not None and transcription_receive_thread is not None:
        transcription_receive_thread.join(args.openai_close_timeout)
        close_ws(transcription_ws)
        transcription_receive_thread.join(1.0)
        if transcription_receive_thread.is_alive():
            stats["inputTranscriptSidecar"]["warning"] = (
                "OpenAI realtime transcription receive loop did not close before timeout."
            )
    if stats["inputTranscriptEventsPosted"] == 0 and not args.disable_input_transcript_audio_api_fallback:
        fallback_stats = transcribe_input_audio_with_audio_api_fallback(
            args=args,
            plan=plan,
            sink=sink,
            api_key=api_key,
        )
        stats["inputTranscriptFallback"].update(fallback_stats)
        stats["inputTranscriptEventsPosted"] += int(fallback_stats.get("eventsPosted") or 0)
    return stats


def send_ws_json(ws: Any, payload: dict[str, Any], stats: dict[str, Any]) -> bool:
    try:
        ws.send(json.dumps(payload))
        return True
    except Exception as exc:
        stats["error"] = f"{type(exc).__name__}: {exc}"
        return False


def build_transcription_session_update(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "type": "session.update",
        "session": {
            "type": "transcription",
            "audio": {
                "input": {
                    "format": {
                        "type": "audio/pcm",
                        "rate": args.sample_rate,
                    },
                    "transcription": {
                        "model": args.input_transcript_model,
                        "language": args.input_transcript_language,
                        "delay": args.input_transcript_delay,
                    },
                    "turn_detection": None,
                },
            },
        },
    }


def connect_openai_translation_ws(
    *,
    api_key: str,
    model: str,
    safety_identifier: str,
    ws_factory: Callable[[str, list[str]], Any] | None = None,
) -> Any:
    url = f"{OPENAI_TRANSLATION_WS_BASE}?model={quote(model)}"
    headers = [
        f"Authorization: Bearer {api_key}",
        f"OpenAI-Safety-Identifier: {safety_identifier}",
    ]
    if ws_factory:
        return ws_factory(url, headers)
    try:
        import websocket
    except ImportError as exc:
        raise SystemExit("Install websocket-client or run pip install -r requirements.txt.") from exc
    ws = websocket.WebSocket()
    ws.connect(url, header=headers)
    return ws


def connect_openai_realtime_ws(
    *,
    api_key: str,
    model: str,
    safety_identifier: str,
    ws_factory: Callable[[str, list[str]], Any] | None = None,
) -> Any:
    url = f"{OPENAI_REALTIME_WS_BASE}?model={quote(model)}"
    headers = [
        f"Authorization: Bearer {api_key}",
        f"OpenAI-Safety-Identifier: {safety_identifier}",
    ]
    if ws_factory:
        return ws_factory(url, headers)
    try:
        import websocket
    except ImportError as exc:
        raise SystemExit("Install websocket-client or run pip install -r requirements.txt.") from exc
    ws = websocket.WebSocket()
    ws.connect(url, header=headers)
    return ws


def receive_openai_events(
    ws: Any,
    sink: LocalSink | BackendSink,
    stats: dict[str, Any],
    source: str = "openai_realtime_translation_ws",
) -> None:
    receive_started_at = time.monotonic()
    while True:
        try:
            message = ws.recv()
        except Exception:
            break
        if not message:
            continue
        try:
            event = json.loads(message)
        except json.JSONDecodeError:
            continue
        event_type = str(event.get("type") or "")
        stats["openaiEventsReceived"] += 1
        event_counts = stats.setdefault("eventTypeCounts", {})
        event_counts[event_type or "unknown"] = int(event_counts.get(event_type or "unknown", 0)) + 1
        if event_type == "error":
            stats.setdefault("errors", []).append(redact_openai_error(event.get("error")))
        payload = openai_event_to_realtime_payload(
            event,
            source=source,
            latency_ms=openai_event_latency_ms(event, receive_started_at=receive_started_at),
        )
        if payload:
            sink.emit(payload)
            if payload["type"].startswith("caption_"):
                stats["captionEventsPosted"] += 1
            if payload["type"].startswith("input_transcript_"):
                stats["inputTranscriptEventsPosted"] += 1
        if event_type == "session.closed":
            break


def openai_event_to_realtime_payload(
    event: dict[str, Any],
    source: str = "openai_realtime_translation_ws",
    latency_ms: int | None = None,
) -> dict[str, Any] | None:
    event_type = str(event.get("type") or "")
    text = extract_openai_transcript_text(event)
    if not text:
        return None
    is_final = event_type.endswith((".done", ".completed", ".final"))
    segment_id = openai_segment_id(event)
    if latency_ms is None:
        latency_ms = openai_event_latency_ms(event)
    if "output_transcript" in event_type:
        payload_type = "caption_final" if is_final else "caption_delta"
        return transcript_payload(payload_type, text, event_type, segment_id, source=source, final=is_final, latency_ms=latency_ms)
    if "input_transcript" in event_type or "input_audio_transcription" in event_type:
        payload_type = "input_transcript_final" if is_final else "input_transcript_delta"
        return transcript_payload(payload_type, text, event_type, segment_id, source=source, final=is_final, latency_ms=latency_ms)
    return None


def extract_openai_transcript_text(event: dict[str, Any]) -> str:
    values = [
        event.get("delta"),
        event.get("text_delta"),
        event.get("transcript_delta"),
        event.get("output_transcript_delta"),
        event.get("audio_transcript_delta"),
        event.get("text"),
        event.get("transcript"),
        event.get("output_text"),
        event.get("output_transcript"),
        event.get("audio_transcript"),
    ]
    for key in ("output_transcript", "audio_transcript", "part", "item", "response"):
        values.extend(nested_text_values(event.get(key)))
    for value in values:
        text = scalar_text(value)
        if text:
            return text
    return ""


def nested_text_values(value: Any) -> list[Any]:
    if not isinstance(value, dict):
        return []
    values: list[Any] = [
        value.get("delta"),
        value.get("text_delta"),
        value.get("transcript_delta"),
        value.get("output_transcript_delta"),
        value.get("audio_transcript_delta"),
        value.get("text"),
        value.get("transcript"),
        value.get("output_text"),
        value.get("output_transcript"),
        value.get("audio_transcript"),
    ]
    for item in value.get("content") or []:
        if isinstance(item, dict):
            values.extend(nested_text_values(item))
    for item in value.get("output") or []:
        if isinstance(item, dict):
            values.extend(nested_text_values(item))
    return values


def scalar_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def openai_segment_id(event: dict[str, Any]) -> str:
    values = [
        event.get("item_id"),
        event.get("content_index"),
        event.get("response_id"),
        event.get("event_id"),
        event.get("id"),
    ]
    for key in ("item", "response"):
        nested = event.get(key)
        if isinstance(nested, dict):
            values.append(nested.get("id"))
    for value in values:
        text = scalar_text(value)
        if text:
            return text[:120]
    return ""


def openai_event_latency_ms(event: dict[str, Any], *, receive_started_at: float | None = None) -> int | None:
    for value in [
        event.get("latencyMs"),
        event.get("latency_ms"),
        event.get("elapsed_ms"),
        nested_number(event.get("response"), "latency_ms"),
        nested_number(event.get("response"), "elapsed_ms"),
    ]:
        parsed = safe_positive_int(value)
        if parsed is not None:
            return parsed
    if receive_started_at is None:
        return None
    return max(0, int((time.monotonic() - receive_started_at) * 1000))


def nested_number(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else None


def safe_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def redact_openai_error(error: Any) -> dict[str, Any] | str:
    if not isinstance(error, dict):
        return str(error)[:500]
    return {
        key: str(value)[:500]
        for key, value in error.items()
        if key in {"type", "code", "message", "param"}
    }


def transcribe_input_audio_with_audio_api_fallback(
    *,
    args: argparse.Namespace,
    plan: AudioSourcePlan,
    sink: LocalSink | BackendSink,
    api_key: str,
) -> dict[str, Any]:
    audio_path = fallback_audio_path(plan)
    stats: dict[str, Any] = {
        "status": "skipped",
        "model": args.input_transcript_fallback_model,
        "eventsPosted": 0,
    }
    if not audio_path:
        stats["reason"] = "no_local_audio_file_for_fallback"
        return stats
    try:
        transcript = request_audio_transcription(
            api_key=api_key,
            model=args.input_transcript_fallback_model,
            language=args.input_transcript_language,
            audio_path=audio_path,
        ).strip()
    except Exception as exc:
        stats["status"] = "failed"
        stats["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        return stats
    if not transcript:
        stats["status"] = "empty"
        return stats
    sink.emit(
        {
            "type": "input_transcript_final",
            "text": transcript,
            "en": transcript,
            "final": True,
            "source": "openai_audio_transcription_fallback",
            "model": args.input_transcript_fallback_model,
            "openaiEventType": "audio.transcriptions.completed",
        }
    )
    stats["status"] = "ok"
    stats["eventsPosted"] = 1
    stats["audio"] = safe_display_path(audio_path)
    return stats


def fallback_audio_path(plan: AudioSourcePlan) -> Path | None:
    candidates = []
    if plan.normalized_audio_path:
        candidates.append(plan.normalized_audio_path)
    if plan.kind == "authorized_audio_file":
        candidates.append(Path(plan.source))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def request_audio_transcription(*, api_key: str, model: str, language: str, audio_path: Path) -> str:
    boundary = f"----sermon-transcribe-{uuid.uuid4().hex}"
    mime_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    fields = [
        ("model", model),
        ("language", language),
        ("response_format", "json"),
    ]
    body = bytearray()
    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="file"; filename="{audio_path.name}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(audio_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    request = Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=bytes(body),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        return ""
    return str(data.get("text") or "")


def transcript_payload(
    payload_type: str,
    text: str,
    openai_event_type: str,
    segment_id: str,
    *,
    source: str,
    final: bool,
    latency_ms: int | None = None,
) -> dict[str, Any]:
    payload = {
        "type": payload_type,
        "text": text,
        "source": source,
        "openaiEventType": openai_event_type,
        "final": final,
    }
    if payload_type.endswith("_delta"):
        payload["delta"] = text
    if payload_type.startswith("caption_"):
        payload["zh"] = text
    else:
        payload["en"] = text
    if segment_id:
        payload["segmentId"] = segment_id
    if latency_ms is not None:
        payload["latencyMs"] = max(0, int(latency_ms))
    return payload


def open_audio_pcm_process(
    *,
    args: argparse.Namespace,
    plan: AudioSourcePlan,
    popen_factory: Callable[..., Any] | None = None,
) -> Any:
    command = raw_pcm_command(args=args, plan=plan)
    factory = popen_factory or subprocess.Popen
    return factory(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def raw_pcm_command(*, args: argparse.Namespace, plan: AudioSourcePlan) -> list[str]:
    if plan.kind == "authorized_audio_file":
        source = plan.source
    elif plan.kind == "authorized_audio_url":
        source = plan.source
    elif plan.kind == "authorized_youtube_source":
        source = resolve_youtube_audio_stream_url(args.yt_dlp, plan.source)
    else:
        raise SystemExit("--connect-openai requires --audio-file or --youtube-url")
    return [
        args.ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        source,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(args.sample_rate),
        "-f",
        "s16le",
        "pipe:1",
    ]


def resolve_youtube_audio_stream_url(yt_dlp: str, url: str) -> str:
    proc = subprocess.run(
        [yt_dlp, "-f", "ba/bestaudio", "--no-playlist", "-g", url],
        check=True,
        text=True,
        capture_output=True,
    )
    for line in proc.stdout.splitlines():
        candidate = line.strip()
        if candidate.startswith(("http://", "https://")):
            return candidate
    raise SystemExit("yt-dlp did not return an audio stream URL.")


def pcm_chunk_size(sample_rate: int, chunk_ms: int) -> int:
    return max(1, int(sample_rate * 2 * (chunk_ms / 1000)))


def wait_for_process(proc: Any) -> None:
    try:
        proc.wait(timeout=5)
    except TypeError:
        proc.wait()
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def close_ws(ws: Any) -> None:
    try:
        ws.close()
    except Exception:
        pass


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def write_report_if_requested(args: argparse.Namespace, report: dict[str, Any]) -> None:
    report_out = getattr(args, "report_out", None)
    if not report_out:
        return
    path = resolve_repo_path(report_out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def create_backend_local_session(args: argparse.Namespace, audio_source_kind: str | None = None) -> dict[str, Any]:
    payload = {
        "sunday": args.sunday,
        "model": args.model,
        "targetLanguage": args.target_language,
        "audioSourceKind": audio_source_kind or "unknown",
        "triggerSource": "realtime-media-worker",
    }
    request = Request(
        f"{normalize_backend_url(args.backend_url)}/api/admin/realtime/local-sessions",
        data=json.dumps(payload).encode("utf-8"),
        headers=auth_headers(args) | {"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict) or not data.get("sessionId") or not data.get("eventToken"):
        raise SystemExit("Backend did not return a realtime session id and event token.")
    return data


def post_backend_event(
    *,
    backend_url: str,
    session_id: str,
    event_token: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    request = Request(
        f"{normalize_backend_url(backend_url)}/api/realtime/sessions/{session_id}/events",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Realtime-Event-Token": event_token,
        },
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def auth_headers(args: argparse.Namespace) -> dict[str, str]:
    headers = {}
    if args.admin_token:
        headers["Authorization"] = f"Bearer {args.admin_token}"
    if args.internal_task_token:
        headers["X-Internal-Task-Token"] = args.internal_task_token
    return headers


def run_commands(commands: list[list[str]]) -> None:
    for command in commands:
        ensure_command_output_dirs(command)
        subprocess.run(command, check=True)


def ensure_command_output_dirs(command: list[str]) -> None:
    if "-o" in command:
        output_index = command.index("-o") + 1
        if output_index < len(command):
            Path(command[output_index]).parent.mkdir(parents=True, exist_ok=True)
        return
    if command and "://" not in command[-1]:
        Path(command[-1]).parent.mkdir(parents=True, exist_ok=True)


def validate_audio_file(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"--audio-file not found: {path}")
    if path.suffix.lower() not in ALLOWED_AUDIO_SUFFIXES:
        raise SystemExit(f"--audio-file must be one of: {', '.join(sorted(ALLOWED_AUDIO_SUFFIXES))}")


def validate_youtube_url(value: str) -> None:
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    if parsed.scheme not in {"http", "https"} or host not in YOUTUBE_HOSTS:
        raise SystemExit("--youtube-url must be an authorized youtube.com or youtu.be URL.")


def validate_audio_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit("--audio-url must be an authorized http:// or https:// audio stream URL.")


def normalize_backend_url(value: str) -> str:
    clean = value.rstrip("/")
    if not clean.startswith(("http://", "https://")):
        raise SystemExit("--backend-url must start with http:// or https://")
    return clean


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def safe_display_path(path: Path | None) -> str | None:
    if path is None:
        return None
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return resolved.name


def redact_url(value: str) -> str:
    parsed = urlparse(value)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def redact_commands_for_report(commands: list[list[str]]) -> list[list[str]]:
    return [[redact_url(arg) if looks_like_url(arg) else arg for arg in command] for command in commands]


def looks_like_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def archive_path_for_sink(args: argparse.Namespace, sink: LocalSink | BackendSink) -> str | None:
    if isinstance(sink, BackendSink):
        return None
    return safe_display_path(resolve_repo_path(args.event_log_dir) / f"{sink.session_id}.jsonl")


if __name__ == "__main__":
    raise SystemExit(main())
