#!/usr/bin/env python3
"""Update only the App shell of the isolated Firebase Dev site.

The shell is the feature JavaScript/MJS set plus the shell static files that the
Production UI plan marks as changed. index.html and style.css are derived from the
feature shell with the same Dev-only additions used by the v3 alignment (noindex,
DEV notice, dev label script, dev notice CSS). Dev data, Dev config, Dev-only
modules and all pages stay byte-identical. The output is an alignment-v1 candidate,
so the existing v3 deploy/verify and the dry-run builder accept it.
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

try:
    from scripts import align_firebase_dev_v3 as dev
    from scripts import firebase_dev_weekly_dry_run as dry
    from scripts import verify_multilingual_hosting as http
except ImportError:
    import align_firebase_dev_v3 as dev
    import firebase_dev_weekly_dry_run as dry
    import verify_multilingual_hosting as http


ROOT = Path(__file__).resolve().parents[1]
SHELL_SUFFIXES = {".js", ".mjs", ".css", ".svg", ".png", ".html"}
DERIVED = {"index.html", "style.css"}
PRESERVED = {"engagement.json", "multilingual-v3.json", "firebase.json"}
PREFLIGHT_SCHEMA = "sermon-firebase-dev-app-shell-preflight-v1"
DEPLOYMENT_SCHEMA = "sermon-firebase-dev-app-shell-deployment-v1"
MARKER = '<main class="field-main">'
NOTICE = ('<p class="field-help dev-preview-notice" role="note">'
          '<span id="devPreviewMessage">DEV 测试站 · 此页用于核验已审核的多语言内容；公开发布请以正式站点为准。</span> '
          '<a id="devPocLink" href="/dev-poc.html">六句实验页</a></p>')
ENTRY = '<script type="module" src="/app.mjs"></script>'
LABEL_SCRIPT = '<script type="module" src="/dev-preview-label.mjs"></script>'
REFERENCE = re.compile(r"""(?:from\s+|import\s*\(\s*|src=|href=)["']([^"']+)["']""")


def read_plan(feature_public: Path, plan_path: Path | None) -> dict:
    plan = dev.load(plan_path or feature_public.parent / "ui-update-plan.json")
    if plan.get("environment") != "production" or plan.get("status") != "prepared_not_deployed":
        raise ValueError("Feature must be a prepared Production UI plan")
    expected_target = {"project": "ai-for-god-caption-dev", "site": "ai-for-god-sermon-audio"}
    if any(plan.get(key) != value for key, value in expected_target.items()):
        raise ValueError("Production UI plan target changed")
    commit = plan.get("sourceCommit", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("UI plan source commit missing")
    source_files = plan.get("sourceFiles") or {}
    feature = dev.files(feature_public)
    replaced, _ = shell_names(feature, plan)
    for name in replaced | DERIVED:
        if name not in source_files or dev.digest(feature[name]) != source_files[name]:
            raise ValueError(f"Feature differs from UI plan: {name}")
        # The producer binds these files under web/ to the recorded Git commit.
        result = subprocess.run(["git", "show", f"{commit}:experiments/sermon-dubbing-poc/web/{name}"], cwd=ROOT,
                                capture_output=True)
        if result.returncode or result.stdout != feature[name].read_bytes():
            raise ValueError(f"Feature differs from recorded source commit: {name}")
    return plan


def shell_names(feature: dict[str, Path], plan: dict) -> tuple[set[str], set[str]]:
    changed = {path.lstrip("/") for path in plan["changedPaths"]}
    if not changed <= set(feature):
        raise ValueError(f"Plan names files missing from feature: {sorted(changed - set(feature))}")
    code = {name for name in feature if name.endswith((".js", ".mjs"))}
    static = {name for name in changed if Path(name).suffix in SHELL_SUFFIXES - {".js", ".mjs", ".html"}}
    replaced = (code | static) - DERIVED - PRESERVED
    return replaced, changed & DERIVED


def check_references(public: Path, names: set[str]) -> None:
    """Every local src/href/import in a shell file must resolve inside the new tree."""
    for name in sorted(names):
        path = public / name
        if path.suffix not in {".js", ".mjs", ".html"}:
            continue
        for match in REFERENCE.finditer(path.read_text(encoding="utf-8")):
            target = match.group(1).split("#", 1)[0].split("?", 1)[0]
            if (not target or target.endswith("/") or "${" in target
                    or target.startswith(("http:", "https:", "data:", "//"))):
                continue
            if not target.startswith((".", "/")):
                continue
            resolved = (public / target.lstrip("/")) if target.startswith("/") else (path.parent / target)
            if not resolved.resolve().is_file() or public.resolve() not in resolved.resolve().parents:
                raise ValueError(f"Unresolved local reference in {name}: {target}")


def prepare(base: Path, feature_public: Path, plan_path: Path | None, out: Path) -> dict:
    if out.exists() or out.is_symlink():
        raise ValueError(f"Output already exists: {out}")
    plan = read_plan(feature_public, plan_path)
    base_report = dry.baseline_report(base)
    base_public = base / "public"
    if dev.load(base_public / "engagement.json")["enabled"] is not False:
        raise ValueError("Dev engagement must remain disabled")
    config = dev.load(base / "firebase.json")
    if config["hosting"].get("site") != dev.SITE or config["hosting"].get("public") != "public":
        raise ValueError("Base Firebase target changed")
    if any(rule.get("source") == "/api/**" for rule in config["hosting"].get("rewrites", [])):
        raise ValueError("Dev config must not route to Production API")
    if not (base_public / "dev-preview-label.mjs").is_file():
        raise ValueError("Dev label is missing")
    # The live Dev label is preserved byte-for-byte; it matches neither reviewed label source.
    label_sha = dev.digest(base_public / "dev-preview-label.mjs")
    feature = dev.files(feature_public)
    replaced, derived = shell_names(feature, plan)
    def planned_bytes(name):
        data = feature[name].read_bytes()
        if hashlib.sha256(data).hexdigest() != plan["sourceFiles"].get(name):
            raise ValueError(f"Feature changed during staging: {name}")
        return data
    if not replaced:
        raise ValueError("No app-shell files selected")
    base_names = set(dev.files(base_public))
    if PRESERVED & replaced or "dev-preview-label.mjs" in replaced:
        raise ValueError("Update would touch a preserved Dev file")
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        public = temporary / "public"
        shutil.copytree(base_public, public)
        if (base / "bucket-video-receipt.json").is_file():
            # Receipt sits beside public/, so it is validated but never uploaded.
            shutil.copyfile(base / "bucket-video-receipt.json", temporary / "bucket-video-receipt.json")
        for name in sorted(replaced):
            target = public / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(planned_bytes(name))
        page = planned_bytes("index.html").decode("utf-8")
        if page.count(MARKER) != 1 or page.count(ENTRY) != 1 or page.count('<meta name="viewport"') != 1:
            raise ValueError("Feature shell insertion points changed")
        page = page.replace(MARKER, MARKER + "\n    " + NOTICE, 1)
        page = page.replace('<meta name="viewport"', '<meta name="robots" content="noindex,nofollow">\n  <meta name="viewport"', 1)
        page = page.replace(ENTRY, ENTRY + "\n  " + LABEL_SCRIPT, 1)
        (public / "index.html").write_text(page, encoding="utf-8")
        css = planned_bytes("style.css").decode("utf-8")
        (public / "style.css").write_text(css + dry.DEV_CSS, encoding="utf-8")
        check_references(public, replaced | derived)
        page_id, locales = dev.validate_published_week(public)
        if page_id != dev.validate_published_week(base_public)[0]:
            raise ValueError("Default Dev sample changed")
        dev.old_dev.verify_dev_poc_assets(public)
        dry.feature_parity(public, feature_public)
        before = {item["path"]: item for item in base_report["files"]}
        after = {item["path"]: item for item in dev.inventory(public)}
        if set(before) - set(after):
            raise ValueError(f"Dev files removed: {sorted(set(before) - set(after))}")
        added = set(after) - set(before)
        if added - replaced:
            raise ValueError(f"Unexpected new files: {sorted(added - replaced)}")
        changed = {name for name in before if before[name] != after[name]}
        if changed - replaced - DERIVED:
            raise ValueError(f"Dev file changed outside the shell: {sorted(changed - replaced - DERIVED)}")
        for name in PRESERVED | {"dev-preview-label.mjs"}:
            if name in before and before[name] != after[name]:
                raise ValueError(f"Preserved Dev file changed: {name}")
        shutil.copyfile(base / "firebase.json", temporary / "firebase.json")
        report = {"schemaVersion": dev.SCHEMA, "status": "validated_not_deployed",
                  "siteId": dev.SITE, "origin": dev.ORIGIN, "pageId": page_id,
                  "locales": locales, "productionCatalogSha256": dev.digest(public / "multilingual-v3.json"),
                  "baseBuildReportSha256": dev.digest(base / "build-report.json"),
                  "baseFiles": base_report["files"], "devLabelScriptSha256": label_sha,
                  "firebaseConfigSha256": dev.digest(temporary / "firebase.json"),
                  "appShellUpdate": {
                      "replacedFiles": sorted(replaced), "derivedFiles": sorted(DERIVED),
                      "addedFiles": sorted(added), "changedFiles": sorted(changed | DERIVED),
                      "productionUiPlanSourceCommit": plan.get("sourceCommit"),
                      "productionUiPlanIosCommit": plan.get("iosSourceCommit"),
                      "preservedDevFiles": sorted(PRESERVED | {"dev-preview-label.mjs"})},
                  "files": dev.inventory(public)}
        (temporary / "build-report.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        temporary.rename(out)
        return report
    except BaseException:
        shutil.rmtree(temporary)
        raise


def preflight(candidate: Path, base: Path) -> dict:
    report = dev.candidate_report(candidate)
    base_report = dry.baseline_report(base)
    if (report["baseBuildReportSha256"] != dev.digest(base / "build-report.json")
            or report["baseFiles"] != base_report["files"]):
        raise ValueError("Candidate uses a different Dev baseline")
    checked = 0
    for item in base_report["files"]:
        status, _, size, sha = http.request_file(dev.ORIGIN, "/" + item["path"])
        if (status, size, sha) != (200, item["bytes"], item["sha256"]):
            raise ValueError(f"Live Dev baseline changed: {item['path']}")
        checked += 1
    return {"schemaVersion": PREFLIGHT_SCHEMA, "status": "pass", "origin": dev.ORIGIN,
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "buildReportSha256": dev.digest(candidate / "build-report.json"),
            "baseBuildReportSha256": report["baseBuildReportSha256"], "checkedFiles": checked}


def deploy(candidate: Path, receipt: Path) -> dict:
    report = dev.candidate_report(candidate)
    pre = dev.load(receipt)
    age = datetime.now(timezone.utc) - datetime.fromisoformat(pre["checkedAt"])
    if (pre.get("schemaVersion") != PREFLIGHT_SCHEMA or pre.get("status") != "pass"
            or pre.get("origin") != dev.ORIGIN or not 0 <= age.total_seconds() <= 1800
            or pre.get("buildReportSha256") != dev.digest(candidate / "build-report.json")
            or pre.get("baseBuildReportSha256") != report["baseBuildReportSha256"]
            or pre.get("checkedFiles") != len(report["baseFiles"])):
        raise ValueError("Fresh complete Dev preflight required")
    subprocess.run(["npx", "--yes", "firebase-tools@15.29.0", "deploy", "--only", "hosting",
                    "--project", dev.SITE, "--non-interactive", "--message", "Dev app shell update"],
                   cwd=candidate, check=True)
    return {"schemaVersion": DEPLOYMENT_SCHEMA, "status": "deployed_http_verification_pending",
            "origin": dev.ORIGIN, "pageId": report["pageId"],
            "deployedAt": datetime.now(timezone.utc).isoformat(),
            "buildReportSha256": dev.digest(candidate / "build-report.json"),
            "preflightSha256": dev.digest(receipt), "files": len(report["files"])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("prepare")
    make.add_argument("--dev-base-candidate", type=Path, required=True)
    make.add_argument("--feature-public", type=Path, required=True)
    make.add_argument("--plan", type=Path)
    make.add_argument("--out", type=Path, required=True)
    check = commands.add_parser("preflight")
    check.add_argument("--candidate", type=Path, required=True)
    check.add_argument("--dev-base-candidate", type=Path, required=True)
    check.add_argument("--out", type=Path, required=True)
    deploy_command = commands.add_parser("deploy")
    deploy_command.add_argument("--candidate", type=Path, required=True)
    deploy_command.add_argument("--preflight", type=Path, required=True)
    deploy_command.add_argument("--out", type=Path, required=True)
    verify_command = commands.add_parser("verify")
    verify_command.add_argument("--candidate", type=Path, required=True)
    verify_command.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.dev_base_candidate, args.feature_public, args.plan, args.out)
        print(json.dumps({"status": "validated_not_deployed", "pageId": result["pageId"],
                          "replaced": len(result["appShellUpdate"]["replacedFiles"]),
                          "added": result["appShellUpdate"]["addedFiles"],
                          "changed": len(result["appShellUpdate"]["changedFiles"])}))
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as output:
        # Keep a durable failure marker if an operation raises after dispatch.
        output.write(json.dumps({"status": "operation_in_progress_or_failed", "command": args.command}) + "\n")
        output.flush()
        if args.command == "preflight":
            receipt = preflight(args.candidate, args.dev_base_candidate)
        elif args.command == "deploy":
            receipt = deploy(args.candidate, args.preflight)
        else:
            receipt = dev.verify(args.candidate)
        output.seek(0)
        output.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        output.truncate()
    print(json.dumps({"status": receipt.get("status"), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
