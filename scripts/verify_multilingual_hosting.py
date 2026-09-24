#!/usr/bin/env python3
"""Verify a deployed multilingual Hosting snapshot without changing its packages."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

try:
    from scripts import assemble_multilingual_hosting as hosting
except ImportError:
    import assemble_multilingual_hosting as hosting


def checked_origin(value: str) -> str:
    parsed = urlparse(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise ValueError("Origin must be a bare HTTPS site")
    return value.rstrip("/")


def request_bytes(origin: str, path: str, *, opener=urlopen, range_first=False) -> tuple[int, dict, bytes]:
    headers = {"Range": "bytes=0-0"} if range_first else {}
    request = Request(origin + path, headers=headers, method="GET")
    with opener(request, timeout=60) as response:
        final = urlparse(response.geturl())
        expected = urlparse(origin)
        if (final.scheme, final.netloc, final.path) != (
                expected.scheme, expected.netloc, path):
            raise ValueError(f"Redirect or changed URL: {path}")
        status = response.status
        returned = {key.lower(): value for key, value in response.headers.items()}
        if range_first:
            data = response.read(2)
            if response.read(1):
                raise ValueError(f"Range returned more than one byte: {path}")
        else:
            data = response.read()
        return status, returned, data


def request_file(origin: str, path: str, *, opener=urlopen) -> tuple[int, dict, int, str]:
    with opener(Request(origin + path, method="GET"), timeout=180) as response:
        final, expected = urlparse(response.geturl()), urlparse(origin)
        if (final.scheme, final.netloc, final.path) != (
                expected.scheme, expected.netloc, path):
            raise ValueError(f"Redirect or changed URL: {path}")
        headers = {key.lower(): value for key, value in response.headers.items()}
        digest = hashlib.sha256()
        length = 0
        while chunk := response.read(1024 * 1024):
            length += len(chunk)
            digest.update(chunk)
        return response.status, headers, length, digest.hexdigest()


def verify(candidate: Path, origin: str, *, opener=urlopen) -> dict:
    origin = checked_origin(origin)
    public = candidate / "public"
    report = hosting.load(candidate / "build-report.json")
    if (report.get("schemaVersion") != "sermon-multilingual-hosting-candidate-v1"
            or report.get("status") != "validated_not_deployed"):
        raise ValueError("Not a prepared multilingual Hosting candidate")
    files = hosting.regular_files(public)
    expected = {item["path"]: item for item in report["files"]}
    if len(expected) != len(report["files"]) or set(files) != set(expected):
        raise ValueError("Candidate file list changed")
    for name, path in files.items():
        if (path.stat().st_size != expected[name]["bytes"]
                or hosting.digest(path) != expected[name]["sha256"]):
            raise ValueError(f"Candidate file changed: {name}")
    catalog = hosting.load(public / hosting.CATALOG)
    hosting.validate_catalog(catalog)
    hosting.verify_catalog_assets(public, catalog)
    if hosting.digest(public / hosting.CATALOG) != report["newCatalogSha256"]:
        raise ValueError("Candidate catalog changed")
    if report.get("productionReader") and urlparse(origin).hostname != "ai-for-god-sermon-audio.web.app":
        raise ValueError("Production reader candidate targets the Production Hosting origin")

    results = []
    for name, info in sorted(expected.items()):
        path = "/" + name
        status, headers, length, actual = request_file(origin, path, opener=opener)
        if status != 200 or length != info["bytes"]:
            raise ValueError(f"Online file missing or incomplete: {path}")
        if actual != info["sha256"]:
            raise ValueError(f"Online SHA-256 differs: {path}")
        mime = headers.get("content-type", "").split(";")[0].lower()
        if (name.endswith(".json") and mime not in {"application/json", "text/json"}
                or name.endswith(".html") and mime != "text/html"
                or name.endswith(".mp3") and mime not in {"audio/mpeg", "audio/mp3"}
                or name.endswith(".wav") and mime not in {"audio/wav", "audio/x-wav", "audio/wave"}):
            raise ValueError(f"Unexpected Content-Type for {path}: {mime}")
        if name == hosting.CATALOG and "no-store" not in headers.get("cache-control", ""):
            raise ValueError("Online multilingual catalog must use no-store")
        results.append({"path": path, "status": status, "sha256": actual,
                        "bytes": length, "contentType": mime})

    page = next(item for item in catalog["pages"] if item["id"] == report["newPageId"])
    for locale in page["targets"]:
        release = hosting.load(public / page["targets"][locale]["releasePackageUrl"][1:])
        audio = next(item for item in release["assets"] if item["role"] == "audio")
        status, headers, data = request_bytes(origin, audio["path"], opener=opener,
                                              range_first=True)
        size = (public / audio["path"][1:]).stat().st_size
        with (public / audio["path"][1:]).open("rb") as stream:
            first = stream.read(1)
        if (status != 206 or data != first
                or headers.get("content-range") != f"bytes 0-0/{size}"):
            raise ValueError(f"Audio Range 206 failed: {audio['path']}")
        page_url = f"/pages/{page['id']}/{locale}"
        route_status, route_headers, html = request_bytes(origin, page_url, opener=opener)
        if (route_status != 200 or "text/html" not in route_headers.get("content-type", "")
                or b"<html" not in html[:4096].lower()):
            raise ValueError(f"Multilingual deep link failed: {page_url}")
        results.append({"path": audio["path"], "range206": True,
                        "contentRange": headers["content-range"]})
        results.append({"path": page_url, "routeHtml": True, "status": route_status})
    return {
        "schemaVersion": "sermon-multilingual-hosting-http-verification-v1",
        "origin": origin, "pageId": page["id"],
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "status": "pass", "buildReportSha256": hosting.digest(candidate / "build-report.json"),
        "catalogSha256": report["newCatalogSha256"],
        "checkedFiles": len(expected), "results": results,
        "deviceAcceptance": "not_run", "venueAcceptance": "not_run",
    }


def verify_baseline(candidate: Path, origin: str, *, opener=urlopen) -> dict:
    """Refuse to publish an overlay made from an older Production snapshot."""
    origin = checked_origin(origin)
    report = hosting.load(candidate / "build-report.json")
    if (report.get("schemaVersion") != "sermon-multilingual-hosting-candidate-v1"
            or report.get("status") != "validated_not_deployed"
            or not report.get("productionReader")):
        raise ValueError("Expected a prepared Production reader candidate")
    if urlparse(origin).hostname != "ai-for-god-sermon-audio.web.app":
        raise ValueError("Baseline must use the Production Hosting origin")
    expected = report.get("baseFiles")
    if not isinstance(expected, list) or not expected:
        raise ValueError("Candidate lacks a complete base snapshot")
    if len({item["path"] for item in expected}) != len(expected):
        raise ValueError("Duplicate base file")
    results = []
    for item in expected:
        path = "/" + item["path"]
        status, _, size, actual = request_file(origin, path, opener=opener)
        if status != 200 or size != item["bytes"] or actual != item["sha256"]:
            raise ValueError(f"Production baseline changed: {path}")
        results.append({"path": path, "sha256": actual, "bytes": size})
    if report.get("oldCatalogSha256") is None:
        try:
            status, _, _, _ = request_file(origin, "/" + hosting.CATALOG, opener=opener)
        except HTTPError as error:
            status = error.code
        if status != 404:
            raise ValueError("Production now has a multilingual catalog; rebuild from current snapshot")
    return {
        "schemaVersion": "sermon-multilingual-hosting-baseline-check-v1",
        "origin": origin, "status": "pass", "pageId": report["newPageId"],
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "buildReportSha256": hosting.digest(candidate / "build-report.json"),
        "checkedFiles": len(expected), "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preflight-baseline", action="store_true",
                        help="Compare every base file with live Production before deploy")
    args = parser.parse_args()
    if args.out.exists() or args.out.is_symlink():
        raise ValueError(f"Verification output already exists: {args.out}")
    receipt = (verify_baseline(args.candidate, args.origin) if args.preflight_baseline
               else verify(args.candidate, args.origin))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                        encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "pageId": receipt["pageId"],
                      "checkedFiles": receipt["checkedFiles"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
