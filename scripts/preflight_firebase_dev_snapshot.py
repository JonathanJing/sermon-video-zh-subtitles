#!/usr/bin/env python3
"""Compare every file in a complete local Firebase Dev snapshot with the live site."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

try:
    from scripts import firebase_dev_four_layer_bucket_dry_run as dry
except ImportError:
    import firebase_dev_four_layer_bucket_dry_run as dry


def check_file(item: tuple[str, Path]) -> dict:
    name, path = item
    expected = dry.sha(path)
    request = Request(f"{dry.DEV_ORIGIN}/{name}", headers={"Cache-Control": "no-cache"})
    digest = hashlib.sha256()
    size = 0
    with urlopen(request, timeout=120) as response:
        if response.status != 200:
            raise ValueError(f"Dev baseline HTTP status differs: {name}")
        etag = response.headers.get("ETag")
        while block := response.read(4 * 1024 * 1024):
            size += len(block)
            digest.update(block)
    if digest.hexdigest() != expected or size != path.stat().st_size:
        raise ValueError(f"Live Dev file differs from complete baseline: {name}")
    return {"path": name, "sha256": expected, "bytes": size, "etag": etag}


def verify(base_dev: Path) -> dict:
    config = dry.read(base_dev / "firebase.json")
    if config.get("hosting", {}).get("site") != dry.DEV_SITE:
        raise ValueError("Expected Firebase Dev complete Hosting configuration")
    files = dry.weekly.regular_files(base_dev / "public")
    with ThreadPoolExecutor(max_workers=8) as pool:
        checked = sorted(pool.map(check_file, files.items()), key=lambda value: value["path"])
    return {"schemaVersion": "sermon-dev-complete-baseline-preflight-v1", "status": "pass",
            "origin": dry.DEV_ORIGIN, "fileCount": len(checked),
            "totalBytes": sum(row["bytes"] for row in checked),
            "files": checked, "checkedAt": datetime.now(timezone.utc).isoformat()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dev", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Preflight receipt already exists")
    result = verify(args.base_dev)
    dry.write(args.out, result)
    print(json.dumps({key: result[key] for key in ("status", "fileCount", "totalBytes")}))


if __name__ == "__main__":
    main()
