#!/usr/bin/env python3
"""Publish a hosting snapshot incrementally through the Hosting REST API.

`firebase deploy` re-hashes and re-uploads the whole site snapshot in one node process; on a
2.9 GB site on a 36 GiB Mac that process was killed twice by macOS jetsam (low swap) before it
could finalize a version. This publisher clones the live version, uploads only the files whose
hash changed, finalizes, and releases. It reads and writes the same snapshot directory the
sentence-first publish driver builds, and writes a receipt that names exactly what it did.

  hosting_incremental_publish.py --site ai-for-god-sermon-audio --public <snapshot>/public \
      --out <snapshot>/incremental-publish.json [--execute] [--no-release]
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import hashlib
import json
import time
from pathlib import Path

API = "https://firebasehosting.googleapis.com/v1beta1"
SKIP_NAMES = {".firebase", ".DS_Store"}


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def session():
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return AuthorizedSession(credentials)


def upload_payload(path: Path) -> tuple[str, bytes]:
    """The Hosting API hashes the gzip-encoded body the CLI uploads, not the raw file."""
    raw = path.read_bytes()
    encoded = gzip.compress(raw, mtime=0)
    return hashlib.sha256(encoded).hexdigest(), encoded


def local_files(public: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in public.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(public)
        if any(part in SKIP_NAMES for part in rel.parts):
            continue
        files["/" + rel.as_posix()] = path
    return files


def remote_files(http, site: str, version: str) -> dict[str, str]:
    files, token = {}, None
    while True:
        url = f"{API}/sites/{site}/versions/{version}/files?pageSize=1000"
        if token:
            url += f"&pageToken={token}"
        response = http.get(url)
        response.raise_for_status()
        body = response.json()
        for row in body.get("files") or []:
            files[row["path"]] = row["hash"]
        token = body.get("nextPageToken")
        if not token:
            return files


def poll_operation(http, name: str, timeout: float = 600.0) -> dict:
    deadline = time.time() + timeout
    url = f"{API}/{name}"
    while time.time() < deadline:
        response = http.get(url)
        response.raise_for_status()
        body = response.json()
        if body.get("done"):
            if body.get("error"):
                raise SystemExit(f"operation failed: {json.dumps(body['error'])[:400]}")
            return body.get("response") or {}
        time.sleep(2)
    raise SystemExit("operation did not finish in time")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", required=True)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--baseline-version", help="default: the version the live release points at")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--no-release", action="store_true", help="finalize the version but keep the live release")
    args = parser.parse_args()

    http = session()
    baseline = args.baseline_version
    if not baseline:
        listing = http.get(f"{API}/sites/{args.site}/releases?pageSize=10")
        listing.raise_for_status()
        releases = listing.json().get("releases") or []
        if not releases:
            raise SystemExit("site has no release to clone from")
        newest = max(releases, key=lambda row: row.get("name", ""))
        baseline = (newest.get("version") or {}).get("name", "").split("/")[-1]
    if not baseline:
        raise SystemExit("no baseline version: pass --baseline-version")

    local = local_files(args.public)
    payloads: dict[str, bytes] = {}
    local_hashes: dict[str, str] = {}
    for path, file in sorted(local.items()):
        digest, encoded = upload_payload(file)
        local_hashes[path] = digest
        payloads[path] = encoded
    remote = remote_files(http, args.site, baseline)
    changed = sorted(p for p, h in local_hashes.items() if remote.get(p) != h)
    removed = sorted(p for p in remote if p not in local_hashes and not p.startswith("/__/"))
    bytes_changed = sum(local[p].stat().st_size for p in changed)
    plan = {"site": args.site, "liveVersion": baseline, "localFiles": len(local), "remoteFiles": len(remote),
            "changed": changed, "changedBytes": bytes_changed, "removed": removed, "startedAt": now()}
    print(json.dumps({k: plan[k] for k in ("site", "liveVersion", "localFiles", "remoteFiles",
                                           "changedBytes", "removed")}, ensure_ascii=False))
    print(json.dumps({"changed": changed}, ensure_ascii=False)[:1500])
    if removed:
        raise SystemExit("this publisher only adds or replaces files; the snapshot removes files: " + ", ".join(removed[:5]))
    if not args.execute:
        plan["mode"] = "dry-run"
        args.out.write_text(json.dumps(plan, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return 0

    operation = http.post(f"{API}/sites/{args.site}/versions:clone",
                          json={"sourceVersion": f"sites/{args.site}/versions/{baseline}", "finalize": False})
    operation.raise_for_status()
    version = poll_operation(http, operation.json()["name"]).get("name", "")
    if not version:
        raise SystemExit("clone returned no version")
    plan["clonedVersion"] = version
    print(json.dumps({"cloned": version}), flush=True)

    if changed:
        populate = http.post(f"{API}/{version}:populateFiles",
                             json={"files": local_hashes})
        populate.raise_for_status()
        body = populate.json()
        upload_url = body["uploadUrl"].rstrip("/")
        required = list(body.get("uploadRequiredHashes") or [])
        by_hash = {local_hashes[p]: p for p in changed}
        uploaded = []
        for digest in required:
            path = by_hash.get(digest)
            if path is None:
                raise SystemExit(f"populate asked for an unknown hash {digest}")
            response = http.post(upload_url + "/" + digest, data=payloads[path],
                                 headers={"Content-Type": "application/octet-stream"})
            if response.status_code != 200:
                raise SystemExit(f"upload failed for {path}: HTTP {response.status_code} {response.text[:200]}")
            uploaded.append({"path": path, "encodedBytes": len(payloads[path]),
                             "rawBytes": local[path].stat().st_size})
        plan["uploaded"] = uploaded
        print(json.dumps({"requiredHashes": len(required), "uploaded": len(uploaded),
                          "encodedBytes": sum(u["encodedBytes"] for u in uploaded)}), flush=True)

    finalize = http.patch(f"{API}/{version}?updateMask=status", json={"status": "FINALIZED"})
    finalize.raise_for_status()
    plan["finalized"] = finalize.json().get("status")
    print(json.dumps({"finalized": plan["finalized"]}), flush=True)

    if not args.no_release:
        created = http.post(f"{API}/sites/{args.site}/releases", params={"versionName": version})
        created.raise_for_status()
        body = created.json()
        plan["release"] = {"name": body.get("name"), "version": (body.get("version") or {}).get("name")}
        print(json.dumps({"released": plan["release"]}), flush=True)

    plan.update(mode="execute", finishedAt=now())
    args.out.write_text(json.dumps(plan, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
