#!/usr/bin/env python3
"""Smoke test deployed WebRTC realtime session creation without storing secrets."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MODEL = "gpt-realtime-translate"
EXPECTED_TARGET_LANGUAGE = "zh"
EXPECTED_AUDIO_SOURCE_KIND = "ipad_mic"
EXPECTED_WEBRTC_URL = "https://api.openai.com/v1/realtime/calls"


def main() -> int:
    args = parse_args()
    report = run_smoke(args)
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--sunday", default="current")
    parser.add_argument("--admin-token")
    parser.add_argument("--internal-task-token")
    parser.add_argument("--timeout-seconds", type=float, default=20)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not (args.admin_token or args.internal_task_token):
        raise SystemExit("--admin-token or --internal-task-token is required")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be > 0")
    return args


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    base_url = normalize_base_url(args.base_url)
    response = create_webrtc_session(base_url, args)
    body = response.get("json") if isinstance(response.get("json"), dict) else {}
    session = session_summary(response, body)
    checks: list[dict[str, Any]] = []

    add_check(
        checks,
        "create_webrtc_realtime_session",
        response["status"] == 201
        and session["ready"] is True
        and session["model"] == EXPECTED_MODEL
        and session["targetLanguage"] == EXPECTED_TARGET_LANGUAGE
        and session["audioSourceKind"] == EXPECTED_AUDIO_SOURCE_KIND
        and bool(session["sessionId"])
        and session["eventTokenReturned"] is True
        and session["clientSecretReturned"] is True,
        session,
    )
    add_check(
        checks,
        "webrtc_session_metadata",
        session["model"] == EXPECTED_MODEL
        and session["targetLanguage"] == EXPECTED_TARGET_LANGUAGE
        and session["audioSourceKind"] == EXPECTED_AUDIO_SOURCE_KIND,
        {
            "model": session["model"],
            "targetLanguage": session["targetLanguage"],
            "audioSourceKind": session["audioSourceKind"],
        },
    )
    add_check(
        checks,
        "client_secret_returned_without_printing_value",
        session["clientSecretReturned"] is True,
        {
            "clientSecretReturned": session["clientSecretReturned"],
            "clientSecretExpiresAtReturned": session["clientSecretExpiresAtReturned"],
        },
    )
    add_check(
        checks,
        "event_token_returned_but_redacted",
        session["eventTokenReturned"] is True,
        {"eventTokenReturned": session["eventTokenReturned"]},
    )
    add_check(checks, "webrtc_calls_url", session["webrtcUrl"] == EXPECTED_WEBRTC_URL, session["webrtcUrl"])

    failed = [check for check in checks if check["state"] == "fail"]
    return {
        "schemaVersion": 1,
        "status": "failed" if failed else "ok",
        "failedChecks": [check["name"] for check in failed],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "baseUrl": base_url,
        "checks": checks,
        "realtimeSession": session,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
        "clientSecretIncluded": False,
    }


def create_webrtc_session(base_url: str, args: argparse.Namespace) -> dict[str, Any]:
    sunday = args.sunday if args.sunday != "current" else date.today().isoformat()
    payload = json.dumps(
        {
            "sunday": sunday,
            "model": EXPECTED_MODEL,
            "targetLanguage": EXPECTED_TARGET_LANGUAGE,
            "audioSourceKind": EXPECTED_AUDIO_SOURCE_KIND,
            "triggerSource": "deployed-webrtc-session-smoke",
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
        base_url + "/api/admin/realtime/sessions",
        data=payload,
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
        return {"status": 0, "contentType": "", "json": None, "error": str(exc.reason)[:200]}


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
        "json": data,
    }
    if error:
        result["error"] = error[:200]
    return result


def session_summary(response: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    client_secret = body.get("clientSecret") if isinstance(body.get("clientSecret"), dict) else {}
    webrtc = body.get("webrtc") if isinstance(body.get("webrtc"), dict) else {}
    return {
        "httpStatus": response["status"],
        "ready": body.get("status") == "ready",
        "model": body.get("model"),
        "targetLanguage": body.get("targetLanguage"),
        "audioSourceKind": body.get("audioSourceKind"),
        "sessionId": body.get("sessionId"),
        "eventTokenReturned": bool(body.get("eventToken")),
        "clientSecretReturned": bool(client_secret.get("value")),
        "clientSecretExpiresAtReturned": client_secret.get("expiresAt") is not None,
        "webrtcUrl": webrtc.get("url"),
        "error": body.get("error") or response.get("error"),
        "message": body.get("message"),
    }


def add_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any) -> None:
    checks.append({"name": name, "state": "pass" if passed else "fail", "observed": observed})


def normalize_base_url(url: str) -> str:
    return url.rstrip("/")


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
