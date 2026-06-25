#!/usr/bin/env python3
"""Validate the offline YouTube archive caption generation chain."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
JS_PREFIX = "window.SERMON_PLAYBACK_SIMULATION = "
EXPECTED_ASR_MODEL = "gpt-4o-transcribe"
EXPECTED_TRANSLATION_MODEL = "gpt-5.5-mini"
EXPECTED_REALTIME_MODEL = "gpt-realtime-translate"
ALLOWED_OFFLINE_SOURCES = {"live_archive", "sermon_vod", "openai_asr"}
AUDIO_SOURCE_EXTENSIONS = {".aac", ".aiff", ".caf", ".flac", ".m4a", ".mp3", ".wav"}
SECRET_PATTERNS = [
    "apiKeySecret",
    "Authorization",
    "Bearer ",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "/secrets/",
    "BEGIN " + "PRIVATE KEY",
]
RAW_OPENAI_KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{12,}")


def main() -> int:
    args = parse_args()
    inputs, input_errors = read_cli_inputs(args)
    if input_errors:
        validation = missing_input_report(args, input_errors)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    report_text = inputs["report"]
    playback_text = inputs["playback_js"]
    zh_vtt_text = inputs["zh_vtt"]
    zh_srt_text = inputs["zh_srt"]
    manifest_text = inputs.get("manifest")

    report = parse_json_object(report_text, "offline report")
    playback = parse_playback_js(playback_text)
    manifest = parse_json_object(manifest_text, "manifest") if manifest_text is not None else None
    validation = validate_offline_chain(
        report=report,
        report_text=report_text,
        report_uri=args.report,
        playback=playback,
        playback_text=playback_text,
        playback_uri=args.playback_js,
        zh_vtt_text=zh_vtt_text,
        zh_vtt_uri=args.zh_vtt,
        zh_srt_text=zh_srt_text,
        zh_srt_uri=args.zh_srt,
        manifest=manifest,
        manifest_text=manifest_text,
        manifest_uri=args.manifest,
        expected_asr_model=args.expected_asr_model,
        expected_translation_model=args.expected_translation_model,
    )
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if validation["status"] == "ok" else 2


def read_cli_inputs(args: argparse.Namespace) -> tuple[dict[str, str], list[dict[str, str]]]:
    specs = [
        ("report", args.report),
        ("playback_js", args.playback_js),
        ("zh_vtt", args.zh_vtt),
        ("zh_srt", args.zh_srt),
    ]
    if args.manifest:
        specs.append(("manifest", args.manifest))
    values: dict[str, str] = {}
    errors: list[dict[str, str]] = []
    for name, uri in specs:
        try:
            values[name] = read_text(uri)
        except Exception as exc:
            errors.append({"name": name, "uri": safe_uri(uri), "error": str(exc)[:240]})
    return values, errors


def missing_input_report(args: argparse.Namespace, errors: list[dict[str, str]]) -> dict[str, Any]:
    checks = [
        {
            "name": f"input_readable_{error['name']}",
            "state": "fail",
            "observed": {"uri": error["uri"], "error": error["error"]},
        }
        for error in errors
    ]
    return {
        "schemaVersion": 1,
        "status": "failed",
        "failedChecks": [check["name"] for check in checks],
        "checks": checks,
        "inputs": {
            "report": safe_uri(args.report),
            "playbackJs": safe_uri(args.playback_js),
            "zhVtt": safe_uri(args.zh_vtt),
            "zhSrt": safe_uri(args.zh_srt),
            "manifest": safe_uri(args.manifest) if args.manifest else None,
        },
        "offlineSourceKind": None,
        "offlineRoute": None,
        "asr": {"model": None, "used": None},
        "translation": {"model": None, "translatedSegments": 0, "totalSegments": 0},
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, help="offline_live_sermon_subtitles.py report.json path or gs:// URI.")
    parser.add_argument("--playback-js", required=True, help="Translated playback simulation JS path or gs:// URI.")
    parser.add_argument("--zh-vtt", required=True, help="Exported Chinese VTT path or gs:// URI.")
    parser.add_argument("--zh-srt", required=True, help="Exported Chinese SRT path or gs:// URI.")
    parser.add_argument("--manifest", help="Optional cloud-manifest.json path or gs:// URI.")
    parser.add_argument("--expected-asr-model", default=EXPECTED_ASR_MODEL)
    parser.add_argument("--expected-translation-model", default=EXPECTED_TRANSLATION_MODEL)
    parser.add_argument("--out", help="Optional JSON validation report path.")
    return parser.parse_args()


def validate_offline_chain(
    *,
    report: dict[str, Any],
    report_text: str,
    report_uri: str,
    playback: dict[str, Any],
    playback_text: str,
    playback_uri: str,
    zh_vtt_text: str,
    zh_vtt_uri: str,
    zh_srt_text: str,
    zh_srt_uri: str,
    manifest: dict[str, Any] | None = None,
    manifest_text: str | None = None,
    manifest_uri: str | None = None,
    expected_asr_model: str = EXPECTED_ASR_MODEL,
    expected_translation_model: str = EXPECTED_TRANSLATION_MODEL,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    caption_source_kind = str(nested(report, "caption_source", "kind") or "")
    route = report.get("offline_route") if isinstance(report.get("offline_route"), dict) else {}
    playback_source_kind = str(playback.get("offlineSourceKind") or "")
    provider = playback.get("translationProvider") if isinstance(playback.get("translationProvider"), dict) else {}
    segments = playback.get("segments") if isinstance(playback.get("segments"), list) else []
    translated_segments = [segment for segment in segments if is_ready_chinese_segment(segment)]
    expected_cues = cues_from_segments(translated_segments)
    zh_vtt_cues = parse_vtt_cues(zh_vtt_text)
    zh_srt_cues = parse_srt_cues(zh_srt_text)
    output_sources = {
        str(output.get("source_kind") or "")
        for output in report.get("outputs", [])
        if isinstance(output, dict)
    }
    outputs = [output for output in report.get("outputs", []) if isinstance(output, dict)]
    artifact_text = report_text + playback_text + zh_vtt_text + zh_srt_text

    add_check(checks, "report_status", report.get("status") == "ok", report.get("status"))
    add_check(checks, "offline_source_kind", caption_source_kind in ALLOWED_OFFLINE_SOURCES, caption_source_kind)
    add_check(
        checks,
        "offline_route_strategy",
        route.get("strategy") == "captions_first_then_asr",
        route.get("strategy"),
    )
    add_check(
        checks,
        "offline_route_source_match",
        not route or route.get("selectedSourceKind") == caption_source_kind,
        {"route": route.get("selectedSourceKind"), "captionSource": caption_source_kind},
    )
    add_check(
        checks,
        "playback_offline_source_kind",
        not playback_source_kind or playback_source_kind == caption_source_kind,
        {"report": caption_source_kind, "playback": playback_source_kind},
    )
    add_check(checks, "not_realtime_chain", "gpt-realtime-translate" not in artifact_text, None)
    add_check(checks, "report_secret_strings", not contains_secret_material(report_text), None)

    if caption_source_kind == "openai_asr":
        add_check(checks, "asr_model", nested(report, "asr", "model") == expected_asr_model, nested(report, "asr", "model"))
        add_check(checks, "asr_output_source", "openai_asr" in output_sources, sorted(output_sources))
        add_check(
            checks,
            "asr_is_caption_fallback",
            route.get("decision") == "use_asr_fallback"
            and route.get("asrFallbackRequired") is True
            and route.get("audioExtractionAttempted") is True
            and route.get("fallbackReason") == "no_requested_caption_track",
            route,
        )
        add_check(
            checks,
            "asr_no_requested_caption_tracks",
            no_requested_caption_tracks(route),
            {
                "requestedLangs": route.get("requestedLangs"),
                "liveCaptionLangs": route.get("liveCaptionLangs"),
                "sermonVodCaptionLangs": route.get("sermonVodCaptionLangs"),
            },
        )
        add_check(
            checks,
            "asr_audio_source_artifact",
            any(is_openai_asr_audio_source(output) for output in outputs),
            [
                {
                    "source_kind": output.get("source_kind"),
                    "source_file": output.get("source_file"),
                }
                for output in outputs
            ],
        )
    else:
        add_check(checks, "caption_priority", caption_source_kind in {"live_archive", "sermon_vod"}, caption_source_kind)
        add_check(
            checks,
            "caption_route_did_not_extract_audio",
            route.get("decision") == "use_caption_track"
            and route.get("asrFallbackRequired") is False
            and route.get("audioExtractionAttempted") is False,
            route,
        )
        add_check(
            checks,
            "caption_route_no_asr_outputs",
            "openai_asr" not in output_sources,
            sorted(output_sources),
        )

    add_check(checks, "playback_secret_strings", not contains_secret_material(playback_text), None)
    add_check(checks, "playback_generated_by_translation", playback.get("generatedFrom") == "openai-translation-e2e", playback.get("generatedFrom"))
    add_check(checks, "playback_translation_status", playback.get("translationStatus") == "ready", playback.get("translationStatus"))
    add_check(checks, "offline_translation_model", provider.get("model") == expected_translation_model, provider.get("model"))
    add_check(checks, "playback_translated_segments", bool(segments) and len(translated_segments) == len(segments), {"translated": len(translated_segments), "total": len(segments)})

    add_check(checks, "zh_vtt_secret_strings", not contains_secret_material(zh_vtt_text), None)
    add_check(checks, "zh_vtt_shape", zh_vtt_text.lstrip().startswith("WEBVTT"), first_line(zh_vtt_text))
    add_check(checks, "zh_vtt_chinese", contains_cjk(zh_vtt_text), None)
    add_check(
        checks,
        "zh_vtt_timeline_alignment",
        captions_align_with_segments(zh_vtt_cues, expected_cues),
        timeline_observed(zh_vtt_cues, expected_cues),
    )
    add_check(checks, "zh_srt_secret_strings", not contains_secret_material(zh_srt_text), None)
    add_check(checks, "zh_srt_shape", "-->" in zh_srt_text and re.search(r"\d\d:\d\d:\d\d,\d{3}", zh_srt_text) is not None, first_line(zh_srt_text))
    add_check(checks, "zh_srt_chinese", contains_cjk(zh_srt_text), None)
    add_check(
        checks,
        "zh_srt_timeline_alignment",
        captions_align_with_segments(zh_srt_cues, expected_cues),
        timeline_observed(zh_srt_cues, expected_cues),
    )

    if manifest is not None and manifest_text is not None:
        manifest_paths = manifest_output_paths(manifest)
        manifest_models = manifest.get("models") if isinstance(manifest.get("models"), dict) else {}
        manifest_route = manifest.get("offlineRoute") if isinstance(manifest.get("offlineRoute"), dict) else {}
        add_check(checks, "manifest_secret_strings", not contains_secret_material(manifest_text), None)
        add_check(
            checks,
            "manifest_offline_source_kind",
            manifest.get("offlineSourceKind") == caption_source_kind,
            {"manifest": manifest.get("offlineSourceKind"), "report": caption_source_kind},
        )
        add_check(
            checks,
            "manifest_offline_route_decision",
            manifest_route.get("decision") == route.get("decision"),
            {"manifest": manifest_route.get("decision"), "report": route.get("decision")},
        )
        add_check(
            checks,
            "manifest_offline_route_source_match",
            manifest_route.get("selectedSourceKind") == caption_source_kind,
            {"manifest": manifest_route.get("selectedSourceKind"), "report": caption_source_kind},
        )
        add_check(
            checks,
            "manifest_offline_route_asr_policy",
            manifest_route.get("asrFallbackRequired") == route.get("asrFallbackRequired")
            and manifest_route.get("audioExtractionAttempted") == route.get("audioExtractionAttempted"),
            {
                "manifest": {
                    "asrFallbackRequired": manifest_route.get("asrFallbackRequired"),
                    "audioExtractionAttempted": manifest_route.get("audioExtractionAttempted"),
                },
                "report": {
                    "asrFallbackRequired": route.get("asrFallbackRequired"),
                    "audioExtractionAttempted": route.get("audioExtractionAttempted"),
                },
            },
        )
        add_check(
            checks,
            "manifest_offline_route_fallback_reason",
            manifest_route.get("fallbackReason") == route.get("fallbackReason"),
            {"manifest": manifest_route.get("fallbackReason"), "report": route.get("fallbackReason")},
        )
        add_check(
            checks,
            "manifest_models_present",
            isinstance(manifest.get("models"), dict),
            manifest.get("models"),
        )
        add_check(
            checks,
            "manifest_realtime_draft_model",
            manifest_models.get("realtimeDraft") == EXPECTED_REALTIME_MODEL,
            manifest_models.get("realtimeDraft"),
        )
        add_check(
            checks,
            "manifest_offline_asr_model",
            manifest_models.get("offlineAsr") == expected_asr_model,
            manifest_models.get("offlineAsr"),
        )
        add_check(
            checks,
            "manifest_offline_translation_model",
            manifest_models.get("offlineTranslation") == expected_translation_model,
            manifest_models.get("offlineTranslation"),
        )
        add_check(
            checks,
            "manifest_stable_correction_model",
            manifest_models.get("stableCorrection") == expected_translation_model,
            manifest_models.get("stableCorrection"),
        )
        add_check(checks, "manifest_playback_js", any(path.endswith("web/playback-simulation.generated.js") for path in manifest_paths), sorted(manifest_paths))
        add_check(checks, "manifest_zh_vtt", any(is_chinese_caption(path) and path.endswith(".vtt") for path in manifest_paths), sorted(manifest_paths))
        add_check(checks, "manifest_zh_srt", any(is_chinese_caption(path) and path.endswith(".srt") for path in manifest_paths), sorted(manifest_paths))

    failed = [check for check in checks if check["state"] == "fail"]
    return {
        "schemaVersion": 1,
        "status": "failed" if failed else "ok",
        "failedChecks": [check["name"] for check in failed],
        "checks": checks,
        "inputs": {
            "report": safe_uri(report_uri),
            "playbackJs": safe_uri(playback_uri),
            "zhVtt": safe_uri(zh_vtt_uri),
            "zhSrt": safe_uri(zh_srt_uri),
            "manifest": safe_uri(manifest_uri) if manifest_uri else None,
        },
        "offlineSourceKind": caption_source_kind,
        "offlineRoute": {
            "strategy": route.get("strategy"),
            "decision": route.get("decision"),
            "selectedSourceKind": route.get("selectedSourceKind"),
            "asrFallbackRequired": route.get("asrFallbackRequired"),
            "audioExtractionAttempted": route.get("audioExtractionAttempted"),
        },
        "asr": {
            "model": nested(report, "asr", "model"),
            "used": caption_source_kind == "openai_asr",
        },
        "translation": {
            "model": provider.get("model"),
            "translatedSegments": len(translated_segments),
            "totalSegments": len(segments),
        },
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def is_ready_chinese_segment(segment: Any) -> bool:
    if not isinstance(segment, dict):
        return False
    zh = str(segment.get("zh") or "").strip()
    return (
        bool(zh)
        and contains_cjk(zh)
        and not zh.startswith("AI 中文待生成")
        and segment.get("translationStatus") == "ready"
    )


def no_requested_caption_tracks(route: dict[str, Any]) -> bool:
    requested = {normalize_lang(lang) for lang in route.get("requestedLangs") or []}
    live = {normalize_lang(lang) for lang in route.get("liveCaptionLangs") or []}
    sermon_vod = {normalize_lang(lang) for lang in route.get("sermonVodCaptionLangs") or []}
    available = live | sermon_vod
    return bool(requested) and not bool(requested & available)


def normalize_lang(value: Any) -> str:
    return str(value or "").strip().lower()


def is_openai_asr_audio_source(output: dict[str, Any]) -> bool:
    if output.get("source_kind") != "openai_asr":
        return False
    source_file = str(output.get("source_file") or "").strip().lower()
    return any(source_file.endswith(extension) for extension in AUDIO_SOURCE_EXTENSIONS)


def cues_from_segments(segments: list[Any]) -> list[dict[str, Any]]:
    cues = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        try:
            start_ms = int(segment.get("startMs") or 0)
            end_ms = int(segment.get("endMs") or 0)
        except (TypeError, ValueError):
            continue
        if end_ms <= start_ms:
            continue
        cues.append(
            {
                "startMs": start_ms,
                "endMs": end_ms,
                "text": str(segment.get("zh") or "").strip(),
            }
        )
    return cues


def read_text(uri: str) -> str:
    if uri.startswith("gs://"):
        completed = subprocess.run(["gcloud", "storage", "cat", uri], check=True, capture_output=True, text=True)
        return completed.stdout
    return Path(uri).read_text(encoding="utf-8")


def parse_json_object(text: str | None, label: str) -> dict[str, Any]:
    if text is None:
        raise SystemExit(f"{label} is missing.")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise SystemExit(f"{label} must be a JSON object.")
    return data


def parse_playback_js(text: str) -> dict[str, Any]:
    if not text.startswith(JS_PREFIX):
        raise SystemExit("Playback JS is missing window.SERMON_PLAYBACK_SIMULATION.")
    payload = text[len(JS_PREFIX) :].strip()
    if payload.endswith(";"):
        payload = payload[:-1]
    return parse_json_object(payload, "playback payload")


def add_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any = None) -> None:
    checks.append({"name": name, "state": "pass" if passed else "fail", "observed": observed})


def parse_vtt_cues(text: str) -> list[dict[str, Any]]:
    return parse_caption_cues(text, separator=".")


def parse_srt_cues(text: str) -> list[dict[str, Any]]:
    return parse_caption_cues(text, separator=",")


def parse_caption_cues(text: str, *, separator: str) -> list[dict[str, Any]]:
    cues = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if "-->" not in line:
            index += 1
            continue
        start_raw, end_raw = [part.strip() for part in line.split("-->", 1)]
        start_ms = parse_caption_time(start_raw, separator=separator)
        end_ms = parse_caption_time(end_raw.split()[0], separator=separator)
        text_lines = []
        index += 1
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index].strip())
            index += 1
        cues.append({"startMs": start_ms, "endMs": end_ms, "text": " ".join(text_lines).strip()})
    return cues


def parse_caption_time(value: str, *, separator: str) -> int:
    clean = value.strip()
    if separator not in clean:
        return -1
    hms, millis = clean.rsplit(separator, 1)
    parts = hms.split(":")
    if len(parts) != 3:
        return -1
    try:
        hours, minutes, seconds = [int(part) for part in parts]
        millis_int = int(millis[:3].ljust(3, "0"))
    except ValueError:
        return -1
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis_int


def captions_align_with_segments(caption_cues: list[dict[str, Any]], expected_cues: list[dict[str, Any]]) -> bool:
    if not expected_cues or len(caption_cues) != len(expected_cues):
        return False
    return all(caption_cue_aligned(cue, expected) for cue, expected in zip(caption_cues, expected_cues))


def caption_cue_aligned(cue: dict[str, Any], expected: dict[str, Any], tolerance_ms: int = 120) -> bool:
    return (
        abs(int(cue.get("startMs") or -1) - int(expected.get("startMs") or 0)) <= tolerance_ms
        and abs(int(cue.get("endMs") or -1) - int(expected.get("endMs") or 0)) <= tolerance_ms
        and contains_cjk(str(cue.get("text") or ""))
    )


def timeline_observed(caption_cues: list[dict[str, Any]], expected_cues: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cueCount": len(caption_cues),
        "expectedCueCount": len(expected_cues),
        "firstCue": compact_cue(caption_cues[0]) if caption_cues else None,
        "firstExpected": compact_cue(expected_cues[0]) if expected_cues else None,
    }


def compact_cue(cue: dict[str, Any]) -> dict[str, Any]:
    return {
        "startMs": cue.get("startMs"),
        "endMs": cue.get("endMs"),
        "hasChinese": contains_cjk(str(cue.get("text") or "")),
    }


def nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def contains_secret_material(text: str) -> bool:
    return any(pattern in text for pattern in SECRET_PATTERNS) or RAW_OPENAI_KEY_RE.search(text) is not None


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:120]
    return ""


def manifest_output_paths(manifest: dict[str, Any]) -> set[str]:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        return set()
    return {
        str(item.get("localPath") or "")
        for item in outputs
        if isinstance(item, dict) and item.get("localPath")
    }


def is_chinese_caption(path: str) -> bool:
    clean = path.lower()
    return any(marker in clean for marker in [".zh.", "zh-hans", "zh_cn", "zh-cn"])


def safe_uri(uri: str | None) -> str | None:
    if uri is None or uri.startswith("gs://"):
        return uri
    path = Path(uri)
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


if __name__ == "__main__":
    raise SystemExit(main())
