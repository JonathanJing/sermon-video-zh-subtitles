#!/usr/bin/env python3
"""Deploy only a verified static listening release to its dedicated Hosting site."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

from poc import sha256, write_json

HERE = Path(__file__).resolve().parent


def verify_release(release):
    report = json.loads((release / "build-report.json").read_text())
    public = (release / "public").resolve()
    expected = {f["path"]: f for f in report["files"]}
    actual = {str(p.relative_to(public)) for p in public.rglob("*") if p.is_file()}
    if actual != set(expected):
        raise ValueError("Unexpected or missing upload files")
    for name, info in expected.items():
        path = public / name
        if not path.resolve().is_relative_to(public) or sha256(path) != info["sha256"]:
            raise ValueError("Release file or path changed")
        if name not in {"index.html", "style.css", "app.mjs", "timing.mjs", "catalog.mjs", "theme.js", "weekly.json"} and not re.fullmatch(r"media/[a-f0-9]{16}-[\w.-]+\.mp3", name):
            raise ValueError("Only UI, weekly content and hashed listening MP3s may be uploaded")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--site", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    release = args.release.resolve()
    report = verify_release(release)
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", args.site) or args.site == args.project:
        raise ValueError("Use a dedicated, non-default site ID")
    shutil.copyfile(HERE / "firebase/firebase.json", release / "firebase.json")
    write_json(release / ".firebaserc", {"projects": {"default": args.project}, "targets": {args.project: {"hosting": {"sermonDubbing": [args.site]}}}})
    receipt = {"projectId": args.project, "siteId": args.site, "url": f"https://{args.site}.web.app", "files": len(report["files"]), "bytes": report["totalBytes"],
        "buildReportSha256": sha256(release / "build-report.json"), "only": "hosting:sermonDubbing", "status": "validated_not_deployed"}
    if args.execute:
        command = ["npx", "--yes", "firebase-tools@15.29.0", "deploy", "--only", "hosting:sermonDubbing", "--project", args.project, "--non-interactive", "--message", "Weekly Chinese sermon listening app"]
        with (release / "deploy.log").open("w") as log:
            subprocess.run(command, cwd=release, stdout=log, stderr=subprocess.STDOUT, check=True)
        receipt["status"] = "deployed_http_verification_pending"
    write_json(release / "deployment-receipt.json", receipt)
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
