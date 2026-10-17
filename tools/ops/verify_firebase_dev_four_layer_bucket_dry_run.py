#!/usr/bin/env python3
"""Read back a published simulated four-layer bucket dry run from Firebase Dev."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request

try:
    from scripts import firebase_dev_four_layer_bucket_dry_run as dry
except ImportError:
    import firebase_dev_four_layer_bucket_dry_run as dry


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def get(url: str, headers: dict | None = None):
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=30)


def verify(candidate: Path, baseline_preflight: Path) -> dict:
    report = dry.read(candidate / "dry-run-report.json")
    if (report.get("schemaVersion") != "sermon-dev-four-layer-bucket-dry-run-v2"
            or report.get("status") != "validated_not_deployed"
            or report.get("origin") != dry.DEV_ORIGIN
            or report.get("formalCatalogUpdated") is not False):
        raise ValueError("Expected an unpublished simulated Dev candidate")
    if dry.sha(baseline_preflight) != report["baselinePreflightSha256"]:
        raise ValueError("Dev baseline preflight receipt differs")
    baseline = dry.read(baseline_preflight)
    if baseline.get("status") != "pass" or baseline.get("origin") != dry.DEV_ORIGIN:
        raise ValueError("Dev baseline was not fully checked")
    stage = dry.weekly.regular_files(candidate / "stage-public")
    if (len(stage) != 22 or report["weeklyHostingFileCount"] != 21
            or report["devHostingChangedFileCount"] != 22):
        raise ValueError("Dev bucket-video file count differs")
    manifest_path = candidate / "simulation/stage-manifest.json"
    if dry.sha(manifest_path) != report["stageManifestSha256"]:
        raise ValueError("Stage manifest differs from report")
    manifest = dry.read(manifest_path)
    if (manifest.get("status") != "simulation_only" or manifest.get("pageId") != report["pageId"]
            or manifest.get("videoDelivery") != report["videoDelivery"]
            or {item["path"].lstrip("/"): item["sha256"] for item in manifest["files"]}
            != {name: dry.sha(path) for name, path in stage.items() if not name.startswith("dry-run/")}):
        raise ValueError("Staged files do not bind to simulated manifest")
    app_index = dry.read(candidate / "stage-public/dry-run/latest.json")
    if (app_index.get("status") != "simulation_only" or app_index.get("pageId") != report["pageId"]
            or app_index.get("catalogSha256")
            != dry.sha(candidate / f"stage-public/dry-run/{report['pageId']}/catalog.json")):
        raise ValueError("Dev App index does not bind to the latest simulated week")
    config = dry.read(candidate / "hosting/firebase.json")
    redirect = {r["source"]: r for r in config["hosting"]["redirects"]}.get(
        report["videoDelivery"]["canonicalUrl"])
    if redirect != {"source": report["videoDelivery"]["canonicalUrl"],
                    "destination": report["videoDelivery"]["storageUrl"], "type": 302}:
        raise ValueError("Dev Hosting config lacks exact bucket redirect")
    origin = dry.DEV_ORIGIN
    public = candidate / "hosting/public"
    def check_preserved(row: dict) -> None:
        request = urllib.request.Request(f"{origin}/{row['path']}", method="HEAD",
                                         headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=30) as response:
            if (response.status != 200 or not row["etag"]
                    or response.headers.get("ETag") != row["etag"]
                    or dry.sha(public / row["path"]) != row["sha256"]):
                raise ValueError(f"Previously published Dev file changed: {row['path']}")
    preserved_rows = [row for row in baseline["files"] if row["path"] != "dry-run/latest.json"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(check_preserved, preserved_rows))
    for name, path in stage.items():
        if dry.sha(public / name) != dry.sha(path):
            raise ValueError(f"Candidate changed staged file: {name}")
        with get(f"{origin}/{name}", {"Cache-Control": "no-cache"}) as response:
            value = response.read(path.stat().st_size + 1)
            if response.status != 200 or hashlib.sha256(value).hexdigest() != dry.sha(path):
                raise ValueError(f"Published Dev asset differs: {name}")
    for name, digest in (("multilingual-v3.json", "baseDevCatalogSha256"),
                         ("app.mjs", "baseDevAppSha256"),
                         (f"pages/{dry.SOURCE_PAGE}/style.css", "baseDevPageStyleSha256")):
        with get(f"{origin}/{name}", {"Cache-Control": "no-cache"}) as response:
            if hashlib.sha256(response.read()).hexdigest() != report[digest]:
                raise ValueError(f"Dev App baseline changed: {name}")
    delivery = report["videoDelivery"]
    canonical = origin + delivery["canonicalUrl"]
    try:
        urllib.request.build_opener(NoRedirect).open(canonical, timeout=30)
        raise ValueError("Video canonical URL did not redirect")
    except urllib.error.HTTPError as error:
        if error.code != 302 or error.headers.get("Location") != delivery["storageUrl"]:
            raise ValueError("Video redirect differs") from error
    for range_header, expected in (
        ("bytes=0-1023", f"bytes 0-1023/{delivery['bytes']}"),
        ("bytes=-1024", f"bytes {delivery['bytes']-1024}-{delivery['bytes']-1}/{delivery['bytes']}"),
    ):
        with get(canonical, {"Range": range_header, "Origin": origin}) as response:
            if (response.status != 206 or response.headers.get("Content-Range") != expected
                    or response.headers.get("Access-Control-Allow-Origin") != origin
                    or response.headers.get_content_type() != "video/mp4"
                    or len(response.read(1025)) != 1024):
                raise ValueError(f"Video Range differs: {range_header}")
    with get(delivery["storageUrl"]) as response:
        body = response.read(delivery["bytes"] + 1)
        if (response.status != 200 or len(body) != delivery["bytes"]
                or response.headers.get_content_type() != "video/mp4"
                or hashlib.sha256(body).hexdigest() != delivery["sha256"]):
            raise ValueError("Bucket video full GET differs")
    for locale in dry.LOCALES:
        path = f"media/{report['pageId']}/{locale}.mp3"
        size = stage[path].stat().st_size
        with get(f"{origin}/{path}", {"Range": "bytes=0-1023"}) as response:
            if (response.status != 206 or response.headers.get("Content-Range") != f"bytes 0-1023/{size}"
                    or response.headers.get_content_type() != "audio/mpeg"
                    or len(response.read(1025)) != 1024):
                raise ValueError(f"{locale}: Dev audio Range differs")
    return {"schemaVersion": "sermon-dev-four-layer-bucket-http-receipt-v1",
            "status": "pass", "simulationOnly": True, "pageId": report["pageId"],
            "origin": origin, "hostingAssetsVerified": len(stage),
            "existingDevFilesPreserved": len(preserved_rows),
            "bucketBytesVerified": delivery["bytes"], "bucketSha256": delivery["sha256"],
            "videoRedirectStatus": 302, "videoRangeStatus": 206,
            "localeAudioRangeVerified": list(dry.LOCALES),
            "formalCatalogUnchanged": True, "devAppUnchanged": True,
            "browserPlayback": "not_run", "iosPlayback": "not_run",
            "verifiedAt": datetime.now(timezone.utc).isoformat()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline-preflight", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.candidate, args.baseline_preflight)
    if args.out.exists():
        raise ValueError("Receipt already exists")
    dry.write(args.out, result)
    print(json.dumps({key: result[key] for key in ("status", "pageId", "hostingAssetsVerified",
                                                   "bucketBytesVerified")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
