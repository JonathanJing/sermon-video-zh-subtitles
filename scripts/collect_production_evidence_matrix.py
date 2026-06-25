#!/usr/bin/env python3
"""Collect production-readiness evidence into one operator-facing matrix."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_REALTIME_SESSION = {
    "model": "gpt-realtime-translate",
    "targetLanguage": "zh",
    "audioSourceKind": "ipad_mic",
}
EXPECTED_CLOUD_RUN_API_PREFLIGHT_CHECKS = [
    "realtime_local_session_create",
    "realtime_local_session_metadata",
    "no_secret_material_in_http_responses",
]
EXPECTED_HANDOFF_BROWSER_EVIDENCE = {
    "artifacts/evidence/web-realtime-contract.json",
    "artifacts/evidence/public-caption-view-runtime.json",
    "artifacts/evidence/realtime-public-sse-smoke.json",
    "artifacts/evidence/realtime-public-sse-smoke.session-validation.json",
}


REQUIREMENTS = [
    {
        "id": "cloud_run_realtime_config",
        "label": "Cloud Run realtime config",
        "description": "Single-instance realtime SSE, GCS mirror, and server-side token/key configuration.",
    },
    {
        "id": "cloud_run_api_preflight",
        "label": "Cloud Run API preflight",
        "description": "Root HTML, health, public Sunday read, admin status, and realtime local session creation.",
    },
    {
        "id": "realtime_audio_source_preflight",
        "label": "Realtime audio source preflight",
        "description": "Authorized audio file, stream URL, or YouTube source is valid and ready for realtime relay.",
    },
    {
        "id": "server_media_worker_contract",
        "label": "Server media worker contract",
        "description": "Server worker maps OpenAI realtime transcript events to backend English/Chinese deltas.",
    },
    {
        "id": "browser_webrtc_contract",
        "label": "iPad/iPhone WebRTC contract",
        "description": "Browser mic path maps OpenAI realtime transcript deltas to backend events and public SSE.",
    },
    {
        "id": "live_1130_realtime_run_plan",
        "label": "11:30 realtime run plan",
        "description": "Operator plan preserves iPad/iPhone WebRTC mic and server worker authorized audio options for the 11:30 realtime run.",
    },
    {
        "id": "realtime_handoff_validation",
        "label": "Realtime handoff validation",
        "description": "Live plan, operator bundle, and go-live sequence preserve the realtime draft and offline correction/translation handoff.",
    },
    {
        "id": "public_caption_view_runtime",
        "label": "Public caption view runtime",
        "description": "Public caption page displays realtime draft captions and replaces them with gpt-5.5-mini stable corrections.",
    },
    {
        "id": "realtime_public_sse_contract",
        "label": "Realtime public SSE contract",
        "description": "Backend accepts realtime Chinese caption events and exposes them through public SSE.",
    },
    {
        "id": "realtime_live",
        "label": "Realtime draft path",
        "description": "Authorized source or iPad mic produced realtime Chinese output transcript and English input transcript deltas.",
    },
    {
        "id": "stable_correction_contract",
        "label": "Stable correction contract",
        "description": "Delayed corrections are gpt-5.5-mini caption_final events, not realtime draft reuse.",
    },
    {
        "id": "stable_correction",
        "label": "Stable correction path",
        "description": "Saved realtime deltas received at least one gpt-5.5-mini stable correction.",
    },
    {
        "id": "offline_archive_preflight",
        "label": "Offline archive preflight",
        "description": "YouTube archive metadata was checked for captions-first or ASR fallback routing.",
    },
    {
        "id": "offline_worker_publish_plan",
        "label": "Offline worker publish plan",
        "description": "Default worker chain publishes translated captions and manifest before optional notes.",
    },
    {
        "id": "offline_caption_route",
        "label": "Offline caption route",
        "description": "A real YouTube archive with English captions completed captions-first offline output.",
    },
    {
        "id": "offline_asr_fallback_plan",
        "label": "Offline ASR fallback plan",
        "description": "No-caption archive fallback plan preserves audio extraction, gpt-4o-transcribe ASR, gpt-5.5-mini translation, and not-realtime validation.",
    },
    {
        "id": "offline_asr_route",
        "label": "Offline ASR fallback",
        "description": "A real no-caption archive completed gpt-4o-transcribe ASR fallback output.",
    },
    {
        "id": "cloud_run_gcs_manifest",
        "label": "Cloud Run/GCS manifest",
        "description": "Promoted Sunday manifest and public VTT/SRT/playback artifacts are readable.",
    },
]


def main() -> int:
    args = parse_args()
    report = collect_matrix(args)
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "complete" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-readiness-report", action="append", default=[])
    parser.add_argument("--cloud-run-config-report")
    parser.add_argument("--cloud-run-api-preflight-report")
    parser.add_argument("--realtime-audio-source-preflight-report")
    parser.add_argument("--server-realtime-contract-report")
    parser.add_argument("--web-realtime-contract-report")
    parser.add_argument("--live-1130-run-plan-report")
    parser.add_argument("--realtime-handoff-validation-report")
    parser.add_argument("--public-caption-view-runtime-report")
    parser.add_argument("--realtime-public-sse-smoke-report")
    parser.add_argument("--realtime-openai-smoke-report")
    parser.add_argument("--realtime-session-validation-report")
    parser.add_argument("--stable-correction-contract-report")
    parser.add_argument("--offline-archive-preflight-report")
    parser.add_argument("--offline-worker-plan-report")
    parser.add_argument("--offline-chain-validation-report")
    parser.add_argument("--offline-asr-chain-validation-report")
    parser.add_argument("--no-caption-asr-plan-report")
    parser.add_argument("--offline-asr-smoke-report")
    parser.add_argument("--offline-translation-report")
    parser.add_argument("--sunday-manifest-validation-report")
    parser.add_argument("--gcs-manifest-publish-plan")
    parser.add_argument("--openai-model-access-preflight-report")
    parser.add_argument("--openai-alternative-model-access-preflight-report", action="append", default=[])
    parser.add_argument("--update-plan")
    parser.add_argument("--update-execution")
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def collect_matrix(args: argparse.Namespace) -> dict[str, Any]:
    readiness_reports = read_optional_json_reports(args.production_readiness_report)
    config = read_optional_json(args.cloud_run_config_report)
    preflight = read_optional_json(args.cloud_run_api_preflight_report)
    audio_source_preflight = (
        read_optional_json(args.realtime_audio_source_preflight_report)
    )
    web_realtime_contract = read_optional_json(args.web_realtime_contract_report)
    live_1130_run_plan = read_optional_json(args.live_1130_run_plan_report)
    realtime_handoff_validation = read_optional_json(args.realtime_handoff_validation_report)
    public_caption_view_runtime = read_optional_json(args.public_caption_view_runtime_report)
    server_realtime_contract = (
        read_optional_json(args.server_realtime_contract_report)
    )
    offline_archive_preflight = (
        read_optional_json(args.offline_archive_preflight_report)
    )
    offline_worker_plan = read_optional_json(args.offline_worker_plan_report)
    offline_chain_validation = (
        read_optional_json(args.offline_chain_validation_report)
    )
    offline_asr_chain_validation = (
        read_optional_json(args.offline_asr_chain_validation_report)
    )
    no_caption_asr_plan = read_optional_json(args.no_caption_asr_plan_report)
    offline_asr_smoke = read_optional_json(args.offline_asr_smoke_report)
    offline_translation = (
        read_optional_json(args.offline_translation_report)
    )
    sunday_manifest_validation = (
        read_optional_json(args.sunday_manifest_validation_report)
    )
    gcs_manifest_publish_plan = read_optional_json(args.gcs_manifest_publish_plan)
    model_access = (
        read_optional_json(args.openai_model_access_preflight_report)
    )
    alternative_model_access = [
        report for report in read_optional_json_reports(args.openai_alternative_model_access_preflight_report)
    ]
    available_alternative_models = available_model_access_models(alternative_model_access)
    public_sse_smoke = (
        read_optional_json(args.realtime_public_sse_smoke_report)
    )
    realtime_openai_smoke = (
        read_optional_json(args.realtime_openai_smoke_report)
    )
    realtime_session_validation = (
        read_optional_json(args.realtime_session_validation_report)
    )
    stable_correction_contract = (
        read_optional_json(args.stable_correction_contract_report)
    )
    update_plan = read_optional_json(args.update_plan)
    update_execution = read_optional_json(args.update_execution)

    states = {
        "cloud_run_realtime_config": state_from_config(config, args.cloud_run_config_report),
        "cloud_run_api_preflight": state_from_preflight(preflight, args.cloud_run_api_preflight_report),
        "realtime_audio_source_preflight": state_from_audio_source_preflight(
            audio_source_preflight,
            args.realtime_audio_source_preflight_report,
        ),
        "server_media_worker_contract": state_from_server_realtime_contract(
            server_realtime_contract,
            args.server_realtime_contract_report,
        ),
        "browser_webrtc_contract": state_from_web_realtime_contract(
            web_realtime_contract,
            args.web_realtime_contract_report,
        ),
        "live_1130_realtime_run_plan": state_from_live_1130_run_plan(
            live_1130_run_plan,
            args.live_1130_run_plan_report,
        ),
        "realtime_handoff_validation": state_from_realtime_handoff_validation(
            realtime_handoff_validation,
            args.realtime_handoff_validation_report,
        ),
        "public_caption_view_runtime": state_from_public_caption_view_runtime(
            public_caption_view_runtime,
            args.public_caption_view_runtime_report,
        ),
        "realtime_public_sse_contract": state_from_public_sse_smoke(
            public_sse_smoke,
            args.realtime_public_sse_smoke_report,
        ),
        "realtime_live": state_from_readiness_realtime(
            readiness_reports,
            args.production_readiness_report,
            realtime_openai_smoke,
            args.realtime_openai_smoke_report,
            realtime_session_validation,
            args.realtime_session_validation_report,
        ),
        "stable_correction_contract": state_from_stable_correction_contract(
            stable_correction_contract,
            args.stable_correction_contract_report,
        ),
        "stable_correction": state_from_readiness_stable(
            readiness_reports,
            args.production_readiness_report,
            realtime_session_validation,
            args.realtime_session_validation_report,
            public_sse_smoke,
            args.realtime_public_sse_smoke_report,
            model_access,
            args.openai_model_access_preflight_report,
            available_alternative_models,
        ),
        "offline_archive_preflight": state_from_offline_archive_preflight(
            offline_archive_preflight,
            args.offline_archive_preflight_report,
        ),
        "offline_worker_publish_plan": state_from_worker_publish_plan(
            offline_worker_plan,
            args.offline_worker_plan_report,
        ),
        "offline_caption_route": state_from_offline_route(
            readiness_reports,
            args.production_readiness_report,
            "use_caption_track",
            offline_translation,
            args.offline_translation_report,
            model_access,
            args.openai_model_access_preflight_report,
            offline_chain_validation=offline_chain_validation,
            offline_chain_validation_path=args.offline_chain_validation_report,
            available_alternative_models=available_alternative_models,
        ),
        "offline_asr_fallback_plan": state_from_no_caption_asr_plan(
            no_caption_asr_plan,
            args.no_caption_asr_plan_report,
        ),
        "offline_asr_route": state_from_offline_route(
            readiness_reports,
            args.production_readiness_report,
            "use_asr_fallback",
            offline_chain_validation=offline_asr_chain_validation,
            offline_chain_validation_path=args.offline_asr_chain_validation_report,
            offline_asr_smoke=offline_asr_smoke,
            offline_asr_smoke_path=args.offline_asr_smoke_report,
        ),
        "cloud_run_gcs_manifest": state_from_manifest(
            readiness_reports,
            args.production_readiness_report,
            sunday_manifest_validation,
            args.sunday_manifest_validation_report,
            gcs_manifest_publish_plan,
            args.gcs_manifest_publish_plan,
        ),
    }

    matrix = []
    for item in REQUIREMENTS:
        row = {"id": item["id"], "label": item["label"], "description": item["description"]}
        row.update(states[item["id"]])
        matrix.append(row)

    failed_or_missing = [row for row in matrix if row["state"] != "pass"]
    return {
        "schemaVersion": 1,
        "status": "complete" if not failed_or_missing else "incomplete",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "passed": sum(1 for row in matrix if row["state"] == "pass"),
            "missing": sum(1 for row in matrix if row["state"] == "missing"),
            "failed": sum(1 for row in matrix if row["state"] == "fail"),
            "warnings": sum(1 for row in matrix if row["state"] == "warn"),
            "total": len(matrix),
        },
        "matrix": matrix,
        "updatePlan": compact_update_plan(update_plan, args.update_plan),
        "updateExecution": compact_update_execution(update_execution, args.update_execution),
        "nextActions": next_actions(matrix, update_plan, update_execution),
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def state_from_config(report: dict[str, Any] | None, path: str | None) -> dict[str, Any]:
    if not report:
        return missing(path, "Run validate_cloud_run_realtime_config.py.")
    if report.get("status") == "ok":
        return passed(path, {"maxInstances": nested(report, "cloudRun", "maxInstances")})
    return failed(
        path,
        {
            "status": report.get("status"),
            "failedChecks": report.get("failedChecks") or [],
            "maxInstances": nested(report, "cloudRun", "maxInstances"),
        },
        "Apply the approved Cloud Run realtime update plan, then rerun config validation.",
    )


def state_from_preflight(report: dict[str, Any] | None, path: str | None) -> dict[str, Any]:
    if not report:
        return {
            **missing(
                path,
                (
                    "Run run_cloud_run_realtime_preflight.py with --create-realtime-session "
                    "and --internal-task-token after approval."
                ),
            ),
            "observed": expected_cloud_run_api_preflight(),
        }
    if is_local_base_url(str(report.get("baseUrl") or "")):
        return {
            "state": "warn",
            "evidence": path,
            "observed": {
                "baseUrl": report.get("baseUrl"),
                "status": report.get("status"),
                **expected_cloud_run_api_preflight(),
            },
            "nextAction": "Rerun API preflight against the deployed Cloud Run URL.",
        }
    warnings = report.get("warnings") or []
    if report.get("status") == "ok" and "realtime_local_session_create" not in warnings:
        check_names = {str(check.get("name")) for check in report.get("checks") or [] if isinstance(check, dict)}
        if "realtime_local_session_metadata" not in check_names:
            return {
                "state": "warn",
                "evidence": path,
                "observed": {
                    "warnings": warnings,
                    "realtimeSession": report.get("realtimeSession"),
                    "missingChecks": ["realtime_local_session_metadata"],
                    **expected_cloud_run_api_preflight(),
                },
                "nextAction": (
                    "Rerun run_cloud_run_realtime_preflight.py with the current script so realtime session "
                    "target language and audio source metadata are checked."
                ),
            }
        return passed(
            path,
            {
                "warnings": warnings,
                "realtimeSession": report.get("realtimeSession"),
                **expected_cloud_run_api_preflight(),
            },
        )
    if report.get("status") == "ok":
        return {
            "state": "warn",
            "evidence": path,
            "observed": {"warnings": warnings, **expected_cloud_run_api_preflight()},
            "nextAction": (
                "Rerun preflight with --create-realtime-session and --internal-task-token "
                "after Cloud Run token config is applied."
            ),
        }
    return failed(
        path,
        {"failedChecks": report.get("failedChecks") or [], **expected_cloud_run_api_preflight()},
        "Fix deployed API preflight failures.",
    )


def expected_cloud_run_api_preflight() -> dict[str, Any]:
    return {
        "expectedRealtimeSession": dict(EXPECTED_REALTIME_SESSION),
        "expectedChecks": list(EXPECTED_CLOUD_RUN_API_PREFLIGHT_CHECKS),
    }


def state_from_audio_source_preflight(report: dict[str, Any] | None, path: str | None) -> dict[str, Any]:
    if not report:
        return missing(path, "Run run_realtime_audio_source_preflight.py against the authorized Sunday source.")
    if report.get("status") == "ok":
        warnings = report.get("warnings") or []
        state = "warn" if "prepare_audio" in warnings else "pass"
        return {
            "state": state,
            "evidence": path,
            "observed": {
                "source": report.get("source"),
                "warnings": warnings,
            },
            "nextAction": "Rerun audio source preflight with --prepare-audio before live OpenAI smoke."
            if state == "warn"
            else None,
        }
    return failed(path, {"failedChecks": report.get("failedChecks") or []}, "Fix realtime audio source preflight failures.")


def state_from_web_realtime_contract(report: dict[str, Any] | None, path: str | None) -> dict[str, Any]:
    if not report:
        return missing(path, "Run validate_web_realtime_contract.py and include its report.")
    normalization_probe = report.get("normalizationProbe") if isinstance(report.get("normalizationProbe"), dict) else {}
    session_probe = (
        normalization_probe.get("sessionProbe") if isinstance(normalization_probe.get("sessionProbe"), dict) else {}
    )
    session_probe_checks = (
        session_probe.get("checks") if isinstance(session_probe.get("checks"), dict) else {}
    )
    no_browser_speech_fallback = contract_check(report, "no_browser_speech_success_fallback")
    observed = {
        "status": report.get("status"),
        "failedChecks": report.get("failedChecks") or [],
        "models": report.get("models"),
        "path": report.get("path"),
        "normalizationProbe": {
            "status": normalization_probe.get("status"),
            "caseCount": len(normalization_probe.get("results") or []),
        },
        "sessionProbe": {
            "status": session_probe.get("status"),
            "createUsesRealtimeTranslate": session_probe_checks.get("createUsesRealtimeTranslate"),
            "createTargetsChinese": session_probe_checks.get("createTargetsChinese"),
            "createUsesIpadMic": session_probe_checks.get("createUsesIpadMic"),
            "backendPostUsesSessionEndpoint": session_probe_checks.get("backendPostUsesSessionEndpoint"),
            "backendPostUsesEventTokenHeader": session_probe_checks.get("backendPostUsesEventTokenHeader"),
            "backendPostStoresChineseDelta": session_probe_checks.get("backendPostStoresChineseDelta"),
            "backendPostDoesNotIncludeClientSecret": session_probe_checks.get("backendPostDoesNotIncludeClientSecret"),
            "backendPostDoesNotIncludeEventToken": session_probe_checks.get("backendPostDoesNotIncludeEventToken"),
            "persistedEvents": session_probe.get("persistedEvents"),
            "persistFailures": session_probe.get("persistFailures"),
        },
        "noBrowserSpeechSuccessFallback": {
            "state": no_browser_speech_fallback.get("state"),
            "forbiddenPresent": no_browser_speech_fallback.get("forbiddenPresent") or [],
        },
    }
    no_fallback_ok = no_browser_speech_fallback.get("state") == "pass"
    session_probe_ok = session_probe.get("status") == "ok"
    if report.get("status") == "ok" and normalization_probe.get("status") == "ok" and session_probe_ok and no_fallback_ok:
        return passed(path, observed)
    if report.get("status") == "ok":
        inferred_failed = []
        if normalization_probe.get("status") != "ok":
            inferred_failed.append("openai_event_normalization_runtime")
        if not session_probe_ok:
            inferred_failed.append("browser_session_backend_persistence_probe")
        if not no_fallback_ok:
            inferred_failed.append("no_browser_speech_success_fallback")
        observed["failedChecks"] = list(observed["failedChecks"]) + inferred_failed
        return failed(
            path,
            observed,
            "Rerun validate_web_realtime_contract.py with the runtime OpenAI event normalization probe, browser session persistence, and no browser-speech success fallback passing.",
        )
    return failed(path, observed, "Fix the browser WebRTC realtime contract, then rerun validation.")


def state_from_live_1130_run_plan(report: dict[str, Any] | None, path: str | None) -> dict[str, Any]:
    if not report:
        return missing(path, "Generate live-1130-realtime-run-plan.json and include it in the evidence matrix.")
    choices = report.get("operatorChoices") if isinstance(report.get("operatorChoices"), list) else []
    choice_ids = [choice.get("id") for choice in choices if isinstance(choice, dict)]
    criteria = report.get("passCriteria") if isinstance(report.get("passCriteria"), list) else []
    model_policy = report.get("modelPolicy") if isinstance(report.get("modelPolicy"), dict) else {}
    target_window = report.get("targetWindow") if isinstance(report.get("targetWindow"), dict) else {}
    observed = {
        "status": report.get("status"),
        "targetWindow": target_window,
        "modelPolicy": model_policy,
        "operatorChoices": choice_ids,
        "passCriteria": criteria,
    }
    expected_model_policy = {
        "realtimeDraftModel": "gpt-realtime-translate",
        "stableCorrectionModel": "gpt-5.5-mini",
        "offlineAsrModel": "gpt-4o-transcribe",
        "offlineTranslationModel": "gpt-5.5-mini",
        "forbiddenOfflineModel": "gpt-realtime-translate",
    }
    mismatched_policy = {
        key: model_policy.get(key)
        for key, expected in expected_model_policy.items()
        if model_policy.get(key) != expected
    }
    required_choices = {
        "browser_webrtc_ipad_or_iphone_mic",
        "server_worker_authorized_audio",
    }
    missing_choices = sorted(required_choices - set(choice_ids))
    required_criterion = "Offline post-live route never uses gpt-realtime-translate."
    failed_checks = []
    if report.get("status") not in {"ready_for_operator_review", "complete"}:
        failed_checks.append("status")
    if target_window.get("liveCaptionStart") != "11:30 PT":
        failed_checks.append("live_caption_start")
    if mismatched_policy:
        failed_checks.append("model_policy")
    if model_policy.get("doNotSubstituteGpt55ForGpt55Mini") is not True:
        failed_checks.append("mini_substitution_guard")
    if missing_choices:
        failed_checks.append("operator_choices")
    if required_criterion not in criteria:
        failed_checks.append("offline_not_realtime_guard")
    if failed_checks:
        return failed(
            path,
            {
                **observed,
                "failedChecks": failed_checks,
                "mismatchedModelPolicy": mismatched_policy,
                "missingOperatorChoices": missing_choices,
            },
            "Regenerate the 11:30 realtime run plan with browser WebRTC, server worker fallback, and offline non-realtime guards.",
        )
    return passed(path, observed)


def state_from_realtime_handoff_validation(report: dict[str, Any] | None, path: str | None) -> dict[str, Any]:
    if not report:
        return missing(path, "Run validate_realtime_handoff.py after generating the operator bundle and go-live sequence.")
    reports = report.get("reports") if isinstance(report.get("reports"), dict) else {}
    required_evidence = set(
        item for item in report.get("requiredEvidenceReports") or [] if isinstance(item, str)
    )
    checks = report.get("checks") if isinstance(report.get("checks"), list) else []
    secret_flags = {
        "apiKeyMaterialIncluded": report.get("apiKeyMaterialIncluded"),
        "secretResourceNamesIncluded": report.get("secretResourceNamesIncluded"),
        "eventTokenIncluded": report.get("eventTokenIncluded"),
    }
    observed = {
        "status": report.get("status"),
        "failedChecks": report.get("failedChecks") or [],
        "checkCount": len(checks),
        "reports": reports,
        "missingReports": sorted({"livePlan", "operatorBundle", "goLiveSequence"} - set(reports)),
        "missingRequiredEvidenceReports": sorted(EXPECTED_HANDOFF_BROWSER_EVIDENCE - required_evidence),
        "models": report.get("models"),
        "secretFlags": secret_flags,
    }
    secret_flags_ok = (
        secret_flags["apiKeyMaterialIncluded"] is False
        and secret_flags["secretResourceNamesIncluded"] is False
        and secret_flags["eventTokenIncluded"] is False
    )
    if (
        report.get("status") == "ok"
        and not observed["failedChecks"]
        and not observed["missingReports"]
        and not observed["missingRequiredEvidenceReports"]
        and secret_flags_ok
    ):
        return passed(path, observed)
    return failed(
        path,
        observed,
        "Regenerate the realtime handoff validation after the operator bundle and go-live sequence, then rerun the evidence matrix.",
    )


def state_from_public_caption_view_runtime(report: dict[str, Any] | None, path: str | None) -> dict[str, Any]:
    if not report:
        return missing(path, "Run validate_public_caption_view_runtime.py and include its report.")
    probe = report.get("probe") if isinstance(report.get("probe"), dict) else {}
    observed = {
        "status": report.get("status"),
        "failedChecks": report.get("failedChecks") or [],
        "eventSourceUrl": probe.get("eventSourceUrl"),
        "eventSourceListeners": probe.get("eventSourceListeners") or [],
        "draftCaptionVisible": bool(probe.get("draftCaption")),
        "stableCaptionVisible": bool(probe.get("stableCaption")),
        "englishDeltaSaved": bool(probe.get("segmentEn")),
        "segmentStable": probe.get("segmentStable"),
        "models": report.get("models"),
        "path": report.get("path"),
    }
    required = {
        "caption_delta",
        "caption_final",
        "input_transcript_delta",
        "input_transcript_final",
    }
    listeners = set(observed["eventSourceListeners"])
    is_passed = (
        report.get("status") == "ok"
        and required.issubset(listeners)
        and observed["draftCaptionVisible"]
        and observed["stableCaptionVisible"]
        and observed["englishDeltaSaved"]
        and observed["segmentStable"] is True
    )
    if is_passed:
        return passed(path, observed)
    return failed(path, observed, "Fix public caption view realtime runtime handling, then rerun validation.")


def state_from_server_realtime_contract(report: dict[str, Any] | None, path: str | None) -> dict[str, Any]:
    if not report:
        return missing(path, "Run validate_server_realtime_contract.py and include its report.")
    backend_policy = contract_check(report, "backend_realtime_session_policy")
    backend_policy_observed = (
        backend_policy.get("observed") if isinstance(backend_policy.get("observed"), dict) else {}
    )
    media_worker_policy = contract_check(report, "media_worker_model_policy")
    media_worker_policy_observed = (
        media_worker_policy.get("observed") if isinstance(media_worker_policy.get("observed"), dict) else {}
    )
    observed = {
        "status": report.get("status"),
        "failedChecks": report.get("failedChecks") or [],
        "models": report.get("models"),
        "path": report.get("path"),
        "backendRealtimeSessionPolicy": backend_policy_observed,
        "mediaWorkerModelPolicy": media_worker_policy_observed,
    }
    policies_ok = (
        backend_policy.get("state") == "pass"
        and media_worker_policy.get("state") == "pass"
        and all(backend_policy_observed.values())
        and all(media_worker_policy_observed.values())
    )
    if report.get("status") == "ok" and policies_ok:
        return passed(path, observed)
    return failed(
        path,
        observed,
        "Fix the server media worker realtime model policy contract, then rerun validation.",
    )


def state_from_public_sse_smoke(report: dict[str, Any] | None, path: str | None) -> dict[str, Any]:
    if not report:
        return missing(path, "Run run_realtime_public_sse_smoke.py after Cloud Run token config is applied.")
    session_validation = report.get("sessionValidation") if isinstance(report.get("sessionValidation"), dict) else {}
    observed = {
        "baseUrl": report.get("baseUrl"),
        "sessionId": report.get("sessionId"),
        "eventPayloadSource": report.get("eventPayloadSource"),
        "sse": report.get("sse"),
        "sessionValidation": compact_session_validation_summary(session_validation),
    }
    fill_public_sse_session_metadata(observed)
    check_names = {str(check.get("name")) for check in report.get("checks") or [] if isinstance(check, dict)}
    required_checks = {
        "browser_normalized_event_payloads",
        "create_local_session_metadata",
        "sse_session_metadata",
        "sse_stable_correction_matches_draft_segment",
    }
    missing_checks = sorted(required_checks - check_names)
    if missing_checks:
        return {
            "state": "warn",
            "evidence": path,
            "observed": {**observed, "missingChecks": missing_checks},
            "nextAction": (
                "Rerun run_realtime_public_sse_smoke.py with the current smoke test so session target language "
                "and audio source metadata plus draft/stable segment continuity are checked."
            ),
        }
    if session_validation and session_validation.get("status") not in {None, "ok", "skipped"}:
        return failed(
            path,
            {**observed, "failedChecks": report.get("failedChecks") or []},
            "Fix realtime public SSE smoke session JSONL validation failures.",
        )
    if report.get("status") == "ok":
        if is_local_base_url(str(report.get("baseUrl") or "")):
            return {
                "state": "warn",
                "evidence": path,
                "observed": {**observed, "postedEvents": report.get("postedEvents")},
                "nextAction": "Rerun realtime public SSE smoke against the deployed Cloud Run URL.",
            }
        return passed(
            path,
            {
                **observed,
                "postedEvents": report.get("postedEvents"),
            },
        )
    return failed(path, {"failedChecks": report.get("failedChecks") or []}, "Fix realtime public SSE smoke failures.")


def state_from_offline_archive_preflight(report: dict[str, Any] | None, path: str | None) -> dict[str, Any]:
    if not report:
        return missing(path, "Run run_offline_archive_preflight.py against the YouTube live archive.")
    if report.get("status") != "ok":
        return failed(path, {"failedChecks": report.get("failedChecks") or []}, "Fix offline archive preflight failures.")
    warnings = report.get("warnings") or []
    route = report.get("offlineRoute") if isinstance(report.get("offlineRoute"), dict) else {}
    return {
        "state": "warn" if route.get("decision") == "use_asr_fallback" else "pass",
        "evidence": path,
        "observed": {
            "decision": route.get("decision"),
            "selectedSourceKind": route.get("selectedSourceKind"),
            "warnings": warnings,
        },
        "nextAction": "No requested captions were found; confirm ASR fallback with gpt-4o-transcribe."
        if route.get("decision") == "use_asr_fallback"
        else None,
    }


def state_from_worker_publish_plan(report: dict[str, Any] | None, path: str | None) -> dict[str, Any]:
    if not report:
        return missing(path, "Generate worker-caption-first-plan.json from backend.worker and include it in the evidence matrix.")
    stages = report.get("stages") if isinstance(report.get("stages"), list) else []
    required_order = [
        "model-access",
        "prepare",
        "translate",
        "export-captions",
        "validate-offline",
        "upload-playback",
        "upload-manifest",
        "promote",
    ]
    observed = {
        "status": report.get("status"),
        "stages": stages,
        "translationMode": report.get("translationMode"),
        "notesIncluded": report.get("notesIncluded"),
        "promoteBeforeNotes": report.get("promoteBeforeNotes"),
        "commandCount": report.get("commandCount"),
    }
    passed_plan = (
        report.get("status") == "ok"
        and stages == required_order
        and report.get("translationMode") == "fresh_model_call"
        and report.get("notesIncluded") is False
        and report.get("promoteBeforeNotes") is True
        and report.get("apiKeyMaterialIncluded") is False
        and report.get("secretResourceNamesIncluded") is False
    )
    if passed_plan:
        return passed(path, observed)
    return failed(
        path,
        observed,
        "Fix backend.worker so default offline generation publishes captions and manifest before optional notes.",
    )


def state_from_readiness_realtime(
    reports: list[dict[str, Any]],
    paths: list[str],
    realtime_openai_smoke: dict[str, Any] | None = None,
    realtime_openai_smoke_path: str | None = None,
    realtime_session_validation: dict[str, Any] | None = None,
    realtime_session_validation_path: str | None = None,
) -> dict[str, Any]:
    for report, path in zip(reports, paths):
        if report.get("status") == "ok" and nested(report, "realtime", "counts", "realtimeCaptionEvents"):
            return passed(path, nested(report, "realtime", "counts"))
    if realtime_openai_smoke:
        status = realtime_openai_smoke.get("status")
        observed = {
            "status": status,
            "model": realtime_openai_smoke.get("model"),
            "openaiRealtime": realtime_openai_smoke.get("openaiRealtime"),
            "sse": realtime_openai_smoke.get("sse"),
            "audio": realtime_openai_smoke.get("audio"),
            "inputTranscriptAvailable": realtime_openai_smoke.get("inputTranscriptAvailable"),
            "inputTranscriptMode": input_transcript_mode(
                realtime_openai_smoke,
                realtime_session_validation,
            ),
            "warnings": realtime_openai_smoke.get("warnings") or [],
        }
        if status == "ok":
            synthetic_warning = synthetic_realtime_source_warning(realtime_openai_smoke, realtime_session_validation)
            validation_state = realtime_validation_state(
                realtime_session_validation,
                realtime_session_validation_path,
                require_stable_correction=False,
                missing_action="Run validate_realtime_session.py on the saved realtime JSONL and feed --realtime-session-validation-report.",
            )
            if validation_state:
                return validation_state
            if synthetic_warning:
                return {
                    "state": "warn",
                    "evidence": realtime_session_validation_path or realtime_openai_smoke_path,
                    "observed": {
                        **observed,
                        "validation": compact_realtime_validation(realtime_session_validation),
                        "sourceEvidence": "synthetic_smoke",
                    },
                    "nextAction": synthetic_warning,
                }
            return passed(
                realtime_session_validation_path or realtime_openai_smoke_path,
                {
                    **observed,
                    "validation": compact_realtime_validation(realtime_session_validation),
                },
            )
        if status in {"missing_input_transcript", "no_transcript"}:
            return failed(
                realtime_openai_smoke_path,
                observed,
                "Rerun realtime OpenAI smoke and require both Chinese output transcript and English input transcript events.",
            )
        return failed(
            realtime_openai_smoke_path,
            observed,
            "Fix realtime OpenAI smoke failure, then rerun with an authorized source.",
        )
    return missing(None, "Run realtime live/smoke validation and feed its JSONL into a production readiness report.")


def input_transcript_mode(
    realtime_openai_smoke: dict[str, Any],
    realtime_session_validation: dict[str, Any] | None,
) -> str:
    realtime_input_count = nested(realtime_session_validation or {}, "counts", "realtimeInputTranscriptEvents") or 0
    input_count = nested(realtime_session_validation or {}, "counts", "inputTranscriptEvents") or 0
    fallback = nested(realtime_openai_smoke, "openaiRealtime", "inputTranscriptFallback")
    fallback_events = nested(fallback if isinstance(fallback, dict) else {}, "eventsPosted") or 0
    if realtime_input_count:
        return "openai_realtime"
    if fallback_events or (input_count and nested(fallback if isinstance(fallback, dict) else {}, "enabled")):
        return "audio_api_fallback"
    if input_count or realtime_openai_smoke.get("inputTranscriptAvailable"):
        return "input_transcript_available"
    return "missing"


def synthetic_realtime_source_warning(
    realtime_openai_smoke: dict[str, Any],
    realtime_session_validation: dict[str, Any] | None,
) -> str | None:
    audio = realtime_openai_smoke.get("audio") if isinstance(realtime_openai_smoke.get("audio"), dict) else {}
    audio_file = str(audio.get("file") or "").lower()
    validation_summary = compact_realtime_validation(realtime_session_validation) or {}
    source_kinds = validation_summary.get("audioSourceKinds") or []
    synthetic_path = any(marker in audio_file for marker in ("synthetic", "sample", "fixture"))
    synthetic_authorized_file = synthetic_path and "authorized_audio_file" in source_kinds
    if synthetic_authorized_file or synthetic_path:
        return (
            "Realtime OpenAI smoke passed on synthetic audio only. Run the 11:30 iPad mic, "
            "authorized live stream, or non-synthetic authorized source and validate the saved realtime JSONL."
        )
    return None


def state_from_stable_correction_contract(report: dict[str, Any] | None, path: str | None) -> dict[str, Any]:
    if not report:
        return missing(path, "Run validate_stable_correction_contract.py and include its report.")
    event_check = contract_check(report, "stable_corrections_are_caption_final_events")
    event_observed = event_check.get("observed") if isinstance(event_check.get("observed"), dict) else {}
    model_policy_check = contract_check(report, "stable_correction_model_policy")
    model_policy_observed = (
        model_policy_check.get("observed") if isinstance(model_policy_check.get("observed"), dict) else {}
    )
    observed = {
        "status": report.get("status"),
        "failedChecks": report.get("failedChecks") or [],
        "models": report.get("models"),
        "path": report.get("path"),
        "stableEvent": event_observed,
        "stableModelPolicy": model_policy_observed,
    }
    event_shape_ok = (
        event_check.get("state") == "pass"
        and event_observed.get("type") == "caption_final"
        and event_observed.get("source") == "gpt-5.5-mini-stable-correction"
        and event_observed.get("model") == "gpt-5.5-mini"
        and event_observed.get("final") is True
        and event_observed.get("hasSegmentId") is True
        and event_observed.get("hasChinese") is True
        and event_observed.get("hasEnglish") is True
    )
    model_policy_ok = model_policy_check.get("state") == "pass" and all(model_policy_observed.values())
    if report.get("status") == "ok" and event_shape_ok and model_policy_ok:
        return passed(path, observed)
    return failed(
        path,
        observed,
        "Fix the stable correction event contract and model policy, then rerun validation.",
    )


def state_from_readiness_stable(
    reports: list[dict[str, Any]],
    paths: list[str],
    realtime_session_validation: dict[str, Any] | None = None,
    realtime_session_validation_path: str | None = None,
    public_sse_smoke: dict[str, Any] | None = None,
    public_sse_smoke_path: str | None = None,
    model_access: dict[str, Any] | None = None,
    model_access_path: str | None = None,
    available_alternative_models: list[str] | None = None,
) -> dict[str, Any]:
    for report, path in zip(reports, paths):
        if report.get("status") == "ok" and (nested(report, "realtime", "counts", "stableCorrectionEvents") or 0) > 0:
            return passed(path, nested(report, "realtime", "counts"))
    public_sse_stable_state = state_from_public_sse_stable_correction(
        public_sse_smoke,
        public_sse_smoke_path,
    )
    if public_sse_stable_state:
        return public_sse_stable_state
    validation_state = realtime_validation_state(
        realtime_session_validation,
        realtime_session_validation_path,
        require_stable_correction=True,
    )
    if validation_state:
        return validation_state
    if (nested(realtime_session_validation or {}, "counts", "stableCorrectionEvents") or 0) > 0:
        return passed(realtime_session_validation_path, compact_realtime_validation(realtime_session_validation))
    model_failure = model_access_failure(model_access, "gpt-5.5-mini")
    if model_failure:
        return failed(
            model_access_path,
            with_available_alternatives(model_failure, available_alternative_models),
            "Fix gpt-5.5-mini model access, then rerun stable correction validation.",
        )
    if not realtime_session_validation:
        return missing(None, "Run gpt-5.5-mini stable correction and validate realtime JSONL with --require-stable-correction.")
    return failed(
        realtime_session_validation_path,
        compact_realtime_validation(realtime_session_validation),
        "Run gpt-5.5-mini stable correction and validate realtime JSONL with --require-stable-correction.",
    )


def state_from_public_sse_stable_correction(
    report: dict[str, Any] | None,
    path: str | None,
) -> dict[str, Any] | None:
    if not report:
        return None
    session_validation = report.get("sessionValidation") if isinstance(report.get("sessionValidation"), dict) else {}
    stable_match = nested(report, "sse", "stableCorrection")
    observed = {
        "baseUrl": report.get("baseUrl"),
        "status": report.get("status"),
        "sessionValidation": compact_session_validation_summary(session_validation),
        "stableCorrection": stable_match,
    }
    has_stable_validation = (
        session_validation.get("status") == "ok"
        and (nested(session_validation, "counts", "stableCorrectionEvents") or 0) > 0
    )
    stable_matches_draft = isinstance(stable_match, dict) and stable_match.get("matched") is True
    if has_stable_validation and stable_matches_draft:
        if is_local_base_url(str(report.get("baseUrl") or "")):
            return {
                "state": "warn",
                "evidence": path,
                "observed": observed,
                "nextAction": (
                    "Local stable correction session validation passed. Rerun realtime public SSE smoke against "
                    "the deployed Cloud Run URL, or validate the real saved realtime JSONL with --require-stable-correction."
                ),
            }
        return passed(path, observed)
    failed_checks = report.get("failedChecks") or []
    if (
        report.get("status") not in {None, "ok"}
        and (
            "sse_stable_correction_matches_draft_segment" in failed_checks
            or "session_jsonl_validation" in failed_checks
            or "stable_correction" in (session_validation.get("failedChecks") or [])
            or "stable_correction_matches_realtime_draft_segment" in (session_validation.get("failedChecks") or [])
        )
    ):
        return failed(
            path,
            {**observed, "failedChecks": failed_checks},
            "Fix public SSE stable correction validation, then rerun realtime public SSE smoke.",
        )
    return None


def state_from_offline_route(
    reports: list[dict[str, Any]],
    paths: list[str],
    decision: str,
    offline_translation: dict[str, Any] | None = None,
    offline_translation_path: str | None = None,
    model_access: dict[str, Any] | None = None,
    model_access_path: str | None = None,
    offline_chain_validation: dict[str, Any] | None = None,
    offline_chain_validation_path: str | None = None,
    offline_asr_smoke: dict[str, Any] | None = None,
    offline_asr_smoke_path: str | None = None,
    available_alternative_models: list[str] | None = None,
) -> dict[str, Any]:
    if decision == "use_caption_track" and offline_chain_validation:
        observed_chain = compact_offline_chain_validation(offline_chain_validation)
        if (
            offline_chain_validation.get("status") == "ok"
            and nested(offline_chain_validation, "offlineRoute", "decision") == decision
            and nested(offline_chain_validation, "translation", "model") == "gpt-5.5-mini"
            and offline_chain_check_state(offline_chain_validation, "not_realtime_chain") == "pass"
        ):
            return passed(offline_chain_validation_path, observed_chain)
        if offline_translation and offline_translation.get("status") == "failed":
            return failed(
                offline_translation_path or offline_chain_validation_path,
                {
                    "failureStage": offline_translation.get("failureStage"),
                    "model": offline_translation.get("model"),
                    "httpStatus": offline_translation.get("httpStatus"),
                    "failureKind": offline_translation.get("failureKind"),
                    "error": offline_translation.get("error"),
                    "translatedSegments": offline_translation.get("translatedSegments"),
                    "totalSegments": offline_translation.get("totalSegments"),
                    "offlineChainValidation": observed_chain,
                    "availableButNotConfiguredModels": available_alternative_models or [],
                },
                "Fix the offline translation model/access issue, then rerun gpt-5.5-mini translation and export zh VTT/SRT.",
            )
        return failed(
            offline_chain_validation_path,
            observed_chain,
            "Fix offline chain validation failures, then rerun gpt-5.5-mini translation and export zh VTT/SRT.",
        )
    if decision == "use_caption_track" and offline_translation and offline_translation.get("status") == "failed":
        return failed(
            offline_translation_path or offline_chain_validation_path,
            {
                "failureStage": offline_translation.get("failureStage"),
                "model": offline_translation.get("model"),
                "httpStatus": offline_translation.get("httpStatus"),
                "failureKind": offline_translation.get("failureKind"),
                "error": offline_translation.get("error"),
                "translatedSegments": offline_translation.get("translatedSegments"),
                "totalSegments": offline_translation.get("totalSegments"),
                "offlineChainValidation": compact_offline_chain_validation(offline_chain_validation),
                "availableButNotConfiguredModels": available_alternative_models or [],
            },
            "Fix the offline translation model/access issue, then rerun gpt-5.5-mini translation and export zh VTT/SRT.",
        )
    for report, path in zip(reports, paths):
        if report.get("status") == "ok" and nested(report, "offline", "offlineRoute", "decision") == decision:
            if decision == "use_caption_track":
                return {
                    "state": "warn",
                    "evidence": path,
                    "observed": nested(report, "offline", "offlineRoute"),
                    "nextAction": "Run validate_offline_chain.py on the caption-route VTT/SRT/playback/manifest artifacts and feed --offline-chain-validation-report.",
                }
            return passed(path, nested(report, "offline", "offlineRoute"))
    if decision == "use_caption_track" and offline_translation:
        if offline_translation.get("status") == "ok":
            return {
                "state": "warn",
                "evidence": offline_translation_path,
                "observed": {
                    "model": offline_translation.get("model"),
                    "translatedSegments": offline_translation.get("translatedSegments"),
                    "totalSegments": offline_translation.get("totalSegments"),
                },
                "nextAction": "Export translated VTT/SRT and run validate_production_readiness.py.",
            }
    if decision == "use_caption_track":
        model_failure = model_access_failure(model_access, "gpt-5.5-mini")
        if model_failure:
            return failed(
                model_access_path,
                with_available_alternatives(model_failure, available_alternative_models),
                "Fix gpt-5.5-mini model access, then rerun offline translation and export zh VTT/SRT.",
            )
    if decision == "use_caption_track":
        return missing(None, "Run a real YouTube archive with English captions through the offline chain.")
    if decision == "use_asr_fallback" and offline_chain_validation:
        observed_chain = compact_offline_chain_validation(offline_chain_validation)
        chain_ok = (
            offline_chain_validation.get("status") == "ok"
            and nested(offline_chain_validation, "offlineRoute", "decision") == decision
            and nested(offline_chain_validation, "translation", "model") == "gpt-5.5-mini"
            and nested(offline_chain_validation, "asr", "used") is True
            and nested(offline_chain_validation, "asr", "model") == "gpt-4o-transcribe"
            and offline_chain_check_state(offline_chain_validation, "not_realtime_chain") == "pass"
        )
        if offline_asr_smoke and offline_asr_smoke.get("status") != "ok":
            return failed(
                offline_asr_smoke_path,
                {
                    "status": offline_asr_smoke.get("status"),
                    "model": nested(offline_asr_smoke, "asr", "model"),
                    "error": offline_asr_smoke.get("error"),
                    "offlineChainValidation": observed_chain,
                },
                "Fix gpt-4o-transcribe ASR fallback smoke, then rerun the no-caption offline chain validation.",
            )
        if chain_ok and offline_asr_smoke and offline_asr_smoke.get("status") == "ok":
            return passed(
                offline_chain_validation_path,
                {
                    **(observed_chain or {}),
                    "asrSmoke": {
                        "model": nested(offline_asr_smoke, "asr", "model"),
                        "cueCount": offline_asr_smoke.get("cueCount"),
                        "source": offline_asr_smoke.get("source"),
                    },
                },
            )
        if chain_ok:
            return {
                "state": "warn",
                "evidence": offline_chain_validation_path,
                "observed": observed_chain,
                "nextAction": (
                    "Offline ASR chain validation passed. Add the matching gpt-4o-transcribe ASR smoke "
                    "report for the authorized extracted audio or real no-caption archive."
                ),
            }
        return failed(
            offline_chain_validation_path,
            observed_chain,
            "Fix the no-caption offline chain validation so it proves openai_asr, gpt-4o-transcribe, gpt-5.5-mini, and not_realtime_chain.",
        )
    if offline_asr_smoke:
        if offline_asr_smoke.get("status") == "ok":
            return {
                "state": "warn",
                "evidence": offline_asr_smoke_path,
                "observed": {
                    "model": nested(offline_asr_smoke, "asr", "model"),
                    "cueCount": offline_asr_smoke.get("cueCount"),
                    "source": offline_asr_smoke.get("source"),
                },
                "nextAction": (
                    "ASR smoke passed on extracted/authorized audio. Run the no-caption archive through "
                    "extraction, gpt-4o-transcribe, gpt-5.5-mini translation, export zh VTT/SRT/manifest, "
                    "and feed --offline-asr-chain-validation-report from validate_offline_chain.py."
                ),
            }
        return failed(
            offline_asr_smoke_path,
            {
                "status": offline_asr_smoke.get("status"),
                "model": nested(offline_asr_smoke, "asr", "model"),
                "error": offline_asr_smoke.get("error"),
            },
            "Fix gpt-4o-transcribe ASR fallback smoke, then rerun a real no-caption archive.",
        )
    return missing(None, "Run a real no-caption archive through gpt-4o-transcribe ASR fallback.")


def state_from_no_caption_asr_plan(report: dict[str, Any] | None, path: str | None) -> dict[str, Any]:
    if not report:
        return missing(path, "Generate no-caption-asr-fallback-plan.json for the real no-caption archive ASR fallback.")
    commands = report.get("commands") if isinstance(report.get("commands"), list) else []
    command_text = json.dumps(commands, ensure_ascii=False)
    criteria = report.get("passCriteria") if isinstance(report.get("passCriteria"), list) else []
    criteria_text = "\n".join(str(item) for item in criteria)
    required_models = report.get("requiredModels") if isinstance(report.get("requiredModels"), dict) else {}
    required_source = report.get("requiredSource") if isinstance(report.get("requiredSource"), dict) else {}
    checks = {
        "status": report.get("status") == "needs_real_no_caption_archive",
        "sourceKind": required_source.get("kind") == "youtube_live_archive",
        "captionRequirement": "No requested English caption track" in str(required_source.get("captionRequirement") or ""),
        "authorizationRequirement": bool(str(required_source.get("authorizationRequirement") or "").strip()),
        "offlineAsrModel": required_models.get("offlineAsr") == "gpt-4o-transcribe",
        "offlineTranslationModel": required_models.get("offlineTranslation") == "gpt-5.5-mini",
        "forbiddenOfflineModel": required_models.get("forbiddenOfflineModel") == "gpt-realtime-translate",
        "preflightCommand": "scripts/run_offline_archive_preflight.py" in command_text and "use_asr_fallback" in criteria_text,
        "audioExtractionCommand": "scripts/prepare_live_link_playback.py" in command_text and "gpt-4o-transcribe" in command_text,
        "translationCommand": "scripts/translate_playback_with_openai.py" in command_text and "gpt-5.5-mini" in command_text,
        "exportCommand": "scripts/export_playback_captions.py" in command_text and "--gcs-dry-run" in command_text,
        "offlineValidationCommand": "scripts/validate_offline_chain.py" in command_text and "not_realtime_chain" in criteria_text,
        "readinessCommand": "scripts/validate_production_readiness.py" in command_text,
        "asrSourceCriterion": "caption_source.kind=openai_asr" in criteria_text,
        "noSecretMaterialFlags": report.get("apiKeyMaterialIncluded") is False
        and report.get("secretResourceNamesIncluded") is False,
    }
    observed = {
        "status": report.get("status"),
        "requiredSource": required_source,
        "requiredModels": required_models,
        "commandCount": len(commands),
        "checks": checks,
        "failedChecks": [name for name, ok in checks.items() if not ok],
    }
    if not observed["failedChecks"]:
        return passed(path, observed)
    return failed(
        path,
        observed,
        "Regenerate no-caption-asr-fallback-plan.json with ASR extraction, gpt-4o-transcribe, gpt-5.5-mini translation, and not-realtime validation.",
    )


def state_from_manifest(
    reports: list[dict[str, Any]],
    paths: list[str],
    sunday_manifest_validation: dict[str, Any] | None = None,
    sunday_manifest_validation_path: str | None = None,
    gcs_manifest_publish_plan: dict[str, Any] | None = None,
    gcs_manifest_publish_plan_path: str | None = None,
) -> dict[str, Any]:
    publish_observed = compact_gcs_manifest_publish_plan(gcs_manifest_publish_plan)
    if sunday_manifest_validation:
        observed = {
            "status": sunday_manifest_validation.get("status"),
            "manifest": sunday_manifest_validation.get("manifest"),
            "artifactLocation": sunday_manifest_validation.get("artifactLocation"),
            "publicGcsArtifacts": sunday_manifest_validation.get("publicGcsArtifacts"),
            "readableArtifactsRequired": sunday_manifest_validation.get("readableArtifactsRequired"),
            "sunday": sunday_manifest_validation.get("sunday"),
            "failedChecks": sunday_manifest_validation.get("failedChecks") or [],
            "outputs": sunday_manifest_validation.get("outputs"),
            "playback": sunday_manifest_validation.get("playback"),
            "captions": sunday_manifest_validation.get("captions"),
            "publishPlan": publish_observed,
        }
        if (
            sunday_manifest_validation.get("status") == "ok"
            and sunday_manifest_validation.get("publicGcsArtifacts") is True
            and sunday_manifest_validation.get("readableArtifactsRequired") is True
        ):
            return passed(sunday_manifest_validation_path, observed)
        if sunday_manifest_validation.get("status") == "ok" and sunday_manifest_validation.get("publicGcsArtifacts") is True:
            return {
                "state": "warn",
                "evidence": sunday_manifest_validation_path,
                "observed": observed,
                "nextAction": "GCS Sunday manifest shape passed. Rerun validate_sunday_manifest.py with --require-readable-artifacts against the gs:// URI.",
            }
        if sunday_manifest_validation.get("status") == "ok":
            return {
                "state": "warn",
                "evidence": sunday_manifest_validation_path,
                "observed": observed,
                "nextAction": "Local Sunday manifest contract passed. Upload/promote the manifest and artifacts to GCS, then rerun validate_sunday_manifest.py against the gs:// URI.",
            }
        return failed(
            sunday_manifest_validation_path,
            observed,
            "Fix Sunday manifest/public artifact validation failures, then rerun validate_sunday_manifest.py.",
        )
    for report, path in zip(reports, paths):
        if report.get("status") == "ok" and nested(report, "sundayManifest", "status") == "ok":
            return passed(path, report.get("sundayManifest"))
    if gcs_manifest_publish_plan:
        return {
            "state": "warn",
            "evidence": gcs_manifest_publish_plan_path,
            "observed": publish_observed,
            "nextAction": "Apply the generated GCS Sunday manifest publish plan, then rerun validate_sunday_manifest.py with --require-readable-artifacts.",
        }
    return missing(None, "Validate the promoted Sunday GCS manifest with readable public artifacts.")


def compact_gcs_manifest_publish_plan(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    return {
        "status": report.get("status"),
        "artifactLocation": report.get("artifactLocation"),
        "runManifestUri": report.get("runManifestUri"),
        "stableManifestUri": report.get("stableManifestUri"),
        "artifactCount": len(report.get("artifacts") or []),
        "commandCount": len(report.get("commands") or []),
        "gcsManifestValidation": report.get("gcsManifestValidation"),
        "appliedSteps": len(report.get("appliedSteps") or []),
    }


def realtime_validation_state(
    report: dict[str, Any] | None,
    path: str | None,
    *,
    require_stable_correction: bool,
    missing_action: str | None = None,
) -> dict[str, Any] | None:
    if not report:
        if missing_action:
            return {
                "state": "warn",
                "evidence": path,
                "observed": None,
                "nextAction": missing_action,
            }
        return None
    check_names = {str(check.get("name")) for check in report.get("checks") or [] if isinstance(check, dict)}
    required_checks = {
        "event_ids_strictly_increasing",
        "session_id_consistent",
        "target_language",
        "audio_source_kind",
    }
    if require_stable_correction:
        required_checks.add("stable_correction_matches_realtime_draft_segment")
    missing_checks = sorted(required_checks - check_names)
    if missing_checks:
        if require_stable_correction and "stable_correction_matches_realtime_draft_segment" in missing_checks:
            next_action = (
                "Run gpt-5.5-mini stable correction on saved realtime deltas so caption_final uses the same "
                "segmentId as the realtime draft, then rerun validate_realtime_session.py with "
                "--require-stable-correction."
            )
        else:
            next_action = (
                "Rerun validate_realtime_session.py with the current validator so session id, event id, "
                "target language, and audio source are checked."
            )
        return {
            "state": "warn",
            "evidence": path,
            "observed": {"status": report.get("status"), "missingChecks": missing_checks},
            "nextAction": next_action,
        }
    if report.get("status") != "ok":
        return failed(
            path,
            {
                "status": report.get("status"),
                "failedChecks": report.get("failedChecks") or [],
                "counts": report.get("counts"),
            },
            "Fix realtime JSONL validation failures, then rerun validate_realtime_session.py.",
        )
    if require_stable_correction and (nested(report, "counts", "stableCorrectionEvents") or 0) <= 0:
        return failed(
            path,
            compact_realtime_validation(report),
            "Run gpt-5.5-mini stable correction and validate realtime JSONL with --require-stable-correction.",
        )
    return None


def compact_realtime_validation(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    return {
        "status": report.get("status"),
        "eventsJsonl": report.get("eventsJsonl"),
        "counts": report.get("counts"),
        "models": report.get("models"),
        "sessionIds": report.get("sessionIds"),
        "realtimeSources": report.get("realtimeSources"),
        "targetLanguages": report.get("targetLanguages"),
        "audioSourceKinds": report.get("audioSourceKinds"),
    }


def compact_session_validation_summary(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    return {
        "status": report.get("status"),
        "eventsJsonl": report.get("eventsJsonl"),
        "report": report.get("report"),
        "failedChecks": report.get("failedChecks") or [],
        "counts": report.get("counts"),
        "targetLanguages": report.get("targetLanguages"),
        "audioSourceKinds": report.get("audioSourceKinds"),
    }


def fill_public_sse_session_metadata(observed: dict[str, Any]) -> None:
    validation = observed.get("sessionValidation")
    sse = observed.get("sse") if isinstance(observed.get("sse"), dict) else {}
    session_started = sse.get("sessionStarted") if isinstance(sse.get("sessionStarted"), dict) else {}
    if not isinstance(validation, dict) or not session_started:
        return
    if validation.get("targetLanguages") is None and session_started.get("targetLanguage"):
        validation["targetLanguages"] = [session_started["targetLanguage"]]
    if validation.get("audioSourceKinds") is None and session_started.get("audioSourceKind"):
        validation["audioSourceKinds"] = [session_started["audioSourceKind"]]


def compact_offline_chain_validation(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    return {
        "status": report.get("status"),
        "failedChecks": report.get("failedChecks") or [],
        "inputs": report.get("inputs"),
        "offlineRoute": report.get("offlineRoute"),
        "notRealtimeChain": offline_chain_check_state(report, "not_realtime_chain"),
        "timelineAlignment": {
            "zhVtt": offline_chain_check_state(report, "zh_vtt_timeline_alignment"),
            "zhSrt": offline_chain_check_state(report, "zh_srt_timeline_alignment"),
        },
        "translation": report.get("translation"),
        "asr": report.get("asr"),
    }


def offline_chain_check_state(report: dict[str, Any], name: str) -> str | None:
    for check in report.get("checks") or []:
        if isinstance(check, dict) and check.get("name") == name:
            return check.get("state")
    return None


def contract_check(report: dict[str, Any], name: str) -> dict[str, Any]:
    for check in report.get("checks") or []:
        if isinstance(check, dict) and check.get("name") == name:
            return check
    return {}


def passed(path: str | None, observed: Any) -> dict[str, Any]:
    return {"state": "pass", "evidence": path, "observed": observed, "nextAction": None}


def missing(path: str | None, action: str) -> dict[str, Any]:
    return {"state": "missing", "evidence": path, "observed": None, "nextAction": action}


def failed(path: str | None, observed: Any, action: str) -> dict[str, Any]:
    return {"state": "fail", "evidence": path, "observed": observed, "nextAction": action}


def model_access_failure(report: dict[str, Any] | None, model: str) -> dict[str, Any] | None:
    if not report or report.get("status") == "ok":
        return None
    for check in report.get("checks") or []:
        if not isinstance(check, dict) or check.get("state") != "fail":
            continue
        observed = check.get("observed")
        if isinstance(observed, dict) and observed.get("model") == model:
            return {
                "model": observed.get("model"),
                "endpoint": observed.get("endpoint"),
                "httpStatus": observed.get("httpStatus"),
                "failureKind": observed.get("failureKind"),
                "error": observed.get("error"),
                "failedCheck": check.get("name"),
            }
    if model in (report.get("models") or []):
        return {
            "model": model,
            "failedChecks": report.get("failedChecks") or [],
            "status": report.get("status"),
        }
    return None


def available_model_access_models(reports: list[dict[str, Any]]) -> list[str]:
    models: list[str] = []
    for report in reports:
        if report.get("status") != "ok":
            continue
        for check in report.get("checks") or []:
            if not isinstance(check, dict) or check.get("state") != "pass":
                continue
            observed = check.get("observed")
            if not isinstance(observed, dict):
                continue
            model = observed.get("model")
            if isinstance(model, str) and model and model not in models:
                models.append(model)
    return models


def with_available_alternatives(observed: dict[str, Any], alternatives: list[str] | None) -> dict[str, Any]:
    if not alternatives:
        return observed
    return {
        **observed,
        "availableButNotConfiguredModels": alternatives,
        "alternativeModelPolicy": "Observed availability only; do not substitute for required gpt-5.5-mini without an explicit routing decision.",
    }


def compact_update_plan(report: dict[str, Any] | None, path: str | None) -> dict[str, Any] | None:
    if not report:
        return None
    return {
        "path": path,
        "status": report.get("status"),
        "requiresExplicitApproval": report.get("requiresExplicitApproval"),
        "secretReferencesIncluded": report.get("secretReferencesIncluded"),
        "secretResourceNamesIncluded": report.get("secretResourceNamesIncluded"),
        "plannedChanges": report.get("plannedChanges") or [],
    }


def compact_update_execution(report: dict[str, Any] | None, path: str | None) -> dict[str, Any] | None:
    if not report:
        return None
    return {
        "path": path,
        "status": report.get("status"),
        "approved": report.get("approved"),
        "applyStatus": nested(report, "apply", "status"),
        "rollbackStatus": nested(report, "rollback", "status"),
        "runtimeTokenSources": report.get("runtimeTokenSources") or {},
        "missingRuntimeEnv": report.get("missingRuntimeEnv") or [],
        "secretReferencesIncluded": report.get("secretReferencesIncluded"),
        "secretResourceNamesIncluded": report.get("secretResourceNamesIncluded"),
    }


def next_actions(matrix: list[dict[str, Any]], update_plan: dict[str, Any] | None, update_execution: dict[str, Any] | None) -> list[str]:
    actions = []
    if update_plan and update_plan.get("status") == "approval_required" and not (update_execution and update_execution.get("approved")):
        actions.append("Get explicit approval, then run apply_cloud_run_realtime_update_plan.py with --approve --rollback-on-failure.")
    for row in matrix:
        if row["state"] != "pass" and row.get("nextAction"):
            actions.append(row["nextAction"])
    return dedupe(actions)


def dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def is_local_base_url(value: str) -> bool:
    return value.startswith("http://127.0.0.1") or value.startswith("http://localhost")


def read_json(path_value: str) -> dict[str, Any]:
    path = resolve_repo_path(Path(path_value))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"JSON report must be an object: {path_value}")
    return data


def read_optional_json(path_value: str | None) -> dict[str, Any] | None:
    if not path_value:
        return None
    path = resolve_repo_path(Path(path_value))
    if not path.exists():
        return None
    return read_json(path_value)


def read_optional_json_reports(path_values: list[str]) -> list[dict[str, Any]]:
    reports = []
    for path_value in path_values:
        report = read_optional_json(path_value)
        if report:
            reports.append(report)
    return reports


def nested(data: Any, *keys: str) -> Any:
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
