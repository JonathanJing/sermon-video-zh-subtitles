#!/usr/bin/env python3
"""Deploy one preflight-checked multilingual Production Hosting candidate.

This is an explicit operator command. Without --execute it writes only a plan.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

try:
    from scripts import assemble_multilingual_hosting as hosting
except ImportError:
    import assemble_multilingual_hosting as hosting


PROJECT = "ai-for-god-caption-dev"
SITE = "ai-for-god-sermon-audio"
ORIGIN = f"https://{SITE}.web.app"
COMMAND = ["npx", "--yes", "firebase-tools@15.29.0", "deploy", "--only",
           "hosting:sermonDubbing", "--project", PROJECT, "--non-interactive",
           "--message", "Reviewed multilingual sermon release"]


def prepare(candidate: Path, preflight: Path) -> dict:
    report = hosting.load(candidate / "build-report.json")
    receipt = hosting.load(preflight)
    if (report.get("schemaVersion") != "sermon-multilingual-hosting-candidate-v1"
            or report.get("status") != "validated_not_deployed"
            or report.get("productionReader") is not True):
        raise ValueError("Expected an immutable Production Hosting candidate")
    if (receipt.get("schemaVersion") != "sermon-multilingual-hosting-baseline-check-v1"
            or receipt.get("status") != "pass" or receipt.get("origin") != ORIGIN
            or receipt.get("pageId") != report.get("newPageId")
            or receipt.get("buildReportSha256") != hosting.digest(candidate / "build-report.json")
            or receipt.get("checkedFiles") != len(report.get("baseFiles", []))):
        raise ValueError("Preflight does not bind this candidate and complete base snapshot")
    checked_at = datetime.fromisoformat(receipt["checkedAt"])
    age = datetime.now(timezone.utc) - checked_at.astimezone(timezone.utc)
    if not 0 <= age.total_seconds() <= 30 * 60:
        raise ValueError("Preflight is older than 30 minutes; rerun against live Production")
    expected = {item["path"]: item for item in report["files"]}
    actual = hosting.regular_files(candidate / "public")
    if len(expected) != len(report["files"]) or set(expected) != set(actual):
        raise ValueError("Candidate file inventory changed")
    for name, path in actual.items():
        if path.stat().st_size != expected[name]["bytes"] or hosting.digest(path) != expected[name]["sha256"]:
            raise ValueError(f"Candidate file changed: {name}")
    config = hosting.load(candidate / "firebase.json")
    targets = hosting.load(candidate / ".firebaserc")
    if (report.get("firebaseConfigSha256") != hosting.digest(candidate / "firebase.json")
            or report.get("firebaseTargetsSha256") != hosting.digest(candidate / ".firebaserc")):
        raise ValueError("Firebase configuration changed after candidate preparation")
    destination = "/index.html" if report.get("promotedHome") else "/multilingual-reader.html"
    if (config.get("hosting", {}).get("target") != "sermonDubbing"
            or config["hosting"].get("public") != "public"
            or targets.get("projects", {}).get("default") != PROJECT
            or targets.get("targets", {}).get(PROJECT, {}).get("hosting", {}).get("sermonDubbing") != [SITE]
            or {"source": "/pages/**", "destination": destination}
            not in config["hosting"].get("rewrites", [])):
        raise ValueError("Firebase target or multilingual route changed")
    feedback_rewrite = {"source": "/api/**", "function": {
        "functionId": "sermon-feedback-api", "region": "us-west1"}}
    if (feedback_rewrite in config["hosting"].get("rewrites", [])) != report["feedbackEnabled"]:
        raise ValueError("Firebase feedback route differs from base snapshot")
    return {
        "schemaVersion": "sermon-multilingual-hosting-deployment-v1",
        "status": "validated_not_deployed", "projectId": PROJECT,
        "siteId": SITE, "origin": ORIGIN, "pageId": report["newPageId"],
        "buildReportSha256": hosting.digest(candidate / "build-report.json"),
        "preflightSha256": hosting.digest(preflight),
        "files": len(expected), "command": COMMAND,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--preflight", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.out.exists() or args.out.is_symlink():
        raise ValueError(f"Deployment receipt already exists: {args.out}")
    receipt = prepare(args.candidate, args.preflight)
    if args.execute:
        subprocess.run(COMMAND, cwd=args.candidate, check=True)
        receipt["status"] = "deployed_http_verification_pending"
        receipt["deployedAt"] = datetime.now(timezone.utc).isoformat()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                        encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("status", "pageId", "siteId", "files")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
