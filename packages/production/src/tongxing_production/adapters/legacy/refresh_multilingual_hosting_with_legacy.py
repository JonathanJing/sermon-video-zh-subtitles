#!/usr/bin/env python3
"""Apply a prepared legacy weekly release to a verified multilingual Hosting snapshot.

The result is a new immutable Hosting candidate. This command never deploys.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

try:
    from scripts import assemble_multilingual_hosting as hosting
except ImportError:
    import assemble_multilingual_hosting as hosting


ROOT = Path(__file__).resolve().parents[1]
LEGACY_CODE = ROOT / "experiments/sermon-dubbing-poc"
if str(LEGACY_CODE) not in sys.path:
    sys.path.insert(0, str(LEGACY_CODE))
import weekly_release  # noqa: E402


def snapshot_files(public: Path) -> list[dict]:
    return [{"path": name, "sha256": hosting.digest(path), "bytes": path.stat().st_size}
            for name, path in sorted(hosting.regular_files(public).items())]


def refresh(base: Path, legacy: Path, prior_http: Path, out: Path) -> dict:
    if out.exists() or out.is_symlink():
        raise ValueError("Use a new Hosting candidate directory")
    base_report = hosting.load(base / "build-report.json")
    old_public = base / "public"
    old_files = hosting.regular_files(old_public)
    if (base_report.get("schemaVersion") != "sermon-multilingual-hosting-candidate-v1"
            or base_report.get("status") != "validated_not_deployed"
            or base_report.get("productionReader") is not True
            or snapshot_files(old_public) != base_report.get("files")
            or hosting.digest(base / "firebase.json") != base_report.get("firebaseConfigSha256")
            or hosting.digest(base / ".firebaserc") != base_report.get("firebaseTargetsSha256")):
        raise ValueError("Current multilingual candidate is not immutable and complete")
    http = hosting.load(prior_http)
    if (http.get("schemaVersion") != "sermon-multilingual-hosting-http-verification-v1"
            or http.get("status") != "pass"
            or http.get("origin") != "https://ai-for-god-sermon-audio.web.app"
            or http.get("buildReportSha256") != hosting.digest(base / "build-report.json")
            or http.get("checkedFiles") != len(old_files)):
        raise ValueError("Prior Production HTTP receipt does not bind the current site")
    old_catalog = hosting.load(old_public / hosting.CATALOG)
    hosting.validate_catalog(old_catalog)
    hosting.verify_catalog_assets(old_public, old_catalog)

    legacy_report, new_weekly = weekly_release.read_release(legacy)
    plan = hosting.load(legacy / "release-plan.json")
    previous_weekly = hosting.load(old_public / "weekly.json")
    previous_ids = {page["id"] for page in previous_weekly["weeks"]}
    incoming_ids = {page["id"] for page in new_weekly["weeks"]}
    if (plan.get("schemaVersion") != "sermon-weekly-release-plan-v1"
            or plan.get("status") != "prepared_not_deployed"
            or legacy_report.get("reviewPreview") is not False
            or plan.get("origin") != http["origin"]
            or plan.get("buildReportSha256") != hosting.digest(legacy / "build-report.json")
            or plan.get("previousWeekIds") != sorted(previous_ids)
            or plan.get("weekIds") != sorted(incoming_ids)
            or plan.get("changes", {}).get("removed") != []
            or plan.get("uiPolicy") != "reuse_registered_ui_and_settings"
            or not previous_ids.issubset(incoming_ids)):
        raise ValueError("Legacy release does not extend the current weekly catalog")
    if legacy_report["feedbackEnabled"] != base_report["feedbackEnabled"]:
        raise ValueError("Legacy release changed the feedback configuration")
    if hosting.digest(legacy / "public/index.html") != base_report["legacyHomepageSha256"]:
        raise ValueError("Legacy UI changed outside the reviewed UI release path")

    incoming_files = hosting.regular_files(legacy / "public")
    for name, path in incoming_files.items():
        if name in {"index.html", "weekly.json"}:
            continue
        if name in old_files and hosting.digest(path) != hosting.digest(old_files[name]):
            raise ValueError(f"Legacy release would overwrite an existing file: {name}")
        if name not in old_files and not name.startswith(("media/", "downloads/", "fingerprints/")):
            raise ValueError(f"Legacy release added unreviewed UI/configuration: {name}")

    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        public = temporary / "public"
        shutil.copytree(old_public, public)
        for name, source in incoming_files.items():
            if name in {"index.html", "weekly.json"} or name in old_files:
                continue
            target = public / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        shutil.copyfile(legacy / "public/weekly.json", public / "weekly.json")
        for name in ("firebase.json", ".firebaserc"):
            shutil.copyfile(base / name, temporary / name)
        if legacy_report["feedbackEnabled"]:
            source = legacy / "feedback-catalog.json"
            if (not source.is_file() or
                    hosting.digest(source) != legacy_report.get("feedbackCatalogSha256")):
                raise ValueError("New feedback catalog is missing or changed")
            shutil.copyfile(source, temporary / "feedback-catalog.json")
        hosting.verify_catalog_assets(public, old_catalog)
        new_files = snapshot_files(public)
        modified = sorted(name for name in old_files
                          if hosting.digest(old_files[name]) != hosting.digest(public / name))
        report = dict(base_report)
        report.update(
            status="validated_not_deployed",
            baseFiles=snapshot_files(old_public),
            files=new_files,
            modifiedFiles=modified,
            preservedFileCount=len(old_files) - len(modified),
            addedFileCount=len(new_files) - len(old_files),
            legacyWeeklyReleaseBuildReportSha256=hosting.digest(legacy / "build-report.json"),
            legacyWeeklyReleasePlanSha256=hosting.digest(legacy / "release-plan.json"),
            priorHttpVerificationSha256=hosting.digest(prior_http),
        )
        if legacy_report["feedbackEnabled"]:
            report["feedbackCatalogSha256"] = hosting.digest(temporary / "feedback-catalog.json")
        (temporary / "build-report.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
        os.rename(temporary, out)
        return report
    except Exception:
        shutil.rmtree(temporary)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-candidate", required=True, type=Path)
    parser.add_argument("--legacy-release", required=True, type=Path)
    parser.add_argument("--prior-http-verification", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    report = refresh(args.base_candidate, args.legacy_release,
                     args.prior_http_verification, args.out)
    print(json.dumps({key: report[key] for key in
                      ("status", "newPageId", "preservedFileCount", "addedFileCount")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
