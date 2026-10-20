#!/usr/bin/env python3
"""Validate the delayed stable-correction event contract."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import stabilize_realtime_deltas_with_openai as stable  # noqa: E402


EXPECTED_MODEL = "gpt-5.4-mini"
EXPECTED_SOURCE = "gpt-5.4-mini-stable-correction"
FORBIDDEN_REPORT_NEEDLES = [
    "OPENAI_API_KEY",
    "projects/",
    "/secrets/",
    "sk-",
]


def main() -> int:
    args = parse_args()
    report = validate_stable_correction_contract()
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


def validate_stable_correction_contract() -> dict[str, Any]:
    sample_events = [
        {"id": 1, "type": "caption_delta", "segmentId": "seg_1", "delta": "耶稣是"},
        {
            "id": 2,
            "type": "caption_final",
            "segmentId": "seg_1",
            "text": "耶稣是中保。",
            "final": True,
        },
        {
            "id": 3,
            "type": "input_transcript_final",
            "segmentId": "seg_1",
            "text": "Jesus is our mediator.",
            "createdAt": "2026-06-25T00:00:00+00:00",
        },
    ]
    candidates = stable.stable_correction_candidates(sample_events, max_windows=None)
    output = stable.build_output(
        input_jsonl=Path("artifacts/realtime-events/rt_sample.jsonl"),
        model=EXPECTED_MODEL,
        candidates=candidates,
        corrections=[{"id": "seg_1", "zh": "耶稣是我们的中保。", "note": "术语修正。"}],
        api_key_secret="<OPENAI_API_KEY_SECRET_RESOURCE>",
    )
    correction_events = stable.stable_correction_events(output, model=EXPECTED_MODEL)
    checks = [
        check_candidates(candidates),
        check_output(output),
        check_events(correction_events),
        check_stable_model_policy(),
    ]
    failed = [check for check in checks if check["state"] != "pass"]
    report = {
        "schemaVersion": 1,
        "status": "ok" if not failed else "failed",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "failedChecks": [check["name"] for check in failed],
        "models": {
            "stableCorrection": EXPECTED_MODEL,
        },
        "path": "saved realtime English/Chinese deltas -> gpt-5.4-mini -> caption_final stable corrections -> backend session events",
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }
    enforce_report_sanitized(report)
    return report


def check_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    observed = candidates[0] if candidates else {}
    passed = (
        len(candidates) == 1
        and observed.get("id") == "seg_1"
        and observed.get("en") == "Jesus is our mediator."
        and observed.get("draftZh") == "耶稣是中保。"
    )
    return {
        "name": "candidate_uses_english_source_and_draft_zh",
        "description": "Stable correction candidates preserve English source transcript and realtime draft Chinese.",
        "state": "pass" if passed else "fail",
        "observed": {
            "count": len(candidates),
            "id": observed.get("id"),
            "hasEnglish": bool(observed.get("en")),
            "hasDraftChinese": bool(observed.get("draftZh")),
        },
    }


def check_output(output: dict[str, Any]) -> dict[str, Any]:
    passed = (
        output.get("status") == "ready"
        and output.get("model") == EXPECTED_MODEL
        and output.get("generatedFrom") == "realtime-delta-stable-correction"
        and output.get("apiKeyMaterialIncluded") is False
        and output.get("secretResourceNamesIncluded") is False
    )
    return {
        "name": "output_uses_gpt_5_4_mini_without_secret_material",
        "description": "Stable correction output is model-stamped and omits raw key or Secret Manager resource names.",
        "state": "pass" if passed else "fail",
        "observed": {
            "status": output.get("status"),
            "model": output.get("model"),
            "generatedFrom": output.get("generatedFrom"),
            "apiKeyMaterialIncluded": output.get("apiKeyMaterialIncluded"),
            "secretResourceNamesIncluded": output.get("secretResourceNamesIncluded"),
        },
    }


def check_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    observed = events[0] if events else {}
    passed = (
        len(events) == 1
        and observed.get("type") == "caption_final"
        and observed.get("source") == EXPECTED_SOURCE
        and observed.get("model") == EXPECTED_MODEL
        and observed.get("final") is True
        and bool(str(observed.get("segmentId") or "").strip())
        and bool(observed.get("zh"))
        and bool(observed.get("en"))
    )
    return {
        "name": "stable_corrections_are_caption_final_events",
        "description": "Stable corrections post as caption_final events with the gpt-5.4-mini stable-correction source.",
        "state": "pass" if passed else "fail",
        "observed": {
            "count": len(events),
            "type": observed.get("type"),
            "source": observed.get("source"),
            "model": observed.get("model"),
            "final": observed.get("final"),
            "segmentId": observed.get("segmentId"),
            "hasSegmentId": bool(str(observed.get("segmentId") or "").strip()),
            "hasChinese": bool(observed.get("zh")),
            "hasEnglish": bool(observed.get("en")),
        },
    }


def check_stable_model_policy() -> dict[str, Any]:
    observed = {
        "allowsRequiredMini": returns_ok(stable.validate_stable_correction_model, EXPECTED_MODEL),
        "rejectsRealtimeTranslate": raises_system_exit(
            stable.validate_stable_correction_model,
            "gpt-realtime-translate",
        ),
        "rejectsAlternativeSubstitute": raises_system_exit(
            stable.validate_stable_correction_model,
            "gpt-5.5",
        ),
    }
    return {
        "name": "stable_correction_model_policy",
        "description": "Stable correction CLI only permits gpt-5.4-mini and rejects realtime or substitute models.",
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


def enforce_report_sanitized(report: dict[str, Any]) -> None:
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    for needle in FORBIDDEN_REPORT_NEEDLES:
        if needle in serialized:
            raise SystemExit(f"Report contains forbidden material: {needle}")


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
