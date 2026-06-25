#!/usr/bin/env python3
"""Promote a generated run manifest to the stable Sunday manifest pointer."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.observability import log_event
from backend.storage import LocalArtifactReader


REQUIRED_PUBLIC_OUTPUTS = {"web/playback-simulation.generated.js"}
DEFAULT_SOURCE_MODE = "youtube-live-archive"
DEFAULT_REALTIME_DRAFT_MODEL = "gpt-realtime-translate"
DEFAULT_OFFLINE_ASR_MODEL = "gpt-4o-transcribe"
DEFAULT_OFFLINE_TRANSLATION_MODEL = "gpt-5.4-mini"
DEFAULT_STABLE_CORRECTION_MODEL = "gpt-5.4-mini"
READINESS_STATES = {
    "source_detected",
    "caption_generating",
    "needs_review",
    "ready",
    "published",
    "fallback",
}


def main() -> int:
    args = parse_args()
    manifest = read_json(args.source_manifest)
    destination = args.destination_manifest or stable_manifest_uri(
        bucket=args.gcs_bucket,
        prefix=args.gcs_prefix,
        sunday=args.sunday,
    )
    promoted = promote_manifest(
        manifest,
        sunday=args.sunday,
        source_manifest=args.source_manifest,
        destination_manifest=destination,
        source_mode=args.source_mode,
        readiness_state=args.readiness_state,
        operator_reviewed=args.operator_reviewed,
        fallback_reason=args.fallback_reason,
        realtime_session_id=args.realtime_session_id,
        realtime_draft_model=args.realtime_draft_model,
        offline_asr_model=args.offline_asr_model,
        offline_translation_model=args.offline_translation_model,
        stable_correction_model=args.stable_correction_model,
    )
    write_json(destination, promoted, dry_run=args.dry_run)
    log_event(
        "captions_ready",
        component="promote-sunday-manifest",
        sunday=args.sunday,
        sourceManifest=args.source_manifest,
        destinationManifest=destination,
        translationStatus=promoted.get("translationStatus"),
        artifactCount=len(promoted.get("outputs", [])),
        dryRun=args.dry_run,
    )
    print(
        json.dumps(
            {
                "status": "planned" if args.dry_run else "promoted",
                "sourceManifest": args.source_manifest,
                "destinationManifest": destination,
                "sunday": args.sunday,
                "artifactCount": len(promoted.get("outputs", [])),
                "readinessState": promoted.get("readiness", {}).get("state"),
                "publishedManifest": destination,
                "apiKeyMaterialIncluded": False,
                "secretResourceNamesIncluded": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", required=True, help="Run cloud-manifest.json path or gs:// URI.")
    parser.add_argument("--sunday", required=True, help="Sunday slice date, YYYY-MM-DD.")
    parser.add_argument("--gcs-bucket", help="Bucket for stable Sunday manifest.")
    parser.add_argument("--gcs-prefix", default="sundays", help="Stable Sunday manifest prefix.")
    parser.add_argument("--destination-manifest", help="Override stable manifest destination path or gs:// URI.")
    parser.add_argument(
        "--source-mode",
        default=DEFAULT_SOURCE_MODE,
        choices=["youtube-live-archive", "authorized-audio", "realtime-stable-correction"],
        help="Published artifact source path.",
    )
    parser.add_argument("--readiness-state", default="published", choices=sorted(READINESS_STATES))
    parser.add_argument("--operator-reviewed", action="store_true")
    parser.add_argument("--fallback-reason", help="Required context when publishing fallback state.")
    parser.add_argument("--realtime-session-id", help="Realtime session whose stable corrections contributed.")
    parser.add_argument("--realtime-draft-model", default=DEFAULT_REALTIME_DRAFT_MODEL)
    parser.add_argument("--offline-asr-model", default=DEFAULT_OFFLINE_ASR_MODEL)
    parser.add_argument("--offline-translation-model", default=DEFAULT_OFFLINE_TRANSLATION_MODEL)
    parser.add_argument("--stable-correction-model", default=DEFAULT_STABLE_CORRECTION_MODEL)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    validate_sunday(args.sunday)
    if not args.destination_manifest and not args.gcs_bucket:
        raise SystemExit("--gcs-bucket is required unless --destination-manifest is provided")
    if args.readiness_state == "fallback" and not args.fallback_reason:
        raise SystemExit("--fallback-reason is required when --readiness-state=fallback")
    return args


def promote_manifest(
    manifest: dict[str, Any],
    sunday: str,
    source_manifest: str,
    destination_manifest: str | None = None,
    source_mode: str = DEFAULT_SOURCE_MODE,
    readiness_state: str = "published",
    operator_reviewed: bool = False,
    fallback_reason: str | None = None,
    realtime_session_id: str | None = None,
    realtime_draft_model: str = DEFAULT_REALTIME_DRAFT_MODEL,
    offline_asr_model: str = DEFAULT_OFFLINE_ASR_MODEL,
    offline_translation_model: str = DEFAULT_OFFLINE_TRANSLATION_MODEL,
    stable_correction_model: str = DEFAULT_STABLE_CORRECTION_MODEL,
) -> dict[str, Any]:
    validate_manifest(manifest)
    if readiness_state not in READINESS_STATES:
        raise SystemExit(f"invalid readiness state: {readiness_state}")
    if readiness_state == "fallback" and not fallback_reason:
        raise SystemExit("fallback readiness requires a fallback reason")
    promoted_at = datetime.now(timezone.utc).isoformat()
    translation_status = infer_translation_status(manifest)
    validate_readiness_translation_status(readiness_state, translation_status)
    promoted = dict(manifest)
    promoted["schemaVersion"] = int(promoted.get("schemaVersion", 1))
    promoted["status"] = "fallback" if readiness_state == "fallback" else "ready"
    promoted["sunday"] = sunday
    promoted["sourceManifest"] = source_manifest
    promoted["publishedManifest"] = destination_manifest
    promoted["promotedAt"] = promoted_at
    promoted["publishedAt"] = promoted_at if readiness_state in {"published", "fallback"} else None
    promoted["readyTime"] = promoted_at if readiness_state in {"ready", "published", "fallback"} else None
    promoted["translationStatus"] = translation_status
    promoted["generationMode"] = source_mode
    promoted["models"] = {
        "realtimeDraft": realtime_draft_model,
        "offlineAsr": offline_asr_model,
        "offlineTranslation": offline_translation_model,
        "stableCorrection": stable_correction_model,
    }
    promoted["apiKeyMaterialIncluded"] = False
    promoted["secretResourceNamesIncluded"] = False
    promoted["readiness"] = build_readiness(
        state=readiness_state,
        public_artifacts_ready=True,
        operator_reviewed=operator_reviewed,
        translation_status=translation_status,
        source_mode=source_mode,
        promoted_at=promoted_at,
        destination_manifest=destination_manifest,
        fallback_reason=fallback_reason,
        realtime_session_id=realtime_session_id,
    )
    return promoted


def validate_readiness_translation_status(readiness_state: str, translation_status: str) -> None:
    if readiness_state in {"ready", "published"} and translation_status != "ready":
        raise SystemExit(
            f"cannot promote readiness={readiness_state} when playback translationStatus={translation_status!r}; "
            "rerun gpt-5.4-mini translation or publish an explicit fallback manifest."
        )


def build_readiness(
    *,
    state: str,
    public_artifacts_ready: bool,
    operator_reviewed: bool,
    translation_status: str,
    source_mode: str,
    promoted_at: str,
    destination_manifest: str | None,
    fallback_reason: str | None,
    realtime_session_id: str | None,
) -> dict[str, Any]:
    fallback = state == "fallback"
    checks = [
        {"name": "public_playback_js", "state": "pass" if public_artifacts_ready else "fail"},
        {"name": "caption_vtt_or_srt", "state": "pass"},
        {"name": "offline_translation", "state": "pass" if translation_status == "ready" else "warn"},
        {"name": "operator_review", "state": "pass" if operator_reviewed else "not_required"},
    ]
    if source_mode == "realtime-stable-correction":
        checks.append({"name": "realtime_session", "state": "pass" if realtime_session_id else "warn"})
    readiness = {
        "state": state,
        "publicArtifactsReady": public_artifacts_ready,
        "operatorReviewed": operator_reviewed,
        "fallback": fallback,
        "fallbackReason": fallback_reason if fallback else None,
        "sourceMode": source_mode,
        "translationStatus": translation_status,
        "readyTime": promoted_at if state in {"ready", "published", "fallback"} else None,
        "publishedAt": promoted_at if state in {"published", "fallback"} else None,
        "publishedManifest": destination_manifest,
        "realtimeSessionId": realtime_session_id,
        "checks": checks,
    }
    return readiness


def infer_translation_status(manifest: dict[str, Any]) -> str:
    playback = next(
        (
            item
            for item in manifest.get("outputs", [])
            if isinstance(item, dict)
            and item.get("localPath") == "web/playback-simulation.generated.js"
            and item.get("gcsUri")
        ),
        None,
    )
    if not playback:
        return "unknown"
    try:
        text = read_text(str(playback["gcsUri"]))
    except Exception:
        return "unknown"
    match = re.search(r'"translationStatus"\s*:\s*"([^"]+)"', text)
    return match.group(1) if match else "unknown"


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("apiKeyMaterialIncluded") is True:
        raise SystemExit("manifest says API key material is included")
    if manifest.get("secretResourceNamesIncluded") is True:
        raise SystemExit("manifest says Secret Manager resource names are included")
    text = json.dumps(manifest, ensure_ascii=False)
    if "apiKeySecret" in text or "/secrets/" in text:
        raise SystemExit("manifest contains secret references")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise SystemExit("manifest must include outputs")
    local_paths = {str(item.get("localPath", "")) for item in outputs if isinstance(item, dict)}
    missing = sorted(REQUIRED_PUBLIC_OUTPUTS - local_paths)
    if missing:
        raise SystemExit(f"manifest missing required public outputs: {', '.join(missing)}")
    has_caption = any(path.endswith((".vtt", ".srt")) for path in local_paths)
    if not has_caption:
        raise SystemExit("manifest must include at least one VTT or SRT caption output")
    has_chinese_caption = any(
        path.endswith((".vtt", ".srt")) and any(marker in path.lower() for marker in [".zh.", "zh-hans", "zh_cn", "zh-cn"])
        for path in local_paths
    )
    if not has_chinese_caption:
        raise SystemExit("manifest must include a Chinese VTT or SRT caption output")


def stable_manifest_uri(bucket: str, prefix: str, sunday: str) -> str:
    clean_bucket = bucket.removeprefix("gs://").strip("/")
    clean_prefix = prefix.strip().strip("/")
    if not clean_bucket or "/" in clean_bucket:
        raise SystemExit("--gcs-bucket must be a bucket name, not a path")
    if any(part in {".", ".."} for part in clean_prefix.split("/") if part):
        raise SystemExit("--gcs-prefix cannot contain . or ..")
    object_name = f"{clean_prefix}/{sunday}/cloud-manifest.json" if clean_prefix else f"{sunday}/cloud-manifest.json"
    return f"gs://{clean_bucket}/{object_name}"


def validate_sunday(value: str) -> None:
    date.fromisoformat(value)


def read_json(uri: str) -> dict[str, Any]:
    return json.loads(read_text(uri))


def read_text(uri: str) -> str:
    if uri.startswith("gs://"):
        completed = subprocess.run(
            ["gcloud", "storage", "cat", uri],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout
    path = Path(uri)
    reader = LocalArtifactReader(path.parent if path.parent != Path("") else Path("."))
    return reader.read_text(path.name)


def write_json(uri: str, payload: dict[str, Any], dry_run: bool = False) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    if uri.startswith("gs://"):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            handle.write(body)
            temp_path = Path(handle.name)
        command = ["gcloud", "storage", "cp", str(temp_path), uri]
        print("$ " + " ".join(command))
        if not dry_run:
            subprocess.run(command, check=True)
        temp_path.unlink(missing_ok=True)
        return
    path = Path(uri)
    print(f"$ write {path}")
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
