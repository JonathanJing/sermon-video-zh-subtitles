#!/usr/bin/env python3
"""Write a sanitized recovery plan for the required gpt-5.5-mini routes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "artifacts" / "evidence" / "model-access-recovery-plan.json"
DEFAULT_REQUIRED_REPORT = REPO_ROOT / "artifacts" / "evidence" / "openai-model-access-preflight.json"
DEFAULT_ALTERNATIVE_REPORT = REPO_ROOT / "artifacts" / "evidence" / "openai-model-access-preflight-gpt-5.5.json"
PLACEHOLDER_SECRET = "<OPENAI_API_KEY_SECRET_RESOURCE>"
PLACEHOLDER_EVENT_TOKEN = "<REALTIME_EVENT_TOKEN_OR_ADMIN_TOKEN>"


def main() -> int:
    args = parse_args()
    report = build_plan(args)
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sunday", required=True)
    parser.add_argument("--required-model", default="gpt-5.5-mini")
    parser.add_argument("--alternative-model", default="gpt-5.5")
    parser.add_argument("--required-report", type=Path, default=DEFAULT_REQUIRED_REPORT)
    parser.add_argument("--alternative-report", type=Path, default=DEFAULT_ALTERNATIVE_REPORT)
    parser.add_argument("--offline-run-root", default="artifacts/evidence/offline-caption-route")
    parser.add_argument("--realtime-events-jsonl", default="<REALTIME_SESSION_EVENTS_JSONL>")
    parser.add_argument("--realtime-session-id", default="<REALTIME_SESSION_ID>")
    parser.add_argument("--backend-url", default="<BACKEND_BASE_URL>")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    required = read_optional_json(resolve_repo_path(args.required_report))
    alternative = read_optional_json(resolve_repo_path(args.alternative_report))
    run_root = args.offline_run_root.rstrip("/")
    playback_js = f"{run_root}/web/playback-simulation.generated.js"
    artifacts_dir = f"{run_root}/artifacts"
    model_output_dir = f"{run_root}/model-output"
    zh_vtt = f"{artifacts_dir}/sermon.zh.live-aligned.vtt"
    zh_srt = f"{artifacts_dir}/sermon.zh.live-aligned.srt"
    manifest = f"{artifacts_dir}/cloud-manifest.json"
    stable_out_dir = "artifacts/evidence/realtime-stable-correction-recovery"
    return {
        "schemaVersion": 1,
        "status": status_from_reports(required, args.required_model),
        "sunday": args.sunday,
        "requiredModel": args.required_model,
        "alternativeModel": args.alternative_model,
        "modelPolicy": {
            "doNotSubstitute": True,
            "alternativeModelIsSideEvidenceOnly": True,
            "requiredStableAndOfflineModel": args.required_model,
        },
        "observedRequiredModelAccess": observed_model(required, args.required_model),
        "observedAlternativeModelAccess": observed_model(alternative, args.alternative_model),
        "commands": [
            [
                "python3",
                "scripts/run_openai_model_access_preflight.py",
                "--model",
                args.required_model,
                "--out",
                "artifacts/evidence/openai-model-access-preflight.json",
            ],
            [
                "python3",
                "scripts/translate_playback_with_openai.py",
                "--input",
                playback_js,
                "--model",
                args.required_model,
                "--api-key-secret",
                PLACEHOLDER_SECRET,
                "--out",
                playback_js,
                "--out-dir",
                model_output_dir,
            ],
            [
                "python3",
                "scripts/export_playback_captions.py",
                "--input",
                playback_js,
                "--out-dir",
                artifacts_dir,
                "--stem",
                "sermon.zh.live-aligned",
                "--manifest",
                manifest,
            ],
            [
                "python3",
                "scripts/validate_offline_chain.py",
                "--report",
                f"{artifacts_dir}/report.json",
                "--playback-js",
                playback_js,
                "--zh-vtt",
                zh_vtt,
                "--zh-srt",
                zh_srt,
                "--manifest",
                manifest,
                "--expected-translation-model",
                args.required_model,
                "--out",
                f"{run_root}/offline-chain-validation.json",
            ],
            [
                "python3",
                "scripts/stabilize_realtime_deltas_with_openai.py",
                "--input-jsonl",
                args.realtime_events_jsonl,
                "--api-key-secret",
                PLACEHOLDER_SECRET,
                "--model",
                args.required_model,
                "--out-dir",
                stable_out_dir,
                "--post-backend-url",
                args.backend_url,
                "--post-session-id",
                args.realtime_session_id,
                "--post-event-token",
                PLACEHOLDER_EVENT_TOKEN,
            ],
            [
                "python3",
                "scripts/validate_realtime_session.py",
                "--events-jsonl",
                args.realtime_events_jsonl,
                "--expected-model",
                "gpt-realtime-translate",
                "--expected-stable-model",
                args.required_model,
                "--require-stable-correction",
                "--out",
                "artifacts/evidence/realtime-stable-correction-recovery/session-validation.json",
            ],
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
        "passCriteria": [
            f"run_openai_model_access_preflight.py reports responses_model:{args.required_model}=pass.",
            f"Offline translation report uses {args.required_model}.",
            "validate_offline_chain.py status is ok and not_realtime_chain passes.",
            f"Stable correction events have source gpt-5.5-mini-stable-correction and model {args.required_model}.",
            "validate_realtime_session.py passes with --require-stable-correction.",
            f"{args.alternative_model} availability is not used as a substitute for {args.required_model}.",
        ],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def status_from_reports(report: dict[str, Any] | None, model: str) -> str:
    observed = observed_model(report, model)
    return "ready_to_rerun_model_routes" if observed.get("status") == "ok" else "waiting_for_required_model_access"


def observed_model(report: dict[str, Any] | None, model: str) -> dict[str, Any]:
    if not report:
        return {"model": model, "status": "missing_report"}
    for check in report.get("checks") or []:
        if not isinstance(check, dict):
            continue
        observed = check.get("observed")
        if isinstance(observed, dict) and observed.get("model") == model:
            return {
                "model": model,
                "status": observed.get("status") or check.get("state"),
                "httpStatus": observed.get("httpStatus"),
                "failureKind": observed.get("failureKind"),
                "error": observed.get("error"),
            }
    return {"model": model, "status": report.get("status") or "unknown"}


def read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
