#!/usr/bin/env python3
"""Validate the server media worker realtime-caption contract."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import realtime_media_worker  # noqa: E402
from backend.realtime import realtime_translation_policy_error  # noqa: E402


FORBIDDEN_REPORT_NEEDLES = [
    "OPENAI_API_KEY",
    "projects/",
    "/secrets/",
]


def main() -> int:
    args = parse_args()
    report = validate_server_realtime_contract()
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def validate_server_realtime_contract() -> dict[str, Any]:
    checks = [
        check_output_delta_mapping(),
        check_nested_output_delta_object_mapping(),
        check_nested_output_mapping(),
        check_nested_input_mapping(),
        check_backend_realtime_session_policy(),
        check_media_worker_model_policy(),
    ]
    failed = [check for check in checks if check["state"] != "pass"]
    report = {
        "schemaVersion": 1,
        "status": "ok" if not failed else "failed",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "failedChecks": [check["name"] for check in failed],
        "models": {
            "realtimeDraft": "gpt-realtime-translate",
            "inputTranscriptFallback": "gpt-4o-transcribe",
        },
        "path": "youtube live/authorized audio -> server media worker -> gpt-realtime-translate -> backend session events -> public caption SSE",
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }
    enforce_report_sanitized(report)
    return report


def check_output_delta_mapping() -> dict[str, Any]:
    payload = realtime_media_worker.openai_event_to_realtime_payload(
        {
            "type": "session.output_transcript.delta",
            "delta": "Translated caption",
            "item_id": "seg_1",
        }
    )
    return check_payload(
        name="output_transcript_delta_mapping",
        description="session.output_transcript.delta becomes a Chinese caption_delta event.",
        payload=payload,
        expected={"type": "caption_delta", "zh": "Translated caption", "segmentId": "seg_1"},
    )


def check_nested_output_mapping() -> dict[str, Any]:
    payload = realtime_media_worker.openai_event_to_realtime_payload(
        {
            "type": "session.output_transcript.done",
            "response": {
                "id": "resp_1",
                "output": [{"content": [{"output_transcript": "Final translated caption"}]}],
            },
        }
    )
    return check_payload(
        name="nested_output_transcript_mapping",
        description="Nested output transcript payloads become final Chinese captions.",
        payload=payload,
        expected={
            "type": "caption_final",
            "zh": "Final translated caption",
            "segmentId": "resp_1",
            "final": True,
        },
    )


def check_nested_output_delta_object_mapping() -> dict[str, Any]:
    payload = realtime_media_worker.openai_event_to_realtime_payload(
        {
            "type": "session.output_transcript.delta",
            "output_transcript": {
                "delta": "Nested translated delta",
            },
            "response": {
                "id": "resp_delta_1",
            },
        }
    )
    return check_payload(
        name="nested_output_transcript_delta_object_mapping",
        description="Nested output_transcript.delta payloads become Chinese caption_delta events.",
        payload=payload,
        expected={
            "type": "caption_delta",
            "zh": "Nested translated delta",
            "delta": "Nested translated delta",
            "segmentId": "resp_delta_1",
        },
    )


def check_nested_input_mapping() -> dict[str, Any]:
    payload = realtime_media_worker.openai_event_to_realtime_payload(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item": {
                "id": "item_1",
                "content": [{"transcript": "Original English transcript"}],
            },
        }
    )
    return check_payload(
        name="nested_input_transcript_mapping",
        description="Nested input transcription payloads become final English transcript events.",
        payload=payload,
        expected={
            "type": "input_transcript_final",
            "en": "Original English transcript",
            "segmentId": "item_1",
            "final": True,
        },
    )


def check_backend_realtime_session_policy() -> dict[str, Any]:
    allowed = realtime_translation_policy_error("gpt-realtime-translate", "zh")
    wrong_model = realtime_translation_policy_error("gpt-realtime-2", "zh")
    wrong_language = realtime_translation_policy_error("gpt-realtime-translate", "es")
    observed = {
        "allowedRealtimeTranslateZh": allowed is None,
        "rejectsWrongModel": isinstance(wrong_model, dict)
        and wrong_model.get("error") == "unsupported_realtime_model",
        "rejectsWrongTargetLanguage": isinstance(wrong_language, dict)
        and wrong_language.get("error") == "unsupported_realtime_target_language",
    }
    return {
        "name": "backend_realtime_session_policy",
        "description": "Backend realtime session creation only permits gpt-realtime-translate targeting Chinese.",
        "state": "pass" if all(observed.values()) else "fail",
        "observed": observed,
    }


def check_media_worker_model_policy() -> dict[str, Any]:
    observed = {
        "allowsRealtimeTranslateZh": returns_ok(
            realtime_media_worker.validate_realtime_translation_model,
            "gpt-realtime-translate",
            "zh",
        ),
        "rejectsWrongRealtimeModel": raises_system_exit(
            realtime_media_worker.validate_realtime_translation_model,
            "gpt-realtime-2",
            "zh",
        ),
        "rejectsWrongTargetLanguage": raises_system_exit(
            realtime_media_worker.validate_realtime_translation_model,
            "gpt-realtime-translate",
            "es",
        ),
        "allowsGpt4oTranscribeFallback": returns_ok(
            realtime_media_worker.validate_input_transcript_fallback_model,
            "gpt-4o-transcribe",
        ),
        "rejectsWrongFallbackModel": raises_system_exit(
            realtime_media_worker.validate_input_transcript_fallback_model,
            "gpt-4o-mini-transcribe",
        ),
    }
    return {
        "name": "media_worker_model_policy",
        "description": "Server media worker CLI only permits the production realtime and input transcript fallback models.",
        "state": "pass" if all(observed.values()) else "fail",
        "observed": observed,
    }


def returns_ok(func: Any, *args: Any) -> bool:
    try:
        func(*args)
    except SystemExit:
        return False
    return True


def raises_system_exit(func: Any, *args: Any) -> bool:
    try:
        func(*args)
    except SystemExit:
        return True
    return False


def check_payload(
    *,
    name: str,
    description: str,
    payload: dict[str, Any] | None,
    expected: dict[str, Any],
) -> dict[str, Any]:
    mismatches = []
    for key, value in expected.items():
        observed = payload.get(key) if isinstance(payload, dict) else None
        if observed != value:
            mismatches.append({"field": key, "expected": value, "observed": observed})
    return {
        "name": name,
        "description": description,
        "state": "pass" if payload and not mismatches else "fail",
        "mismatches": mismatches,
    }


def enforce_report_sanitized(report: dict[str, Any]) -> None:
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    for needle in FORBIDDEN_REPORT_NEEDLES:
        if needle in serialized:
            raise SystemExit(f"Report contains forbidden material: {needle}")


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
