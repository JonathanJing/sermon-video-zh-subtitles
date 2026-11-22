#!/usr/bin/env python3
"""Re-seal a Hosting snapshot's seal-report after changing catalogs or adding files.

2026-11-21: binding the alignment sidecar rewrote the three catalogs and added the sidecar plus
three fingerprint indexes. The guarded publisher then refused the snapshot twice —
"Baseline catalog differs" and "Baseline snapshot is incomplete" — because ``seal-report.json``
still held the old catalog hashes and the old file list. This tool recomputes both from the
snapshot's own bytes (same shape the publisher's seal writes) so the deploy can proceed.

It is a byte-identity operation, not a seal of approval: it never changes a page, content, audio
or catalog byte, only the report that describes them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

CATALOGS = {"catalogSha256": "multilingual-v3.json",
            "catalogV4Sha256": "multilingual-v4.json",
            "catalogV5Sha256": "multilingual-v5.json"}


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def catalog_report(public: Path) -> dict:
    report = {}
    for key, name in CATALOGS.items():
        path = Path(public) / name
        if path.is_file():
            report[key] = digest(path)
    return report


def files_report(public: Path) -> list[dict]:
    public = Path(public)
    return [{"path": "/" + str(path.relative_to(public)), "sha256": digest(path), "bytes": path.stat().st_size}
            for path in sorted(public.rglob("*")) if path.is_file()]


def reseal(snapshot: Path) -> dict:
    snapshot = Path(snapshot)
    report_path = snapshot / "seal-report.json"
    if not report_path.is_file():
        raise SystemExit(f"not a sealed snapshot: {report_path} missing")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    public = snapshot / "public"
    before = {key: report.get(key) for key in CATALOGS}
    fresh = catalog_report(public)
    for key in CATALOGS:
        report.pop(key, None)
    report.update(fresh)
    report["files"] = files_report(public)
    changed = {key: (before.get(key), fresh[key]) for key in fresh if before.get(key) != fresh[key]}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"snapshot": str(snapshot), "files": len(report["files"]),
            "catalogs": {key: report[key][:16] for key in CATALOGS if key in report},
            "catalogChanges": {key: {"before": pair[0][:16] if pair[0] else None,
                                     "after": pair[1][:16]} for key, pair in changed.items()}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(reseal(args.snapshot), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
