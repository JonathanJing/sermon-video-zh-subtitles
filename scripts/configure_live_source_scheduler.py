#!/usr/bin/env python3
"""Configure Cloud Scheduler to trigger Sunday live-source discovery."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote


DEFAULT_JOB_ID = "sermon-live-source-discovery"
DEFAULT_SCHEDULE = "55 9 * * SUN"
DEFAULT_TIMEZONE = "America/Los_Angeles"
DEFAULT_TOKEN_ENV = "INTERNAL_TASK_TOKEN"


@dataclass(frozen=True)
class SchedulerPlan:
    job_id: str
    endpoint: str
    payload: dict[str, Any]
    update_command: list[str]
    create_command: list[str]


def main() -> int:
    args = parse_args()
    token = os.getenv(args.internal_task_token_env, "")
    if args.apply and not token:
        raise SystemExit(f"{args.internal_task_token_env} is required with --apply")
    plan = build_scheduler_plan(args, internal_task_token=token or "REDACTED")
    if args.apply:
        result = ensure_scheduler_job(plan)
    else:
        result = {
            "status": "dry-run",
            "message": "Pass --apply after setting INTERNAL_TASK_TOKEN to create or update the job.",
        }
    print(json.dumps(sanitized_report(plan, result), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Google Cloud project id.")
    parser.add_argument("--location", default="us-west1", help="Cloud Scheduler location.")
    parser.add_argument("--job-id", default=DEFAULT_JOB_ID)
    parser.add_argument("--service-url", required=True, help="Cloud Run service base URL.")
    parser.add_argument(
        "--sunday",
        default="current",
        help="Sunday route value. Use current so the backend resolves the active Sunday at runtime.",
    )
    parser.add_argument("--schedule", default=DEFAULT_SCHEDULE, help="Cron schedule in the configured timezone.")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--service", default="auto", choices=["auto", "830", "1000"])
    parser.add_argument("--operator-alert-time", default="09:58")
    parser.add_argument("--expected-title")
    parser.add_argument("--manual-url", action="append", default=[])
    parser.add_argument("--include-candidates", action="store_true")
    parser.add_argument("--no-auto-generate", action="store_true")
    parser.add_argument("--attempt-deadline", default="180s")
    parser.add_argument("--internal-task-token-env", default=DEFAULT_TOKEN_ENV)
    parser.add_argument("--apply", action="store_true", help="Run gcloud. Default is a redacted dry run.")
    return parser.parse_args()


def build_scheduler_plan(args: argparse.Namespace, *, internal_task_token: str) -> SchedulerPlan:
    endpoint = discover_endpoint(args.service_url, args.sunday)
    payload = discovery_payload(args)
    message_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    headers = f"Content-Type=application/json,X-Internal-Task-Token={internal_task_token}"
    base = [
        "gcloud",
        "scheduler",
        "jobs",
    ]
    common = [
        "http",
        args.job_id,
        "--project",
        args.project,
        "--location",
        args.location,
        "--schedule",
        args.schedule,
        "--time-zone",
        args.timezone,
        "--uri",
        endpoint,
        "--http-method",
        "POST",
        "--headers",
        headers,
        "--message-body",
        message_body,
        "--attempt-deadline",
        args.attempt_deadline,
    ]
    create_command = [
        *base,
        "create",
        *common,
        "--description",
        "Sunday sermon live-source discovery and offline caption generation handoff.",
    ]
    update_command = [*base, "update", *common]
    return SchedulerPlan(
        job_id=args.job_id,
        endpoint=endpoint,
        payload=payload,
        update_command=update_command,
        create_command=create_command,
    )


def discovery_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "triggerSource": "cloud-scheduler",
        "service": args.service,
        "operatorAlertTime": args.operator_alert_time,
        "autoGenerate": not args.no_auto_generate,
    }
    if args.expected_title:
        payload["expectedTitle"] = args.expected_title
    if args.manual_url:
        payload["manualUrls"] = args.manual_url
    if args.include_candidates:
        payload["includeCandidates"] = True
    return payload


def discover_endpoint(service_url: str, sunday: str) -> str:
    base = service_url.rstrip("/")
    return f"{base}/api/admin/sundays/{quote(sunday, safe='')}/discover-source"


def ensure_scheduler_job(
    plan: SchedulerPlan,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, Any]:
    update = runner(plan.update_command, capture_output=True, text=True)
    if update.returncode == 0:
        return {"status": "updated", "jobId": plan.job_id}
    create = runner(plan.create_command, capture_output=True, text=True)
    if create.returncode == 0:
        return {"status": "created", "jobId": plan.job_id}
    return {
        "status": "failed",
        "jobId": plan.job_id,
        "updateReturnCode": update.returncode,
        "createReturnCode": create.returncode,
        "stderr": redact_text((create.stderr or update.stderr or "")[:400]),
    }


def sanitized_report(plan: SchedulerPlan, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "status": result.get("status"),
        "jobId": plan.job_id,
        "endpoint": plan.endpoint,
        "payload": plan.payload,
        "commands": {
            "update": redact_command(plan.update_command),
            "create": redact_command(plan.create_command),
        },
        "result": {key: value for key, value in result.items() if key != "stderr"},
        "authMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def redact_command(command: list[str]) -> list[str]:
    redacted = []
    for item in command:
        redacted.append(redact_text(item))
    return redacted


def redact_text(text: str) -> str:
    return re_redact_header_token(text)


def re_redact_header_token(text: str) -> str:
    marker = "X-Internal-Task-Token="
    if marker not in text:
        return text
    before, after = text.split(marker, 1)
    for separator in [",", " ", "\n"]:
        if separator in after:
            token, rest = after.split(separator, 1)
            return f"{before}{marker}REDACTED{separator}{rest}"
    return f"{before}{marker}REDACTED"


if __name__ == "__main__":
    raise SystemExit(main())
