#!/usr/bin/env python3
"""Build stable Chinese corrections from saved realtime delta JSONL events."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
SECRET_RESOURCE_RE = re.compile(
    r"^projects/(?P<project>[^/\s]+)/secrets/(?P<secret>[^/\s]+)(?:/versions/(?P<version>[^/\s]+))?$"
)
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.5-mini"
FORBIDDEN_STABLE_MODEL = "gpt-realtime-translate"


def main() -> int:
    args = parse_args()
    validate_secret_resource_name(args.api_key_secret)
    events = read_jsonl(args.input_jsonl)
    candidates = stable_correction_candidates(events, max_windows=args.max_windows)
    if not candidates:
        raise SystemExit("No realtime English transcript events were available for stable correction.")

    api_key = access_secret(args.api_key_secret)
    corrections: list[dict[str, Any]] = []
    for batch in batched(candidates, args.batch_size):
        corrections.extend(stabilize_batch(batch, api_key=api_key, model=args.model))

    output = build_output(
        input_jsonl=args.input_jsonl,
        model=args.model,
        candidates=candidates,
        corrections=corrections,
        api_key_secret=args.api_key_secret,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = args.out_dir / "openai-stable-corrections-output.jsonl"
    write_jsonl(jsonl_path, corrections)
    report_path = args.out_dir / "openai-stable-corrections-report.json"
    report = {
        "schemaVersion": 1,
        "status": "ok",
        "model": args.model,
        "input": safe_display_path(args.input_jsonl),
        "out": safe_display_path(args.out),
        "modelOutputJsonl": safe_display_path(jsonl_path),
        "candidateWindows": len(candidates),
        "correctedWindows": len(corrections),
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "serverSideSecretConfigured": bool(args.api_key_secret),
        "backendPostConfigured": bool(args.post_backend_url),
        "postedStableCorrections": 0,
    }
    if args.post_backend_url:
        posted = post_stable_corrections(
            output=output,
            backend_url=args.post_backend_url,
            session_id=args.post_session_id,
            event_token=args.post_event_token,
            admin_token=args.post_admin_token,
            internal_task_token=args.post_internal_task_token,
            model=args.model,
        )
        report["postedStableCorrections"] = posted
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({**report, "report": safe_display_path(report_path)}, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Use gpt-5.5-mini to stabilize realtime English/Chinese delta JSONL events."
    )
    parser.add_argument("--input-jsonl", type=Path, required=True, help="Realtime event JSONL file.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts/realtime-stable-corrections/stable-corrections.json"),
        help="Stable correction JSON output.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("artifacts/realtime-stable-corrections"),
        help="Directory for report and raw model JSONL output.",
    )
    parser.add_argument(
        "--api-key-secret",
        required=True,
        help="Google Secret Manager resource name for the OpenAI key.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument("--max-windows", type=int, default=40)
    parser.add_argument("--post-backend-url", help="Optional backend base URL for posting stable corrections.")
    parser.add_argument("--post-session-id", help="Realtime session id to receive stable correction events.")
    parser.add_argument("--post-event-token", help="Realtime event token for posting stable correction events.")
    parser.add_argument("--post-admin-token", help="Operator admin token for posting stable corrections only.")
    parser.add_argument("--post-internal-task-token", help="Internal task token for posting stable corrections only.")
    args = parser.parse_args()
    args.input_jsonl = resolve_repo_path(args.input_jsonl)
    args.out = resolve_repo_path(args.out)
    args.out_dir = resolve_repo_path(args.out_dir)
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")
    if args.max_windows == 0:
        args.max_windows = None
    validate_stable_correction_model(args.model)
    post_auth = args.post_event_token or args.post_admin_token or args.post_internal_task_token
    if any([args.post_backend_url, args.post_session_id, post_auth]) and not all(
        [args.post_backend_url, args.post_session_id, post_auth]
    ):
        raise SystemExit(
            "--post-backend-url, --post-session-id, and one post auth token "
            "(--post-event-token, --post-admin-token, or --post-internal-task-token) must be provided together."
        )
    return args


def validate_stable_correction_model(model: str) -> None:
    if model == FORBIDDEN_STABLE_MODEL:
        raise SystemExit(
            "Delayed stable corrections must not use gpt-realtime-translate; "
            "use gpt-5.5-mini."
        )
    if model != DEFAULT_MODEL:
        raise SystemExit("Delayed stable corrections must use gpt-5.5-mini.")


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def stable_correction_candidates(
    events: list[dict[str, Any]],
    max_windows: int | None,
) -> list[dict[str, Any]]:
    draft_zh_by_segment: dict[str, str] = {}
    input_delta_buffer: list[str] = []
    candidates: list[dict[str, Any]] = []

    for event in events:
        event_type = str(event.get("type") or "")
        segment_id = str(event.get("segmentId") or "").strip()
        text = event_text(event)
        if event_type in {"caption_delta", "caption_final"} and segment_id:
            draft_zh_by_segment[segment_id] = append_or_replace(
                draft_zh_by_segment.get(segment_id, ""),
                text,
                final=event_type == "caption_final" or bool(event.get("final")),
            )
            continue

        if event_type == "input_transcript_delta":
            if text:
                input_delta_buffer.append(text)
            continue

        if event_type == "input_transcript_final":
            source = text or " ".join(input_delta_buffer).strip()
            input_delta_buffer = []
            if not source:
                continue
            stable_id = segment_id or f"rt_stable_{len(candidates) + 1:04d}"
            candidates.append(
                {
                    "id": stable_id,
                    "en": source,
                    "draftZh": draft_zh_by_segment.get(stable_id, ""),
                    "sourceEventId": event.get("id"),
                    "createdAt": event.get("createdAt"),
                }
            )

    if input_delta_buffer:
        source = " ".join(input_delta_buffer).strip()
        if source:
            candidates.append(
                {
                    "id": f"rt_stable_{len(candidates) + 1:04d}",
                    "en": source,
                    "draftZh": "",
                    "sourceEventId": None,
                    "createdAt": None,
                }
            )
    return candidates[:max_windows] if max_windows else candidates


def event_text(event: dict[str, Any]) -> str:
    return str(event.get("text") or event.get("en") or event.get("delta") or event.get("zh") or "").strip()


def append_or_replace(existing: str, incoming: str, final: bool) -> str:
    if not incoming:
        return existing
    if final:
        return incoming
    return f"{existing}{incoming}" if existing else incoming


def validate_secret_resource_name(value: str) -> None:
    if not SECRET_RESOURCE_RE.fullmatch(value):
        raise SystemExit(
            "--api-key-secret must be a Google Secret Manager resource name like "
            "projects/PROJECT_ID/secrets/openai-api-key/versions/latest. Do not pass raw API key material."
        )


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


def batched(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def stabilize_batch(batch: list[dict[str, Any]], api_key: str, model: str) -> list[dict[str, Any]]:
    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "You are stabilizing realtime draft Simplified Chinese sermon captions. "
                            "Use the English transcript as source of truth. Improve readability, faithfulness, "
                            "Bible/person/theology terms, and subtitle length. Do not add commentary. Return strict JSON only."
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "For each window, return exactly this JSON shape: "
                            "{\"segments\":[{\"id\":\"...\",\"zh\":\"...\",\"note\":\"...\"}]}.\n"
                            "Keep ids unchanged. Use the draft Chinese only as a hint; correct it from English.\n"
                            f"Windows:\n{json.dumps(batch, ensure_ascii=False)}"
                        ),
                    }
                ],
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
        timeout=90,
    )
    if response.status_code >= 400:
        raise SystemExit(f"OpenAI request failed with HTTP {response.status_code}: {safe_error_message(response)}")
    data = response.json()
    content = extract_response_text(data)
    parsed = parse_json_object(content)
    segments = parsed.get("segments")
    if not isinstance(segments, list):
        raise SystemExit("OpenAI stable correction response did not include a segments array.")
    return [normalize_correction(item) for item in segments]


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
    raise SystemExit("OpenAI stable correction response did not include output text.")


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


def normalize_correction(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise SystemExit("OpenAI correction item was not an object.")
    segment_id = str(item.get("id") or item.get("segment_id") or item.get("segmentId") or "").strip()
    zh = str(item.get("zh") or item.get("translation") or item.get("chinese") or item.get("text") or "").strip()
    if not segment_id or not zh:
        raise SystemExit("OpenAI correction item missing id or Chinese text.")
    return {
        "id": segment_id,
        "zh": zh,
        "note": str(item.get("note") or "Stable correction from realtime English transcript.").strip(),
    }


def build_output(
    input_jsonl: Path,
    model: str,
    candidates: list[dict[str, Any]],
    corrections: list[dict[str, Any]],
    api_key_secret: str,
) -> dict[str, Any]:
    by_id = {item["id"]: item for item in corrections}
    segments = []
    for candidate in candidates:
        correction = by_id.get(candidate["id"])
        segments.append(
            {
                "id": candidate["id"],
                "en": candidate["en"],
                "draftZh": candidate.get("draftZh") or "",
                "stableZh": correction.get("zh") if correction else "",
                "note": correction.get("note") if correction else "No stable correction returned.",
                "sourceEventId": candidate.get("sourceEventId"),
                "createdAt": candidate.get("createdAt"),
            }
        )
    return {
        "schemaVersion": 1,
        "status": "ready" if corrections else "empty",
        "generatedFrom": "realtime-delta-stable-correction",
        "model": model,
        "input": safe_display_path(input_jsonl),
        "segments": segments,
        "totalWindows": len(candidates),
        "correctedWindows": len(corrections),
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "serverSideSecretConfigured": bool(api_key_secret),
    }


def stable_correction_events(output: dict[str, Any], model: str) -> list[dict[str, Any]]:
    events = []
    for segment in output.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        segment_id = str(segment.get("id") or "").strip()
        stable_zh = str(segment.get("stableZh") or "").strip()
        if not segment_id or not stable_zh:
            continue
        events.append(
            {
                "type": "caption_final",
                "text": stable_zh,
                "zh": stable_zh,
                "en": str(segment.get("en") or "").strip(),
                "final": True,
                "segmentId": segment_id,
                "source": "gpt-5.5-mini-stable-correction",
                "model": model,
            }
        )
    return events


def post_stable_corrections(
    *,
    output: dict[str, Any],
    backend_url: str,
    session_id: str,
    model: str,
    event_token: str | None = None,
    admin_token: str | None = None,
    internal_task_token: str | None = None,
) -> int:
    events = stable_correction_events(output, model)
    if not events:
        return 0
    base_url = normalize_backend_url(backend_url)
    endpoint = f"{base_url}/api/realtime/sessions/{quote(session_id)}/events"
    posted = 0
    for event in events:
        response = requests.post(
            endpoint,
            headers=stable_correction_post_headers(
                event_token=event_token,
                admin_token=admin_token,
                internal_task_token=internal_task_token,
            ),
            json=event,
            timeout=20,
        )
        if response.status_code >= 400:
            raise SystemExit(
                f"Posting stable correction failed with HTTP {response.status_code}: {safe_error_message(response)}"
            )
        posted += 1
    return posted


def stable_correction_post_headers(
    *,
    event_token: str | None = None,
    admin_token: str | None = None,
    internal_task_token: str | None = None,
) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if event_token:
        headers["X-Realtime-Event-Token"] = event_token
    elif admin_token:
        headers["Authorization"] = f"Bearer {admin_token}"
    elif internal_task_token:
        headers["X-Internal-Task-Token"] = internal_task_token
    else:
        raise SystemExit("Posting stable corrections requires an event, admin, or internal task token.")
    return headers


def normalize_backend_url(value: str) -> str:
    clean = str(value or "").strip().rstrip("/")
    if not clean.startswith(("http://", "https://")):
        raise SystemExit("--post-backend-url must start with http:// or https://")
    return clean


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def safe_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:400]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or "unknown error")
    return str(data)[:400]


def safe_display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.name


if __name__ == "__main__":
    raise SystemExit(main())
