#!/usr/bin/env python3
"""Publish an isolated weekly App dry-run page to Firebase Dev.

The page uses the current Dev App runtime and one already reviewed sample week.
It is never inserted into the formal multilingual-v3 catalog. No Layer 1-3
approval or new-week content is inferred from this preview.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

try:
    from scripts import align_firebase_dev_v3 as dev
    from scripts import verify_multilingual_hosting as http
except ImportError:
    import align_firebase_dev_v3 as dev
    import verify_multilingual_hosting as http


SCHEMA = "sermon-firebase-dev-weekly-dry-run-v1"
PREVIEW = "preview_only"
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
LOCALES = ("zh-Hans", "ko", "es")
RUNTIME = ("app.mjs", "catalog.mjs", "published-weeks.mjs", "style.css", "index.html")
ENTRY = '<a id="devPocLink" href="/dev-poc.html">六句实验页</a>'
NOTICE = '<main class="field-main">'
DRY_RUN_LINK = re.compile(r'<a id="devDryRunLink" href="/dry-run/[A-Za-z0-9_-]+/index\.html\?week=[A-Za-z0-9_-]+&amp;contentLang=zh-Hans">[^<]+</a>')
DEV_CSS = "\n.dev-preview-notice{padding:.7rem 1rem;background:#fff4ce;color:#463500;border-radius:.7rem}.dev-preview-notice a{color:inherit;text-decoration:underline}\n"


def json_write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def copy_or_link(source: str, target: str) -> None:
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def replace_text(path: Path, value: str) -> None:
    # copytree may have hard-linked this file to the immutable Dev baseline.
    temporary = path.with_name(path.name + ".new")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def paths(preview_id: str) -> tuple[str, str]:
    if not ID.fullmatch(preview_id):
        raise ValueError("Invalid dry-run ID")
    root = f"dry-run/{preview_id}"
    return f"{root}/index.html", f"{root}/manifest.json"


def feature_parity(base_public: Path, feature_public: Path) -> dict[str, str]:
    """Fail if Dev lacks any JS, HTML or CSS feature in the selected green build."""
    source = {p.name: p for p in feature_public.iterdir() if p.is_file() and p.suffix in {".js", ".mjs"}}
    if not source or not {"app.mjs", "published-weeks.mjs", "catalog.mjs"} <= set(source):
        raise ValueError("Latest feature public snapshot is incomplete")
    for name, path in source.items():
        target = base_public / name
        if not target.is_file() or dev.digest(target) != dev.digest(path):
            raise ValueError(f"Dev App lacks latest feature asset: {name}")
    page = (base_public / "index.html").read_text(encoding="utf-8")
    page = page.replace('  <meta name="robots" content="noindex,nofollow">\n', "", 1)
    lines = [line for line in page.splitlines(keepends=True)
             if 'class="field-help dev-preview-notice" role="note"' not in line
             and '<script type="module" src="/dev-preview-label.mjs"></script>' not in line]
    normalized = "".join(lines)
    if normalized != (feature_public / "index.html").read_text(encoding="utf-8"):
        raise ValueError("Dev App HTML lacks latest feature shell")
    css = (base_public / "style.css").read_text(encoding="utf-8")
    if not css.endswith(DEV_CSS) or css[:-len(DEV_CSS)] != (feature_public / "style.css").read_text(encoding="utf-8"):
        raise ValueError("Dev App CSS lacks latest feature style")
    return {name: dev.digest(path) for name, path in sorted(source.items())}


def baseline_report(base: Path) -> dict:
    schema = dev.load(base / "build-report.json").get("schemaVersion")
    if schema == SCHEMA:
        return candidate_report(base)
    if schema == dev.SCHEMA:
        return dev.candidate_report(base)
    raise ValueError("Unsupported complete Dev v3 baseline")


def checked_backend_run(root: Path) -> tuple[dict, dict[str, Path]]:
    report = dev.load(root / "run-report.json")
    if (report.get("schemaVersion") != "sermon-backend-four-layer-dry-run-v2"
            or report.get("simulationOnly") is not True or report.get("status") != "pass_simulated"
            or report.get("formalApproval") is not False
            or report.get("productionReleaseEligible") is not False
            or report.get("sharedControlLoops") != {
                "layer2": "astra_sol_group_runner",
                "layer3": "pcm16_schedule_and_assembly"}
            or any(report.get("layers", {}).get("layer2", {}).get(locale, {}).get("modelCalls")
                   != 2 * report.get("layers", {}).get("layer2", {}).get(locale, {}).get("groups", -1)
                   for locale in LOCALES)
            or set(report.get("externalCalls", {})) != {"download", "asr", "translation", "tts", "firebase"}
            or any(value != 0 for value in report.get("externalCalls", {}).values())):
        raise ValueError("Complete simulation-only backend run required")
    actual = dev.files(root / "public")
    if not actual or set(actual) != {item["path"] for item in report.get("publicFiles", [])}:
        raise ValueError("Backend preview file set changed")
    for item in report["publicFiles"]:
        if (not item["path"].startswith("flow/")
                or item["path"].startswith("flow/../")
                or item["bytes"] != actual[item["path"]].stat().st_size
                or item["sha256"] != dev.digest(actual[item["path"]])):
            raise ValueError("Backend preview file changed or escaped flow namespace")
    summary = dev.load(root / "public/flow/report.json")
    if (summary.get("simulationOnly") is not True or summary.get("status") != "pass_simulated"
            or summary.get("sourceUrlSha256") != report.get("sourceUrlSha256")
            or summary.get("schemaVersion") != report.get("schemaVersion")
            or summary.get("sharedControlLoops") != report.get("sharedControlLoops")
            or summary.get("formalApproval") is not False):
        raise ValueError("Backend public report differs from simulation")
    if b"DRY RUN" not in (root / "public/flow/index.html").read_bytes():
        raise ValueError("Backend preview label is missing")
    return report, actual


def build(base: Path, feature_public: Path, preview_id: str, out: Path,
          *, backend_run: Path | None = None) -> dict:
    page_path, manifest_path = paths(preview_id)
    if out.exists() or out.is_symlink():
        raise ValueError("Output already exists")
    old = baseline_report(base)
    public_base = base / "public"
    feature_sha = feature_parity(public_base, feature_public)
    catalog = dev.load(public_base / "multilingual-v3.json")
    sample = next((page for page in catalog["pages"] if page["id"] == catalog["defaultPageId"]), None)
    if sample is None or not set(LOCALES) <= set(sample["targets"]):
        raise ValueError("Current reviewed Dev sample lacks three languages")
    sample_id = sample["id"]
    if any(name.startswith(f"dry-run/{preview_id}/") for name in dev.files(public_base)):
        raise ValueError("Dry-run ID already exists; choose a new ID")
    if dev.load(base / "firebase.json")["hosting"].get("site") != dev.SITE:
        raise ValueError("Dry run must use Firebase Dev")
    for name in RUNTIME:
        if not (public_base / name).is_file():
            raise ValueError(f"Missing App runtime: {name}")
    source = (public_base / "index.html").read_text(encoding="utf-8")
    if source.count(ENTRY) != 1 or source.count(NOTICE) != 1:
        raise ValueError("Dev App insertion points changed")
    backend_report, backend_files = checked_backend_run(backend_run) if backend_run else (None, {})
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        public = temporary / "public"
        shutil.copytree(public_base, public, copy_function=copy_or_link)
        link = f'<a id="devDryRunLink" href="/{page_path}?week={sample_id}&amp;contentLang=zh-Hans">每周演练页</a>'
        if "devDryRunLink" in source:
            home, count = DRY_RUN_LINK.subn(link, source)
            if count != 1:
                raise ValueError("Existing Dev dry-run link changed")
        else:
            home = source.replace(ENTRY, ENTRY + " · " + link, 1)
        replace_text(public / "index.html", home)
        label = public / "dev-preview-label.mjs"
        if not label.is_file():
            raise ValueError("Dev preview label is missing")
        label.unlink()
        shutil.copyfile(dev.DEV_LABEL, label)
        sample_title = html.escape(sample["title"])
        backend_link = (f' · <a href="/dry-run/{preview_id}/flow/index.html">'
                        '查看模拟链接 → Layer 1–4 结果</a>') if backend_report else ""
        preview_note = (
            '<p class="field-help dev-preview-notice" id="dryRunStatus" role="status" '
            'data-release-state="preview_only"><strong>DRY RUN · preview_only</strong> · '
            f'这是使用已批准样本「{sample_title}」生成的 App 测试页面；不是下一周正式证道。 '
            + " · ".join(
                f'<a href="/{page_path}?week={sample_id}&amp;contentLang={locale}">{label}</a>'
                for locale, label in (("zh-Hans", "中文"), ("ko", "한국어"), ("es", "Español"))
            ) + backend_link + "</p>"
        )
        preview = home.replace(NOTICE, NOTICE + "\n    " + preview_note, 1)
        page = public / page_path
        page.parent.mkdir(parents=True)
        page.write_text(preview, encoding="utf-8")
        for name, source_file in backend_files.items():
            target = public / f"dry-run/{preview_id}/{name}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file, target)
            if dev.digest(target) != dev.digest(source_file):
                raise ValueError(f"Backend preview copy differs: {name}")
        # This manifest has its own namespace; the formal v3 catalog is unchanged.
        runtime_sha = {name: dev.digest(public / name) for name in RUNTIME}
        manifest = {
            "schemaVersion": SCHEMA, "status": PREVIEW, "previewId": preview_id,
            "samplePageId": sample_id, "sampleCatalogSha256": dev.digest(public / "multilingual-v3.json"),
            "appRuntimeSha256": runtime_sha, "pagePath": "/" + page_path,
            "featureJavascriptSha256": feature_sha,
            "locales": list(LOCALES), "generatedAt": datetime.now(timezone.utc).isoformat(),
            "backendRunReportSha256": dev.digest(backend_run / "run-report.json") if backend_report else None,
            "backendFlowFiles": sorted(backend_files),
        }
        json_write(public / manifest_path, manifest)
        shutil.copyfile(base / "firebase.json", temporary / "firebase.json")
        before = {item["path"]: item for item in old["files"]}
        after = {item["path"]: item for item in dev.inventory(public)}
        expected_added = {page_path, manifest_path} | {
            f"dry-run/{preview_id}/{name}" for name in backend_files}
        if set(after) - set(before) != expected_added:
            raise ValueError("Dry-run file set changed unexpectedly")
        changed = {name for name in before if before[name] != after[name]}
        if "index.html" not in changed or changed - {"index.html", "dev-preview-label.mjs"}:
            raise ValueError("Dry run changed another Dev file")
        if dev.digest(label) != dev.digest(dev.DEV_LABEL):
            raise ValueError("Dev preview label differs from source")
        if any(name.startswith("releases-v2/") or name == "multilingual-v3.json"
               for name in set(after) - set(before)):
            raise ValueError("Dry run must not create formal release assets")
        report = {
            "schemaVersion": SCHEMA, "status": "validated_not_deployed", "siteId": dev.SITE,
            "origin": dev.ORIGIN, "previewId": preview_id, "samplePageId": sample_id,
            "pagePath": "/" + page_path, "manifestPath": "/" + manifest_path,
            "baseBuildReportSha256": dev.digest(base / "build-report.json"),
            "baseFiles": old["files"], "firebaseConfigSha256": dev.digest(temporary / "firebase.json"),
            "runtimeSha256": runtime_sha, "files": list(after[name] for name in sorted(after)),
            "featureJavascriptSha256": feature_sha,
            "backendRunReportSha256": manifest["backendRunReportSha256"],
            "backendFlowFiles": manifest["backendFlowFiles"],
        }
        json_write(temporary / "build-report.json", report)
        temporary.rename(out)
        return report
    except BaseException:
        shutil.rmtree(temporary)
        raise


def candidate_report(candidate: Path) -> dict:
    report = dev.load(candidate / "build-report.json")
    if (report.get("schemaVersion") != SCHEMA or report.get("status") != "validated_not_deployed"
            or report.get("siteId") != dev.SITE or report.get("origin") != dev.ORIGIN
            or report.get("files") != dev.inventory(candidate / "public")
            or report.get("firebaseConfigSha256") != dev.digest(candidate / "firebase.json")
            or dev.load(candidate / "firebase.json")["hosting"].get("site") != dev.SITE):
        raise ValueError("Dev dry-run candidate changed")
    page_path, manifest_path = paths(report["previewId"])
    if report["pagePath"] != "/" + page_path or report["manifestPath"] != "/" + manifest_path:
        raise ValueError("Dry-run paths changed")
    manifest = dev.load(candidate / "public" / manifest_path)
    if (manifest.get("status") != PREVIEW or manifest.get("samplePageId") != report["samplePageId"]
            or manifest.get("sampleCatalogSha256") != dev.digest(candidate / "public/multilingual-v3.json")
            or manifest.get("appRuntimeSha256") != report["runtimeSha256"]
            or manifest.get("featureJavascriptSha256") != report["featureJavascriptSha256"]
            or manifest.get("backendRunReportSha256") != report.get("backendRunReportSha256")
            or manifest.get("backendFlowFiles") != report.get("backendFlowFiles")
            or report["runtimeSha256"] != {name: dev.digest(candidate / "public" / name) for name in RUNTIME}):
        raise ValueError("Preview manifest changed")
    flow_files = report.get("backendFlowFiles", [])
    if (not isinstance(flow_files, list) or len(flow_files) != len(set(flow_files))
            or any(not isinstance(name, str) or not name.startswith("flow/")
                   or ".." in Path(name).parts for name in flow_files)):
        raise ValueError("Backend flow paths changed")
    if flow_files:
        flow = candidate / "public" / f"dry-run/{report['previewId']}/flow/report.json"
        summary = dev.load(flow)
        if (summary.get("status") != "pass_simulated"
                or summary.get("simulationOnly") is not True
                or summary.get("formalApproval") is not False
                or b"flow/index.html" not in (candidate / "public" / page_path).read_bytes()):
            raise ValueError("Backend flow is not a labeled simulation")
    if (report["samplePageId"] != dev.load(candidate / "public/multilingual-v3.json")["defaultPageId"]
            or b'preview_only' not in (candidate / "public" / page_path).read_bytes()):
        raise ValueError("Preview does not use the reviewed sample")
    dev.validate_published_week(candidate / "public")
    dev.old_dev.verify_dev_poc_assets(candidate / "public")
    return report


def preflight(candidate: Path, base: Path) -> dict:
    report = candidate_report(candidate)
    previous = baseline_report(base)
    if (report["baseBuildReportSha256"] != dev.digest(base / "build-report.json")
            or report["baseFiles"] != previous["files"]):
        raise ValueError("Candidate uses a different Dev baseline")
    for item in previous["files"]:
        status, _, size, sha = http.request_file(dev.ORIGIN, "/" + item["path"])
        if (status, size, sha) != (200, item["bytes"], item["sha256"]):
            raise ValueError(f"Live Dev baseline changed: {item['path']}")
    return {"schemaVersion": SCHEMA, "status": "preflight_pass", "origin": dev.ORIGIN,
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "buildReportSha256": dev.digest(candidate / "build-report.json"),
            "baseBuildReportSha256": report["baseBuildReportSha256"],
            "checkedFiles": len(previous["files"])}


def deploy(candidate: Path, receipt: Path) -> dict:
    report = candidate_report(candidate)
    pre = dev.load(receipt)
    age = datetime.now(timezone.utc) - datetime.fromisoformat(pre["checkedAt"])
    if (pre.get("schemaVersion") != SCHEMA or pre.get("status") != "preflight_pass"
            or pre.get("origin") != dev.ORIGIN or not 0 <= age.total_seconds() <= 1800
            or pre.get("buildReportSha256") != dev.digest(candidate / "build-report.json")
            or pre.get("baseBuildReportSha256") != report["baseBuildReportSha256"]
            or pre.get("checkedFiles") != len(report["baseFiles"])):
        raise ValueError("Fresh complete Dev preflight required")
    subprocess.run(["npx", "--yes", "firebase-tools@15.29.0", "deploy", "--only", "hosting",
                    "--project", dev.SITE, "--non-interactive", "--message", "Dev weekly dry run"],
                   cwd=candidate, check=True)
    return {"schemaVersion": SCHEMA, "status": "deployed_http_verification_pending",
            "origin": dev.ORIGIN, "previewId": report["previewId"],
            "deployedAt": datetime.now(timezone.utc).isoformat(),
            "buildReportSha256": dev.digest(candidate / "build-report.json"),
            "preflightSha256": dev.digest(receipt)}


def verify(candidate: Path) -> dict:
    report = candidate_report(candidate)
    for item in report["files"]:
        status, _, size, sha = http.request_file(dev.ORIGIN, "/" + item["path"])
        if (status, size, sha) != (200, item["bytes"], item["sha256"]):
            raise ValueError(f"Dev HTTP mismatch: {item['path']}")
    status, headers, body = http.request_bytes(dev.ORIGIN, report["pagePath"])
    if (status != 200 or "text/html" not in headers.get("content-type", "")
            or b'preview_only' not in body or b'<script type="module" src="/app.mjs"></script>' not in body):
        raise ValueError("Dry-run App page is unavailable")
    for locale in LOCALES:
        if f"contentLang={locale}".encode() not in body:
            raise ValueError(f"Dry-run language link missing: {locale}")
    if report.get("backendFlowFiles"):
        flow_path = f"/dry-run/{report['previewId']}/flow/index.html"
        status, headers, flow = http.request_bytes(dev.ORIGIN, flow_path)
        if (status != 200 or "text/html" not in headers.get("content-type", "")
                or b"DRY RUN" not in flow or b"SIMULATED" not in flow):
            raise ValueError("Backend simulation page is unavailable")
    return {"schemaVersion": SCHEMA, "status": "pass", "origin": dev.ORIGIN,
            "previewId": report["previewId"], "pagePath": report["pagePath"],
            "samplePageId": report["samplePageId"], "checkedFiles": len(report["files"]),
            "verifiedAt": datetime.now(timezone.utc).isoformat(),
            "buildReportSha256": dev.digest(candidate / "build-report.json"),
            "browserAcceptance": "not_run", "deviceAcceptance": "not_run"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    create = commands.add_parser("build")
    create.add_argument("--dev-base-candidate", type=Path, required=True)
    create.add_argument("--feature-public", type=Path, required=True)
    create.add_argument("--preview-id", required=True)
    create.add_argument("--backend-run", type=Path)
    create.add_argument("--out", type=Path, required=True)
    check = commands.add_parser("preflight")
    check.add_argument("--candidate", type=Path, required=True)
    check.add_argument("--dev-base-candidate", type=Path, required=True)
    check.add_argument("--out", type=Path, required=True)
    for action in ("deploy", "verify"):
        command = commands.add_parser(action)
        command.add_argument("--candidate", type=Path, required=True)
        command.add_argument("--out", type=Path, required=True)
        if action == "deploy":
            command.add_argument("--preflight", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "build":
        result = build(args.dev_base_candidate, args.feature_public, args.preview_id, args.out,
                       backend_run=args.backend_run)
    elif args.action == "preflight":
        result = preflight(args.candidate, args.dev_base_candidate)
    elif args.action == "deploy":
        result = deploy(args.candidate, args.preflight)
    else:
        result = verify(args.candidate)
    if args.action != "build":
        if args.out.exists() or args.out.is_symlink():
            raise ValueError("Output already exists")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        json_write(args.out, result)
    print(json.dumps({key: result[key] for key in ("status", "previewId", "pagePath") if key in result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
