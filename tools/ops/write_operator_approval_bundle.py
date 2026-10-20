#!/usr/bin/env python3
"""Write a sanitized operator approval bundle for production unblock steps."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "artifacts" / "evidence" / "operator-approval-bundle.json"
DEFAULT_UNBLOCK_PLAN = REPO_ROOT / "artifacts" / "evidence" / "production-unblock-plan.json"
DEFAULT_CLOUD_RUN_UPDATE_PLAN = REPO_ROOT / "artifacts" / "evidence" / "cloud-run-realtime-update-plan.json"
DEFAULT_CLOUD_RUN_DRY_RUN = REPO_ROOT / "artifacts" / "evidence" / "cloud-run-realtime-update-execution-dry-run.json"
DEFAULT_GCS_PUBLISH_PLAN = REPO_ROOT / "artifacts" / "evidence" / "gcs-sunday-manifest-publish-plan.json"
DEFAULT_LIVE_1130_RUN_PLAN = REPO_ROOT / "artifacts" / "evidence" / "live-1130-realtime-run-plan.json"


def main() -> int:
    args = parse_args()
    report = build_bundle(args)
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"approval_required", "no_approval_steps"} else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sunday", required=True)
    parser.add_argument("--unblock-plan", type=Path, default=DEFAULT_UNBLOCK_PLAN)
    parser.add_argument("--cloud-run-update-plan", type=Path, default=DEFAULT_CLOUD_RUN_UPDATE_PLAN)
    parser.add_argument("--cloud-run-dry-run", type=Path, default=DEFAULT_CLOUD_RUN_DRY_RUN)
    parser.add_argument("--gcs-publish-plan", type=Path, default=DEFAULT_GCS_PUBLISH_PLAN)
    parser.add_argument("--live-1130-run-plan", type=Path, default=DEFAULT_LIVE_1130_RUN_PLAN)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def build_bundle(args: argparse.Namespace) -> dict[str, Any]:
    unblock = read_optional_json(resolve_repo_path(args.unblock_plan)) or {}
    cloud_plan = read_optional_json(resolve_repo_path(args.cloud_run_update_plan)) or {}
    cloud_dry_run = read_optional_json(resolve_repo_path(args.cloud_run_dry_run)) or {}
    gcs_plan = read_optional_json(resolve_repo_path(args.gcs_publish_plan)) or {}
    live_1130_plan = read_optional_json(resolve_repo_path(args.live_1130_run_plan)) or {}
    approval_steps = [step for step in unblock.get("steps") or [] if isinstance(step, dict) and step.get("requiresApproval")]
    followup_steps = [step for step in unblock.get("steps") or [] if isinstance(step, dict) and not step.get("requiresApproval")]
    post_cloud_run_validation_commands = cloud_run_followup_validation_commands(unblock)
    approval_summaries = [
        approval_step_summary(step, cloud_plan=cloud_plan, cloud_dry_run=cloud_dry_run, gcs_plan=gcs_plan)
        if step.get("id") != "apply_cloud_run_realtime_config"
        else approval_step_summary(
            step,
            cloud_plan=cloud_plan,
            cloud_dry_run=cloud_dry_run,
            gcs_plan=gcs_plan,
            post_validation_commands=post_cloud_run_validation_commands,
        )
        for step in approval_steps
    ]
    followup_summaries = [followup_step_summary(step) for step in followup_steps]
    return {
        "schemaVersion": 1,
        "status": "approval_required" if approval_steps else "no_approval_steps",
        "sunday": args.sunday,
        "approvalStepCount": len(approval_steps),
        "requiredApprovals": required_approvals_summary(approval_summaries),
        "approvalSteps": approval_summaries,
        "postApprovalFollowupSteps": followup_summaries,
        "postApprovalValidation": post_approval_validation_summary(approval_summaries, followup_summaries),
        "rollback": rollback_summary(approval_summaries),
        "live1130Runbook": live_1130_runbook_summary(live_1130_plan),
        "guards": {
            "requiresExplicitOperatorApproval": bool(approval_steps),
            "doesNotApplyCloudRun": True,
            "doesNotUploadGcs": True,
            "cloudRunApplyRequiresApproveFlag": True,
            "gcsPublishRequiresApplyFlag": True,
            "gcsProductionStableRequiresConfirmFlag": True,
        },
        "postApprovalEvidence": [
            "artifacts/evidence/cloud-run-realtime-config.json",
            "artifacts/evidence/cloud-run-api-preflight.json",
            "artifacts/evidence/web-realtime-contract.json",
            "artifacts/evidence/realtime-public-sse-smoke.json",
            "artifacts/evidence/realtime-public-sse-smoke.session-validation.json",
            "artifacts/evidence/sunday-manifest-validation.json",
            "artifacts/evidence/production-evidence-matrix.json",
            "artifacts/evidence/production-goal-readiness-audit.json",
        ],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def required_approvals_summary(approval_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": step.get("id"),
            "state": step.get("state"),
            "approvalKind": step.get("approvalKind"),
            "reason": step.get("reason"),
            "requiresExplicitApproval": step.get("requiresExplicitApproval") is True,
        }
        for step in approval_steps
    ]


def post_approval_validation_summary(
    approval_steps: list[dict[str, Any]],
    followup_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    validation_commands: list[Any] = []
    expected_checks: list[str] = []
    for step in approval_steps:
        validation_commands.extend(step.get("validationCommands") or [])
        expected_checks.extend(string_list(step.get("expectedValidationChecks")))
    for step in followup_steps:
        validation_commands.extend(step.get("commands") or [])
        expected_checks.extend(string_list(step.get("expectedChecks")))
    return {
        "commands": dedupe_commands(validation_commands),
        "expectedChecks": sorted(set(expected_checks)),
        "requiredEvidence": [
            "artifacts/evidence/cloud-run-realtime-config.json",
            "artifacts/evidence/cloud-run-api-preflight.json",
            "artifacts/evidence/realtime-public-sse-smoke.json",
            "artifacts/evidence/realtime-public-sse-smoke.session-validation.json",
            "artifacts/evidence/sunday-manifest-validation.json",
            "artifacts/evidence/production-evidence-matrix.json",
            "artifacts/evidence/production-goal-readiness-audit.json",
        ],
    }


def rollback_summary(approval_steps: list[dict[str, Any]]) -> dict[str, Any]:
    commands = [
        step.get("rollbackCommand")
        for step in approval_steps
        if isinstance(step.get("rollbackCommand"), list)
    ]
    return {
        "available": bool(commands),
        "commands": dedupe_commands(commands),
        "requiresExplicitApproval": bool(commands),
    }


def approval_step_summary(
    step: dict[str, Any],
    *,
    cloud_plan: dict[str, Any],
    cloud_dry_run: dict[str, Any],
    gcs_plan: dict[str, Any],
    post_validation_commands: list[list[str]] | None = None,
) -> dict[str, Any]:
    step_id = str(step.get("id") or "")
    if step_id == "apply_cloud_run_realtime_config":
        return {
            "id": step_id,
            "state": step.get("state"),
            "reason": step.get("reason"),
            "approvalKind": "cloud_run_runtime_update",
            "plannedChanges": cloud_plan.get("plannedChanges") or [],
            "applyCommand": cloud_dry_run.get("wouldApply"),
            "rollbackCommand": cloud_dry_run.get("wouldRollback"),
            "validationCommands": dedupe_commands(
                [
                    *(cloud_dry_run.get("wouldValidate") or step.get("commands") or []),
                    *(post_validation_commands or []),
                ]
            ),
            "expectedValidationChecks": [
                "realtime_local_session_create",
                "realtime_local_session_metadata",
                "no_secret_material_in_http_responses",
                "browser_normalized_event_payloads",
                "sse_stable_correction_matches_draft_segment",
                "session_jsonl_validation",
            ],
            "requiresExplicitApproval": True,
            "secretReferencesIncluded": bool(cloud_plan.get("secretReferencesIncluded")),
            "secretResourceNamesIncluded": False,
        }
    if step_id == "publish_sunday_manifest_to_gcs":
        return {
            "id": step_id,
            "state": step.get("state"),
            "reason": step.get("reason"),
            "approvalKind": "gcs_manifest_publish",
            "stableManifestUri": gcs_plan.get("stableManifestUri") or step.get("stableManifestUri"),
            "runManifestUri": gcs_plan.get("runManifestUri"),
            "artifactCount": step.get("artifactCount") or len(gcs_plan.get("artifacts") or []),
            "approvalCommands": step.get("commands") or [],
            "commands": gcs_plan.get("commands") or step.get("commands") or [],
            "localValidation": gcs_plan.get("localValidation"),
            "gcsManifestValidation": gcs_plan.get("gcsManifestValidation"),
            "productionStableConfirmRequired": gcs_production_confirm_required(step),
            "requiresExplicitApproval": True,
            "secretResourceNamesIncluded": False,
        }
    return {
        "id": step_id,
        "state": step.get("state"),
        "reason": step.get("reason"),
        "approvalKind": "operator_approval",
        "commands": step.get("commands") or [],
        "requiresExplicitApproval": True,
        "secretResourceNamesIncluded": False,
    }


def gcs_production_confirm_required(step: dict[str, Any]) -> bool:
    for command in step.get("commands") or []:
        if isinstance(command, list) and "--confirm-production-stable" in command:
            return True
    return False


def cloud_run_followup_validation_commands(unblock: dict[str, Any]) -> list[list[str]]:
    source_rows = {"cloud_run_api_preflight", "realtime_public_sse_contract"}
    commands: list[list[str]] = []
    for step in unblock.get("steps") or []:
        if not isinstance(step, dict) or step.get("sourceRow") not in source_rows:
            continue
        for command in step.get("commands") or []:
            if isinstance(command, list) and all(isinstance(part, str) for part in command):
                commands.append(command)
    return commands


def followup_step_summary(step: dict[str, Any]) -> dict[str, Any]:
    plan_report = str(step.get("planReport") or "")
    plan = read_optional_json(resolve_repo_path(Path(plan_report))) if plan_report else None
    plan_commands = plan.get("commands") if isinstance(plan, dict) and isinstance(plan.get("commands"), list) else []
    runner_command = plan.get("runnerCommand") if isinstance(plan, dict) and isinstance(plan.get("runnerCommand"), list) else None
    summary = {
        "id": step.get("id"),
        "state": step.get("state"),
        "dependency": step.get("dependency"),
        "sourceRow": step.get("sourceRow"),
        "reason": step.get("reason"),
        "commands": step.get("commands") or ([runner_command] if runner_command else plan_commands),
        "expectedChecks": step.get("expectedChecks") or [],
        "planReport": plan_report or None,
        "planStatus": plan.get("status") if isinstance(plan, dict) else None,
        "requiresExplicitApproval": False,
    }
    if runner_command and plan_commands:
        summary["expandedCommands"] = plan_commands
    return summary


def live_1130_runbook_summary(plan: dict[str, Any]) -> dict[str, Any] | None:
    if not plan:
        return None
    operator_choices = []
    for choice in plan.get("operatorChoices") or []:
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
        operator_choices.append(summary)
    return {
        "status": plan.get("status"),
        "sunday": plan.get("sunday"),
        "targetWindow": plan.get("targetWindow"),
        "defaultPath": next((choice.get("path") for choice in operator_choices if choice.get("default")), None),
        "operatorChoices": operator_choices,
        "modelPolicy": plan.get("modelPolicy"),
        "liveValidationCommands": dedupe_commands(plan.get("liveValidationCommands") or []),
        "stabilizerFallbackCommand": plan.get("stabilizerFallbackCommand")
        if isinstance(plan.get("stabilizerFallbackCommand"), list)
        and all(isinstance(part, str) for part in plan.get("stabilizerFallbackCommand") or [])
        else None,
        "passCriteria": plan.get("passCriteria") or [],
        "postLiveOfflineHandoff": plan.get("postLiveOfflineHandoff"),
        "guards": plan.get("guards"),
    }


def dedupe_commands(commands: list[Any]) -> list[list[str]]:
    seen: set[tuple[str, ...]] = set()
    result: list[list[str]] = []
    for command in commands:
        if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
            continue
        key = tuple(command)
        if key in seen:
            continue
        seen.add(key)
        result.append(command)
    return result


def sanitized_command(command: Any) -> list[str] | None:
    if isinstance(command, list) and command and all(isinstance(part, str) for part in command):
        return command
    return None


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
