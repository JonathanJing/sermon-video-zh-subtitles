#!/usr/bin/env python3
"""Run the real no-caption archive ASR fallback chain end to end."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUCKET = "sermon-zh-artifacts-ai-for-god"
DEFAULT_SESSION_ID = "no-caption-asr-route"
DEFAULT_ASR_MODEL = "gpt-4o-transcribe"
DEFAULT_TRANSLATION_MODEL = "gpt-5.4-mini"
SECRET_RESOURCE_RE = re.compile(
    r"^projects/[^/\s]+/secrets/[^/\s]+(?:/versions/[^/\s]+)?$"
)
SECRET_RESOURCE_VALUE_RE = re.compile(
    r"projects/[^/\s,'\"]+/secrets/[^/\s,'\"]+(?:/versions/[^/\s,'\"]+)?"
)


def main() -> int:
    args = parse_args()
    report = run_route(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-url", required=True, help="Authorized YouTube live archive URL without requested captions.")
    parser.add_argument("--api-key-secret", required=True, help="Secret Manager resource for the OpenAI API key.")
    parser.add_argument("--sunday", required=True)
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--lang", action="append", default=["en-orig", "en"])
    parser.add_argument("--asr-model", default=DEFAULT_ASR_MODEL)
    parser.add_argument("--translation-model", default=DEFAULT_TRANSLATION_MODEL)
    parser.add_argument("--gcs-bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--gcs-prefix")
    parser.add_argument("--apply-gcs", action="store_true", help="Upload generated route artifacts instead of dry-running GCS writes.")
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--out", type=Path, default=Path("artifacts/evidence/no-caption-asr-route-run.json"))
    args = parser.parse_args()
    validate_args(args)
    args.run_root = resolve_repo_path(
        args.run_root or Path("artifacts/evidence") / f"{args.sunday}-{args.session_id}"
    )
    args.out = resolve_repo_path(args.out)
    if not args.gcs_prefix:
        args.gcs_prefix = f"sundays/{args.sunday}/runs/{args.session_id}"
    return args


def validate_args(args: argparse.Namespace) -> None:
    if args.asr_model != DEFAULT_ASR_MODEL:
        raise SystemExit("Offline no-caption ASR fallback must use gpt-4o-transcribe.")
    if args.translation_model != DEFAULT_TRANSLATION_MODEL:
        raise SystemExit("Offline no-caption translation must use gpt-5.4-mini.")
    if args.asr_model == "gpt-realtime-translate" or args.translation_model == "gpt-realtime-translate":
        raise SystemExit("Offline post-live route must not use gpt-realtime-translate.")
    if not SECRET_RESOURCE_RE.fullmatch(args.api_key_secret):
        raise SystemExit("--api-key-secret must be a Secret Manager resource name, not raw key material.")


def run_route(args: argparse.Namespace) -> dict[str, Any]:
    paths = route_paths(args)
    commands = route_commands(args, paths)
    steps: list[dict[str, Any]] = []
    for command in commands:
        step = run_step(command)
        steps.append(step)
        if step["status"] != "ok":
            break

    status = "ok" if len(steps) == len(commands) and all(step["status"] == "ok" for step in steps) else "failed"
    validation = route_validation_summary(paths) if status == "ok" else {}
    return {
        "schemaVersion": 1,
        "status": status,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sunday": args.sunday,
        "sessionId": args.session_id,
        "source": {
            "kind": "youtube_live_archive",
            "url": redact_url(args.live_url),
            "captionRequirement": "No requested English caption track is available.",
        },
        "models": {
            "offlineAsr": args.asr_model,
            "offlineTranslation": args.translation_model,
            "forbiddenOfflineModel": "gpt-realtime-translate",
        },
        "gcs": {
            "bucket": args.gcs_bucket,
            "prefix": args.gcs_prefix,
            "apply": args.apply_gcs,
        },
        "paths": {name: safe_display_path(path) for name, path in paths.items()},
        "commands": [redact_command(command) for command in commands],
        "steps": steps,
        "failedSteps": [step["name"] for step in steps if step["status"] != "ok"],
        "validation": validation,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def route_paths(args: argparse.Namespace) -> dict[str, Path]:
    artifact_dir = args.run_root / "artifacts"
    web_out = args.run_root / "web" / "playback-simulation.generated.js"
    return {
        "runRoot": args.run_root,
        "artifactDir": artifact_dir,
        "webOut": web_out,
        "manifest": artifact_dir / "cloud-manifest.json",
        "preflight": args.run_root / "no-caption-archive-preflight.json",
        "translationOutDir": args.run_root / "model-output",
        "offlineChainValidation": REPO_ROOT / "artifacts/evidence/no-caption-offline-chain-validation.json",
        "routeReadiness": REPO_ROOT / "artifacts/evidence/asr-route-readiness.json",
        "zhVtt": artifact_dir / "sermon.zh.live-aligned.vtt",
        "zhSrt": artifact_dir / "sermon.zh.live-aligned.srt",
        "offlineReport": artifact_dir / "report.json",
    }


def route_commands(args: argparse.Namespace, paths: dict[str, Path]) -> list[list[str]]:
    lang_args = repeat("--lang", args.lang)
    gcs_mode_args = [] if args.apply_gcs else ["--gcs-dry-run"]
    return [
        [
            sys.executable,
            "scripts/run_offline_archive_preflight.py",
            "--live-url",
            args.live_url,
            *lang_args,
            "--asr-model",
            args.asr_model,
            "--out",
            str(paths["preflight"]),
        ],
        [
            sys.executable,
            "scripts/prepare_live_link_playback.py",
            "--live-url",
            args.live_url,
            *lang_args,
            "--asr-model",
            args.asr_model,
            "--api-key-secret",
            args.api_key_secret,
            "--out-dir",
            str(paths["artifactDir"]),
            "--web-out",
            str(paths["webOut"]),
            "--gcs-bucket",
            args.gcs_bucket,
            "--gcs-prefix",
            args.gcs_prefix,
            *gcs_mode_args,
        ],
        [
            sys.executable,
            "scripts/translate_playback_with_openai.py",
            "--input",
            str(paths["webOut"]),
            "--model",
            args.translation_model,
            "--api-key-secret",
            args.api_key_secret,
            "--out",
            str(paths["webOut"]),
            "--out-dir",
            str(paths["translationOutDir"]),
        ],
        [
            sys.executable,
            "scripts/export_playback_captions.py",
            "--input",
            str(paths["webOut"]),
            "--out-dir",
            str(paths["artifactDir"]),
            "--stem",
            "sermon.zh.live-aligned",
            "--manifest",
            str(paths["manifest"]),
            "--gcs-bucket",
            args.gcs_bucket,
            "--gcs-prefix",
            args.gcs_prefix,
            *gcs_mode_args,
        ],
        [
            sys.executable,
            "scripts/validate_offline_chain.py",
            "--report",
            str(paths["offlineReport"]),
            "--playback-js",
            str(paths["webOut"]),
            "--zh-vtt",
            str(paths["zhVtt"]),
            "--zh-srt",
            str(paths["zhSrt"]),
            "--manifest",
            str(paths["manifest"]),
            "--expected-asr-model",
            args.asr_model,
            "--expected-translation-model",
            args.translation_model,
            "--out",
            str(paths["offlineChainValidation"]),
        ],
        [
            sys.executable,
            "scripts/validate_production_readiness.py",
            "--offline-report",
            str(paths["offlineReport"]),
            "--playback-js",
            str(paths["webOut"]),
            "--zh-vtt",
            str(paths["zhVtt"]),
            "--zh-srt",
            str(paths["zhSrt"]),
            "--run-manifest",
            str(paths["manifest"]),
            "--sunday-manifest",
            str(paths["manifest"]),
            "--sunday",
            args.sunday,
            "--allow-missing-realtime",
            "--out",
            str(paths["routeReadiness"]),
        ],
    ]


def run_step(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False, capture_output=True, text=True)
    return {
        "name": step_name(command),
        "status": "ok" if completed.returncode == 0 else "failed",
        "returnCode": completed.returncode,
        "command": redact_command(command),
        "stdoutTail": sanitize_tail(completed.stdout),
        "stderrTail": sanitize_tail(completed.stderr),
    }


def route_validation_summary(paths: dict[str, Path]) -> dict[str, Any]:
    return {
        "offlineChain": compact_offline_chain_validation(
            read_optional_json(paths["offlineChainValidation"])
        ),
        "routeReadiness": compact_route_readiness(
            read_optional_json(paths["routeReadiness"])
        ),
    }


def read_optional_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def compact_offline_chain_validation(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    return {
        "status": report.get("status"),
        "failedChecks": report.get("failedChecks") or [],
        "offlineRoute": report.get("offlineRoute"),
        "sourceEvidence": report.get("sourceEvidence"),
        "asr": report.get("asr"),
        "translation": report.get("translation"),
        "notRealtimeChain": check_state(report, "not_realtime_chain"),
        "timelineAlignment": {
            "zhVtt": check_state(report, "zh_vtt_timeline_alignment"),
            "zhSrt": check_state(report, "zh_srt_timeline_alignment"),
        },
    }


def compact_route_readiness(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    return {
        "status": report.get("status"),
        "failedChecks": report.get("failedChecks") or [],
        "warnings": report.get("warnings") or [],
        "offline": report.get("offline"),
        "sundayManifest": report.get("sundayManifest"),
        "realtime": report.get("realtime"),
        "secretFlags": {
            "apiKeyMaterialIncluded": report.get("apiKeyMaterialIncluded"),
            "secretResourceNamesIncluded": report.get("secretResourceNamesIncluded"),
        },
    }


def check_state(report: dict[str, Any], name: str) -> str | None:
    for check in report.get("checks") or []:
        if isinstance(check, dict) and check.get("name") == name:
            return check.get("state")
    return None


def step_name(command: list[str]) -> str:
    for item in command:
        if item.startswith("scripts/") and item.endswith(".py"):
            return Path(item).stem
    return Path(command[0]).stem if command else "unknown"


def repeat(flag: str, values: list[str]) -> list[str]:
    args: list[str] = []
    for value in values:
        args.extend([flag, value])
    return args


def redact_command(command: list[str]) -> list[str]:
    redacted = []
    redact_next = False
    for item in command:
        if redact_next:
            redacted.append("<redacted-secret-resource>")
            redact_next = False
            continue
        if item == "--live-url":
            redacted.append(item)
            redact_next = False
            continue
        redacted.append(redact_url(item) if is_probable_url(item) else item)
        if item == "--api-key-secret":
            redact_next = True
    return redacted


def sanitize_tail(text: str) -> str:
    clean = str(text or "")
    clean = re.sub(r"\bsk-[A-Za-z0-9_-]+", "sk-REDACTED", clean)
    clean = SECRET_RESOURCE_VALUE_RE.sub("projects/REDACTED/secrets/REDACTED/versions/REDACTED", clean)
    return clean[-2500:] if len(clean) > 2500 else clean


def redact_url(value: str) -> str:
    if not is_probable_url(value):
        return value
    clean = re.sub(r"([?&](?:key|token|sig|signature|auth|access_token)=)[^&]+", r"\1REDACTED", value)
    return clean


def is_probable_url(value: str) -> bool:
    return str(value).startswith(("http://", "https://"))


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def safe_display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.name


if __name__ == "__main__":
    raise SystemExit(main())
