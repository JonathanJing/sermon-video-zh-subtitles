#!/usr/bin/env python3
"""Stage a compatible catalog using an explicitly pinned, hash-verified API snapshot."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

from deploy_firebase import verify_release
from deploy_feedback import public_week_date
from poc import sha256, write_json

HERE = Path(__file__).resolve().parent
PROJECT = "ai-for-god-caption-dev"
REGION = "us-west1"
DATABASE = "sermon-dubbing-feedback"
MANIFEST_SCHEMA = "sermon-feedback-api-source-manifest-v3"
HASH = re.compile(r"[a-f0-9]{64}\Z")


def source_identity(source):
    return source["week"], source["trackId"], source["audioSha256"]


def verified_feedback_catalog(release):
    """Do not follow source paths from reports; bind to explicit public files."""
    release = Path(release).resolve()
    public = release / "public"
    required = [release / "build-report.json", release / "feedback-catalog.json", public]
    if any(path.is_symlink() for path in required) or any(path.is_symlink() for path in public.rglob("*")):
        raise ValueError("Release inputs must not contain symlinks")
    report = verify_release(release)
    if report.get("schemaVersion") != "sermon-weekly-build-v1":
        raise ValueError("Unsupported listening build schema")
    if report.get("feedbackEnabled") is not True:
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
    allowed = ({"schemaVersion", "sources"}, {"schemaVersion", "sources", "weekIds", "voiceIds"})
    if not isinstance(catalog, dict) or set(catalog) not in allowed or type(catalog.get("schemaVersion")) is not int or catalog["schemaVersion"] != 1 or not isinstance(catalog.get("sources"), list):
        raise ValueError("Unsupported feedback catalog schema")
    weekly = json.loads((public / "weekly.json").read_text())
    if weekly.get("schemaVersion") != "sermon-weekly-catalog-v1" or not isinstance(weekly.get("weeks"), list):
        raise ValueError("Unsupported public weekly catalog schema")
    expected = {}
    week_ids, page_ids = set(), set()
    for week in weekly["weeks"]:
        week_date = public_week_date(week)
        if week["id"] in page_ids:
            raise ValueError("Repeated public source page identity")
        page_ids.add(week["id"])
        week_ids.add(week_date)
        for track in week["tracks"]:
            duration = track.get("durationSeconds")
            if not isinstance(track.get("id"), str) or not 1 <= len(track["id"]) <= 160 or not isinstance(track.get("sha256"), str) or not HASH.fullmatch(track["sha256"]):
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
    public_voices = [speaker["id"] for speaker in weekly.get("voiceBank", {}).get("speakers", [])]
    for field, expected_ids in [("weekIds", week_ids), ("voiceIds", public_voices)]:
        if field not in catalog:
            continue
        values = catalog[field]
        if not isinstance(values, list) or any(not isinstance(value, str) or not value or len(value) > 160 for value in values) or len(values) != len(set(values)) or set(values) != set(expected_ids):
            raise ValueError("Usage allowlist differs from public listening catalog")
    return catalog, {"release": str(release), "releaseBuildSha256": sha256(release / "build-report.json"),
        "feedbackCatalogSha256": sha256(release / "feedback-catalog.json"), "sourceCount": len(actual)}


def merge_release_catalogs(release, previous_releases=()):
    catalog, current = verified_feedback_catalog(release)
    sources = {source_identity(source): source for source in catalog["sources"]}
    usage_context = "weekIds" in catalog
    week_ids = set(catalog.get("weekIds", [source["week"] for source in catalog["sources"]]))
    voice_ids = set(catalog.get("voiceIds", []))
    compatible = []
    seen = {current["releaseBuildSha256"]}
    for previous in previous_releases:
        old_catalog, receipt = verified_feedback_catalog(previous)
        if receipt["releaseBuildSha256"] in seen:
            continue
        seen.add(receipt["releaseBuildSha256"])
        usage_context = usage_context or "weekIds" in old_catalog
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
    merged = {"schemaVersion": 1, "sources": list(sources.values())}
    if usage_context:
        merged.update(weekIds=sorted(week_ids), voiceIds=sorted(voice_ids))
    return merged, current, compatible


def api_runtime_snapshot(api_source):
    """All source files are hash-bound; only the runtime module graph is copied."""
    source = Path(api_source).resolve()

    def read_regular(name):
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Missing or unsafe API source file: " + name)
        return path.read_bytes()

    raw = read_regular("source-manifest.json")
    manifest_hash = hashlib.sha256(raw).hexdigest()
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list) or manifest.get("schemaVersion") not in (None, "sermon-feedback-api-source-manifest-v2", MANIFEST_SCHEMA):
        raise ValueError("API source requires a supported original file hash manifest")
    if any(not isinstance(manifest.get(key), str) or not HASH.fullmatch(manifest[key]) for key in ("releaseBuildSha256", "feedbackCatalogSha256")):
        raise ValueError("API source manifest lacks its listening release binding")
    verified = {}
    for item in manifest["files"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid API source manifest entry")
        name = item.get("path")
        allowed = name in {".gcloudignore", "catalog.json", "server-config.json", "package.json", "package-lock.json"} if isinstance(name, str) else False
        if not allowed and not (isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]+\.mjs", name)):
            raise ValueError("Unsupported path in API source manifest")
        if name in verified or not isinstance(item.get("sha256"), str) or not HASH.fullmatch(item["sha256"]):
            raise ValueError("Invalid or duplicate API source manifest entry")
        data = read_regular(name)
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("API source file changed: " + name)
        verified[name] = data

    def source_bytes(name):
        if name not in verified:
            raise ValueError("API runtime dependency is not hash-bound: " + name)
        return verified[name]

    expected_catalog_hash = manifest.get("runtimeCatalogSha256", manifest["feedbackCatalogSha256"])
    if hashlib.sha256(source_bytes("catalog.json")).hexdigest() != expected_catalog_hash:
        raise ValueError("API source catalog does not match its manifest binding")
    runtime = {name: source_bytes(name) for name in ("package.json", "package-lock.json")}
    pending = ["index.mjs"]
    while pending:
        name = pending.pop()
        if name in runtime:
            continue
        data = source_bytes(name)
        runtime[name] = data
        text = data.decode("utf-8")
        if re.search(r"\bimport\s*\(\s*(?!['\"\s])", text):
            raise ValueError("Computed imports require an explicit API packaging contract")
        for _, imported in re.findall(r"(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s*)(['\"])([^'\"]+)\1", text):
            if imported.startswith("."):
                if not re.fullmatch(r"\./[A-Za-z0-9_-]+\.mjs", imported):
                    raise ValueError("Only same-directory .mjs API imports may be packaged")
                pending.append(imported[2:])
            elif imported.startswith("/") or ":" in imported and not imported.startswith("node:"):
                raise ValueError("External-path API imports are not supported")
    config_bytes = source_bytes("server-config.json")
    config = json.loads(config_bytes)
    if config.get("projectId") != PROJECT or config.get("databaseId") != DATABASE or config.get("serviceAccount") != f"sermon-feedback-runtime@{PROJECT}.iam.gserviceaccount.com":
        raise ValueError("API source configuration targets another service")
    identity = {"kind": "verified_api_source_snapshot", "source": str(source), "sourceManifestSha256": manifest_hash,
        "verifiedSourceFiles": [{"path": name, "sha256": hashlib.sha256(data).hexdigest()} for name, data in sorted(verified.items())],
        "runtimeFiles": [{"path": name, "sha256": hashlib.sha256(data).hexdigest()} for name, data in sorted(runtime.items())],
        "serverConfigSha256": hashlib.sha256(config_bytes).hexdigest()}
    return runtime, config_bytes, identity


def prepare(release, out, previous_releases=(), *, api_source):
    out = Path(out)
    if out.exists():
        raise ValueError("Use a new API output directory to preserve earlier deployments")
    catalog, current, compatible = merge_release_catalogs(release, previous_releases)
    runtime, config_bytes, api_identity = api_runtime_snapshot(api_source)
    out.mkdir(parents=True)
    for name, data in runtime.items():
        (out / name).write_bytes(data)
    write_json(out / "catalog.json", catalog)
    (out / "server-config.json").write_bytes(config_bytes)
    (out / ".gcloudignore").write_text("node_modules/\ndeploy.log\ndeployment-receipt.json\nsource-manifest.json\n")
    manifest = {"schemaVersion": MANIFEST_SCHEMA,
        "releaseBuildSha256": current["releaseBuildSha256"], "feedbackCatalogSha256": current["feedbackCatalogSha256"],
        "runtimeCatalogSha256": sha256(out / "catalog.json"), "currentSourceCount": current["sourceCount"],
        "runtimeSourceCount": len(catalog["sources"]), "compatibleReleases": compatible,
        "compatibilityPolicy": "explicit_verified_previous_releases_only", "apiSource": api_identity,
        "files": [{"path": p.name, "sha256": sha256(p)} for p in sorted(out.iterdir()) if p.is_file()]}
    write_json(out / "source-manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--api-source", type=Path, required=True,
        help="Pinned API output directory with its original hash-verified source-manifest.json")
    parser.add_argument("--previous-release", type=Path, action="append", default=[],
        help="Keep the verified prior release's feedback sources for existing pages; may be repeated")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    release, out = args.release.resolve(), args.out.resolve()
    manifest = prepare(release, out, [path.resolve() for path in args.previous_release], api_source=args.api_source)
    command = ["gcloud", "functions", "deploy", "sermon-feedback-api", f"--project={PROJECT}", "--gen2", f"--region={REGION}",
        "--runtime=nodejs22", "--entry-point=sermonFeedback", f"--source={out}", "--trigger-http", "--allow-unauthenticated",
        f"--service-account=sermon-feedback-runtime@{PROJECT}.iam.gserviceaccount.com",
        f"--build-service-account=projects/{PROJECT}/serviceAccounts/sermon-feedback-build@{PROJECT}.iam.gserviceaccount.com",
        f"--docker-repository=projects/{PROJECT}/locations/{REGION}/repositories/sermon-feedback",
        "--memory=256Mi", "--cpu=1", "--concurrency=20", "--min-instances=0", "--max-instances=2", "--timeout=15s", "--quiet"]
    receipt = {"projectId": PROJECT, "databaseId": DATABASE, "region": REGION, "functionId": "sermon-feedback-api",
        "entryPoint": "sermonFeedback", "status": "prepared_not_deployed", "command": command,
        "sourceManifestSha256": sha256(out / "source-manifest.json"), "runtimeCatalogSha256": manifest["runtimeCatalogSha256"],
        "compatibleReleases": manifest["compatibleReleases"], "apiSource": manifest["apiSource"]}
    write_json(out / "deployment-receipt.json", receipt)
    if args.execute:
        with (out / "deploy.log").open("w") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        receipt["status"] = "deployed_verification_pending"
        write_json(out / "deployment-receipt.json", receipt)
    print(json.dumps({key: value for key, value in receipt.items() if key != "command"}), flush=True)


if __name__ == "__main__":
    main()
