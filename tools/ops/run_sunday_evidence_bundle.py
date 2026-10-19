#!/usr/bin/env python3
"""Build and run the Sunday production-readiness evidence bundle command."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE_PRODUCTION = REPO_ROOT / "scripts" / "validate_production_readiness.py"
COLLECT_MATRIX = REPO_ROOT / "scripts" / "collect_production_evidence_matrix.py"
AUDIT_GOAL = REPO_ROOT / "scripts" / "audit_production_goal_readiness.py"
DEFAULT_WORK_ROOT = Path("/tmp/sermon-worker")
DEFAULT_REALTIME_EVENT_DIR = Path("/tmp/sermon-realtime-events")


def main() -> int:
    args = parse_args()
    commands = build_bundle_commands(args)
    command = commands["productionReadiness"]
    report = {
        "schemaVersion": 1,
        "status": "planned" if args.dry_run else "running",
        "sunday": args.sunday,
        "sessionId": args.session_id,
        "realtimeSessionId": args.realtime_session_id,
        "realtimeEventsJsonl": command_value(command, "--realtime-events-jsonl"),
        "artifactLocation": args.artifact_location,
        "command": command,
        "commands": commands,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }
    if args.bundle_report_out:
        report["bundleReport"] = str(resolve_repo_path(args.bundle_report_out))
    if args.dry_run:
        write_report(args.bundle_report_out, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    steps = run_bundle_commands(commands)
    report["steps"] = steps
    report["status"] = "ok" if all(step["returnCode"] == 0 for step in steps.values()) else "failed"
    report["returnCode"] = max((step["returnCode"] for step in steps.values()), default=0)
    write_report(args.bundle_report_out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return int(report["returnCode"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sunday", required=True, help="Sunday date, YYYY-MM-DD.")
    parser.add_argument("--session-id", required=True, help="Worker generation session id.")
    parser.add_argument(
        "--artifact-location",
        choices=["local", "gcs"],
        default="local",
        help="Use local worker files or GCS object paths as evidence inputs.",
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        default=DEFAULT_WORK_ROOT,
        help="Local worker root, used when --artifact-location=local.",
    )
    parser.add_argument(
        "--artifact-bucket",
        default=os.getenv("SERMON_ARTIFACT_BUCKET"),
        help="GCS bucket, required when --artifact-location=gcs.",
    )
    parser.add_argument(
        "--artifact-prefix",
        default=os.getenv("SERMON_ARTIFACT_PREFIX", "sundays"),
        help="GCS artifact prefix, usually sundays.",
    )
    parser.add_argument("--realtime-session-id", help="Realtime session id to validate.")
    parser.add_argument("--realtime-events-jsonl", help="Exact realtime JSONL path or gs:// URI.")
    parser.add_argument(
        "--realtime-smoke-report",
        help=(
            "Optional realtime smoke/live-session report.json; sessionId is used when "
            "--realtime-session-id is omitted."
        ),
    )
    parser.add_argument(
        "--realtime-location",
        choices=["local", "gcs"],
        default="local",
        help="Use local realtime JSONL or GCS realtime-event mirror.",
    )
    parser.add_argument(
        "--realtime-event-dir",
        type=Path,
        default=DEFAULT_REALTIME_EVENT_DIR,
        help="Local realtime event directory.",
    )
    parser.add_argument(
        "--realtime-event-gcs-prefix",
        default=os.getenv("REALTIME_EVENT_GCS_PREFIX"),
        help="GCS prefix for realtime events, e.g. gs://bucket/realtime-events.",
    )
    parser.add_argument("--allow-missing-realtime", action="store_true")
    parser.add_argument("--allow-missing-stable-correction", action="store_true")
    parser.add_argument("--require-readable-sunday-artifacts", action="store_true")
    parser.add_argument(
        "--out",
        type=Path,
        help="Optional validation report path passed to validate_production_readiness.py.",
    )
    parser.add_argument(
        "--evidence-matrix-out",
        type=Path,
        help="Optional collect_production_evidence_matrix.py output path.",
    )
    parser.add_argument(
        "--goal-audit-out",
        type=Path,
        help="Optional audit_production_goal_readiness.py output path.",
    )
    parser.add_argument("--bundle-report-out", type=Path, help="Optional JSON report path for this bundle runner.")
    parser.add_argument("--cloud-run-config-report")
    parser.add_argument("--cloud-run-api-preflight-report")
    parser.add_argument("--realtime-audio-source-preflight-report")
    parser.add_argument("--server-realtime-contract-report")
    parser.add_argument("--web-realtime-contract-report")
    parser.add_argument("--public-caption-view-runtime-report")
    parser.add_argument("--realtime-public-sse-smoke-report")
    parser.add_argument("--realtime-openai-smoke-report")
    parser.add_argument("--realtime-session-validation-report")
    parser.add_argument("--stable-correction-contract-report")
    parser.add_argument("--offline-archive-preflight-report")
    parser.add_argument("--offline-chain-validation-report")
    parser.add_argument("--offline-asr-chain-validation-report")
    parser.add_argument("--offline-asr-smoke-report")
    parser.add_argument("--offline-translation-report")
    parser.add_argument("--sunday-manifest-validation-report")
    parser.add_argument("--openai-model-access-preflight-report")
    parser.add_argument("--openai-alternative-model-access-preflight-report", action="append", default=[])
    parser.add_argument("--cloud-run-update-plan")
    parser.add_argument("--cloud-run-update-execution")
    parser.add_argument("--dry-run", action="store_true", help="Print the validation command without running it.")
    args = parser.parse_args()
    if args.realtime_smoke_report:
        evidence = realtime_evidence_from_report(args.realtime_smoke_report)
        if not args.realtime_session_id:
            args.realtime_session_id = evidence.get("sessionId")
        if not args.realtime_events_jsonl:
            args.realtime_events_jsonl = evidence.get("realtimeEventsJsonl")
    if (args.evidence_matrix_out or args.goal_audit_out) and not args.out:
        args.out = default_production_readiness_report(args)
    validate_args(args)
    return args


def validate_args(args: argparse.Namespace) -> None:
    if args.artifact_location == "gcs" and not args.artifact_bucket:
        raise SystemExit("--artifact-bucket or SERMON_ARTIFACT_BUCKET is required for --artifact-location=gcs")
    if args.realtime_location == "gcs" and args.realtime_session_id and not args.realtime_event_gcs_prefix and not args.realtime_events_jsonl:
        raise SystemExit("--realtime-event-gcs-prefix or REALTIME_EVENT_GCS_PREFIX is required for realtime GCS evidence")
    if not args.realtime_session_id and not args.realtime_events_jsonl and not args.allow_missing_realtime:
        raise SystemExit("--realtime-session-id or --realtime-events-jsonl is required unless --allow-missing-realtime is set")


def build_validation_command(args: argparse.Namespace) -> list[str]:
    paths = evidence_paths(args)
    command = [
        sys.executable,
        str(VALIDATE_PRODUCTION),
        "--offline-report",
        paths["offline_report"],
        "--playback-js",
        paths["playback_js"],
        "--zh-vtt",
        paths["zh_vtt"],
        "--zh-srt",
        paths["zh_srt"],
        "--run-manifest",
        paths["run_manifest"],
        "--sunday-manifest",
        paths["sunday_manifest"],
        "--sunday",
        args.sunday,
    ]
    if args.require_readable_sunday_artifacts:
        command.append("--require-readable-sunday-artifacts")
    if args.realtime_events_jsonl:
        command.extend(["--realtime-events-jsonl", args.realtime_events_jsonl])
    elif args.realtime_session_id:
        command.extend(["--realtime-events-jsonl", paths["realtime_events_jsonl"]])
    if args.allow_missing_realtime:
        command.append("--allow-missing-realtime")
    if args.allow_missing_stable_correction:
        command.append("--allow-missing-stable-correction")
    if args.out:
        command.extend(["--out", str(resolve_repo_path(args.out))])
    return command


def build_bundle_commands(args: argparse.Namespace) -> dict[str, list[str]]:
    commands = {"productionReadiness": build_validation_command(args)}
    if args.evidence_matrix_out:
        commands["productionEvidenceMatrix"] = build_matrix_command(args)
    if args.goal_audit_out:
        commands["productionGoalAudit"] = build_goal_audit_command(args)
    return commands


def build_matrix_command(args: argparse.Namespace) -> list[str]:
    if not args.out:
        raise SystemExit("--out is required when building a production evidence matrix.")
    command = [
        sys.executable,
        str(COLLECT_MATRIX),
        "--production-readiness-report",
        str(resolve_repo_path(args.out)),
        "--out",
        str(resolve_repo_path(args.evidence_matrix_out)),
    ]
    append_optional_report(command, "--cloud-run-config-report", args.cloud_run_config_report)
    append_optional_report(command, "--cloud-run-api-preflight-report", args.cloud_run_api_preflight_report)
    append_optional_report(
        command,
        "--realtime-audio-source-preflight-report",
        args.realtime_audio_source_preflight_report,
    )
    append_optional_report(command, "--server-realtime-contract-report", args.server_realtime_contract_report)
    append_optional_report(command, "--web-realtime-contract-report", args.web_realtime_contract_report)
    append_optional_report(
        command,
        "--public-caption-view-runtime-report",
        args.public_caption_view_runtime_report,
    )
    append_optional_report(command, "--realtime-public-sse-smoke-report", args.realtime_public_sse_smoke_report)
    append_optional_report(command, "--realtime-openai-smoke-report", args.realtime_openai_smoke_report)
    append_optional_report(command, "--realtime-session-validation-report", args.realtime_session_validation_report)
    append_optional_report(command, "--stable-correction-contract-report", args.stable_correction_contract_report)
    append_optional_report(command, "--offline-archive-preflight-report", args.offline_archive_preflight_report)
    append_optional_report(command, "--offline-chain-validation-report", args.offline_chain_validation_report)
    append_optional_report(command, "--offline-asr-chain-validation-report", args.offline_asr_chain_validation_report)
    append_optional_report(command, "--offline-asr-smoke-report", args.offline_asr_smoke_report)
    append_optional_report(command, "--offline-translation-report", args.offline_translation_report)
    append_optional_report(command, "--sunday-manifest-validation-report", args.sunday_manifest_validation_report)
    append_optional_report(command, "--openai-model-access-preflight-report", args.openai_model_access_preflight_report)
    for path in args.openai_alternative_model_access_preflight_report:
        append_optional_report(command, "--openai-alternative-model-access-preflight-report", path)
    append_optional_report(command, "--update-plan", args.cloud_run_update_plan)
    append_optional_report(command, "--update-execution", args.cloud_run_update_execution)
    return command


def build_goal_audit_command(args: argparse.Namespace) -> list[str]:
    if not args.out:
        raise SystemExit("--out is required when building a production goal audit.")
    command = [
        sys.executable,
        str(AUDIT_GOAL),
        "--production-readiness-report",
        str(resolve_repo_path(args.out)),
        "--out",
        str(resolve_repo_path(args.goal_audit_out)),
    ]
    append_optional_report(command, "--cloud-run-config-report", args.cloud_run_config_report)
    append_optional_report(command, "--cloud-run-api-preflight-report", args.cloud_run_api_preflight_report)
    if args.evidence_matrix_out:
        append_optional_report(
            command,
            "--evidence-matrix-report",
            str(resolve_repo_path(args.evidence_matrix_out)),
        )
    return command


def run_bundle_commands(commands: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
    results = {}
    readiness_report = command_value(commands.get("productionReadiness", []), "--out")
    matrix_report = command_value(commands.get("productionEvidenceMatrix", []), "--out")
    for name, command in commands.items():
        if name in {"productionEvidenceMatrix", "productionGoalAudit"}:
            ensure_readiness_report_exists(readiness_report, results.get("productionReadiness"))
        if name == "productionGoalAudit":
            ensure_matrix_report_exists(matrix_report, results.get("productionEvidenceMatrix"))
        completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)
        results[name] = {
            "command": command,
            "returnCode": completed.returncode,
            "stdout": tail(completed.stdout),
            "stderr": tail(completed.stderr),
        }
    return results


def ensure_readiness_report_exists(path_value: str | None, production_step: dict[str, Any] | None) -> None:
    if not path_value:
        return
    path = Path(path_value)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": "failed",
                "failedChecks": ["production_readiness_report_missing"],
                "warnings": [],
                "checks": [
                    {
                        "name": "production_readiness_report",
                        "state": "fail",
                        "observed": "validate_production_readiness.py exited before writing its report",
                    }
                ],
                "sunday": None,
                "offline": None,
                "sundayManifest": None,
                "realtime": None,
                "commandReturnCode": production_step.get("returnCode") if production_step else None,
                "commandStdoutTail": production_step.get("stdout") if production_step else None,
                "commandStderrTail": production_step.get("stderr") if production_step else None,
                "apiKeyMaterialIncluded": False,
                "secretResourceNamesIncluded": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def ensure_matrix_report_exists(path_value: str | None, matrix_step: dict[str, Any] | None) -> None:
    if not path_value:
        return
    path = Path(path_value)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": "incomplete",
                "summary": {
                    "passed": 0,
                    "failed": 1,
                    "missing": 0,
                    "warnings": 0,
                    "total": 1,
                },
                "matrix": [
                    {
                        "id": "production_evidence_matrix",
                        "label": "Production evidence matrix",
                        "description": "collect_production_evidence_matrix.py exited before writing its report.",
                        "state": "fail",
                        "evidence": path_value,
                        "observed": {
                            "commandReturnCode": matrix_step.get("returnCode") if matrix_step else None,
                            "commandStdoutTail": matrix_step.get("stdout") if matrix_step else None,
                            "commandStderrTail": matrix_step.get("stderr") if matrix_step else None,
                        },
                        "nextAction": "Fix production evidence matrix input report paths, then rerun run_sunday_evidence_bundle.py.",
                    }
                ],
                "nextActions": [
                    "Fix production evidence matrix input report paths, then rerun run_sunday_evidence_bundle.py."
                ],
                "apiKeyMaterialIncluded": False,
                "secretResourceNamesIncluded": False,
                "eventTokenIncluded": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def append_optional_report(command: list[str], flag: str, path_value: str | Path | None) -> None:
    if path_value:
        command.extend([flag, str(resolve_repo_path(Path(path_value)))])


def write_report(path_value: Path | None, report: dict[str, Any]) -> None:
    if not path_value:
        return
    path = resolve_repo_path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def default_production_readiness_report(args: argparse.Namespace) -> Path:
    return Path("artifacts") / "evidence" / f"{args.sunday}-{safe_session_id(args.session_id)}-production-readiness.json"


def evidence_paths(args: argparse.Namespace) -> dict[str, str]:
    if args.artifact_location == "gcs":
        run_base = gcs_join(
            f"gs://{normalize_bucket(args.artifact_bucket)}",
            normalize_prefix(args.artifact_prefix),
            args.sunday,
            "runs",
            args.session_id,
        )
        sunday_manifest = gcs_join(
            f"gs://{normalize_bucket(args.artifact_bucket)}",
            normalize_prefix(args.artifact_prefix),
            args.sunday,
            "cloud-manifest.json",
        )
        paths = {
            "offline_report": gcs_join(run_base, "artifacts", "report.json"),
            "playback_js": gcs_join(run_base, "web", "playback-simulation.generated.js"),
            "zh_vtt": gcs_join(run_base, "artifacts", "sermon.zh.live-aligned.vtt"),
            "zh_srt": gcs_join(run_base, "artifacts", "sermon.zh.live-aligned.srt"),
            "run_manifest": gcs_join(run_base, "artifacts", "cloud-manifest.json"),
            "sunday_manifest": sunday_manifest,
        }
    else:
        run_root = resolve_repo_path(args.work_root) / args.sunday / args.session_id
        paths = {
            "offline_report": str(run_root / "artifacts" / "report.json"),
            "playback_js": str(run_root / "web" / "playback-simulation.generated.js"),
            "zh_vtt": str(run_root / "artifacts" / "sermon.zh.live-aligned.vtt"),
            "zh_srt": str(run_root / "artifacts" / "sermon.zh.live-aligned.srt"),
            "run_manifest": str(run_root / "artifacts" / "cloud-manifest.json"),
            "sunday_manifest": gcs_join(
                f"gs://{normalize_bucket(args.artifact_bucket)}",
                normalize_prefix(args.artifact_prefix),
                args.sunday,
                "cloud-manifest.json",
            )
            if args.artifact_bucket
            else str(run_root / "artifacts" / "cloud-manifest.json"),
        }

    if args.realtime_session_id:
        if args.realtime_location == "gcs":
            paths["realtime_events_jsonl"] = gcs_join(
                normalize_gcs_prefix(args.realtime_event_gcs_prefix),
                args.sunday,
                f"{safe_session_id(args.realtime_session_id)}.jsonl",
            )
        else:
            paths["realtime_events_jsonl"] = str(
                resolve_repo_path(args.realtime_event_dir) / f"{safe_session_id(args.realtime_session_id)}.jsonl"
            )
    return paths


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def normalize_bucket(bucket: str | None) -> str:
    if not bucket:
        raise SystemExit("GCS bucket is required.")
    clean = bucket.strip()
    if clean.startswith("gs://"):
        clean = clean[5:]
    clean = clean.strip("/")
    if not clean or "/" in clean:
        raise SystemExit("GCS bucket must be a bucket name, not a path.")
    return clean


def normalize_prefix(prefix: str | None) -> str:
    clean = (prefix or "").strip().strip("/")
    if "\\" in clean or any(part in {".", ".."} for part in clean.split("/") if part):
        raise SystemExit("GCS prefix contains an unsafe path segment.")
    return clean


def normalize_gcs_prefix(value: str | None) -> str:
    clean = (value or "").strip().rstrip("/")
    if not clean.startswith("gs://"):
        raise SystemExit("Realtime event GCS prefix must start with gs://")
    return clean


def gcs_join(*parts: str) -> str:
    first, *rest = parts
    result = first.rstrip("/")
    for part in rest:
        clean = str(part).strip("/")
        if clean:
            result += "/" + clean
    return result


def safe_session_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def tail(text: str, limit: int = 4000) -> str:
    return text[-limit:] if len(text) > limit else text


def command_value(command: list[str], flag: str) -> str | None:
    try:
        index = command.index(flag)
    except ValueError:
        return None
    value_index = index + 1
    return command[value_index] if value_index < len(command) else None


def realtime_session_id_from_report(uri: str) -> str | None:
    return realtime_evidence_from_report(uri).get("sessionId")


def realtime_evidence_from_report(uri: str) -> dict[str, str]:
    try:
        text = read_text(uri)
        data = json.loads(text)
    except (OSError, json.JSONDecodeError, subprocess.CalledProcessError):
        raise SystemExit(f"Could not read realtime smoke report: {uri}")
    if not isinstance(data, dict):
        raise SystemExit("Realtime smoke report must be a JSON object.")
    session_id = str(data.get("sessionId") or "").strip()
    events_jsonl = str(data.get("realtimeEventsJsonl") or "").strip()
    evidence = {}
    if session_id:
        evidence["sessionId"] = session_id
    if events_jsonl:
        evidence["realtimeEventsJsonl"] = events_jsonl
    return evidence


def read_text(uri: str) -> str:
    if str(uri).startswith("gs://"):
        completed = subprocess.run(["gcloud", "storage", "cat", uri], check=True, capture_output=True, text=True)
        return completed.stdout
    return Path(uri).read_text(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
