#!/usr/bin/env python3
"""Validate a Sunday caption manifest against the production caption contract."""

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
EXPECTED_MODELS = {
    "realtimeDraft": "gpt-realtime-translate",
    "offlineAsr": "gpt-4o-transcribe",
    "offlineTranslation": "gpt-5.5-mini",
    "stableCorrection": "gpt-5.5-mini",
}
ALLOWED_OFFLINE_SOURCES = {"live_archive", "sermon_vod", "openai_asr"}
SECRET_PATTERNS = [
    "apiKeySecret",
    "/secrets/",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "BEGIN " + "PRIVATE KEY",
]
RAW_OPENAI_KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{12,}")


def main() -> int:
    args = parse_args()
    try:
        manifest = read_json(args.manifest)
        report = validate_manifest_contract(
            manifest=manifest,
            manifest_uri=args.manifest,
            sunday=args.sunday,
            expected_readiness=args.expected_readiness,
            expected_source_mode=args.expected_source_mode,
            require_readable_artifacts=args.require_readable_artifacts,
        )
    except Exception as exc:
        report = manifest_read_failure_report(args.manifest, args.sunday, exc)
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Local path or gs:// URI for Sunday cloud-manifest.json.")
    parser.add_argument("--sunday", help="Expected Sunday date, YYYY-MM-DD.")
    parser.add_argument("--expected-readiness", default="published")
    parser.add_argument("--expected-source-mode", default="youtube-live-archive")
    parser.add_argument(
        "--require-readable-artifacts",
        action="store_true",
        help="Fail if playback JS and Chinese VTT/SRT cannot be read from their manifest output URIs.",
    )
    parser.add_argument("--out", type=Path, help="Optional JSON report path.")
    return parser.parse_args()


