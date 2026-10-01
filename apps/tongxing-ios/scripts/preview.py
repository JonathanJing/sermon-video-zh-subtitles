#!/usr/bin/env python3
"""Render registered SwiftUI views through a hosted iOS XCTest, then export PNGs."""

import argparse
import base64
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid

from ios_cli import APP_ROOT, PROJECT, REPO_ROOT, CommandFailed, Runner, developer_directory, select_simulator

REGISTRY = ("ContentView.swift", "PlaybackDock.swift", "DesignSystem.swift", "EnglishLocateSheet.swift")
VARIANTS = ("light", "dark", "dark-large")
TEST = "TongxingTests/SwiftUIPreviewTests/testRenderRequestedViews"


def split_values(value):
    return [part for part in re.split(r"[\s,]+", value.strip()) if part]


def selected_files(value):
    values = split_values(value)
    if not values:
        raise ValueError("请用 FILES 或 --files 选择视图；--list 列出已注册文件。")
    names = []
    for value in values:
        name = value.removeprefix("App/")
        if name not in REGISTRY:
            raise ValueError("未注册的预览文件：" + value + "。支持：" + ", ".join(REGISTRY))
        if not (APP_ROOT / "App" / name).is_file():
            raise ValueError("预览源文件不存在：App/" + name)
        if name not in names:
            names.append(name)
    return names


def parse_arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", default=os.environ.get("FILES", ""), help="注册文件名或 App/路径；逗号或空格分隔")
    parser.add_argument("--variants", default="light,dark", help="light,dark,dark-large；默认 light,dark")
    parser.add_argument("--interface-locale", choices=["zh-Hans", "en"], default="zh-Hans")
    parser.add_argument("--simulator", metavar="UDID", help="现有模拟器 UDID；默认复用唯一已启动的 iPhone")
    parser.add_argument("--developer-dir", help="完整 Xcode .app 或 Contents/Developer")
    parser.add_argument("--configuration", choices=["Debug"], default="Debug", help="预览夹具仅在 Debug 启用")
    parser.add_argument("--derived-data", type=Path, help="默认 worktree 本地 artifacts/tongxing-ios/preview/DerivedData")
    parser.add_argument("--dry-run", action="store_true", help="只读检查来源、scheme 与模拟器，展示命令；不构建")
    parser.add_argument("--list", action="store_true", help="列出已注册文件，不查询 Xcode")
    args = parser.parse_args()
    if args.simulator:
        try:
            args.simulator = str(uuid.UUID(args.simulator)).upper()
        except ValueError:
            parser.error("--simulator 必须为完整模拟器 UDID")
    return args


def source_identity(files):
    def git(*arguments):
        return subprocess.check_output(["git", *arguments], cwd=REPO_ROOT, text=True).strip()

    return {
        "git_revision": git("rev-parse", "HEAD"),
        "git_branch": git("branch", "--show-current"),
        "git_dirty": bool(git("status", "--porcelain")),
        "sources": [{"path": "apps/tongxing-ios/App/" + name,
                     "sha256": hashlib.sha256((APP_ROOT / "App" / name).read_bytes()).hexdigest()}
                    for name in files],
    }


@contextlib.contextmanager
def process_lock(key, metadata):
    """Process-lifetime locks are shared across worktrees and survive stale files safely."""
    directory = Path(tempfile.gettempdir()) / ("tongxing-preview-locks-" + str(os.getuid()))
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / (key + ".lock")
    with path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.seek(0)
            owner = lock.read().strip()
            raise ValueError("预览资源正被另一进程使用：" + key + "; " + owner) from None
        lock.seek(0)
        lock.truncate()
        json.dump(dict(metadata, pid=os.getpid()), lock, ensure_ascii=False)
        lock.flush()
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def validate_summary(summary):
    if (summary.get("result") != "Passed" or summary.get("totalTestCount") != 1
            or summary.get("passedTests") != 1 or summary.get("failedTests") != 0
            or summary.get("skippedTests") != 0 or summary.get("expectedFailures") != 0):
        raise ValueError("预览 XCTest 未实际通过唯一测试：" + json.dumps(summary, ensure_ascii=False))


def canonical_attachment_name(name, expected):
    if name in expected:
        return name
    # xcresulttool adds an attachment index and UUID to the XCTest name.
    suffix = re.fullmatch(r"(.+)_[0-9]+_[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}\.png", name)
    canonical = suffix[1] + ".png" if suffix else None
    return canonical if canonical in expected else None


