#!/usr/bin/env python3
"""Build, deploy and verify a Production-layout preview on the isolated Dev site.

The inputs are immutable snapshots: a reviewed Production-layout candidate and
the complete public directory from the last Dev deployment. This command never
targets the Production Firebase project or changes an upstream review package.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

try:
    from scripts import assemble_multilingual_hosting as hosting
    from scripts import verify_multilingual_hosting as verifier
except ImportError:
    import assemble_multilingual_hosting as hosting
    import verify_multilingual_hosting as verifier


DEV_PROJECT = "ai-for-god-sermon-audio-dev"
DEV_SITE = "ai-for-god-sermon-audio-dev"
DEV_ORIGIN = f"https://{DEV_SITE}.web.app"
LABEL_SCRIPT = Path(__file__).resolve().parents[1] / "firebase/dev-preview/dev-preview-label.mjs"
DEV_MESSAGE = "DEV 测试站 · 此页用于核验已审核的多语言内容；公开发布请以正式站点为准。"
REQUIRED_LOCALES = frozenset({"zh-Hans", "ko", "es"})
ALIAS = {
    "app.js": "dev-poc-app.js",
    "formal-dev-adapter.mjs": "dev-poc-formal-dev-adapter.mjs",
    "index.html": "dev-poc.html",
    "weekly.json": "dev-poc-weekly.json",
}
COMMAND = ["npx", "--yes", "firebase-tools@15.29.0", "deploy", "--only",
           "hosting", "--project", DEV_PROJECT, "--non-interactive", "--message",
           "Reviewed multilingual Dev production preview"]
CONTENT_TYPES = {
    ".json": {"application/json", "text/json"},
    ".html": {"text/html"},
    ".js": {"text/javascript", "application/javascript"},
    ".mjs": {"text/javascript", "application/javascript"},
    ".css": {"text/css"},
    ".mp3": {"audio/mpeg", "audio/mp3"},
    ".wav": {"audio/wav", "audio/x-wav", "audio/wave"},
    ".pdf": {"application/pdf"},
    ".srt": {"application/x-subrip", "text/plain"},
    ".png": {"image/png"},
}


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def inventory(root: Path) -> list[dict]:
    return [{"path": name, "sha256": hosting.digest(path), "bytes": path.stat().st_size}
            for name, path in sorted(hosting.regular_files(root).items())]


def checked_inventory(root: Path, recorded: object, label: str) -> dict[str, Path]:
    require(isinstance(recorded, list) and bool(recorded), f"{label}: missing inventory")
    files = hosting.regular_files(root)
    expected = {item["path"]: item for item in recorded}
    require(len(expected) == len(recorded) and set(expected) == set(files),
            f"{label}: file inventory differs")
    for name, path in files.items():
        require(path.stat().st_size == expected[name]["bytes"]
                and hosting.digest(path) == expected[name]["sha256"],
                f"{label}: file changed: {name}")
    return files


def verify_dev_poc_assets(public: Path) -> None:
    """Do not silently omit media that the archived Dev POC still advertises."""
    demo = hosting.load(public / "multilingual.json")
    weekly = hosting.load(public / "weekly.json")
    require(demo.get("schemaVersion") == "sermon-multilingual-demo-catalog-v1"
            and demo.get("environment") == "development" and demo.get("poc") is True,
            "Dev POC catalog identity changed")
    require(weekly.get("schemaVersion") == "sermon-weekly-catalog-v1",
            "Dev weekly POC catalog identity changed")

    def check(url: str, expected: str, label: str) -> None:
        file = hosting.checked_public_path(public, url)
        require(file.is_file() and hosting.digest(file) == expected,
                f"Dev POC referenced asset missing or changed: {label}: {url}")

    for page in demo["pages"]:
        for locale, target in page["targets"].items():
            release_url = target["releasePackageUrl"]
            check(release_url, target["releasePackageJsonSha256"], f"release {locale}")
            release = hosting.load(hosting.checked_public_path(public, release_url))
            require(release.get("pageId") == page["id"]
                    and release.get("targetLocale") == locale
                    and release.get("productionEligible") is False,
                    f"Dev POC release identity changed: {locale}")
            for role in ("content", "audio"):
                check(release[f"{role}Url"], release[f"{role}Sha256"],
                      f"{locale}/{role}")
            for variant in release.get("audioVariants", []):
                check(variant["audioUrl"], variant["audioSha256"],
                      f"{locale}/variant")
    for week in weekly["weeks"]:
        for track in week.get("tracks", []):
            check(track["audioUrl"], track["sha256"], f"{week['id']}/track")


def checked_production_config(candidate: Path, report: dict) -> dict:
    config_path = candidate / "firebase.json"
    targets_path = candidate / ".firebaserc"
    require(report.get("firebaseConfigSha256") == hosting.digest(config_path)
            and report.get("firebaseTargetsSha256") == hosting.digest(targets_path),
            "Reviewed Production Firebase configuration changed")
    config = hosting.load(config_path)
    targets = hosting.load(targets_path)
    require(config.get("hosting", {}).get("target") == "sermonDubbing"
            and config["hosting"].get("public") == "public"
            and config["hosting"].get("ignore") == [
                "firebase.json", "**/.*", "**/node_modules/**"]
            and targets.get("projects", {}).get("default") == "ai-for-god-caption-dev"
            and targets.get("targets", {}).get("ai-for-god-caption-dev", {})
            .get("hosting", {}).get("sermonDubbing") == ["ai-for-god-sermon-audio"],
            "Reviewed Production Firebase target changed")
    return config


def prepare(production_candidate: Path, dev_base: Path, out: Path) -> dict:
    require(not out.exists() and not out.is_symlink(), f"Output exists: {out}")
    production_report = hosting.load(production_candidate / "build-report.json")
    require(production_report.get("schemaVersion") == "sermon-multilingual-hosting-candidate-v1"
            and production_report.get("status") == "validated_not_deployed"
            and production_report.get("productionReader") is True
            and production_report.get("promotedHome") is True,
            "Expected reviewed, promoted Production-layout candidate")
    production_config = checked_production_config(production_candidate, production_report)
    prod = checked_inventory(production_candidate / "public", production_report.get("files"),
                             "Production candidate")
    formal = hosting.load(production_candidate / "public/multilingual-v2.json")
    hosting.validate_catalog(formal)
    hosting.verify_catalog_assets(production_candidate / "public", formal)
    require(formal["defaultPageId"] == production_report["newPageId"],
            "Production candidate catalog/default differs")
    dev = hosting.regular_files(dev_base)
    require({"index.html", "app.js", "formal-dev-adapter.mjs", "weekly.json",
             "multilingual-v2.json", "multilingual.json"} <= set(dev),
            "Dev base is not the complete formal-plus-POC deployment")
    verify_dev_poc_assets(dev_base)
    require(hosting.digest(dev["multilingual-v2.json"])
            == hosting.digest(prod["multilingual-v2.json"]),
            "Dev formal catalog differs from reviewed candidate")
    # Existing reviewed audio/content/release bytes must be identical. Only
    # frontend files and the two environment-specific weekly catalogs differ.
    collisions = {name for name in dev if name in prod
                  and hosting.digest(dev[name]) != hosting.digest(prod[name])}
    require(collisions == set(ALIAS), f"Unexpected Dev/Production collisions: {sorted(collisions)}")
    for alias in ALIAS.values():
        require(alias not in prod and alias not in dev, f"Dev POC alias collision: {alias}")
    require('from "./formal-dev-adapter.mjs";' in dev["app.js"].read_text(),
            "Dev POC import changed")
    require('<script type="module" src="/app.js"></script>'
            in dev["index.html"].read_text(), "Dev POC HTML entry changed")
    for name in ("index.html", "multilingual-reader.html"):
        require('data-reader-mode="production"' in prod[name].read_text(),
                f"Reviewed reader mode missing: {name}")
    require('<details id="feedback-options">' in prod["legacy-reader.html"].read_text(),
            "Legacy feedback marker changed")
    engagement = hosting.load(prod["engagement.json"])
    require(engagement.get("schemaVersion") == 1
            and engagement.get("enabled") is True
            and isinstance(engagement.get("appVersion"), str),
            "Production engagement policy changed")

    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        public = temporary / "public"
        shutil.copytree(production_candidate / "public", public)
        for name, path in dev.items():
            if name not in prod:
                target = public / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        for name, alias in ALIAS.items():
            shutil.copyfile(dev[name], public / alias)
        poc_app = (public / ALIAS["app.js"]).read_text()
        require('if (navigate) history.pushState({ locale }, "", release.pageUrl);' in poc_app
                and 'defaultPageId: formal?.defaultPageId || demo.defaultPageId' in poc_app,
                "Dev POC routing changed")
        poc_app = poc_app.replace('from "./formal-dev-adapter.mjs";',
                                  'from "./dev-poc-formal-dev-adapter.mjs";', 1)
        poc_app = poc_app.replace(
            'if (navigate) history.pushState({ locale }, "", release.pageUrl);',
            'if (navigate && location.pathname !== "/dev-poc.html") '
            'history.pushState({ locale }, "", release.pageUrl);', 1)
        poc_app = poc_app.replace(
            'defaultPageId: formal?.defaultPageId || demo.defaultPageId',
            'defaultPageId: location.pathname === "/dev-poc.html" '
            '? demo.defaultPageId : (formal?.defaultPageId || demo.defaultPageId)', 1)
        (public / ALIAS["app.js"]).write_text(poc_app)
        poc_html = (public / ALIAS["index.html"]).read_text()
        (public / ALIAS["index.html"]).write_text(
            poc_html.replace('<script type="module" src="/app.js"></script>',
                             '<script type="module" src="/dev-poc-app.js"></script>', 1))
        notice = ('<p class="field-help" role="note"><span id="devPreviewMessage">'
                  f'{DEV_MESSAGE}'
                  '</span> <a id="devPocLink" href="/dev-poc.html">六句实验页</a></p>')
        for name in ("index.html", "multilingual-reader.html"):
            text = (public / name).read_text()
            marker = '<main class="field-main">'
            require(text.count(marker) == 1, f"Reader notice insertion point changed: {name}")
            text = text.replace(marker, f'{marker}\n    {notice}', 1)
            text = text.replace('<meta name="viewport"',
                                '<meta name="robots" content="noindex,nofollow">\n'
                                '  <meta name="viewport"', 1)
            entry = '<script type="module" src="/app.js"></script>'
            require(text.count(entry) == 1, f"Reader script entry changed: {name}")
            text = text.replace(entry, entry + '\n  <script type="module" '
                                'src="/dev-preview-label.mjs"></script>', 1)
            (public / name).write_text(text)
        shutil.copyfile(LABEL_SCRIPT, public / "dev-preview-label.mjs")
        legacy_html = (public / "legacy-reader.html").read_text()
        (public / "legacy-reader.html").write_text(
            legacy_html.replace('<details id="feedback-options">',
                                '<details id="feedback-options" hidden>', 1))
        engagement["enabled"] = False  # Dev has no matching feedback/usage API.
        (public / "engagement.json").write_text(
            json.dumps(engagement, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        config = production_config
        config["hosting"].pop("target", None)
        config["hosting"]["site"] = DEV_SITE
        config["hosting"]["rewrites"] = [rule for rule in config["hosting"]["rewrites"]
                                         if rule.get("source") != "/api/**"]
        config["hosting"]["headers"].append({"source": "**", "headers": [
            {"key": "X-Robots-Tag", "value": "noindex, nofollow"}]})
        (temporary / "firebase.json").write_text(
            json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        require(config["hosting"]["rewrites"] == [{"source": "/pages/**",
                                                    "destination": "/index.html"}],
                "Dev preview has unexpected rewrites")
        require(all(rule.get("source") != "/api/**"
                    for rule in config["hosting"]["rewrites"]), "Dev API rewrite is unsafe")
        require(hosting.digest(public / "multilingual-v2.json")
                == production_report["newCatalogSha256"], "Formal catalog changed")
        hosting.verify_catalog_assets(public, formal)
        for name, source in dev.items():
            actual = public / (ALIAS[name] if name in ALIAS else name)
            if name in ALIAS and name in {"index.html", "app.js"}:
                continue  # Patched only to point at the preserved Dev POC entry.
            require(hosting.digest(actual) == hosting.digest(source),
                    f"Existing Dev asset changed: {name}")
        report = {
            "schemaVersion": "sermon-multilingual-dev-preview-v1",
            "status": "validated_not_deployed", "projectId": DEV_PROJECT,
            "siteId": DEV_SITE, "origin": DEV_ORIGIN,
            "pageId": formal["defaultPageId"],
            "productionCandidateSha256": hosting.digest(production_candidate / "build-report.json"),
            "devBaseFiles": inventory(dev_base), "files": inventory(public),
            "firebaseConfigSha256": hosting.digest(temporary / "firebase.json"),
            "preservedPocAliases": ALIAS,
        }
        (temporary / "build-report.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        os.rename(temporary, out)
        return report
    except Exception:
        shutil.rmtree(temporary)
        raise


def prepare_update(dev_base_candidate: Path, staged: Path, out: Path) -> dict:
    """Append a reviewed page to the complete currently published Dev snapshot."""
    require(not out.exists() and not out.is_symlink(), f"Output exists: {out}")
    base_report = candidate_report(dev_base_candidate)
    base_public = dev_base_candidate / "public"
    verify_dev_poc_assets(base_public)
    require(set(ALIAS.values()) <= set(hosting.regular_files(base_public)),
            "Current Dev release lacks the preserved POC entry")
    base_config = hosting.load(dev_base_candidate / "firebase.json")
    require(type(base_config["hosting"].get("cleanUrls")) is bool,
            "Current Dev cleanUrls policy is missing")
    incoming = hosting.load(staged / hosting.CATALOG)
    require(len(incoming.get("pages", [])) == 1
            and set(incoming["pages"][0]["targets"]) == REQUIRED_LOCALES
            and all(target["contentStatus"] == "human_reviewed"
                    and target["audioStatus"] == "human_reviewed"
                    for target in incoming["pages"][0]["targets"].values()),
            "Dev release plan requires reviewed text and audio in all three locales")

    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        assembled = temporary / "assembled"
        merge = hosting.assemble(base_public, staged, assembled)
        require(merge["productionReader"] is False
                and merge["oldCatalogSha256"] == hosting.digest(base_public / hosting.CATALOG)
                and merge["baseFiles"] == base_report["files"]
                and merge["modifiedFiles"] == [hosting.CATALOG],
                "New Dev page changed the complete baseline unexpectedly")
        os.rename(assembled / "public", temporary / "public")
        shutil.copyfile(assembled / "build-report.json", temporary / "hosting-merge-report.json")
        shutil.copyfile(assembled / "rollback-multilingual-v2.json",
                        temporary / "rollback-multilingual-v2.json")
        shutil.copyfile(dev_base_candidate / "build-report.json",
                        temporary / "dev-base-build-report.json")
        shutil.rmtree(assembled)
        for name in ("index.html", "multilingual-reader.html"):
            path = temporary / "public" / name
            text = path.read_text(encoding="utf-8")
            text, count = re.subn(r'(<span id="devPreviewMessage">)[^<]*(</span>)',
                                  lambda match: match[1] + DEV_MESSAGE + match[2], text)
            require(count == 1, f"Dev notice marker changed: {name}")
            path.write_text(text, encoding="utf-8")
        shutil.copyfile(LABEL_SCRIPT, temporary / "public/dev-preview-label.mjs")
        shutil.copyfile(dev_base_candidate / "firebase.json", temporary / "firebase.json")
        report = {
            "schemaVersion": "sermon-multilingual-dev-preview-v2",
            "status": "validated_not_deployed", "projectId": DEV_PROJECT,
            "siteId": DEV_SITE, "origin": DEV_ORIGIN,
            "pageId": merge["newPageId"], "preservedPocAliases": ALIAS,
            "baseBuildReportSha256": hosting.digest(dev_base_candidate / "build-report.json"),
            "baseCleanUrls": base_config["hosting"]["cleanUrls"],
            "devBaseFiles": base_report["files"], "files": inventory(temporary / "public"),
            "firebaseConfigSha256": hosting.digest(temporary / "firebase.json"),
            "hostingMergeReportSha256": hosting.digest(temporary / "hosting-merge-report.json"),
            "stagingReceiptSha256": merge["stagingReceiptSha256"],
            "oldCatalogSha256": merge["oldCatalogSha256"],
            "newCatalogSha256": merge["newCatalogSha256"],
        }
        (temporary / "build-report.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        os.rename(temporary, out)
        return report
    except Exception:
        shutil.rmtree(temporary)
        raise


def candidate_report(candidate: Path) -> dict:
    report = hosting.load(candidate / "build-report.json")
    require(report.get("schemaVersion") in {
                "sermon-multilingual-dev-preview-v1", "sermon-multilingual-dev-preview-v2"}
            and report.get("status") == "validated_not_deployed"
            and report.get("projectId") == DEV_PROJECT
            and report.get("siteId") == DEV_SITE
            and report.get("origin") == DEV_ORIGIN
            and report.get("preservedPocAliases") == ALIAS,
            "Not a reviewed Dev preview candidate")
    checked_inventory(candidate / "public", report.get("files"), "Dev candidate")
    config = hosting.load(candidate / "firebase.json")
    require(hosting.digest(candidate / "firebase.json") == report["firebaseConfigSha256"]
            and config.get("hosting", {}).get("site") == DEV_SITE
            and config["hosting"].get("public") == "public"
            and config["hosting"].get("rewrites") == [
                {"source": "/pages/**", "destination": "/index.html"}],
            "Dev Firebase target/config changed")
    if report["schemaVersion"] == "sermon-multilingual-dev-preview-v2":
        merge = hosting.load(candidate / "hosting-merge-report.json")
        base = hosting.load(candidate / "dev-base-build-report.json")
        require(type(report.get("baseCleanUrls")) is bool
                and report["baseCleanUrls"] == config["hosting"].get("cleanUrls")
                and report.get("baseBuildReportSha256")
                == hosting.digest(candidate / "dev-base-build-report.json")
                and base.get("files") == report.get("devBaseFiles")
                and base.get("projectId") == DEV_PROJECT
                and base.get("siteId") == DEV_SITE
                and base.get("firebaseConfigSha256") == report.get("firebaseConfigSha256")
                and base.get("pageId") == hosting.load(
                    candidate / "rollback-multilingual-v2.json").get("defaultPageId")
                and report.get("hostingMergeReportSha256")
                == hosting.digest(candidate / "hosting-merge-report.json")
                and report.get("oldCatalogSha256")
                == hosting.digest(candidate / "rollback-multilingual-v2.json")
                == merge.get("oldCatalogSha256")
                and report.get("newCatalogSha256")
                == hosting.digest(candidate / "public" / hosting.CATALOG)
                == merge.get("newCatalogSha256")
                and report.get("stagingReceiptSha256")
                == merge.get("stagingReceiptSha256")
                and report.get("devBaseFiles") == merge.get("baseFiles")
                and merge.get("modifiedFiles") == [hosting.CATALOG]
                and merge.get("productionReader") is False
                and report.get("pageId") == merge.get("newPageId"),
                "Dev update provenance changed")
    return report


def preflight(candidate: Path) -> dict:
    report = candidate_report(candidate)
    results = []
    for item in report["devBaseFiles"]:
        path = "/" + item["path"]
        # The initial POC base used cleanUrls=true and redirected these files.
        # Later Dev candidates record their baseline's actual policy.
        current_url = ({"/index.html": "/", "/404.html": "/404"}.get(path, path)
                       if report.get("baseCleanUrls", True) else path)
        status, _, size, actual = verifier.request_file(DEV_ORIGIN, current_url)
        require(status == 200 and size == item["bytes"] and actual == item["sha256"],
                f"Dev baseline changed: {path}")
        results.append({"path": path, "requestedPath": current_url,
                        "sha256": actual, "bytes": size})
    return {"schemaVersion": "sermon-multilingual-dev-preview-preflight-v1",
            "status": "pass", "origin": DEV_ORIGIN,
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "buildReportSha256": hosting.digest(candidate / "build-report.json"),
            "checkedFiles": len(results), "results": results}


def deploy(candidate: Path, preflight_path: Path, *, execute: bool) -> dict:
    report = candidate_report(candidate)
    checked = hosting.load(preflight_path)
    require(checked.get("schemaVersion") == "sermon-multilingual-dev-preview-preflight-v1"
            and checked.get("status") == "pass"
            and checked.get("origin") == DEV_ORIGIN
            and checked.get("buildReportSha256") == hosting.digest(candidate / "build-report.json")
            and checked.get("checkedFiles") == len(report["devBaseFiles"]),
            "Dev preflight does not bind the current candidate")
    age = datetime.now(timezone.utc) - datetime.fromisoformat(checked["checkedAt"])
    require(0 <= age.total_seconds() <= 30 * 60,
            "Dev preflight is stale; recheck the live baseline")
    result = {"schemaVersion": "sermon-multilingual-dev-preview-deployment-v1",
              "status": "validated_not_deployed", "projectId": DEV_PROJECT,
              "siteId": DEV_SITE, "origin": DEV_ORIGIN,
              "pageId": report["pageId"], "files": len(report["files"]),
              "buildReportSha256": hosting.digest(candidate / "build-report.json"),
              "preflightSha256": hosting.digest(preflight_path), "command": COMMAND}
    if execute:
        subprocess.run(COMMAND, cwd=candidate, check=True)
        result["status"] = "deployed_http_verification_pending"
        result["deployedAt"] = datetime.now(timezone.utc).isoformat()
    return result


def verify(candidate: Path) -> dict:
    report = candidate_report(candidate)
    results = []
    for item in report["files"]:
        path = "/" + item["path"]
        status, headers, size, actual = verifier.request_file(DEV_ORIGIN, path)
        require(status == 200 and size == item["bytes"] and actual == item["sha256"],
                f"Dev file missing or changed after deployment: {path}")
        mime = headers.get("content-type", "").split(";")[0].lower()
        expected_mime = CONTENT_TYPES.get(Path(path).suffix.lower())
        if expected_mime is not None and mime not in expected_mime:
            raise ValueError(f"Unexpected Dev Content-Type for {path}: {mime}")
        if path == "/multilingual-v2.json":
            require("no-store" in headers.get("cache-control", ""),
                    "Dev formal catalog must be no-store")
        results.append({"path": path, "sha256": actual, "bytes": size,
                        "contentType": mime})
    catalog = hosting.load(candidate / "public/multilingual-v2.json")
    page = next(item for item in catalog["pages"] if item["id"] == report["pageId"])
    for locale, target in page["targets"].items():
        release = hosting.load(candidate / "public" / target["releasePackageUrl"].lstrip("/"))
        audio = next(asset for asset in release["assets"] if asset["role"] == "audio")
        status, headers, first = verifier.request_bytes(
            DEV_ORIGIN, audio["path"], range_first=True)
        audio_path = candidate / "public" / audio["path"].lstrip("/")
        with audio_path.open("rb") as stream:
            expected_first = stream.read(1)
        require(status == 206 and first == expected_first
                and headers.get("content-range") == f"bytes 0-0/{audio_path.stat().st_size}",
                f"Dev audio Range failed: {locale}")
        path = f"/pages/{page['id']}/{locale}"
        route_status, route_headers, html = verifier.request_bytes(DEV_ORIGIN, path)
        require(route_status == 200 and "text/html" in route_headers.get("content-type", "")
                and b"<html" in html[:4096].lower(), f"Dev deep link failed: {path}")
        results.append({"path": audio["path"], "range206": True})
        results.append({"path": path, "status": route_status})
    return {"schemaVersion": "sermon-multilingual-dev-preview-http-v1",
            "status": "pass", "origin": DEV_ORIGIN, "pageId": page["id"],
            "verifiedAt": datetime.now(timezone.utc).isoformat(),
            "buildReportSha256": hosting.digest(candidate / "build-report.json"),
            "checkedFiles": len(report["files"]), "results": results,
            "browserAcceptance": "not_run", "deviceAcceptance": "not_run",
            "venueAcceptance": "not_run"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    build = sub.add_parser("build")
    build.add_argument("--production-candidate", type=Path, required=True)
    build.add_argument("--dev-base-public", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    update = sub.add_parser("build-update")
    update.add_argument("--dev-base-candidate", type=Path, required=True)
    update.add_argument("--staged", type=Path, required=True)
    update.add_argument("--out", type=Path, required=True)
    for action in ("preflight", "verify"):
        command = sub.add_parser(action)
        command.add_argument("--candidate", type=Path, required=True)
        command.add_argument("--out", type=Path, required=True)
    publish = sub.add_parser("deploy")
    publish.add_argument("--candidate", type=Path, required=True)
    publish.add_argument("--preflight", type=Path, required=True)
    publish.add_argument("--out", type=Path, required=True)
    publish.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.action == "build":
        result = prepare(args.production_candidate, args.dev_base_public, args.out)
    elif args.action == "build-update":
        result = prepare_update(args.dev_base_candidate, args.staged, args.out)
    else:
        require(not args.out.exists() and not args.out.is_symlink(),
                f"Output exists: {args.out}")
        if args.action == "preflight":
            result = preflight(args.candidate)
        elif args.action == "verify":
            result = verify(args.candidate)
        else:
            result = deploy(args.candidate, args.preflight, execute=args.execute)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("status", "pageId") if key in result},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
