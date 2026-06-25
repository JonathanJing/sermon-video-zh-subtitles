#!/usr/bin/env python3
"""Prepare a redacted Cloud Run update plan for realtime caption readiness."""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    args = parse_args()
    plan = build_plan(args)
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-report", type=Path, required=True, help="validate_cloud_run_realtime_config.py report.")
    parser.add_argument("--service", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument(
        "--realtime-event-gcs-prefix",
        default="gs://sermon-zh-artifacts-ai-for-god/realtime-events",
    )
    parser.add_argument("--operator-admin-secret", default="operator-admin-token")
    parser.add_argument("--internal-task-secret", default="internal-task-token")
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    report = read_report(args.config_report)
    failed = list(report.get("failedChecks") or [])
    current = report.get("cloudRun") if isinstance(report.get("cloudRun"), dict) else {}
    service = args.service
    project = args.project
    region = args.region
    update_command = [
        "gcloud",
        "run",
        "services",
        "update",
        service,
        "--project",
        project,
        "--region",
        region,
        "--max-instances",
        "1",
        "--update-env-vars",
        f"REALTIME_EVENT_GCS_PREFIX={args.realtime_event_gcs_prefix}",
        "--update-secrets",
        f"OPERATOR_ADMIN_TOKEN={args.operator_admin_secret}:latest,INTERNAL_TASK_TOKEN={args.internal_task_secret}:latest",
        "--quiet",
    ]
    rollback_command = rollback_command_for(
        service=service,
        project=project,
        region=region,
        previous_max_instances=current.get("maxInstances"),
    )
    validation_commands = [
        [
            "python3",
            "scripts/validate_cloud_run_realtime_config.py",
            "--service",
            service,
            "--project",
            project,
            "--region",
            region,
            "--out",
            "artifacts/evidence/cloud-run-realtime-config.json",
        ],
        [
            "python3",
            "scripts/run_cloud_run_realtime_preflight.py",
            "--base-url",
            "https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app",
            "--cloud-run-config-report",
            "artifacts/evidence/cloud-run-realtime-config.json",
            "--create-realtime-session",
            "--internal-task-token",
            "$INTERNAL_TASK_TOKEN",
            "--out",
            "artifacts/evidence/cloud-run-api-preflight.json",
        ],
    ]
    return {
        "schemaVersion": 1,
        "status": "approval_required" if failed else "already_ready",
        "requiresExplicitApproval": bool(failed),
        "reason": (
            "Cloud Run runtime and secret wiring will be changed; execute only after operator approval."
            if failed
            else "Current config report has no failed checks."
        ),
        "currentConfig": {
            "service": current.get("service") or service,
            "project": current.get("project") or project,
            "region": current.get("region") or region,
            "ready": current.get("ready"),
            "maxInstances": current.get("maxInstances"),
            "containerConcurrency": current.get("containerConcurrency"),
            "configuredEnv": current.get("configuredEnv") or [],
            "failedChecks": failed,
        },
        "plannedChanges": [
            {
                "name": "single_instance_realtime_sse",
                "action": "set Cloud Run max instances to 1 for the current in-process realtime SSE session store",
                "needed": "single_instance_realtime_sse" in failed,
            },
            {
                "name": "realtime_event_gcs_prefix",
                "action": "set REALTIME_EVENT_GCS_PREFIX so sanitized realtime deltas are mirrored to GCS",
                "needed": "realtime_event_gcs_prefix" in failed,
            },
            {
                "name": "operator_admin_token",
                "action": "inject OPERATOR_ADMIN_TOKEN from Secret Manager",
                "needed": "operator_admin_token" in failed,
            },
            {
                "name": "internal_task_token",
                "action": "inject INTERNAL_TASK_TOKEN from Secret Manager",
                "needed": "internal_task_token" in failed,
            },
        ],
        "commands": {
            "apply": command_record(update_command),
            "rollback": command_record(rollback_command),
            "validate": [command_record(command) for command in validation_commands],
        },
        "postApplyEvidence": [
            "artifacts/evidence/cloud-run-realtime-config.json",
            "artifacts/evidence/cloud-run-api-preflight.json",
        ],
        "apiKeyMaterialIncluded": False,
        "secretReferencesIncluded": True,
        "secretResourceNamesIncluded": False,
    }


def rollback_command_for(
    *,
    service: str,
    project: str,
    region: str,
    previous_max_instances: Any,
) -> list[str]:
    command = [
        "gcloud",
        "run",
        "services",
        "update",
        service,
        "--project",
        project,
        "--region",
        region,
    ]
    if previous_max_instances:
        command.extend(["--max-instances", str(previous_max_instances)])
    command.extend(
        [
            "--remove-env-vars",
            "REALTIME_EVENT_GCS_PREFIX,OPERATOR_ADMIN_TOKEN,INTERNAL_TASK_TOKEN",
            "--quiet",
        ]
    )
    return command


def command_record(command: list[str]) -> dict[str, Any]:
    return {
        "argv": command,
        "shell": " ".join(shlex.quote(part) for part in command),
    }


def read_report(path: Path) -> dict[str, Any]:
    data = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("--config-report must be a JSON object")
    return data


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
