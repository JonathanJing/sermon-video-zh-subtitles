#!/usr/bin/env python3
"""Stage a minimal feedback API bound to a verified listening release; opt-in deploy."""
import argparse
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

from deploy_firebase import verify_release
from poc import sha256, write_json

HERE = Path(__file__).resolve().parent
PROJECT = "ai-for-god-caption-dev"
REGION = "us-west1"
DATABASE = "sermon-dubbing-feedback"


def source_identity(source):
    return source["week"], source["trackId"], source["audioSha256"]


def public_week_date(week):
    """Project source pages onto the existing date-based feedback contract."""
    page_id, week_date = week.get("id"), week.get("date", week.get("id"))
    if not isinstance(page_id, str) or not isinstance(week_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", week_date):
        raise ValueError("Invalid public week identity")
    if page_id != week_date and (week.get("sourceRoute") not in {"live_archive", "same_video", "archive_caption"}
            or page_id != f'{week_date}-{week["sourceRoute"]}-{week.get("sourceId", "")}'):
        raise ValueError("Invalid public source page identity")
    return week_date


def verified_feedback_catalog(release):
    """Read only the explicit release's bound, public audio identities and cues."""
    release = Path(release).resolve()
    public = release / "public"
    required = [release / "build-report.json", release / "feedback-catalog.json", public]
    if any(path.is_symlink() for path in required) or any(path.is_symlink() for path in public.rglob("*")):
        raise ValueError("Release inputs must not contain symlinks")
    report = verify_release(release)
    if report.get("schemaVersion") != "sermon-weekly-build-v1":
        raise ValueError("Unsupported listening build schema")
    if not report.get("feedbackEnabled"):
        raise ValueError("Build the listening release with --feedback-enabled first")
    files = {item["path"]: item for item in report["files"]}
    if len(files) != len(report["files"]):
        raise ValueError("Repeated listening build file")
    for name, item in files.items():
        if type(item.get("bytes")) is not int or item["bytes"] != (public / name).stat().st_size:
            raise ValueError("Listening build file size changed")
    catalog = json.loads((release / "feedback-catalog.json").read_text())
    if report.get("feedbackCatalogSha256") != sha256(release / "feedback-catalog.json"):
        raise ValueError("Feedback catalog changed after the listening build")
    if not isinstance(catalog, dict) or set(catalog) not in ({"schemaVersion", "sources"}, {"schemaVersion", "sources", "weekIds", "voiceIds"}) or type(catalog.get("schemaVersion")) is not int or catalog["schemaVersion"] != 1 or not isinstance(catalog.get("sources"), list):
        raise ValueError("Unsupported feedback catalog schema")
    weekly = json.loads((public / "weekly.json").read_text())
    if weekly.get("schemaVersion") != "sermon-weekly-catalog-v1" or not isinstance(weekly.get("weeks"), list):
        raise ValueError("Unsupported public weekly catalog schema")
    expected = {}
    page_ids = set()
    for week in weekly["weeks"]:
        week_date = public_week_date(week)
        if week["id"] in page_ids:
            raise ValueError("Repeated public source page identity")
        page_ids.add(week["id"])
        for track in week["tracks"]:
            duration = track.get("durationSeconds")
            if not isinstance(track.get("id"), str) or not 1 <= len(track["id"]) <= 160 or not isinstance(track.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", track["sha256"]):
                raise ValueError("Invalid public audio identity")
            if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= 21600:
                raise ValueError("Invalid public audio duration")
            name = track.get("file")
            media = "media/" + name if isinstance(name, str) else ""
            if media not in files or not name.startswith(track["sha256"][:16] + "-") or track.get("audioUrl") != "/" + media or files[media]["sha256"] != track["sha256"]:
                raise ValueError("Feedback audio is not a verified public release file")
            cues = []
            previous_end = 0
            for index, cue in enumerate(track["cues"]):
                start, end = cue.get("start"), cue.get("end")
                if any(type(value) not in (int, float) or not math.isfinite(value) for value in (start, end)) or not 0 <= previous_end <= start < end <= duration + .001:
                    raise ValueError("Invalid public cue timing")
                block = cue.get("blockId")
                if block is not None and (isinstance(block, bool) or not isinstance(block, (str, int))):
                    raise ValueError("Invalid public cue block")
                cues.append({"id": str(index), "start": start, "end": end, "blockId": str(block) if block is not None else None})
                previous_end = end
            if not cues:
                raise ValueError("Public audio requires verified cues")
            source = {"week": week_date, "trackId": track["id"], "audioSha256": track["sha256"], "durationSeconds": duration,
                "cueIds": [cue["id"] for cue in cues], "blockIds": sorted({cue["blockId"] for cue in cues if cue["blockId"] is not None}), "cues": cues}
            key = source_identity(source)
            if key in expected:
                raise ValueError("Repeated public audio identity")
            expected[key] = source
    actual = {}
    for source in catalog["sources"]:
        if not isinstance(source, dict) or set(source) != {"week", "trackId", "audioSha256", "durationSeconds", "cueIds", "blockIds", "cues"}:
            raise ValueError("Invalid feedback source fields")
        try:
            key = source_identity(source)
            if key in actual or json.dumps(source, sort_keys=True) != json.dumps(expected.get(key), sort_keys=True):
                raise ValueError("Feedback source or timing differs from public audio")
            actual[key] = source
        except TypeError as exc:
            raise ValueError("Invalid feedback source identity") from exc
    if set(actual) != set(expected):
        raise ValueError("Feedback source catalog differs from public audio")
    # Optional usage allowlists are bound to the same verified public release.
    # Older feedback-only catalogs derive these lists from that public catalog.
    for field, expected_ids in [
        ("weekIds", sorted({public_week_date(week) for week in weekly["weeks"]})),
        ("voiceIds", [speaker["id"] for speaker in weekly.get("voiceBank", {}).get("speakers", [])]),
    ]:
        values = catalog.get(field, expected_ids)
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values) or len(values) != len(set(values)) or set(values) != set(expected_ids):
            raise ValueError("Usage allowlist differs from public listening catalog")
    return catalog, {"release": str(release), "releaseBuildSha256": sha256(release / "build-report.json"),
        "feedbackCatalogSha256": sha256(release / "feedback-catalog.json"), "sourceCount": len(actual)}


V4_CATALOG = "sermon-multilingual-catalog-v4"
_ID = re.compile(r"[A-Za-z0-9_-]{1,160}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def validate_catalog_snapshot(snapshot):
    """The four-layer sealed snapshot check, imported lazily so this entry point
    keeps working from its own directory."""
    import sys
    root = str(HERE.parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from scripts.delivery_contract import validate_catalog_snapshot as validate
    return validate(snapshot)


def v4_feedback_sources(public, catalog=None):
    """Feedback sources for every published v4 locale with audio, read from a sealed
    snapshot's public directory and bound to its bytes.

    The reader (published-weeks.mjs) names a v4 track ``<pageId>-<locale>-<first 12
    hex of the audio sha>`` and keeps the page date as the feedback week; the dub
    clock duration and the caption cues give the API its cue bounds, and each cue's
    block is its text group. ``pageId`` and ``audioLocale`` carry the listening
    identity the API already accepts. Without these sources /api/session answers
    unknown_source for a new week, which is what visitors saw on 2026-10-11."""
    public = Path(public).resolve()
    catalog = json.loads((public / "multilingual-v4.json").read_text()) if catalog is None else catalog
    if catalog.get("schemaVersion") != V4_CATALOG or not isinstance(catalog.get("pages"), list):
        raise ValueError("Unsupported v4 catalog schema")

    def bound(path, digest):
        target = (public / path.lstrip("/")).resolve()
        if not target.is_relative_to(public) or target.is_symlink() or not target.is_file() or sha256(target) != digest:
            raise ValueError("v4 asset is not a verified public release file: " + path)
        return target

    sources = []
    for page in catalog["pages"]:
        page_id, date = page.get("id"), page.get("date")
        if not isinstance(page_id, str) or not _ID.fullmatch(page_id) or not isinstance(date, str) or not _DATE.fullmatch(date):
            raise ValueError("Invalid v4 page identity")
        for locale, target in sorted((page.get("targets") or {}).items()):
            if "audio" not in (target.get("capabilities") or []):
                continue
            release = json.loads(bound(target["releasePackageUrl"], target.get("releasePackageJsonSha256")).read_text())
            if release.get("pageId") != page_id or release.get("targetLocale") != locale or release.get("audioLocale") != locale:
                raise ValueError("v4 release identity differs from the catalog page")
            assets = {row["role"]: row for row in release.get("assets", []) if isinstance(row, dict)}
            if any(role not in assets for role in ("audio", "content", "captions")):
                raise ValueError("v4 release lacks audio, content or captions")
            for role in ("audio", "content", "captions"):
                bound(assets[role]["path"], assets[role]["sha256"])
            content = json.loads((public / assets["content"]["path"].lstrip("/")).read_text())
            captions = json.loads((public / assets["captions"]["path"].lstrip("/")).read_text())
            duration = content.get("audioDurationSeconds", content.get("durationSeconds"))
            if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= 21600:
                raise ValueError("Invalid v4 audio duration")
            cues, previous = [], 0
            for index, cue in enumerate(captions.get("cues") or []):
                start, end, group = cue.get("start"), cue.get("end"), cue.get("textGroupId")
                if (any(type(value) not in (int, float) or not math.isfinite(value) for value in (start, end))
                        or not 0 <= previous <= start < end <= duration + .001 or not isinstance(group, str) or not group):
                    raise ValueError("Invalid v4 caption cue")
                cues.append({"id": str(index), "start": start, "end": end, "blockId": group})
                previous = end
            if not cues:
                raise ValueError("v4 audio requires published caption cues")
            sources.append({"week": date, "trackId": f"{page_id}-{locale}-{assets['audio']['sha256'][:12]}",
                            "audioSha256": assets["audio"]["sha256"], "durationSeconds": duration,
                            "cueIds": [cue["id"] for cue in cues], "blockIds": sorted({cue["blockId"] for cue in cues}),
                            "cues": cues, "pageId": page_id, "audioLocale": locale})
    return sources


def verified_runtime_catalog(api_source):
    """The runtime catalog of an earlier prepared API source directory, bound to the
    manifest it was deployed with. Keeping what production already serves does not
    require re-verifying the old listening releases with today's verifier."""
    api_source = Path(api_source).resolve()
    manifest_path, catalog_path = api_source / "source-manifest.json", api_source / "catalog.json"
    if any(path.is_symlink() or not path.is_file() for path in (manifest_path, catalog_path)):
        raise ValueError("Previous API source needs catalog.json and source-manifest.json")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("runtimeCatalogSha256") != sha256(catalog_path):
        raise ValueError("Previous runtime catalog differs from its source manifest")
    catalog = json.loads(catalog_path.read_text())
    if not isinstance(catalog, dict) or catalog.get("schemaVersion") != 1 or not isinstance(catalog.get("sources"), list):
        raise ValueError("Unsupported previous runtime catalog schema")
    for source in catalog["sources"]:
        if not isinstance(source, dict) or not {"week", "trackId", "audioSha256", "durationSeconds", "cueIds", "blockIds", "cues"} <= set(source):
            raise ValueError("Invalid previous runtime source")
    return catalog, {"runtime": str(api_source), "runtimeCatalogSha256": manifest["runtimeCatalogSha256"],
                     "sourceManifestSha256": sha256(manifest_path), "sourceCount": len(catalog["sources"])}


def merge_release_catalogs(release=None, previous_releases=(), v4_snapshots=(), previous_runtimes=()):
    """Keep old open pages working only for explicitly verified prior releases or
    an earlier deployed runtime catalog, and add every v4 page of the given sealed
    four-layer snapshots. ``release`` (a legacy listening release) is optional once
    the new weeks come from v4 snapshots."""
    if release is not None:
        catalog, current = verified_feedback_catalog(release)
    else:
        catalog, current = {"schemaVersion": 1, "sources": []}, None
    sources = {source_identity(source): source for source in catalog["sources"]}
    include_usage = "weekIds" in catalog
    week_ids = set(catalog.get("weekIds", [source["week"] for source in catalog["sources"]]))
    voice_ids = set(catalog.get("voiceIds", []))
    compatible = []
    seen = {current["releaseBuildSha256"]} if current else set()
    runtimes = []
    for previous in previous_runtimes:
        old_catalog, receipt = verified_runtime_catalog(previous)
        include_usage = include_usage or "weekIds" in old_catalog
        week_ids.update(old_catalog.get("weekIds", [source["week"] for source in old_catalog["sources"]]))
        voice_ids.update(old_catalog.get("voiceIds", []))
        added = 0
        for source in old_catalog["sources"]:
            key = source_identity(source)
            if key in sources and sources[key] != source:
                raise ValueError("Conflicting feedback timing for the same audio identity")
            if key not in sources:
                sources[key] = source
                added += 1
        runtimes.append({**receipt, "addedSourceCount": added})
    for previous in previous_releases:
        old_catalog, receipt = verified_feedback_catalog(previous)
        if receipt["releaseBuildSha256"] in seen:
            continue
        seen.add(receipt["releaseBuildSha256"])
        include_usage = include_usage or "weekIds" in old_catalog
        week_ids.update(old_catalog.get("weekIds", [source["week"] for source in old_catalog["sources"]]))
        voice_ids.update(old_catalog.get("voiceIds", []))
        added = 0
        for source in old_catalog["sources"]:
            key = source_identity(source)
            if key in sources and sources[key] != source:
                raise ValueError("Conflicting feedback timing for the same audio identity")
            if key not in sources:
                sources[key] = source
                added += 1
        compatible.append({**receipt, "addedSourceCount": added})
    snapshots = []
    for snapshot in v4_snapshots:
        snapshot = Path(snapshot).resolve()
        validate_catalog_snapshot(snapshot)
        added = 0
        for source in v4_feedback_sources(snapshot / "public"):
            key = source_identity(source)
            if key in sources and sources[key] != source:
                raise ValueError("Conflicting feedback timing for the same audio identity")
            if key not in sources:
                sources[key] = source
                added += 1
            week_ids.add(source["week"])
        snapshots.append({"snapshot": str(snapshot), "sealReportSha256": sha256(snapshot / "seal-report.json"),
                          "catalogV4Sha256": sha256(snapshot / "public/multilingual-v4.json"), "addedSourceCount": added})
    if not sources:
        raise ValueError("The runtime catalog would be empty; give a release, a previous runtime or a v4 snapshot")
    result = {"schemaVersion": 1, "sources": list(sources.values())}
    if include_usage:
        result.update(weekIds=sorted(week_ids), voiceIds=sorted(voice_ids))
    return result, current, compatible, snapshots, runtimes


def prepare(release, out, previous_releases=(), v4_snapshots=(), previous_runtimes=()):
    if out.exists():
        raise ValueError("Use a new API output directory to preserve earlier deployments")
    catalog, current, compatible, snapshots, runtimes = merge_release_catalogs(
        release, previous_releases, v4_snapshots, previous_runtimes)
    out.mkdir(parents=True)
    for name in ["index.mjs", "core.mjs", "usage-core.mjs", "firestore-store.mjs", "package.json", "package-lock.json"]:
        shutil.copyfile(HERE / "feedback-api" / name, out / name)
    write_json(out / "catalog.json", catalog)
    config = json.loads((HERE / "feedback-api/server-config.example.json").read_text())
    config.update(projectId=PROJECT, databaseId=DATABASE, serviceAccount=f"sermon-feedback-runtime@{PROJECT}.iam.gserviceaccount.com")
    write_json(out / "server-config.json", config)
    (out / ".gcloudignore").write_text("node_modules/\ndeploy.log\ndeployment-receipt.json\nsource-manifest.json\n")
    manifest = {"schemaVersion": "sermon-feedback-api-source-manifest-v2",
        # Null when the new weeks come from v4 snapshots and no legacy listening release was given.
        "releaseBuildSha256": current["releaseBuildSha256"] if current else None,
        "feedbackCatalogSha256": current["feedbackCatalogSha256"] if current else None,
        "runtimeCatalogSha256": sha256(out / "catalog.json"), "currentSourceCount": current["sourceCount"] if current else 0,
        "runtimeSourceCount": len(catalog["sources"]), "compatibleReleases": compatible,
        "fourLayerSnapshots": snapshots, "previousRuntimes": runtimes,
        "compatibilityPolicy": "explicit_verified_previous_releases_only",
        "files": [{"path": p.name, "sha256": sha256(p)} for p in sorted(out.iterdir()) if p.is_file()]}
    write_json(out / "source-manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, help="A legacy listening release built with --feedback-enabled")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--previous-release", type=Path, action="append", default=[],
        help="Retain a verified previous listening release's feedback sources for existing open pages; may be repeated")
    parser.add_argument("--previous-runtime", type=Path, action="append", default=[],
        help="Retain every source of an earlier prepared API source directory (catalog.json bound by its source-manifest.json); may be repeated")
    parser.add_argument("--v4-sealed", type=Path, action="append", default=[],
        help="A sealed four-layer snapshot (public/, seal-report.json) whose v4 pages get feedback sources; may be repeated")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not (args.release or args.v4_sealed or args.previous_runtime):
        parser.error("give --release, --v4-sealed or --previous-runtime")
    release, out = (args.release.resolve() if args.release else None), args.out.resolve()
    manifest = prepare(release, out, [path.resolve() for path in args.previous_release],
                       [path.resolve() for path in args.v4_sealed], [path.resolve() for path in args.previous_runtime])
    command = ["gcloud", "functions", "deploy", "sermon-feedback-api", f"--project={PROJECT}", "--gen2", f"--region={REGION}",
        "--runtime=nodejs22", "--entry-point=sermonFeedback", f"--source={out}", "--trigger-http", "--allow-unauthenticated",
        f"--service-account=sermon-feedback-runtime@{PROJECT}.iam.gserviceaccount.com",
        f"--build-service-account=projects/{PROJECT}/serviceAccounts/sermon-feedback-build@{PROJECT}.iam.gserviceaccount.com",
        f"--docker-repository=projects/{PROJECT}/locations/{REGION}/repositories/sermon-feedback",
        "--memory=256Mi", "--cpu=1", "--concurrency=20", "--min-instances=0", "--max-instances=2", "--timeout=15s", "--quiet"]
    receipt = {"projectId": PROJECT, "databaseId": DATABASE, "region": REGION, "functionId": "sermon-feedback-api",
        "entryPoint": "sermonFeedback", "status": "prepared_not_deployed", "command": command,
        "sourceManifestSha256": sha256(out / "source-manifest.json"), "runtimeCatalogSha256": manifest["runtimeCatalogSha256"],
        "compatibleReleases": manifest["compatibleReleases"]}
    write_json(out / "deployment-receipt.json", receipt)
    if args.execute:
        with (out / "deploy.log").open("w") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        receipt["status"] = "deployed_verification_pending"
        write_json(out / "deployment-receipt.json", receipt)
    print(json.dumps({key: value for key, value in receipt.items() if key != "command"}), flush=True)


if __name__ == "__main__":
    main()
