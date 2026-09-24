#!/usr/bin/env python3
"""Merge one reviewed Layer 4 page into a complete, immutable Hosting candidate.

The input stage must have been produced by stage_formal_multilingual_dev.py.
This command neither deploys nor changes review/HTTP acceptance state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
CATALOG = "multilingual-v2.json"
READER_FILES = ("app.js", "styles.css", "formal-dev-adapter.mjs", "dev-integrity.mjs")
SHARED_READER_FILES = ("playback-memory.mjs", "brand-icon.png")
ENTRY_LABEL = "多语言证道 · 中文 / 한국어 / Español"


def reader_entry(page: dict) -> str:
    return (
        '<nav class="week-browser" aria-label="多语言证道">'
        f'<a class="text-button" href="/pages/{page["id"]}/{page["defaultTargetLocale"]}">'
        f'{ENTRY_LABEL}</a></nav>'
    )


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected object: {path}")
    return value


def validate_catalog(value: dict) -> None:
    schema = load(ROOT / "schemas/sermon-multilingual-catalog-v2.schema.json")
    problems = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    if problems:
        raise ValueError(f"Invalid multilingual catalog: {problems[0].message}")
    ids = [page["id"] for page in value["pages"]]
    if len(ids) != len(set(ids)) or value["defaultPageId"] not in ids:
        raise ValueError("Duplicate page or missing catalog default")
    for page in value["pages"]:
        if page["defaultTargetLocale"] not in page["targets"]:
            raise ValueError(f"{page['id']}: missing default target")


def regular_files(root: Path) -> dict[str, Path]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"Not a regular directory: {root}")
    files = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Symlink in Hosting input: {path}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path
        elif not path.is_dir():
            raise ValueError(f"Unsupported Hosting input: {path}")
    return files


def checked_public_path(public: Path, name: str) -> Path:
    parts = PurePosixPath(name).parts
    if (not name.startswith("/") or name.startswith("//") or ".." in parts
            or "\\" in name or "%" in name or "?" in name or "#" in name):
        raise ValueError(f"Unsafe public path: {name}")
    path = public.joinpath(*parts[1:])
    if not path.resolve().is_relative_to(public.resolve()):
        raise ValueError(f"Public path escapes root: {name}")
    return path


def verify_catalog_assets(public: Path, catalog: dict) -> set[str]:
    """Recheck every existing and incoming formal reference before copying."""
    referenced = set()
    for page in catalog["pages"]:
        for locale, target in page["targets"].items():
            name = target["releasePackageUrl"]
            if name != f"/releases/{page['id']}/{locale}.json":
                raise ValueError(f"{page['id']}/{locale}: unexpected release URL")
            release_path = checked_public_path(public, name)
            if not release_path.is_file() or digest(release_path) != target["releasePackageJsonSha256"]:
                raise ValueError(f"{name}: release hash differs")
            referenced.add(name[1:])
            release = load(release_path)
            if (release.get("schemaVersion") != "sermon-target-language-release-package-v1"
                    or release.get("pageId") != page["id"]
                    or release.get("targetLocale") != locale
                    or release.get("sourceLocale") != "en"
                    or release.get("contentLocale") != locale
                    or release.get("audioLocale") != locale
                    or release.get("contentStatus") != target["contentStatus"]
                    or release.get("audioStatus") != target["audioStatus"]
                    or release.get("issues")):
                raise ValueError(f"{name}: release identity or review differs")
            roles = set()
            for asset in release.get("assets", []):
                role, asset_name = asset["role"], asset["path"]
                if role in roles or asset_name in referenced:
                    raise ValueError(f"{name}: duplicate asset")
                roles.add(role)
                expected = {
                    "content": f"/content/{page['id']}/{locale}.json",
                    "captions": f"/captions/{page['id']}/{locale}.json",
                }.get(role)
                if role == "audio":
                    if asset_name not in {
                        f"/media/{page['id']}/{locale}.wav",
                        f"/media/{page['id']}/{locale}.mp3",
                    }:
                        raise ValueError(f"{name}: unexpected audio URL")
                elif expected != asset_name:
                    raise ValueError(f"{name}: unsupported asset {role}")
                asset_path = checked_public_path(public, asset_name)
                if not asset_path.is_file() or digest(asset_path) != asset["sha256"]:
                    raise ValueError(f"{asset_name}: asset hash differs")
                referenced.add(asset_name[1:])
            if roles != {"content", "audio", "captions"}:
                raise ValueError(f"{name}: incomplete reviewed release assets")
    return referenced


def assemble(base_public: Path, staged: Path, out: Path,
             *, production_reader: bool = False, promote_home: bool = False) -> dict:
    if promote_home and not production_reader:
        raise ValueError("Home promotion requires the Production reader")
    if out.exists() or out.is_symlink():
        raise ValueError(f"Output already exists: {out}")
    base_files = regular_files(base_public)
    stage_files = regular_files(staged)
    if CATALOG not in stage_files or "stage-receipt.json" not in stage_files:
        raise ValueError("Staged page lacks catalog or stage receipt")
    receipt = load(stage_files["stage-receipt.json"])
    incoming = load(stage_files[CATALOG])
    validate_catalog(incoming)
    if (receipt.get("schemaVersion") != "sermon-formal-dev-stage-receipt-v1"
            or receipt.get("deploymentStatus") != "not_deployed"
            or receipt.get("httpVerification") != "not_run"
            or receipt.get("catalogSha256") != digest(stage_files[CATALOG])
            or len(incoming["pages"]) != 1
            or receipt.get("pageId") != incoming["pages"][0]["id"]
            or receipt.get("sourceIdentitySha256") != incoming["pages"][0]["sourceIdentitySha256"]
            or set(receipt.get("targetLocales", [])) != set(incoming["pages"][0]["targets"])):
        raise ValueError("Staging receipt does not bind the incoming page")
    incoming_refs = verify_catalog_assets(staged, incoming)
    if receipt.get("releasePackageSha256") != {
        locale: target["releasePackageJsonSha256"]
        for locale, target in incoming["pages"][0]["targets"].items()
    }:
        raise ValueError("Staging release package hashes differ")
    if set(stage_files) != incoming_refs | {CATALOG, "stage-receipt.json"}:
        raise ValueError("Staged file list differs from reviewed release references")
    if receipt.get("assetCount") != len(incoming_refs):
        raise ValueError("Staging asset count differs")

    old = load(base_public / CATALOG) if CATALOG in base_files else None
    if old:
        validate_catalog(old)
        verify_catalog_assets(base_public, old)
    incoming_page = incoming["pages"][0]
    if old and any(page["id"] == incoming_page["id"] for page in old["pages"]):
        raise ValueError("Existing page ID cannot be overwritten; create a reviewed revision")
    collisions = incoming_refs & set(base_files)
    if collisions:
        raise ValueError(f"Incoming assets would overwrite prior release: {sorted(collisions)[0]}")
    reader_root = ROOT / "firebase/dev/public"
    reader_files = {}
    feedback_enabled = False
    if production_reader:
        if "weekly.json" not in base_files:
            raise ValueError("Production base must retain the legacy weekly catalog")
        weekly = load(base_files["weekly.json"])
        weeks = weekly.get("weeks")
        if (weekly.get("schemaVersion") != "sermon-weekly-catalog-v1"
                or not isinstance(weeks, list)
                or any(not isinstance(week, dict) or not isinstance(week.get("id"), str)
                       for week in weeks)
                or len({week["id"] for week in weeks}) != len(weeks)):
            raise ValueError("Production base has an invalid legacy weekly catalog")
        legacy_week_ids = [week["id"] for week in weeks]
        legacy_report_path = base_public.parent / "build-report.json"
        if not legacy_report_path.is_file():
            raise ValueError("Production base lacks its immutable build report")
        legacy_report = load(legacy_report_path)
        if (legacy_report.get("schemaVersion") not in {
                "sermon-weekly-build-v1", "sermon-multilingual-hosting-candidate-v1"}
                or type(legacy_report.get("feedbackEnabled")) is not bool):
            raise ValueError("Production base feedback configuration is unknown")
        feedback_enabled = legacy_report["feedbackEnabled"]
        prior_reader = "multilingual-reader.html" in base_files
        if prior_reader and not old:
            raise ValueError("Existing Production reader lacks a catalog")
        if not prior_reader and any(name in base_files for name in READER_FILES):
            raise ValueError("App file collision without an existing Production reader")
        if prior_reader and b'data-reader-mode="production"' not in base_files[
                "multilingual-reader.html"].read_bytes():
            raise ValueError("Existing reader is not this Production overlay")
        prior_promoted = "legacy-reader.html" in base_files
        if prior_promoted and not prior_reader:
            raise ValueError("Legacy reader exists without Production reader")
        if prior_promoted and not promote_home:
            raise ValueError("Cannot demote a promoted Production home implicitly")
        if promote_home and prior_reader and not prior_promoted:
            raise ValueError("Existing overlay needs an explicit home migration")
        for name in READER_FILES:
            if prior_reader != (name in base_files):
                raise ValueError(f"Incomplete existing Production reader: {name}")
            reader_files[name] = reader_root / name
        for name in SHARED_READER_FILES:
            source = reader_root / name
            if name in base_files:
                if digest(base_files[name]) != digest(source):
                    raise ValueError(f"Shared reader asset differs from production: {name}")
            else:
                reader_files[name] = source

    merged = {
        "schemaVersion": "sermon-multilingual-catalog-v2",
        "generatedAt": incoming["generatedAt"],
        "defaultPageId": incoming_page["id"],
        "pages": sorted([incoming_page, *(old["pages"] if old else [])],
                        key=lambda page: (page["date"], page["id"]), reverse=True),
    }
    validate_catalog(merged)
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        public = temporary / "public"
        shutil.copytree(base_public, public)
        for name in incoming_refs:
            target = public / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(stage_files[name], target)
            if digest(target) != digest(stage_files[name]):
                raise ValueError(f"Staged bytes changed during copy: {name}")
        if production_reader:
            for name, source in reader_files.items():
                shutil.copyfile(source, public / name)
            html = (reader_root / "index.html").read_text(encoding="utf-8")
            if '<html lang="zh-Hans" data-theme="dark">' not in html:
                raise ValueError("Reader HTML entry changed")
            html = html.replace(
                '<html lang="zh-Hans" data-theme="dark">',
                '<html lang="zh-Hans" data-theme="dark" data-reader-mode="production">',
                1,
            )
            for old_text, new_text in (
                ("同行 Firebase Dev：多语言证道界面与机器翻译、音频片段测试。", "同行多语言证道：经审核的译文、配音和同步字幕。"),
                ("同行 · 多语言 Dev", "同行 · 多语言证道"),
                ("同行 Dev 首页", "同行首页"),
                ("DEV · MACHINE POC", "多语言证道"),
                ("字幕随当前音频更新 · Dev POC", "字幕随当前音频更新"),
                ("此 POC 未发布现场自动对齐资料", "本页未提供现场自动对齐"),
                ("英文是来源对照；四种目标语言均为开发 POC。", "请选择本页已发布的证道语言。"),
            ):
                html = html.replace(old_text, new_text)
            if promote_home:
                link = ('<nav class="week-browser" aria-label="过往中文证道">'
                        '<a id="legacyReaderLink" class="text-button" href="/legacy-reader.html">'
                        '过往中文证道</a></nav>')
                marker = '<main class="field-main">'
                if html.count(marker) != 1:
                    raise ValueError("Reader homepage insertion point changed")
                html = html.replace(marker, f'{marker}\n    {link}', 1)
                head = "  <link rel=\"stylesheet\" href=\"/styles.css\">"
                if html.count(head) != 1:
                    raise ValueError("Reader head insertion point changed")
                html = html.replace(head, head + '\n  <script src="/legacy-query-router.js"></script>', 1)
                old_legacy = (public / ("legacy-reader.html" if prior_promoted else "index.html")).read_bytes()
                (public / "legacy-reader.html").write_bytes(old_legacy)
                router = (ROOT / "firebase/production-overlay/legacy-query-router.js").read_text(
                    encoding="utf-8")
                if router.count("__LEGACY_WEEK_IDS__") != 1:
                    raise ValueError("Legacy query router template changed")
                (public / "legacy-query-router.js").write_text(
                    router.replace("__LEGACY_WEEK_IDS__", json.dumps(legacy_week_ids)),
                    encoding="utf-8")
                (public / "index.html").write_text(html, encoding="utf-8")
                (public / "multilingual-reader.html").write_text(html, encoding="utf-8")
            else:
                (public / "multilingual-reader.html").write_text(html, encoding="utf-8")
            legacy_html = (public / "index.html").read_text(encoding="utf-8")
            if prior_reader and not promote_home:
                old_default = next(page for page in old["pages"]
                                   if page["id"] == old["defaultPageId"])
                prior_entry = reader_entry(old_default)
                if legacy_html.count(prior_entry) != 1:
                    raise ValueError("Existing Production reader entry differs from catalog")
                legacy_html = legacy_html.replace(prior_entry, "", 1)
            elif not promote_home and re.search(r'aria-label="多语言证道"', legacy_html):
                raise ValueError("Production homepage already has a multilingual entry")
            if not promote_home:
                marker = '<main class="field-main">'
                if legacy_html.count(marker) != 1:
                    raise ValueError("Production homepage insertion point changed")
                entry = f'{marker}\n    {reader_entry(incoming_page)}'
                (public / "index.html").write_text(
                    legacy_html.replace(marker, entry, 1), encoding="utf-8")
        (public / CATALOG).write_text(
            json.dumps(merged, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        verify_catalog_assets(public, merged)
        updated_reader = (set(READER_FILES) | {"multilingual-reader.html", "legacy-query-router.js"}
                          if production_reader else set())
        for name, source in base_files.items():
            if name not in ({CATALOG, "index.html"} | updated_reader if production_reader else {CATALOG}) \
                    and digest(public / name) != digest(source):
                raise ValueError(f"Existing Hosting file changed during copy: {name}")
        modified = sorted(name for name in base_files
                          if name in regular_files(public) and digest(base_files[name]) != digest(public / name))
        report = {
            "schemaVersion": "sermon-multilingual-hosting-candidate-v1",
            "status": "validated_not_deployed",
            "newPageId": incoming_page["id"],
            "oldCatalogSha256": digest(base_files[CATALOG]) if old else None,
            "newCatalogSha256": digest(public / CATALOG),
            "stagingReceiptSha256": digest(stage_files["stage-receipt.json"]),
            "preservedFileCount": len(base_files) - len(modified),
            "addedFileCount": len(incoming_refs),
            "modifiedFiles": modified,
            "baseFiles": [
                {"path": name, "sha256": digest(path), "bytes": path.stat().st_size}
                for name, path in sorted(base_files.items())
            ],
            "productionReader": production_reader,
            "promotedHome": promote_home,
            "feedbackEnabled": feedback_enabled if production_reader else None,
            "legacyHomepageSha256": digest(base_files["index.html"]) if production_reader else None,
            "files": [
                {"path": name, "sha256": digest(path), "bytes": path.stat().st_size}
                for name, path in sorted(regular_files(public).items())
            ],
        }
        if old:
            shutil.copyfile(base_files[CATALOG], temporary / "rollback-multilingual-v2.json")
        if production_reader:
            config = load(ROOT / "firebase/production-overlay/firebase.json")
            if promote_home:
                for rewrite in config["hosting"]["rewrites"]:
                    if rewrite.get("source") == "/pages/**":
                        rewrite["destination"] = "/index.html"
            if feedback_enabled:
                config["hosting"]["rewrites"].insert(0, {
                    "source": "/api/**",
                    "function": {"functionId": "sermon-feedback-api", "region": "us-west1"},
                })
            (temporary / "firebase.json").write_text(
                json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            (temporary / ".firebaserc").write_text(json.dumps({
                "projects": {"default": "ai-for-god-caption-dev"},
                "targets": {"ai-for-god-caption-dev": {
                    "hosting": {"sermonDubbing": ["ai-for-god-sermon-audio"]}}},
            }, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            report["firebaseConfigSha256"] = digest(temporary / "firebase.json")
            report["firebaseTargetsSha256"] = digest(temporary / ".firebaserc")
        (temporary / "build-report.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.rename(temporary, out)
        return report
    except Exception:
        shutil.rmtree(temporary)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-public", type=Path, required=True)
    parser.add_argument("--staged", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--production-reader", action="store_true")
    parser.add_argument("--promote-home", action="store_true")
    args = parser.parse_args()
    report = assemble(args.base_public, args.staged, args.out,
                      production_reader=args.production_reader,
                      promote_home=args.promote_home)
    print(json.dumps({key: report[key] for key in (
        "status", "newPageId", "newCatalogSha256", "preservedFileCount",
        "addedFileCount", "productionReader")}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
