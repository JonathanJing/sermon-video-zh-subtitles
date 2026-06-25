#!/usr/bin/env python3
"""Run Cloud Run API preflight checks for realtime caption readiness."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_REALTIME_MODEL = "gpt-realtime-translate"
EXPECTED_STABLE_MODEL = "gpt-5.5-mini"
EXPECTED_TARGET_LANGUAGE = "zh"
EXPECTED_AUDIO_SOURCE_KIND = "ipad_mic"
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"projects/[^/\"'\s]+/secrets/[^/\"'\s]+(?:/versions/[^/\"'\s]+)?"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{12,}"),
]


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
    parser.add_argument("--base-url", required=True, help="Cloud Run service base URL.")
    parser.add_argument("--cloud-run-config-report", type=Path, help="validate_cloud_run_realtime_config.py report.")
    parser.add_argument("--sunday", default="current")
    parser.add_argument("--admin-token", help="Operator admin token for optional realtime session creation.")
    parser.add_argument("--internal-task-token", help="Internal task token for optional realtime session creation.")
    parser.add_argument(
        "--create-realtime-session",
        action="store_true",
        help="POST a backend-only realtime session and verify the sanitized response shape.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=20)
    parser.add_argument("--out", type=Path, help="Optional JSON report path.")
    args = parser.parse_args()
    if args.create_realtime_session and not (args.admin_token or args.internal_task_token):
        raise SystemExit("--create-realtime-session requires --admin-token or --internal-task-token")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be > 0")
    return args


def run_preflight(args: argparse.Namespace) -> dict[str, Any]:
    base_url = normalize_base_url(args.base_url)
    checks: list[dict[str, Any]] = []
    raw_texts: list[str] = []

    config_report = read_config_report(args.cloud_run_config_report) if args.cloud_run_config_report else None
    add_check(
        checks,
        "cloud_run_realtime_config",
        config_report is not None and config_report.get("status") == "ok",
        compact_config(config_report),
        state="pass" if config_report and config_report.get("status") == "ok" else "warn",
    )

    root = fetch_json_or_text(base_url + "/", timeout=args.timeout_seconds)
    raw_texts.append(root["raw"])
    add_check(checks, "root_serves_html", root["status"] == 200 and "html" in root["contentType"], root_summary(root))

    health = fetch_json_or_text(base_url + "/api/health", timeout=args.timeout_seconds)
    raw_texts.append(health["raw"])
    add_check(
        checks,
        "api_health",
        health["status"] == 200 and nested(health.get("json"), "status") == "ok",
        response_summary(health),
    )

    public_sunday = fetch_json_or_text(
        base_url + f"/api/sundays/{args.sunday}",
        timeout=args.timeout_seconds,
    )
    raw_texts.append(public_sunday["raw"])
    add_check(
        checks,
        "public_sunday_read",
        public_sunday["status"] == 200 and isinstance(public_sunday.get("json"), dict),
        public_sunday_summary(public_sunday),
    )

    admin_status = fetch_json_or_text(base_url + "/api/admin/status", timeout=args.timeout_seconds)
    raw_texts.append(admin_status["raw"])
    add_check(
        checks,
        "admin_status_safe",
        admin_status["status"] == 200 and nested(admin_status.get("json"), "status") == "ok",
        admin_status_summary(admin_status),
    )

    realtime_session = None
    if args.create_realtime_session:
        realtime_session = create_realtime_session(base_url, args)
        raw_texts.append(realtime_session["raw"])
        body = realtime_session.get("json") if isinstance(realtime_session.get("json"), dict) else {}
        add_check(
            checks,
            "realtime_local_session_create",
            realtime_session["status"] == 201
            and body.get("status") == "ready"
            and body.get("model") == EXPECTED_REALTIME_MODEL
            and body.get("targetLanguage") == EXPECTED_TARGET_LANGUAGE
            and body.get("audioSourceKind") == EXPECTED_AUDIO_SOURCE_KIND
            and bool(body.get("sessionId"))
            and bool(body.get("eventToken"))
            and not body.get("clientSecret"),
            realtime_session_summary(realtime_session),
        )
        add_check(
            checks,
            "realtime_local_session_metadata",
            body.get("model") == EXPECTED_REALTIME_MODEL
            and body.get("targetLanguage") == EXPECTED_TARGET_LANGUAGE
            and body.get("audioSourceKind") == EXPECTED_AUDIO_SOURCE_KIND,
            {
                "model": body.get("model"),
                "targetLanguage": body.get("targetLanguage"),
                "audioSourceKind": body.get("audioSourceKind"),
            },
        )
    else:
        add_check(
            checks,
            "realtime_local_session_create",
            True,
            "skipped; pass --create-realtime-session after approving a live session smoke",
            state="warn",
        )

    leaked = secret_leak_labels(raw_texts)
    add_check(checks, "no_secret_material_in_http_responses", not leaked, leaked)

    failed = [check for check in checks if check["state"] == "fail"]
    warnings = [check for check in checks if check["state"] == "warn"]
    return {
        "schemaVersion": 1,
        "status": "failed" if failed else "ok",
        "failedChecks": [check["name"] for check in failed],
        "warnings": [check["name"] for check in warnings],
        "baseUrl": base_url,
        "sunday": args.sunday,
        "checks": checks,
        "realtimeSession": realtime_session_summary(realtime_session) if realtime_session else None,
        "models": {
            "realtimeDraft": EXPECTED_REALTIME_MODEL,
            "stableCorrection": EXPECTED_STABLE_MODEL,
        },
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def fetch_json_or_text(url: str, *, timeout: float) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json,text/html;q=0.9,*/*;q=0.1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return parse_response(raw, response.status, response.headers.get("Content-Type", ""))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return parse_response(raw, exc.code, exc.headers.get("Content-Type", ""), error=str(exc))
    except URLError as exc:
        return {"status": 0, "contentType": "", "raw": "", "json": None, "error": str(exc.reason)[:200]}


def create_realtime_session(base_url: str, args: argparse.Namespace) -> dict[str, Any]:
    body = json.dumps(
        {
            "sunday": args.sunday if args.sunday != "current" else date.today().isoformat(),
            "model": EXPECTED_REALTIME_MODEL,
            "targetLanguage": EXPECTED_TARGET_LANGUAGE,
            "audioSourceKind": EXPECTED_AUDIO_SOURCE_KIND,
            "triggerSource": "cloud-run-realtime-preflight",
        }
    ).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if args.admin_token:
        headers["Authorization"] = f"Bearer {args.admin_token}"
    if args.internal_task_token:
        headers["X-Internal-Task-Token"] = args.internal_task_token
    request = Request(
        base_url + "/api/admin/realtime/local-sessions",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=args.timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return parse_response(raw, response.status, response.headers.get("Content-Type", ""))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return parse_response(raw, exc.code, exc.headers.get("Content-Type", ""), error=str(exc))
    except URLError as exc:
        return {"status": 0, "contentType": "", "raw": "", "json": None, "error": str(exc.reason)[:200]}


def parse_response(raw: str, status: int, content_type: str, error: str | None = None) -> dict[str, Any]:
    data: Any = None
    if raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
    result = {
        "status": status,
        "contentType": content_type.split(";", 1)[0].strip().lower(),
        "raw": raw,
        "json": data,
    }
    if error:
        result["error"] = error[:200]
    return result


def read_config_report(path: Path) -> dict[str, Any]:
    data = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("--cloud-run-config-report must be a JSON object")
    return data


def root_summary(response: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": response["status"],
        "contentType": response["contentType"],
        "bytes": len(response["raw"].encode("utf-8")),
    }


def response_summary(response: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": response["status"],
        "contentType": response["contentType"],
        "jsonStatus": nested(response.get("json"), "status"),
        "error": response.get("error"),
    }


def public_sunday_summary(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("json") if isinstance(response.get("json"), dict) else {}
    return {
        "status": response["status"],
        "sunday": data.get("sunday"),
        "translationStatus": data.get("translationStatus"),
        "artifactCount": data.get("artifactCount"),
        "readinessState": nested(data, "readiness", "state"),
    }


def admin_status_summary(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("json") if isinstance(response.get("json"), dict) else {}
    return {
        "status": response["status"],
        "serviceHealth": nested(data, "service", "health"),
        "artifactBucketConfigured": bool(nested(data, "artifact", "bucket")),
        "openaiApiKey": nested(data, "secrets", "openaiApiKey"),
        "operatorAdminToken": nested(data, "secrets", "operatorAdminToken"),
        "internalTaskToken": nested(data, "secrets", "internalTaskToken"),
        "realtimeArchive": nested(data, "realtime", "eventArchive", "enabled"),
        "realtimeGcsMirror": nested(data, "realtime", "eventArchive", "gcsMirrorEnabled"),
    }


def realtime_session_summary(response: dict[str, Any] | None) -> dict[str, Any] | None:
    if not response:
        return None
    data = response.get("json") if isinstance(response.get("json"), dict) else {}
    return {
        "status": response["status"],
        "ready": data.get("status") == "ready",
        "sessionId": data.get("sessionId"),
        "model": data.get("model"),
        "targetLanguage": data.get("targetLanguage"),
        "audioSourceKind": data.get("audioSourceKind"),
        "eventTokenReturned": bool(data.get("eventToken")),
        "clientSecretReturned": bool(data.get("clientSecret")),
    }


def compact_config(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    return {
        "status": report.get("status"),
        "failedChecks": report.get("failedChecks") or [],
        "maxInstances": nested(report, "cloudRun", "maxInstances"),
        "configuredEnv": nested(report, "cloudRun", "configuredEnv") or [],
    }


def secret_leak_labels(texts: list[str]) -> list[str]:
    labels = []
    for pattern in SECRET_PATTERNS:
        if any(pattern.search(text) for text in texts):
            labels.append(pattern.pattern)
    return labels


def add_check(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    observed: Any,
    *,
    state: str | None = None,
) -> None:
    checks.append({"name": name, "state": state or ("pass" if passed else "fail"), "observed": observed})


def nested(data: Any, *keys: str) -> Any:
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def normalize_base_url(value: str) -> str:
    clean = value.strip().rstrip("/")
    if not clean.startswith(("https://", "http://")):
        raise SystemExit("--base-url must start with http:// or https://")
    return clean


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
