#!/usr/bin/env python3
"""Bind an existing verified poster to a current release; never generate sermon content or deploy.

Release metadata may change while the frozen source and content remain identical.
Such reuse requires --allow-metadata-rebind and records the old and new release hashes.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import struct
from urllib.parse import urlsplit


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build(catalog, release_bytes, receipt, poster_bytes, locale, page_id, allow_rebind=False):
    page = next(p for p in catalog["pages"] if p["id"] == page_id)
    target = page["targets"][locale]
    if target["contentStatus"] not in ("human_reviewed", "machine_checked"):
        raise ValueError("announcement must reference published content")
    release_hash = digest(release_bytes)
    if release_hash != target["releasePackageJsonSha256"]:
        raise ValueError("release bytes do not match current catalog")
    release = json.loads(release_bytes)
    source = receipt["source"]
    if (receipt.get("status") != "complete" or source["pageId"] != page_id
            or source["targetLocale"] != locale or source["sourceIdentitySha256"] != page["sourceIdentitySha256"]
            or release["pageId"] != page_id or release["targetLocale"] != locale):
        raise ValueError("poster receipt is incomplete or source/page/language changed")
    content_hash = next(a["sha256"] for a in release["assets"] if a["role"] == "content")
    if content_hash != source["contentSha256"]:
        raise ValueError("poster content changed; upstream poster must be regenerated")
    rebind = source["releasePackageSha256"] != release_hash
    if rebind and not allow_rebind:
        raise ValueError("release metadata changed; verify unchanged source/content and explicitly allow rebind")
    poster_hash = digest(poster_bytes)
    if poster_hash not in receipt["outputs"].values():
        raise ValueError("poster bytes are not a verified receipt output")
    if not poster_bytes.startswith(b"\x89PNG\r\n\x1a\n") or poster_bytes[12:16] != b"IHDR":
        raise ValueError("producer requires an existing PNG poster")
    width, height = struct.unpack(">II", poster_bytes[16:24])
    if not (0 < len(poster_bytes) <= 8 * 1024 * 1024 and 0 < width <= 8192 and 0 < height <= 8192 and width * height <= 20_000_000):
        raise ValueError("poster dimensions or bytes exceed client limits")
    for identifier in (page_id, locale):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", identifier):
            raise ValueError("unsafe identifier")
    image_path = f"/posters/{page_id}/{locale}-{poster_hash}.png"
    announcement = dict(id=f"{page_id}-{locale}", pageID=page_id, locale=locale,
        releaseSHA256=release_hash, sourceIdentitySHA256=page["sourceIdentitySha256"],
        title=source["brief"]["title"], publishedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        poster=dict(url=image_path, sha256=poster_hash, bytes=len(poster_bytes), width=width, height=height))
    evidence = dict(schemaVersion="tongxing-announcement-binding-receipt-v1", pageID=page_id, locale=locale,
        sourceIdentitySHA256=page["sourceIdentitySha256"], contentSHA256=content_hash,
        originalReleaseSHA256=source["releasePackageSha256"], currentReleaseSHA256=release_hash,
        metadataRebound=rebind, posterSHA256=poster_hash, originalPosterOrigin=source["brief"]["origin"],
        note="Poster image is unchanged. Source and frozen content match exactly. Existing QR may target original origin; App action uses current catalog.")
    return announcement, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("catalog", "release", "poster-receipt", "poster-file", "locale", "page-id", "out", "origin"):
        parser.add_argument("--" + argument, required=True)
    parser.add_argument("--allow-metadata-rebind", action="store_true")
    args = parser.parse_args()
    origin = urlsplit(args.origin)
    if origin.scheme != "https" or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment or origin.path not in ("", "/"):
        raise ValueError("origin must be an HTTPS origin")
    poster = Path(args.poster_file).read_bytes()
    announcement, evidence = build(read(args.catalog), Path(args.release).read_bytes(), read(args.poster_receipt), poster,
        args.locale, args.page_id, args.allow_metadata_rebind)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sidecar = out / "weekly-announcements-v1.json"
    value = read(sidecar) if sidecar.exists() else dict(schemaVersion="tongxing-weekly-announcements-v1", announcements=[])
    if value["schemaVersion"] != "tongxing-weekly-announcements-v1":
        raise ValueError("unsupported existing sidecar")
    key = (args.page_id, args.locale)
    value["announcements"] = [item for item in value["announcements"] if (item["pageID"], item["locale"]) != key] + [announcement]
    image = out / announcement["poster"]["url"].lstrip("/")
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(poster)
    sidecar.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence.update(catalogSHA256=digest(Path(args.catalog).read_bytes()), targetOrigin=args.origin,
        posterReceiptSHA256=digest(Path(args.poster_receipt).read_bytes()))
    receipts = out / "announcement-binding-receipts"
    receipts.mkdir(exist_ok=True)
    (receipts / f"{args.page_id}-{args.locale}.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"sidecar": str(sidecar), "image": str(image), "metadataRebound": evidence["metadataRebound"]}))


if __name__ == "__main__":
    main()
