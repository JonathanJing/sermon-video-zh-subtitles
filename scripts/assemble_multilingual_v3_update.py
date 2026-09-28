#!/usr/bin/env python3
"""Assemble a Production v3 weekly update without deploying it.

The legacy profile stages 21 Hosting assets. The bucket-video profile stages
20 Hosting assets and binds one separately uploaded, immutable MP4 object.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile

from jsonschema import Draft202012Validator, FormatChecker

try:
    from scripts.assemble_multilingual_hosting import digest, load, regular_files, checked_public_path
except ImportError:
    from assemble_multilingual_hosting import digest, load, regular_files, checked_public_path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = "multilingual-v3.json"
SCHEMA = "sermon-multilingual-catalog-v3.schema.json"
RELEASE_SCHEMA = "sermon-target-language-release-package-v2.schema.json"
SUPPORTED_LOCALES = {"zh-Hans", "ko", "es"}
STAGE_SCHEMA = "sermon-multilingual-v3-stage-manifest-v2"
STAGE_SCHEMA_FILE = f"{STAGE_SCHEMA}.schema.json"
PUBLICATION_PROFILE = "three_locale_full_video_v1"
STAGE_FILE_COUNT = 21
WEEKLY_FILE_COUNT = STAGE_FILE_COUNT + 1  # The mutable v3 catalog is updated last.
BUCKET_PROFILE = "three_locale_bucket_video_v2"
BUCKET_STAGE_SCHEMA = "sermon-multilingual-v3-stage-manifest-v3"
BUCKET_STAGE_FILE_COUNT = 20


def validate_schema(value: dict, name: str) -> None:
    schema = load(ROOT / "schemas" / name)
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    if errors:
        raise ValueError(f"{name}: {errors[0].message}")


def require_file(public: Path, url: str, expected_sha: str) -> Path:
    path = checked_public_path(public, url)
    if not path.is_file() or path.is_symlink() or digest(path) != expected_sha:
        raise ValueError(f"Missing or changed asset: {url}")
    return path


def validate_page(public: Path, page: dict) -> set[str]:
    """Return all direct catalog/release/fingerprint/sidecar references."""
    page_id = page["id"]
    refs: set[str] = set()
    releases: dict[str, dict] = {}
    video_sha: str | None = None
    for locale, target in page["targets"].items():
        release_url = f"/releases-v2/{page_id}/{locale}.json"
        if target["releasePackageUrl"] != release_url:
            raise ValueError(f"{page_id}/{locale}: wrong Release URL")
        release_path = require_file(public, release_url, target["releasePackageJsonSha256"])
        refs.add(release_url[1:])
        release = load(release_path)
        validate_schema(release, RELEASE_SCHEMA)
        if (release["pageId"] != page_id or release["targetLocale"] != locale
                or release["contentLocale"] != locale
                or release["audioStatus"] != target["audioStatus"]
                or release["contentStatus"] != target["contentStatus"]
                or release["status"] != "published_http_verified"
                or release["httpVerification"]["status"] != "pass"
                or release["issues"]):
            raise ValueError(f"{page_id}/{locale}: Release identity/status mismatch")
        releases[locale] = release
        roles: dict[str, dict] = {}
        for asset in release["assets"]:
            role, url = asset["role"], asset["path"]
            if role in roles:
                raise ValueError(f"{page_id}/{locale}: duplicate asset role {role}")
            roles[role] = asset
            require_file(public, url, asset["sha256"])
            refs.add(url[1:])
        for role, url in {
            "page": f"/pages/{page_id}/{locale}/index.html",
            "content": f"/content/{page_id}/{locale}.json",
            "captions": f"/captions/{page_id}/{locale}.json",
        }.items():
            if roles.get(role, {}).get("path") != url:
                raise ValueError(f"{page_id}/{locale}: missing {role}")
        content = load(public / f"content/{page_id}/{locale}.json")
        if content.get("pageId") != page_id or content.get("targetLocale") != locale:
            raise ValueError(f"{page_id}/{locale}: content identity differs")
        if not isinstance(content.get("browserVideoSha256"), str):
            raise ValueError(f"{page_id}/{locale}: browser video binding missing")
        if video_sha is None:
            video_sha = content["browserVideoSha256"]
        elif video_sha != content["browserVideoSha256"]:
            raise ValueError(f"{page_id}/{locale}: browser video binding differs")
        if locale == page["defaultTargetLocale"]:
            title = f"{content.get('series', '').strip()} · {content.get('title', '').strip()}"
            if title != page["title"]:
                raise ValueError(f"{page_id}: catalog title differs from approved content")
        has_audio = target["audioStatus"] == "human_reviewed"
        if has_audio != ("audio" in roles):
            raise ValueError(f"{page_id}/{locale}: audio capability differs")
        if has_audio and (release["audioLocale"] != locale
                          or "audio" not in target["capabilities"]):
            raise ValueError(f"{page_id}/{locale}: audio locale/capability differs")
        if has_audio and roles["audio"]["path"] != f"/media/{page_id}/{locale}.mp3":
            raise ValueError(f"{page_id}/{locale}: audio must use the canonical weekly path")
        if not has_audio and (release["audioLocale"] is not None
                              or "audio" in target["capabilities"]):
            raise ValueError(f"{page_id}/{locale}: text-only capability differs")
        binding = target.get("audioFingerprint")
        if (binding is not None) != ("alignment" in target["capabilities"]):
            raise ValueError(f"{page_id}/{locale}: alignment capability differs")
        if binding:
            if (binding["pageId"] != page_id
                    or binding["sourceSha256"] != page["sourceMediaSha256"]
                    or binding["trackSha256"] != roles["audio"]["sha256"]):
                raise ValueError(f"{page_id}/{locale}: fingerprint binding differs")
            if binding["indexUrl"] != f"/fingerprints/{binding['indexSha256'][:16]}-landmarks.json":
                raise ValueError(f"{page_id}/{locale}: fingerprint must use its hash path")
            index = load(require_file(public, binding["indexUrl"], binding["indexSha256"]))
            if (index.get("pageId") != page_id
                    or index.get("sourceSha256") != binding["sourceSha256"]
                    or index.get("trackSha256") != binding["trackSha256"]):
                raise ValueError(f"{page_id}/{locale}: fingerprint index differs")
            refs.add(binding["indexUrl"][1:])

    for folder, schema_version in (
        ("english-reference", "sermon-published-english-reference-v1"),
        ("alignment", "sermon-published-alignment-v1"),
    ):
        name = f"{folder}/{page_id}.json"
        sidecar = load(public / name)
        if (sidecar.get("schemaVersion") != schema_version
                or sidecar.get("pageId") != page_id
                or sidecar.get("sourceIdentitySha256") != page["sourceIdentitySha256"]
                or set(sidecar.get("targets", {})) != set(page["targets"])):
            raise ValueError(f"{name}: source or target identity differs")
        if folder == "english-reference" and sidecar.get("reviewState") != "human_approved":
            raise ValueError(f"{name}: English reference is not approved")
        if folder == "english-reference" and sidecar.get("sourceMediaSha256") != page["sourceMediaSha256"]:
            raise ValueError(f"{name}: source media differs")
        for locale, info in sidecar["targets"].items():
            release = releases[locale]
            if info.get("releasePackageJsonSha256") != page["targets"][locale]["releasePackageJsonSha256"]:
                raise ValueError(f"{name}/{locale}: Release binding differs")
            if folder == "english-reference":
                assets = {asset["role"]: asset["sha256"] for asset in release["assets"]}
                if (info.get("contentSha256") != assets["content"]
                        or info.get("captionsSha256") != assets["captions"]):
                    raise ValueError(f"{name}/{locale}: text or captions binding differs")
            elif info.get("audioFingerprint") != page["targets"][locale].get("audioFingerprint"):
                raise ValueError(f"{name}/{locale}: fingerprint binding differs")
        refs.add(name)

    video_name = f"pages/{page_id}/full-video-browser.mp4"
    delivery = page.get("videoDelivery")
    if delivery is None:
        if not (public / video_name).is_file() or digest(public / video_name) != video_sha:
            raise ValueError(f"{page_id}: full sermon video missing")
        refs.add(video_name)
    else:
        validate_video_delivery(page_id, delivery, video_sha)
        for locale in page["targets"]:
            content = load(public / f"content/{page_id}/{locale}.json")
            if content.get("sourceVideoUrl") != delivery["canonicalUrl"]:
                raise ValueError(f"{page_id}/{locale}: canonical video URL differs")
    return refs


def validate_video_delivery(page_id: str, delivery: dict, video_sha: str) -> None:
    """The object URL is immutable; clients keep using the canonical path."""
    if (delivery.get("schemaVersion") != "sermon-video-delivery-v1"
            or delivery.get("canonicalUrl") != f"/pages/{page_id}/full-video-browser.mp4"
            or delivery.get("sha256") != video_sha
            or not isinstance(delivery.get("bytes"), int) or delivery["bytes"] <= 0):
        raise ValueError(f"{page_id}: invalid bucket video binding")
    url = delivery.get("storageUrl", "")
    if (not isinstance(url, str)
            or not url.startswith("https://storage.googleapis.com/ai-for-god-sermon-media-")
            or not url.endswith(f"/weekly/{page_id}/{video_sha}.mp4")
            or "?" in url or "#" in url):
        raise ValueError(f"{page_id}: invalid immutable bucket URL")


def add_video_redirect(config: dict, delivery: dict) -> dict:
    """Return a new Hosting config with one exact video redirect and media CSP."""
    config = json.loads(json.dumps(config))
    hosting = config.get("hosting")
    if not isinstance(hosting, dict) or hosting.get("public") != "public":
        raise ValueError("Expected complete Hosting configuration")
    canonical = delivery["canonicalUrl"]
    redirects = hosting.setdefault("redirects", [])
    if any(rule.get("source") == canonical for rule in redirects):
        raise ValueError("Video redirect already exists")
    redirects.append({"source": canonical, "destination": delivery["storageUrl"], "type": 302})
    matches = [item for rule in hosting.get("headers", [])
               for item in rule.get("headers", [])
               if item.get("key", "").lower() == "content-security-policy"]
    if len(matches) != 1:
        raise ValueError("Expected exactly one site-wide media CSP")
    value = matches[0].get("value", "")
    if "media-src 'self' blob:" in value:
        matches[0]["value"] = value.replace("media-src 'self' blob:",
                                            "media-src 'self' https://storage.googleapis.com blob:")
    elif "media-src 'self' https://storage.googleapis.com blob:" not in value:
        raise ValueError("Unexpected CSP media-src; review before migration")
    return config


def require_video_redirect(config: dict, delivery: dict) -> None:
    matches = [rule for rule in config.get("hosting", {}).get("redirects", [])
               if rule.get("source") == delivery["canonicalUrl"]]
    if matches != [{"source": delivery["canonicalUrl"],
                    "destination": delivery["storageUrl"], "type": 302}]:
        raise ValueError("Historical bucket video redirect is missing or changed")


def stage_files_from_manifest(stage_public: Path, manifest_path: Path,
                              page_id: str) -> tuple[dict[str, Path], dict | None]:
    manifest = load(manifest_path)
    profile = manifest.get("profile")
    bucket = profile == BUCKET_PROFILE
    expected_keys = {"schemaVersion", "profile", "pageId", "files"}
    if bucket:
        expected_keys.add("videoDelivery")
    schema = BUCKET_STAGE_SCHEMA if bucket else STAGE_SCHEMA
    count = BUCKET_STAGE_FILE_COUNT if bucket else STAGE_FILE_COUNT
    if (set(manifest) != expected_keys or manifest.get("schemaVersion") != schema
            or profile not in {PUBLICATION_PROFILE, BUCKET_PROFILE}
            or manifest.get("pageId") != page_id):
        raise ValueError("Production weekly stage requires a supported three-locale file contract")
    entries = manifest.get("files")
    if not isinstance(entries, list) or len(entries) != count:
        raise ValueError(f"Production weekly stage requires exactly {count} assets")
    validate_schema(manifest, f"{schema}.schema.json")
    actual = regular_files(stage_public)
    listed: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise ValueError("Invalid stage manifest entry")
        url = entry["path"]
        path = checked_public_path(stage_public, url)
        name = path.relative_to(stage_public).as_posix()
        if name == CATALOG or name in listed:
            raise ValueError("Catalog must be staged separately; duplicate stage file")
        require_file(stage_public, url, entry["sha256"])
        listed.add(name)
    if set(actual) != listed | {CATALOG}:
        raise ValueError("Stage manifest differs from staged public files")
    return {name: actual[name] for name in listed}, manifest.get("videoDelivery")


def assemble(base_public: Path, stage_public: Path, stage_manifest: Path, out: Path,
             video_file: Path | None = None,
             base_firebase_json: Path | None = None) -> dict:
    if out.exists() or out.is_symlink():
        raise ValueError("Output already exists")
    base_files = regular_files(base_public)
    if CATALOG not in base_files or "weekly.json" not in base_files:
        raise ValueError("Base is not a complete Production snapshot")
    old = load(base_public / CATALOG)
    incoming = load(stage_public / CATALOG)
    validate_schema(old, SCHEMA)
    validate_schema(incoming, SCHEMA)
    if len(incoming["pages"]) != 1 or incoming["defaultPageId"] != incoming["pages"][0]["id"]:
        raise ValueError("Stage catalog must contain one new default page")
    page = incoming["pages"][0]
    if (set(page["targets"]) != SUPPORTED_LOCALES
            or any(target["audioStatus"] != "human_reviewed"
                   or "alignment" not in target["capabilities"]
                   or target.get("audioFingerprint") is None
                   for target in page["targets"].values())):
        raise ValueError("Current Production weekly profile requires zh-Hans/ko/es reviewed audio and alignment")
    if any(prior["id"] == page["id"] for prior in old["pages"]):
        raise ValueError("Existing page ID cannot be overwritten")
    for prior in old["pages"]:
        validate_page(base_public, prior)
    stage_files, delivery = stage_files_from_manifest(stage_public, stage_manifest, page["id"])
    if delivery != page.get("videoDelivery"):
        raise ValueError("Stage video delivery differs from catalog")
    if delivery is not None:
        validate_video_delivery(page["id"], delivery, delivery["sha256"])
        if "/ai-for-god-sermon-media-prod/" not in delivery["storageUrl"]:
            raise ValueError("Production bucket profile requires the Production media bucket")
        if (video_file is None or not video_file.is_file() or video_file.is_symlink()
                or video_file.stat().st_size != delivery["bytes"]
                or digest(video_file) != delivery["sha256"]):
            raise ValueError("Bucket video file missing or changed")
    elif video_file is not None:
        raise ValueError("Legacy Hosting profile must not supply a bucket video file")
    if set(stage_files) & set(base_files):
        raise ValueError("Stage would overwrite an existing Production file")
    required = validate_page(stage_public, page)
    if len(required) != len(stage_files) or required != set(stage_files):
        raise ValueError("Stage must contain exactly the referenced weekly assets, without aliases")
    merged = {
        "schemaVersion": "sermon-multilingual-catalog-v3",
        "generatedAt": incoming["generatedAt"],
        "defaultPageId": page["id"],
        "pages": sorted([page, *old["pages"]],
                        key=lambda item: (item["date"], item["id"]), reverse=True),
    }
    validate_schema(merged, SCHEMA)
    config = None
    if delivery:
        config_path = base_firebase_json or base_public.parent / "firebase.json"
        if not config_path.is_file():
            raise ValueError("Bucket profile requires the complete base firebase.json")
        base_config = load(config_path)
        for prior in old["pages"]:
            if prior.get("videoDelivery"):
                require_video_redirect(base_config, prior["videoDelivery"])
        config = add_video_redirect(base_config, delivery)
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        public = temporary / "public"
        shutil.copytree(base_public, public)
        for name, source in stage_files.items():
            target = public / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if digest(target) != digest(source):
                raise ValueError(f"Stage copy changed: {name}")
        old_catalog_sha = digest(public / CATALOG)
        shutil.copyfile(public / CATALOG, temporary / f"rollback-{CATALOG}")
        (public / CATALOG).write_text(json.dumps(merged, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        if config is not None:
            (temporary / "firebase.json").write_text(
                json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        validate_page(public, page)
        for name, source in base_files.items():
            if name != CATALOG and digest(public / name) != digest(source):
                raise ValueError(f"Base file changed: {name}")
        report = {
            "schemaVersion": "sermon-multilingual-v3-update-candidate-v2",
            "status": "validated_not_deployed",
            "publicationProfile": BUCKET_PROFILE if delivery else PUBLICATION_PROFILE,
            "pageId": page["id"],
            "targetLocales": sorted(page["targets"]),
            "oldCatalogSha256": old_catalog_sha,
            "newCatalogSha256": digest(public / CATALOG),
            "baseFileCount": len(base_files),
            "addedFileCount": len(stage_files),
            "catalogUpdateFileCount": 1,
            "weeklyFileCount": len(stage_files) + 1,
            "bucketObjectCount": 1 if delivery else 0,
            "weeklyFirebaseObjectCount": len(stage_files) + 1 + (1 if delivery else 0),
            "videoDelivery": delivery,
            "firebaseConfigSha256": digest(temporary / "firebase.json") if config else None,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "files": [
                {"path": name, "bytes": path.stat().st_size, "sha256": digest(path)}
                for name, path in sorted(regular_files(public).items())
            ],
        }
        (temporary / "build-report.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        temporary.rename(out)
        return report
    except BaseException:
        shutil.rmtree(temporary)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-public", type=Path, required=True)
    parser.add_argument("--stage-public", type=Path, required=True)
    parser.add_argument("--stage-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--video-file", type=Path,
                        help="Required for the bucket profile; kept outside stage-public")
    parser.add_argument("--base-firebase-json", type=Path,
                        help="Complete Hosting config required for the bucket profile")
    args = parser.parse_args()
    report = assemble(args.base_public, args.stage_public, args.stage_manifest, args.out,
                      args.video_file, args.base_firebase_json)
    print(json.dumps({key: report[key] for key in ("status", "pageId", "targetLocales", "addedFileCount", "weeklyFileCount")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