def export_images(runner, result, directory, files, variants):
    exported = directory / "attachments"
    runner.run(["/usr/bin/xcrun", "xcresulttool", "export", "attachments", "--path", result,
                "--output-path", exported])
    attachment_manifest = json.loads((exported / "manifest.json").read_text(encoding="utf-8"))
    expected = {f"preview-{Path(name).stem}-{variant}.png" for name in files for variant in variants}
    matches = {}
    for test in attachment_manifest:
        for attachment in test["attachments"]:
            name = canonical_attachment_name(attachment["suggestedHumanReadableName"], expected)
            if name is not None:
                if name in matches:
                    raise ValueError("重复预览附件：" + name)
                source = exported / attachment["exportedFileName"]
                if source.parent.resolve() != exported.resolve() or not source.is_file():
                    raise ValueError("无效预览附件路径：" + name)
                if not source.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError("附件不是 PNG：" + name)
                if attachment.get("isAssociatedWithFailure"):
                    raise ValueError("预览附件关联测试失败：" + name)
                matches[name] = source
    missing = expected - matches.keys()
    if missing:
        raise ValueError("缺少预览图片：" + ", ".join(sorted(missing)))
    images = []
    for name in sorted(expected):
        target = directory / name
        shutil.copyfile(matches[name], target)
        images.append({"path": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    return images


def execute(args, runner, directory, receipt):
    files = selected_files(args.files)
    variants = list(dict.fromkeys(split_values(args.variants)))
    if not variants or set(variants) - set(VARIANTS):
        raise ValueError("预览外观只支持：" + ", ".join(VARIANTS))
    request = {"files": files, "variants": variants, "interfaceLocale": args.interface_locale}
    encoded = base64.b64encode(json.dumps(request, separators=(",", ":")).encode()).decode()
    receipt.update(source_identity(files), request=request,
                   fixture={"identity": "synthetic-native-published-page-zh-Hans",
                            "content_locale": "zh-Hans", "audio": "synthetic silent MP3",
                            "playback_state": "paused-ready"},
                   renderer={"method": "UIHostingController + UIKit drawHierarchy",
                             "viewport": "native simulator window bounds and scale",
                             "springboard_status_bar": False})
    developer = developer_directory(args.developer_dir)
    runner.environment["DEVELOPER_DIR"] = str(developer)
    receipt["developer_dir"] = str(developer)
    listing = runner.json(["/usr/bin/xcrun", "xcodebuild", "-project", PROJECT, "-list", "-json",
                           "-disableAutomaticPackageResolution"])["project"]
    if "Tongxing" not in listing.get("schemes", []) or "TongxingTests" not in listing.get("targets", []):
        raise ValueError("工程缺少 Tongxing scheme 或 TongxingTests；先同步 project.yml 与 Xcode 工程。")
    simulator = select_simulator(runner, args.simulator)
    derived = (args.derived_data or REPO_ROOT / "artifacts/tongxing-ios/preview/DerivedData").expanduser().resolve()
    destination = "platform=iOS Simulator,id=" + simulator["udid"]
    result = directory / "preview.xcresult"
    receipt.update(configuration=args.configuration, destination=destination, derived_data=str(derived),
                   simulator={key: simulator[key] for key in ("udid", "name", "runtime", "state")},
                   result_bundle=str(result), only_testing=TEST)
    command = ["/usr/bin/xcrun", "xcodebuild", "-project", PROJECT, "-scheme", "Tongxing",
               "-configuration", args.configuration, "-sdk", "iphonesimulator", "-destination", destination,
               "-derivedDataPath", derived, "-disableAutomaticPackageResolution", "-resultBundlePath", result,
               "-parallel-testing-enabled", "NO", "-only-testing:" + TEST, "CODE_SIGNING_ALLOWED=NO",
               "CODE_SIGNING_REQUIRED=NO", "TONGXING_PREVIEW_REQUEST=" + encoded, "test"]
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)
    if args.dry_run:
        print(shlex.join(map(str, command)))
        return
    metadata = {"repository": str(REPO_ROOT), "run_directory": str(directory)}
    derived_key = "derived-" + hashlib.sha256(str(derived).encode()).hexdigest()[:24]
    with process_lock("simulator-" + simulator["udid"], metadata), process_lock(derived_key, metadata):
        runner.run(command)
        summary = runner.json(["/usr/bin/xcrun", "xcresulttool", "get", "test-results", "summary", "--path", result])
        receipt["test_summary"] = summary
        validate_summary(summary)
        receipt["images"] = export_images(runner, result, directory, files, variants)
    receipt["result"] = "passed"


def main():
    args = parse_arguments()
    if args.list:
        print("\n".join("App/" + name for name in REGISTRY))
        return 0
    # Reject invalid selections before Xcode queries or creating a run directory.
    try:
        selected_files(args.files)
        if not split_values(args.variants) or set(split_values(args.variants)) - set(VARIANTS):
            raise ValueError("预览外观只支持：" + ", ".join(VARIANTS))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    now = dt.datetime.now().astimezone()
    directory = REPO_ROOT / "artifacts/tongxing-ios" / now.strftime("%Y-%m-%d") / "preview" / (
        now.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8])
    log = None
    if not args.dry_run:
        directory.mkdir(parents=True, exist_ok=False)
        log = (directory / "run.log").open("x", encoding="utf-8")
    runner = Runner(dict(os.environ), log)
    receipt = {"action": "preview", "dry_run": args.dry_run, "started": now.isoformat(),
               "run_directory": str(directory), "result": "not_run"}
    code = 0
    try:
        execute(args, runner, directory, receipt)
    except CommandFailed as error:
        code = error.code
        receipt.update(result="failed", error="工具退出码 " + str(code))
    except KeyboardInterrupt:
        code = 130
        receipt.update(result="interrupted")
    except (ValueError, OSError, KeyError, TypeError) as error:
        code = 2
        receipt.update(result="failed", error=str(error))
        print(error, file=sys.stderr)
    finally:
        receipt.update(exit_status=code, finished=dt.datetime.now().astimezone().isoformat(), commands=runner.commands)
        if log:
            log.write("\nExit status: " + str(code) + "\n")
            log.close()
            rendered = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
            (directory / "status.json").write_text(rendered, encoding="utf-8")
            (directory / "manifest.json").write_text(rendered, encoding="utf-8")
            print("预览结果与日志：" + str(directory), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
