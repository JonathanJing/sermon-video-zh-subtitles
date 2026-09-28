#!/usr/bin/env python3
"""Add approved English comparison text without rewriting published releases.

English is taken verbatim from the frozen, human-approved source anchors. Full
translation groups define the mapping; spoken captions must use those same IDs.
Only public identities and comparison text are emitted, never local evidence paths.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical_sha(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def read_json(path, sha256=None, json_sha256=None):
    data = Path(path).read_bytes()
    if sha256 is not None:
        require(hashlib.sha256(data).hexdigest() == sha256, f"Byte hash mismatch: {path}")
    value = json.loads(data)
    if json_sha256 is not None:
        require(canonical_sha(value) == json_sha256, f"JSON hash mismatch: {path}")
    return value


def read_evidence(ref):
    require(ref.get("sha256") and ref.get("jsonSha256"), "Missing evidence hashes")
    return read_json(ref["path"], ref["sha256"], ref["jsonSha256"])


def public_path(root, url):
    require(isinstance(url, str) and re.fullmatch(r"/[A-Za-z0-9_./-]+", url), "Invalid asset URL")
    require(".." not in PurePosixPath(url).parts and not url.startswith("//"), "Unsafe asset URL")
    path = (root / url.lstrip("/")).resolve()
    require(path.is_relative_to(root), "Asset escapes public directory")
    return path


def build_reference(public, page_id, source_path):
    public = Path(public).resolve()
    require(re.fullmatch(r"[A-Za-z0-9_-]+", page_id), "Invalid page ID")
    source = read_json(source_path)
    require(source.get("schemaVersion") == "sermon-english-source-package-v1", "Unsupported source package")
    require(source.get("status") == "ready_for_translation" and source.get("translationEligible") is True,
            "English source is not approved for translation")
    review = source.get("review", {})
    require(review.get("humanApproval") is True, "English source needs human approval")
    checks = ("sourceIdentity", "transcriptCompleteness", "wordAlignment", "sentenceAndPauseBoundaries")
    require(all(review.get("checks", {}).get(k) == "approved" for k in checks), "Incomplete source approval")
    window = source["source"]["approvedWindow"]
    require(window.get("humanApproval") is True and window.get("status") == "approved", "Unapproved source window")
    read_evidence(window["evidence"])
    read_evidence(source["transcript"]["artifact"])
    anchors = read_evidence(source["anchors"]["artifact"])
    receipt = read_evidence(review["evidence"])
    require(receipt.get("humanApproval") is True and all(receipt.get("checks", {}).get(k) == "approved" for k in checks),
            "Incomplete approval receipt")
    require(receipt.get("anchorManifestJsonSha256") == source["anchors"]["artifact"]["jsonSha256"],
            "Approval receipt does not cover these anchors")
    require(receipt.get("alignedSegmentsSha256") == source["transcript"]["artifact"]["sha256"]
            == anchors.get("input", {}).get("mfaSegmentsSha256"), "Transcript binding mismatch")
    units = anchors["sourceUnits"]
    unit_ids = [unit["sourceUnitId"] for unit in units]
    require(unit_ids and len(set(unit_ids)) == len(unit_ids), "Duplicate or absent source units")
    require(len(unit_ids) == source["anchors"]["sourceUnitCount"], "Source unit count mismatch")
    require(review.get("reviewedSourceUnitIds") == unit_ids, "Source review does not cover all ordered units")
    require(receipt.get("reviewedSourceUnitIds") == unit_ids, "Receipt does not cover all ordered units")
    english = {unit["sourceUnitId"]: unit["english"] for unit in units}
    require(all(isinstance(text, str) and text.strip() for text in english.values()), "Empty English unit")
    source_sha = canonical_sha(source)
    media_sha = source["source"]["media"]["sha256"]
    catalog = read_json(public / "multilingual-v3.json")
    require(catalog.get("schemaVersion") == "sermon-multilingual-catalog-v3", "Unsupported catalog")
    pages = [page for page in catalog["pages"] if page["id"] == page_id]
    require(len(pages) == 1, "Page must occur exactly once in catalog")
    page = pages[0]
    require(page["sourceIdentitySha256"] == source_sha, "Catalog source identity mismatch")
    targets = {}
    for locale, target in page["targets"].items():
        # The published catalog binds the served JSON bytes (despite the field
        # name); the English source package identity uses canonical JSON above.
        release = read_json(public_path(public, target["releasePackageUrl"]),
                            sha256=target["releasePackageJsonSha256"])
        require(release.get("status") == "published_http_verified" and release.get("contentStatus") == "human_reviewed",
                f"Unpublished or unreviewed release: {locale}")
        require(release.get("pageId") == page_id and release.get("targetLocale") == locale
                and release.get("contentLocale") == locale, f"Release identity mismatch: {locale}")
        assets = {}
        for role in ("content", "captions"):
            matches = [asset for asset in release["assets"] if asset["role"] == role]
            require(len(matches) == 1, f"Expected one {role} asset: {locale}")
            asset = matches[0]
            assets[role] = (read_json(public_path(public, asset["path"]), sha256=asset["sha256"]), asset["sha256"])
        content, content_sha = assets["content"]
        captions, captions_sha = assets["captions"]
        require(content.get("pageId") == page_id and content.get("targetLocale") == locale
                and content.get("status") == "human_reviewed", f"Content identity/status mismatch: {locale}")
        require(content.get("englishSourcePackageJsonSha256") == source_sha
                and content.get("sourceMediaSha256") == media_sha, f"Content source mismatch: {locale}")
        require(content.get("targetLanguageCandidateJsonSha256") == release.get("targetLanguageCandidateJsonSha256"),
                f"Content candidate mismatch: {locale}")
        groups = content["cues"]
        group_ids = [group["textGroupId"] for group in groups]
        require(len(set(group_ids)) == len(group_ids), f"Duplicate translation groups: {locale}")
        require([cue["textGroupId"] for cue in captions["cues"]] == group_ids,
                f"Spoken captions do not match translation group order: {locale}")
        mapped_ids = [unit_id for group in groups for unit_id in group["sourceUnitIds"]]
        require(mapped_ids == unit_ids, f"Source mapping must cover every unit once, in order: {locale}")
        require(all(group["sourceUnitIds"] for group in groups), f"Empty source mapping: {locale}")
        blocks = [{"textGroupId": group["textGroupId"], "sourceUnitIds": group["sourceUnitIds"],
                   "english": " ".join(english[unit_id] for unit_id in group["sourceUnitIds"])} for group in groups]
        targets[locale] = {"contentSha256": content_sha, "captionsSha256": captions_sha,
                           "releasePackageJsonSha256": target["releasePackageJsonSha256"], "blocks": blocks}
    require(targets, "Page has no published targets")
    return {"schemaVersion": "sermon-published-english-reference-v1", "pageId": page_id,
            "sourceIdentitySha256": source_sha, "sourceMediaSha256": media_sha,
            "reviewState": "human_approved", "targets": targets}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    reference = build_reference(args.public, args.page_id, args.source)
    destination = args.public / "english-reference" / f"{args.page_id}.json"
    require(not destination.exists(), "English reference already exists; use a new candidate directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(reference, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(destination), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                      "groups": {locale: len(target["blocks"]) for locale, target in reference["targets"].items()}},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
