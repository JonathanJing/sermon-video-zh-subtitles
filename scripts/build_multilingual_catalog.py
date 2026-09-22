#!/usr/bin/env python3
"""Build the Layer 4 multilingual catalog from immutable, reviewed packages.

This command is deliberately fail closed.  It does not translate, synthesize,
upload, or upgrade review state.  Exact input bytes are hashed and catalogued.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
LOCALE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


class CatalogBuildError(ValueError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    data = path.read_bytes()
    value = json.loads(data)
    if not isinstance(value, dict):
        raise CatalogBuildError(f"{path}: expected a JSON object")
    return data, value


def validate_schema(value: dict[str, Any], schema_name: str, label: str) -> None:
    schema = json.loads((SCHEMAS / schema_name).read_text())
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
            for error in errors[:8]
        )
        raise CatalogBuildError(f"{label}: schema validation failed: {details}")


def parse_assignments(values: list[str], option: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        key, separator, assigned = value.partition("=")
        if not separator or not key or not assigned:
            raise CatalogBuildError(f"{option} requires PAGE=VALUE: {value}")
        if key in result:
            raise CatalogBuildError(f"{option} repeats page {key}")
        result[key] = assigned
    return result


def safe_asset_path(path: str) -> bool:
    parsed = PurePosixPath(path)
    return path.startswith("/") and ".." not in parsed.parts and not path.startswith("//")


def candidate_is_approved(candidate: dict[str, Any]) -> bool:
    group_ids = {group["translationGroupId"] for group in candidate["groups"]}
    human = candidate["humanReview"]
    return (
        candidate["status"] == "human_translation_approved"
        and human["translation"] == "approved"
        and set(human["reviewedGroupIds"]) == group_ids
        and candidate["modelReview"]["status"] == "pass"
        and all(group["semanticReview"]["status"] == "pass" for group in candidate["groups"])
        and all(group["languageReview"]["status"] == "pass" for group in candidate["groups"])
    )


def derive_capabilities(release: dict[str, Any]) -> list[str]:
    roles = {asset["role"] for asset in release["assets"]}
    capabilities: list[str] = []
    if roles & {"content", "page"}:
        capabilities.append("text")
    if "captions" in roles:
        capabilities.append("captions")
    if release["audioStatus"] == "human_reviewed" and "audio" in roles:
        capabilities.append("audio")
    if "download" in roles:
        capabilities.append("download")
    return capabilities


def build(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    page_dates = parse_assignments(args.page_date, "--page-date")
    defaults = parse_assignments(args.default_target, "--default-target")

    candidates: dict[str, dict[str, Any]] = {}
    for path_text in args.candidate:
        path = Path(path_text)
        data, candidate = load_json(path)
        validate_schema(candidate, "sermon-target-language-candidate-v2.schema.json", str(path))
        digest = sha256(data)
        if digest in candidates:
            raise CatalogBuildError(f"duplicate candidate bytes: {path}")
        candidates[digest] = candidate

    audio_packages: dict[str, dict[str, Any]] = {}
    for path_text in args.audio_package:
        path = Path(path_text)
        data, package = load_json(path)
        validate_schema(package, "sermon-target-language-audio-package-v1.schema.json", str(path))
        audio_packages[sha256(data)] = package

    pages: dict[str, dict[str, Any]] = {}
    input_receipts: list[dict[str, str]] = []
    for path_text in args.release:
        path = Path(path_text)
        data, release = load_json(path)
        validate_schema(release, "sermon-target-language-release-package-v1.schema.json", str(path))
        release_hash = sha256(data)
        page_id, locale = release["pageId"], release["targetLocale"]
        candidate_hash = release["targetLanguageCandidateJsonSha256"]
        candidate = candidates.get(candidate_hash)
        if candidate is None:
            raise CatalogBuildError(f"{path}: referenced candidate bytes were not supplied")
        if candidate["targetLocale"] != locale or not candidate_is_approved(candidate):
            raise CatalogBuildError(f"{path}: candidate locale or human approval is invalid")
        if release["status"] != "published_http_verified" or release["httpVerification"]["status"] != "pass":
            raise CatalogBuildError(f"{path}: release is not HTTP-verified")
        if release["contentStatus"] != "human_reviewed":
            raise CatalogBuildError(f"{path}: content is not human reviewed")
        if release["contentLocale"] != locale or release["interfaceLocale"] != locale:
            raise CatalogBuildError(f"{path}: frozen v1 locale fields do not match targetLocale")
        if release["issues"]:
            raise CatalogBuildError(f"{path}: unresolved release issues remain")

        seen_assets: set[tuple[str, str]] = set()
        for asset in release["assets"]:
            identity = (asset["role"], asset["path"])
            if identity in seen_assets or not safe_asset_path(asset["path"]):
                raise CatalogBuildError(f"{path}: duplicate or unsafe asset {identity}")
            seen_assets.add(identity)

        audio_hash = release["targetLanguageAudioPackageJsonSha256"]
        if release["audioStatus"] == "unavailable":
            if audio_hash is not None or release["audioLocale"] is not None or "audio" in {a["role"] for a in release["assets"]}:
                raise CatalogBuildError(f"{path}: unavailable audio must not expose an audio package or asset")
        else:
            audio = audio_packages.get(audio_hash)
            if audio is None:
                raise CatalogBuildError(f"{path}: reviewed audio package bytes were not supplied")
            if not (
                release["audioStatus"] == "human_reviewed"
                and release["audioLocale"] == locale
                and audio["targetLocale"] == locale
                and audio["targetLanguageCandidateJsonSha256"] == candidate_hash
                and audio["status"] == "human_reviewed"
                and audio["humanReview"]["humanApproval"] is True
                and audio["humanReview"]["fullPlayback"] == "approved"
            ):
                raise CatalogBuildError(f"{path}: audio locale, binding, or listening approval is invalid")

        capabilities = derive_capabilities(release)
        if "text" not in capabilities:
            raise CatalogBuildError(f"{path}: no publishable text/page asset")
        page = pages.setdefault(page_id, {
            "id": page_id,
            "date": page_dates.get(page_id),
            "sourceLocale": "en",
            "sourceIdentitySha256": candidate["englishSourcePackageJsonSha256"],
            "defaultTargetLocale": defaults.get(page_id),
            "targets": {},
        })
        if page["sourceIdentitySha256"] != candidate["englishSourcePackageJsonSha256"]:
            raise CatalogBuildError(f"{path}: locale does not share the page source identity")
        if locale in page["targets"]:
            raise CatalogBuildError(f"duplicate release for {page_id} + {locale}")
        page["targets"][locale] = {
            "releasePackageUrl": f"/releases/{page_id}/{locale}.json",
            "releasePackageJsonSha256": release_hash,
            "contentStatus": "human_reviewed",
            "audioStatus": release["audioStatus"],
            "capabilities": capabilities,
        }
        input_receipts.append({"path": str(path), "sha256": release_hash, "pageId": page_id, "targetLocale": locale})

    if not pages:
        raise CatalogBuildError("at least one --release is required")
    for page_id, page in pages.items():
        if not page["date"]:
            raise CatalogBuildError(f"missing --page-date {page_id}=YYYY-MM-DD")
        default = page["defaultTargetLocale"]
        if not default or default not in page["targets"]:
            raise CatalogBuildError(f"default target for {page_id} must name a supplied release")
        page["targets"] = dict(sorted(page["targets"].items()))

    default_page = args.default_page or sorted(pages)[0]
    if default_page not in pages:
        raise CatalogBuildError("--default-page must name a supplied page")
    catalog = {
        "schemaVersion": "sermon-multilingual-catalog-v2",
        "generatedAt": args.generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "defaultPageId": default_page,
        "pages": [pages[key] for key in sorted(pages, reverse=True)],
    }
    validate_schema(catalog, "sermon-multilingual-catalog-v2.schema.json", "catalog")
    encoded = (json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    report = {
        "schemaVersion": "sermon-multilingual-catalog-build-report-v1",
        "catalogJsonSha256": sha256(encoded),
        "defaultPageId": default_page,
        "releaseInputs": sorted(input_receipts, key=lambda value: (value["pageId"], value["targetLocale"])),
        "pageCount": len(pages),
        "targetCount": sum(len(page["targets"]) for page in pages.values()),
    }
    return catalog, report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", action="append", default=[])
    parser.add_argument("--candidate", action="append", default=[])
    parser.add_argument("--audio-package", action="append", default=[])
    parser.add_argument("--page-date", action="append", default=[], metavar="PAGE=DATE")
    parser.add_argument("--default-target", action="append", default=[], metavar="PAGE=LOCALE")
    parser.add_argument("--default-page")
    parser.add_argument("--generated-at")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv or sys.argv[1:])
        catalog, report = build(args)
        catalog_bytes = (json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(catalog_bytes)
        args.report.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        return 0
    except (CatalogBuildError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
