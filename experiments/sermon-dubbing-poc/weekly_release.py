#!/usr/bin/env python3
"""Versioned weekly content releases; no model calls or network deployment.

Existing builders produce a candidate. This module preserves the registered
catalog and UI, merges candidate pages/media, and records a new head only after
an independently supplied HTTP verification receipt. Original releases survive.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from urllib.parse import urlsplit

from build_weekly_app import validate_catalog
from deploy_firebase import verify_release


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".json-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def origin_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or parsed.port not in {None, 443}):
        raise ValueError("origin must be an HTTPS origin without path or credentials")
    return "https://" + parsed.hostname.lower()


def safe_name(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("invalid release file path")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(p in {".", ".."} or p.startswith(".") for p in path.parts):
        raise ValueError("invalid release file path")
    return value


def read_release(release: Path) -> tuple[dict, dict]:
    release = Path(release)
    public = release / "public"
    if release.is_symlink() or public.is_symlink() or (release / "build-report.json").is_symlink():
        raise ValueError("release inputs must not be symlinks")
    if not public.is_dir() or any(p.is_symlink() for p in public.rglob("*")):
        raise ValueError("release public files must be regular local files")
    report = read_json(release / "build-report.json")
    if report.get("schemaVersion") != "sermon-weekly-build-v1" or report.get("trainingDataPublished") is not False:
        raise ValueError("unsupported or unsafe release report")
    files = report.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("release has no file manifest")
    expected = {}
    for entry in files:
        name = safe_name(entry["path"])
        if name in expected or type(entry.get("bytes")) is not int or entry["bytes"] < 0:
            raise ValueError("duplicate release file or invalid size")
        if not re.fullmatch(r"[a-f0-9]{64}", str(entry.get("sha256", ""))):
            raise ValueError("invalid release file hash")
        expected[name] = entry
    # Keep the deployed uploader's strict public-file allowlist.
    verify_release(release)
    if "weekly.json" not in expected or "index.html" not in expected:
        raise ValueError("release lacks UI or weekly catalog")
    if any((public / name).stat().st_size != item["bytes"] for name, item in expected.items()):
        raise ValueError("release file size differs from manifest")
    if report.get("totalBytes") != sum(item["bytes"] for item in files):
        raise ValueError("release totalBytes differs from files")
    catalog = read_json(public / "weekly.json")
    validate_catalog(catalog)
    weeks = catalog["weeks"]
    if report.get("weeks") != len(weeks) or report.get("playableWeeks") != sum(bool(w["tracks"]) for w in weeks):
        raise ValueError("release week counts differ from catalog")
    tracks = []
    for week in weeks:
        date = week.get("date", week["id"])
        if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError("invalid content date")
        if week["id"] != date and (week.get("sourceRoute") not in {"same_video", "live_archive", "archive_caption"}
                or week["id"] != f"{date}-{week['sourceRoute']}-{week.get('sourceId', '')}"):
            raise ValueError("page ID does not match its source identity")
        if len({t["id"] for t in week["tracks"]}) != len(week["tracks"]):
            raise ValueError("duplicate track ID")
        tracks.extend(week["tracks"])
    for speaker in catalog.get("voiceBank", {}).get("speakers", []):
        tracks.extend([speaker["reference"], speaker["chinese"]])
    for track in tracks:
        name = safe_name("media/" + track["file"])
        if name not in expected or expected[name]["sha256"] != track["sha256"]:
            raise ValueError("catalog audio is not bound to release files")
        if expected[name]["bytes"] <= 0:
            raise ValueError("audio file is empty")
        if not track["file"].startswith(track["sha256"][:16] + "-"):
            raise ValueError("audio filename is not content-addressed")
        # Alignment indexes need the corresponding uploader/schema support.
        if track.get("alignment") is not None:
            raise ValueError("alignment-index releases require a separate supported publisher")
    if report.get("feedbackEnabled"):
        from deploy_feedback import verified_feedback_catalog
        verified_feedback_catalog(release)
    if "engagement.json" in expected:
        engagement = read_json(public / "engagement.json")
        if engagement.get("enabled") is not bool(report.get("feedbackEnabled")):
            raise ValueError("feedback setting and release report disagree")
    return report, catalog


def release_id(report):
    return "rel_" + json_hash(report)[:24]


@contextmanager
def registry_lock(registry):
    registry = Path(registry)
    if registry.is_symlink():
        raise ValueError("registry must not be a symlink")
    registry.mkdir(parents=True, exist_ok=True)
    lock = registry / ".registry.lock"
    if lock.is_symlink():
        raise ValueError("registry lock must not be a symlink")
    with lock.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def load_registry(registry):
    registry = Path(registry)
    if registry.is_symlink() or (registry / "registry.json").is_symlink() or (registry / "releases").is_symlink():
        raise ValueError("registry must be local regular storage")
    data = read_json(registry / "registry.json")
    if data.get("schemaVersion") != "sermon-weekly-release-registry-v1":
        raise ValueError("unsupported registry")
    if not re.fullmatch(r"rel_[a-f0-9]{24}", str(data.get("head", ""))):
        raise ValueError("invalid registry head")
    release = registry / "releases" / data["head"]
    report, catalog = read_release(release)
    if release_id(report) != data["head"]:
        raise ValueError("registry head content changed")
    return data, release, report, catalog


def copy_release(source, destination):
    report, _ = read_release(source)
    destination = Path(destination)
    if destination.exists():
        raise ValueError("snapshot already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=destination.parent))
    try:
        shutil.copytree(Path(source) / "public", temporary / "public")
        shutil.copy2(Path(source) / "build-report.json", temporary / "build-report.json")
        if report.get("feedbackEnabled"):
            shutil.copy2(Path(source) / "feedback-catalog.json", temporary / "feedback-catalog.json")
        copied, _ = read_release(temporary)
        if copied != report:
            raise ValueError("source report changed during snapshot")
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def check_verification(release, receipt, origin):
    report, _ = read_release(release)
    if (receipt.get("passed") is not True or receipt.get("origin") != origin_url(origin)
            or receipt.get("buildReportSha256") != sha256(Path(release) / "build-report.json")):
        raise ValueError("verification receipt does not bind this release and origin")
    files = {f["path"]: f for f in report["files"]}
    checked = receipt.get("checkedFiles", [])
    if (len(checked) != len(files) or {f.get("path") for f in checked} != set(files)
            or receipt.get("expectedFileCount") != len(files) or receipt.get("checkedFileCount") != len(files)):
        raise ValueError("HTTP verification file coverage incomplete")
    for item in checked:
        expected = files[item["path"]]
        if (item.get("passed") is not True or item.get("httpStatus") != 200
                or item.get("expectedSha256") != expected["sha256"] or item.get("observedSha256") != expected["sha256"]
                or item.get("expectedBytes") != expected["bytes"] or item.get("receivedBytes") != expected["bytes"]):
            raise ValueError("HTTP verification file result inconsistent")
    audio = {name: f for name, f in files.items() if name.endswith(".mp3")}
    ranges = receipt.get("audioRanges", [])
    if len(ranges) != len(audio) or {r.get("path") for r in ranges} != set(audio):
        raise ValueError("HTTP range verification coverage incomplete")
    for item in ranges:
        size = audio[item["path"]]["bytes"]
        length = min(1024, size)
        with (Path(release) / "public" / item["path"]).open("rb") as stream:
            prefix_hash = hashlib.sha256(stream.read(length)).hexdigest()
        if (item.get("passed") is not True or item.get("httpStatus") != 206
                or item.get("contentRange") != f"bytes 0-{length-1}/{size}"
                or item.get("observedSha256") != prefix_hash or item.get("expectedSha256") != prefix_hash
                or item.get("receivedBytes") != length or item.get("expectedBytes") != length):
            raise ValueError("HTTP range verification result inconsistent")
    return report


def bootstrap(registry, release, origin, verification=None):
    registry, release = Path(registry), Path(release)
    if registry.resolve().is_relative_to(release.resolve()):
        raise ValueError("registry must be outside the source release")
    origin = origin_url(origin)
    report, catalog = read_release(release)
    if verification is not None:
        check_verification(release, verification, origin)
    identity = release_id(report)
    with registry_lock(registry):
        if (registry / "releases").is_symlink():
            raise ValueError("registry releases must not be a symlink")
        if (registry / "registry.json").exists():
            raise ValueError("registry already initialized")
        destination = registry / "releases" / identity
        if not destination.exists():
            copy_release(release, destination)
        else:
            previous, _ = read_release(destination)
            if release_id(previous) != identity:
                raise ValueError("existing registry snapshot differs")
        state = {"schemaVersion": "sermon-weekly-release-registry-v1", "origin": origin,
                 "head": identity, "generation": 0, "updatedAt": now(),
                 "history": [{"releaseId": identity, "parentReleaseId": None,
                              "status": "published_http_verified" if verification else "baseline_registered_local",
                              "weeks": len(catalog["weeks"]), "at": now()}]}
        if verification:
            write_json(destination / "http-verification.json", verification)
        write_json(registry / "registry.json", state)
    return state


def merged_catalog(base, candidate, replace_ids=()):
    result = copy.deepcopy(base)
    old = {w["id"]: w for w in base["weeks"]}
    replace_ids = set(replace_ids)
    if not replace_ids.issubset(set(old) & {w["id"] for w in candidate["weeks"]}):
        raise ValueError("replacement IDs must exist in both baseline and candidate")
    merged = copy.deepcopy(old)
    for week in candidate["weeks"]:
        if week["id"] in old and any(old[week["id"]].get(k) != week.get(k) for k in ("date", "sourceId", "sourceRoute")):
            raise ValueError("existing page source identity cannot change")
        if week["id"] in old and week != old[week["id"]] and week["id"] not in replace_ids:
            raise ValueError("existing page changed; explicitly select --replace-page " + week["id"])
        merged[week["id"]] = copy.deepcopy(week)
    result["weeks"] = sorted(merged.values(), key=lambda w: (w.get("date", w["id"]), w["id"]), reverse=True)
    result["defaultWeekId"] = result["weeks"][0]["id"]
    if "voiceBank" in candidate and candidate["voiceBank"] != base.get("voiceBank"):
        raise ValueError("voice bank changes require a separate reviewed release")
    validate_catalog(result)
    return result, {"added": sorted(set(merged)-set(old)),
                    "updated": sorted(k for k in old if merged[k] != old[k]),
                    "unchanged": sorted(k for k in old if merged[k] == old[k]), "removed": []}


def feedback_catalog(catalog):
    sources = []
    for week in catalog["weeks"]:
        for track in week["tracks"]:
            cues = [{"id": str(i), "start": c["start"], "end": c["end"],
                     "blockId": str(c["blockId"]) if c.get("blockId") is not None else None}
                    for i, c in enumerate(track["cues"])]
            sources.append({"week": week.get("date", week["id"]), "trackId": track["id"],
                            "audioSha256": track["sha256"], "durationSeconds": track["durationSeconds"],
                            "cueIds": [c["id"] for c in cues], "blockIds": sorted({c["blockId"] for c in cues if c["blockId"] is not None}), "cues": cues})
    return {"schemaVersion": 1, "sources": sources,
            "weekIds": sorted({w.get("date", w["id"]) for w in catalog["weeks"]}),
            "voiceIds": [s["id"] for s in catalog.get("voiceBank", {}).get("speakers", [])]}


def prune_unreferenced_assets(public, catalog):
    """Drop replaced download/index files from an owned staging output only.

    Call after constructing the final catalog, never on a source release or a
    registry snapshot. Media and UI remain untouched. Every reference and every
    deletion path is checked before deleting any staging file.
    """
    from deploy_firebase import DOWNLOAD_EXTENSIONS, DOWNLOAD_PATH
    public = Path(public)
    if public.is_symlink() or not public.is_dir():
        raise ValueError("asset pruning requires a regular staging public directory")
    public = public.resolve()
    validate_catalog(catalog)
    referenced = set()
    for week in catalog["weeks"]:
        downloads = week.get("downloads", {})
        if not isinstance(downloads, dict) or set(downloads) - set(DOWNLOAD_EXTENSIONS):
            raise ValueError("unsupported download references during staging cleanup")
        for kind, url in downloads.items():
            match = DOWNLOAD_PATH.fullmatch(url) if isinstance(url, str) else None
            if not match or match.group(2) != DOWNLOAD_EXTENSIONS[kind]:
                raise ValueError("unsafe download reference during staging cleanup")
            referenced.add(safe_name(url[1:]))
        binding = week.get("audioFingerprint")
        if binding is not None:
            url = binding.get("indexUrl") if isinstance(binding, dict) else None
            if not isinstance(url, str) or not re.fullmatch(r"/fingerprints/[a-f0-9]{16}-landmarks\.json", url):
                raise ValueError("unsafe fingerprint reference during staging cleanup")
            referenced.add(safe_name(url[1:]))
    for name in referenced:
        target = public / name
        if (not target.is_file() or target.is_symlink() or target.parent.is_symlink()
                or not target.resolve().is_relative_to(public)):
            raise ValueError("referenced staging asset is missing or unsafe")
    remove = []
    for name in ("downloads", "fingerprints"):
        folder = public / name
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            raise ValueError("staging asset directory must be a regular directory")
        if not folder.exists():
            continue
        for target in folder.rglob("*"):
            if target.is_symlink() or not target.resolve().is_relative_to(public):
                raise ValueError("unsafe staging asset path")
            if target.is_file() and str(target.relative_to(public)) not in referenced:
                remove.append(target)
    removed = sorted(str(path.relative_to(public)) for path in remove)
    for target in remove:
        target.unlink()
    return removed


def prepare(registry, candidate, out, replace_ids=()):
    registry, candidate, out = Path(registry), Path(candidate), Path(out)
    if out.exists() or out.is_symlink():
        raise ValueError("use a new output directory")
    if out.resolve().is_relative_to(registry.resolve()) or out.resolve().is_relative_to(candidate.resolve()):
        raise ValueError("output must be outside registry and candidate release")
    state, base, base_report, base_catalog = load_registry(registry)
    candidate_report, candidate_catalog = read_release(candidate)
    catalog, changes = merged_catalog(base_catalog, candidate_catalog, replace_ids)
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".weekly-release-", dir=out.parent))
    try:
        public = temporary / "public"
        shutil.copytree(base / "public", public)
        if any(sha256(public / f["path"]) != f["sha256"] for f in base_report["files"]):
            raise ValueError("registered release changed during copy")
        for item in candidate_report["files"]:
            name = item["path"]
            if not name.startswith(("media/", "downloads/", "fingerprints/")):
                continue  # The weekly content release keeps registered UI/settings.
            target = public / name
            if target.exists() and sha256(target) != item["sha256"]:
                raise ValueError("content-addressed media collision")
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(candidate / "public" / name, target)
            if sha256(target) != item["sha256"]:
                raise ValueError("candidate media changed during copy")
        write_json(public / "weekly.json", catalog)
        pruned_assets = prune_unreferenced_assets(public, catalog)
        report = copy.deepcopy(base_report)
        sources = {json_hash(s): s for s in base_report.get("sources", []) + candidate_report.get("sources", [])}
        files = [{"path": str(p.relative_to(public)), "sha256": sha256(p), "bytes": p.stat().st_size}
                 for p in sorted(public.rglob("*")) if p.is_file()]
        report.update(builtAt=now(), weeks=len(catalog["weeks"]), playableWeeks=sum(bool(w["tracks"]) for w in catalog["weeks"]),
                      files=files, sources=list(sources.values()), totalBytes=sum(f["bytes"] for f in files), includeHistory=True,
                      reviewPreview=any(w.get("audioStatus") != "full_reviewed" for w in catalog["weeks"]),
                      contentReviewSha256=None, originalAudioPublished=bool(catalog.get("voiceBank")),
                      originalAudioScope="short_authorized_voice_references_only" if catalog.get("voiceBank") else "none",
                      releaseRegistry={"parentReleaseId": state["head"], "parentGeneration": state["generation"],
                                       "candidateBuildReportSha256": sha256(candidate / "build-report.json"),
                                       "prunedUnreferencedAssets": pruned_assets})
        if report.get("feedbackEnabled"):
            write_json(temporary / "feedback-catalog.json", feedback_catalog(catalog))
            report["feedbackCatalogSha256"] = sha256(temporary / "feedback-catalog.json")
        write_json(temporary / "build-report.json", report)
        read_release(temporary)
        plan = {"schemaVersion": "sermon-weekly-release-plan-v1", "createdAt": now(), "origin": state["origin"],
                "parentReleaseId": state["head"], "parentGeneration": state["generation"], "releaseId": release_id(report),
                "buildReportSha256": sha256(temporary / "build-report.json"), "changes": changes,
                "previousWeekIds": sorted(w["id"] for w in base_catalog["weeks"]),
                "weekIds": sorted(w["id"] for w in catalog["weeks"]), "status": "prepared_not_deployed",
                "uiPolicy": "reuse_registered_ui_and_settings", "humanApprovalGranted": False,
                "workflowComplete": False, "rollbackReleaseId": state["head"]}
        write_json(temporary / "release-plan.json", plan)
        temporary.rename(out)
        return plan
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def record_published(registry, release, verification):
    registry, release = Path(registry), Path(release)
    plan = read_json(release / "release-plan.json")
    with registry_lock(registry):
        state, _, _, current_catalog = load_registry(registry)
        report = check_verification(release, verification, state["origin"])
        identity = release_id(report)
        if plan.get("releaseId") != identity or plan.get("buildReportSha256") != sha256(release / "build-report.json"):
            raise ValueError("release plan changed or does not match output")
        if plan.get("origin") != state["origin"] or plan.get("changes", {}).get("removed") != []:
            raise ValueError("release plan origin or history preservation invalid")
        if state["head"] == identity and state["history"][-1]["status"] == "published_http_verified":
            return state
        if plan.get("parentReleaseId") != state["head"] or plan.get("parentGeneration") != state["generation"]:
            raise ValueError("registry advanced; rebuild candidate against current head")
        bound_parent = report.get("releaseRegistry", {})
        if bound_parent.get("parentReleaseId") != state["head"] or bound_parent.get("parentGeneration") != state["generation"]:
            raise ValueError("build report parent does not match registry and plan")
        old_pages = {w["id"] for w in current_catalog["weeks"]}
        new_pages = {w["id"] for w in read_json(release / "public/weekly.json")["weeks"]}
        if (not old_pages.issubset(new_pages) or plan.get("previousWeekIds") != sorted(old_pages)
                or plan.get("weekIds") != sorted(new_pages)):
            raise ValueError("release does not preserve registered page history")
        destination = registry / "releases" / identity
        if not destination.exists():
            copy_release(release, destination)
        else:
            existing, _ = read_release(destination)
            if release_id(existing) != identity:
                raise ValueError("saved release content changed")
        write_json(destination / "http-verification.json", verification)
        write_json(destination / "release-plan.json", plan)
        state["generation"] += 1
        state["history"].append({"releaseId": identity, "parentReleaseId": state["head"], "at": now(),
                                 "status": "published_http_verified", "weeks": report["weeks"],
                                 "clientSmoke": verification.get("client_smoke", "not_run")})
        state.update(head=identity, updatedAt=now())
        write_json(registry / "registry.json", state)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    boot = commands.add_parser("bootstrap")
    boot.add_argument("--registry", type=Path, required=True)
    boot.add_argument("--release", type=Path, required=True)
    boot.add_argument("--origin", required=True)
    boot.add_argument("--verification", type=Path)
    build = commands.add_parser("prepare")
    build.add_argument("--registry", type=Path, required=True)
    build.add_argument("--candidate", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--replace-page", action="append", default=[], help="Explicitly replace this existing page, retaining candidate review status")
    publish = commands.add_parser("record-published")
    publish.add_argument("--registry", type=Path, required=True)
    publish.add_argument("--release", type=Path, required=True)
    publish.add_argument("--verification", type=Path, required=True)
    inspect = commands.add_parser("status")
    inspect.add_argument("--registry", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "bootstrap":
        result = bootstrap(args.registry, args.release, args.origin, read_json(args.verification) if args.verification else None)
    elif args.command == "prepare":
        result = prepare(args.registry, args.candidate, args.out, args.replace_page)
    elif args.command == "record-published":
        result = record_published(args.registry, args.release, read_json(args.verification))
    else:
        result, _, _, catalog = load_registry(args.registry)
        result = {**result, "pages": [{k: w.get(k) for k in ("id", "date", "sourceId", "title", "audioStatus", "videoSynchronization")} for w in catalog["weeks"]]}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
