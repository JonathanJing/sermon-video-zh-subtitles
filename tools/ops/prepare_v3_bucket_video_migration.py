#!/usr/bin/env python3
"""Prepare a reversible, one-page Hosting -> Cloud Storage video migration.

This changes only the mutable v3 catalog and Hosting configuration in a new
candidate. It preserves the input snapshot and does not upload or deploy.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile

try:
    from scripts import assemble_multilingual_v3_update as weekly
    from scripts.assemble_multilingual_hosting import digest, load, regular_files
except ImportError:
    import assemble_multilingual_v3_update as weekly
    from assemble_multilingual_hosting import digest, load, regular_files


def storage_url(bucket: str, page_id: str, sha: str) -> str:
    if bucket not in {"ai-for-god-sermon-media-dev", "ai-for-god-sermon-media-prod"}:
        raise ValueError("Use a dedicated public sermon-media bucket")
    return f"https://storage.googleapis.com/{bucket}/weekly/{page_id}/{sha}.mp4"


def prepare(base: Path, page_id: str, bucket: str, out: Path) -> dict:
    if out.exists() or out.is_symlink():
        raise ValueError("Output already exists")
    public = base / "public"
    video_rel = f"pages/{page_id}/full-video-browser.mp4"
    video = public / video_rel
    if not video.is_file() or video.is_symlink():
        raise ValueError("Expected one locally hosted source video")
    old_catalog = load(public / weekly.CATALOG)
    weekly.validate_schema(old_catalog, weekly.SCHEMA)
    matches = [page for page in old_catalog["pages"] if page["id"] == page_id]
    if len(matches) != 1 or matches[0].get("videoDelivery") is not None:
        raise ValueError("Page is missing or already migrated")
    for page in old_catalog["pages"]:
        weekly.validate_page(public, page)
    config = load(base / "firebase.json")
    hosting = config.get("hosting", {})
    if not isinstance(hosting, dict) or hosting.get("public") != "public":
        raise ValueError("Expected complete Hosting snapshot configuration")
    canonical = "/" + video_rel
    sha = digest(video)
    delivery = {
        "schemaVersion": "sermon-video-delivery-v1",
        "canonicalUrl": canonical,
        "storageUrl": storage_url(bucket, page_id, sha),
        "sha256": sha,
        "bytes": video.stat().st_size,
    }
    weekly.validate_video_delivery(page_id, delivery, sha)
    matches[0]["videoDelivery"] = delivery
    weekly.validate_schema(old_catalog, weekly.SCHEMA)
    config = weekly.add_video_redirect(config, delivery)

    out.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        destination = temp / "public"
        shutil.copytree(public, destination, ignore=lambda path, names: {
            "full-video-browser.mp4"} if Path(path) == video.parent else set())
        (destination / weekly.CATALOG).write_text(
            json.dumps(old_catalog, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        (temp / "firebase.json").write_text(
            json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        targets = base / ".firebaserc"
        if targets.is_file():
            shutil.copyfile(targets, temp / ".firebaserc")
        for page in old_catalog["pages"]:
            weekly.validate_page(destination, page)
        old_files = regular_files(public)
        new_files = regular_files(destination)
        if set(old_files) - set(new_files) != {video_rel}:
            raise ValueError("Migration removed an unexpected Hosting file")
        if set(new_files) - set(old_files):
            raise ValueError("Migration added an unexpected Hosting file")
        for name, path in new_files.items():
            if name != weekly.CATALOG and digest(path) != digest(old_files[name]):
                raise ValueError(f"Migration changed another file: {name}")
        report = {
            "schemaVersion": "sermon-v3-bucket-video-migration-candidate-v1",
            "status": "validated_not_deployed",
            "pageId": page_id,
            "videoDelivery": delivery,
            "oldCatalogSha256": digest(public / weekly.CATALOG),
            "newCatalogSha256": digest(destination / weekly.CATALOG),
            "oldFirebaseConfigSha256": digest(base / "firebase.json"),
            "newFirebaseConfigSha256": digest(temp / "firebase.json"),
            "oldHostingFileCount": len(old_files),
            "newHostingFileCount": len(new_files),
            "removedHostingFile": video_rel,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        (temp / "migration-report.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        temp.rename(out)
        return report
    except BaseException:
        shutil.rmtree(temp)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path,
                        help="Complete Hosting snapshot directory containing public/ and firebase.json")
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    report = prepare(args.base, args.page_id, args.bucket, args.out)
    print(json.dumps({key: report[key] for key in ("status", "pageId", "videoDelivery")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
