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


def main() -> int:
    args = parse_args()
    manifest = read_json(args.source_manifest)
    promoted = promote_manifest(manifest, sunday=args.sunday, source_manifest=args.source_manifest)
    destination = args.destination_manifest or stable_manifest_uri(
        bucket=args.gcs_bucket,
        prefix=args.gcs_prefix,
        sunday=args.sunday,
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
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    validate_sunday(args.sunday)
    if not args.destination_manifest and not args.gcs_bucket:
        raise SystemExit("--gcs-bucket is required unless --destination-manifest is provided")
    return args


def promote_manifest(manifest: dict[str, Any], sunday: str, source_manifest: str) -> dict[str, Any]:
    validate_manifest(manifest)
    promoted = dict(manifest)
    promoted["schemaVersion"] = int(promoted.get("schemaVersion", 1))
    promoted["status"] = "ready"
    promoted["sunday"] = sunday
    promoted["sourceManifest"] = source_manifest
    promoted["promotedAt"] = datetime.now(timezone.utc).isoformat()
    promoted["translationStatus"] = infer_translation_status(promoted)
    promoted["apiKeyMaterialIncluded"] = False
    promoted["secretResourceNamesIncluded"] = False
    promoted["readiness"] = {
        "state": "published",
        "publicArtifactsReady": True,
        "operatorReviewed": False,
    }
    return promoted


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
    parsed = date.fromisoformat(value)
    if parsed.weekday() != 6:
        raise SystemExit("--sunday must be a Sunday date")


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
    return reader.read_text(str(path))


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
