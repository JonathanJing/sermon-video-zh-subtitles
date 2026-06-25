#!/usr/bin/env python3
"""Validate Cloud Run settings needed for realtime caption sessions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_ENV_TOKENS = ("KEY", "TOKEN", "SECRET", "COOKIE", "WEBHOOK")
RESOURCE_REF_ENV_NAMES = {"OPENAI_API_KEY_SECRET"}


def main() -> int:
    args = parse_args()
    report = validate_cloud_run_realtime_config(args)
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--service-json", type=Path, help="Saved `gcloud run services describe --format=json` output.")
    source.add_argument("--service", help="Cloud Run service name to describe with gcloud.")
    parser.add_argument("--project", help="GCP project for --service.")
    parser.add_argument("--region", help="Cloud Run region for --service.")
    parser.add_argument(
        "--allow-multi-instance",
        action="store_true",
        help="Allow max instances > 1 only after a shared realtime fanout store is deployed.",
    )
    parser.add_argument("--out", type=Path, help="Optional JSON report path.")
    args = parser.parse_args()
    if args.service and (not args.project or not args.region):
        raise SystemExit("--service requires --project and --region")
    return args


def validate_cloud_run_realtime_config(args: argparse.Namespace) -> dict[str, Any]:
    service = load_service(args)
    env = collect_env(service)
    max_instances = cloud_run_max_instances(service)
    concurrency = cloud_run_concurrency(service)
    ready = cloud_run_ready(service)

    direct_secret_env_names = sorted(name for name, item in env.items() if is_direct_secret_env(name, item))
    checks: list[dict[str, Any]] = []
    add_check(checks, "service_ready", ready is not False, ready)
    add_check(
        checks,
        "single_instance_realtime_sse",
        args.allow_multi_instance or max_instances in {None, 0, 1},
        max_instances,
    )
    add_check(
        checks,
        "realtime_event_gcs_prefix",
        valid_gcs_prefix(env_value(env, "REALTIME_EVENT_GCS_PREFIX")),
        env_has(env, "REALTIME_EVENT_GCS_PREFIX"),
    )
    add_check(checks, "artifact_bucket", env_has(env, "SERMON_ARTIFACT_BUCKET"), env_has(env, "SERMON_ARTIFACT_BUCKET"))
    add_check(checks, "artifact_prefix", env_has(env, "SERMON_ARTIFACT_PREFIX"), env_has(env, "SERMON_ARTIFACT_PREFIX"))
    add_check(checks, "timezone", env_value(env, "APP_TIMEZONE") == "America/Los_Angeles", env_has(env, "APP_TIMEZONE"))
    add_check(
        checks,
        "openai_key_server_side",
        env_has(env, "OPENAI_API_KEY_SECRET") or env_has_secret_ref(env, "OPENAI_API_KEY"),
        {
            "hasOpenaiApiKeySecretRef": env_has(env, "OPENAI_API_KEY_SECRET"),
            "hasOpenaiApiKeySecretEnv": env_has_secret_ref(env, "OPENAI_API_KEY"),
        },
    )
    add_check(checks, "operator_admin_token", env_has(env, "OPERATOR_ADMIN_TOKEN"), env_has(env, "OPERATOR_ADMIN_TOKEN"))
    add_check(checks, "internal_task_token", env_has(env, "INTERNAL_TASK_TOKEN"), env_has(env, "INTERNAL_TASK_TOKEN"))
    add_check(checks, "no_direct_secret_env_values", not direct_secret_env_names, direct_secret_env_names)

    failed = [check for check in checks if check["state"] == "fail"]
    return {
        "schemaVersion": 1,
        "status": "failed" if failed else "ok",
        "failedChecks": [check["name"] for check in failed],
        "checks": checks,
        "cloudRun": {
            "service": service_name(service),
            "project": args.project if args.service else None,
            "region": args.region if args.service else None,
            "ready": ready,
            "maxInstances": max_instances,
            "containerConcurrency": concurrency,
            "configuredEnv": sorted(env),
            "allowMultiInstance": bool(args.allow_multi_instance),
        },
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def load_service(args: argparse.Namespace) -> dict[str, Any]:
    if args.service_json:
        return json.loads(resolve_repo_path(args.service_json).read_text(encoding="utf-8"))
    completed = subprocess.run(
        [
            "gcloud",
            "run",
            "services",
            "describe",
            args.service,
            "--project",
            args.project,
            "--region",
            args.region,
            "--format=json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def cloud_run_ready(service: dict[str, Any]) -> bool | None:
    status = service.get("status")
    if not isinstance(status, dict):
        return None
    for condition in status.get("conditions", []):
        if condition.get("type") == "Ready":
            return str(condition.get("status")).lower() == "true"
    return None


def cloud_run_max_instances(service: dict[str, Any]) -> int | None:
    candidates = [
        nested(service, "template", "scaling", "maxInstanceCount"),
        nested(service, "spec", "template", "metadata", "annotations", "autoscaling.knative.dev/maxScale"),
        nested(service, "metadata", "annotations", "run.googleapis.com/maxScale"),
    ]
    for value in candidates:
        parsed = parse_int(value)
        if parsed is not None:
            return parsed
    return None


def cloud_run_concurrency(service: dict[str, Any]) -> int | None:
    candidates = [
        nested(service, "template", "maxInstanceRequestConcurrency"),
        nested(service, "spec", "template", "spec", "containerConcurrency"),
    ]
    for value in candidates:
        parsed = parse_int(value)
        if parsed is not None:
            return parsed
    return None


def collect_env(service: dict[str, Any]) -> dict[str, dict[str, Any]]:
    env: dict[str, dict[str, Any]] = {}
    for container in containers(service):
        for item in container.get("env", []) or []:
            name = item.get("name")
            if name:
                env[str(name)] = item
    return env


def containers(service: dict[str, Any]) -> list[dict[str, Any]]:
    found = nested(service, "template", "containers")
    if isinstance(found, list):
        return [item for item in found if isinstance(item, dict)]
    found = nested(service, "spec", "template", "spec", "containers")
    if isinstance(found, list):
        return [item for item in found if isinstance(item, dict)]
    return []


def env_has(env: dict[str, dict[str, Any]], name: str) -> bool:
    return name in env


def env_value(env: dict[str, dict[str, Any]], name: str) -> str | None:
    value = env.get(name, {}).get("value")
    return str(value).strip() if value is not None else None


def env_has_secret_ref(env: dict[str, dict[str, Any]], name: str) -> bool:
    item = env.get(name) or {}
    return bool(item.get("valueSource") or item.get("valueFrom"))


def is_direct_secret_env(name: str, item: dict[str, Any]) -> bool:
    if name in RESOURCE_REF_ENV_NAMES:
        return False
    if not any(token in name.upper() for token in SENSITIVE_ENV_TOKENS):
        return False
    if item.get("valueSource") or item.get("valueFrom"):
        return False
    return bool(str(item.get("value") or "").strip())


def valid_gcs_prefix(value: str | None) -> bool:
    if not value or not value.startswith("gs://"):
        return False
    rest = value[5:].strip("/")
    bucket, sep, prefix = rest.partition("/")
    return bool(bucket and sep and prefix)


def service_name(service: dict[str, Any]) -> str | None:
    return nested(service, "metadata", "name") or nested(service, "name")


def add_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any) -> None:
    checks.append({"name": name, "state": "pass" if passed else "fail", "observed": observed})


def nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
