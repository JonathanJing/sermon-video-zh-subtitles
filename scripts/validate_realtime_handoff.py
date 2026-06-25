#!/usr/bin/env python3
"""Validate realtime/offline production handoff reports."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIVE_PLAN = REPO_ROOT / "artifacts" / "evidence" / "live-1130-realtime-run-plan.json"
DEFAULT_OPERATOR_BUNDLE = REPO_ROOT / "artifacts" / "evidence" / "operator-approval-bundle.json"
DEFAULT_GO_LIVE_SEQUENCE = REPO_ROOT / "artifacts" / "evidence" / "production-go-live-sequence.json"

EXPECTED_BROWSER_EVIDENCE = {
    "artifacts/evidence/web-realtime-contract.json",
    "artifacts/evidence/public-caption-view-runtime.json",
    "artifacts/evidence/realtime-public-sse-smoke.json",
    "artifacts/evidence/realtime-public-sse-smoke.session-validation.json",
}
EXPECTED_MODELS = {
    "realtimeDraftModel": "gpt-realtime-translate",
    "stableCorrectionModel": "gpt-5.5-mini",
    "offlineAsrModel": "gpt-4o-transcribe",
    "offlineTranslationModel": "gpt-5.5-mini",
    "forbiddenOfflineModel": "gpt-realtime-translate",
}


def main() -> int:
    args = parse_args()
    report = validate_handoff(args)
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-plan", type=Path, default=DEFAULT_LIVE_PLAN)
    parser.add_argument("--operator-bundle", type=Path, default=DEFAULT_OPERATOR_BUNDLE)
    parser.add_argument("--go-live-sequence", type=Path, default=DEFAULT_GO_LIVE_SEQUENCE)
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def validate_handoff(args: argparse.Namespace) -> dict[str, Any]:
    live_plan = read_json(resolve_repo_path(args.live_plan))
    operator_bundle = read_json(resolve_repo_path(args.operator_bundle))
    go_live_sequence = read_json(resolve_repo_path(args.go_live_sequence))
    checks: list[dict[str, Any]] = []

    add_check(checks, "live_plan_ready", live_plan.get("status") == "ready_for_operator_review", live_plan.get("status"))
    add_model_policy_check(checks, "live_plan_model_policy", live_plan.get("modelPolicy"))
    add_operator_choices_check(checks, "live_plan_operator_choices", live_plan.get("operatorChoices"))
    add_live_validation_commands_check(checks, "live_plan_validation_commands", live_plan.get("liveValidationCommands"))
    add_offline_handoff_check(checks, "live_plan_offline_handoff", live_plan.get("postLiveOfflineHandoff"), live_plan.get("passCriteria"))
    add_clean_report_check(checks, "live_plan_secret_flags", live_plan)

    runbook = operator_bundle.get("live1130Runbook") if isinstance(operator_bundle.get("live1130Runbook"), dict) else {}
    add_check(checks, "operator_bundle_status", operator_bundle.get("status") in {"approval_required", "no_approval_steps"}, operator_bundle.get("status"))
    add_model_policy_check(checks, "operator_runbook_model_policy", runbook.get("modelPolicy"))
    add_operator_choices_check(checks, "operator_runbook_operator_choices", runbook.get("operatorChoices"))
    add_live_validation_commands_check(checks, "operator_runbook_validation_commands", runbook.get("liveValidationCommands"))
    add_offline_handoff_check(checks, "operator_runbook_offline_handoff", runbook.get("postLiveOfflineHandoff"), runbook.get("passCriteria"))
    add_clean_report_check(checks, "operator_bundle_secret_flags", operator_bundle)

    live_stage = live_stage_from_sequence(go_live_sequence)
    asr_stage = asr_stage_from_sequence(go_live_sequence)
    add_check(checks, "go_live_sequence_status", go_live_sequence.get("status") in {"ready_for_go_live", "not_ready_for_go_live"}, go_live_sequence.get("status"))
    add_model_policy_check(checks, "go_live_live_stage_model_policy", live_stage.get("modelPolicy") if live_stage else None)
    add_operator_choices_check(checks, "go_live_live_stage_operator_choices", live_stage.get("operatorChoices") if live_stage else None)
    add_live_validation_commands_check(checks, "go_live_live_stage_validation_commands", live_stage.get("liveValidationCommands") if live_stage else None)
    add_no_caption_asr_stage_check(checks, "go_live_no_caption_asr_stage", asr_stage)
    add_clean_report_check(checks, "go_live_sequence_secret_flags", go_live_sequence)

    serialized = json.dumps(
        {
            "livePlan": live_plan,
            "operatorBundle": operator_bundle,
            "goLiveSequence": go_live_sequence,
        },
        ensure_ascii=False,
    )
    add_check(
        checks,
        "no_secret_material",
        not contains_secret_material(serialized),
        None,
    )

    failed = [check["name"] for check in checks if check["state"] != "pass"]
    return {
        "schemaVersion": 1,
        "status": "ok" if not failed else "failed",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "failedChecks": failed,
        "reports": {
            "livePlan": display_path(resolve_repo_path(args.live_plan)),
            "operatorBundle": display_path(resolve_repo_path(args.operator_bundle)),
            "goLiveSequence": display_path(resolve_repo_path(args.go_live_sequence)),
        },
        "requiredEvidenceReports": sorted(EXPECTED_BROWSER_EVIDENCE),
        "models": EXPECTED_MODELS,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def add_model_policy_check(checks: list[dict[str, Any]], name: str, policy: Any) -> None:
    observed = policy if isinstance(policy, dict) else {}
    missing_or_wrong = {
        key: observed.get(key)
        for key, expected in EXPECTED_MODELS.items()
        if observed.get(key) != expected
    }
    add_check(checks, name, not missing_or_wrong, {"missingOrWrong": missing_or_wrong, "observed": observed})


def add_operator_choices_check(checks: list[dict[str, Any]], name: str, choices: Any) -> None:
    choice_list = choices if isinstance(choices, list) else []
    by_id = {choice.get("id"): choice for choice in choice_list if isinstance(choice, dict)}
    browser = by_id.get("browser_webrtc_ipad_or_iphone_mic") or {}
    server = by_id.get("server_worker_authorized_audio") or {}
    browser_evidence = set(item for item in browser.get("evidenceReports") or [] if isinstance(item, str))
    server_command = server.get("command") if isinstance(server.get("command"), list) else []
    observed = {
        "choiceIds": sorted(by_id),
        "browserDefault": bool(browser.get("default")),
        "browserAudioSourceKind": browser.get("expectedAudioSourceKind"),
        "browserEvidenceMissing": sorted(EXPECTED_BROWSER_EVIDENCE - browser_evidence),
        "serverCommand": server_command,
    }
    ok = (
        bool(browser)
        and bool(server)
        and browser.get("default") is True
        and browser.get("expectedAudioSourceKind") == "ipad_mic"
        and not observed["browserEvidenceMissing"]
        and "scripts/run_realtime_live_session.py" in server_command
        and "gpt-realtime-translate" in server_command
        and "gpt-5.5-mini" in server_command
    )
    add_check(checks, name, ok, observed)


def add_live_validation_commands_check(checks: list[dict[str, Any]], name: str, commands: Any) -> None:
    command_text = json.dumps(commands if isinstance(commands, list) else [], ensure_ascii=False)
    observed = {
        "hasSseSmoke": "scripts/run_realtime_public_sse_smoke.py" in command_text,
        "hasWebContractReport": "--web-realtime-contract-report" in command_text,
        "hasSessionValidator": "scripts/validate_realtime_session.py" in command_text,
        "hasRealtimeModel": "gpt-realtime-translate" in command_text,
        "hasStableModel": "gpt-5.5-mini" in command_text,
        "requiresStableCorrection": "--require-stable-correction" in command_text,
    }
    add_check(checks, name, all(observed.values()), observed)


def add_offline_handoff_check(checks: list[dict[str, Any]], name: str, handoff: Any, pass_criteria: Any) -> None:
    text = json.dumps({"handoff": handoff, "passCriteria": pass_criteria}, ensure_ascii=False)
    observed = {
        "archiveTrigger": "YouTube live archive" in text,
        "captionFirst": "captions/VTT" in text or "captions" in text,
        "asrModel": "gpt-4o-transcribe" in text,
        "translationModel": "gpt-5.5-mini" in text,
        "forbidsRealtimeOffline": "Offline post-live route never uses gpt-realtime-translate." in text,
        "exportsSubtitleArtifacts": "VTT/SRT/playback JS/GCS manifest" in text or "VTT/SRT" in text,
    }
    add_check(checks, name, all(observed.values()), observed)


def add_no_caption_asr_stage_check(checks: list[dict[str, Any]], name: str, stage: Any) -> None:
    stage_obj = stage if isinstance(stage, dict) else {}
    command_text = json.dumps(stage_obj.get("commands") if isinstance(stage_obj.get("commands"), list) else [], ensure_ascii=False)
    report_paths = set(item for item in stage_obj.get("requiredReports") or [] if isinstance(item, str))
    pass_criteria_text = "\n".join(str(item) for item in stage_obj.get("passCriteria") or [])
    required_models = stage_obj.get("requiredModels") if isinstance(stage_obj.get("requiredModels"), dict) else {}
    observed = {
        "state": stage_obj.get("state"),
        "hasArchivePreflight": "scripts/run_offline_archive_preflight.py" in command_text,
        "hasPreparePlayback": "scripts/prepare_live_link_playback.py" in command_text,
        "hasTranslate": "scripts/translate_playback_with_openai.py" in command_text,
        "hasExport": "scripts/export_playback_captions.py" in command_text,
        "hasOfflineChainValidation": "scripts/validate_offline_chain.py" in command_text,
        "hasProductionReadinessValidation": "scripts/validate_production_readiness.py" in command_text,
        "hasAsrModel": "gpt-4o-transcribe" in command_text and required_models.get("offlineAsr") == "gpt-4o-transcribe",
        "hasTranslationModel": "gpt-5.5-mini" in command_text and required_models.get("offlineTranslation") == "gpt-5.5-mini",
        "forbidsRealtimeOffline": required_models.get("forbiddenOfflineModel") == "gpt-realtime-translate",
        "hasOfflineAsrChainReport": "artifacts/evidence/no-caption-offline-chain-validation.json" in report_paths,
        "hasArchivePreflightReport": "artifacts/evidence/no-caption-archive-preflight.json" in report_paths,
        "hasAsrReadinessReport": "artifacts/evidence/asr-route-readiness.json" in report_paths,
        "hasMatrixHandoffInstruction": "--offline-asr-chain-validation-report" in str(stage_obj.get("nextAction") or ""),
        "criteriaRequireOpenaiAsr": "caption_source.kind=openai_asr" in pass_criteria_text,
        "criteriaRequireNotRealtime": "not_realtime_chain" in pass_criteria_text,
    }
    add_check(checks, name, all(observed.values()), observed)


def add_clean_report_check(checks: list[dict[str, Any]], name: str, report: dict[str, Any]) -> None:
    observed = {
        "apiKeyMaterialIncluded": report.get("apiKeyMaterialIncluded"),
        "secretResourceNamesIncluded": report.get("secretResourceNamesIncluded"),
        "eventTokenIncluded": report.get("eventTokenIncluded"),
    }
    add_check(
        checks,
        name,
        observed["apiKeyMaterialIncluded"] is False
        and observed["secretResourceNamesIncluded"] is False
        and observed["eventTokenIncluded"] in {False, None},
        observed,
    )


def live_stage_from_sequence(report: dict[str, Any]) -> dict[str, Any] | None:
    for stage in report.get("sequence") or []:
        if isinstance(stage, dict) and stage.get("id") == "live_1130_realtime_run":
            return stage
    return None


def asr_stage_from_sequence(report: dict[str, Any]) -> dict[str, Any] | None:
    for stage in report.get("sequence") or []:
        if isinstance(stage, dict) and stage.get("id") == "real_no_caption_asr_validation":
            return stage
    return None


def add_check(checks: list[dict[str, Any]], name: str, ok: bool, observed: Any) -> None:
    checks.append({"name": name, "state": "pass" if ok else "fail", "observed": observed})


def contains_secret_material(text: str) -> bool:
    patterns = [
        r"sk-[A-Za-z0-9_-]{12,}",
        r"Bearer [A-Za-z0-9._-]{20,}",
        r"BEGIN PRIVATE KEY",
        r"projects/[^/\s,'\"]+/secrets/[^/\s,'\"]+(?:/versions/[^/\s,'\"]+)?",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must contain a JSON object")
    return data


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def display_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
