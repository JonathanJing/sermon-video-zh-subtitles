#!/usr/bin/env python3
"""Deploy only a verified static listening release to its dedicated Hosting site."""
import argparse
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

from poc import sha256, write_json

HERE = Path(__file__).resolve().parent
FINGERPRINT_UI = {"fingerprint-core.mjs", "fingerprint-capture.mjs", "fingerprint-worklet.mjs", "fingerprint-worker.mjs", "fingerprint-ui.mjs"}


def bound_fingerprints(public, expected):
    """Publish only a non-audio index bound to this source, window and track."""
    catalog = json.loads((public / "weekly.json").read_text()) if (public / "weekly.json").is_file() else {"weeks": []}
    if not isinstance(catalog, dict) or not isinstance(catalog.get("weeks", []), list):
        raise ValueError("Invalid fingerprint catalog")
    referenced = set()
    for week in catalog.get("weeks", []):
        if not isinstance(week, dict):
            raise ValueError("Invalid fingerprint week")
        binding = week.get("audioFingerprint")
        if binding is None:
            continue
        if catalog.get("schemaVersion") != "sermon-weekly-catalog-v1":
            raise ValueError("Unsupported fingerprint catalog schema")
        if not isinstance(binding, dict) or binding.get("schemaVersion") != "sermon-audio-fingerprint-binding-v1":
            raise ValueError("Unsupported audio fingerprint binding")
        required = {"schemaVersion", "algorithmVersion", "captureSeconds", "indexUrl", "indexSha256",
                    "sourceSha256", "trackSha256", "pageId", "sourceStartSeconds", "sourceEndSeconds"}
        if not required.issubset(binding):
            raise ValueError("Incomplete audio fingerprint binding")
        if binding.get("algorithmVersion") != "spectral-landmarks-v1" or binding.get("captureSeconds") != 10:
            raise ValueError("Unsupported audio fingerprint algorithm or capture duration")
        for field in ("indexSha256", "sourceSha256", "trackSha256"):
            if not re.fullmatch(r"[a-f0-9]{64}", str(binding.get(field, ""))):
                raise ValueError("Invalid audio fingerprint identity hash")
        match = re.fullmatch(r"/fingerprints/([a-f0-9]{16})-landmarks\.json", str(binding.get("indexUrl", "")))
        if not match or match.group(1) != binding["indexSha256"][:16]:
            raise ValueError("Fingerprint index URL must be content addressed and local")
        name = binding["indexUrl"][1:]
        info = expected.get(name, {})
        path = public / name
        if (info.get("sha256") != binding["indexSha256"] or not path.is_file() or path.is_symlink()
                or (public / "fingerprints").is_symlink() or not path.resolve().is_relative_to(public)
                or not 0 < path.stat().st_size <= 16 * 1024 * 1024 or info.get("bytes") != path.stat().st_size):
            raise ValueError("Fingerprint index is not bound to a regular release file")
        if sha256(path) != binding["indexSha256"]:
            raise ValueError("Fingerprint index content changed")
        index = json.loads(path.read_text())
        if not isinstance(index, dict) or index.get("schemaVersion") != "sermon-landmark-index-v1":
            raise ValueError("Unsupported fingerprint index schema")
        for field in ("pageId", "sourceSha256", "trackSha256", "sourceStartSeconds", "sourceEndSeconds", "algorithmVersion"):
            if index.get(field) != binding.get(field):
                raise ValueError("Fingerprint index and catalog identity disagree")
        if (binding["pageId"] != week.get("id") or week.get("sourceRoute") != "same_video"
                or not str(week.get("sourceId", "")).endswith(binding["sourceSha256"][:16])):
            raise ValueError("Fingerprint source does not match the selected recording")
        start, end = binding["sourceStartSeconds"], binding["sourceEndSeconds"]
        if (type(start) not in (int, float) or type(end) not in (int, float) or not 0 <= start < end
                or not math.isfinite(start) or not math.isfinite(end)
                or start != week.get("sourceStartSeconds") or end != week.get("sourceEndSeconds")):
            raise ValueError("Fingerprint source window changed")
        all_tracks = week.get("tracks")
        if not isinstance(all_tracks, list) or any(not isinstance(t, dict) for t in all_tracks):
            raise ValueError("Invalid fingerprint audio tracks")
        tracks = [t for t in all_tracks if t.get("sha256") == binding["trackSha256"]]
        if (len(tracks) != 1 or type(tracks[0].get("durationSeconds")) not in (int, float)
                or not math.isfinite(tracks[0]["durationSeconds"])
                or abs(tracks[0]["durationSeconds"] - (end - start)) > .1):
            raise ValueError("Fingerprint requires a same-clock full sermon audio track")
        track = tracks[0]
        track_name = "media/" + str(track.get("file", ""))
        track_info = expected.get(track_name, {})
        if (not re.fullmatch(r"media/" + binding["trackSha256"][:16] + r"-[\w.-]+\.mp3", track_name)
                or track.get("audioUrl") != "/" + track_name
                or track_info.get("sha256") != binding["trackSha256"]
                or type(track_info.get("bytes")) is not int or track_info["bytes"] <= 0
                or (public / track_name).is_symlink() or (public / "media").is_symlink()):
            raise ValueError("Fingerprint audio must bind to the published hashed MP3")
        allowed = {"schemaVersion", "algorithmVersion", "sampleRate", "hopSize", "fftSize", "sourceSha256", "trackSha256", "pageId", "sourceStartSeconds", "sourceEndSeconds", "window", "durationSeconds", "landmarkCount", "postings"}
        if set(index) != allowed or (index["sampleRate"], index["hopSize"], index["fftSize"]) != (8000, 256, 1024):
            raise ValueError("Fingerprint index may contain only supported numeric landmarks and identity fields")
        if index["window"] != {"startSeconds": start, "endSeconds": end} or index["durationSeconds"] != end - start:
            raise ValueError("Fingerprint index duration disagrees with source window")
        if not isinstance(index.get("postings"), dict) or not index["postings"]:
            raise ValueError("Fingerprint index must contain landmark postings")
        if type(index["landmarkCount"]) is not int or not 1 <= index["landmarkCount"] <= 1000000:
            raise ValueError("Invalid fingerprint landmark count")
        count = 0
        for key, times in index["postings"].items():
            if (not re.fullmatch(r"0|[1-9][0-9]{0,9}", key) or int(key) > 4294967295
                    or not isinstance(times, list) or not times or len(times) > 10000):
                raise ValueError("Invalid fingerprint posting")
            previous = -1
            for frame in times:
                if type(frame) is not int or not previous < frame <= (end - start) * 8000 / 256:
                    raise ValueError("Fingerprint posting must contain ordered source frame numbers")
                previous = frame
            count += len(times)
        if not 1 <= count <= index["landmarkCount"]:
            raise ValueError("Fingerprint posting count disagrees with index")
        referenced.add(name)
    if {name for name in expected if name.startswith("fingerprints/")} != referenced:
        raise ValueError("Unbound fingerprint files may not be uploaded")
    if referenced and not FINGERPRINT_UI.issubset(expected):
        raise ValueError("Fingerprint browser runtime is incomplete")
    return referenced


def verify_release(release):
    report = json.loads((release / "build-report.json").read_text())
    public = (release / "public").resolve()
    expected = {f["path"]: f for f in report["files"]}
    actual = {str(p.relative_to(public)) for p in public.rglob("*") if p.is_file()}
    if len(expected) != len(report["files"]) or actual != set(expected):
        raise ValueError("Unexpected or missing upload files")
    fingerprints = bound_fingerprints(public, expected)
    for name, info in expected.items():
        path = public / name
        if not path.resolve().is_relative_to(public) or sha256(path) != info["sha256"]:
            raise ValueError("Release file or path changed")
        if name not in {"index.html", "style.css", "app.mjs", "timing.mjs", "catalog.mjs", "theme.js", "weekly.json"} | FINGERPRINT_UI and name not in fingerprints and not re.fullmatch(r"media/[a-f0-9]{16}-[\w.-]+\.mp3", name):
            raise ValueError("Only UI, weekly content, hashed listening MP3s and bound fingerprint indexes may be uploaded")
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
