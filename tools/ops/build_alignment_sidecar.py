#!/usr/bin/env python3
"""Assemble the field-audio alignment sidecar from a Hosting snapshot (one page, N locales).

2026-11-21: the sidecar was hand-built during a production run and failed the catalog binder four
times (wrong schemaVersion, release hash scheme, a 0.0003 s window difference, and a snapshot that
was not re-sealed afterwards). This tool derives every field from the snapshot instead of from a
human's memory:

  * ``releasePackageJsonSha256`` is the sha256 of the release **file bytes** (the scheme the catalog
    stores), not a canonical-JSON hash;
  * the fingerprint binding uses ``sermon-audio-fingerprint-binding-v1`` / ``spectral-landmarks-v1``
    with the bound track's published MP3 sha;
  * the window comes from the page content (``sourceWindow`` when present, else 0..duration), and
    must equal the index's ``sourceStartSeconds``/``sourceEndSeconds`` exactly;
  * the index URL must be ``/fingerprints/<indexSha256[:16]>-landmarks.json``.

Dry-run by default; ``--write`` copies the indexes and writes the sidecar. Re-sealing the hosting
snapshot afterwards is a separate step (``tools/ops/reseal_snapshot.py``).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

BINDING_SCHEMA = "sermon-audio-fingerprint-binding-v1"
ALGORITHM = "spectral-landmarks-v1"
SIDECAR_SCHEMA = "sermon-published-alignment-v1"
WINDOW_SCHEMA = "sermon-original-recording-window-v1"
INDEX_SCHEMA = "sermon-landmark-index-v1"
CATALOGS = ("multilingual-v5.json", "multilingual-v4.json", "multilingual-v3.json")


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def find_page(catalog: dict, page_id: str) -> dict:
    if catalog.get("schemaVersion") not in ("sermon-multilingual-catalog-v5", "sermon-multilingual-catalog-v4",
                                            "sermon-multilingual-catalog-v3"):
        raise SystemExit(f"unsupported catalog schema: {catalog.get('schemaVersion')!r}")
    pages = [p for p in catalog.get("pages") or []
             if p.get("id") == page_id
             or any(t.get("editionId") == page_id for t in (p.get("targets") or {}).values())]
    if len(pages) != 1:
        raise SystemExit(f"page {page_id} must occur exactly once in the catalog (found {len(pages)})")
    return pages[0]


def window_for(content: dict) -> tuple[float, float]:
    window = content.get("sourceWindow")
    if isinstance(window, dict):
        if window.get("schemaVersion") != WINDOW_SCHEMA:
            raise SystemExit(f"content sourceWindow has unsupported schema {window.get('schemaVersion')!r}")
        return float(window["startSeconds"]), float(window["endSeconds"])
    return 0.0, float(content["durationSeconds"])


def build_sidecar(public: Path, page_id: str, indexes: dict[str, Path], *, capture_seconds: int = 10) -> tuple[dict, dict]:
    public = Path(public)
    catalog_path = next((public / name for name in CATALOGS if (public / name).is_file()), None)
    if catalog_path is None:
        raise SystemExit(f"no catalog under {public}")
    catalog = read_json(catalog_path)
    page = find_page(catalog, page_id)
    identity = page.get("sourceIdentitySha256")
    if not identity:
        raise SystemExit("page has no sourceIdentitySha256")
    targets = {}
    evidence = {"catalog": catalog_path.name, "locales": {}}
    for locale, target in (page.get("targets") or {}).items():
        index_path = indexes.get(locale)
        if index_path is None:
            continue
        release_path = public / str(target["releasePackageUrl"]).lstrip("/")
        if not release_path.is_file():
            raise SystemExit(f"{locale}: release missing: {release_path}")
        release_sha = sha(release_path)
        if release_sha != target["releasePackageJsonSha256"]:
            raise SystemExit(f"{locale}: release bytes differ from the catalog hash")
        release = read_json(release_path)
        by_role = {asset["role"]: asset for asset in release["assets"]}
        audio = by_role["audio"]
        content = read_json(public / str(by_role["content"]["path"]).lstrip("/"))
        index = read_json(index_path)
        if index.get("schemaVersion") != INDEX_SCHEMA:
            raise SystemExit(f"{locale}: index schema {index.get('schemaVersion')!r} is not {INDEX_SCHEMA}")
        if index.get("trackSha256") != audio["sha256"]:
            raise SystemExit(f"{locale}: index binds track {index.get('trackSha256')} but the release ships {audio['sha256']}")
        if index.get("pageId") != page_id:
            raise SystemExit(f"{locale}: index pageId differs")
        start, end = window_for(content)
        if (index.get("sourceStartSeconds"), index.get("sourceEndSeconds")) != (start, end):
            raise SystemExit(f"{locale}: index window {index.get('sourceStartSeconds')}..{index.get('sourceEndSeconds')} "
                             f"differs from content {start}..{end}")
        if content.get("sourceMediaSha256") != index.get("sourceSha256"):
            raise SystemExit(f"{locale}: index media sha differs from content")
        if content.get("englishSourcePackageJsonSha256") != identity:
            raise SystemExit(f"{locale}: content source identity differs from the catalog page")
        index_sha = sha(index_path)
        url = f"/fingerprints/{index_sha[:16]}-landmarks.json"
        targets[locale] = {
            "releasePackageJsonSha256": release_sha,
            "audioFingerprint": {
                "schemaVersion": BINDING_SCHEMA, "algorithmVersion": ALGORITHM,
                "captureSeconds": capture_seconds, "pageId": page_id,
                "sourceSha256": index["sourceSha256"], "trackSha256": index["trackSha256"],
                "sourceStartSeconds": start, "sourceEndSeconds": end,
                "indexSha256": index_sha, "indexUrl": url,
            },
        }
        evidence["locales"][locale] = {"release": str(release_path.relative_to(public)),
                                       "audioSha256": audio["sha256"], "indexPath": str(index_path),
                                       "indexUrl": url, "window": [start, end]}
    missing = sorted(set(page.get("targets") or {}) - set(targets))
    if missing:
        raise SystemExit(f"no index for published locales: {missing}")
    sidecar = {"schemaVersion": SIDECAR_SCHEMA, "pageId": page_id,
               "sourceIdentitySha256": identity, "targets": targets}
    return sidecar, evidence


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--public", type=Path, required=True, help="snapshot public/ directory")
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--index", action="append", required=True, metavar="LOCALE=PATH")
    parser.add_argument("--capture-seconds", type=int, default=10)
    parser.add_argument("--out", type=Path, help="default: the snapshot public/ directory")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    indexes = {}
    for item in args.index:
        locale, sep, path = item.partition("=")
        if not sep or not locale or not path:
            raise SystemExit(f"--index wants LOCALE=PATH, got {item!r}")
        indexes[locale] = Path(path)
    sidecar, evidence = build_sidecar(args.public, args.page_id, indexes,
                                      capture_seconds=args.capture_seconds)
    out = Path(args.out or args.public)
    result = {"pageId": args.page_id, "locales": sorted(sidecar["targets"]),
              "sidecar": str(out / "alignment" / f"{args.page_id}.json"), "write": bool(args.write),
              "evidence": evidence}
    if args.write:
        (out / "alignment").mkdir(parents=True, exist_ok=True)
        (out / "alignment" / f"{args.page_id}.json").write_text(
            json.dumps(sidecar, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (out / "fingerprints").mkdir(parents=True, exist_ok=True)
        for locale, target in sidecar["targets"].items():
            source = indexes[locale]
            destination = out / target["audioFingerprint"]["indexUrl"].lstrip("/")
            shutil.copyfile(source, destination)
        result["sidecarSha256"] = sha(out / "alignment" / f"{args.page_id}.json")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
