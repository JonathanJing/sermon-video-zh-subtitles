#!/usr/bin/env python3
"""Prepare web playback simulation data from a YouTube live archive link."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OFFLINE_POC = REPO_ROOT / "scripts" / "offline_live_sermon_subtitles.py"
BUILD_PLAYBACK = REPO_ROOT / "scripts" / "build_playback_simulation.py"
DEFAULT_ASR_MODEL = "gpt-4o-transcribe"
FORBIDDEN_ASR_MODEL = "gpt-realtime-translate"
SECRET_RESOURCE_RE = re.compile(
    r"^projects/[^/\s]+/secrets/[^/\s]+(?:/versions/[^/\s]+)?$"
)


def main() -> int:
    args = parse_args()
    validate_args(args)
    out_dir = resolve_repo_path(args.out_dir)
    web_out = resolve_repo_path(args.web_out)
    out_dir.mkdir(parents=True, exist_ok=True)

    run(
        [
            sys.executable,
            str(OFFLINE_POC),
            "--live-url",
            args.live_url,
            "--out-dir",
            str(out_dir),
            "--playlist-end",
            str(args.playlist_end),
            "--asr-model",
            args.asr_model,
        ]
        + optional("--sermon-url", args.sermon_url)
        + optional("--sermon-start", args.sermon_start)
        + optional("--api-key-secret", args.api_key_secret)
        + repeat("--lang", args.lang),
        cwd=REPO_ROOT,
    )

    run(
        [
            sys.executable,
            str(BUILD_PLAYBACK),
            "--report",
            str(out_dir / "report.json"),
            "--out",
            str(web_out),
            "--max-segments",
            str(args.max_segments),
            "--playback-speed",
            str(args.playback_speed),
        ]
        + optional("--lang", args.playback_lang)
        + optional("--api-key-secret", args.api_key_secret),
        cwd=REPO_ROOT,
    )

    gcs_outputs = []
    if args.gcs_bucket:
        gcs_outputs = publish_generated_content_to_gcs(
            bucket=args.gcs_bucket,
            prefix=args.gcs_prefix,
            out_dir=out_dir,
            web_out=web_out,
            dry_run=args.gcs_dry_run,
        )
        manifest_path = write_cloud_manifest(
            out_dir=out_dir,
            web_out=web_out,
            gcs_outputs=gcs_outputs,
            api_key_secret=args.api_key_secret,
            report_path=out_dir / "report.json",
            playback_path=web_out,
        )
        gcs_outputs.extend(
            publish_files_to_gcs(
                files=[manifest_path],
                bucket=args.gcs_bucket,
                prefix=args.gcs_prefix,
                out_dir=out_dir,
                web_out=web_out,
                dry_run=args.gcs_dry_run,
            )
        )

    print(f"Prepared playback simulation: {web_out}")
    if gcs_outputs:
        print("Uploaded generated content:")
        for item in gcs_outputs:
            print(f"- {item['gcsUri']}")
    print("Open web/index.html and click 模拟播放.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Given a YouTube live archive link, prepare web playback simulation data."
    )
    parser.add_argument("--live-url", required=True, help="YouTube live archive URL.")
    parser.add_argument(
        "--sermon-url",
        help="Optional edited sermon VOD URL when discovery should be skipped or pinned.",
    )
    parser.add_argument(
        "--sermon-start",
        help="Optional live timeline sermon start override, e.g. 00:23:25.",
    )
    parser.add_argument(
        "--lang",
        action="append",
        default=[],
        help="Caption language requested from YouTube. Repeatable; defaults to POC preferences.",
    )
    parser.add_argument(
        "--playback-lang",
        help="Preferred language from generated POC outputs for browser playback.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("artifacts/offline-live-sermon-poc"),
        help="POC artifact directory.",
    )
    parser.add_argument(
        "--web-out",
        type=Path,
        default=Path("web/playback-simulation.generated.js"),
        help="Generated JS file loaded by web/index.html.",
    )
    parser.add_argument("--playlist-end", type=int, default=40)
    parser.add_argument("--max-segments", type=int, default=80)
    parser.add_argument("--playback-speed", type=float, default=18.0)
    parser.add_argument(
        "--asr-model",
        default=DEFAULT_ASR_MODEL,
        help="OpenAI transcription model to use when captions are unavailable.",
    )
    parser.add_argument(
        "--gcs-bucket",
        help="Optional GCS bucket for generated content, e.g. sermon-zh-artifacts.",
    )
    parser.add_argument(
        "--gcs-prefix",
        default="poc/live-link",
        help="GCS object prefix for generated content.",
    )
    parser.add_argument(
        "--gcs-dry-run",
        action="store_true",
        help="Print GCS upload commands without executing them.",
    )
    parser.add_argument(
        "--api-key-secret",
        help=(
            "Google Secret Manager resource for model/translation API key, e.g. "
            "projects/PROJECT_ID/secrets/openai-api-key/versions/latest."
        ),
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.api_key_secret:
        validate_secret_resource_name(args.api_key_secret)
    validate_asr_model(args.asr_model)
    if args.gcs_bucket:
        normalize_gcs_bucket(args.gcs_bucket)
        normalize_gcs_prefix(args.gcs_prefix)


def validate_asr_model(model: str) -> None:
    if model == FORBIDDEN_ASR_MODEL:
        raise SystemExit(
            "Offline no-caption ASR fallback must not use gpt-realtime-translate; "
            "use gpt-4o-transcribe."
        )
    if model != DEFAULT_ASR_MODEL:
        raise SystemExit("Offline no-caption ASR fallback must use gpt-4o-transcribe.")


def validate_secret_resource_name(value: str) -> None:
    if not SECRET_RESOURCE_RE.fullmatch(value):
        raise SystemExit(
            "--api-key-secret must be a Google Secret Manager resource name like "
            "projects/PROJECT_ID/secrets/SECRET_ID/versions/latest. Do not pass raw API key material."
        )


def optional(flag: str, value: str | None) -> list[str]:
    return [flag, value] if value else []


def repeat(flag: str, values: list[str]) -> list[str]:
    args = []
    for value in values:
        args.extend([flag, value])
    return args


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def run(command: list[str], cwd: Path) -> None:
    printable = " ".join(command)
    print(f"$ {printable}")
    subprocess.run(command, cwd=cwd, check=True)


def publish_generated_content_to_gcs(
    bucket: str,
    prefix: str,
    out_dir: Path,
    web_out: Path,
    dry_run: bool = False,
) -> list[dict[str, str]]:
    files = generated_content_files(out_dir, web_out)
    return publish_files_to_gcs(
        files=files,
        bucket=bucket,
        prefix=prefix,
        out_dir=out_dir,
        web_out=web_out,
        dry_run=dry_run,
    )


def publish_files_to_gcs(
    files: list[Path],
    bucket: str,
    prefix: str,
    out_dir: Path,
    web_out: Path,
    dry_run: bool = False,
) -> list[dict[str, str]]:
    uploads = []
    clean_bucket = normalize_gcs_bucket(bucket)
    clean_prefix = normalize_gcs_prefix(prefix)
    for file_path in files:
        rel = relative_artifact_path(file_path, out_dir, web_out)
        gcs_uri = (
            f"gs://{clean_bucket}/{clean_prefix}/{rel.as_posix()}"
            if clean_prefix
            else f"gs://{clean_bucket}/{rel.as_posix()}"
        )
        command = ["gcloud", "storage", "cp", str(file_path), gcs_uri]
        print("$ " + " ".join(command))
        if not dry_run:
            subprocess.run(command, cwd=REPO_ROOT, check=True)
        uploads.append({"localPath": rel.as_posix(), "gcsUri": gcs_uri})
    return uploads


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


def generated_content_files(out_dir: Path, web_out: Path) -> list[Path]:
    patterns = ["report.json", "report.md", "*.vtt", "*.srt"]
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path for path in out_dir.glob(pattern) if path.is_file())
    if web_out.exists():
        files.append(web_out)
    return sorted(set(files))


def relative_artifact_path(file_path: Path, out_dir: Path, web_out: Path) -> Path:
    file_path = file_path.resolve()
    out_dir = out_dir.resolve()
    web_out = web_out.resolve()
    if file_path == web_out:
        return Path("web") / web_out.name
    try:
        return Path("artifacts") / file_path.relative_to(out_dir)
    except ValueError:
        return Path(file_path.name)


def write_cloud_manifest(
    out_dir: Path,
    web_out: Path,
    gcs_outputs: list[dict[str, str]],
    api_key_secret: str | None,
    report_path: Path | None = None,
    playback_path: Path | None = None,
) -> None:
    route_metadata = manifest_route_metadata(report_path=report_path, playback_path=playback_path)
    manifest = {
        "schemaVersion": 1,
        "generatedContentStorage": "gcs",
        "playbackSimulation": relative_artifact_path(web_out, out_dir, web_out).as_posix(),
        **route_metadata,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "serverSideSecretConfigured": bool(api_key_secret),
        "outputs": gcs_outputs,
    }
    (out_dir / "cloud-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_dir / "cloud-manifest.json"


def manifest_route_metadata(report_path: Path | None = None, playback_path: Path | None = None) -> dict:
    metadata: dict[str, object] = {}
    report = read_json_object(report_path) if report_path and report_path.exists() else {}
    playback = read_playback_js(playback_path) if playback_path and playback_path.exists() else {}
    route = report.get("offline_route") if isinstance(report.get("offline_route"), dict) else {}
    source_kind = (
        nested(report, "caption_source", "kind")
        or route.get("selectedSourceKind")
        or playback.get("offlineSourceKind")
    )
    if source_kind:
        metadata["offlineSourceKind"] = source_kind
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


def read_json_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_playback_js(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    prefix = "window.SERMON_PLAYBACK_SIMULATION = "
    if not text.startswith(prefix):
        return {}
    payload = text[len(prefix) :].strip().rstrip(";")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def nested(data: dict, *keys: str):
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode)
