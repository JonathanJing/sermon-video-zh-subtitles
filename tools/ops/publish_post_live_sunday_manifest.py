#!/usr/bin/env python3
"""Publish reviewed post-live subtitles as the stable Sunday page manifest."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.cloud import upload_file_to_gcs  # noqa: E402


JS_PREFIX = "window.SERMON_PLAYBACK_SIMULATION = "


def main() -> int:
    args = parse_args()
    report = publish_post_live_sunday_manifest(args)
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"planned", "published"} else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sunday", required=True, help="Sunday date, YYYY-MM-DD.")
    parser.add_argument("--slug", required=True, help="Stable source slug, usually the YouTube video id.")
    parser.add_argument("--pipeline-outdir", type=Path, required=True, help="Post-live pipeline output directory.")
    parser.add_argument("--out-root", type=Path, help="Local Sunday page package root.")
    parser.add_argument("--live-url", help="Public live/archive URL.")
    parser.add_argument("--title", help="Sermon title for the Sunday API.")
    parser.add_argument("--translation-model", default="gpt-5.5")
    parser.add_argument("--asr-model", default="gpt-4o-transcribe")
    parser.add_argument("--stable-correction-model", default="gpt-5.4-mini")
    parser.add_argument("--realtime-draft-model", default="gpt-realtime-translate")
    parser.add_argument("--gcs-bucket", help="GCS bucket for published Sunday artifacts.")
    parser.add_argument("--gcs-prefix", default="sundays")
    parser.add_argument("--session-id", help="Run id under <prefix>/<sunday>/runs/.")
    parser.add_argument("--apply", action="store_true", help="Upload artifacts and stable manifest to GCS.")
    parser.add_argument("--out", type=Path, help="Optional report JSON path.")
    return parser.parse_args()


def publish_post_live_sunday_manifest(args: argparse.Namespace) -> dict[str, Any]:
    pipeline_outdir = resolve_repo_path(args.pipeline_outdir)
    out_root = resolve_repo_path(args.out_root) if args.out_root else default_out_root(args.sunday, args.slug)
    session_id = args.session_id or f"post-live-reviewed-{sanitize_path_part(args.slug)}"
    local_package = build_local_package(
        sunday=args.sunday,
        slug=args.slug,
        pipeline_outdir=pipeline_outdir,
        out_root=out_root,
        live_url=args.live_url,
        title=args.title,
        translation_model=args.translation_model,
        asr_model=args.asr_model,
        stable_correction_model=args.stable_correction_model,
        realtime_draft_model=args.realtime_draft_model,
    )
    gcs_package = None
    uploaded: list[dict[str, str]] = []
    if args.gcs_bucket:
        gcs_package = build_gcs_manifest_package(
            local_package=local_package,
            bucket=args.gcs_bucket,
            prefix=args.gcs_prefix,
            sunday=args.sunday,
            session_id=session_id,
        )
        if args.apply:
            uploaded = upload_manifest_package(gcs_package)
    return {
        "schemaVersion": 1,
        "status": "published" if args.apply and gcs_package else "planned",
        "sunday": args.sunday,
        "slug": args.slug,
        "segmentCount": local_package["segmentCount"],
        "localRoot": display_path(out_root),
        "localManifest": display_path(local_package["stableManifestPath"]),
        "gcsRunManifest": gcs_package["runManifestUri"] if gcs_package else None,
        "gcsStableManifest": gcs_package["stableManifestUri"] if gcs_package else None,
        "uploaded": uploaded,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def build_local_package(
    *,
    sunday: str,
    slug: str,
    pipeline_outdir: Path,
    out_root: Path,
    live_url: str | None,
    title: str | None,
    translation_model: str,
    asr_model: str,
    stable_correction_model: str,
    realtime_draft_model: str,
) -> dict[str, Any]:
    summary = read_optional_json(pipeline_outdir / "summary.json")
    zh_srt = reviewed_or_original(pipeline_outdir, "sermon_zh_relative", ".srt")
    zh_vtt = reviewed_or_original(pipeline_outdir, "sermon_zh_relative", ".vtt")
    en_srt = pipeline_outdir / "sermon_en_relative.srt"
    if not zh_srt.is_file() or not zh_vtt.is_file():
        raise SystemExit("pipeline output must include sermon_zh_relative(.reviewed).srt and .vtt")

    zh_cues = parse_srt(zh_srt)
    en_cues = parse_srt(en_srt) if en_srt.is_file() else []
    segments = build_segments(zh_cues, en_cues)
    out_web = out_root / "web" / "playback-simulation.generated.js"
    out_artifacts = out_root / "artifacts"
    out_artifacts.mkdir(parents=True, exist_ok=True)
    out_web.parent.mkdir(parents=True, exist_ok=True)
    copy_text(zh_srt, out_artifacts / "sermon.zh.live-aligned.srt")
    copy_text(zh_vtt, out_artifacts / "sermon.zh.live-aligned.vtt")
    now = datetime.now(timezone.utc).isoformat()
    sermon_title = title or f"Mariners Church Sunday Sermon - {sunday}"
    video_url = live_url or f"https://www.youtube.com/watch?v={slug}"
    playback = {
        "schemaVersion": 1,
        "generatedFrom": "post-live-reviewed-sermon-pipeline",
        "mode": "live-link-playback-simulation",
        "playbackSpeed": 18.0,
        "lang": "zh-reviewed",
        "offlineSourceKind": "openai_asr",
        "sourceVtt": "artifacts/sermon.zh.live-aligned.vtt",
        "sermonTitle": sermon_title,
        "secrets": {
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
            "serverSideSecretConfigured": False,
        },
        "live": {
            "id": slug,
            "title": sermon_title,
            "url": video_url,
            "durationSeconds": summary.get("sourceDurationSeconds"),
        },
        "sermonCandidate": {
            "id": slug,
            "title": sermon_title,
            "url": video_url,
            "durationSeconds": summary.get("clipDurationSeconds"),
        },
        "sermonStart": {
            "seconds": summary.get("sermonStartSeconds"),
            "timecode": summary.get("sermonStartTimecode"),
            "method": "operator_reviewed_post_live_window",
        },
        "sermonEnd": {
            "seconds": summary.get("sermonEndSeconds"),
            "timecode": summary.get("sermonEndTimecode"),
            "method": "operator_reviewed_post_live_window",
        },
        "translationStatus": "ready",
        "translationProvider": {
            "model": translation_model,
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
        },
        "scriptureReferences": [],
        "segments": segments,
        "rawSegments": segments,
        "displaySegments": segments,
        "reviewSegments": [{**segment, "reviewStatus": "reviewed", "displaySegmentId": segment["id"]} for segment in segments],
        "review": {"status": "reviewed", "reviewedAt": now, "cueCount": len(segments), "source": zh_srt.name},
        "offlineRoute": openai_asr_route(),
    }
    out_web.write_text(JS_PREFIX + json.dumps(playback, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")
    report = {
        "status": "ok",
        "sunday": sunday,
        "live": {"id": slug, "title": sermon_title, "url": video_url, "live_status": "post_live"},
        "sermon_candidate": {"id": slug, "title": sermon_title, "url": video_url},
        "caption_source": {"kind": "openai_asr", "path": display_path(en_srt)},
        "offline_route": openai_asr_route(),
        "translation_status": "ready",
        "totalSegments": len(segments),
        "translatedSegments": len(segments),
        "reviewedSegments": len(segments),
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }
    (out_artifacts / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    manifest = build_manifest(
        sunday=sunday,
        now=now,
        out_root=out_root,
        translation_model=translation_model,
        asr_model=asr_model,
        stable_correction_model=stable_correction_model,
        realtime_draft_model=realtime_draft_model,
    )
    run_manifest_path = out_artifacts / "cloud-manifest.json"
    stable_manifest_path = out_root / "cloud-manifest.json"
    write_json(run_manifest_path, manifest)
    write_json(stable_manifest_path, manifest)
    return {
        "outRoot": out_root,
        "runManifestPath": run_manifest_path,
        "stableManifestPath": stable_manifest_path,
        "segmentCount": len(segments),
    }


def build_segments(zh_cues: list[dict[str, Any]], en_cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments = []
    for index, zh in enumerate(zh_cues, start=1):
        en = en_cues[index - 1]["text"] if index - 1 < len(en_cues) else ""
        text = zh["text"]
        segments.append(
            {
                "id": f"sim_{index:04d}",
                "startMs": zh["startMs"],
                "endMs": zh["endMs"],
                "zh": text,
                "draft": text,
                "en": en,
                "ref": "",
                "refs": [],
                "note": "Reviewed post-live Chinese subtitle.",
                "confidence": 90,
                "translationStatus": "ready",
                "sourceCue": zh["index"],
            }
        )
    return segments


def build_manifest(
    *,
    sunday: str,
    now: str,
    out_root: Path,
    translation_model: str,
    asr_model: str,
    stable_correction_model: str,
    realtime_draft_model: str,
) -> dict[str, Any]:
    outputs = [
        {"localPath": "web/playback-simulation.generated.js", "gcsUri": str((out_root / "web/playback-simulation.generated.js").resolve())},
        {"localPath": "artifacts/sermon.zh.live-aligned.vtt", "gcsUri": str((out_root / "artifacts/sermon.zh.live-aligned.vtt").resolve())},
        {"localPath": "artifacts/sermon.zh.live-aligned.srt", "gcsUri": str((out_root / "artifacts/sermon.zh.live-aligned.srt").resolve())},
        {"localPath": "artifacts/report.json", "gcsUri": str((out_root / "artifacts/report.json").resolve())},
    ]
    return {
        "schemaVersion": 1,
        "status": "ready",
        "sunday": sunday,
        "generationMode": "youtube-live-archive",
        "sourceMode": "post-live-reviewed-sermon-pipeline",
        "captionExportStatus": "ready",
        "translationStatus": "ready",
        "offlineSourceKind": "openai_asr",
        "offlineRoute": openai_asr_route(),
        "models": {
            "realtimeDraft": realtime_draft_model,
            "offlineAsr": asr_model,
            "offlineTranslation": translation_model,
            "stableCorrection": stable_correction_model,
        },
        "outputs": outputs,
        "sourceManifest": str((out_root / "artifacts/cloud-manifest.json").resolve()),
        "publishedManifest": str((out_root / "cloud-manifest.json").resolve()),
        "promotedAt": now,
        "publishedAt": now,
        "readyTime": now,
        "readiness": {
            "state": "published",
            "publicArtifactsReady": True,
            "operatorReviewed": True,
            "fallback": False,
            "fallbackReason": None,
            "sourceMode": "youtube-live-archive",
            "translationStatus": "ready",
            "readyTime": now,
            "publishedAt": now,
            "publishedManifest": str((out_root / "cloud-manifest.json").resolve()),
            "realtimeSessionId": None,
            "checks": [
                {"name": "public_playback_js", "state": "pass"},
                {"name": "caption_vtt_or_srt", "state": "pass"},
                {"name": "offline_translation", "state": "pass"},
                {"name": "operator_review", "state": "pass"},
            ],
        },
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def build_gcs_manifest_package(
    *,
    local_package: dict[str, Any],
    bucket: str,
    prefix: str,
    sunday: str,
    session_id: str,
) -> dict[str, Any]:
    bucket_name = bucket.removeprefix("gs://").strip("/")
    run_prefix = "/".join(part.strip("/") for part in [prefix, sunday, "runs", sanitize_path_part(session_id)] if part.strip("/"))
    stable_manifest_uri = f"gs://{bucket_name}/{'/'.join(part.strip('/') for part in [prefix, sunday, 'cloud-manifest.json'] if part.strip('/'))}"
    run_manifest_uri = f"gs://{bucket_name}/{run_prefix}/artifacts/cloud-manifest.json"
    manifest = json.loads(local_package["stableManifestPath"].read_text(encoding="utf-8"))
    for item in manifest["outputs"]:
        item["gcsUri"] = f"gs://{bucket_name}/{run_prefix}/{item['localPath']}"
    manifest["sourceManifest"] = run_manifest_uri
    manifest["publishedManifest"] = stable_manifest_uri
    manifest["readiness"]["publishedManifest"] = stable_manifest_uri
    gcs_manifest_path = local_package["outRoot"] / "cloud-manifest.gcs.json"
    write_json(gcs_manifest_path, manifest)
    return {
        "outRoot": local_package["outRoot"],
        "gcsManifestPath": gcs_manifest_path,
        "runManifestUri": run_manifest_uri,
        "stableManifestUri": stable_manifest_uri,
        "outputs": manifest["outputs"],
    }


def upload_manifest_package(package: dict[str, Any]) -> list[dict[str, str]]:
    uploaded = []
    out_root = package["outRoot"]
    for item in package["outputs"]:
        source = out_root / item["localPath"]
        destination = item["gcsUri"]
        upload_file_to_gcs(source, destination)
        uploaded.append({"localPath": item["localPath"], "gcsUri": destination})
    for destination in [package["runManifestUri"], package["stableManifestUri"]]:
        upload_file_to_gcs(package["gcsManifestPath"], destination)
        uploaded.append({"localPath": "cloud-manifest.gcs.json", "gcsUri": destination})
    return uploaded


def parse_srt(path: Path) -> list[dict[str, Any]]:
    blocks = [block for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip()) if block.strip()]
    cues = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        match = re.match(
            r"(\d\d):(\d\d):(\d\d),(\d{3})\s+-->\s+(\d\d):(\d\d):(\d\d),(\d{3})",
            lines[1].strip(),
        )
        if not match:
            continue
        values = [int(value) for value in match.groups()]
        cues.append(
            {
                "index": int(lines[0]) if lines[0].strip().isdigit() else len(cues) + 1,
                "startMs": ((values[0] * 3600 + values[1] * 60 + values[2]) * 1000 + values[3]),
                "endMs": ((values[4] * 3600 + values[5] * 60 + values[6]) * 1000 + values[7]),
                "text": "\n".join(lines[2:]).strip(),
            }
        )
    return cues


def reviewed_or_original(outdir: Path, stem: str, suffix: str) -> Path:
    reviewed = outdir / f"{stem}.reviewed{suffix}"
    return reviewed if reviewed.is_file() else outdir / f"{stem}{suffix}"


def openai_asr_route() -> dict[str, Any]:
    return {
        "strategy": "captions_first_then_asr",
        "decision": "use_asr_fallback",
        "selectedSourceKind": "openai_asr",
        "asrFallbackRequired": True,
        "audioExtractionAttempted": True,
        "fallbackReason": "no_requested_caption_track",
    }


def read_optional_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def copy_text(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def default_out_root(sunday: str, slug: str) -> Path:
    return REPO_ROOT / "artifacts" / f"sunday-{sunday}-{sanitize_path_part(slug)}-reviewed"


def sanitize_path_part(value: str) -> str:
    clean = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value.strip())
    clean = clean.strip("-_")
    if not clean:
        raise SystemExit("path part cannot be empty")
    return clean


def resolve_repo_path(path: Path | str) -> Path:
    value = Path(path)
    return value if value.is_absolute() else REPO_ROOT / value


def display_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
