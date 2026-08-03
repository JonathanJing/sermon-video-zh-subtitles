#!/usr/bin/env python3
"""Run the production sermon supervisor from the local Codex automation environment."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.config import upcoming_sunday
from backend.cloud import read_gcs_bytes
from scripts import (
    live_source_monitor,
    run_sermon_production_supervisor_agent,
    sermon_production_supervisor,
)


DEFAULT_STATE_URI = (
    "gs://sermon-zh-artifacts-ai-for-god/sundays/live-source-monitor/backend-state.json"
)
DEFAULT_BUCKET = "sermon-zh-artifacts-ai-for-god"
DEFAULT_OPENAI_SECRET = "projects/ai-for-god/secrets/openai-api-key/versions/latest"
DEFAULT_YOUTUBE_API_SECRET = (
    "projects/ai-for-god/secrets/youtube-data-api-key/versions/latest"
)
DEFAULT_SENDGRID_SECRET = "projects/ai-for-god/secrets/sendgrid-api-key/versions/latest"
DEFAULT_RECIPIENTS_SECRET = "projects/ai-for-god/secrets/recipient-emails/versions/latest"
DEFAULT_SENDER_SECRET = "projects/ai-for-god/secrets/sender-email/versions/latest"
LOCAL_TIMEZONE = "America/Los_Angeles"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sunday")
    parser.add_argument("--mode", choices=("shadow", "execute"), default="execute")
    parser.add_argument("--state-file", default=DEFAULT_STATE_URI)
    parser.add_argument(
        "--work-root",
        type=Path,
        default=REPO_ROOT / "artifacts" / "post-live-runs",
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--gcs-bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--gcs-prefix", default="sundays")
    parser.add_argument("--api-key-secret", default=DEFAULT_OPENAI_SECRET)
    parser.add_argument("--youtube-api-key-secret", default=DEFAULT_YOUTUBE_API_SECRET)
    parser.add_argument("--youtube-cookies-secret")
    parser.add_argument("--glossary", type=Path)
    parser.add_argument(
        "--youtube-cookies",
        type=Path,
        default=Path(os.environ["SERMON_YOUTUBE_COOKIES_FILE"]).expanduser()
        if os.environ.get("SERMON_YOUTUBE_COOKIES_FILE")
        else None,
    )
    parser.add_argument("--notify-sendgrid-secret", default=DEFAULT_SENDGRID_SECRET)
    parser.add_argument("--notify-recipients-secret", default=DEFAULT_RECIPIENTS_SECRET)
    parser.add_argument("--notify-sender-secret", default=DEFAULT_SENDER_SECRET)
    parser.add_argument("--model", default="gpt-5.6")
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument(
        "--skip-source-refresh",
        action="store_true",
        help="Skip local source refresh and only consume existing GCS state.",
    )
    parser.add_argument(
        "--force-after-complete",
        action="store_true",
        help="Bypass this Sunday's verified completion latch for an explicit repair run.",
    )
    parser.add_argument(
        "--resume-failed-generation",
        action="store_true",
        help="Explicitly archive failed generation evidence and resume under the generation lease.",
    )
    return parser.parse_args()


def make_agent_args(args: argparse.Namespace) -> argparse.Namespace:
    sunday = args.sunday or upcoming_sunday().isoformat()
    out = args.out or (
        REPO_ROOT
        / "artifacts"
        / "sermon-production-supervisor"
        / sunday
        / "latest.json"
    )
    if args.youtube_cookies and args.youtube_cookies_secret:
        raise SystemExit(
            "Configure only one of --youtube-cookies or --youtube-cookies-secret."
        )
    return argparse.Namespace(
        sunday=sunday,
        state_file=args.state_file,
        work_root=args.work_root,
        out=out,
        gcs_bucket=args.gcs_bucket,
        gcs_prefix=args.gcs_prefix,
        api_key_secret=args.api_key_secret,
        youtube_api_key_secret=args.youtube_api_key_secret,
        youtube_cookies_secret=args.youtube_cookies_secret,
        youtube_cookies=args.youtube_cookies,
        glossary=getattr(args, "glossary", None),
        discord_bot_token_secret=None,
        discord_channel_id=None,
        notify_sendgrid_secret=args.notify_sendgrid_secret,
        notify_recipients_secret=args.notify_recipients_secret,
        notify_sender_secret=args.notify_sender_secret,
        model=args.model,
        mode=args.mode,
        max_turns=args.max_turns,
        skip_source_refresh=args.skip_source_refresh,
        force_after_complete=getattr(args, "force_after_complete", False),
        resume_failed_generation=getattr(args, "resume_failed_generation", False),
        approve_window=False,
        start_time=None,
        end_time=None,
        approved_by=None,
        approval_note=None,
        content_scope=None,
    )


def refresh_source_state(args: argparse.Namespace) -> dict[str, Any]:
    sunday = args.sunday
    out = (
        REPO_ROOT
        / "artifacts"
        / "live-source-monitor"
        / sunday
        / "local-refresh.json"
    )
    previous_state = live_source_monitor.read_state(args.state_file)
    if persisted_live_url(previous_state, sunday):
        return {
            "status": "existing_source_preserved",
            "sunday": sunday,
            "selectedSource": previous_state.get("lastSelectedSource"),
            "operatorAlert": False,
            "report": None,
            "completedAt": datetime.now(timezone.utc).isoformat(),
        }
    service = discovery_service_for_run(sunday)
    monitor_args = argparse.Namespace(
        sunday=sunday,
        service=service,
        expected_title=None,
        manual_url=[],
        mariners_online_url=live_source_monitor.DEFAULT_MARINERS_ONLINE_URL,
        youtube_streams_url=live_source_monitor.DEFAULT_YOUTUBE_STREAMS_URL,
        youtube_live_url=live_source_monitor.DEFAULT_YOUTUBE_LIVE_URL,
        fixture_json=None,
        out=out,
        state_file=args.state_file,
        notify_webhook_url=None,
        notify_sendgrid_secret=args.notify_sendgrid_secret,
        notify_recipients_secret=args.notify_recipients_secret,
        notify_sender_secret=args.notify_sender_secret,
        youtube_api_key_secret=args.youtube_api_key_secret,
        timezone=LOCAL_TIMEZONE,
        now=None,
        min_confidence=0.70,
        operator_alert_time="17:50",
        backend_url="http://127.0.0.1:8080",
        post_generate=False,
        admin_token=None,
        internal_task_token=None,
    )
    report = live_source_monitor.run_monitor(monitor_args)
    notification = live_source_monitor.build_notification(report, previous_state)
    if notification["shouldNotify"] and monitor_args.notify_sendgrid_secret:
        notification["delivery"] = live_source_monitor.send_sendgrid_notification(
            monitor_args.notify_sendgrid_secret,
            monitor_args.notify_recipients_secret,
            monitor_args.notify_sender_secret,
            notification,
        )
    report["notification"] = notification
    live_source_monitor.write_state(
        monitor_args.state_file,
        report,
        previous_state,
        notification,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {
        "status": report.get("status"),
        "sunday": sunday,
        "service": service,
        "selectedSource": report.get("selectedSource"),
        "operatorAlert": report.get("operatorAlert"),
        "report": str(out),
        "completedAt": datetime.now(timezone.utc).isoformat(),
    }


def persisted_live_url(state: dict[str, Any], sunday: str) -> str | None:
    if state.get("lastSunday") != sunday:
        return None
    generation_request = state.get("lastGenerationRequest")
    if isinstance(generation_request, dict) and generation_request.get("liveUrl"):
        return str(generation_request["liveUrl"])
    selected_source = state.get("lastSelectedSource")
    if isinstance(selected_source, dict) and selected_source.get("url"):
        return str(selected_source["url"])
    return None


def discovery_service_for_run(
    sunday: str,
    *,
    local_date: date | None = None,
) -> str:
    run_date = local_date or datetime.now(ZoneInfo(LOCAL_TIMEZONE)).date()
    sunday_date = date.fromisoformat(sunday)
    return "auto" if run_date >= sunday_date else "sat-auto"


def completed_production_report(
    args: argparse.Namespace,
    *,
    gcs_reader: Callable[[str], bytes] = read_gcs_bytes,
) -> dict[str, Any] | None:
    """Return a terminal report before refresh/secrets/agent work when this Sunday is done."""
    if getattr(args, "force_after_complete", False):
        return None
    snapshot = local_completed_snapshot(
        args.out,
        args.sunday,
        gcs_reader=gcs_reader,
    )
    latch_source = "local_previous_terminal_report"
    if snapshot is None:
        latch_source = "authoritative_production_snapshot"
        try:
            snapshot = sermon_production_supervisor.production_snapshot(
                run_sermon_production_supervisor_agent.make_config(args)
            )
        except Exception:
            return None
    return completed_report_from_snapshot(args, snapshot, latch_source=latch_source)


def local_completed_snapshot(
    path: Path,
    sunday: str,
    *,
    gcs_reader: Callable[[str], bytes] = read_gcs_bytes,
) -> dict[str, Any] | None:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(report, dict) or report.get("sunday") != sunday:
        return None
    snapshot = report.get("finalSnapshot")
    if not isinstance(snapshot, dict):
        return None
    artifacts = local_completion_artifacts(snapshot, gcs_reader=gcs_reader)
    if artifacts is None:
        return None
    return {
        **snapshot,
        "generation": artifacts["generation"],
        "runStatus": artifacts["runStatus"],
    }


def local_completion_artifacts(
    snapshot: dict[str, Any],
    *,
    gcs_reader: Callable[[str], bytes] = read_gcs_bytes,
) -> dict[str, Any] | None:
    locations = snapshot.get("locations") or {}
    try:
        reading_pdf = Path(str(locations["readingPdfLocal"]))
        generation_report = json.loads(
            Path(str(locations["generationReportLocal"])).read_text(encoding="utf-8")
        )
        reading_quality = json.loads(
            Path(str(locations["readingQualityLocal"])).read_text(encoding="utf-8")
        )
        reading_qa = json.loads(
            Path(str(locations["readingQaLocal"])).read_text(encoding="utf-8")
        )
        run_status = json.loads(
            Path(str(locations["runStatusLocal"])).read_text(encoding="utf-8")
        )
    except (KeyError, FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    publication_valid = True
    reading_pdf_gcs = locations.get("readingPdfGcs")
    if reading_pdf_gcs:
        publication = (
            generation_report.get("publication")
            if isinstance(generation_report, dict)
            else {}
        )
        if not isinstance(publication, dict):
            publication = {}
        publication_artifacts = (
            publication.get("artifacts")
        )
        published_pdf = next(
            (
                artifact
                for artifact in publication_artifacts or []
                if isinstance(artifact, dict)
                and artifact.get("gcsUri") == reading_pdf_gcs
            ),
            None,
        )
        local_pdf_sha256 = (
            hashlib.sha256(reading_pdf.read_bytes()).hexdigest()
            if reading_pdf.is_file()
            else None
        )
        try:
            current_gcs_bytes = gcs_reader(str(reading_pdf_gcs))
        except Exception:
            return None
        current_gcs_sha256 = hashlib.sha256(current_gcs_bytes).hexdigest()
        publication_valid = bool(
            publication.get("status") == "pass"
            and published_pdf
            and published_pdf.get("localSha256") == local_pdf_sha256
            and published_pdf.get("gcsSha256") == current_gcs_sha256
            and current_gcs_sha256 == local_pdf_sha256
            and published_pdf.get("localSize") == reading_pdf.stat().st_size
            and published_pdf.get("gcsSize") == len(current_gcs_bytes)
            and len(current_gcs_bytes) == reading_pdf.stat().st_size
        )
    valid = bool(
        reading_pdf.is_file()
        and reading_pdf.stat().st_size > 0
        and isinstance(generation_report, dict)
        and generation_report.get("status") == "completed"
        and publication_valid
        and isinstance(reading_quality, dict)
        and reading_quality.get("status") == "pass"
        and isinstance(reading_qa, dict)
        and reading_qa.get("status") == "pass"
        and isinstance(run_status, dict)
        and run_status.get("status") == "complete"
    )
    if not valid:
        return None
    return {
        "generation": sermon_production_supervisor.public_generation_report(
            generation_report
        ),
        "runStatus": run_status,
    }


def completed_report_from_snapshot(
    args: argparse.Namespace,
    snapshot: dict[str, Any],
    *,
    latch_source: str,
) -> dict[str, Any] | None:
    generation = snapshot.get("generation") or {}
    quality = snapshot.get("quality") or {}
    reading_quality = quality.get("readingEdition") or {}
    pdf_quality = quality.get("readingPdf") or {}
    recommended = snapshot.get("recommendedAction") or {}
    reading_pdf_gcs = (snapshot.get("locations") or {}).get("readingPdfGcs")
    publication = generation.get("publication") or {}
    if not (
        generation.get("status") == "completed"
        and reading_quality.get("status") == "pass"
        and pdf_quality.get("status") == "pass"
        and recommended.get("action") == "complete"
        and (not reading_pdf_gcs or publication.get("status") == "pass")
    ):
        return None
    evidence = [
        "generation.status=completed",
        "quality.readingEdition.status=pass",
        "quality.readingPdf.status=pass",
        "recommendedAction.action=complete",
    ]
    if reading_pdf_gcs:
        evidence.append("generation.publication.status=pass")
        evidence.append(f"locations.readingPdfGcs={reading_pdf_gcs}")
    return {
        "schemaVersion": 1,
        "status": "complete",
        "sunday": args.sunday,
        "mode": args.mode,
        "model": args.model,
        "approvalWritten": False,
        "traceSensitiveDataIncluded": False,
        "completionLatch": {
            "status": "already_complete",
            "source": latch_source,
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "skippedSourceRefresh": True,
            "skippedSecretAccess": True,
            "skippedAgentRun": True,
        },
        "decision": {
            "status": "complete",
            "action": "already_complete",
            "summary_zh": "本周阅读版 PDF 已完成且两项质量检查通过；本次触发已在入口结束。",
            "human_action_required": False,
            "modelDecisionAccepted": False,
            "evidence": evidence,
        },
        "sourceRefresh": {
            "status": "skipped",
            "reason": "completed_production_latch",
        },
        "finalSnapshot": snapshot,
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> int:
    args = make_agent_args(parse_args())
    if args.resume_failed_generation:
        result = sermon_production_supervisor.resume_failed_reading_pdf_generation(
            run_sermon_production_supervisor_agent.make_config(args)
        )
        final_snapshot = sermon_production_supervisor.production_snapshot(
            run_sermon_production_supervisor_agent.make_config(args)
        )
        report = {
            "schemaVersion": 1,
            "status": "complete" if result.get("status") == "completed" else "blocked",
            "sunday": args.sunday,
            "mode": args.mode,
            "model": args.model,
            "approvalWritten": False,
            "traceSensitiveDataIncluded": False,
            "sourceRefresh": {
                "status": "skipped",
                "reason": "explicit_failed_generation_resume",
            },
            "resumeResult": result,
            "finalSnapshot": final_snapshot,
        }
        write_report(args.out, report)
        return 0 if result.get("status") == "completed" else 2
    completed = completed_production_report(args)
    if completed is not None:
        write_report(args.out, completed)
        return 0
    if args.skip_source_refresh:
        source_refresh = {"status": "skipped"}
    else:
        try:
            source_refresh = refresh_source_state(args)
        except Exception as exc:
            source_refresh = {
                "status": "failed",
                "errorClass": exc.__class__.__name__,
                "reason": str(exc)[:500],
            }
    report = asyncio.run(run_sermon_production_supervisor_agent.run_agent(args))
    report["sourceRefresh"] = source_refresh
    write_report(args.out, report)
    return 0 if report.get("status") in {"observed", "advanced", "complete"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
