#!/usr/bin/env python3
"""Verify a published v3 catalog's bucket video through the App's stable URL."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request

try:
    from scripts import assemble_multilingual_v3_update as weekly
except ImportError:
    import assemble_multilingual_v3_update as weekly


ORIGINS = {
    "https://ai-for-god-sermon-audio.web.app": "ai-for-god-sermon-media-prod",
    "https://ai-for-god-sermon-audio-dev.web.app": "ai-for-god-sermon-media-dev",
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def request(url: str, *, method: str = "GET", headers: dict | None = None):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    return urllib.request.urlopen(req, timeout=30)


def verify(origin: str, catalog_path: Path, page_id: str) -> dict:
    if origin not in ORIGINS:
        raise ValueError("Unrecognized App origin")
    catalog_bytes = catalog_path.read_bytes()
    local = json.loads(catalog_bytes)
    weekly.validate_schema(local, weekly.SCHEMA)
    with request(origin + "/multilingual-v3.json", headers={"Cache-Control": "no-cache"}) as response:
        live_bytes = response.read(4 * 1024 * 1024 + 1)
    if live_bytes != catalog_bytes:
        raise ValueError("Live catalog differs from expected candidate")
    matches = [page for page in local["pages"] if page["id"] == page_id]
    if len(matches) != 1 or not matches[0].get("videoDelivery"):
        raise ValueError("Published page lacks bucket video delivery")
    delivery = matches[0]["videoDelivery"]
    weekly.validate_video_delivery(page_id, delivery, delivery["sha256"])
    if f"/{ORIGINS[origin]}/" not in delivery["storageUrl"]:
        raise ValueError("Video bucket does not match App environment")
    canonical = origin + delivery["canonicalUrl"]
    no_redirect = urllib.request.build_opener(NoRedirect)
    try:
        no_redirect.open(urllib.request.Request(canonical), timeout=30)
        raise ValueError("Canonical video URL did not redirect")
    except urllib.error.HTTPError as error:
        if error.code != 302 or error.headers.get("Location") != delivery["storageUrl"]:
            raise ValueError("Canonical video redirect differs") from error

    with request(delivery["storageUrl"], method="HEAD") as response:
        if (response.status != 200
                or response.headers.get("Content-Type", "").split(";")[0] != "video/mp4"
                or int(response.headers.get("Content-Length", "-1")) != delivery["bytes"]):
            raise ValueError("Bucket object metadata differs")
    for header, expected_range in (
        ("bytes=0-1023", f"bytes 0-1023/{delivery['bytes']}"),
        ("bytes=-1024", f"bytes {delivery['bytes']-1024}-{delivery['bytes']-1}/{delivery['bytes']}"),
    ):
        with request(canonical, headers={"Range": header, "Origin": origin}) as response:
            body = response.read(1025)
            if (response.status != 206 or response.url != delivery["storageUrl"]
                    or response.headers.get("Content-Range") != expected_range
                    or response.headers.get("Access-Control-Allow-Origin") != origin
                    or len(body) != 1024):
                raise ValueError(f"Canonical video Range failed: {header}")
    hasher = hashlib.sha256()
    size = 0
    with request(delivery["storageUrl"]) as response:
        if response.status != 200:
            raise ValueError("Bucket object full GET failed")
        while chunk := response.read(4 * 1024 * 1024):
            size += len(chunk)
            if size > delivery["bytes"]:
                raise ValueError("Bucket object exceeds bound size")
            hasher.update(chunk)
    if size != delivery["bytes"] or hasher.hexdigest() != delivery["sha256"]:
        raise ValueError("Bucket object full GET hash differs")
    return {
        "schemaVersion": "sermon-v3-bucket-video-http-verification-v1",
        "status": "pass",
        "pageId": page_id,
        "origin": origin,
        "catalogSha256": hashlib.sha256(catalog_bytes).hexdigest(),
        "videoDelivery": delivery,
        "redirectStatus": 302,
        "rangeStatus": 206,
        "fullGetBytes": size,
        "fullGetSha256": hasher.hexdigest(),
        "browserAcceptance": "not_run",
        "iosAcceptance": "not_run",
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.origin, args.catalog, args.page_id)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        raise ValueError("Output receipt already exists")
    args.out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "pageId", "fullGetBytes")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
