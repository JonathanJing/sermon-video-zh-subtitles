#!/usr/bin/env python3
"""Write a sanitized plan for proving the real no-caption archive ASR route."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "artifacts" / "evidence" / "no-caption-asr-fallback-plan.json"


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
    parser.add_argument("--session-id", default="no-caption-asr-route")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    run_root = f"artifacts/evidence/{args.sunday}-{args.session_id}"
    artifact_dir = f"{run_root}/artifacts"
    web_out = f"{run_root}/web/playback-simulation.generated.js"
    manifest = f"{artifact_dir}/cloud-manifest.json"
    gcs_bucket = "sermon-zh-artifacts-ai-for-god"
    gcs_prefix = f"sundays/{args.sunday}/runs/{args.session_id}"
    live_url = "<NO_CAPTION_YOUTUBE_LIVE_ARCHIVE_URL>"
    secret = "<OPENAI_API_KEY_SECRET_RESOURCE>"
    return {
        "schemaVersion": 1,
        "status": "needs_real_no_caption_archive",
        "sunday": args.sunday,
        "sessionId": args.session_id,
        "requiredSource": {
            "kind": "youtube_live_archive",
            "captionRequirement": "No requested English caption track is available.",
            "authorizationRequirement": "Use only a source we are authorized to process.",
            "placeholderUrl": live_url,
        },
        "requiredModels": {
            "offlineAsr": "gpt-4o-transcribe",
            "offlineTranslation": "gpt-5.4-mini",
            "forbiddenOfflineModel": "gpt-realtime-translate",
        },
        "runnerCommand": [
            "python3",
            "scripts/run_no_caption_archive_asr_route.py",
            "--live-url",
            live_url,
            "--api-key-secret",
            secret,
            "--sunday",
            args.sunday,
            "--session-id",
            args.session_id,
            "--sermon-start",
            "<SERMON_START_TIMECODE_IF_KNOWN>",
            "--asr-model",
            "gpt-4o-transcribe",
            "--translation-model",
            "gpt-5.4-mini",
            "--out",
            "artifacts/evidence/no-caption-asr-route-run.json",
        ],
        "commands": [
            [
                "python3",
                "scripts/run_offline_archive_preflight.py",
                "--live-url",
                live_url,
                "--no-discover",
                "--lang",
                "en-orig",
                "--lang",
                "en",
                "--sermon-start",
                "<SERMON_START_TIMECODE_IF_KNOWN>",
                "--asr-model",
                "gpt-4o-transcribe",
                "--out",
                "artifacts/evidence/no-caption-archive-preflight.json",
            ],
            [
                "python3",
                "scripts/prepare_live_link_playback.py",
                "--live-url",
                live_url,
                "--no-discover",
                "--lang",
                "en-orig",
                "--lang",
                "en",
                "--sermon-start",
                "<SERMON_START_TIMECODE_IF_KNOWN>",
                "--asr-model",
                "gpt-4o-transcribe",
                "--api-key-secret",
                secret,
                "--out-dir",
                artifact_dir,
                "--web-out",
                web_out,
                "--gcs-bucket",
                gcs_bucket,
                "--gcs-prefix",
                gcs_prefix,
                "--gcs-dry-run",
            ],
            [
                "python3",
                "scripts/translate_playback_with_openai.py",
                "--input",
                web_out,
                "--model",
                "gpt-5.4-mini",
                "--api-key-secret",
                secret,
                "--out",
                web_out,
                "--out-dir",
                f"{run_root}/model-output",
            ],
            [
                "python3",
                "scripts/export_playback_captions.py",
                "--input",
                web_out,
                "--out-dir",
                artifact_dir,
                "--stem",
                "sermon.zh.live-aligned",
                "--manifest",
                manifest,
                "--gcs-bucket",
                gcs_bucket,
                "--gcs-prefix",
                gcs_prefix,
                "--gcs-dry-run",
            ],
            [
                "python3",
                "scripts/validate_offline_chain.py",
                "--report",
                f"{artifact_dir}/report.json",
                "--playback-js",
                web_out,
                "--zh-vtt",
                f"{artifact_dir}/sermon.zh.live-aligned.vtt",
                "--zh-srt",
                f"{artifact_dir}/sermon.zh.live-aligned.srt",
                "--manifest",
                manifest,
                "--expected-asr-model",
                "gpt-4o-transcribe",
                "--expected-translation-model",
                "gpt-5.4-mini",
                "--out",
                "artifacts/evidence/no-caption-offline-chain-validation.json",
            ],
            [
                "python3",
                "scripts/validate_production_readiness.py",
                "--offline-report",
                f"{artifact_dir}/report.json",
                "--playback-js",
                web_out,
                "--zh-vtt",
                f"{artifact_dir}/sermon.zh.live-aligned.vtt",
                "--zh-srt",
                f"{artifact_dir}/sermon.zh.live-aligned.srt",
                "--sunday-manifest",
                manifest,
                "--allow-missing-realtime",
                "--out",
                "artifacts/evidence/asr-route-readiness.json",
            ],
        ],
        "passCriteria": [
            "run_offline_archive_preflight.py reports decision=use_asr_fallback.",
            "prepare_live_link_playback.py runs offline_live_sermon_subtitles.py, builds playback JS, and writes a cloud-manifest.json dry-run manifest.",
            "Prepared offline report has caption_source.kind=openai_asr.",
            "validate_offline_chain.py confirms no requested English caption track exists before ASR fallback.",
            "validate_offline_chain.py confirms the openai_asr output source_file is an extracted audio artifact.",
            "ASR model is gpt-4o-transcribe.",
            "Chinese translation model is gpt-5.4-mini.",
            "validate_offline_chain.py status is ok and not_realtime_chain passes.",
            "validate_production_readiness.py output records offlineRoute.decision=use_asr_fallback.",
        ],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
