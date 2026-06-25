#!/usr/bin/env python3
"""Audit whether the sermon caption production goal has enough evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


LOCAL_REQUIREMENTS = [
    {
        "id": "realtime_model_route",
        "description": "Realtime draft uses gpt-realtime-translate.",
        "files": ["backend/realtime.py", "backend/worker.py", "web/app.js"],
        "needles": ["gpt-realtime-translate"],
    },
    {
        "id": "realtime_event_archive",
        "description": "Realtime English/Chinese deltas are saved and streamable.",
        "files": ["backend/realtime.py", "backend/app.py", "scripts/validate_realtime_session.py"],
        "needles": ["RealtimeEventArchive", "input_transcript_delta", "caption_delta"],
    },
    {
        "id": "browser_webrtc_public_caption_view",
        "description": "iPad/iPhone mic uses browser WebRTC and the public caption view consumes backend SSE deltas.",
        "files": ["web/app.js", "backend/app.py"],
        "needles": [
            "navigator.mediaDevices.getUserMedia",
            "new RTCPeerConnection()",
            "gpt-realtime-translate",
            "openai-realtime-webrtc",
            "/api/realtime/sessions/current/events",
            "handleRealtimeCaptionEvent",
        ],
    },
    {
        "id": "server_media_worker_realtime_path",
        "description": "YouTube live or authorized audio uses the server media worker and saves English/Chinese realtime deltas.",
        "files": [
            "scripts/realtime_media_worker.py",
            "scripts/validate_server_realtime_contract.py",
            "backend/app.py",
        ],
        "needles": [
            "gpt-realtime-translate",
            "openai_event_to_realtime_payload",
            "extract_openai_transcript_text",
            "session.output_transcript.delta",
            "caption_delta",
            "input_transcript_final",
            "zh",
            "en",
            "/api/realtime/sessions/",
        ],
    },
    {
        "id": "realtime_stable_correction",
        "description": "Delayed stable corrections use gpt-5.5-mini and write caption_final events.",
        "files": [
            "scripts/stabilize_realtime_deltas_with_openai.py",
            "scripts/run_realtime_stabilizer_loop.py",
            "scripts/run_realtime_live_session.py",
        ],
        "needles": ["gpt-5.5-mini", "gpt-5.5-mini-stable-correction", "caption_final"],
    },
    {
        "id": "offline_captions_first",
        "description": "Offline route prefers captions/VTT before ASR fallback.",
        "files": ["scripts/offline_live_sermon_subtitles.py", "scripts/validate_offline_chain.py"],
        "needles": ["captions_first_then_asr", "use_caption_track", "use_asr_fallback"],
    },
    {
        "id": "offline_model_route",
        "description": "Offline ASR and translation use gpt-4o-transcribe plus gpt-5.5-mini, not realtime.",
        "files": ["backend/worker.py", "scripts/validate_offline_chain.py"],
        "needles": ["gpt-4o-transcribe", "gpt-5.5-mini", "gpt-realtime-translate"],
    },
    {
        "id": "offline_outputs",
        "description": "Offline chain exports translated VTT/SRT/playback JS/GCS manifest evidence.",
        "files": [
            "scripts/export_playback_captions.py",
            "scripts/promote_sunday_manifest.py",
            "scripts/validate_sunday_manifest.py",
            "scripts/run_sunday_evidence_bundle.py",
        ],
        "needles": ["sermon.zh.live-aligned.vtt", "sermon.zh.live-aligned.srt", "playback-simulation.generated.js"],
    },
]


EXTERNAL_REQUIREMENTS = [
    {
        "id": "external_realtime_live",
        "description": "A real authorized source or iPad mic reached gpt-realtime-translate and produced realtime deltas.",
    },
    {
        "id": "external_stable_correction",
        "description": "A real realtime session received at least one gpt-5.5-mini stable correction.",
    },
    {
        "id": "external_offline_caption_route",
        "description": "A real YouTube live archive with English captions completed the offline caption route.",
    },
    {
        "id": "external_offline_asr_route",
        "description": "A real no-caption archive completed the gpt-4o-transcribe ASR fallback route.",
    },
    {
        "id": "external_offline_not_realtime_chain",
        "description": "Offline post-live subtitles prove they did not use gpt-realtime-translate.",
    },
    {
        "id": "external_cloud_run_gcs_manifest",
        "description": "Cloud Run/GCS evidence proves readable public artifacts and promoted Sunday manifest.",
    },
    {
        "id": "external_cloud_run_realtime_config",
        "description": "Cloud Run config is safe for realtime session fanout and durable realtime event mirroring.",
    },
    {
        "id": "external_cloud_run_api_preflight",
        "description": "Cloud Run API preflight proves health, public Sunday reads, admin status, and realtime session creation.",
    },
]

EXTERNAL_MATRIX_ROWS = {
    "external_realtime_live": "realtime_live",
    "external_stable_correction": "stable_correction",
    "external_offline_caption_route": "offline_caption_route",
    "external_offline_asr_route": "offline_asr_route",
    "external_offline_not_realtime_chain": "offline_caption_route",
    "external_cloud_run_gcs_manifest": "cloud_run_gcs_manifest",
    "external_cloud_run_realtime_config": "cloud_run_realtime_config",
    "external_cloud_run_api_preflight": "cloud_run_api_preflight",
}


def main() -> int:
    args = parse_args()
    report = audit_goal_readiness(args)
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "complete" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--production-readiness-report",
        action="append",
        default=[],
        help="validate_production_readiness.py report.json. Repeat for caption-route and ASR-route runs.",
    )
    parser.add_argument(
        "--cloud-run-config-report",
        help="validate_cloud_run_realtime_config.py report.json proving realtime-safe Cloud Run settings.",
    )
    parser.add_argument(
        "--cloud-run-api-preflight-report",
        help="run_cloud_run_realtime_preflight.py report.json proving deployed API readiness.",
    )
    parser.add_argument(
        "--evidence-matrix-report",
        help="collect_production_evidence_matrix.py report.json with row-level production evidence.",
    )
    parser.add_argument("--out", type=Path, help="Optional audit report path.")
    return parser.parse_args()


def audit_goal_readiness(args: argparse.Namespace) -> dict[str, Any]:
    local_checks = [local_requirement_check(item) for item in LOCAL_REQUIREMENTS]
    missing_report_paths: list[str] = []
    readiness_reports = [
        report
        for report in (
            read_optional_json_report(path, missing_report_paths)
            for path in args.production_readiness_report
        )
        if report is not None
    ]
    cloud_run_config_report = read_optional_json_report(args.cloud_run_config_report, missing_report_paths)
    cloud_run_api_preflight_report = (
        read_optional_json_report(args.cloud_run_api_preflight_report, missing_report_paths)
    )
    evidence_matrix_report = read_optional_json_report(args.evidence_matrix_report, missing_report_paths)
    external_checks = external_requirement_checks(
        readiness_reports,
        cloud_run_config_report,
        cloud_run_api_preflight_report,
        evidence_matrix_report,
    )
    failed = [check for check in local_checks + external_checks if check["state"] != "pass"]
    return {
        "schemaVersion": 1,
        "status": "complete" if not failed else "incomplete",
        "summary": audit_summary(local_checks, external_checks),
        "failedChecks": [check["id"] for check in failed],
        "nextActions": next_actions_for_failed_checks(failed),
        "localImplementation": local_checks,
        "externalEvidence": external_checks,
        "productionReadinessReports": len(readiness_reports),
        "productionEvidenceMatrix": matrix_summary(evidence_matrix_report, args.evidence_matrix_report),
        "missingReportPaths": missing_report_paths,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def local_requirement_check(requirement: dict[str, Any]) -> dict[str, Any]:
    missing_files = []
    haystack = ""
    for rel in requirement["files"]:
        path = REPO_ROOT / rel
        if not path.is_file():
            missing_files.append(rel)
            continue
        haystack += path.read_text(encoding="utf-8", errors="replace")
        haystack += "\n"
    missing_needles = [needle for needle in requirement["needles"] if needle not in haystack]
    passed = not missing_files and not missing_needles
    return {
        "id": requirement["id"],
        "description": requirement["description"],
        "state": "pass" if passed else "fail",
        "missingFiles": missing_files,
        "missingEvidenceStrings": missing_needles,
    }


def external_requirement_checks(
    reports: list[dict[str, Any]],
    cloud_run_config_report: dict[str, Any] | None,
    cloud_run_api_preflight_report: dict[str, Any] | None,
    evidence_matrix_report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    matrix_states = matrix_row_states(evidence_matrix_report)
    matrix_rows = matrix_row_details(evidence_matrix_report)
    any_ok = [report for report in reports if report.get("status") == "ok"]
    has_realtime = matrix_states.get("realtime_live") == "pass" or any(
        realtime_report_has_caption_and_input(report) for report in any_ok
    )
    has_stable = matrix_states.get("stable_correction") == "pass" or any(
        (nested(report, "realtime", "counts", "stableCorrectionEvents") or 0) > 0 for report in any_ok
    )
    has_caption_route = matrix_states.get("offline_caption_route") == "pass" or any(
        nested(report, "offline", "offlineRoute", "decision") == "use_caption_track" for report in any_ok
    )
    has_asr_route = matrix_states.get("offline_asr_route") == "pass" or any(
        nested(report, "offline", "offlineRoute", "decision") == "use_asr_fallback" for report in any_ok
    )
    has_offline_not_realtime_chain = matrix_offline_not_realtime_chain_passed(matrix_rows) or any(
        nested(report, "offline", "checks", "not_realtime_chain") == "pass"
        or nested(report, "offline", "notRealtimeChain") == "pass"
        for report in any_ok
    )
    has_cloud_run_manifest = matrix_states.get("cloud_run_gcs_manifest") == "pass" or any(
        nested(report, "sundayManifest", "status") == "ok" for report in any_ok
    )
    has_cloud_run_realtime_config = matrix_states.get("cloud_run_realtime_config") == "pass" or bool(
        cloud_run_config_report and cloud_run_config_report.get("status") == "ok"
    )
    has_cloud_run_api_preflight = bool(
        matrix_states.get("cloud_run_api_preflight") == "pass"
        or (
            cloud_run_api_preflight_report
            and cloud_run_api_preflight_report.get("status") == "ok"
            and not has_warning(cloud_run_api_preflight_report, "realtime_local_session_create")
            and report_check_passed(cloud_run_api_preflight_report, "realtime_local_session_create")
            and report_check_passed(cloud_run_api_preflight_report, "realtime_local_session_metadata")
        )
    )
    observed = {
        "okReports": len(any_ok),
        "matrixRows": matrix_states,
        "realtime": has_realtime,
        "stableCorrection": has_stable,
        "offlineCaptionRoute": has_caption_route,
        "offlineAsrRoute": has_asr_route,
        "offlineNotRealtimeChain": has_offline_not_realtime_chain,
        "cloudRunManifest": has_cloud_run_manifest,
        "cloudRunRealtimeConfig": has_cloud_run_realtime_config,
        "cloudRunApiPreflight": has_cloud_run_api_preflight,
    }
    return [
        external_check("external_realtime_live", has_realtime, observed, matrix_rows),
        external_check("external_stable_correction", has_stable, observed, matrix_rows),
        external_check("external_offline_caption_route", has_caption_route, observed, matrix_rows),
        external_check("external_offline_asr_route", has_asr_route, observed, matrix_rows),
        external_check("external_offline_not_realtime_chain", has_offline_not_realtime_chain, observed, matrix_rows),
        external_check("external_cloud_run_gcs_manifest", has_cloud_run_manifest, observed, matrix_rows),
        external_check("external_cloud_run_realtime_config", has_cloud_run_realtime_config, observed, matrix_rows),
        external_check("external_cloud_run_api_preflight", has_cloud_run_api_preflight, observed, matrix_rows),
    ]


def realtime_report_has_caption_and_input(report: dict[str, Any]) -> bool:
    counts = nested(report, "realtime", "counts")
    if not isinstance(counts, dict):
        return False
    caption_events = counts.get("realtimeCaptionEvents") or 0
    input_events = (
        counts.get("realtimeInputTranscriptEvents")
        or counts.get("inputTranscriptEvents")
        or 0
    )
    return caption_events > 0 and input_events > 0


def report_check_passed(report: dict[str, Any], name: str) -> bool:
    for check in report.get("checks") or []:
        if isinstance(check, dict) and check.get("name") == name:
            return check.get("state") == "pass"
    return False


def matrix_offline_not_realtime_chain_passed(matrix_rows: dict[str, dict[str, Any]]) -> bool:
    row = matrix_rows.get("offline_caption_route") or {}
    observed = row.get("observed") if isinstance(row, dict) else None
    if not isinstance(observed, dict):
        return False
    if observed.get("notRealtimeChain") == "pass":
        return True
    checks = observed.get("checks")
    return isinstance(checks, dict) and checks.get("not_realtime_chain") == "pass"


def external_check(
    check_id: str,
    passed: bool,
    observed: dict[str, Any],
    matrix_rows: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    description = next(item["description"] for item in EXTERNAL_REQUIREMENTS if item["id"] == check_id)
    row_id = EXTERNAL_MATRIX_ROWS.get(check_id)
    row = (matrix_rows or {}).get(row_id or "") if row_id else None
    row_state = (row or {}).get("state")
    check = {
        "id": check_id,
        "description": description,
        "state": external_evidence_state(passed, row_state),
        "observed": observed,
    }
    if row_id:
        check["productionEvidenceRow"] = {
            "id": row_id,
            "state": (row or {}).get("state"),
            "nextAction": (row or {}).get("nextAction"),
            "artifact": (row or {}).get("artifact"),
        }
    return check


def external_evidence_state(passed: bool, row_state: Any) -> str:
    if passed:
        return "pass"
    if row_state == "warn":
        return "partial_external_evidence"
    return "missing_external_evidence"


def audit_summary(local_checks: list[dict[str, Any]], external_checks: list[dict[str, Any]]) -> dict[str, Any]:
    local_failed = sum(1 for check in local_checks if check.get("state") != "pass")
    external_missing = sum(1 for check in external_checks if check.get("state") != "pass")
    return {
        "localPassed": len(local_checks) - local_failed,
        "localFailed": local_failed,
        "externalPassed": len(external_checks) - external_missing,
        "externalMissing": external_missing,
        "totalPassed": len(local_checks) + len(external_checks) - local_failed - external_missing,
        "totalFailed": local_failed + external_missing,
        "total": len(local_checks) + len(external_checks),
    }


def next_actions_for_failed_checks(failed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions = []
    for check in failed:
        row = check.get("productionEvidenceRow") or {}
        action: dict[str, Any] = {
            "id": check.get("id"),
            "state": check.get("state"),
            "description": check.get("description"),
        }
        if row.get("id"):
            action["sourceRow"] = row.get("id")
            action["sourceRowState"] = row.get("state")
        if row.get("nextAction"):
            action["nextAction"] = row.get("nextAction")
        elif check.get("missingFiles") or check.get("missingEvidenceStrings"):
            action["nextAction"] = "Restore the missing local implementation evidence."
        else:
            action["nextAction"] = "Collect stronger production evidence for this requirement."
        actions.append(action)
    return actions


def nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def has_warning(report: dict[str, Any], name: str) -> bool:
    warnings = report.get("warnings") or []
    return name in warnings


def matrix_row_states(report: dict[str, Any] | None) -> dict[str, str]:
    if not report:
        return {}
    rows = report.get("matrix") or []
    if not isinstance(rows, list):
        return {}
    states: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("id") or "")
        state = str(row.get("state") or "")
        if row_id and state:
            states[row_id] = state
    return states


def matrix_row_details(report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not report:
        return {}
    rows = report.get("matrix") or []
    if not isinstance(rows, list):
        return {}
    details: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("id") or "")
        if row_id:
            details[row_id] = row
    return details


def matrix_summary(report: dict[str, Any] | None, path: str | None) -> dict[str, Any] | None:
    if not report:
        return None
    return {
        "path": path,
        "status": report.get("status"),
        "summary": report.get("summary"),
    }


def read_json_report(path_value: str | None) -> dict[str, Any]:
    if not path_value:
        raise SystemExit("Report path is required")
    path = resolve_repo_path(Path(path_value))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"Report must be a JSON object: {path_value}")
    return data


def read_optional_json_report(path_value: str | None, missing_report_paths: list[str]) -> dict[str, Any] | None:
    if not path_value:
        return None
    path = resolve_repo_path(Path(path_value))
    if not path.is_file():
        missing_report_paths.append(str(path_value))
        return None
    return read_json_report(path_value)


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
