#!/usr/bin/env python3
"""Preflight OpenAI model access for the text routes used by production."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
from typing import Any

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODELS = ["gpt-5.5-mini"]
SECRET_RESOURCE_RE = re.compile(
    r"^projects/(?P<project>[^/\s]+)/secrets/(?P<secret>[^/\s]+)(?:/versions/(?P<version>[^/\s]+))?$"
)


def main() -> int:
    args = parse_args()
    return run_and_write(args)


def run_and_write(args: argparse.Namespace) -> int:
    report = run_preflight(args)
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    secret_source = parser.add_mutually_exclusive_group(required=True)
    secret_source.add_argument("--api-key-secret", help="Secret Manager resource for the OpenAI API key.")
    secret_source.add_argument(
        "--cloud-run-service",
        help="Read OPENAI_API_KEY_SECRET from a Cloud Run service before testing model access.",
    )
    parser.add_argument("--project", help="GCP project for --cloud-run-service.")
    parser.add_argument("--region", help="Cloud Run region for --cloud-run-service.")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY_SECRET")
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="OpenAI text model to test through Responses API. Repeatable.",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.cloud_run_service and (not args.project or not args.region):
        raise SystemExit("--cloud-run-service requires --project and --region")
    args.models = args.model or DEFAULT_MODELS
    return args


def run_preflight(args: argparse.Namespace) -> dict[str, Any]:
    api_key_secret = resolve_api_key_secret(args)
    validate_secret_resource_name(api_key_secret)
    checks: list[dict[str, Any]] = []
    try:
        api_key = access_secret(api_key_secret)
        add_check(checks, "api_key_secret_access", True, "secret value read from Secret Manager")
    except Exception as exc:
        add_check(checks, "api_key_secret_access", False, sanitize_error_message(str(exc)))
        return report_from_checks(args, checks)

    for model in args.models:
        result = responses_smoke(model=model, api_key=api_key)
        add_check(
            checks,
            f"responses_model:{model}",
            result["status"] == "ok",
            result,
        )
    return report_from_checks(args, checks)


def responses_smoke(*, model: str, api_key: str) -> dict[str, Any]:
    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": "Return strict JSON only."}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": 'Return {"ok":true}.'}],
            },
        ],
        "text": {"format": {"type": "json_object"}},
    }
    response = requests.post(
        OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=45,
    )
    if response.status_code >= 400:
        error_message = sanitize_error_message(safe_error_message(response))
        return {
            "status": "failed",
            "model": model,
            "endpoint": "responses",
            "httpStatus": response.status_code,
            "failureKind": classify_model_access_failure(response.status_code, error_message),
            "error": error_message,
        }
    content = parse_response_content(response)
    return {
        "status": "ok",
        "model": model,
        "endpoint": "responses",
        "httpStatus": response.status_code,
        "responseJson": parse_json_object(content),
    }


def report_from_checks(args: argparse.Namespace, checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [check for check in checks if check["state"] == "fail"]
    return {
        "schemaVersion": 1,
        "status": "failed" if failed else "ok",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "models": args.models,
        "checks": checks,
        "failedChecks": [check["name"] for check in failed],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def add_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any) -> None:
    checks.append({"name": name, "state": "pass" if passed else "fail", "observed": observed})


def parse_response_content(response: requests.Response) -> str:
    data = response.json()
    return extract_response_text(data)


def extract_response_text(data: dict[str, Any]) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text") or content.get("output_text")
            if isinstance(text, str) and text.strip():
                return text
    raise SystemExit("OpenAI response did not include output text.")


def parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Could not parse OpenAI JSON response: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("OpenAI response JSON was not an object.")
    return parsed


def safe_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:400]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or "unknown error")
    return str(data)[:400]


def classify_model_access_failure(status_code: int, message: str) -> str:
    lower = str(message or "").lower()
    if status_code in {400, 404} and (
        "does not exist" in lower
        or "not found" in lower
        or "do not have access" in lower
        or "don't have access" in lower
        or "model" in lower and "access" in lower
    ):
        return "model_unavailable_or_not_found"
    if status_code in {401, 403}:
        return "auth_or_permission_denied"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "provider_server_error"
    return "request_failed"


def validate_secret_resource_name(value: str) -> None:
    if not SECRET_RESOURCE_RE.fullmatch(value):
        raise SystemExit(
            "--api-key-secret must be a Google Secret Manager resource name like "
            "projects/PROJECT_ID/secrets/openai-api-key/versions/latest. Do not pass raw API key material."
        )


def resolve_api_key_secret(args: argparse.Namespace) -> str:
    direct = getattr(args, "api_key_secret", None)
    if direct:
        return str(direct)
    service = load_cloud_run_service(
        service=getattr(args, "cloud_run_service", None),
        project=getattr(args, "project", None),
        region=getattr(args, "region", None),
    )
    env_name = getattr(args, "api_key_env", None) or "OPENAI_API_KEY_SECRET"
    return extract_env_secret_resource(service, env_name)


def load_cloud_run_service(*, service: str | None, project: str | None, region: str | None) -> dict[str, Any]:
    if not service or not project or not region:
        raise SystemExit("--cloud-run-service requires --project and --region")
    proc = subprocess.run(
        [
            "gcloud",
            "run",
            "services",
            "describe",
            service,
            "--project",
            project,
            "--region",
            region,
            "--format=json",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    data = json.loads(proc.stdout)
    if not isinstance(data, dict):
        raise SystemExit("Cloud Run service describe did not return a JSON object.")
    return data


def extract_env_secret_resource(service: dict[str, Any], env_name: str) -> str:
    for container in cloud_run_containers(service):
        for item in container.get("env", []) or []:
            if item.get("name") != env_name:
                continue
            value = item.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
            secret_ref = (
                nested(item, "valueSource", "secretKeyRef", "secret")
                or nested(item, "valueFrom", "secretKeyRef", "name")
            )
            if isinstance(secret_ref, str) and secret_ref.strip():
                version = (
                    nested(item, "valueSource", "secretKeyRef", "version")
                    or nested(item, "valueFrom", "secretKeyRef", "key")
                    or "latest"
                )
                return normalize_secret_resource(secret_ref.strip(), str(version).strip())
    raise SystemExit(f"{env_name} is not configured on Cloud Run.")


def normalize_secret_resource(secret_ref: str, version: str) -> str:
    if SECRET_RESOURCE_RE.fullmatch(secret_ref):
        return secret_ref
    raise SystemExit(
        "Cloud Run OPENAI_API_KEY_SECRET must be a full Secret Manager resource name; "
        "resource names are not included in this report."
    )


def cloud_run_containers(service: dict[str, Any]) -> list[dict[str, Any]]:
    containers = nested(service, "template", "containers")
    if isinstance(containers, list):
        return [item for item in containers if isinstance(item, dict)]
    containers = nested(service, "spec", "template", "spec", "containers")
    if isinstance(containers, list):
        return [item for item in containers if isinstance(item, dict)]
    return []


def nested(data: Any, *keys: str) -> Any:
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def access_secret(resource_name: str) -> str:
    match = SECRET_RESOURCE_RE.fullmatch(resource_name)
    if not match:
        raise SystemExit("Invalid Secret Manager resource name.")
    project = match.group("project")
    secret = match.group("secret")
    version = match.group("version") or "latest"
    proc = subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            version,
            "--secret",
            secret,
            "--project",
            project,
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    value = proc.stdout.strip()
    if not value:
        raise SystemExit(f"Secret {resource_name} returned an empty value.")
    return value


def sanitize_error_message(message: str) -> str:
    clean = str(message or "unknown error")
    clean = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-REDACTED", clean)
    clean = re.sub(
        r"projects/[^/\s]+/secrets/[^/\s]+(?:/versions/[^/\s]+)?",
        "projects/REDACTED/secrets/REDACTED/versions/REDACTED",
        clean,
    )
    return clean[:500]


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
