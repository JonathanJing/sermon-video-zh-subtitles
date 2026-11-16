#!/usr/bin/env python3
"""One run report for a whole production: every run directory of a page.

A weekly page is produced by several run directories that share a stem: one per
locale, plus ``-source``, ``-review``, ``-publish``, ``-poster``, ``-reading``.
The 2026-11-08 report covered only the Chinese run, and the 2026-11-15 report
was written by hand with no manifest or journal, so the week had no comparable
numbers. This tool finds the whole set, then:

1. writes the public, redacted digest with export_run_digest.py (under ignored
   ``artifacts/run-reports/``; publishing stays a separate step);
2. uploads the private text evidence of the same directories to the private
   evidence store (tools/ops/evidence_store.py), so a retrospective does not
   depend on the machine that ran the production;
3. records in the digest which private bundles exist (``private-evidence.json``:
   store URI, file count and manifest hash; no content, host or path).

Both steps are observation: a failure prints the reason and the hand command,
and never changes a production result. When the combined digest exceeds the
exporter's size cap it is split into ``<name>`` (source, locales, review) and
``<name>-publish``, then per directory.

Usage (repo root):

    .venv/bin/python tools/development/export_production_report.py artifacts/sentence-first-agent/20261115-x-zh
    .venv/bin/python tools/development/export_production_report.py RUN_DIR [RUN_DIR ...] --also EXTRA_DIR --name 20261115-x
    .venv/bin/python tools/development/export_production_report.py RUN_DIR --no-upload

``sfa_publish.py readback`` calls :func:`export_production` when it passes; for
a failed or stopped production run this command by hand.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.development import export_run_digest as digest  # noqa: E402

SCHEMA = "sermon-production-report-evidence-v1"
EVIDENCE_NAME = "private-evidence.json"
TOKEN = re.compile(r"[A-Za-z0-9]+")
PUBLISH_SUFFIX = "-publish"


def stem_of(seeds: list[Path]) -> str:
    """The shared production stem of run directory names: their common prefix up to a ``-``."""
    names = sorted({Path(seed).resolve().name for seed in seeds})
    if len(names) == 1:
        head, _, tail = names[0].rpartition("-")
        return head if head and TOKEN.fullmatch(tail) else names[0]
    prefix = os.path.commonprefix(names)
    if all(name == prefix or name.startswith(prefix + "-") for name in names):
        return prefix
    head = prefix.rpartition("-")[0]
    if not head:
        raise ValueError(f"run directories share no stem: {', '.join(names)}")
    return head


def production_dirs(seeds: list[Path], also: list[Path] | None = None) -> tuple[str, list[Path]]:
    """Return (stem, directories): the seeds, their one-token siblings and the extras, each once."""
    seeds = [Path(seed).resolve() for seed in seeds]
    missing = [str(seed) for seed in seeds if not seed.is_dir()]
    if missing:
        raise ValueError(f"not a directory: {', '.join(missing)}")
    stem = stem_of(seeds)
    found: dict[Path, None] = {}
    for parent in dict.fromkeys(seed.parent for seed in seeds):
        for path in sorted(parent.iterdir()):
            if not path.is_dir() or path.is_symlink():
                continue
            if path.name == stem or (path.name.startswith(stem + "-") and TOKEN.fullmatch(path.name[len(stem) + 1:])):
                found[path.resolve()] = None
    for path in [*seeds, *(Path(extra).resolve() for extra in also or [])]:
        if path.is_dir():
            found[path] = None
    return stem, sorted(found)


def report_name(stem: str, name: str | None, out: Path) -> str:
    base = name or (stem if digest.NAME.fullmatch(stem) else f"{datetime.now(timezone.utc):%Y%m%d}-{stem}")
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-")
    if not digest.NAME.fullmatch(base):
        raise ValueError(f"report name must be YYYYMMDD-<label>: {base}")
    candidate, n = base, 1
    while (out / candidate).exists():
        n += 1
        candidate = f"{base}-r{n}"
    return candidate


def _write(dirs: list[Path], name: str, out: Path) -> Path | None:
    try:
        code = digest.main([*map(str, dirs), "--name", name, "--out", str(out)])
    except SystemExit as error:
        code = error.code
    return out / name if code == 0 else None


def write_digests(dirs: list[Path], name: str, out: Path) -> list[tuple[Path, list[Path]]]:
    """Write one digest, or split it when the size cap refuses the whole set."""
    whole = _write(dirs, name, out)
    if whole:
        return [(whole, dirs)]
    publish = [d for d in dirs if d.name.endswith(PUBLISH_SUFFIX)]
    rest = [d for d in dirs if d not in publish]
    written: list[tuple[Path, list[Path]]] = []
    groups = [(name, rest), (f"{name}{PUBLISH_SUFFIX}", publish)] if publish and rest else []
    for group_name, group in groups:
        report = _write(group, report_name(group_name, group_name, out), out)
        if report:
            written.append((report, group))
    covered = {d for _, group in written for d in group}
    for path in dirs:
        if path not in covered:
            label = re.sub(r"[^A-Za-z0-9._-]+", "-", path.name)
            single = label if digest.NAME.fullmatch(label) else f"{name}-{label}"
            report = _write([path], report_name(single, single, out), out)
            if report:
                written.append((report, [path]))
    return written


def upload_evidence(dirs: list[Path], store_uri: str | None) -> list[dict]:
    from tools.ops import evidence_store

    store = evidence_store.open_store(store_uri)
    problems = store.check()
    if problems:
        raise ValueError(f"{store.uri} must not hold private evidence: " + "; ".join(problems))
    rows = []
    for path in dirs:
        manifest, files = evidence_store.collect(path)
        result = evidence_store.upload_bundle(store, manifest, files)
        rows.append({"runName": result["runName"], "store": result["store"], "files": manifest["totals"]["files"],
                     "omitted": len(manifest["omitted"]), "collectedAt": manifest["collectedAt"],
                     "manifestSha256": hashlib.sha256(evidence_store.manifest_bytes(manifest)).hexdigest()})
    return rows


def export_production(seeds: list[Path], *, also: list[Path] | None = None, name: str | None = None,
                      out: Path | None = None, store_uri: str | None = None, upload: bool = True) -> dict:
    """Write the digest(s) for a production and upload its private evidence; never raises."""
    out = Path(out) if out else ROOT / "artifacts/run-reports"
    result: dict = {"reports": [], "evidence": [], "problems": []}
    try:
        stem, dirs = production_dirs(seeds, also)
        result["stem"], result["runDirs"] = stem, [d.name for d in dirs]
        out.mkdir(parents=True, exist_ok=True)
        written = write_digests(dirs, report_name(stem, name, out), out)
        if not written:
            result["problems"].append("no digest written; run tools/development/export_run_digest.py by hand")
    except (Exception, SystemExit) as error:  # noqa: BLE001 - the production's own result must stand
        result["problems"].append(f"digest: {error}")
        return result
    evidence: list[dict] = []
    if upload:
        try:
            evidence = upload_evidence(dirs, store_uri)
        except Exception as error:  # noqa: BLE001 - e.g. no credentials on this machine
            result["problems"].append(
                f"private evidence not uploaded ({type(error).__name__}: {str(error)[:200]}); "
                "run tools/ops/evidence_store.py push by hand")
    result["evidence"] = evidence
    for report, group in written:
        names = {path.name for path in group}
        record = {"schemaVersion": SCHEMA, "report": report.name, "runDirs": sorted(names),
                  "uploaded": bool(evidence),
                  "bundles": [row for row in evidence if row["runName"] in names]}
        (report / EVIDENCE_NAME).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["reports"].append(str(report))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dirs", nargs="+", type=Path, help="one or more run directories of the production")
    parser.add_argument("--also", action="append", default=[], type=Path,
                        help="a directory outside the stem to include (shared source, review, alignment)")
    parser.add_argument("--name", help="YYYYMMDD-<label> (default: the stem)")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--store", help="private evidence store (default: evidence_store.py's)")
    parser.add_argument("--no-upload", action="store_true", help="write the digest only")
    args = parser.parse_args(argv)
    result = export_production(args.run_dirs, also=args.also, name=args.name, out=args.out,
                               store_uri=args.store, upload=not args.no_upload)
    for problem in result["problems"]:
        print(f"export_production_report: {problem}", file=sys.stderr)
    for report in result["reports"]:
        print(f"Publish for review: tools/development/publish_run_report.sh {report}")
    print(json.dumps({key: result.get(key) for key in ("stem", "runDirs", "reports")}, ensure_ascii=False))
    return 0 if result["reports"] else 1


if __name__ == "__main__":
    sys.exit(main())
