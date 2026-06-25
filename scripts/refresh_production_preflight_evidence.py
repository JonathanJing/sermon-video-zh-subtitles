#!/usr/bin/env python3
"""Refresh read-only production preflight evidence before a live Sunday run."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app"
DEFAULT_SERVICE = "sermon-zh-caption-web"
DEFAULT_PROJECT = "ai-for-god"
DEFAULT_REGION = "us-west1"
EXPECTED_REALTIME_MODEL = "gpt-realtime-translate"
EXPECTED_TARGET_LANGUAGE = "zh"
EXPECTED_AUDIO_SOURCE_KIND = "ipad_mic"
EXPECTED_CLOUD_RUN_API_PREFLIGHT_CHECKS = [
    "realtime_local_session_create",
    "realtime_local_session_metadata",
    "no_secret_material_in_http_responses",
]
EXPECTED_INCOMPLETE_STEPS = {"productionMatrix", "goalAudit"}
POST_REPORT_STEPS = ("productionGoLiveSequence", "realtimeHandoffValidation")
POST_REPORT_RERUN_STEPS = ("productionMatrix", "goalAudit")
LOCAL_ONLY_SKIP_STEPS = {
    "cloudRunConfig",
    "cloudRunUpdatePlan",
    "cloudRunUpdateDryRun",
    "cloudRunApiPreflight",
    "deployedWebrtcSession",
    "requiredModelAccess",
    "alternativeModelAccess",
}


def main() -> int:
    args = parse_args()
    report = refresh_evidence(args)
    write_report(args.out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.dry_run:
        return 0
    if args.local_only and not report["failedSteps"]:
        return 0
    return 0 if report["status"] == "ok" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default=DEFAULT_SERVICE)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--sunday", default=upcoming_sunday(), help="Sunday slice date, YYYY-MM-DD.")
    parser.add_argument(
        "--realtime-event-gcs-prefix",
        default="gs://sermon-zh-artifacts-ai-for-god/realtime-events",
    )
    parser.add_argument("--required-model", default="gpt-5.4-mini")
    parser.add_argument("--alternative-model", default="gpt-5.5")
    parser.add_argument("--evidence-dir", type=Path, default=Path("artifacts/evidence"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/evidence/production-preflight-refresh.json"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Refresh only local contract/planning evidence; skip Cloud Run, OpenAI, and deployed API checks.",
    )
    return parser.parse_args()


def refresh_evidence(args: argparse.Namespace) -> dict[str, Any]:
    paths = evidence_paths(args.evidence_dir)
    commands = build_commands(args, paths)
    if args.dry_run:
        return report_from_steps(args, commands, {}, "planned")

    steps = {}
    selected_commands = select_commands(commands, local_only=args.local_only)
    for name, command in selected_commands.items():
        if name in POST_REPORT_STEPS:
            continue
        steps[name] = run_command(name, command)
    report = report_from_steps(args, commands, steps, status_from_steps(steps))
    write_report(args.out, report)

    for name in POST_REPORT_STEPS:
        command = selected_commands.get(name)
        if command:
            steps[name] = run_command(name, command)
    for name in POST_REPORT_RERUN_STEPS:
        command = selected_commands.get(name)
        if command:
            steps[name] = run_command(name, command)
    return report_from_steps(args, commands, steps, status_from_steps(steps))


def select_commands(commands: dict[str, list[str]], *, local_only: bool) -> dict[str, list[str]]:
    if not local_only:
        return commands
    return {name: command for name, command in commands.items() if name not in LOCAL_ONLY_SKIP_STEPS}


def evidence_paths(evidence_dir: Path) -> dict[str, Path]:
    root = resolve_repo_path(evidence_dir)
    return {
        "cloudRunConfig": root / "cloud-run-realtime-config.json",
        "cloudRunApiPreflight": root / "cloud-run-api-preflight-readonly.json",
        "requiredModelAccess": root / "openai-model-access-preflight.json",
        "alternativeModelAccess": root / "openai-model-access-preflight-gpt-5.5.json",
        "modelAccessRecoveryPlan": root / "model-access-recovery-plan.json",
        "productionMatrix": root / "production-evidence-matrix.json",
        "productionUnblockPlan": root / "production-unblock-plan.json",
        "operatorApprovalBundle": root / "operator-approval-bundle.json",
        "productionGoLiveSequence": root / "production-go-live-sequence.json",
        "realtimeHandoffValidation": root / "realtime-handoff-validation.json",
        "live1130RunPlan": root / "live-1130-realtime-run-plan.json",
        "goalAudit": root / "production-goal-readiness-audit.json",
        "realtimeAudioSource": root / "realtime-audio-source-preflight.json",
        "serverRealtimeContract": root / "server-realtime-contract.json",
        "webRealtimeContract": root / "web-realtime-contract.json",
        "deployedWebrtcSession": root / "deployed-webrtc-realtime-session-smoke.json",
        "publicCaptionViewRuntime": root / "public-caption-view-runtime.json",
        "realtimePublicSse": root / "realtime-public-sse-smoke.json",
        "realtimeOpenaiSmoke": root / "realtime-openai-smoke" / "report.json",
        "realtimeSessionValidation": root / "realtime-openai-smoke" / "realtime-session-validation.json",
        "stableCorrectionContract": root / "stable-correction-contract.json",
        "offlineArchivePreflight": root / "offline-archive-preflight.json",
        "offlineWorkerPlan": root / "worker-caption-first-plan.json",
        "noCaptionAsrPlan": root / "no-caption-asr-fallback-plan.json",
        "offlineSourceRunRoot": root / "offline-export-contract",
        "localSundayManifestEvidence": root / "local-sunday-manifest-evidence.json",
        "localSundayManifestRoot": root / "manifest-promotion-guard",
        "offlineChainValidation": root / "offline-chain-validation.json",
        "offlineAsrChainValidation": root / "no-caption-offline-chain-validation.json",
        "offlineAsrRouteRun": root / "no-caption-asr-route-run.json",
        "offlineAsrSampleChainRoot": root / "no-caption-asr-sample-chain",
        "offlineAsrSampleChainReport": root / "no-caption-asr-sample-chain" / "sample-chain-report.json",
        "offlineAsrSampleChainValidation": root / "no-caption-asr-sample-chain-validation.json",
        "offlineAsrSmoke": root / "offline-asr-fallback-smoke" / "report.json",
        "offlineTranslation": root / "offline-caption-route" / "model-output" / "openai-translation-report.json",
        "sundayManifestValidation": root / "sunday-manifest-validation.json",
        "gcsManifestPublishPlan": root / "gcs-sunday-manifest-publish-plan.json",
        "cloudRunUpdatePlan": root / "cloud-run-realtime-update-plan.json",
        "cloudRunUpdateExecution": root / "cloud-run-realtime-update-execution-dry-run.json",
    }


def build_commands(args: argparse.Namespace, paths: dict[str, Path]) -> dict[str, list[str]]:
    return {
        "cloudRunConfig": [
            sys.executable,
            "scripts/validate_cloud_run_realtime_config.py",
            "--service",
            args.service,
            "--project",
            args.project,
            "--region",
            args.region,
            "--out",
            str(paths["cloudRunConfig"]),
        ],
        "cloudRunUpdatePlan": [
            sys.executable,
            "scripts/prepare_cloud_run_realtime_update_plan.py",
            "--config-report",
            str(paths["cloudRunConfig"]),
            "--service",
            args.service,
            "--project",
            args.project,
            "--region",
            args.region,
            "--realtime-event-gcs-prefix",
            args.realtime_event_gcs_prefix,
            "--out",
            str(paths["cloudRunUpdatePlan"]),
        ],
        "cloudRunUpdateDryRun": [
            sys.executable,
            "scripts/apply_cloud_run_realtime_update_plan.py",
            "--plan",
            str(paths["cloudRunUpdatePlan"]),
            "--out",
            str(paths["cloudRunUpdateExecution"]),
        ],
        "cloudRunApiPreflight": [
            sys.executable,
            "scripts/run_cloud_run_realtime_preflight.py",
            "--base-url",
            args.base_url,
            "--cloud-run-config-report",
            str(paths["cloudRunConfig"]),
            "--create-realtime-session",
            "--internal-task-token",
            "$INTERNAL_TASK_TOKEN",
            "--out",
            str(paths["cloudRunApiPreflight"]),
        ],
        "deployedWebrtcSession": [
            sys.executable,
            "scripts/run_deployed_webrtc_session_smoke.py",
            "--base-url",
            args.base_url,
            "--sunday",
            args.sunday,
            "--internal-task-token",
            "$INTERNAL_TASK_TOKEN",
            "--out",
            str(paths["deployedWebrtcSession"]),
        ],
        "requiredModelAccess": [
            sys.executable,
            "scripts/run_openai_model_access_preflight.py",
            "--cloud-run-service",
            args.service,
            "--project",
            args.project,
            "--region",
            args.region,
            "--model",
            args.required_model,
            "--out",
            str(paths["requiredModelAccess"]),
        ],
        "alternativeModelAccess": [
            sys.executable,
            "scripts/run_openai_model_access_preflight.py",
            "--cloud-run-service",
            args.service,
            "--project",
            args.project,
            "--region",
            args.region,
            "--model",
            args.alternative_model,
            "--out",
            str(paths["alternativeModelAccess"]),
        ],
        "modelAccessRecoveryPlan": [
            sys.executable,
            "scripts/write_model_access_recovery_plan.py",
            "--sunday",
            args.sunday,
            "--required-model",
            args.required_model,
            "--alternative-model",
            args.alternative_model,
            "--required-report",
            str(paths["requiredModelAccess"]),
            "--alternative-report",
            str(paths["alternativeModelAccess"]),
            "--out",
            str(paths["modelAccessRecoveryPlan"]),
        ],
        "serverRealtimeContract": [
            sys.executable,
            "scripts/validate_server_realtime_contract.py",
            "--out",
            str(paths["serverRealtimeContract"]),
        ],
        "webRealtimeContract": [
            sys.executable,
            "scripts/validate_web_realtime_contract.py",
            "--out",
            str(paths["webRealtimeContract"]),
        ],
        "stableCorrectionContract": [
            sys.executable,
            "scripts/validate_stable_correction_contract.py",
            "--out",
            str(paths["stableCorrectionContract"]),
        ],
        "live1130RunPlan": [
            sys.executable,
            "scripts/write_1130_live_realtime_run_plan.py",
            "--sunday",
            args.sunday,
            "--base-url",
            args.base_url,
            "--out",
            str(paths["live1130RunPlan"]),
        ],
        "offlineWorkerPlan": [
            sys.executable,
            "scripts/write_worker_caption_first_plan.py",
            "--out",
            str(paths["offlineWorkerPlan"]),
        ],
        "publicCaptionViewRuntime": [
            sys.executable,
            "scripts/validate_public_caption_view_runtime.py",
            "--out",
            str(paths["publicCaptionViewRuntime"]),
        ],
        "noCaptionAsrPlan": [
            sys.executable,
            "scripts/write_no_caption_asr_fallback_plan.py",
            "--sunday",
            args.sunday,
            "--out",
            str(paths["noCaptionAsrPlan"]),
        ],
        "offlineAsrSampleChain": [
            sys.executable,
            "scripts/build_no_caption_asr_sample_chain.py",
            "--asr-smoke-report",
            str(paths["offlineAsrSmoke"]),
            "--sunday",
            args.sunday,
            "--out-root",
            str(paths["offlineAsrSampleChainRoot"]),
            "--validation-out",
            str(paths["offlineAsrSampleChainValidation"]),
            "--out",
            str(paths["offlineAsrSampleChainReport"]),
        ],
        "localSundayManifestEvidence": [
            sys.executable,
            "scripts/build_local_sunday_manifest_evidence.py",
            "--sunday",
            args.sunday,
            "--source-run-root",
            str(paths["offlineSourceRunRoot"]),
            "--out-root",
            str(paths["localSundayManifestRoot"]),
            "--validation-out",
            str(paths["sundayManifestValidation"]),
            "--offline-chain-validation-out",
            str(paths["offlineChainValidation"]),
        ],
        "gcsManifestPublishPlan": [
            sys.executable,
            "scripts/plan_gcs_sunday_manifest_publish.py",
            "--sunday",
            args.sunday,
            "--local-root",
            str(paths["localSundayManifestRoot"]),
            "--bucket",
            "sermon-zh-artifacts-ai-for-god",
            "--prefix",
            "sundays",
            "--session-id",
            "local-manifest-contract",
            "--out",
            str(paths["gcsManifestPublishPlan"]),
        ],
        "productionMatrix": production_matrix_command(paths),
        "productionUnblockPlan": production_unblock_plan_command(paths),
        "operatorApprovalBundle": operator_approval_bundle_command(args, paths),
        "goalAudit": goal_audit_command(paths),
        "productionGoLiveSequence": production_go_live_sequence_command(args, paths),
        "realtimeHandoffValidation": realtime_handoff_validation_command(paths),
    }


def production_matrix_command(paths: dict[str, Path]) -> list[str]:
    return [
        sys.executable,
        "scripts/collect_production_evidence_matrix.py",
        "--cloud-run-config-report",
        str(paths["cloudRunConfig"]),
        "--cloud-run-api-preflight-report",
        str(paths["cloudRunApiPreflight"]),
        "--realtime-audio-source-preflight-report",
        str(paths["realtimeAudioSource"]),
        "--server-realtime-contract-report",
        str(paths["serverRealtimeContract"]),
        "--web-realtime-contract-report",
        str(paths["webRealtimeContract"]),
        "--deployed-webrtc-session-report",
        str(paths["deployedWebrtcSession"]),
        "--live-1130-run-plan-report",
        str(paths["live1130RunPlan"]),
        "--realtime-handoff-validation-report",
        str(paths["realtimeHandoffValidation"]),
        "--public-caption-view-runtime-report",
        str(paths["publicCaptionViewRuntime"]),
        "--realtime-public-sse-smoke-report",
        str(paths["realtimePublicSse"]),
        "--realtime-openai-smoke-report",
        str(paths["realtimeOpenaiSmoke"]),
        "--realtime-session-validation-report",
        str(paths["realtimeSessionValidation"]),
        "--stable-correction-contract-report",
        str(paths["stableCorrectionContract"]),
        "--offline-archive-preflight-report",
        str(paths["offlineArchivePreflight"]),
        "--offline-worker-plan-report",
        str(paths["offlineWorkerPlan"]),
        "--offline-chain-validation-report",
        str(paths["offlineChainValidation"]),
        "--offline-asr-chain-validation-report",
        str(paths["offlineAsrChainValidation"]),
        "--offline-asr-route-run-report",
        str(paths["offlineAsrRouteRun"]),
        "--offline-asr-sample-chain-validation-report",
        str(paths["offlineAsrSampleChainValidation"]),
        "--no-caption-asr-plan-report",
        str(paths["noCaptionAsrPlan"]),
        "--offline-asr-smoke-report",
        str(paths["offlineAsrSmoke"]),
        "--offline-translation-report",
        str(paths["offlineTranslation"]),
        "--sunday-manifest-validation-report",
        str(paths["sundayManifestValidation"]),
        "--gcs-manifest-publish-plan",
        str(paths["gcsManifestPublishPlan"]),
        "--openai-model-access-preflight-report",
        str(paths["requiredModelAccess"]),
        "--openai-alternative-model-access-preflight-report",
        str(paths["alternativeModelAccess"]),
        "--update-plan",
        str(paths["cloudRunUpdatePlan"]),
        "--update-execution",
        str(paths["cloudRunUpdateExecution"]),
        "--out",
        str(paths["productionMatrix"]),
    ]


def goal_audit_command(paths: dict[str, Path]) -> list[str]:
    return [
        sys.executable,
        "scripts/audit_production_goal_readiness.py",
        "--cloud-run-config-report",
        str(paths["cloudRunConfig"]),
        "--cloud-run-api-preflight-report",
        str(paths["cloudRunApiPreflight"]),
        "--evidence-matrix-report",
        str(paths["productionMatrix"]),
        "--openai-model-access-preflight-report",
        str(paths["requiredModelAccess"]),
        "--out",
        str(paths["goalAudit"]),
    ]


def production_unblock_plan_command(paths: dict[str, Path]) -> list[str]:
    return [
        sys.executable,
        "scripts/write_production_unblock_plan.py",
        "--evidence-matrix",
        str(paths["productionMatrix"]),
        "--gcs-manifest-publish-plan",
        str(paths["gcsManifestPublishPlan"]),
        "--cloud-run-update-plan",
        str(paths["cloudRunUpdatePlan"]),
        "--out",
        str(paths["productionUnblockPlan"]),
    ]


def operator_approval_bundle_command(args: argparse.Namespace, paths: dict[str, Path]) -> list[str]:
    return [
        sys.executable,
        "scripts/write_operator_approval_bundle.py",
        "--sunday",
        args.sunday,
        "--unblock-plan",
        str(paths["productionUnblockPlan"]),
        "--cloud-run-update-plan",
        str(paths["cloudRunUpdatePlan"]),
        "--cloud-run-dry-run",
        str(paths["cloudRunUpdateExecution"]),
        "--gcs-publish-plan",
        str(paths["gcsManifestPublishPlan"]),
        "--live-1130-run-plan",
        str(paths["live1130RunPlan"]),
        "--out",
        str(paths["operatorApprovalBundle"]),
    ]


def production_go_live_sequence_command(args: argparse.Namespace, paths: dict[str, Path]) -> list[str]:
    return [
        sys.executable,
        "scripts/write_production_go_live_sequence.py",
        "--sunday",
        args.sunday,
        "--preflight-refresh",
        str(resolve_repo_path(args.out)),
        "--goal-audit",
        str(paths["goalAudit"]),
        "--unblock-plan",
        str(paths["productionUnblockPlan"]),
        "--operator-approval-bundle",
        str(paths["operatorApprovalBundle"]),
        "--model-access-recovery-plan",
        str(paths["modelAccessRecoveryPlan"]),
        "--no-caption-asr-plan",
        str(paths["noCaptionAsrPlan"]),
        "--live-1130-run-plan",
        str(paths["live1130RunPlan"]),
        "--out",
        str(paths["productionGoLiveSequence"]),
    ]


def realtime_handoff_validation_command(paths: dict[str, Path]) -> list[str]:
    return [
        sys.executable,
        "scripts/validate_realtime_handoff.py",
        "--live-plan",
        str(paths["live1130RunPlan"]),
        "--operator-bundle",
        str(paths["operatorApprovalBundle"]),
        "--go-live-sequence",
        str(paths["productionGoLiveSequence"]),
        "--out",
        str(paths["realtimeHandoffValidation"]),
    ]


def run_command(name: str, command: list[str]) -> dict[str, Any]:
    try:
        executable_command = expand_runtime_placeholders(command)
    except RuntimeError as exc:
        return {
            "returnCode": 2,
            "status": classify_step_status(name, 2),
            "stdoutTail": "",
            "stderrTail": sanitize_tail(str(exc)),
        }
    completed = subprocess.run(
        executable_command,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "returnCode": completed.returncode,
        "status": classify_step_status(name, completed.returncode),
        "stdoutTail": sanitize_tail(tail(completed.stdout)),
        "stderrTail": sanitize_tail(tail(completed.stderr)),
    }


def status_from_steps(steps: dict[str, dict[str, Any]]) -> str:
    return "ok" if all(step["status"] == "ok" for step in steps.values()) else "incomplete"


def expand_runtime_placeholders(command: list[str]) -> list[str]:
    expanded = []
    for value in command:
        if value == "$INTERNAL_TASK_TOKEN":
            token = os.getenv("INTERNAL_TASK_TOKEN")
            if not token:
                raise RuntimeError("INTERNAL_TASK_TOKEN is required for this preflight step.")
            expanded.append(token)
        else:
            expanded.append(value)
    return expanded


def classify_step_status(name: str, return_code: int) -> str:
    if return_code == 0:
        return "ok"
    if name in EXPECTED_INCOMPLETE_STEPS and return_code == 2:
        return "incomplete"
    return "failed"


def report_from_steps(
    args: argparse.Namespace,
    commands: dict[str, list[str]],
    steps: dict[str, dict[str, Any]],
    status: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "status": status,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "service": args.service,
        "project": args.project,
        "region": args.region,
        "baseUrl": args.base_url,
        "sunday": args.sunday,
        "realtimeEventGcsPrefix": args.realtime_event_gcs_prefix,
        "requiredModel": args.required_model,
        "alternativeModel": args.alternative_model,
        "expectedRealtimeSession": {
            "model": EXPECTED_REALTIME_MODEL,
            "targetLanguage": EXPECTED_TARGET_LANGUAGE,
            "audioSourceKind": EXPECTED_AUDIO_SOURCE_KIND,
        },
        "expectedValidationChecks": {
            "cloudRunApiPreflight": EXPECTED_CLOUD_RUN_API_PREFLIGHT_CHECKS,
        },
        "commands": commands,
        "steps": steps,
        "mode": "local_only" if args.local_only else "full",
        "skippedSteps": sorted(LOCAL_ONLY_SKIP_STEPS) if args.local_only else [],
        "failedSteps": [name for name, step in steps.items() if step.get("status") == "failed"],
        "incompleteSteps": [name for name, step in steps.items() if step.get("status") == "incomplete"],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def write_report(path: Path | None, report: dict[str, Any]) -> None:
    if not path:
        return
    out = resolve_repo_path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def tail(text: str, limit: int = 2500) -> str:
    return text[-limit:] if len(text) > limit else text


def sanitize_tail(text: str) -> str:
    clean = str(text or "")
    clean = re.sub(r"\bsk-[A-Za-z0-9_-]+", "sk-REDACTED", clean)
    clean = re.sub(
        r"projects/[^/\s,'\"]+/secrets/[^/\s,'\"]+(?:/versions/[^/\s,'\"]+)?",
        "projects/REDACTED/secrets/REDACTED/versions/REDACTED",
        clean,
    )
    clean = re.sub(r"(?<!-)\b(?:operator-admin-token|internal-task-token)\b", "<redacted-secret-name>", clean)
    return clean


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def upcoming_sunday(today: date | None = None) -> str:
    today = today or date.today()
    days_until_sunday = (6 - today.weekday()) % 7
    return (today + timedelta(days=days_until_sunday)).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
