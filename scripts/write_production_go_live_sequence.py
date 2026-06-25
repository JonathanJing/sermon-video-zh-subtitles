#!/usr/bin/env python3
"""Write a sanitized go-live sequence from the current production handoffs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "artifacts" / "evidence" / "production-go-live-sequence.json"
DEFAULT_PREFLIGHT_REFRESH = REPO_ROOT / "artifacts" / "evidence" / "production-preflight-refresh.json"
DEFAULT_GOAL_AUDIT = REPO_ROOT / "artifacts" / "evidence" / "production-goal-readiness-audit.json"
DEFAULT_UNBLOCK_PLAN = REPO_ROOT / "artifacts" / "evidence" / "production-unblock-plan.json"
DEFAULT_OPERATOR_APPROVAL_BUNDLE = REPO_ROOT / "artifacts" / "evidence" / "operator-approval-bundle.json"
DEFAULT_MODEL_ACCESS_RECOVERY_PLAN = REPO_ROOT / "artifacts" / "evidence" / "model-access-recovery-plan.json"
DEFAULT_NO_CAPTION_ASR_PLAN = REPO_ROOT / "artifacts" / "evidence" / "no-caption-asr-fallback-plan.json"
DEFAULT_LIVE_1130_RUN_PLAN = REPO_ROOT / "artifacts" / "evidence" / "live-1130-realtime-run-plan.json"
DEFAULT_PRODUCTION_MATRIX = REPO_ROOT / "artifacts" / "evidence" / "production-evidence-matrix.json"
DEFAULT_REALTIME_EVENT_GCS_PREFIX = "gs://sermon-zh-artifacts-ai-for-god/realtime-events"
DEFAULT_WEB_REALTIME_CONTRACT_REPORT = "artifacts/evidence/web-realtime-contract.json"


def main() -> int:
    args = parse_args()
    report = build_sequence(args)
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sunday", required=True)
    parser.add_argument("--preflight-refresh", type=Path, default=DEFAULT_PREFLIGHT_REFRESH)
    parser.add_argument("--goal-audit", type=Path, default=DEFAULT_GOAL_AUDIT)
    parser.add_argument("--unblock-plan", type=Path, default=DEFAULT_UNBLOCK_PLAN)
    parser.add_argument("--operator-approval-bundle", type=Path, default=DEFAULT_OPERATOR_APPROVAL_BUNDLE)
    parser.add_argument("--model-access-recovery-plan", type=Path, default=DEFAULT_MODEL_ACCESS_RECOVERY_PLAN)
    parser.add_argument("--no-caption-asr-plan", type=Path, default=DEFAULT_NO_CAPTION_ASR_PLAN)
    parser.add_argument("--live-1130-run-plan", type=Path, default=DEFAULT_LIVE_1130_RUN_PLAN)
    parser.add_argument("--production-matrix", type=Path, default=DEFAULT_PRODUCTION_MATRIX)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def build_sequence(args: argparse.Namespace) -> dict[str, Any]:
    preflight = read_optional_json(resolve_repo_path(args.preflight_refresh)) or {}
    goal_audit = read_optional_json(resolve_repo_path(args.goal_audit)) or {}
    unblock = read_optional_json(resolve_repo_path(args.unblock_plan)) or {}
    operator_bundle = read_optional_json(resolve_repo_path(args.operator_approval_bundle)) or {}
    model_plan = read_optional_json(resolve_repo_path(args.model_access_recovery_plan)) or {}
    no_caption_plan = read_optional_json(resolve_repo_path(args.no_caption_asr_plan)) or {}
    live_1130_plan = read_optional_json(resolve_repo_path(args.live_1130_run_plan)) or {}
    production_matrix = read_optional_json(resolve_repo_path(args.production_matrix)) or {}

    model_recovery_needed = required_model_recovery_needed(preflight, unblock)
    required_model_stage = required_model_recovery_stage(args, model_plan) if model_recovery_needed else None
    real_no_caption_depends_on = ["required_model_recovery"] if required_model_stage else ["post_approval_validation"]
    final_dependencies = [
        "operator_approval",
        "post_approval_validation",
        "live_1130_realtime_run",
        "real_no_caption_asr_validation",
    ]
    if required_model_stage:
        final_dependencies.insert(3, "required_model_recovery")

    stages = [
        operator_approval_stage(args, unblock, operator_bundle),
        post_approval_validation_stage(args, unblock, operator_bundle),
        live_1130_realtime_run_stage(args, live_1130_plan, unblock),
        required_model_stage,
        real_no_caption_asr_validation_stage(
            args,
            no_caption_plan,
            production_matrix,
            depends_on=real_no_caption_depends_on,
        ),
        final_readiness_audit_stage(
            args,
            preflight,
            goal_audit,
            unblock,
            production_matrix,
            depends_on=final_dependencies,
        ),
    ]
    stages = [stage for stage in stages if stage is not None]
    blockers = current_blockers(preflight, goal_audit, unblock, production_matrix, stages)
    return {
        "schemaVersion": 1,
        "status": "not_ready_for_go_live" if has_blockers(blockers) else "ready_for_go_live",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sunday": args.sunday,
        "currentStatus": {
            "preflightRefresh": preflight.get("status") or "missing",
            "goalAudit": goal_audit.get("status") or "missing",
            "unblockPlan": unblock.get("status") or "missing",
        },
        "handoffReports": {
            "operatorApprovalBundle": display_path(args.operator_approval_bundle),
            "modelAccessRecoveryPlan": display_path(args.model_access_recovery_plan),
            "noCaptionAsrFallbackPlan": display_path(args.no_caption_asr_plan),
            "live1130RealtimeRunPlan": display_path(args.live_1130_run_plan),
            "preflightRefresh": display_path(args.preflight_refresh),
            "goalAudit": display_path(args.goal_audit),
            "unblockPlan": display_path(args.unblock_plan),
            "productionMatrix": display_path(args.production_matrix),
        },
        "sequence": stages,
        "blockingSummary": blockers,
        "passCriteria": [
            "Operator approval bundle has no remaining approval_required steps, or approved Cloud Run/GCS evidence is present.",
            "Cloud Run realtime config and API preflight pass after any approved runtime update.",
            "Required gpt-5.4-mini model access passes; gpt-5.5 availability is side evidence only.",
            "11:30 realtime operator plan is ready and preserves browser WebRTC plus server worker options.",
            "Offline translation and stable correction routes use gpt-5.4-mini.",
            "Offline post-live subtitle evidence includes not_realtime_chain=pass.",
            "A real authorized YouTube archive with no requested English caption track proves the gpt-4o-transcribe ASR fallback from an extracted audio artifact.",
            "Final production evidence matrix and goal readiness audit are complete.",
        ],
        "modelPolicy": {
            "realtimeDraftModel": "gpt-realtime-translate",
            "offlineAsrModel": "gpt-4o-transcribe",
            "offlineAndStableCorrectionModel": "gpt-5.4-mini",
            "doNotSubstituteAlternativeForRequiredMini": True,
        },
        "guards": {
            "doesNotApplyCloudRun": True,
            "doesNotUploadGcs": True,
            "doesNotCallOpenAI": True,
            "requiresExplicitOperatorApprovalForMutation": True,
        },
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def live_1130_realtime_run_stage(
    args: argparse.Namespace,
    live_plan: dict[str, Any],
    unblock: dict[str, Any],
) -> dict[str, Any]:
    realtime_step = unblock_step_for_source_row(unblock, "realtime_live")
    plan_status = str(live_plan.get("status") or "missing")
    if realtime_step:
        state = "pending_realtime_field_run"
    elif plan_status == "ready_for_operator_review":
        state = "ready_for_operator_review"
    elif plan_status == "complete":
        state = "complete"
    else:
        state = "needs_live_1130_run_plan"
    return {
        "id": "live_1130_realtime_run",
        "state": state,
        "dependsOn": ["post_approval_validation"],
        "handoffReport": display_path(args.live_1130_run_plan),
        "targetWindow": live_plan.get("targetWindow")
        or {
            "liveCaptionStart": "11:30 PT",
            "publicReadinessDeadline": "11:50 PT",
        },
        "defaultPath": "browser WebRTC iPad/iPhone mic -> gpt-realtime-translate -> public caption SSE",
        "fallbackPath": "server media worker authorized audio -> gpt-realtime-translate -> public caption SSE",
        "modelPolicy": live_plan.get("modelPolicy")
        or {
            "realtimeDraftModel": "gpt-realtime-translate",
            "stableCorrectionModel": "gpt-5.4-mini",
            "offlineAsrModel": "gpt-4o-transcribe",
            "offlineTranslationModel": "gpt-5.4-mini",
            "forbiddenOfflineModel": "gpt-realtime-translate",
        },
        "operatorChoices": operator_choices_summary(live_plan),
        "nextAction": realtime_step.get("reason")
        if realtime_step
        else "Use this operator plan for the 11:30 realtime run after deployed preflight gates pass.",
        "commands": realtime_step.get("commands") if realtime_step else [],
        "liveValidationCommands": dedupe_commands(live_plan.get("liveValidationCommands") or []),
        "stabilizerFallbackCommand": sanitized_command(live_plan.get("stabilizerFallbackCommand")),
        "expectedChecks": realtime_step.get("expectedChecks") if realtime_step else [],
    }


def operator_approval_stage(
    args: argparse.Namespace,
    unblock: dict[str, Any],
    operator_bundle: dict[str, Any],
) -> dict[str, Any]:
    approval_count = int(operator_bundle.get("approvalStepCount") or unblock.get("approvalStepCount") or 0)
    state = "approval_required" if approval_count else "complete"
    return {
        "id": "operator_approval",
        "state": state,
        "handoffReport": display_path(args.operator_approval_bundle),
        "approvalStepCount": approval_count,
        "requiresApproval": approval_count > 0,
        "nextAction": "Review and explicitly approve Cloud Run runtime config and GCS manifest publish steps."
        if approval_count
        else "No operator approval steps are currently reported.",
    }


def post_approval_validation_stage(
    args: argparse.Namespace,
    unblock: dict[str, Any],
    operator_bundle: dict[str, Any],
) -> dict[str, Any]:
    approval_count = int(operator_bundle.get("approvalStepCount") or unblock.get("approvalStepCount") or 0)
    if approval_count:
        state = "blocked_until_operator_approval"
    elif unblock.get("status") == "complete":
        state = "complete"
    else:
        state = "pending_validation"
    return {
        "id": "post_approval_validation",
        "state": state,
        "dependsOn": ["operator_approval"],
        "evidenceReports": [
            "artifacts/evidence/cloud-run-realtime-config.json",
            "artifacts/evidence/cloud-run-api-preflight.json",
            DEFAULT_WEB_REALTIME_CONTRACT_REPORT,
            "artifacts/evidence/realtime-public-sse-smoke.json",
            "artifacts/evidence/realtime-public-sse-smoke.session-validation.json",
            "artifacts/evidence/sunday-manifest-validation.json",
        ],
        "expectedValidationChecks": [
            "realtime_local_session_create",
            "realtime_local_session_metadata",
            "no_secret_material_in_http_responses",
            "browser_normalized_event_payloads",
            "sse_stable_correction_matches_draft_segment",
            "session_jsonl_validation",
        ],
        "commands": [
            [
                "python3",
                "scripts/validate_cloud_run_realtime_config.py",
                "--out",
                "artifacts/evidence/cloud-run-realtime-config.json",
            ],
            [
                "python3",
                "scripts/run_cloud_run_realtime_preflight.py",
                "--base-url",
                "<CLOUD_RUN_BASE_URL>",
                "--cloud-run-config-report",
                "artifacts/evidence/cloud-run-realtime-config.json",
                "--create-realtime-session",
                "--internal-task-token",
                "$INTERNAL_TASK_TOKEN",
                "--out",
                "artifacts/evidence/cloud-run-api-preflight.json",
            ],
            [
                "python3",
                "scripts/run_realtime_public_sse_smoke.py",
                "--base-url",
                "<CLOUD_RUN_BASE_URL>",
                "--sunday",
                args.sunday,
                "--internal-task-token",
                "$INTERNAL_TASK_TOKEN",
                "--realtime-event-gcs-prefix",
                DEFAULT_REALTIME_EVENT_GCS_PREFIX,
                "--web-realtime-contract-report",
                DEFAULT_WEB_REALTIME_CONTRACT_REPORT,
                "--session-validation-out",
                "artifacts/evidence/realtime-public-sse-smoke.session-validation.json",
                "--out",
                "artifacts/evidence/realtime-public-sse-smoke.json",
            ],
            [
                "python3",
                "scripts/validate_sunday_manifest.py",
                "--manifest",
                "gs://<BUCKET>/<PREFIX>/<SUNDAY>/cloud-manifest.json",
                "--sunday",
                args.sunday,
                "--require-readable-artifacts",
                "--out",
                "artifacts/evidence/sunday-manifest-validation.json",
            ],
        ],
    }


def required_model_recovery_stage(args: argparse.Namespace, model_plan: dict[str, Any]) -> dict[str, Any]:
    model_status = str(model_plan.get("status") or "missing")
    if model_status == "complete":
        state = "complete"
    elif model_status == "ready_to_rerun_model_routes":
        state = "pending_model_route_validation"
    elif model_status == "waiting_for_required_model_access":
        state = "blocked_by_required_model_access"
    else:
        state = "needs_model_recovery_plan"
    return {
        "id": "required_model_recovery",
        "state": state,
        "dependsOn": ["post_approval_validation"],
        "handoffReport": display_path(args.model_access_recovery_plan),
        "requiredModel": model_plan.get("requiredModel") or "gpt-5.4-mini",
        "alternativeModel": model_plan.get("alternativeModel") or "gpt-5.5",
        "doNotSubstitute": bool((model_plan.get("modelPolicy") or {}).get("doNotSubstitute", True)),
        "nextAction": "Rerun required model access preflight, then offline translation and stable correction validation.",
    }


def real_no_caption_asr_validation_stage(
    args: argparse.Namespace,
    no_caption_plan: dict[str, Any],
    production_matrix: dict[str, Any],
    *,
    depends_on: list[str],
) -> dict[str, Any]:
    plan_status = str(no_caption_plan.get("status") or "missing")
    matrix_row = matrix_entry(production_matrix, "offline_asr_route")
    matrix_passed = matrix_row_passed(matrix_row)
    state = "complete" if plan_status == "complete" or matrix_passed else "needs_real_no_caption_archive"
    expanded_commands = dedupe_commands(no_caption_plan.get("commands") or [])
    runner_command = sanitized_command(no_caption_plan.get("runnerCommand"))
    commands = [runner_command] if runner_command else expanded_commands
    pass_criteria = string_list(no_caption_plan.get("passCriteria"))
    required_reports = [
        "artifacts/evidence/no-caption-archive-preflight.json",
        "artifacts/evidence/no-caption-offline-chain-validation.json",
        "artifacts/evidence/asr-route-readiness.json",
    ]
    return {
        "id": "real_no_caption_asr_validation",
        "state": state,
        "dependsOn": depends_on,
        "handoffReport": display_path(args.no_caption_asr_plan),
        "requiredSource": "Authorized YouTube live archive without requested English captions.",
        "requiredModels": no_caption_plan.get("requiredModels")
        or {
            "offlineAsr": "gpt-4o-transcribe",
            "offlineTranslation": "gpt-5.4-mini",
            "forbiddenOfflineModel": "gpt-realtime-translate",
        },
        "commands": commands,
        "expandedCommands": expanded_commands if runner_command and expanded_commands else [],
        "currentEvidence": matrix_row_evidence(matrix_row),
        "requiredReports": required_reports,
        "passCriteria": pass_criteria
        or [
            "run_offline_archive_preflight.py reports decision=use_asr_fallback.",
            "Prepared offline report has caption_source.kind=openai_asr.",
            "ASR model is gpt-4o-transcribe.",
            "Chinese translation model is gpt-5.4-mini.",
            "validate_offline_chain.py status is ok and not_realtime_chain passes.",
        ],
        "nextAction": (
            "Run the no-caption ASR fallback plan against a real source, then feed "
            "artifacts/evidence/no-caption-offline-chain-validation.json into "
            "collect_production_evidence_matrix.py via --offline-asr-chain-validation-report."
        ),
    }


def final_readiness_audit_stage(
    args: argparse.Namespace,
    preflight: dict[str, Any],
    goal_audit: dict[str, Any],
    unblock: dict[str, Any],
    production_matrix: dict[str, Any],
    *,
    depends_on: list[str],
) -> dict[str, Any]:
    complete = final_readiness_complete(preflight, goal_audit, unblock, production_matrix)
    return {
        "id": "final_readiness_audit",
        "state": "complete" if complete else "pending_final_audit",
        "dependsOn": depends_on,
        "commands": [
            [
                "python3",
                "scripts/refresh_production_preflight_evidence.py",
                "--sunday",
                args.sunday,
                "--out",
                "artifacts/evidence/production-preflight-refresh.json",
            ],
            [
                "python3",
                "scripts/write_production_go_live_sequence.py",
                "--sunday",
                args.sunday,
                "--out",
                "artifacts/evidence/production-go-live-sequence.json",
            ],
        ],
        "requiredReports": [
            "artifacts/evidence/production-preflight-refresh.json",
            "artifacts/evidence/production-evidence-matrix.json",
            "artifacts/evidence/production-goal-readiness-audit.json",
            "artifacts/evidence/production-go-live-sequence.json",
        ],
    }


def required_model_recovery_needed(preflight: dict[str, Any], unblock: dict[str, Any]) -> bool:
    if "requiredModelAccess" in set(preflight.get("failedSteps") or []):
        return True
    for step in unblock.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if step.get("id") == "fix_required_gpt_5_4_mini_access":
            return True
        if step.get("dependency") == "model_access":
            return True
    return False


def unblock_step_for_source_row(unblock: dict[str, Any], source_row: str) -> dict[str, Any] | None:
    for step in unblock.get("steps") or []:
        if isinstance(step, dict) and step.get("sourceRow") == source_row:
            return step
    return None


def operator_choices_summary(live_plan: dict[str, Any]) -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    for choice in live_plan.get("operatorChoices") or []:
        if not isinstance(choice, dict):
            continue
        summary = {
            "id": choice.get("id"),
            "default": bool(choice.get("default")),
            "source": choice.get("source"),
            "path": choice.get("path"),
            "expectedAudioSourceKind": choice.get("expectedAudioSourceKind"),
            "expectedAudioSourceKinds": choice.get("expectedAudioSourceKinds"),
            "operatorAction": choice.get("operatorAction"),
        }
        evidence_reports = string_list(choice.get("evidenceReports"))
        if evidence_reports:
            summary["evidenceReports"] = evidence_reports
        command = sanitized_command(choice.get("command"))
        if command:
            summary["command"] = command
        choices.append(summary)
    return choices


def current_blockers(
    preflight: dict[str, Any],
    goal_audit: dict[str, Any],
    unblock: dict[str, Any],
    production_matrix: dict[str, Any],
    stages: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "failedPreflightSteps": list(preflight.get("failedSteps") or []),
        "incompletePreflightSteps": effective_incomplete_preflight_steps(
            preflight,
            goal_audit,
            unblock,
            production_matrix,
        ),
        "goalAuditFailedChecks": list(goal_audit.get("failedChecks") or []),
        "goalAuditExternalMissing": int((goal_audit.get("summary") or {}).get("externalMissing") or 0),
        "unblockPlanStatus": unblock.get("status") or "missing",
        "blockingStages": [
            stage["id"]
            for stage in stages
            if str(stage.get("state") or "").startswith(("approval_required", "blocked_", "needs_", "pending_"))
        ],
    }


def has_blockers(blockers: dict[str, Any]) -> bool:
    return any(
        [
            blockers.get("failedPreflightSteps"),
            blockers.get("incompletePreflightSteps"),
            blockers.get("goalAuditFailedChecks"),
            blockers.get("goalAuditExternalMissing"),
            blockers.get("unblockPlanStatus") not in {"complete", "missing"},
            blockers.get("blockingStages"),
        ]
    )


def final_readiness_complete(
    preflight: dict[str, Any],
    goal_audit: dict[str, Any],
    unblock: dict[str, Any],
    production_matrix: dict[str, Any],
) -> bool:
    if preflight.get("status") == "ok" and goal_audit.get("status") == "complete":
        return True
    return (
        production_matrix.get("status") == "complete"
        and goal_audit.get("status") == "complete"
        and unblock.get("status") == "complete"
    )


def effective_incomplete_preflight_steps(
    preflight: dict[str, Any],
    goal_audit: dict[str, Any],
    unblock: dict[str, Any],
    production_matrix: dict[str, Any],
) -> list[str]:
    incomplete = list(preflight.get("incompleteSteps") or [])
    complete_replacements = {
        "productionMatrix": production_matrix.get("status") == "complete",
        "goalAudit": goal_audit.get("status") == "complete",
        "productionUnblockPlan": unblock.get("status") == "complete",
    }
    return [step for step in incomplete if not complete_replacements.get(str(step), False)]


def matrix_entry(production_matrix: dict[str, Any], entry_id: str) -> dict[str, Any]:
    for entry in production_matrix.get("matrix") or []:
        if isinstance(entry, dict) and entry.get("id") == entry_id:
            return entry
    return {}


def matrix_row_passed(entry: dict[str, Any]) -> bool:
    return entry.get("state") == "pass" or entry.get("status") == "pass"


def matrix_row_evidence(entry: dict[str, Any]) -> dict[str, Any]:
    if not entry:
        return {}
    evidence = {
        "matrixRow": entry.get("id"),
        "state": entry.get("state") or entry.get("status"),
        "evidence": entry.get("evidence"),
    }
    observed = entry.get("observed")
    if isinstance(observed, dict):
        evidence["observedStatus"] = observed.get("status")
        evidence["models"] = observed.get("models")
        evidence["offlineChain"] = observed.get("offlineChain")
    return {key: value for key, value in evidence.items() if value is not None}


def read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def display_path(path: Path) -> str:
    if path.is_absolute():
        try:
            return path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return str(path)
    return path.as_posix()


def dedupe_commands(commands: list[Any]) -> list[list[str]]:
    seen: set[tuple[str, ...]] = set()
    result: list[list[str]] = []
    for command in commands:
        sanitized = sanitized_command(command)
        if not sanitized:
            continue
        key = tuple(sanitized)
        if key in seen:
            continue
        seen.add(key)
        result.append(sanitized)
    return result


def sanitized_command(command: Any) -> list[str] | None:
    if isinstance(command, list) and command and all(isinstance(part, str) for part in command):
        return command
    return None


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


if __name__ == "__main__":
    raise SystemExit(main())
