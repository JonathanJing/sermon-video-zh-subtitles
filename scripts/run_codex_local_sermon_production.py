#!/usr/bin/env python3
"""Run the production sermon supervisor from the local Codex automation environment."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.config import upcoming_sunday
from scripts import live_source_monitor, run_sermon_production_supervisor_agent


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
        help="Skip the local sat-auto source refresh and only consume existing GCS state.",
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
        discord_bot_token_secret=None,
        discord_channel_id=None,
        notify_sendgrid_secret=args.notify_sendgrid_secret,
        notify_recipients_secret=args.notify_recipients_secret,
        notify_sender_secret=args.notify_sender_secret,
        model=args.model,
        mode=args.mode,
        max_turns=args.max_turns,
        skip_source_refresh=args.skip_source_refresh,
        approve_window=False,
        start_time=None,
        end_time=None,
        approved_by=None,
        approval_note=None,
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
    monitor_args = argparse.Namespace(
        sunday=sunday,
        service="sat-auto",
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
        timezone="America/Los_Angeles",
        now=None,
        min_confidence=0.70,
        operator_alert_time="17:50",
        backend_url="http://127.0.0.1:8080",
        post_generate=False,
        admin_token=None,
        internal_task_token=None,
    )
    previous_state = live_source_monitor.read_state(monitor_args.state_file)
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
        "selectedSource": report.get("selectedSource"),
        "operatorAlert": report.get("operatorAlert"),
        "report": str(out),
        "completedAt": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    args = make_agent_args(parse_args())
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
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("status") in {"observed", "advanced", "complete"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
