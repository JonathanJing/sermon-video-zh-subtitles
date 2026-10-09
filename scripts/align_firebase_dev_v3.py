#!/usr/bin/env python3
"""Align the isolated Firebase Dev reader with an already published v3 week.

Use the complete last Dev candidate and the complete Production public snapshot.
This only reuses published, reviewed bytes; it never creates review receipts.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from jsonschema import Draft202012Validator, FormatChecker

try:
    from scripts import multilingual_dev_preview as old_dev
    from scripts import verify_multilingual_hosting as http
except ImportError:
    import multilingual_dev_preview as old_dev
    import verify_multilingual_hosting as http


ROOT = Path(__file__).resolve().parents[1]
ORIGIN = old_dev.DEV_ORIGIN
SITE = old_dev.DEV_SITE
RUNTIME_REPLACEMENTS = {
    "app.mjs", "catalog.mjs", "i18n.mjs", "locales-app.mjs",
    "locales-feedback.mjs", "locales-interface.mjs", "usage.mjs",
}
DERIVED_REPLACEMENTS = {"index.html", "style.css"}
DEV_LABEL = ROOT / "firebase/dev-preview/dev-v3-label.mjs"
PRESERVED_DEV = {"engagement.json"}
SCHEMA = "sermon-firebase-dev-v3-alignment-v1"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def files(root: Path) -> dict[str, Path]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"Missing public directory: {root}")
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Symlink in public directory: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path
    return result


def inventory(root: Path) -> list[dict]:
    return [{"path": name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for name, path in sorted(files(root).items())]


def checked(path: Path, sha256: str) -> Path:
    if not path.is_file() or path.is_symlink() or digest(path) != sha256:
        raise ValueError(f"Missing or changed referenced asset: {path}")
    return path


def checked_browser_video(public: Path, page_id: str, page: dict, sha256: str) -> None:
    """Local browser video must match; a bucket-hosted one needs a verified receipt beside public/."""
    local = public / f"pages/{page_id}/full-video-browser.mp4"
    delivery = page.get("videoDelivery") or {}
    if local.exists() or local.is_symlink() or not delivery.get("storageUrl"):
        checked(local, sha256)
        return
    receipt_path = public.parent / "bucket-video-receipt.json"
    receipt = load(receipt_path) if receipt_path.is_file() else {}
    if (delivery.get("sha256") != sha256 or receipt.get("schemaVersion") != "sermon-bucket-video-receipt-v1"
            or receipt.get("status") != "verified" or receipt.get("pageId") != page_id
            or receipt.get("storageUrl") != delivery["storageUrl"] or receipt.get("sha256") != sha256
            or receipt.get("bytes") != delivery.get("bytes")):
        raise ValueError(f"Browser video is neither local nor receipt-verified: {page_id}")


def validate_published_week(public: Path) -> tuple[str, list[str]]:
    catalog = load(public / "multilingual-v3.json")
    schema = load(ROOT / "schemas/sermon-multilingual-catalog-v3.schema.json")
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(catalog)
    page_id = catalog["defaultPageId"]
    page = next((p for p in catalog["pages"] if p["id"] == page_id), None)
    if page is None or set(page["targets"]) != {"zh-Hans", "ko", "es"}:
        raise ValueError("Published week lacks three target languages")
    release_schema = load(ROOT / "schemas/sermon-target-language-release-package-v2.schema.json")
    video_sha = None
    for locale, target in page["targets"].items():
        if target["contentStatus"] != "human_reviewed" or target["audioStatus"] != "human_reviewed":
            raise ValueError(f"Unreviewed target: {locale}")
        release_url = f"/releases-v2/{page_id}/{locale}.json"
        if target["releasePackageUrl"] != release_url:
            raise ValueError(f"Wrong release path: {locale}")
        release = load(checked(public / release_url[1:], target["releasePackageJsonSha256"]))
        Draft202012Validator(release_schema, format_checker=FormatChecker()).validate(release)
        if (release["pageId"] != page_id or release["targetLocale"] != locale
                or release["status"] != "published_http_verified"
                or release["httpVerification"]["status"] != "pass"):
            raise ValueError(f"Unpublished or mismatched release: {locale}")
        roles = {asset["role"]: asset for asset in release["assets"]}
        for role in ("page", "content", "captions", "audio"):
            asset = roles[role]
            checked(public / asset["path"].lstrip("/"), asset["sha256"])
        content = load(public / roles["content"]["path"].lstrip("/"))
        if content["pageId"] != page_id or content["targetLocale"] != locale:
            raise ValueError(f"Content identity mismatch: {locale}")
        if video_sha is None:
            video_sha = content["browserVideoSha256"]
        elif video_sha != content["browserVideoSha256"]:
            raise ValueError("Target languages reference different source videos")
        binding = target.get("audioFingerprint")
        if binding:
            checked(public / binding["indexUrl"].lstrip("/"), binding["indexSha256"])
            if binding["trackSha256"] != roles["audio"]["sha256"]:
                raise ValueError(f"Fingerprint/audio mismatch: {locale}")
    checked_browser_video(public, page_id, page, video_sha)
    for directory in ("english-reference", "alignment"):
        sidecar = load(public / directory / f"{page_id}.json")
        if sidecar["pageId"] != page_id or set(sidecar["targets"]) != set(page["targets"]):
            raise ValueError(f"Sidecar identity mismatch: {directory}")
    if load(public / "english-reference" / f"{page_id}.json")["reviewState"] != "human_approved":
        raise ValueError("English reference is not human approved")
    return page_id, sorted(page["targets"])


def prepare(base: Path, production_public: Path, production_config: Path, out: Path) -> dict:
    if out.exists() or out.is_symlink():
        raise ValueError(f"Output already exists: {out}")
    base_report = old_dev.candidate_report(base)
    base_public = base / "public"
    old_dev.verify_dev_poc_assets(base_public)
    if load(base_public / "engagement.json")["enabled"] is not False:
        raise ValueError("Dev engagement must remain disabled")
    prod_config = load(production_config)
    if prod_config["hosting"].get("site") != "ai-for-god-sermon-audio":
        raise ValueError("Expected complete Production Hosting snapshot")
    page_id, locales = validate_published_week(production_public)
    old, new = files(base_public), files(production_public)
    collisions = {name for name in old.keys() & new.keys() if digest(old[name]) != digest(new[name])}
    if collisions != RUNTIME_REPLACEMENTS | DERIVED_REPLACEMENTS | PRESERVED_DEV:
        raise ValueError(f"Unexpected Dev/Production collisions: {sorted(collisions)}")
    if "multilingual-v3.json" in old or "published-weeks.mjs" in old:
        raise ValueError("Base already has a v3 reader; use a weekly update instead")
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        public = temporary / "public"
        shutil.copytree(base_public, public)
        for name, source in new.items():
            if name in PRESERVED_DEV:
                continue
            target = public / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        html = (public / "index.html").read_text(encoding="utf-8")
        marker = '<main class="field-main">'
        if html.count(marker) != 1:
            raise ValueError("Production reader insertion point changed")
        notice = ('<p class="field-help dev-preview-notice" role="note">'
                  '<span id="devPreviewMessage">DEV 测试站 · 此页用于核验已审核的多语言内容；公开发布请以正式站点为准。</span> '
                  '<a id="devPocLink" href="/dev-poc.html">六句实验页</a></p>')
        html = html.replace(marker, marker + "\n    " + notice, 1)
        html = html.replace('<meta name="viewport"',
                            '<meta name="robots" content="noindex,nofollow">\n  <meta name="viewport"', 1)
        entry = '<script type="module" src="/app.mjs"></script>'
        if html.count(entry) != 1:
            raise ValueError("Production reader entry changed")
        html = html.replace(entry, entry + '\n  <script type="module" src="/dev-preview-label.mjs"></script>', 1)
        (public / "index.html").write_text(html, encoding="utf-8")
        css = (public / "style.css").read_text(encoding="utf-8")
        (public / "style.css").write_text(css + "\n.dev-preview-notice{padding:.7rem 1rem;background:#fff4ce;color:#463500;border-radius:.7rem}.dev-preview-notice a{color:inherit;text-decoration:underline}\n", encoding="utf-8")
        shutil.copyfile(DEV_LABEL, public / "dev-preview-label.mjs")
        config = load(base / "firebase.json")
        if config["hosting"].get("site") != SITE or config["hosting"].get("public") != "public":
            raise ValueError("Base Firebase target changed")
        config["hosting"]["headers"].append({"source": "/multilingual-v3.json", "headers": [
            {"key": "Cache-Control", "value": "no-store"}]})
        if any(rule.get("source") == "/api/**" for rule in config["hosting"].get("rewrites", [])):
            raise ValueError("Dev config must not route to Production API")
        (temporary / "firebase.json").write_text(json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        old_dev.verify_dev_poc_assets(public)
        validate_published_week(public)
        for name, path in old.items():
            if name not in collisions and name != "dev-preview-label.mjs" and digest(public / name) != digest(path):
                raise ValueError(f"Old Dev asset changed: {name}")
        for name in RUNTIME_REPLACEMENTS:
            if digest(public / name) != digest(new[name]):
                raise ValueError(f"Reader runtime changed: {name}")
        if digest(public / "engagement.json") != digest(old["engagement.json"]):
            raise ValueError("Dev engagement changed")
        report = {"schemaVersion": SCHEMA, "status": "validated_not_deployed",
                  "siteId": SITE, "origin": ORIGIN, "pageId": page_id,
                  "locales": locales, "baseBuildReportSha256": digest(base / "build-report.json"),
                  "baseFiles": base_report["files"], "productionCatalogSha256": digest(production_public / "multilingual-v3.json"),
                  "devLabelScriptSha256": digest(DEV_LABEL),
                  "firebaseConfigSha256": digest(temporary / "firebase.json"),
                  "files": inventory(public)}
        (temporary / "build-report.json").write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        temporary.rename(out)
        return report
    except BaseException:
        shutil.rmtree(temporary)
        raise


def prepare_label_update(base: Path, out: Path) -> dict:
    """Change only the Dev label after a v3 candidate has been deployed."""
    if out.exists() or out.is_symlink():
        raise ValueError(f"Output already exists: {out}")
    old = candidate_report(base)
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        shutil.copytree(base / "public", temporary / "public")
        shutil.copyfile(DEV_LABEL, temporary / "public/dev-preview-label.mjs")
        shutil.copyfile(base / "firebase.json", temporary / "firebase.json")
        current = inventory(temporary / "public")
        before = {item["path"]: item for item in old["files"]}
        after = {item["path"]: item for item in current}
        changed = {name for name in before if before[name] != after.get(name)}
        if set(before) != set(after) or changed != {"dev-preview-label.mjs"}:
            raise ValueError(f"Unexpected Dev label update: {sorted(changed)}")
        report = {"schemaVersion": SCHEMA, "status": "validated_not_deployed",
                  "siteId": SITE, "origin": ORIGIN, "pageId": old["pageId"],
                  "locales": old["locales"], "labelUpdateOnly": True,
                  "baseBuildReportSha256": digest(base / "build-report.json"),
                  "baseFiles": old["files"],
                  "productionCatalogSha256": old["productionCatalogSha256"],
                  "devLabelScriptSha256": digest(DEV_LABEL),
                  "firebaseConfigSha256": digest(temporary / "firebase.json"), "files": current}
        (temporary / "build-report.json").write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        temporary.rename(out)
        return report
    except BaseException:
        shutil.rmtree(temporary)
        raise


def candidate_report(candidate: Path) -> dict:
    report = load(candidate / "build-report.json")
    if (report.get("schemaVersion") != SCHEMA or report.get("status") != "validated_not_deployed"
            or report.get("siteId") != SITE or report.get("origin") != ORIGIN
            or not report.get("pageId") or report.get("files") != inventory(candidate / "public")
            or report.get("firebaseConfigSha256") != digest(candidate / "firebase.json")):
        raise ValueError("Dev v3 candidate changed")
    if load(candidate / "firebase.json")["hosting"].get("site") != SITE:
        raise ValueError("Not the Firebase Dev site")
    if report.get("labelUpdateOnly"):
        before = {item["path"]: item for item in report["baseFiles"]}
        after = {item["path"]: item for item in report["files"]}
        if (set(before) != set(after)
                or {name for name in before if before[name] != after[name]} != {"dev-preview-label.mjs"}):
            raise ValueError("Dev label update changed another file")
    page_id, _ = validate_published_week(candidate / "public")
    if page_id != report["pageId"]:
        raise ValueError("Dev v3 default page changed")
    old_dev.verify_dev_poc_assets(candidate / "public")
    return report


def preflight(candidate: Path, base: Path) -> dict:
    report = candidate_report(candidate)
    base_schema = load(base / "build-report.json").get("schemaVersion")
    base_report = candidate_report(base) if base_schema == SCHEMA else old_dev.candidate_report(base)
    if report["baseBuildReportSha256"] != digest(base / "build-report.json") or report["baseFiles"] != base_report["files"]:
        raise ValueError("Candidate uses a different Dev baseline")
    results = []
    for item in base_report["files"]:
        path = "/" + item["path"]
        status, _, size, sha = http.request_file(ORIGIN, path)
        if status != 200 or size != item["bytes"] or sha != item["sha256"]:
            raise ValueError(f"Live Dev baseline changed: {path}")
        results.append({"path": path, "sha256": sha, "bytes": size})
    return {"schemaVersion": "sermon-firebase-dev-v3-preflight-v1", "status": "pass",
            "checkedAt": datetime.now(timezone.utc).isoformat(), "origin": ORIGIN,
            "buildReportSha256": digest(candidate / "build-report.json"),
            "baseBuildReportSha256": digest(base / "build-report.json"),
            "checkedFiles": len(results), "results": results}


def deploy(candidate: Path, receipt: Path) -> dict:
    report = candidate_report(candidate)
    pre = load(receipt)
    age = datetime.now(timezone.utc) - datetime.fromisoformat(pre["checkedAt"])
    if (pre.get("schemaVersion") != "sermon-firebase-dev-v3-preflight-v1"
            or pre.get("status") != "pass" or pre.get("origin") != ORIGIN
            or pre.get("buildReportSha256") != digest(candidate / "build-report.json")
            or pre.get("baseBuildReportSha256") != report["baseBuildReportSha256"]
            or pre.get("checkedFiles") != len(report["baseFiles"])
            or not 0 <= age.total_seconds() <= 1800):
        raise ValueError("Fresh complete Dev baseline preflight required")
    command = ["npx", "--yes", "firebase-tools@15.29.0", "deploy", "--only", "hosting",
               "--project", SITE, "--non-interactive", "--message", "Dev v3 weekly reader alignment"]
    subprocess.run(command, cwd=candidate, check=True)
    return {"schemaVersion": "sermon-firebase-dev-v3-deployment-v1",
            "status": "deployed_http_verification_pending", "origin": ORIGIN,
            "pageId": report["pageId"], "deployedAt": datetime.now(timezone.utc).isoformat(),
            "buildReportSha256": digest(candidate / "build-report.json"),
            "preflightSha256": digest(receipt), "files": len(report["files"])}


def verify(candidate: Path) -> dict:
    report = candidate_report(candidate)
    results = []
    for item in report["files"]:
        name = item["path"]
        status, headers, size, sha = http.request_file(ORIGIN, "/" + name)
        if status != 200 or size != item["bytes"] or sha != item["sha256"]:
            raise ValueError(f"Dev HTTP file mismatch: {name}")
        results.append({"path": name, "sha256": sha, "bytes": size})
    catalog = load(candidate / "public/multilingual-v3.json")
    page = next(p for p in catalog["pages"] if p["id"] == report["pageId"])
    for locale, target in page["targets"].items():
        release = load(candidate / "public" / target["releasePackageUrl"].lstrip("/"))
        audio = next(a for a in release["assets"] if a["role"] == "audio")
        status, headers, first = http.request_bytes(ORIGIN, audio["path"], range_first=True)
        audio_file = candidate / "public" / audio["path"].lstrip("/")
        with audio_file.open("rb") as stream:
            expected_first = stream.read(1)
        if (status != 206 or first != expected_first
                or headers.get("content-range") != f"bytes 0-0/{audio_file.stat().st_size}"):
            raise ValueError(f"Dev audio Range failed: {locale}")
        route = f"/pages/{report['pageId']}/{locale}/index.html"
        status, headers, html = http.request_bytes(ORIGIN, route)
        if (status != 200 or "text/html" not in headers.get("content-type", "")
                or b"cue-1" not in html or len(html) < 10000):
            raise ValueError(f"Dev page content failed: {locale}")
        results.append({"path": route, "pageContent": True, "audioRange206": True})
    return {"schemaVersion": "sermon-firebase-dev-v3-http-v1", "status": "pass",
            "origin": ORIGIN, "pageId": report["pageId"],
            "verifiedAt": datetime.now(timezone.utc).isoformat(), "checkedFiles": len(report["files"]),
            "buildReportSha256": digest(candidate / "build-report.json"),
            "results": results, "browserAcceptance": "not_run", "deviceAcceptance": "not_run"}


def verify_label_update(candidate: Path, base: Path, full_receipt: Path) -> dict:
    """Check a one-file update against the preceding complete HTTP receipt."""
    report, previous = candidate_report(candidate), candidate_report(base)
    if (report.get("labelUpdateOnly") is not True
            or report["baseBuildReportSha256"] != digest(base / "build-report.json")
            or report["baseFiles"] != previous["files"]):
        raise ValueError("Label update is not bound to the verified Dev release")
    full = load(full_receipt)
    by_path = {item["path"]: item for item in full.get("results", []) if "sha256" in item}
    if (full.get("schemaVersion") != "sermon-firebase-dev-v3-http-v1"
            or full.get("status") != "pass"
            or full.get("buildReportSha256") != digest(base / "build-report.json")
            or full.get("checkedFiles") != len(previous["files"])
            or any(by_path.get(item["path"], {}).get("sha256") != item["sha256"]
                   or by_path[item["path"]].get("bytes") != item["bytes"]
                   for item in previous["files"])):
        raise ValueError("Prior complete HTTP receipt is missing or changed")
    public = candidate / "public"
    checks = []
    for path in ("/dev-preview-label.mjs", "/index.html", "/multilingual-v3.json"):
        status, headers, size, sha = http.request_file(ORIGIN, path)
        expected = public / path.lstrip("/")
        if status != 200 or size != expected.stat().st_size or sha != digest(expected):
            raise ValueError(f"Dev label update HTTP mismatch: {path}")
        checks.append({"path": path, "sha256": sha, "bytes": size,
                       "contentType": headers.get("content-type")})
    catalog = load(public / "multilingual-v3.json")
    page = next(p for p in catalog["pages"] if p["id"] == report["pageId"])
    for locale, target in page["targets"].items():
        release = load(public / target["releasePackageUrl"].lstrip("/"))
        audio = next(a for a in release["assets"] if a["role"] == "audio")
        status, headers, first = http.request_bytes(ORIGIN, audio["path"], range_first=True)
        audio_file = public / audio["path"].lstrip("/")
        with audio_file.open("rb") as stream:
            expected_first = stream.read(1)
        if (status != 206 or first != expected_first
                or headers.get("content-range") != f"bytes 0-0/{audio_file.stat().st_size}"):
            raise ValueError(f"Dev audio Range failed after label update: {locale}")
        checks.append({"path": audio["path"], "range206": True})
    return {"schemaVersion": "sermon-firebase-dev-v3-label-http-v1",
            "status": "pass_delta", "origin": ORIGIN, "pageId": report["pageId"],
            "verifiedAt": datetime.now(timezone.utc).isoformat(),
            "buildReportSha256": digest(candidate / "build-report.json"),
            "priorFullReceiptSha256": digest(full_receipt),
            "unchangedFilesInherited": len(previous["files"]) - 1,
            "results": checks, "browserAcceptance": "not_run", "deviceAcceptance": "not_run"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    build = sub.add_parser("build")
    build.add_argument("--dev-base-candidate", type=Path, required=True)
    build.add_argument("--production-public", type=Path, required=True)
    build.add_argument("--production-config", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    label = sub.add_parser("build-label-update")
    label.add_argument("--dev-base-candidate", type=Path, required=True)
    label.add_argument("--out", type=Path, required=True)
    check = sub.add_parser("preflight")
    check.add_argument("--candidate", type=Path, required=True)
    check.add_argument("--dev-base-candidate", type=Path, required=True)
    check.add_argument("--out", type=Path, required=True)
    for action in ("deploy", "verify"):
        cmd = sub.add_parser(action)
        cmd.add_argument("--candidate", type=Path, required=True)
        cmd.add_argument("--out", type=Path, required=True)
        if action == "deploy":
            cmd.add_argument("--preflight", type=Path, required=True)
    delta = sub.add_parser("verify-label-update")
    delta.add_argument("--candidate", type=Path, required=True)
    delta.add_argument("--dev-base-candidate", type=Path, required=True)
    delta.add_argument("--base-http-receipt", type=Path, required=True)
    delta.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "build":
        result = prepare(args.dev_base_candidate, args.production_public, args.production_config, args.out)
    elif args.action == "build-label-update":
        result = prepare_label_update(args.dev_base_candidate, args.out)
    elif args.action == "preflight":
        result = preflight(args.candidate, args.dev_base_candidate)
    elif args.action == "deploy":
        result = deploy(args.candidate, args.preflight)
    elif args.action == "verify-label-update":
        result = verify_label_update(args.candidate, args.dev_base_candidate, args.base_http_receipt)
    else:
        result = verify(args.candidate)
    if args.action not in {"build", "build-label-update"}:
        if args.out.exists():
            raise ValueError(f"Output exists: {args.out}")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "pageId") if k in result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
