#!/usr/bin/env python3
"""Local smoke for realtime caption_stable persistence and reconnect reads."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.realtime import RealtimeEventArchive, RealtimeSessionStore  # noqa: E402
from scripts.validate_realtime_session import validate_realtime_session  # noqa: E402


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
    parser.add_argument("--sunday", default="2026-06-28")
    parser.add_argument("--event-log-dir", type=Path, default=Path("artifacts/realtime-stable-reconnect"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/realtime-stable-reconnect/report.json"))
    parser.add_argument(
        "--session-validation-out",
        type=Path,
        default=Path("artifacts/realtime-stable-reconnect/session-validation.json"),
    )
    parser.add_argument("--min-stable-p95-ms", type=int, default=3000)
    parser.add_argument("--max-stable-p95-ms", type=int, default=6000)
    args = parser.parse_args()
    if args.min_stable_p95_ms < 0 or args.max_stable_p95_ms < 0:
        raise SystemExit("--min-stable-p95-ms and --max-stable-p95-ms must be >= 0")
    return args


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    event_log_dir = resolve_repo_path(args.event_log_dir)
    archive = RealtimeEventArchive(event_log_dir)
    store = RealtimeSessionStore(archive)
    session = store.create(
        sunday=args.sunday,
        audio_source_kind="ipad_mic",
    )
    input_event = store.append_event(
        session.session_id,
        {
            "type": "input_transcript_delta",
            "text": "God loved the world.",
            "en": "God loved the world.",
            "segmentId": "seg_smoke_1",
            "source": "openai_realtime_translation_ws",
            "latencyMs": 1800,
        },
    )
    draft_event = store.append_event(
        session.session_id,
        {
            "type": "caption_delta",
            "text": "神爱世人。",
            "zh": "神爱世人。",
            "segmentId": "seg_smoke_1",
            "source": "openai_realtime_translation_ws",
            "latencyMs": 2200,
        },
    )
    reconnect_events = store.wait_for_events(session.session_id, after_id=draft_event["id"], timeout=0)
    stable_event = first_event(reconnect_events, "caption_stable")
    final_event = store.append_event(
        session.session_id,
        {
            "type": "caption_final",
            "text": "神爱世人。",
            "zh": "神爱世人。",
            "en": "God loved the world.",
            "final": True,
            "segmentId": "seg_smoke_1",
            "source": "gpt-5.4-mini-stable-correction",
            "model": "gpt-5.4-mini",
            "latencyMs": 4300,
        },
    )
    all_events = store.wait_for_events(session.session_id, after_id=0, timeout=0)
    archive_path = archive.path_for(session.session_id)
    raw_text = archive_path.read_text(encoding="utf-8")
    validation = validate_realtime_session(
        events=[json.loads(line) for line in raw_text.splitlines() if line.strip()],
        raw_text=raw_text,
        events_uri=str(archive_path),
        require_caption_stable=True,
        require_stable_correction=True,
        min_stable_p95_ms=args.min_stable_p95_ms,
        max_stable_p95_ms=args.max_stable_p95_ms,
    )
    if args.session_validation_out:
        validation_out = resolve_repo_path(args.session_validation_out)
        validation_out.parent.mkdir(parents=True, exist_ok=True)
        validation_out.write_text(json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    checks = [
        check("input_transcript_saved", input_event.get("type") == "input_transcript_delta", input_event_summary(input_event)),
        check("caption_delta_saved", draft_event.get("type") == "caption_delta", input_event_summary(draft_event)),
        check("reconnect_receives_caption_stable", bool(stable_event), input_event_summary(stable_event or {})),
        check(
            "caption_stable_has_window",
            bool(stable_event and stable_event.get("stabilizerWindow")),
            stable_event.get("stabilizerWindow") if stable_event else None,
        ),
        check("caption_final_saved", final_event.get("type") == "caption_final", input_event_summary(final_event)),
        check("session_validation", validation.get("status") == "ok", validation_summary(validation)),
    ]
    failed = [item for item in checks if item["state"] != "pass"]
    return {
        "schemaVersion": 1,
        "status": "ok" if not failed else "failed",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sessionId": session.session_id,
        "eventsJsonl": safe_display_path(archive_path),
        "sessionValidationReport": safe_display_path(resolve_repo_path(args.session_validation_out))
        if args.session_validation_out
        else None,
        "checks": checks,
        "failedChecks": [item["name"] for item in failed],
        "eventTypes": [event.get("type") for event in all_events],
        "stableLatency": validation.get("stableLatency"),
        "stableSegmentId": stable_event.get("segmentId") if stable_event else None,
        "finalSegmentId": final_event.get("segmentId"),
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def first_event(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    for event in events:
        if event.get("type") == event_type:
            return event
    return None


def input_event_summary(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event.get("id"),
        "type": event.get("type"),
        "segmentId": event.get("segmentId"),
        "latencyMs": event.get("latencyMs"),
    }


def validation_summary(validation: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": validation.get("status"),
        "failedChecks": validation.get("failedChecks"),
        "stableLatency": validation.get("stableLatency"),
    }


def check(name: str, passed: bool, observed: Any = None) -> dict[str, Any]:
    return {"name": name, "state": "pass" if passed else "fail", "observed": observed}


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def safe_display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


if __name__ == "__main__":
    raise SystemExit(main())
