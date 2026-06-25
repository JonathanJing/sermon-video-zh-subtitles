#!/usr/bin/env python3
"""Write an operator-facing unblock plan from the production evidence matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "artifacts" / "evidence" / "production-unblock-plan.json"
DEFAULT_CLOUD_RUN_UPDATE_PLAN = REPO_ROOT / "artifacts" / "evidence" / "cloud-run-realtime-update-plan.json"
DEFAULT_NO_CAPTION_ASR_PLAN = "artifacts/evidence/no-caption-asr-fallback-plan.json"
DEFAULT_MODEL_ACCESS_RECOVERY_PLAN = "artifacts/evidence/model-access-recovery-plan.json"
DEFAULT_OPERATOR_APPROVAL_BUNDLE = "artifacts/evidence/operator-approval-bundle.json"
DEFAULT_CLOUD_RUN_BASE_URL = "https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app"
DEFAULT_REALTIME_EVENT_GCS_PREFIX = "gs://sermon-zh-artifacts-ai-for-god/realtime-events"
DEFAULT_WEB_REALTIME_CONTRACT_REPORT = "artifacts/evidence/web-realtime-contract.json"
DEFAULT_SUNDAY = "2026-06-28"


def main() -> int:
    args = parse_args()
    matrix = read_json(resolve_repo_path(args.evidence_matrix))
    publish_plan = read_optional_json(resolve_repo_path(args.gcs_manifest_publish_plan) if args.gcs_manifest_publish_plan else None)
    report = build_unblock_plan(
        matrix=matrix,
        publish_plan=publish_plan,
        cloud_run_update_plan=command_path(args.cloud_run_update_plan),
    )
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"ready_for_approval", "blocked_by_external_dependency", "complete"} else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-matrix",
        type=Path,
        default=REPO_ROOT / "artifacts" / "evidence" / "production-evidence-matrix.json",
    )
    parser.add_argument(
        "--gcs-manifest-publish-plan",
        type=Path,
        default=REPO_ROOT / "artifacts" / "evidence" / "gcs-sunday-manifest-publish-plan.json",
    )
    parser.add_argument(
        "--cloud-run-update-plan",
        type=Path,
        default=DEFAULT_CLOUD_RUN_UPDATE_PLAN,
        help="Approved plan file consumed by apply_cloud_run_realtime_update_plan.py.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def build_unblock_plan(
    *,
    matrix: dict[str, Any],
    publish_plan: dict[str, Any] | None,
    cloud_run_update_plan: str = "artifacts/evidence/cloud-run-realtime-update-plan.json",
) -> dict[str, Any]:
    rows = {str(row.get("id")): row for row in matrix.get("matrix") or [] if isinstance(row, dict)}
    steps: list[dict[str, Any]] = []

    add_cloud_run_config_step(steps, rows.get("cloud_run_realtime_config"), cloud_run_update_plan)
    add_gcs_publish_step(steps, rows.get("cloud_run_gcs_manifest"), publish_plan)
    add_model_access_step(steps, rows.get("stable_correction"), rows.get("offline_caption_route"))
    add_cloud_run_api_step(steps, rows.get("cloud_run_api_preflight"))
    add_public_sse_step(steps, rows.get("realtime_public_sse_contract"))
    add_realtime_field_run_step(steps, rows.get("realtime_live"))
    add_offline_caption_step(steps, rows.get("offline_caption_route"))
    add_stable_correction_step(steps, rows.get("stable_correction"))
    add_asr_archive_step(steps, rows.get("offline_asr_route"))

    status = status_from_steps(steps, matrix.get("status"))
    return {
        "schemaVersion": 1,
        "status": status,
        "matrixStatus": matrix.get("status"),
        "matrixSummary": matrix.get("summary"),
        "steps": steps,
        "requiresApproval": any(step.get("requiresApproval") for step in steps),
        "operatorApprovalBundle": DEFAULT_OPERATOR_APPROVAL_BUNDLE if any(step.get("requiresApproval") for step in steps) else None,
        "externalDependencyCount": sum(1 for step in steps if step.get("dependency") == "external"),
        "approvalStepCount": sum(1 for step in steps if step.get("requiresApproval")),
        "modelPolicy": {
            "requiredStableAndOfflineModel": "gpt-5.5-mini",
            "observedAlternativeModelsAreNotSubstitutes": True,
            "note": "A green gpt-5.5 preflight is side evidence only; do not satisfy gpt-5.5-mini gates with it.",
        },
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def add_cloud_run_config_step(steps: list[dict[str, Any]], row: dict[str, Any] | None, update_plan: str) -> None:
    if not row or row.get("state") == "pass":
        return
    steps.append(
        {
            "id": "apply_cloud_run_realtime_config",
            "sourceRow": "cloud_run_realtime_config",
            "state": "approval_required",
            "requiresApproval": True,
            "dependency": "operator_approval",
            "reason": row.get("nextAction"),
            "commands": [
                [
                    "python3",
                    "scripts/apply_cloud_run_realtime_update_plan.py",
                    "--plan",
                    update_plan,
                    "--approve",
                    "--rollback-on-failure",
                    "--out",
                    "artifacts/evidence/cloud-run-realtime-update-execution.json",
                ],
                [
                    "python3",
                    "scripts/validate_cloud_run_realtime_config.py",
                    "--out",
                    "artifacts/evidence/cloud-run-realtime-config.json",
                ],
            ],
        }
    )


def add_gcs_publish_step(steps: list[dict[str, Any]], row: dict[str, Any] | None, publish_plan: dict[str, Any] | None) -> None:
    if not row or row.get("state") == "pass":
        return
    commands = []
    if publish_plan and publish_plan.get("status") == "planned":
        commands.append(
            [
                "python3",
                "scripts/plan_gcs_sunday_manifest_publish.py",
                "--sunday",
                str(publish_plan.get("sunday")),
                "--local-root",
                str(publish_plan.get("localRoot")),
                "--bucket",
                str(publish_plan.get("bucket")),
                "--prefix",
                str(publish_plan.get("prefix")),
                "--session-id",
                str(publish_plan.get("sessionId")),
                "--apply",
                "--out",
                "artifacts/evidence/gcs-sunday-manifest-publish-plan.json",
            ]
        )
        stable_uri = str(publish_plan.get("stableManifestUri"))
    else:
        stable_uri = "gs://<bucket>/<prefix>/<sunday>/cloud-manifest.json"
    commands.append(
        [
            "python3",
            "scripts/validate_sunday_manifest.py",
            "--manifest",
            stable_uri,
            "--sunday",
            str((publish_plan or {}).get("sunday") or "<YYYY-MM-DD>"),
            "--require-readable-artifacts",
            "--out",
            "artifacts/evidence/sunday-manifest-validation.json",
        ]
    )
    steps.append(
        {
            "id": "publish_sunday_manifest_to_gcs",
            "sourceRow": "cloud_run_gcs_manifest",
            "state": "approval_required" if publish_plan and publish_plan.get("status") == "planned" else "needs_plan",
            "requiresApproval": bool(publish_plan and publish_plan.get("status") == "planned"),
            "dependency": "operator_approval" if publish_plan and publish_plan.get("status") == "planned" else "local_plan",
            "reason": row.get("nextAction"),
            "stableManifestUri": stable_uri,
            "artifactCount": len((publish_plan or {}).get("artifacts") or []),
            "commands": commands,
        }
    )


def add_model_access_step(
    steps: list[dict[str, Any]],
    stable_row: dict[str, Any] | None,
    offline_caption_row: dict[str, Any] | None,
) -> None:
    model_failure = first_model_failure(stable_row, offline_caption_row)
    if not model_failure:
        return
    steps.append(
        {
            "id": "fix_required_gpt_5_5_mini_access",
            "sourceRows": ["stable_correction", "offline_caption_route"],
            "state": "external_dependency",
            "requiresApproval": False,
            "dependency": "external",
            "model": "gpt-5.5-mini",
            "failureKind": model_failure.get("failureKind"),
            "httpStatus": model_failure.get("httpStatus"),
            "error": model_failure.get("error"),
            "availableButNotConfiguredModels": model_failure.get("availableButNotConfiguredModels") or [],
            "doNotSubstitute": True,
            "recoveryPlan": DEFAULT_MODEL_ACCESS_RECOVERY_PLAN,
            "commandsAfterAccessIsFixed": [
                [
                    "python3",
                    "scripts/run_openai_model_access_preflight.py",
                    "--model",
                    "gpt-5.5-mini",
                    "--out",
                    "artifacts/evidence/openai-model-access-preflight.json",
                ]
            ],
        }
    )


def add_cloud_run_api_step(steps: list[dict[str, Any]], row: dict[str, Any] | None) -> None:
    if row and row.get("state") != "pass":
        step = simple_rerun_step("rerun_cloud_run_api_preflight", "cloud_run_api_preflight", row)
        step["commands"] = [
            [
                "python3",
                "scripts/run_cloud_run_realtime_preflight.py",
                "--base-url",
                DEFAULT_CLOUD_RUN_BASE_URL,
                "--cloud-run-config-report",
                "artifacts/evidence/cloud-run-realtime-config.json",
                "--create-realtime-session",
                "--internal-task-token",
                "$INTERNAL_TASK_TOKEN",
                "--out",
                "artifacts/evidence/cloud-run-api-preflight.json",
            ]
        ]
        step["expectedChecks"] = [
            "realtime_local_session_create",
            "realtime_local_session_metadata",
            "no_secret_material_in_http_responses",
        ]
        steps.append(step)


def add_public_sse_step(steps: list[dict[str, Any]], row: dict[str, Any] | None) -> None:
    if row and row.get("state") != "pass":
        step = simple_rerun_step("rerun_deployed_public_sse_smoke", "realtime_public_sse_contract", row)
        step["commands"] = [
            [
                "python3",
                "scripts/run_realtime_public_sse_smoke.py",
                "--base-url",
                DEFAULT_CLOUD_RUN_BASE_URL,
                "--sunday",
                DEFAULT_SUNDAY,
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
            ]
        ]
        step["expectedChecks"] = [
            "create_local_session_metadata",
            "sse_session_metadata",
            "browser_normalized_event_payloads",
            "sse_stable_correction_matches_draft_segment",
            "session_jsonl_validation",
        ]
        steps.append(step)


def add_realtime_field_run_step(steps: list[dict[str, Any]], row: dict[str, Any] | None) -> None:
    if row and row.get("state") != "pass":
        step = simple_rerun_step(
            "run_real_realtime_field_session",
            "realtime_live",
            row,
            dependency="post_approval_validation",
        )
        step["defaultPath"] = "browser WebRTC iPad/iPhone mic -> gpt-realtime-translate -> backend session events -> public caption SSE"
        step["fallbackPath"] = "server media worker authorized audio -> gpt-realtime-translate -> backend session events -> public caption SSE"
        step["commands"] = [
            [
                "python3",
                "scripts/run_realtime_live_session.py",
                "--audio-url",
                "<AUTHORIZED_AUDIO_URL>",
                "--api-key-secret",
                "<OPENAI_API_KEY_SECRET_RESOURCE>",
                "--backend-url",
                DEFAULT_CLOUD_RUN_BASE_URL,
                "--sunday",
                DEFAULT_SUNDAY,
                "--internal-task-token",
                "$INTERNAL_TASK_TOKEN",
                "--target-language",
                "zh",
                "--realtime-model",
                "gpt-realtime-translate",
                "--stable-model",
                "gpt-5.5-mini",
                "--realtime-event-gcs-prefix",
                DEFAULT_REALTIME_EVENT_GCS_PREFIX,
                "--require-stable-correction",
                "--out",
                "artifacts/evidence/realtime-live-session/report.json",
                "--worker-report-out",
                "artifacts/evidence/realtime-live-session/worker-report.json",
                "--stable-out-dir",
                "artifacts/evidence/realtime-live-session/stable-corrections",
            ],
            [
                "python3",
                "scripts/validate_realtime_session.py",
                "--events-jsonl",
                f"{DEFAULT_REALTIME_EVENT_GCS_PREFIX}/{DEFAULT_SUNDAY}/<REALTIME_SESSION_ID>.jsonl",
                "--expected-model",
                "gpt-realtime-translate",
                "--expected-stable-model",
                "gpt-5.5-mini",
                "--require-stable-correction",
                "--out",
                "artifacts/evidence/realtime-live-session/session-validation.json",
            ],
        ]
        step["expectedChecks"] = [
            "realtime_model",
            "caption_events",
            "input_transcript_events",
            "stable_correction",
            "stable_correction_matches_realtime_draft_segment",
            "stable_correction_context",
        ]
        steps.append(step)


def add_offline_caption_step(steps: list[dict[str, Any]], row: dict[str, Any] | None) -> None:
    if row and row.get("state") != "pass":
        steps.append(simple_rerun_step("rerun_offline_caption_route_after_model_access", "offline_caption_route", row, dependency="model_access"))


def add_stable_correction_step(steps: list[dict[str, Any]], row: dict[str, Any] | None) -> None:
    if not row or row.get("state") == "pass":
        return
    if row_has_model_access_failure(row):
        steps.append(
            simple_rerun_step(
                "rerun_stable_correction_after_model_access",
                "stable_correction",
                row,
                dependency="model_access",
            )
        )
        return
    step = simple_rerun_step(
        "validate_deployed_stable_correction_session",
        "stable_correction",
        row,
        dependency="prior_step",
    )
    step["commands"] = [
        [
            "python3",
            "scripts/validate_realtime_session.py",
            "--events-jsonl",
            f"{DEFAULT_REALTIME_EVENT_GCS_PREFIX}/{DEFAULT_SUNDAY}/<REALTIME_SESSION_ID>.jsonl",
            "--expected-model",
            "gpt-realtime-translate",
            "--expected-stable-model",
            "gpt-5.5-mini",
            "--require-stable-correction",
            "--out",
            "artifacts/evidence/realtime-live-session/session-validation.json",
        ]
    ]
    step["expectedChecks"] = [
        "stable_correction",
        "stable_correction_matches_realtime_draft_segment",
        "stable_correction_context",
    ]
    steps.append(step)


def add_asr_archive_step(steps: list[dict[str, Any]], row: dict[str, Any] | None) -> None:
    if row and row.get("state") != "pass":
        step = simple_rerun_step(
            "run_real_no_caption_archive_asr_route",
            "offline_asr_route",
            row,
            dependency="real_source",
        )
        step["planReport"] = DEFAULT_NO_CAPTION_ASR_PLAN
        step["expectedChecks"] = [
            "asr_is_caption_fallback",
            "asr_no_requested_caption_tracks",
            "asr_audio_source_artifact",
            "asr_model",
            "offline_translation_model",
            "not_realtime_chain",
            "zh_vtt_timeline_alignment",
            "zh_srt_timeline_alignment",
        ]
        steps.append(step)


def simple_rerun_step(step_id: str, source_row: str, row: dict[str, Any], dependency: str = "prior_step") -> dict[str, Any]:
    return {
        "id": step_id,
        "sourceRow": source_row,
        "state": "pending",
        "requiresApproval": False,
        "dependency": dependency,
        "reason": row.get("nextAction"),
    }


def first_model_failure(*rows: dict[str, Any] | None) -> dict[str, Any] | None:
    for row in rows:
        observed = row.get("observed") if row else None
        if not isinstance(observed, dict):
            continue
        if observed.get("model") == "gpt-5.5-mini" and observed.get("failureKind"):
            return observed
    return None


def row_has_model_access_failure(row: dict[str, Any]) -> bool:
    observed = row.get("observed")
    if not isinstance(observed, dict):
        return False
    return observed.get("model") == "gpt-5.5-mini" and bool(observed.get("failureKind"))


def status_from_steps(steps: list[dict[str, Any]], matrix_status: str | None) -> str:
    if matrix_status == "complete" and not steps:
        return "complete"
    if any(step.get("requiresApproval") for step in steps):
        return "ready_for_approval"
    if any(step.get("dependency") == "external" for step in steps):
        return "blocked_by_external_dependency"
    return "needs_local_followup"


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"JSON report must be an object: {path}")
    return data


def read_optional_json(path: Path | None) -> dict[str, Any] | None:
    if not path or not path.exists():
        return None
    return read_json(path)


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def command_path(path: Path) -> str:
    if path.is_absolute():
        try:
            return path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return str(path)
    return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
