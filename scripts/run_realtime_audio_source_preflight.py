#!/usr/bin/env python3
"""Preflight an authorized realtime audio source before OpenAI smoke tests."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPT_DIR = REPO_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import realtime_media_worker  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/realtime-audio-source-preflight")
MIN_PREPARED_AUDIO_BYTES = 4096


def main() -> int:
    args = parse_args()
    report = run_preflight(args)
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--audio-file", type=Path)
    source.add_argument("--audio-url")
    source.add_argument("--youtube-url")
    parser.add_argument("--sunday", required=True)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--yt-dlp", default="yt-dlp")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--sample-rate", type=int, default=24000)
    parser.add_argument(
        "--prepare-audio",
        action="store_true",
        help="Run preparation commands for local audio or YouTube sources.",
    )
    args = parser.parse_args()
    if args.sample_rate < 8000:
        raise SystemExit("--sample-rate must be at least 8000")
    return args


def run_preflight(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    worker_args = worker_args_from_preflight(args)
    try:
        plan = realtime_media_worker.build_audio_source_plan(worker_args)
        add_check(checks, "source_plan", True, {"kind": plan.kind, "display": plan.display_source})
    except SystemExit as exc:
        add_check(checks, "source_plan", False, str(exc))
        return report_from_checks(args, checks, plan=None, command_results=[])

    rendered = json.dumps(
        {
            "source": plan.display_source,
            "commands": realtime_media_worker.redact_commands_for_report(plan.commands),
        },
        ensure_ascii=False,
    )
    add_check(checks, "source_redacted", "?" not in plan.display_source and "token=" not in rendered, plan.display_source)
    add_check(checks, "sample_rate", args.sample_rate == 24000, args.sample_rate)
    add_check(
        checks,
        "preparation_available",
        bool(plan.commands) or plan.kind == "authorized_audio_url",
        "stream URL will be decoded directly by ffmpeg during realtime relay"
        if plan.kind == "authorized_audio_url"
        else len(plan.commands),
    )

    command_results: list[dict[str, Any]] = []
    if args.prepare_audio:
        if not plan.commands:
            add_check(
                checks,
                "prepare_audio",
                True,
                "no preparation command for authorized audio URL; relay will decode stream directly",
            )
        else:
            for command in plan.commands:
                realtime_media_worker.ensure_command_output_dirs(command)
                result = run_command(command)
                command_results.append(result)
                add_check(checks, "prepare_audio", result["status"] == "ok", result)
            if plan.normalized_audio_path:
                prepared = resolve_repo_path(plan.normalized_audio_path)
                prepared_bytes = prepared.stat().st_size if prepared.is_file() else 0
                add_check(
                    checks,
                    "prepared_audio_nonempty",
                    prepared.is_file() and prepared_bytes >= MIN_PREPARED_AUDIO_BYTES,
                    {
                        "path": realtime_media_worker.safe_display_path(prepared),
                        "bytes": prepared_bytes,
                        "minBytes": MIN_PREPARED_AUDIO_BYTES,
                    },
                )
    else:
        add_check(checks, "prepare_audio", True, "skipped; pass --prepare-audio to execute source preparation", state="warn")

    return report_from_checks(args, checks, plan=plan, command_results=command_results)


def worker_args_from_preflight(args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        audio_file=resolve_repo_path(args.audio_file) if args.audio_file else None,
        audio_url=args.audio_url,
        youtube_url=args.youtube_url,
        replay_jsonl=None,
        sunday=args.sunday,
        backend_url=None,
        session_id=None,
        event_token=None,
        create_backend_session=False,
        admin_token=None,
        internal_task_token=None,
        event_log_dir=Path("/tmp/sermon-realtime-events"),
        out_dir=resolve_repo_path(args.out_dir),
        report_out=None,
        yt_dlp=args.yt_dlp,
        ffmpeg=args.ffmpeg,
        sample_rate=args.sample_rate,
        model=realtime_media_worker.DEFAULT_REALTIME_MODEL,
        target_language=realtime_media_worker.DEFAULT_TARGET_LANGUAGE,
        dry_run=True,
        connect_openai=False,
        api_key_secret=None,
        openai_api_key_env="OPENAI_API_KEY",
        openai_safety_identifier="sermon-realtime-audio-source-preflight",
        disable_input_transcript_sidecar=True,
        input_transcript_session_model=realtime_media_worker.DEFAULT_REALTIME_INPUT_TRANSCRIPT_SESSION_MODEL,
        input_transcript_model=realtime_media_worker.DEFAULT_REALTIME_INPUT_TRANSCRIPT_MODEL,
        input_transcript_language=realtime_media_worker.DEFAULT_REALTIME_INPUT_TRANSCRIPT_LANGUAGE,
        input_transcript_delay=realtime_media_worker.DEFAULT_REALTIME_INPUT_TRANSCRIPT_DELAY,
        input_transcript_commit_ms=2000,
        disable_input_transcript_audio_api_fallback=False,
        input_transcript_fallback_model=realtime_media_worker.DEFAULT_INPUT_TRANSCRIPT_FALLBACK_MODEL,
        chunk_ms=100,
        max_audio_seconds=None,
        no_realtime_throttle=False,
        openai_close_timeout=20.0,
        prepare_audio=args.prepare_audio,
        max_replay_events=1,
    )


def run_command(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    return {
        "status": "ok" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "argv": realtime_media_worker.redact_commands_for_report([command])[0],
        "stdoutTail": tail(completed.stdout),
        "stderrTail": tail(completed.stderr),
    }


def report_from_checks(
    args: argparse.Namespace,
    checks: list[dict[str, Any]],
    *,
    plan: Any | None,
    command_results: list[dict[str, Any]],
) -> dict[str, Any]:
    failed = [check for check in checks if check["state"] == "fail"]
    warnings = [check for check in checks if check["state"] == "warn"]
    return {
        "schemaVersion": 1,
        "status": "failed" if failed else "ok",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sunday": args.sunday,
        "source": None
        if plan is None
        else {
            "kind": plan.kind,
            "display": plan.display_source,
            "authorizationAssumption": "operator-provided-authorized-source",
        },
        "normalizedAudioPath": None
        if plan is None or plan.normalized_audio_path is None
        else realtime_media_worker.safe_display_path(plan.normalized_audio_path),
        "checks": checks,
        "failedChecks": [check["name"] for check in failed],
        "warnings": [check["name"] for check in warnings],
        "commandResults": command_results,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def add_check(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    observed: Any,
    *,
    state: str | None = None,
) -> None:
    checks.append({"name": name, "state": state or ("pass" if passed else "fail"), "observed": observed})


def tail(text: str, limit: int = 2000) -> str:
    return text[-limit:] if len(text) > limit else text


def resolve_repo_path(path: Path | None) -> Path:
    if path is None:
        raise TypeError("path is required")
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
