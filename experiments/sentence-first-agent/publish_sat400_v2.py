#!/usr/bin/env python3
"""Retract the 2026-10-24 draft publication and republish from the official 1080p recording.

The user replaced the earlier live capture with ``Saturday_400pm_Live__1080.mp4`` and asked for
the official version to be rebuilt from it under the same page. The guarded publisher only adds
new files, so the page is first **retracted** (catalogs no longer list it and its asset files are
removed from the snapshot), which lets the rebuild write those paths as new files again.

Order (each step its own subcommand, each deploy guarded):
  retract        live baseline -> catalogs without the page, page asset files removed -> deploy
  assets         new content/captions/media/releases + fingerprints + alignment sidecar
  stage-assets   retracted snapshot + those files -> deploy
  verify         HTTP SHA/Range for the new assets -> evidence
  stage-release  assets snapshot + releases + catalogs (page re-added, verified) -> deploy
  readback       live catalogs/releases equal the staged bytes
  bind           fresh baseline + published_alignment_catalog.bind_catalogs -> deploy
  verify-alignment  GET catalog binding + index; content duration matches the window

Constants below differ from ``publish_sat400_alignment`` only in the source, window and run dirs.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import publish_sat400_20261025 as base  # noqa: E402
import publish_sat400_alignment as align  # noqa: E402
from tongxing_production.delivery import baseline as bl  # noqa: E402
from tongxing_production.delivery import contract  # noqa: E402

PAGE_ID = base.PAGE_ID
LOCALES = base.LOCALES
MEDIA = Path("/Users/jonathan_jing/Downloads/Saturday_400pm_Live__1080.mp4")
MEDIA_SHA = "beee2df229ddac5a6fd7652953c2042ecdcca3f2eb69112db54ff19e1dcc25a4"
LENGTH = 1853.056

# the official recording runs; every helper reads its module globals at call time
base.PODCAST = Path("/Users/jonathan_jing/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/"
                    "artifacts/sentence-first-agent/20261024-sat400-v2-english")
base.VERDICT = Path("/Users/jonathan_jing/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/"
                    "artifacts/sentence-first-agent/20261024-sat400-v2-review/human-review-verdict.json")
base.SENTENCES = 447
align.RUN_DIR = {"zh-Hans": "20261024-sat400-v2-zh", "ko": "20261024-sat400-v2-ko", "es": "20261024-sat400-v2-es"}
align.SOURCE_MEDIA = MEDIA
align.SOURCE_SHA = MEDIA_SHA
align.TRACK_LENGTH = LENGTH
align.WINDOW_START = 0.0

PAGE_ASSETS = [f"content/{PAGE_ID}/{loc}.json" for loc in LOCALES] + \
              [f"captions/{PAGE_ID}/{loc}.json" for loc in LOCALES] + \
              [f"media/{PAGE_ID}/{loc}.mp3" for loc in LOCALES] + \
              [f"pages/{PAGE_ID}/{loc}/index.html" for loc in LOCALES] + \
              [f"releases-v2/{PAGE_ID}/{loc}.json" for loc in LOCALES] + \
              [f"english-reference/{PAGE_ID}.json"]


def stage_paths(baseline: Path, out: Path, *, remove: list[str], files: dict[str, bytes]) -> None:
    """stage() variant that may delete paths (a retraction), then seals and validates."""
    contract.require(not out.exists(), "Use a new snapshot directory")
    out.mkdir(parents=True)
    shutil.copytree(baseline / "public", out / "public")
    shutil.copyfile(baseline / "firebase.json", out / "firebase.json")
    shutil.copyfile(baseline / "baseline-receipt.json", out / "baseline-receipt.json")
    removed = []
    for rel in remove:
        path = out / "public" / rel
        if path.exists():
            path.unlink()
            removed.append("/" + rel)
    added = []
    for rel, data in files.items():
        target = out / "public" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        added.append("/" + rel)
    report = {**bl.catalog_report(out / "public"), "files": bl.files_report(out / "public")}
    bl.write(out / "seal-report.json", report)
    contract.validate_catalog_snapshot(out)
    bl.write(out / "publish-config.json", bl.publication_config(baseline, out, environment=base.ENVIRONMENT))
    base.write_json(out / "staged-changes.json", {"pageId": PAGE_ID, "environment": base.ENVIRONMENT,
                                                  "changedPaths": added, "removedPaths": removed,
                                                  "base": str(baseline)})


def cmd_retract(baseline: Path, out: Path) -> dict:
    public = baseline / "public"
    v5 = json.loads((public / contract.CATALOG_FILES[contract.CATALOG_V5]).read_text())
    contract.require(sum(1 for p in v5["pages"] if p["id"] == PAGE_ID) == 1, "page is not in the live v5 catalog")
    v5["pages"] = [p for p in v5["pages"] if p["id"] != PAGE_ID]
    v4 = contract.project_legacy_catalog_v4(v5)
    v3 = contract.project_human_catalog(v4)
    files = {}
    for name, value in ((contract.CATALOG_V5, v5), (contract.CATALOG_V4, v4), (contract.CATALOG_V3, v3)):
        contract.validate_catalog_schema(value)
        files[contract.CATALOG_FILES[name]] = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    stage_paths(baseline, out, remove=PAGE_ASSETS, files=files)
    return {"staged": str(out), "retracted": PAGE_ID, "removed": len(PAGE_ASSETS)}


def cmd_stage_release_v2(assets_snapshot: Path, evidence: Path, assets: Path, out: Path) -> dict:
    """Add the releases, the alignment sidecar that binds them, and the catalogs with the page.

    The page was retracted, so it is absent from the snapshot's catalogs and this deploy adds it
    back with the new release hashes. The sidecar is written here because it binds the final
    release bytes (status and HTTP evidence included), which only exist at this point.
    """
    evidence_row = json.loads(evidence.read_text())
    contract.require(evidence_row["status"] == "pass", "HTTP verification did not pass")
    evidence_sha = base.sha_file(evidence)
    esp, esp_sha = base.english_source()
    files, targets, bindings = {}, {}, {}
    for loc in LOCALES:
        release = json.loads((assets / f"releases/{loc}.json").read_text())
        release.update(status="published_http_verified",
                       httpVerification={"status": "pass", "evidenceSha256": evidence_sha})
        contract.validate_release_schema(release)
        data = (json.dumps(release, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()
        files[f"releases-v2/{PAGE_ID}/{loc}.json"] = data
        targets[loc] = {"audioStatus": "human_reviewed", "capabilities": ["text", "captions", "audio"],
                        "contentStatus": "human_reviewed", "releasePackageJsonSha256": hashlib.sha256(data).hexdigest(),
                        "releasePackageUrl": f"/releases-v2/{PAGE_ID}/{loc}.json"}
    summary = json.loads((assets / "assets-summary.json").read_text())
    for loc in LOCALES:
        binding = dict(summary["bindings"][loc])
        bindings[loc] = {"releasePackageJsonSha256": targets[loc]["releasePackageJsonSha256"],
                         "audioFingerprint": binding}
    sidecar = {"schemaVersion": "sermon-published-alignment-v1", "pageId": PAGE_ID,
               "sourceIdentitySha256": esp_sha, "targets": bindings}
    sidecar_bytes = (json.dumps(sidecar, ensure_ascii=False, indent=1) + "\n").encode()
    files[f"alignment/{PAGE_ID}.json"] = sidecar_bytes
    public = assets_snapshot / "public"
    old = {name: json.loads((public / contract.CATALOG_FILES[name]).read_text()) for name in contract.CATALOG_FILES}
    contract.require(all(p["id"] != PAGE_ID for value in old.values() for p in value["pages"]),
                     "page is still in a live catalog; retract first")
    page = {"id": PAGE_ID, "date": base.DATE, "title": base.PAGE_TITLE, "defaultTargetLocale": "zh-Hans",
            "displayCategory": base.CATEGORY, "mediaType": "podcast", "sourceLocale": "en",
            "sourceIdentitySha256": esp_sha, "sourceMediaSha256": esp["source"]["media"]["sha256"],
            "sourceMode": "single_source", "sourceUrl": base.SOURCE_URL, "targets": targets}
    v5 = copy.deepcopy(old[contract.CATALOG_V5])
    v5["pages"].append(page)
    contract.validate_catalog_schema(v5)
    v4 = contract.project_legacy_catalog_v4(v5)
    v3 = contract.project_human_catalog(v4)
    for name, value in ((contract.CATALOG_V5, v5), (contract.CATALOG_V4, v4), (contract.CATALOG_V3, v3)):
        contract.validate_catalog_schema(value)
        files[contract.CATALOG_FILES[name]] = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    base.stage(assets_snapshot, out, None, files,
               replace=frozenset({f"alignment/{PAGE_ID}.json"} | {f"releases-v2/{PAGE_ID}/{loc}.json" for loc in LOCALES}))
    return {"staged": str(out), "changed": sorted(files), "sidecarSha256": hashlib.sha256(sidecar_bytes).hexdigest()}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("normalize"); a.add_argument("--out", type=Path, required=True)
    b = sub.add_parser("assets"); b.add_argument("--out", type=Path, required=True); b.add_argument("--normalized", type=Path, required=True)
    c = sub.add_parser("stage-assets"); c.add_argument("--baseline", type=Path, required=True); c.add_argument("--assets", type=Path, required=True); c.add_argument("--out", type=Path, required=True)
    d = sub.add_parser("verify"); d.add_argument("--assets", type=Path, required=True); d.add_argument("--evidence", type=Path, required=True)
    e = sub.add_parser("stage-release"); e.add_argument("--assets-snapshot", type=Path, required=True); e.add_argument("--assets", type=Path, required=True); e.add_argument("--evidence", type=Path, required=True); e.add_argument("--out", type=Path, required=True)
    f = sub.add_parser("bind"); f.add_argument("--baseline", type=Path, required=True); f.add_argument("--out", type=Path, required=True)
    g = sub.add_parser("verify-alignment"); g.add_argument("--assets", type=Path, required=True)
    r = sub.add_parser("retract"); r.add_argument("--baseline", type=Path, required=True); r.add_argument("--out", type=Path, required=True)
    pub = sub.add_parser("publish"); pub.add_argument("--snapshot", type=Path, required=True)
    rb = sub.add_parser("readback"); rb.add_argument("--snapshot", type=Path, required=True)
    args = p.parse_args()
    if args.cmd == "normalize":
        result = align.cmd_normalize(args.out)
    elif args.cmd == "assets":
        result = align.cmd_assets(args.out, args.normalized)
    elif args.cmd == "stage-assets":
        result = align.cmd_stage_assets(args.baseline, args.assets, args.out)
    elif args.cmd == "verify":
        result = align.cmd_verify(args.assets, args.evidence)
    elif args.cmd == "stage-release":
        result = cmd_stage_release_v2(args.assets_snapshot, args.evidence, args.assets, args.out)
    elif args.cmd == "bind":
        result = align.cmd_bind(args.baseline, args.out)
    elif args.cmd == "verify-alignment":
        result = align.cmd_verify_alignment(args.assets)
    elif args.cmd == "retract":
        result = cmd_retract(args.baseline, args.out)
    elif args.cmd == "publish":
        result = base.cmd_publish(args.snapshot)
    else:
        result = base.cmd_readback(args.snapshot)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
