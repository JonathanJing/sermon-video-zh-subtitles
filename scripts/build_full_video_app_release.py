#!/usr/bin/env python3
"""Prepare, verify, and seal the full-text / short-spoken-script App release.

This is a Layer 4 adapter for the 2026-09-27 complete video. It copies approved
bytes and never changes either Layer 2 candidate or the reviewed Layer 3 track.
The existing web page and v1/v2 App catalog remain untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

try:
    from scripts import stage_formal_multilingual_dev as stage
    from scripts import build_formal_dev_release_assets as formal_assets
    from scripts.release_asset_io import copy_bound_asset
except ImportError:
    import stage_formal_multilingual_dev as stage
    import build_formal_dev_release_assets as formal_assets
    from release_asset_io import copy_bound_asset


ROOT = Path(__file__).resolve().parents[1]
LOCALES = ("zh-Hans", "ko", "es")
ACCEPT_NOT_RUN = {"status": "not_run", "evidenceSha256": None}
PAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,159}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    return stage.file_sha(path)


def read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")


def validate(value: dict, schema: str) -> None:
    definition = read(ROOT / "schemas" / schema)
    problems = list(Draft202012Validator(definition, format_checker=FormatChecker()).iter_errors(value))
    require(not problems, f"{schema}: {problems[0].message if problems else ''}")


def reviewed_candidate(path: Path, source_sha: str, locale: str) -> tuple[dict, str]:
    candidate = stage.read_package(path, "sermon-target-language-candidate-v2.schema.json")
    require(stage.reviewed_candidate(candidate)
            and candidate["targetLocale"] == locale
            and candidate["englishSourcePackageJsonSha256"] == source_sha,
            f"{locale}: candidate is not approved for this source")
    return candidate, stage.canonical_sha(candidate)


def checked_review(path: Path, candidate: dict, candidate_sha: str, locale: str) -> None:
    receipt = stage.read_package(path, "sermon-target-language-human-review-receipt-v1.schema.json")
    require(receipt["decision"] == "approved"
            and receipt["targetLocale"] == locale
            and receipt["englishSourcePackageJsonSha256"] == candidate["englishSourcePackageJsonSha256"]
            and receipt["candidateJsonSha256"] == candidate_sha
            and receipt["reviewedGroupIds"] == [g["translationGroupId"] for g in candidate["groups"]]
            and [row["translationGroupId"] for row in receipt["groupReviews"]]
                == [g["translationGroupId"] for g in candidate["groups"]]
            and all(row["decision"] == "approved" for row in receipt["groupReviews"]),
            f"{locale}: independent candidate review receipt differs")


def static_page(content: dict, locale: str, page_id: str) -> str:
    esc = html.escape
    outlines = "".join(
        f"<li>{esc(item if isinstance(item, str) else item['title'] + ': ' + item['body'])}</li>"
        for item in content["outline"])
    paragraphs = "".join(
        f"<p id=\"cue-{index}\" data-start=\"{cue['start']}\">{esc(cue['text'])}</p>"
        for index, cue in enumerate(content["cues"], 1))
    return ("<!doctype html>\n"
            f"<html lang=\"{esc(locale)}\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(content['title'])}</title>"
            "<style>body{font:1.12rem/1.75 -apple-system,BlinkMacSystemFont,Arial,sans-serif;"
            "max-width:48rem;margin:auto;padding:1.25rem;color:#1b2430;background:#fff}"
            "h1{line-height:1.25}a{color:#145f9e}main p{margin:0 0 1.1em}"
            "header,aside{border-bottom:1px solid #ccd2d8;padding-bottom:1rem;margin-bottom:1.5rem}"
            "small{color:#52606d}</style></head><body>"
            f"<header><small>{esc(content['series'])} · {esc(content['speaker'])}</small>"
            f"<h1>{esc(content['title'])}</h1><p>{esc(content['scripture'])}</p>"
            "<p>对应完整 31:31 讲道视频；此处为已批准完整阅读稿。</p></header>"
            f"<aside><p>{esc(content['summary'])}</p><ol>{outlines}</ol></aside>"
            f"<main aria-label=\"已批准完整文稿\">{paragraphs}</main>"
            "<footer><small>根据讲道视频制作的已审核译文；配音另使用已审核短口播稿。"
            "来源：Mariners Church 视频；本项目与该教会无隶属关系。</small></footer>"
            "</body></html>\n")


def asset(public: Path, role: str, path: str) -> dict:
    local = public / path.lstrip("/")
    require(local.is_file() and not local.is_symlink(), f"Missing release asset: {path}")
    return {"role": role, "path": path, "sha256": digest(local)}


def assignment_map(values, locales):
    result = {}
    for value in values:
        locale, separator, path = value.partition("=")
        require(separator and locale in locales and locale not in result and path, "Invalid locale assignment")
        result[locale] = Path(path)
    require(set(result) == set(locales), "Input locale assignments differ from release scope")
    return result


def prepare(args: argparse.Namespace) -> dict:
    require(PAGE_ID.fullmatch(args.page_id) is not None, "Unsafe page ID")
    require(not args.out.exists(), "Output already exists")
    source = stage.read_package(args.source, "sermon-english-source-package-v1.schema.json")
    require(source["status"] == "ready_for_translation", "English source is not approved")
    source_sha = stage.canonical_sha(source)
    locales = tuple(getattr(args, "locales", None) or LOCALES)
    require(locales in (LOCALES, ("zh-Hans",)), "Only existing three locales or Chinese are supported")
    if getattr(args, "source_date_label", False):
        require(locales == ("zh-Hans",), "Date-only metadata is Chinese-only")
        metadata = {"schemaVersion": "sermon-source-date-label-v1", "date": args.date,
                    "pageId": args.page_id, "locales": {"zh-Hans": {
                        "series": "", "title": args.date + " 证道", "speaker": "",
                        "scripture": "", "summary": "", "outline": []}}}
    else:
        require(args.metadata_approval and args.metadata_proposal, "Approved metadata is required")
        metadata = formal_assets.checked_metadata(args.metadata_approval, args.metadata_proposal,
                                                  args.page_id, args.date)
    maps = {name: assignment_map(getattr(args, name), locales)
            for name in ("full_candidate", "full_review_receipt", "spoken_candidate",
                         "spoken_review_receipt", "audio_package", "audio_review_receipt",
                         "audio_screening_receipt", "full_content")}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=f".{args.out.name}-", dir=args.out.parent))
    try:
        public = scratch / "public"
        releases = {}
        for locale in locales:
            full, full_sha = reviewed_candidate(maps["full_candidate"][locale], source_sha, locale)
            spoken, spoken_sha = reviewed_candidate(maps["spoken_candidate"][locale], source_sha, locale)
            checked_review(maps["full_review_receipt"][locale], full, full_sha, locale)
            checked_review(maps["spoken_review_receipt"][locale], spoken, spoken_sha, locale)
            require([g["sourceUnitIds"] for g in full["groups"]]
                    == [g["sourceUnitIds"] for g in spoken["groups"]],
                    f"{locale}: full and spoken scripts cover different source units")
            audio_path = maps["audio_package"][locale]
            audio = stage.read_package(audio_path, "sermon-target-language-audio-package-v1.schema.json")
            audio_sha = stage.canonical_sha(audio)
            require(audio["status"] == "human_reviewed"
                    and audio["targetLocale"] == locale
                    and audio["englishSourcePackageJsonSha256"] == source_sha
                    and audio["targetLanguageCandidateJsonSha256"] == spoken_sha
                    and audio["humanReview"]["humanApproval"] is True
                    and audio["humanReview"]["fullPlayback"] == "approved"
                    and not audio["issues"] and audio["track"] and audio["captions"],
                    f"{locale}: reviewed track does not bind approved spoken script")
            audio_receipt_path = maps["audio_review_receipt"][locale]
            receipt_schema = read(audio_receipt_path)["schemaVersion"] + ".schema.json"
            audio_receipt = stage.read_package(audio_receipt_path, receipt_schema)
            screening = stage.read_package(maps["audio_screening_receipt"][locale],
                                           "sermon-target-language-audio-screening-v1.schema.json")
            stage.validate_audio_screening_review(audio, audio_receipt, screening)
            require(audio_receipt["targetLanguageAudioPackageJsonSha256"] == audio_sha
                    and audio_receipt["targetLanguageCandidateJsonSha256"] == spoken_sha
                    and audio_receipt["trackSha256"] == audio["track"]["sha256"]
                    and len(audio["units"]) == len(spoken["groups"])
                    and all(unit["textGroupId"] == group["translationGroupId"]
                            and unit["targetTextSha256"] == hashlib.sha256(
                                group["targetText"].encode("utf-8")).hexdigest()
                            for unit, group in zip(audio["units"], spoken["groups"])),
                    f"{locale}: full-listen approval does not bind track")
            track = stage.local_artifact(audio_path, audio["track"], f"{locale} track")
            captions = stage.local_artifact(audio_path, audio["captions"], f"{locale} captions")
            caption_data = read(captions)
            require(len(caption_data.get("cues", [])) == len(spoken["groups"])
                    and all(cue["textGroupId"] == group["translationGroupId"]
                            and cue["text"] == group["targetText"]
                            for cue, group in zip(caption_data["cues"], spoken["groups"])),
                    f"{locale}: captions differ from approved spoken text")
            require(track.suffix == ".mp3", f"{locale}: App track must be MP3")
            content_source = maps["full_content"][locale]
            content_bytes = content_source.read_bytes()
            content_sha = hashlib.sha256(content_bytes).hexdigest()
            content = json.loads(content_bytes)
            require(content.get("schemaVersion") == "sermon-full-video-text-content-v1"
                    and content.get("status") == "human_reviewed"
                    and content.get("pageId") == args.page_id
                    and content.get("targetLocale") == locale
                    and content.get("englishSourcePackageJsonSha256") == source_sha
                    and content.get("targetLanguageCandidateJsonSha256") == full_sha
                    and len(content.get("cues", [])) == len(full["groups"])
                    and all(cue["textGroupId"] == group["translationGroupId"]
                            and cue["sourceUnitIds"] == group["sourceUnitIds"]
                            and cue["text"] == group["targetText"]
                            for cue, group in zip(content["cues"], full["groups"])),
                    f"{locale}: full reading content differs from approved full text")
            require(all(content.get(field) == metadata["locales"][locale][field]
                        for field in ("series", "title", "speaker", "scripture", "summary", "outline")),
                    f"{locale}: display fields differ from approved page metadata")
            page_path = f"/pages/{args.page_id}/{locale}/index.html"
            content_path = f"/content/{args.page_id}/{locale}.json"
            audio_url = f"/media/{args.page_id}/{locale}.mp3"
            captions_url = f"/captions/{args.page_id}/{locale}.json"
            for source_path, public_path, expected_sha in (
                    (content_source, content_path, content_sha),
                    (track, audio_url, audio["track"]["sha256"]),
                    (captions, captions_url, audio["captions"]["sha256"])):
                copy_bound_asset(source_path, public, public_path, expected_sha)
            page_file = public / page_path.lstrip("/")
            page_file.parent.mkdir(parents=True, exist_ok=True)
            page_file.write_text(static_page(content, locale, args.page_id), encoding="utf-8")
            release = {
                "schemaVersion": "sermon-target-language-release-package-v2",
                "packageId": f"{args.page_id}-{locale}-dual-script",
                "pageId": args.page_id, "sourceLocale": "en", "targetLocale": locale,
                "targetLanguageCandidateJsonSha256": full_sha,
                "spokenTargetLanguageCandidateJsonSha256": spoken_sha,
                "targetLanguageAudioPackageJsonSha256": audio_sha,
                "status": "candidate", "contentStatus": "human_reviewed",
                "audioStatus": "human_reviewed", "interfaceLocale": locale,
                "contentLocale": locale, "audioLocale": locale,
                "assets": [asset(public, role, path) for role, path in (
                    ("page", page_path), ("content", content_path),
                    ("audio", audio_url), ("captions", captions_url))],
                "httpVerification": ACCEPT_NOT_RUN.copy(),
                "deviceAcceptance": ACCEPT_NOT_RUN.copy(),
                "venueAcceptance": ACCEPT_NOT_RUN.copy(), "issues": [],
            }
            validate(release, "sermon-target-language-release-package-v2.schema.json")
            release_path = public / f"releases-v2/{args.page_id}/{locale}.json"
            write(release_path, release)
            releases[locale] = {"releasePath": "/" + str(release_path.relative_to(public)),
                                "releaseSha256": digest(release_path),
                                "fullCandidateSha256": full_sha,
                                "spokenCandidateSha256": spoken_sha,
                                "audioPackageSha256": audio_sha}
        manifest = {"schemaVersion": "sermon-dual-script-app-preparation-v1",
                    "status": "candidate_not_deployed", "pageId": args.page_id,
                    "date": args.date, "englishSourcePackageJsonSha256": source_sha,
                    "metadataApprovalJsonSha256": stage.canonical_sha(metadata),
                    "title": read(maps["full_content"]["zh-Hans"])["title"],
                    "releases": releases,
                    "assets": sorted([asset for locale in locales
                                      for asset in read(public / releases[locale]["releasePath"].lstrip("/"))["assets"]],
                                     key=lambda row: row["path"])}
        write(scratch / "preparation-manifest.json", manifest)
        os.rename(scratch, args.out)
        return manifest
    except Exception:
        shutil.rmtree(scratch)
        raise


def verified_assets(prepared: Path) -> tuple[dict, list[dict]]:
    manifest = read(prepared / "preparation-manifest.json")
    require(manifest.get("schemaVersion") == "sermon-dual-script-app-preparation-v1"
            and manifest.get("status") == "candidate_not_deployed"
            and set(manifest["releases"]) in ({"zh-Hans"}, set(LOCALES)), "Invalid preparation manifest")
    public = prepared / "public"
    assets = manifest["assets"]
    require(len(assets) == 4 * len(manifest["releases"]) and len({a["path"] for a in assets}) == len(assets),
            "Expected twelve distinct page/content/audio/caption assets")
    for row in assets:
        path = public / row["path"].lstrip("/")
        require(path.is_file() and digest(path) == row["sha256"],
                f"Prepared asset changed: {row['path']}")
    for locale, item in manifest["releases"].items():
        path = public / item["releasePath"].lstrip("/")
        require(digest(path) == item["releaseSha256"], f"Candidate release changed: {locale}")
        release = read(path)
        validate(release, "sermon-target-language-release-package-v2.schema.json")
        require(release["status"] == "candidate"
                and release["httpVerification"] == ACCEPT_NOT_RUN
                and len(release["assets"]) == 4
                and {(row["role"], row["path"], row["sha256"]) for row in release["assets"]}
                    == {(row["role"], row["path"], row["sha256"]) for row in assets
                        if row in release["assets"]},
                f"Candidate release gate or assets changed: {locale}")
    return manifest, assets


def verify(args: argparse.Namespace) -> dict:
    _, assets = verified_assets(args.prepared)
    require(args.origin.startswith("https://") and args.origin.rstrip("/") == args.origin
            and "/" not in args.origin.removeprefix("https://"), "Origin must be an HTTPS host")
    require(not args.out.exists(), "Verification receipt already exists")
    observed = []
    for row in assets:
        request = urllib.request.Request(args.origin + row["path"],
                                         headers={"User-Agent": "SermonLayer4Verifier/1"})
        with urllib.request.urlopen(request, timeout=120) as response:
            require(response.status == 200, f"HTTP status differs: {row['path']}")
            result = hashlib.sha256()
            total = 0
            while chunk := response.read(1024 * 1024):
                result.update(chunk)
                total += len(chunk)
            require(result.hexdigest() == row["sha256"], f"HTTP SHA-256 differs: {row['path']}")
            observed.append({"path": row["path"], "sha256": result.hexdigest(),
                             "bytes": total, "status": "pass"})
    receipt = {"schemaVersion": "sermon-app-assets-http-verification-v1",
               "status": "pass", "origin": args.origin,
               "verifiedAt": datetime.now(timezone.utc).isoformat(), "assets": observed}
    write(args.out, receipt)
    return receipt


def seal(args: argparse.Namespace) -> dict:
    manifest, assets = verified_assets(args.prepared)
    locales = tuple(manifest["releases"])
    receipt = read(args.http_verification)
    require(receipt.get("schemaVersion") == "sermon-app-assets-http-verification-v1"
            and receipt.get("status") == "pass"
            and isinstance(receipt.get("origin"), str)
            and receipt["origin"].startswith("https://")
            and {(row["path"], row["sha256"]) for row in receipt.get("assets", [])
                 if row.get("status") == "pass"}
                == {(row["path"], row["sha256"]) for row in assets}
            and len(receipt["assets"]) == len(assets),
            "HTTP receipt does not verify exactly the twelve published assets")
    require(not args.out.exists(), "Sealed output already exists")
    scratch = Path(tempfile.mkdtemp(prefix=f".{args.out.name}-", dir=args.out.parent))
    try:
        public = scratch / "public"
        shutil.copytree(args.prepared / "public", public)
        receipt_sha = digest(args.http_verification)
        targets = {}
        for locale in locales:
            url = manifest["releases"][locale]["releasePath"]
            path = public / url.lstrip("/")
            release = read(path)
            release["status"] = "published_http_verified"
            release["httpVerification"] = {"status": "pass", "evidenceSha256": receipt_sha}
            validate(release, "sermon-target-language-release-package-v2.schema.json")
            write(path, release)
            targets[locale] = {"releasePackageUrl": url,
                               "releasePackageJsonSha256": digest(path),
                               "contentStatus": "human_reviewed",
                               "audioStatus": "human_reviewed",
                               "capabilities": ["text", "captions", "audio"]}
        catalog = {"schemaVersion": "sermon-multilingual-catalog-v3",
                   "generatedAt": datetime.now(timezone.utc).isoformat(),
                   "defaultPageId": manifest["pageId"],
                   "pages": [{"id": manifest["pageId"], "date": manifest["date"],
                              "title": manifest["title"],
                              "sourceLocale": "en",
                              "sourceIdentitySha256": manifest["englishSourcePackageJsonSha256"],
                              "defaultTargetLocale": "zh-Hans", "targets": targets}]}
        validate(catalog, "sermon-multilingual-catalog-v3.schema.json")
        write(public / "multilingual-v3.json", catalog)
        report = {"schemaVersion": "sermon-dual-script-app-seal-v1",
                  "status": "ready_for_catalog_deployment",
                  "pageId": manifest["pageId"], "origin": receipt["origin"],
                  "httpAssetReceiptSha256": receipt_sha,
                  "catalogSha256": digest(public / "multilingual-v3.json"),
                  "releaseSha256s": {locale: targets[locale]["releasePackageJsonSha256"]
                                    for locale in locales},
                  "files": [{"path": "/" + str(path.relative_to(public)), "sha256": digest(path),
                             "bytes": path.stat().st_size}
                            for path in sorted(public.rglob("*")) if path.is_file()]}
        write(scratch / "seal-report.json", report)
        os.rename(scratch, args.out)
        return report
    except Exception:
        shutil.rmtree(scratch)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--source", type=Path, required=True)
    prepare_parser.add_argument("--metadata-approval", type=Path)
    prepare_parser.add_argument("--metadata-proposal", type=Path)
    prepare_parser.add_argument("--locales", nargs="+", choices=LOCALES)
    prepare_parser.add_argument("--source-date-label", action="store_true", help="Use only source date as neutral Chinese display metadata")
    for option in ("full-candidate", "full-review-receipt", "spoken-candidate",
                   "spoken-review-receipt", "audio-package", "audio-review-receipt",
                   "audio-screening-receipt", "full-content"):
        prepare_parser.add_argument("--" + option, action="append", default=[], metavar="LOCALE=PATH")
    prepare_parser.add_argument("--page-id", required=True)
    prepare_parser.add_argument("--date", required=True)
    prepare_parser.add_argument("--out", type=Path, required=True)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--prepared", type=Path, required=True)
    verify_parser.add_argument("--origin", required=True)
    verify_parser.add_argument("--out", type=Path, required=True)
    seal_parser = commands.add_parser("seal")
    seal_parser.add_argument("--prepared", type=Path, required=True)
    seal_parser.add_argument("--http-verification", type=Path, required=True)
    seal_parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = {"prepare": prepare, "verify": verify, "seal": seal}[args.command](args)
    print(json.dumps({"status": result["status"], "pageId": result.get("pageId")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
