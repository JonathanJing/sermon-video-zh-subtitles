#!/usr/bin/env python3
"""Deploy only a verified static listening release to its dedicated Hosting site."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from poc import sha256, write_json

HERE = Path(__file__).resolve().parent
DOWNLOAD_EXTENSIONS = {"readingPdf": "pdf", "companionPdf": "pdf", "fullVideoMp3": "mp3", "fullVideoSrt": "srt"}
DOWNLOAD_PATH = re.compile(r"/downloads/([a-f0-9]{16})-[A-Za-z0-9][A-Za-z0-9._-]*\.(pdf|mp3|srt)")
FINGERPRINT_UI = {"fingerprint-core.mjs", "fingerprint-capture.mjs", "fingerprint-worklet.mjs", "fingerprint-worker.mjs", "fingerprint-ui.mjs"}
PRODUCTION_SITE = "ai-for-god-sermon-audio"
PRODUCTION_PROJECT = "ai-for-god-caption-dev"


def guard_multilingual_home(project, site, *, allow_rollback=False, opener=urlopen):
    """Keep the legacy deploy guarded even if the earlier preflight changes."""
    if (project, site) != (PRODUCTION_PROJECT, PRODUCTION_SITE) or allow_rollback:
        return
    url = f"https://{site}.web.app/multilingual-v2.json"
    try:
        with opener(Request(url, method="GET"), timeout=30) as response:
            status = response.status
    except HTTPError as error:
        status = error.code
    if status == 404:
        return
    if status == 200:
        raise ValueError("Production has a multilingual catalog; use the overlay release or explicit rollback")
    raise ValueError(f"Cannot establish Production multilingual state: HTTP {status}")


def production_has_multilingual_catalog(site, *, opener=urlopen):
    """Fail closed before a legacy-only deploy can erase the formal catalog."""
    url = f"https://{site}.web.app/multilingual-v2.json"
    try:
        with opener(Request(url, method="GET"), timeout=30) as response:
            final = urlparse(response.geturl())
            if (final.scheme, final.netloc, final.path) != (
                    "https", f"{site}.web.app", "/multilingual-v2.json"):
                raise ValueError("Multilingual catalog request redirected")
            if response.status != 200:
                raise ValueError("Unexpected multilingual catalog response")
            value = json.load(response)
            if value.get("schemaVersion") != "sermon-multilingual-catalog-v2":
                raise ValueError("Production catalog is unreadable; refuse legacy deploy")
            return True
    except HTTPError as error:
        if error.code == 404:
            return False
        raise


def validate_automatic_audio_alignment(catalog, required_pages=()):
    """New weekly pages declare availability; historical catalogs remain readable."""
    if (not isinstance(required_pages, (list, tuple))
            or any(not isinstance(page, str) for page in required_pages)
            or len(set(required_pages)) != len(required_pages)):
        raise ValueError("Invalid automatic audio alignment page requirements")
    if not isinstance(catalog, dict) or catalog.get("schemaVersion") != "sermon-weekly-catalog-v1":
        raise ValueError("Unsupported weekly catalog schema")
    weeks = catalog.get("weeks", [])
    if not isinstance(weeks, list) or any(not isinstance(w, dict) for w in weeks):
        raise ValueError("Invalid automatic audio alignment catalog")
    by_id = {week.get("id"): week for week in weeks}
    for page in required_pages:
        if page not in by_id or "automaticAudioAlignment" not in by_id[page]:
            raise ValueError("Required automatic audio alignment declaration is missing")
    for week in weeks:
        marker = week.get("automaticAudioAlignment")
        if marker is None and "automaticAudioAlignment" not in week:
            continue
        if not isinstance(marker, dict) or marker.get("schemaVersion") != "sermon-automatic-audio-alignment-v1":
            raise ValueError("Unsupported automatic audio alignment declaration")
        if marker.get("status") == "ready":
            if marker.get("required") is not True or not isinstance(week.get("audioFingerprint"), dict):
                raise ValueError("Automatic audio alignment requires a bound fingerprint index")
            if week.get("videoSynchronization") not in {"candidate_aligned", "human_reviewed"}:
                raise ValueError("Automatic audio alignment requires a synchronized track")
            if not re.fullmatch(r"[a-f0-9]{64}", str(week.get("sourceSha256", ""))):
                raise ValueError("Automatic audio alignment requires explicit source identity")
        elif marker.get("status") == "unavailable":
            if (marker.get("required") is not False or marker.get("reason") != "unsynchronized_review_preview"
                    or week.get("audioStatus") != "full_candidate"
                    or week.get("videoSynchronization") != "not_validated"
                    or week.get("audioFingerprint") is not None
                    or any(t.get("subtitleTiming") in {"source_video_aligned_candidate", "human_reviewed_source_video"}
                           for t in week.get("tracks", []))):
                raise ValueError("Only an unsynchronized review preview may omit automatic audio alignment")
        else:
            raise ValueError("Unsupported automatic audio alignment availability")


def bound_fingerprints(public, expected, required_pages=()):
    """Publish only a non-audio index bound to this source, window and track."""
    catalog = json.loads((public / "weekly.json").read_text()) if (public / "weekly.json").is_file() else {"schemaVersion": "sermon-weekly-catalog-v1", "weeks": []}
    validate_automatic_audio_alignment(catalog, required_pages)
    referenced = set()
    for week in catalog.get("weeks", []):
        binding = week.get("audioFingerprint")
        if binding is None:
            continue
        if not isinstance(binding, dict) or binding.get("schemaVersion") != "sermon-audio-fingerprint-binding-v1":
            raise ValueError("Unsupported audio fingerprint binding")
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
                or not 0 < path.stat().st_size <= 16 * 1024 * 1024):
            raise ValueError("Fingerprint index is not bound to a regular release file")
        if sha256(path) != binding["indexSha256"]:
            raise ValueError("Fingerprint index content changed")
        index = json.loads(path.read_text())
        if index.get("schemaVersion") != "sermon-landmark-index-v1":
            raise ValueError("Unsupported fingerprint index schema")
        for field in ("pageId", "sourceSha256", "trackSha256", "sourceStartSeconds", "sourceEndSeconds", "algorithmVersion"):
            if index.get(field) != binding.get(field):
                raise ValueError("Fingerprint index and catalog identity disagree")
        explicit_source = week.get("sourceSha256")
        source_matches = (explicit_source == binding["sourceSha256"] if explicit_source is not None else
                          week.get("sourceRoute") == "same_video" and
                          week.get("sourceId", "").endswith(binding["sourceSha256"][:16]))
        if (binding["pageId"] != week["id"]
                or week.get("sourceRoute") not in {"same_video", "archive_caption", "live_archive"}
                or not source_matches):
            raise ValueError("Fingerprint source does not match the selected recording")
        start, end = binding["sourceStartSeconds"], binding["sourceEndSeconds"]
        if (type(start) not in (int, float) or type(end) not in (int, float) or not 0 <= start < end
                or start != week.get("sourceStartSeconds") or end != week.get("sourceEndSeconds")):
            raise ValueError("Fingerprint source window changed")
        tracks = [t for t in week["tracks"] if t["sha256"] == binding["trackSha256"]]
        if len(tracks) != 1 or abs(tracks[0]["durationSeconds"] - (end - start)) > .1:
            raise ValueError("Fingerprint requires a same-clock full sermon audio track")
        track = tracks[0]
        filename = track.get("file")
        if (not isinstance(filename, str)
                or not re.fullmatch(r"[a-f0-9]{16}-[\w.-]+\.mp3", filename)
                or not filename.startswith(binding["trackSha256"][:16] + "-")
                or track.get("audioUrl") != "/media/" + filename):
            raise ValueError("Fingerprint track must reference its content-addressed local MP3")
        track_name = "media/" + filename
        track_info = expected.get(track_name, {})
        track_path = public / track_name
        if (track_info.get("sha256") != binding["trackSha256"]
                or not track_path.is_file() or track_path.is_symlink()
                or (public / "media").is_symlink()
                or not track_path.resolve().is_relative_to(public)
                or track_path.stat().st_size <= 0
                or track_info.get("bytes") != track_path.stat().st_size
                or sha256(track_path) != binding["trackSha256"]):
            raise ValueError("Fingerprint track is not bound to a nonempty published MP3")
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


def bound_downloads(public, expected):
    """Only catalog-selected, content-addressed local deliverables can upload."""
    catalog_path = public / "weekly.json"
    catalog = json.loads(catalog_path.read_text()) if catalog_path.is_file() else {"weeks": []}
    if not isinstance(catalog, dict) or not isinstance(catalog.get("weeks", []), list):
        raise ValueError("Invalid catalog download bindings")
    referenced = set()
    for week in catalog.get("weeks", []):
        if not isinstance(week, dict):
            raise ValueError("Invalid catalog week")
        downloads = week.get("downloads", {})
        if not isinstance(downloads, dict) or set(downloads) - set(DOWNLOAD_EXTENSIONS):
            raise ValueError("Unsupported catalog download fields")
        for kind, url in downloads.items():
            match = DOWNLOAD_PATH.fullmatch(url) if isinstance(url, str) else None
            if not match or match.group(2) != DOWNLOAD_EXTENSIONS[kind]:
                raise ValueError("Download must be a local content-addressed file of its declared format")
            name = url[1:]
            info = expected.get(name)
            if not info or not re.fullmatch(r"[a-f0-9]{64}", str(info.get("sha256", ""))):
                raise ValueError("Catalog download is not bound to release files")
            path = public / name
            if (match.group(1) != info["sha256"][:16] or not path.is_file() or path.is_symlink()
                    or (public / "downloads").is_symlink()
                    or not path.resolve().is_relative_to(public) or path.stat().st_size <= 0):
                raise ValueError("Download hash prefix, path or content is invalid")
            referenced.add(name)
    if {name for name in expected if name.startswith("downloads/")} != referenced:
        raise ValueError("Unreferenced download files may not be uploaded")
    return referenced


def verify_release(release):
    report = json.loads((release / "build-report.json").read_text())
    public = (release / "public").resolve()
    expected = {f["path"]: f for f in report["files"]}
    actual = {str(p.relative_to(public)) for p in public.rglob("*") if p.is_file()}
    if len(expected) != len(report["files"]) or actual != set(expected):
        raise ValueError("Unexpected or missing upload files")
    downloads = bound_downloads(public, expected)
    fingerprints = bound_fingerprints(public, expected, report.get("automaticAudioAlignmentPages", ()))
    for name, info in expected.items():
        path = public / name
        if not path.resolve().is_relative_to(public) or sha256(path) != info["sha256"]:
            raise ValueError("Release file or path changed")
        if name not in {"index.html", "style.css", "app.mjs", "timing.mjs", "catalog.mjs", "theme.js", "weekly.json", "feedback.mjs", "feedback-client.mjs", "listening.mjs", "usage.mjs", "usage-client.mjs", "playback-memory.mjs", "i18n.mjs", "locales-interface.mjs", "locales-app.mjs", "locales-feedback.mjs", "locales-ko.mjs", "locales-es.mjs", "content-locales.mjs", "engagement.json", "brand-icon.png"} | FINGERPRINT_UI and not re.fullmatch(r"media/[a-f0-9]{16}-[\w.-]+\.mp3", name) and name not in downloads | fingerprints:
            raise ValueError("Only UI, weekly content, hashed listening MP3s and bound downloads may be uploaded")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--site", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-multilingual-rollback", action="store_true",
                        help="Explicitly replace a multilingual Production site with this legacy snapshot")
    args = parser.parse_args()
    release = args.release.resolve()
    report = verify_release(release)
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", args.site) or args.site == args.project:
        raise ValueError("Use a dedicated, non-default site ID")
    if args.allow_multilingual_rollback and not args.execute:
        raise ValueError("Rollback override applies only to an actual deploy")
    if (args.execute and args.site == PRODUCTION_SITE
            and production_has_multilingual_catalog(args.site)
            and not args.allow_multilingual_rollback):
        raise ValueError("Production has a multilingual catalog; use the overlay release path or explicit rollback")
    hosting_config = json.loads((HERE / "firebase/firebase.json").read_text())
    if report.get("feedbackEnabled"):
        hosting_config["hosting"]["rewrites"] = [{"source": "/api/**", "function": {"functionId": "sermon-feedback-api", "region": "us-west1"}}]
    write_json(release / "firebase.json", hosting_config)
    write_json(release / ".firebaserc", {"projects": {"default": args.project}, "targets": {args.project: {"hosting": {"sermonDubbing": [args.site]}}}})
    receipt = {"projectId": args.project, "siteId": args.site, "url": f"https://{args.site}.web.app", "files": len(report["files"]), "bytes": report["totalBytes"],
        "buildReportSha256": sha256(release / "build-report.json"), "only": "hosting:sermonDubbing", "status": "validated_not_deployed"}
    if args.execute:
        guard_multilingual_home(args.project, args.site,
                                allow_rollback=args.allow_multilingual_rollback)
        command = ["npx", "--yes", "firebase-tools@15.29.0", "deploy", "--only", "hosting:sermonDubbing", "--project", args.project, "--non-interactive", "--message", "Weekly Chinese sermon listening app"]
        with (release / "deploy.log").open("w") as log:
            subprocess.run(command, cwd=release, stdout=log, stderr=subprocess.STDOUT, check=True)
        receipt["status"] = "deployed_http_verification_pending"
    write_json(release / "deployment-receipt.json", receipt)
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
