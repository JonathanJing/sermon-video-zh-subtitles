#!/usr/bin/env python3
"""Smoke-test the offline ASR fallback on an extracted/authorized audio sample."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPT_DIR = REPO_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import offline_live_sermon_subtitles as offline  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/evidence/offline-asr-fallback-smoke")


def main() -> int:
    args = parse_args()
    report = run_smoke(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audio-file",
        type=Path,
        required=True,
        help="Authorized audio sample, usually extracted from a no-caption archive rehearsal.",
    )
    parser.add_argument("--api-key-secret", required=True, help="Secret Manager resource for the OpenAI API key.")
    parser.add_argument("--model", default=offline.DEFAULT_ASR_MODEL)
    parser.add_argument("--fallback-duration-ms", type=int)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    args.audio_file = resolve_repo_path(args.audio_file)
    args.out_dir = resolve_repo_path(args.out_dir)
    args.out = resolve_repo_path(args.out or (args.out_dir / "report.json"))
    if not args.audio_file.is_file():
        raise SystemExit(f"--audio-file not found: {args.audio_file}")
    offline.validate_secret_resource_name(args.api_key_secret)
    return args


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    try:
        cues = offline.transcribe_audio_to_cues(
            audio_path=args.audio_file,
            api_key_secret=args.api_key_secret,
            model=args.model,
            fallback_duration_ms=args.fallback_duration_ms,
        )
    except Exception as exc:
        return {
            "schemaVersion": 1,
            "status": "failed",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "source": source_summary(args.audio_file),
            "asr": {"provider": "openai", "model": args.model},
            "error": sanitize_error_message(str(exc)),
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
        }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    vtt_path = args.out_dir / "asr-smoke.en.vtt"
    srt_path = args.out_dir / "asr-smoke.en.srt"
    vtt_path.write_text(offline.render_vtt(cues), encoding="utf-8")
    srt_path.write_text(offline.render_srt(cues), encoding="utf-8")
    return {
        "schemaVersion": 1,
        "status": "ok" if cues else "no_cues",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": source_summary(args.audio_file),
        "asr": {"provider": "openai", "model": args.model},
        "cueCount": len(cues),
        "outputs": {
            "vtt": safe_display_path(vtt_path),
            "srt": safe_display_path(srt_path),
        },
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def source_summary(path: Path) -> dict[str, Any]:
    return {
        "kind": "authorized_extracted_audio_sample",
        "path": safe_display_path(path),
        "bytes": path.stat().st_size if path.is_file() else None,
    }


def sanitize_error_message(message: str) -> str:
    clean = str(message or "unknown error")
    clean = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-REDACTED", clean)
    clean = re.sub(
        r"projects/[^/\s]+/secrets/[^/\s]+(?:/versions/[^/\s]+)?",
        "projects/REDACTED/secrets/REDACTED/versions/REDACTED",
        clean,
    )
    return clean[:500]


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
