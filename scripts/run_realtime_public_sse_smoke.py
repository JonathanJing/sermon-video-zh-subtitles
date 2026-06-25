#!/usr/bin/env python3
"""Smoke test backend realtime event persistence and public SSE fanout."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MODEL = "gpt-realtime-translate"
EXPECTED_TARGET_LANGUAGE = "zh"
EXPECTED_AUDIO_SOURCE_KIND = "ipad_mic"

try:
    from validate_realtime_session import (  # type: ignore
        parse_jsonl,
        read_text as read_validation_text,
        validate_realtime_session,
    )
except ModuleNotFoundError:
    from scripts.validate_realtime_session import (  # type: ignore
        parse_jsonl,
        read_text as read_validation_text,
        validate_realtime_session,
    )


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
    parser.add_argument("--sunday", required=True)
    parser.add_argument("--admin-token")
    parser.add_argument("--internal-task-token")
    parser.add_argument("--timeout-seconds", type=float, default=20)
    parser.add_argument(
        "--session-events-jsonl",
        help="Optional local path or gs:// URI for the session JSONL archive to validate.",
    )
    parser.add_argument(
        "--event-log-dir",
        type=Path,
        help="Optional local realtime event log directory used to derive <session_id>.jsonl.",
    )
    parser.add_argument(
        "--realtime-event-gcs-prefix",
        help="Optional GCS prefix used to derive the session JSONL archive URI from sunday/session id.",
    )
    parser.add_argument(
        "--web-realtime-contract-report",
        help="Optional validate_web_realtime_contract.py report; browser-normalized OpenAI events are posted to backend.",
    )
    parser.add_argument("--session-validation-out", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be > 0")
    return args


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    base_url = normalize_base_url(args.base_url)
    created = post_json(
        base_url + "/api/admin/realtime/local-sessions",
        {
            "sunday": args.sunday,
            "model": EXPECTED_MODEL,
            "targetLanguage": EXPECTED_TARGET_LANGUAGE,
            "audioSourceKind": EXPECTED_AUDIO_SOURCE_KIND,
            "triggerSource": "realtime-public-sse-smoke",
        },
        headers=admin_headers(args),
        timeout=args.timeout_seconds,
    )
    body = created.get("json") if isinstance(created.get("json"), dict) else {}
    session_id = str(body.get("sessionId") or "")
    event_token = str(body.get("eventToken") or "")
    add_check(
        checks,
        "create_local_session",
        created["status"] == 201 and body.get("status") == "ready" and bool(session_id) and bool(event_token),
        {
            "status": created["status"],
            "sessionId": session_id or None,
            "model": body.get("model"),
            "targetLanguage": body.get("targetLanguage"),
            "audioSourceKind": body.get("audioSourceKind"),
            "eventTokenReturned": bool(event_token),
            "clientSecretReturned": bool(body.get("clientSecret")),
        },
    )
    add_check(
        checks,
        "create_local_session_metadata",
        body.get("model") == EXPECTED_MODEL
        and body.get("targetLanguage") == EXPECTED_TARGET_LANGUAGE
        and body.get("audioSourceKind") == EXPECTED_AUDIO_SOURCE_KIND,
        {
            "model": body.get("model"),
            "targetLanguage": body.get("targetLanguage"),
            "audioSourceKind": body.get("audioSourceKind"),
        },
    )
    if not session_id or not event_token:
        return report_from_checks(args, base_url, session_id, checks, posted=[], sse_events=[])

    smoke_events_report = browser_normalized_smoke_events(args.web_realtime_contract_report)
    smoke_events = smoke_events_report["events"]
    posted = []
    for payload in smoke_events:
        response = post_json(
            base_url + f"/api/realtime/sessions/{session_id}/events",
            payload,
            headers={"X-Realtime-Event-Token": event_token},
            timeout=args.timeout_seconds,
        )
        posted.append({"type": payload["type"], "status": response["status"], "id": nested(response.get("json"), "id")})
    add_check(
        checks,
        "browser_normalized_event_payloads",
        smoke_events_report["status"] == "ok",
        {
            "status": smoke_events_report["status"],
            "source": smoke_events_report["source"],
            "eventTypes": [event.get("type") for event in smoke_events],
            "segmentIds": sorted({str(event.get("segmentId") or "") for event in smoke_events if event.get("segmentId")}),
            "warnings": smoke_events_report.get("warnings", []),
        },
    )
    add_check(checks, "post_smoke_events", all(item["status"] == 202 for item in posted), posted)

    sse_events = read_sse_events(
        base_url + "/api/realtime/sessions/current/events",
        timeout=args.timeout_seconds,
        min_events=5,
    )
    event_types = [str(event.get("type") or "") for event in sse_events]
    session_started = first_event_of_type(sse_events, "session_started")
    add_check(checks, "sse_receives_session_started", "session_started" in event_types, event_types)
    add_check(
        checks,
        "sse_session_metadata",
        isinstance(session_started, dict)
        and session_started.get("model") == EXPECTED_MODEL
        and session_started.get("targetLanguage") == EXPECTED_TARGET_LANGUAGE
        and session_started.get("audioSourceKind") == EXPECTED_AUDIO_SOURCE_KIND,
        {
            "model": nested(session_started, "model"),
            "targetLanguage": nested(session_started, "targetLanguage"),
            "audioSourceKind": nested(session_started, "audioSourceKind"),
        },
    )
    add_check(checks, "sse_receives_input_transcript", "input_transcript_delta" in event_types, event_types)
    add_check(checks, "sse_receives_caption_delta", "caption_delta" in event_types, event_types)
    add_check(checks, "sse_receives_caption_stable", "caption_stable" in event_types, event_types)
    add_check(checks, "sse_receives_stable_caption_final", "caption_final" in event_types, event_types)
    stable_segment_summary = stable_correction_segment_summary(sse_events)
    add_check(
        checks,
        "sse_stable_correction_matches_draft_segment",
        stable_segment_summary["matched"],
        stable_segment_summary,
    )
    add_check(checks, "no_secret_material", not contains_secret_material(json.dumps(sse_events)), None)
    session_validation = run_session_validation(args=args, session_id=session_id)
    if session_validation["status"] != "skipped":
        add_check(
            checks,
            "session_jsonl_validation",
            session_validation["status"] == "ok",
            session_validation,
        )

    return report_from_checks(
        args,
        base_url,
        session_id,
        checks,
        posted=posted,
        sse_events=sse_events,
        session_validation=session_validation,
    )


def run_session_validation(args: argparse.Namespace, session_id: str) -> dict[str, Any]:
    events_uri = session_events_jsonl_uri(args=args, session_id=session_id)
    if not events_uri:
        return {"status": "skipped", "reason": "session_events_jsonl_not_configured"}
    try:
        raw_text = read_validation_text(events_uri)
        validation_report = validate_realtime_session(
            events=parse_jsonl(raw_text),
            raw_text=raw_text,
            events_uri=events_uri,
            expected_model=EXPECTED_MODEL,
            require_model_event=True,
            require_caption_stable=True,
            require_stable_correction=True,
            min_caption_events=1,
            min_input_events=1,
        )
    except (Exception, SystemExit) as exc:
        validation_report = {
            "schemaVersion": 1,
            "status": "failed",
            "eventsJsonl": safe_uri(events_uri),
            "failedChecks": ["session_validation_read_or_parse"],
            "error": str(exc)[:300],
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
        }
    out_path = getattr(args, "session_validation_out", None)
    if out_path:
        out = resolve_repo_path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(validation_report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "status": validation_report.get("status"),
        "eventsJsonl": validation_report.get("eventsJsonl") or safe_uri(events_uri),
        "report": safe_display_path(resolve_repo_path(out_path)) if out_path else None,
        "failedChecks": validation_report.get("failedChecks", []),
        "counts": validation_report.get("counts"),
    }


def post_json(url: str, payload: dict[str, Any], *, headers: dict[str, str], timeout: float) -> dict[str, Any]:
    request_headers = {"Accept": "application/json", "Content-Type": "application/json", **headers}
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return parse_http_response(response.status, response.headers.get("Content-Type", ""), raw)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return parse_http_response(exc.code, exc.headers.get("Content-Type", ""), raw, error=str(exc))
    except URLError as exc:
        return {"status": 0, "contentType": "", "raw": "", "json": None, "error": str(exc.reason)[:200]}


def read_sse_events(url: str, *, timeout: float, min_events: int) -> list[dict[str, Any]]:
    request_url = url + "?" + urlencode({"cursor": "0"})
    request = Request(request_url, headers={"Accept": "text/event-stream"})
    events: list[dict[str, Any]] = []
    with urlopen(request, timeout=timeout) as response:
        while len(events) < min_events:
            line = response.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text.startswith("data:"):
                continue
            try:
                event = json.loads(text.removeprefix("data:").strip())
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def parse_http_response(status: int, content_type: str, raw: str, error: str | None = None) -> dict[str, Any]:
    data = None
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


def report_from_checks(
    args: argparse.Namespace,
    base_url: str,
    session_id: str,
    checks: list[dict[str, Any]],
    *,
    posted: list[dict[str, Any]],
    sse_events: list[dict[str, Any]],
    session_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failed = [check for check in checks if check["state"] == "fail"]
    return {
        "schemaVersion": 1,
        "status": "failed" if failed else "ok",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "baseUrl": base_url,
        "sunday": args.sunday,
        "sessionId": session_id or None,
        "models": {
            "realtimeDraft": EXPECTED_MODEL,
            "stableCorrection": "gpt-5.4-mini",
        },
        "postedEvents": posted,
        "sse": {
            "eventsRead": len(sse_events),
            "types": [event.get("type") for event in sse_events],
            "sessionStarted": public_session_started_summary(sse_events),
            "stableCaption": stable_caption_segment_summary(sse_events),
            "stableCorrection": stable_correction_segment_summary(sse_events),
        },
        "sessionValidation": session_validation or {"status": "skipped"},
        "eventPayloadSource": event_payload_source_summary(getattr(args, "web_realtime_contract_report", None)),
        "checks": checks,
        "failedChecks": [check["name"] for check in failed],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def admin_headers(args: argparse.Namespace) -> dict[str, str]:
    headers = {}
    if args.admin_token:
        headers["Authorization"] = f"Bearer {args.admin_token}"
    if args.internal_task_token:
        headers["X-Internal-Task-Token"] = args.internal_task_token
    return headers


def browser_normalized_smoke_events(web_realtime_contract_report: str | None) -> dict[str, Any]:
    if not web_realtime_contract_report:
        return {
            "status": "ok",
            "source": "inline_smoke_fixture",
            "events": default_smoke_events(),
            "warnings": ["web_realtime_contract_report_not_provided"],
        }
    report_path = resolve_repo_path(Path(web_realtime_contract_report))
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "failed",
            "source": safe_display_path(report_path),
            "events": default_smoke_events(),
            "warnings": [f"web_realtime_contract_report_unreadable:{str(exc)[:120]}"],
        }
    probe = report.get("normalizationProbe") if isinstance(report.get("normalizationProbe"), dict) else {}
    results = probe.get("results") if isinstance(probe.get("results"), list) else []
    actual_events = [item.get("actual") for item in results if isinstance(item, dict) and isinstance(item.get("actual"), dict)]
    caption_event = first_event(actual_events, {"caption_delta", "caption_final"})
    input_event = matching_input_event(actual_events, caption_event.get("segmentId") if caption_event else None)
    if probe.get("status") != "ok" or not caption_event or not input_event:
        return {
            "status": "failed",
            "source": safe_display_path(report_path),
            "events": default_smoke_events(),
            "warnings": ["normalization_probe_missing_required_input_or_caption_event"],
        }
    segment_id = str(caption_event.get("segmentId") or "smoke_1")
    english_context = str(input_event.get("en") or input_event.get("text") or input_event.get("delta") or "")
    stable_event = {
        "type": "caption_final",
        "source": "gpt-5.4-mini-stable-correction",
        "model": "gpt-5.4-mini",
        "zh": "神爱世人。",
        "text": "神爱世人。",
        "en": english_context,
        "final": True,
        "segmentId": segment_id,
    }
    return {
        "status": "ok",
        "source": safe_display_path(report_path),
        "events": [
            sanitize_smoke_event(input_event),
            sanitize_smoke_event(caption_event),
            stable_event,
        ],
        "warnings": [],
    }


def default_smoke_events() -> list[dict[str, Any]]:
    return [
        {
            "type": "input_transcript_delta",
            "source": "openai-realtime-webrtc",
            "en": "God loved the world",
            "text": "God loved the world",
            "delta": "God loved the world",
            "segmentId": "smoke_1",
        },
        {
            "type": "caption_delta",
            "source": "openai-realtime-webrtc",
            "zh": "神爱世人",
            "text": "神爱世人",
            "delta": "神爱世人",
            "segmentId": "smoke_1",
        },
        {
            "type": "caption_final",
            "source": "gpt-5.4-mini-stable-correction",
            "model": "gpt-5.4-mini",
            "zh": "神爱世人。",
            "text": "神爱世人。",
            "en": "God loved the world",
            "final": True,
            "segmentId": "smoke_1",
        },
    ]


def first_event(events: list[dict[str, Any]], event_types: set[str]) -> dict[str, Any] | None:
    for event in events:
        if event.get("type") in event_types:
            return event
    return None


def matching_input_event(events: list[dict[str, Any]], segment_id: Any) -> dict[str, Any] | None:
    for event in events:
        if str(event.get("type") or "").startswith("input_transcript") and event.get("segmentId") == segment_id:
            return event
    for event in events:
        if str(event.get("type") or "").startswith("input_transcript"):
            return event
    return None


def sanitize_smoke_event(event: dict[str, Any]) -> dict[str, Any]:
    allowed = {"type", "source", "en", "zh", "text", "delta", "final", "segmentId", "openaiEventType"}
    return {key: value for key, value in event.items() if key in allowed}


def event_payload_source_summary(path: str | None) -> dict[str, Any]:
    if path:
        return {
            "kind": "web_realtime_contract_normalization_probe",
            "report": safe_display_path(resolve_repo_path(Path(path))),
        }
    return {"kind": "inline_smoke_fixture"}


def add_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any) -> None:
    checks.append({"name": name, "state": "pass" if passed else "fail", "observed": observed})


def first_event_of_type(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    for event in events:
        if event.get("type") == event_type:
            return event
    return None


def public_session_started_summary(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    event = first_event_of_type(events, "session_started")
    if not event:
        return None
    return {
        "model": event.get("model"),
        "targetLanguage": event.get("targetLanguage"),
        "audioSourceKind": event.get("audioSourceKind"),
    }


def stable_correction_segment_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    draft_segments = {
        str(event.get("segmentId"))
        for event in events
        if event.get("type") in {"caption_delta", "caption_final"}
        and str(event.get("source") or "") in {"openai-realtime-webrtc", "openai_realtime_translation_ws"}
        and str(event.get("segmentId") or "").strip()
    }
    stable_segments = {
        str(event.get("segmentId"))
        for event in events
        if event.get("type") == "caption_final"
        and str(event.get("source") or "") == "gpt-5.4-mini-stable-correction"
        and event.get("model") == "gpt-5.4-mini"
        and str(event.get("segmentId") or "").strip()
    }
    matched_segments = draft_segments & stable_segments
    return {
        "matched": bool(matched_segments),
        "draftSegments": sorted(draft_segments)[:5],
        "stableCorrectionSegments": sorted(stable_segments)[:5],
        "matchedSegments": sorted(matched_segments)[:5],
    }


def stable_caption_segment_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    stable_events = [
        event
        for event in events
        if event.get("type") == "caption_stable"
        and str(event.get("source") or "") == "realtime-caption-stabilizer"
        and str(event.get("segmentId") or "").strip()
    ]
    return {
        "segments": sorted({str(event.get("segmentId")) for event in stable_events})[:5],
        "latencyP95Ms": latency_p95(stable_events),
        "windowed": all(isinstance(event.get("stabilizerWindow"), dict) for event in stable_events) if stable_events else False,
    }


def latency_p95(events: list[dict[str, Any]]) -> int | None:
    values = []
    for event in events:
        try:
            values.append(int(event.get("latencyMs")))
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    values.sort()
    index = min(len(values) - 1, max(0, round((len(values) - 1) * 0.95)))
    return values[index]


def contains_secret_material(text: str) -> bool:
    return any(marker in text for marker in ["eventToken", "Authorization", "Bearer ", "OPENAI_API_KEY", "/secrets/"])


def nested(data: Any, *keys: str) -> Any:
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def normalize_base_url(value: str) -> str:
    clean = value.strip().rstrip("/")
    if not clean.startswith(("http://", "https://")):
        raise SystemExit("--base-url must start with http:// or https://")
    return clean


def session_events_jsonl_uri(*, args: argparse.Namespace, session_id: str) -> str | None:
    explicit = getattr(args, "session_events_jsonl", None)
    if explicit:
        return str(explicit)
    prefix = str(getattr(args, "realtime_event_gcs_prefix", "") or "").strip().rstrip("/")
    if prefix:
        if not session_id:
            return None
        if not prefix.startswith("gs://"):
            raise SystemExit("--realtime-event-gcs-prefix must start with gs://")
        return f"{prefix}/{safe_path_component(args.sunday)}/{safe_path_component(session_id)}.jsonl"
    event_log_dir = getattr(args, "event_log_dir", None)
    if event_log_dir and session_id:
        return str(resolve_repo_path(event_log_dir) / f"{safe_path_component(session_id)}.jsonl")
    return None


def safe_path_component(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in str(value))[:80]


def safe_uri(uri: str) -> str:
    return uri if uri.startswith("gs://") else Path(uri).name


def safe_display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.name


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
