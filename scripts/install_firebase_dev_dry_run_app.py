#!/usr/bin/env python3
"""Install the Dev-only simulated-week adapter on a complete Hosting snapshot."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil

try:
    from scripts import firebase_dev_four_layer_bucket_dry_run as dry
    from scripts.patch_firebase_dev_app_banner import patch_public
except ImportError:
    import firebase_dev_four_layer_bucket_dry_run as dry
    from patch_firebase_dev_app_banner import patch_public

SOURCE = Path(__file__).resolve().parents[1] / "firebase/dev/public"


def install(base_dev: Path, baseline_preflight: Path, page_id: str, out: Path) -> dict:
    if out.exists():
        raise ValueError("Dev App candidate already exists")
    if not re.fullmatch(r"dryrun-[A-Za-z0-9_-]+", page_id):
        raise ValueError("Expected a Dev simulation page ID")
    config = dry.read(base_dev / "firebase.json")
    if config.get("hosting", {}).get("site") != dry.DEV_SITE:
        raise ValueError("Not a complete Firebase Dev snapshot")
    preflight = dry.read(baseline_preflight)
    age = datetime.now(timezone.utc) - datetime.fromisoformat(
        preflight.get("checkedAt", "1970-01-01T00:00:00+00:00"))
    base_files = dry.weekly.regular_files(base_dev / "public")
    if (preflight.get("status") != "pass" or preflight.get("origin") != dry.DEV_ORIGIN
            or age.total_seconds() < 0 or age.total_seconds() > 3600
            or {row["path"]: row["sha256"] for row in preflight["files"]}
            != {name: dry.sha(path) for name, path in base_files.items()}):
        raise ValueError("Complete Dev snapshot does not match the live preflight")
    if not (base_dev / "public/app.mjs").read_text().count('from "/published-weeks.mjs"') == 1:
        raise ValueError("Dev App no longer imports the expected published-week bridge")
    catalog_path = base_dev / f"public/dry-run/{page_id}/catalog.json"
    catalog = dry.read(catalog_path)
    if catalog.get("status") != "simulation_only" or catalog.get("pageId") != page_id:
        raise ValueError("Dev simulation catalog differs")
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(base_dev, out, copy_function=dry.clone)
    public = out / "public"
    original = public / "published-weeks.mjs"
    if (public / "published-weeks-base.mjs").exists():
        raise ValueError("Dev simulation App adapter is already installed")
    shutil.copyfile(original, public / "published-weeks-base.mjs")
    original.unlink()  # copytree hardlinks; avoid overwriting the input snapshot
    shutil.copyfile(SOURCE / "published-weeks-dry-run.mjs", original)
    shutil.copyfile(SOURCE / "dry-run-app-weeks.mjs", public / "dry-run-app-weeks.mjs")
    app_path = public / "app.mjs"
    app_text = app_path.read_text(encoding="utf-8")
    replacements = {
        '$("content-language-note").textContent = t(week?.contentVariants ? "app.content.available" : "app.content.legacy");':
            '$("content-language-note").textContent = week?.simulationOnly ? "DEV 演练：选择片段试听语言；截片未单独人审。" : t(week?.contentVariants ? "app.content.available" : "app.content.legacy");',
        '$("review").textContent = t("app.content.disclosure");':
            '$("review").textContent = week?.simulationOnly ? "DEV 模拟产物；不得视为正式审核或发布。" : t("app.content.disclosure");',
        '$("transcript-description").textContent = week.contentVariants ? t("app.content.spokenHint") : guidance.join(" ");':
            '$("transcript-description").textContent = week.simulationOnly ? "DEV 演练：英文来自已审整篇对应区间；截片未单独人审。" : week.contentVariants ? t("app.content.spokenHint") : guidance.join(" ");',
    }
    for old, new in replacements.items():
        if app_text.count(old) != 1:
            raise ValueError(f"Dev App simulation label patch no longer matches: {old}")
        app_text = app_text.replace(old, new)
    app_path.unlink()  # hardlinked snapshot: never mutate the input App
    app_path.write_text(app_text, encoding="utf-8")
    patch_public(public)
    index_sha = dry.write(public / "dry-run/latest.json", {
        "schemaVersion": "sermon-dev-simulated-app-index-v1", "status": "simulation_only",
        "pageId": page_id, "catalogUrl": f"/dry-run/{page_id}/catalog.json",
        "catalogSha256": dry.sha(catalog_path),
    })
    new_files = dry.weekly.regular_files(public)
    changed = sorted(name for name in base_files if dry.sha(base_files[name]) != dry.sha(new_files[name]))
    added = sorted(set(new_files) - set(base_files))
    if changed != ["app.mjs", "dev-preview-label.mjs", "index.html", "published-weeks.mjs"] or added != [
            "dry-run-app-weeks.mjs", "dry-run/latest.json", "published-weeks-base.mjs"]:
        raise ValueError(f"Unexpected Dev App integration diff: changed={changed}, added={added}")
    report = {"schemaVersion": "sermon-dev-simulated-app-install-v1", "status": "candidate",
              "pageId": page_id, "baselinePreflightSha256": dry.sha(baseline_preflight),
              "baseFileCount": len(base_files), "candidateFileCount": len(new_files),
              "changed": changed, "added": added, "appIndexSha256": index_sha,
              "formalCatalogSha256": dry.sha(public / "multilingual-v3.json"),
              "legacyCatalogSha256": dry.sha(public / "weekly.json")}
    dry.write(out / "install-report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dev", type=Path, required=True)
    parser.add_argument("--baseline-preflight", type=Path, required=True)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = install(args.base_dev, args.baseline_preflight, args.page_id, args.out)
    print(json.dumps({key: result[key] for key in ("status", "pageId", "candidateFileCount")}))


if __name__ == "__main__":
    main()
