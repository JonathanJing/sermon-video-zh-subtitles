#!/usr/bin/env python3
"""Build a local no-caption ASR fallback sample chain from ASR smoke output."""

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

from scripts.export_playback_captions import render_srt, render_vtt, CaptionCue  # noqa: E402
from scripts.validate_offline_chain import (  # noqa: E402
    parse_json_object,
    parse_playback_js,
    read_text as read_validation_text,
    validate_offline_chain,
)


JS_PREFIX = "window.SERMON_PLAYBACK_SIMULATION = "
DEFAULT_OUT_ROOT = Path("artifacts/evidence/no-caption-asr-sample-chain")
DEFAULT_VALIDATION_OUT = Path("artifacts/evidence/no-caption-asr-sample-chain-validation.json")


def main() -> int:
    args = parse_args()
    report = build_sample_chain(args)
    if args.validation_out:
        out = resolve_repo_path(args.validation_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report["validation"], ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asr-smoke-report", type=Path, required=True)
    parser.add_argument("--sunday", required=True)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--validation-out", type=Path, default=DEFAULT_VALIDATION_OUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_ROOT / "sample-chain-report.json")
    return parser.parse_args()


def build_sample_chain(args: argparse.Namespace) -> dict[str, Any]:
    asr_smoke_path = resolve_repo_path(args.asr_smoke_report)
    asr_smoke = read_json(asr_smoke_path)
    if asr_smoke.get("status") != "ok":
        return failure_report(args, asr_smoke, "ASR smoke report is not ok.")
    en_vtt_path = resolve_repo_path(Path(nested(asr_smoke, "outputs", "vtt") or ""))
    if not en_vtt_path.is_file():
        return failure_report(args, asr_smoke, "ASR smoke VTT output is missing.")
    cues = parse_vtt_cues(en_vtt_path.read_text(encoding="utf-8"))
    if not cues:
        return failure_report(args, asr_smoke, "ASR smoke VTT has no cues.")

    out_root = resolve_repo_path(args.out_root)
    artifacts_dir = out_root / "artifacts"
    web_dir = out_root / "web"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    web_dir.mkdir(parents=True, exist_ok=True)

    offline_report_path = artifacts_dir / "report.json"
    playback_path = web_dir / "playback-simulation.generated.js"
    zh_vtt_path = artifacts_dir / "sermon.zh.live-aligned.vtt"
    zh_srt_path = artifacts_dir / "sermon.zh.live-aligned.srt"
    manifest_path = artifacts_dir / "cloud-manifest.json"

    offline_report = build_offline_report(args=args, asr_smoke=asr_smoke)
    segments = translated_segments_from_cues(cues)
    playback = build_playback(args=args, segments=segments)
    zh_cues = [CaptionCue(start_ms=item["startMs"], end_ms=item["endMs"], text=item["zh"]) for item in segments]
    manifest = build_manifest(args=args)

    offline_report_path.write_text(json.dumps(offline_report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    playback_path.write_text(JS_PREFIX + json.dumps(playback, ensure_ascii=False, indent=2, sort_keys=True) + ";\n", encoding="utf-8")
    zh_vtt_path.write_text(render_vtt(zh_cues), encoding="utf-8")
    zh_srt_path.write_text(render_srt(zh_cues), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    validation = validate_offline_chain(
        report=parse_json_object(read_validation_text(str(offline_report_path)), "offline report"),
        report_text=read_validation_text(str(offline_report_path)),
        report_uri=display_path(offline_report_path),
        playback=parse_playback_js(read_validation_text(str(playback_path))),
        playback_text=read_validation_text(str(playback_path)),
        playback_uri=display_path(playback_path),
        zh_vtt_text=read_validation_text(str(zh_vtt_path)),
        zh_vtt_uri=display_path(zh_vtt_path),
        zh_srt_text=read_validation_text(str(zh_srt_path)),
        zh_srt_uri=display_path(zh_srt_path),
        manifest=parse_json_object(read_validation_text(str(manifest_path)), "manifest"),
        manifest_text=read_validation_text(str(manifest_path)),
        manifest_uri=display_path(manifest_path),
    )
    return {
        "schemaVersion": 1,
        "status": "ok" if validation.get("status") == "ok" else "failed",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceEvidence": "authorized_extracted_audio_sample",
        "asrSmokeReport": display_path(asr_smoke_path),
        "outputs": {
            "offlineReport": display_path(offline_report_path),
            "playbackJs": display_path(playback_path),
            "zhVtt": display_path(zh_vtt_path),
            "zhSrt": display_path(zh_srt_path),
            "manifest": display_path(manifest_path),
        },
        "validation": validation,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def build_offline_report(*, args: argparse.Namespace, asr_smoke: dict[str, Any]) -> dict[str, Any]:
    audio_path = nested(asr_smoke, "source", "path")
    return {
        "schemaVersion": 1,
        "status": "ok",
        "sourceEvidence": "authorized_extracted_audio_sample",
        "caption_source": {"kind": "openai_asr"},
        "offline_route": {
            "strategy": "captions_first_then_asr",
            "requestedLangs": ["en-orig", "en"],
            "liveCaptionLangs": [],
            "sermonVodCaptionLangs": [],
            "selectedSourceKind": "openai_asr",
            "decision": "use_asr_fallback",
            "asrFallbackRequired": True,
            "audioExtractionAttempted": True,
            "fallbackReason": "no_requested_caption_track",
            "status": "asr_completed",
        },
        "asr": {"provider": "openai", "model": "gpt-4o-transcribe"},
        "outputs": [
            {
                "lang": "en",
                "cue_count": asr_smoke.get("cueCount"),
                "local_vtt": "artifacts/asr-smoke.en.vtt",
                "local_srt": "artifacts/asr-smoke.en.srt",
                "live_aligned_vtt": "artifacts/asr-smoke.en.vtt",
                "live_aligned_srt": "artifacts/asr-smoke.en.srt",
                "source_kind": "openai_asr",
                "source_file": audio_path,
            }
        ],
        "sunday": args.sunday,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def build_playback(*, args: argparse.Namespace, segments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "generatedFrom": "openai-translation-e2e",
        "mode": "no-caption-asr-sample-chain",
        "translationStatus": "ready",
        "offlineSourceKind": "openai_asr",
        "offlineRoute": offline_route(),
        "translationProvider": {
            "provider": "openai",
            "model": "gpt-5.4-mini",
            "sourceEvidence": "sample_fixture_from_asr_smoke",
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
        },
        "sunday": args.sunday,
        "segments": segments,
    }


def build_manifest(*, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "status": "ready",
        "sunday": args.sunday,
        "offlineSourceKind": "openai_asr",
        "offlineRoute": offline_route(),
        "models": {
            "realtimeDraft": "gpt-realtime-translate",
            "offlineAsr": "gpt-4o-transcribe",
            "offlineTranslation": "gpt-5.4-mini",
            "stableCorrection": "gpt-5.4-mini",
        },
        "outputs": [
            {"localPath": "web/playback-simulation.generated.js", "gcsUri": ""},
            {"localPath": "artifacts/sermon.zh.live-aligned.vtt", "gcsUri": ""},
            {"localPath": "artifacts/sermon.zh.live-aligned.srt", "gcsUri": ""},
        ],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def offline_route() -> dict[str, Any]:
    return {
        "strategy": "captions_first_then_asr",
        "decision": "use_asr_fallback",
        "selectedSourceKind": "openai_asr",
        "asrFallbackRequired": True,
        "audioExtractionAttempted": True,
        "fallbackReason": "no_requested_caption_track",
    }


def translated_segments_from_cues(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments = []
    for index, cue in enumerate(cues, start=1):
        segments.append(
            {
                "id": f"asr_sample_{index:04d}",
                "startMs": cue["startMs"],
                "endMs": cue["endMs"],
                "en": cue["text"],
                "zh": f"示例 ASR fallback 中文翻译第{index}段。",
                "translationStatus": "ready",
                "note": "Sample chain fixture; real archive still requires gpt-5.4-mini translation evidence.",
            }
        )
    return segments


def parse_vtt_cues(text: str) -> list[dict[str, Any]]:
    cues = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if "-->" not in line:
            index += 1
            continue
        start_text, end_text = [part.strip() for part in line.split("-->", 1)]
        index += 1
        body = []
        while index < len(lines) and lines[index].strip():
            body.append(lines[index].strip())
            index += 1
        cues.append(
            {
                "startMs": parse_timestamp_ms(start_text),
                "endMs": parse_timestamp_ms(end_text),
                "text": " ".join(body).strip(),
            }
        )
    return [cue for cue in cues if cue["text"]]


def parse_timestamp_ms(value: str) -> int:
    match = re.match(r"(?:(\d+):)?(\d\d):(\d\d)\.(\d{3})", value)
    if not match:
        raise SystemExit(f"invalid VTT timestamp: {value}")
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis = int(match.group(4))
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def failure_report(args: argparse.Namespace, asr_smoke: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "status": "failed",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "message": message,
        "asrSmokeStatus": asr_smoke.get("status"),
        "sourceEvidence": "authorized_extracted_audio_sample",
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{display_path(path)} must be a JSON object")
    return data


def nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


if __name__ == "__main__":
    raise SystemExit(main())
