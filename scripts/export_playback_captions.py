#!/usr/bin/env python3
"""Export translated playback simulation segments as VTT/SRT caption files."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.cloud import upload_file_to_gcs

JS_PREFIX = "window.SERMON_PLAYBACK_SIMULATION = "
PLACEHOLDER_PREFIX = "AI 中文待生成"


@dataclass(frozen=True)
class CaptionCue:
    start_ms: int
    end_ms: int
    text: str


def main() -> int:
    args = parse_args()
    simulation = read_simulation(resolve_repo_path(args.input))
    cues = cues_from_simulation(simulation, lang=args.lang, allow_draft=args.allow_draft)
    if not cues:
        raise SystemExit("No exportable translated caption segments found.")

    out_dir = resolve_repo_path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.stem or default_stem(args.lang)
    vtt_path = out_dir / f"{stem}.vtt"
    srt_path = out_dir / f"{stem}.srt"
    vtt_path.write_text(render_vtt(cues), encoding="utf-8")
    srt_path.write_text(render_srt(cues), encoding="utf-8")

    uploads: list[dict[str, str]] = []
    if args.gcs_bucket:
        uploads = publish_files_to_gcs(
            files=[vtt_path, srt_path],
            bucket=args.gcs_bucket,
            prefix=args.gcs_prefix,
            out_dir=out_dir,
            dry_run=args.gcs_dry_run,
        )
    manifest_upload = None
    if args.manifest:
        manifest_upload = update_manifest_outputs(
            manifest_path=resolve_repo_path(args.manifest),
            outputs=uploads or local_manifest_outputs([vtt_path, srt_path], out_dir=out_dir),
            playback=simulation,
        )

    report = {
        "schemaVersion": 1,
        "status": "ok",
        "lang": args.lang,
        "cueCount": len(cues),
        "outputs": {
            "vtt": safe_display_path(vtt_path),
            "srt": safe_display_path(srt_path),
        },
        "uploads": uploads,
        "manifestUpdated": bool(args.manifest),
        "manifest": safe_display_path(resolve_repo_path(args.manifest)) if args.manifest else None,
        "manifestUpload": manifest_upload,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Translated playback simulation JS.")
    parser.add_argument("--out-dir", type=Path, required=True, help="Directory for exported caption files.")
    parser.add_argument("--stem", help="Output filename stem without extension.")
    parser.add_argument("--lang", default="zh", choices=["zh", "en"], help="Caption text to export.")
    parser.add_argument(
        "--allow-draft",
        action="store_true",
        help="Allow draft/placeholder Chinese text. Production offline exports should leave this off.",
    )
    parser.add_argument("--manifest", type=Path, help="Optional cloud-manifest.json to update with caption outputs.")
    parser.add_argument("--gcs-bucket", help="Optional GCS bucket for exported captions.")
    parser.add_argument("--gcs-prefix", default="", help="GCS prefix for exported captions.")
    parser.add_argument("--gcs-dry-run", action="store_true")
    return parser.parse_args()


def read_simulation(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith(JS_PREFIX):
        raise SystemExit(f"{path} does not look like a playback simulation JS file.")
    payload = text[len(JS_PREFIX) :].strip()
    if payload.endswith(";"):
        payload = payload[:-1]
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise SystemExit("Playback simulation payload must be an object.")
    return data


def cues_from_simulation(simulation: dict[str, Any], *, lang: str, allow_draft: bool) -> list[CaptionCue]:
    cues: list[CaptionCue] = []
    for segment in simulation.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        text = export_text(segment, lang=lang, allow_draft=allow_draft)
        if not text:
            continue
        start_ms = int(segment.get("startMs") or 0)
        end_ms = int(segment.get("endMs") or 0)
        if end_ms <= start_ms:
            end_ms = start_ms + estimate_text_duration_ms(text)
        cues.append(CaptionCue(start_ms=start_ms, end_ms=end_ms, text=text))
    return cues


def export_text(segment: dict[str, Any], *, lang: str, allow_draft: bool) -> str:
    if lang == "en":
        return clean_caption_text(str(segment.get("en") or ""))
    zh = clean_caption_text(str(segment.get("zh") or ""))
    if not zh and allow_draft:
        zh = clean_caption_text(str(segment.get("draft") or ""))
    if not zh:
        return ""
    if not allow_draft and (
        zh.startswith(PLACEHOLDER_PREFIX)
        or segment.get("translationStatus") not in {"ready", "reviewed", "published"}
    ):
        return ""
    return zh


def clean_caption_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def estimate_text_duration_ms(text: str) -> int:
    return max(1500, min(12000, len(text) * 120))


def render_vtt(cues: list[CaptionCue]) -> str:
    rows = ["WEBVTT", ""]
    for cue in cues:
        rows.append(f"{format_vtt_time(cue.start_ms)} --> {format_vtt_time(cue.end_ms)}")
        rows.append(cue.text)
        rows.append("")
    return "\n".join(rows)


def render_srt(cues: list[CaptionCue]) -> str:
    rows: list[str] = []
    for index, cue in enumerate(cues, start=1):
        rows.append(str(index))
        rows.append(f"{format_srt_time(cue.start_ms)} --> {format_srt_time(cue.end_ms)}")
        rows.append(cue.text)
        rows.append("")
    return "\n".join(rows)


def format_vtt_time(ms: int) -> str:
    hours, minutes, seconds, millis = split_ms(ms)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def format_srt_time(ms: int) -> str:
    hours, minutes, seconds, millis = split_ms(ms)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def split_ms(ms: int) -> tuple[int, int, int, int]:
    total_seconds, millis = divmod(max(0, ms), 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return hours, minutes, seconds, millis


def publish_files_to_gcs(
    *,
    files: list[Path],
    bucket: str,
    prefix: str,
    out_dir: Path,
    dry_run: bool,
) -> list[dict[str, str]]:
    uploads = []
    clean_bucket = normalize_gcs_bucket(bucket)
    clean_prefix = normalize_gcs_prefix(prefix)
    for path in files:
        rel = relative_artifact_path(path, out_dir)
        gcs_uri = (
            f"gs://{clean_bucket}/{clean_prefix}/{rel.as_posix()}"
            if clean_prefix
            else f"gs://{clean_bucket}/{rel.as_posix()}"
        )
        command = ["upload_file_to_gcs.py", "--source", str(path), "--destination", gcs_uri]
        print("$ " + " ".join(command))
        if not dry_run:
            upload_file_to_gcs(path, gcs_uri)
        uploads.append({"localPath": rel.as_posix(), "gcsUri": gcs_uri})
    return uploads


def update_manifest_outputs(
    manifest_path: Path,
    outputs: list[dict[str, str]],
    playback: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("apiKeyMaterialIncluded") is True or manifest.get("secretResourceNamesIncluded") is True:
        raise SystemExit("Refusing to update manifest that contains secret flags.")
    existing = manifest.get("outputs")
    if not isinstance(existing, list):
        existing = []
    by_path = {
        str(item.get("localPath")): item
        for item in existing
        if isinstance(item, dict) and item.get("localPath")
    }
    for output in outputs:
        if "/secrets/" in output.get("localPath", "") or "/secrets/" in output.get("gcsUri", ""):
            raise SystemExit("Refusing to write manifest output with secret reference.")
        by_path[output["localPath"]] = output
    manifest["outputs"] = list(by_path.values())
    manifest["captionExportStatus"] = "ready"
    manifest.update(manifest_route_metadata(playback or {}))
    manifest["apiKeyMaterialIncluded"] = False
    manifest["secretResourceNamesIncluded"] = False
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"localPath": "artifacts/cloud-manifest.json", "path": safe_display_path(manifest_path)}


def manifest_route_metadata(playback: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    source_kind = str(playback.get("offlineSourceKind") or "").strip()
    if source_kind:
        metadata["offlineSourceKind"] = source_kind
    route = playback.get("offlineRoute") if isinstance(playback.get("offlineRoute"), dict) else {}
    if route:
        metadata["offlineRoute"] = {
            "strategy": route.get("strategy"),
            "decision": route.get("decision"),
            "selectedSourceKind": route.get("selectedSourceKind"),
            "asrFallbackRequired": route.get("asrFallbackRequired"),
            "audioExtractionAttempted": route.get("audioExtractionAttempted"),
            "fallbackReason": route.get("fallbackReason"),
        }
    return metadata


def local_manifest_outputs(files: list[Path], *, out_dir: Path) -> list[dict[str, str]]:
    return [
        {"localPath": relative_artifact_path(path, out_dir).as_posix(), "gcsUri": ""}
        for path in files
    ]


def relative_artifact_path(path: Path, out_dir: Path) -> Path:
    try:
        return Path("artifacts") / path.resolve().relative_to(out_dir.resolve())
    except ValueError:
        return Path("artifacts") / path.name


def normalize_gcs_bucket(bucket: str) -> str:
    clean = bucket.strip()
    if clean.startswith("gs://"):
        clean = clean[5:]
    clean = clean.strip("/")
    if not clean or "/" in clean:
        raise SystemExit("--gcs-bucket must be a bucket name, not a path.")
    return clean


def normalize_gcs_prefix(prefix: str) -> str:
    clean = prefix.strip().strip("/")
    if "\\" in clean:
        raise SystemExit("--gcs-prefix must use forward slashes.")
    if any(part in {".", ".."} for part in clean.split("/") if part):
        raise SystemExit("--gcs-prefix cannot contain . or .. path segments.")
    return clean


def default_stem(lang: str) -> str:
    return f"sermon.{lang}.live-aligned"


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
