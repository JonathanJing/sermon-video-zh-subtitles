#!/usr/bin/env python3
"""Write the operator plan for the 11:30 realtime caption run."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "artifacts" / "evidence" / "live-1130-realtime-run-plan.json"


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
    parser.add_argument("--base-url", default="<BACKEND_BASE_URL>")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    sunday = args.sunday
    base_url = args.base_url
    realtime_events_jsonl = f"gs://sermon-zh-artifacts-ai-for-god/realtime-events/{sunday}/<REALTIME_SESSION_ID>.jsonl"
    return {
        "schemaVersion": 1,
        "status": "ready_for_operator_review",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sunday": sunday,
        "targetWindow": {
            "liveCaptionStart": "11:30 PT",
            "publicReadinessDeadline": "11:50 PT",
        },
        "modelPolicy": {
            "realtimeDraftModel": "gpt-realtime-translate",
            "stableCorrectionModel": "gpt-5.5-mini",
            "offlineAsrModel": "gpt-4o-transcribe",
            "offlineTranslationModel": "gpt-5.5-mini",
            "forbiddenOfflineModel": "gpt-realtime-translate",
            "doNotSubstituteGpt55ForGpt55Mini": True,
        },
        "operatorChoices": [
            {
                "id": "browser_webrtc_ipad_or_iphone_mic",
                "default": True,
                "source": "iPad/iPhone mic",
                "path": "browser WebRTC -> gpt-realtime-translate -> backend session events -> public caption SSE",
                "expectedAudioSourceKind": "ipad_mic",
                "operatorAction": "Open the admin page, choose iPad mic realtime mode, and start the microphone session.",
                "evidenceReports": [
                    "artifacts/evidence/web-realtime-contract.json",
                    "artifacts/evidence/public-caption-view-runtime.json",
                    "artifacts/evidence/realtime-public-sse-smoke.json",
                    "artifacts/evidence/realtime-public-sse-smoke.session-validation.json",
                ],
            },
            {
                "id": "server_worker_authorized_audio",
                "default": False,
                "source": "authorized audio URL/file or authorized YouTube live source",
                "path": "server media worker -> gpt-realtime-translate -> backend session events -> public caption SSE",
                "expectedAudioSourceKinds": [
                    "authorized_audio_url",
                    "authorized_audio_file",
                    "authorized_youtube_source",
                ],
                "command": [
                    "python3",
                    "scripts/run_realtime_live_session.py",
                    "--audio-url",
                    "<AUTHORIZED_AUDIO_URL>",
                    "--api-key-secret",
                    "<OPENAI_API_KEY_SECRET_RESOURCE>",
                    "--backend-url",
                    base_url,
                    "--sunday",
                    sunday,
                    "--internal-task-token",
                    "$INTERNAL_TASK_TOKEN",
                    "--target-language",
                    "zh",
                    "--realtime-model",
                    "gpt-realtime-translate",
                    "--stable-model",
                    "gpt-5.5-mini",
                    "--realtime-event-gcs-prefix",
                    "gs://sermon-zh-artifacts-ai-for-god/realtime-events",
                    "--require-stable-correction",
                    "--out",
                    "artifacts/evidence/realtime-live-session/report.json",
                    "--worker-report-out",
                    "artifacts/evidence/realtime-live-session/worker-report.json",
                    "--stable-out-dir",
                    "artifacts/evidence/realtime-live-session/stable-corrections",
                ],
            },
        ],
        "stabilizerFallbackCommand": [
            "python3",
            "scripts/run_realtime_stabilizer_loop.py",
            "--input-jsonl",
            realtime_events_jsonl,
            "--api-key-secret",
            "<OPENAI_API_KEY_SECRET_RESOURCE>",
            "--backend-url",
            base_url,
            "--session-id",
            "<REALTIME_SESSION_ID>",
            "--internal-task-token",
            "$INTERNAL_TASK_TOKEN",
            "--model",
            "gpt-5.5-mini",
            "--interval-seconds",
            "5",
            "--min-age-seconds",
            "4",
            "--model-preflight-out",
            "artifacts/evidence/realtime-stable-correction-recovery/model-access.json",
            "--out-dir",
            "artifacts/evidence/realtime-stable-correction-recovery",
        ],
        "liveValidationCommands": [
            [
                "python3",
                "scripts/run_realtime_public_sse_smoke.py",
                "--base-url",
                base_url,
                "--sunday",
                sunday,
                "--internal-task-token",
                "$INTERNAL_TASK_TOKEN",
                "--realtime-event-gcs-prefix",
                "gs://sermon-zh-artifacts-ai-for-god/realtime-events",
                "--web-realtime-contract-report",
                "artifacts/evidence/web-realtime-contract.json",
                "--session-validation-out",
                "artifacts/evidence/realtime-public-sse-smoke.session-validation.json",
                "--out",
                "artifacts/evidence/realtime-public-sse-smoke.json",
            ],
            [
                "python3",
                "scripts/validate_realtime_session.py",
                "--events-jsonl",
                realtime_events_jsonl,
                "--expected-model",
                "gpt-realtime-translate",
                "--expected-stable-model",
                "gpt-5.5-mini",
                "--require-stable-correction",
                "--out",
                "artifacts/evidence/realtime-live-session/session-validation.json",
            ],
        ],
        "postLiveOfflineHandoff": {
            "trigger": "Run only after the YouTube live archive is available.",
            "captionFirst": [
                "Try requested English captions/VTT first.",
                "Translate with gpt-5.5-mini.",
                "Export zh VTT/SRT/playback JS/GCS manifest.",
            ],
            "noCaptionFallback": [
                "If requested English captions are absent, extract authorized archive audio.",
                "Transcribe with gpt-4o-transcribe.",
                "Translate with gpt-5.5-mini.",
                "Validate not_realtime_chain before publishing.",
            ],
            "commands": [
                [
                    "python3",
                    "scripts/write_no_caption_asr_fallback_plan.py",
                    "--sunday",
                    sunday,
                    "--out",
                    "artifacts/evidence/no-caption-asr-fallback-plan.json",
                ],
                [
                    "python3",
                    "scripts/validate_offline_chain.py",
                    "--report",
                    "<OFFLINE_REPORT_JSON>",
                    "--playback-js",
                    "<PLAYBACK_JS>",
                    "--zh-vtt",
                    "<ZH_VTT>",
                    "--zh-srt",
                    "<ZH_SRT>",
                    "--manifest",
                    "<CLOUD_MANIFEST_JSON>",
                    "--expected-asr-model",
                    "gpt-4o-transcribe",
                    "--expected-translation-model",
                    "gpt-5.5-mini",
                    "--out",
                    "artifacts/evidence/offline-chain-validation.json",
                ],
            ],
        },
        "passCriteria": [
            "Realtime session uses gpt-realtime-translate and targetLanguage=zh.",
            "English input transcript deltas and Chinese caption deltas are saved as backend session events.",
            "Public caption view receives caption_delta and caption_final over SSE.",
            "Stable corrections are gpt-5.5-mini caption_final events that match realtime draft segmentId.",
            "Offline post-live route never uses gpt-realtime-translate.",
            "Offline no-caption fallback uses gpt-4o-transcribe before gpt-5.5-mini translation.",
        ],
        "guards": {
            "doesNotCallOpenAI": True,
            "doesNotApplyCloudRun": True,
            "doesNotUploadGcs": True,
            "requiresExplicitOperatorApprovalForMutation": True,
        },
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