def validate_manifest_contract(
    *,
    manifest: dict[str, Any],
    manifest_uri: str,
    sunday: str | None = None,
    expected_readiness: str = "published",
    expected_source_mode: str = "youtube-live-archive",
    require_readable_artifacts: bool = False,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    outputs = manifest_outputs(manifest)
    artifact_location = artifact_location_for(manifest_uri=manifest_uri, outputs=outputs)
    public_gcs_artifacts = artifact_location == "gcs"
    local_paths = {item.get("localPath", "") for item in outputs}
    playback_output = find_output(outputs, "web/playback-simulation.generated.js")
    zh_vtt_outputs = [item for item in outputs if is_chinese_caption(item.get("localPath", "")) and item.get("localPath", "").endswith(".vtt")]
    zh_srt_outputs = [item for item in outputs if is_chinese_caption(item.get("localPath", "")) and item.get("localPath", "").endswith(".srt")]

    add_check(checks, "manifest_status", manifest.get("status") in {"ready", "fallback"}, manifest.get("status"))
    if sunday:
        add_check(checks, "sunday", manifest.get("sunday") == sunday, manifest.get("sunday"))
    add_check(checks, "readiness_state", nested(manifest, "readiness", "state") == expected_readiness, nested(manifest, "readiness", "state"))
    add_check(checks, "source_mode", (manifest.get("generationMode") or nested(manifest, "readiness", "sourceMode")) == expected_source_mode, manifest.get("generationMode") or nested(manifest, "readiness", "sourceMode"))
    add_check(checks, "translation_status", manifest.get("translationStatus") == "ready", manifest.get("translationStatus"))
    add_check(checks, "public_playback_js", playback_output is not None, sorted(local_paths))
    add_check(checks, "chinese_vtt", bool(zh_vtt_outputs), sorted(local_paths))
    add_check(checks, "chinese_srt", bool(zh_srt_outputs), sorted(local_paths))
    add_check(checks, "secret_flags", manifest.get("apiKeyMaterialIncluded") is not True and manifest.get("secretResourceNamesIncluded") is not True, {"apiKeyMaterialIncluded": manifest.get("apiKeyMaterialIncluded"), "secretResourceNamesIncluded": manifest.get("secretResourceNamesIncluded")})
    add_check(checks, "secret_strings", not contains_secret_material(json.dumps(manifest, ensure_ascii=False)), None)
    add_offline_route_checks(checks, manifest)

    models = manifest.get("models") if isinstance(manifest.get("models"), dict) else {}
    for key, expected in EXPECTED_MODELS.items():
        add_check(checks, f"model_{key}", models.get(key) == expected, models.get(key))

    playback_summary = None
    if playback_output:
        playback_summary = validate_playback_output(
            playback_output,
            manifest_uri=manifest_uri,
            require_readable=require_readable_artifacts,
        )
        checks.extend(playback_summary["checks"])
        playback_source = nested(playback_summary, "summary", "offlineSourceKind")
        if playback_source:
            add_check(
                checks,
                "playback_offline_source_matches_manifest",
                playback_source == manifest.get("offlineSourceKind"),
                {"playback": playback_source, "manifest": manifest.get("offlineSourceKind")},
            )

    caption_summaries = []
    for output in [*zh_vtt_outputs[:1], *zh_srt_outputs[:1]]:
        caption_summary = validate_caption_output(
            output,
            manifest_uri=manifest_uri,
            require_readable=require_readable_artifacts,
        )
        caption_summaries.append(caption_summary)
        checks.extend(caption_summary["checks"])

    failed = [check for check in checks if check["state"] == "fail"]
    return {
        "schemaVersion": 1,
        "status": "failed" if failed else "ok",
        "manifest": manifest_uri,
        "artifactLocation": artifact_location,
        "publicGcsArtifacts": public_gcs_artifacts,
        "readableArtifactsRequired": require_readable_artifacts,
        "sunday": manifest.get("sunday"),
        "checks": checks,
        "failedChecks": [check["name"] for check in failed],
        "outputs": {
            "playbackJs": playback_output.get("localPath") if playback_output else None,
            "chineseVtt": [item.get("localPath") for item in zh_vtt_outputs],
            "chineseSrt": [item.get("localPath") for item in zh_srt_outputs],
        },
        "playback": playback_summary.get("summary") if playback_summary else None,
        "offlineRoute": {
            "offlineSourceKind": manifest.get("offlineSourceKind"),
            "decision": nested(manifest, "offlineRoute", "decision"),
            "selectedSourceKind": nested(manifest, "offlineRoute", "selectedSourceKind"),
            "asrFallbackRequired": nested(manifest, "offlineRoute", "asrFallbackRequired"),
            "audioExtractionAttempted": nested(manifest, "offlineRoute", "audioExtractionAttempted"),
        },
        "captions": [item["summary"] for item in caption_summaries],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def validate_playback_output(output: dict[str, str], *, manifest_uri: str, require_readable: bool) -> dict[str, Any]:
    uri = output_uri(output, manifest_uri)
    checks: list[dict[str, Any]] = []
    if uri.startswith("gs://") and not require_readable:
        add_check(checks, "playback_readable", True, "not_checked")
        return {"checks": checks, "summary": {"uri": safe_uri(uri), "readable": None, "readabilityChecked": False}}
    try:
        text = read_text(uri)
    except Exception as exc:
        add_check(checks, "playback_readable", not require_readable, str(exc)[:160])
        return {"checks": checks, "summary": {"uri": safe_uri(uri), "readable": False}}
    add_check(checks, "playback_readable", True, safe_uri(uri))
    add_check(checks, "playback_secret_strings", not contains_secret_material(text), None)
    if not text.startswith(JS_PREFIX):
        add_check(checks, "playback_js_shape", False, "missing window.SERMON_PLAYBACK_SIMULATION prefix")
        return {"checks": checks, "summary": {"uri": safe_uri(uri), "readable": True}}
    data = json.loads(text[len(JS_PREFIX) :].strip().rstrip(";"))
    segments = data.get("segments") if isinstance(data, dict) else None
    translated = translated_segment_count(segments if isinstance(segments, list) else [])
    total = len(segments) if isinstance(segments, list) else 0
    add_check(checks, "playback_translation_status", data.get("translationStatus") == "ready", data.get("translationStatus"))
    add_check(checks, "playback_translated_segments", total > 0 and translated == total, {"translated": translated, "total": total})
    provider = data.get("translationProvider") if isinstance(data.get("translationProvider"), dict) else {}
    if provider:
        add_check(checks, "playback_translation_model", provider.get("model") == EXPECTED_MODELS["offlineTranslation"], provider.get("model"))
    offline_source_kind = data.get("offlineSourceKind")
    if offline_source_kind:
        add_check(checks, "playback_offline_source_kind", offline_source_kind in ALLOWED_OFFLINE_SOURCES, offline_source_kind)
    return {
        "checks": checks,
        "summary": {
            "uri": safe_uri(uri),
            "readable": True,
            "translationStatus": data.get("translationStatus"),
            "translatedSegments": translated,
            "totalSegments": total,
            "offlineSourceKind": offline_source_kind,
        },
    }


def add_offline_route_checks(checks: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    route = manifest.get("offlineRoute") if isinstance(manifest.get("offlineRoute"), dict) else {}
    source_kind = manifest.get("offlineSourceKind")
    decision = route.get("decision")
    add_check(checks, "offline_source_kind", source_kind in ALLOWED_OFFLINE_SOURCES, source_kind)
    add_check(checks, "offline_route_strategy", route.get("strategy") == "captions_first_then_asr", route.get("strategy"))
    add_check(checks, "offline_route_source_match", route.get("selectedSourceKind") == source_kind, {"route": route.get("selectedSourceKind"), "manifest": source_kind})
    add_check(checks, "offline_route_decision", decision in {"use_caption_track", "use_asr_fallback"}, decision)
    if decision == "use_caption_track":
        add_check(
            checks,
            "offline_route_caption_priority",
            source_kind in {"live_archive", "sermon_vod"}
            and route.get("asrFallbackRequired") is False
            and route.get("audioExtractionAttempted") is False,
            route,
        )
    elif decision == "use_asr_fallback":
        add_check(
            checks,
            "offline_route_asr_fallback",
            source_kind == "openai_asr"
            and route.get("asrFallbackRequired") is True
            and route.get("audioExtractionAttempted") is True
            and route.get("fallbackReason") == "no_requested_caption_track",
            route,
        )


def validate_caption_output(output: dict[str, str], *, manifest_uri: str, require_readable: bool) -> dict[str, Any]:
    uri = output_uri(output, manifest_uri)
    suffix = Path(output.get("localPath", "")).suffix.lower()
    checks: list[dict[str, Any]] = []
    if uri.startswith("gs://") and not require_readable:
        add_check(checks, f"caption_readable_{suffix[1:]}", True, "not_checked")
        return {
            "checks": checks,
            "summary": {"uri": safe_uri(uri), "readable": None, "readabilityChecked": False, "type": suffix},
        }
    try:
        text = read_text(uri)
    except Exception as exc:
        add_check(checks, f"caption_readable_{suffix[1:]}", not require_readable, str(exc)[:160])
        return {"checks": checks, "summary": {"uri": safe_uri(uri), "readable": False, "type": suffix}}
    add_check(checks, f"caption_readable_{suffix[1:]}", True, safe_uri(uri))
    add_check(checks, f"caption_secret_strings_{suffix[1:]}", not contains_secret_material(text), None)
    if suffix == ".vtt":
        add_check(checks, "caption_vtt_shape", text.lstrip().startswith("WEBVTT"), first_line(text))
    elif suffix == ".srt":
        add_check(checks, "caption_srt_shape", "-->" in text and re.search(r"\d\d:\d\d:\d\d,\d{3}", text) is not None, first_line(text))
    add_check(checks, f"caption_has_chinese_{suffix[1:]}", contains_cjk(text), None)
    return {
        "checks": checks,
        "summary": {
            "uri": safe_uri(uri),
            "readable": True,
            "type": suffix,
            "characters": len(text),
        },
    }


def manifest_outputs(manifest: dict[str, Any]) -> list[dict[str, str]]:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        return []
    return [item for item in outputs if isinstance(item, dict)]


def artifact_location_for(*, manifest_uri: str, outputs: list[dict[str, str]]) -> str:
    output_uris = [str(item.get("gcsUri") or "") for item in outputs if isinstance(item, dict)]
    if manifest_uri.startswith("gs://") and output_uris and all(uri.startswith("gs://") for uri in output_uris):
        return "gcs"
    if manifest_uri.startswith("gs://"):
        return "mixed"
    return "local"


def find_output(outputs: list[dict[str, str]], local_path: str) -> dict[str, str] | None:
    for item in outputs:
        if item.get("localPath") == local_path:
            return item
    return None


def is_chinese_caption(path: str) -> bool:
    clean = path.lower()
    return path.endswith((".vtt", ".srt")) and any(marker in clean for marker in [".zh.", "zh-hans", "zh_cn", "zh-cn"])


def output_uri(output: dict[str, str], manifest_uri: str) -> str:
    gcs_uri = str(output.get("gcsUri") or "")
    if gcs_uri:
        return gcs_uri
    local_path = str(output.get("localPath") or "")
    if manifest_uri.startswith("gs://"):
        base = manifest_uri.rsplit("/", 1)[0]
        return f"{base}/{local_path}"
    return str((Path(manifest_uri).parent / local_path).resolve())


def read_json(uri: str) -> dict[str, Any]:
    data = json.loads(read_text(uri))
    if not isinstance(data, dict):
        raise SystemExit("Manifest must be a JSON object.")
    return data


def manifest_read_failure_report(manifest_uri: str, sunday: str | None, exc: Exception) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "status": "failed",
        "manifest": manifest_uri,
        "artifactLocation": "gcs" if manifest_uri.startswith("gs://") else "local",
        "publicGcsArtifacts": False,
        "readableArtifactsRequired": True,
        "sunday": sunday,
        "checks": [
            {
                "name": "manifest_readable",
                "state": "fail",
                "observed": sanitize_error(str(exc)[:300]),
            }
        ],
        "failedChecks": ["manifest_readable"],
        "outputs": {"playbackJs": None, "chineseVtt": [], "chineseSrt": []},
        "playback": None,
        "captions": [],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def read_text(uri: str) -> str:
    if uri.startswith("gs://"):
        completed = subprocess.run(["gcloud", "storage", "cat", uri], check=True, capture_output=True, text=True)
        return completed.stdout
    return Path(uri).read_text(encoding="utf-8")


def translated_segment_count(segments: list[Any]) -> int:
    count = 0
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        zh = str(segment.get("zh") or "").strip()
        if segment.get("translationStatus") == "ready" and zh and not zh.startswith("AI 中文待生成"):
            count += 1
    return count


def add_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any = None) -> None:
    checks.append({"name": name, "state": "pass" if passed else "fail", "observed": observed})


def nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def contains_secret_material(text: str) -> bool:
    return any(pattern in text for pattern in SECRET_PATTERNS) or RAW_OPENAI_KEY_RE.search(text) is not None


def sanitize_error(text: str) -> str:
    text = RAW_OPENAI_KEY_RE.sub("sk-REDACTED", text)
    text = re.sub(r"projects/[^/\s]+/secrets/[^/\s]+(?:/versions/[^/\s]+)?", "projects/REDACTED/secrets/REDACTED", text)
    return text


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:120]
    return ""


def safe_uri(uri: str) -> str:
    if uri.startswith("gs://"):
        return uri
    path = Path(uri)
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
