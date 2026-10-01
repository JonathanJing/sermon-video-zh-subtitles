#!/bin/bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 - "$script_dir" "$@" <<'PY'
"""Archive a frozen native revision; never upload or release it."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shlex
import subprocess
import sys


ORIGINS = {
    "dev": "https://ai-for-god-sermon-audio-dev.web.app",
    "production": "https://ai-for-god-sermon-audio.web.app",
}
CHANNELS = {
    "beta": ("TongxingBeta", "BetaRelease", "com.jonathanjing.tongxing.beta", "同行-beta"),
    "production": ("Tongxing", "Release", "com.jonathanjing.tongxing.dev", "同行"),
}
module = Path(sys.argv.pop(1)).resolve().parent


def run(arguments, *, environment=None):
    result = subprocess.run(arguments, cwd=module, env=environment, capture_output=True, text=True)
    if result.returncode:
        # Git/tool queries contain no account or signing values; archive logs remain private.
        raise ValueError(f"命令失败（{result.returncode}）：{shlex.join(arguments)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def git(*arguments):
    return run(["git", *arguments])


def check_source(expected):
    head = git("rev-parse", "HEAD")
    if expected != head:
        raise ValueError("--expected-commit 必须与当前 HEAD 的完整 commit 一致；请先冻结并提交候选。")
    result = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "."], cwd=module)
    if result.returncode == 1:
        raise ValueError("tracked iOS 文件存在未提交差异；请先提交已验证的候选，再归档。")
    if result.returncode:
        raise ValueError("无法核对 tracked iOS 文件状态。")
    # XcodeGen/SwiftPM source discovery may include files absent from HEAD.
    # Restrict this check to build inputs; unrelated work and Xcode Cloud metadata remain untouched.
    source_directories = [
        "App", "Shared", "ListeningActivityExtension", "Core", "Infrastructure",
        "InfrastructureTests", "Tests", "UITests",
    ]
    untracked_sources = git("ls-files", "--others", "--exclude-standard", "--", *source_directories)
    if untracked_sources:
        raise ValueError("iOS 构建源码或资源目录存在未跟踪文件；请先提交或移出构建目录，再冻结候选。\n" + untracked_sources)
    return head


def developer_directory(value):
    explicit = value or os.environ.get("DEVELOPER_DIR")
    candidates = [Path(explicit).expanduser()] if explicit else [
        Path("/Applications/Xcode-beta.app"), Path("/Applications/Xcode.app")
    ]
    for path in candidates:
        if path.suffix == ".app":
            path = path / "Contents/Developer"
        if (path / "usr/bin/xcodebuild").is_file():
            return path.resolve()
    raise ValueError("未找到完整 Xcode；请传入 --developer-dir <Xcode.app 或 Contents/Developer>。")


def read_plist(path):
    with path.open("rb") as stream:
        return plistlib.load(stream)


def archive_digest(archive):
    manifest = []
    for path in sorted(archive.rglob("*")):
        relative = path.relative_to(archive).as_posix()
        if path.is_symlink():
            # Bind link identity without reading an external link target.
            manifest.append({"path": relative, "kind": "symlink", "target": os.readlink(path)})
        elif path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            manifest.append({"path": relative, "kind": "file", "sha256": digest.hexdigest()})
    if not manifest:
        raise ValueError("Archive 文件清单为空；未生成成功记录。")
    serialized = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest(), len(manifest)


def main():
    parser = argparse.ArgumentParser(prog="archive-channel.sh", description="归档冻结 commit，并从实际产物生成私有 release-record.json；不上传、不发布。")
    parser.add_argument("--channel", required=True, choices=CHANNELS)
    parser.add_argument("--expected-commit", required=True, help="必须与 HEAD 完全一致的完整 commit")
    parser.add_argument("--output-dir", required=True, help="仓库内被 Git 忽略、尚未使用的输出目录")
    parser.add_argument("--developer-dir", help="完整 Xcode .app 或 Contents/Developer；覆盖 DEVELOPER_DIR")
    parser.add_argument("--content-origin", choices=ORIGINS, help="Beta 默认 dev；正式版仅 production；Beta 发布候选可选 production")
    parser.add_argument("--dry-run", action="store_true", help="检查源码和路径，展示命令，不归档、不写文件")
    args = parser.parse_args()
    commit = check_source(args.expected_commit)
    repo = Path(git("rev-parse", "--show-toplevel"))
    output = Path(args.output_dir).expanduser().resolve()
    try:
        relative = output.relative_to(repo)
    except ValueError:
        raise ValueError("输出目录必须位于本仓库内的 Git 忽略路径。")
    ignored = subprocess.run(["git", "check-ignore", "--quiet", "--", str(relative)], cwd=repo)
    if ignored.returncode:
        raise ValueError("输出目录未被 Git 忽略；请使用 artifacts/tongxing-ios/...，避免提交签名日志和产物。")
    if output.exists() and any(output.iterdir()):
        raise ValueError("输出目录已有内容；请使用新的目录，保留既有验证记录。")
    origin_name = args.content_origin or ("dev" if args.channel == "beta" else "production")
    if args.channel == "production" and origin_name != "production":
        raise ValueError("正式版只能使用 production 内容源。")
    scheme, configuration, identifier, display_name = CHANNELS[args.channel]
    url_scheme = "tongxing-beta" if args.channel == "beta" else "tongxing"
    developer = developer_directory(args.developer_dir)
    environment = dict(os.environ, DEVELOPER_DIR=str(developer))
    archive = output / "Tongxing.xcarchive"
    command = [
        "xcrun", "xcodebuild", "-project", str(module / "Tongxing.xcodeproj"),
        "-scheme", scheme, "-configuration", configuration,
        "-destination", "generic/platform=iOS", "-derivedDataPath", str(output / "DerivedData"),
        "-archivePath", str(archive), "-allowProvisioningUpdates", "archive",
        f"TONGXING_CONTENT_ORIGIN={ORIGINS[origin_name]}",
    ]
    if args.dry_run:
        print(f"源码：{commit}\n渠道：{args.channel}；内容源：{origin_name}")
        print(f"DEVELOPER_DIR={shlex.quote(str(developer))} {shlex.join(command)}")
        return 0
    toolchain = run(["xcrun", "xcodebuild", "-version"], environment=environment)
    sdk = run(["xcrun", "--sdk", "iphoneos", "--show-sdk-version"], environment=environment)
    tree = git("rev-parse", "HEAD^{tree}")
    module_tree = git("rev-parse", "HEAD:apps/tongxing-ios")
    output.mkdir(parents=True, exist_ok=True)
    log = output / "archive.log"
    print(f"归档 {args.channel}（{commit}）；日志：{log}", flush=True)
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, cwd=module, env=environment, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        print(f"Archive 失败（{result.returncode}）；保留日志及产物，不生成成功记录：{log}", file=sys.stderr)
        return result.returncode
    check_source(commit)
    apps = list((archive / "Products/Applications").glob("*.app"))
    if len(apps) != 1:
        raise ValueError("Archive 未包含唯一 App；未生成成功记录。")
    app = read_plist(apps[0] / "Info.plist")
    if app.get("CFBundleIdentifier") != identifier or app.get("CFBundleDisplayName") != display_name:
        raise ValueError("Archive 的 App 身份或显示名与渠道不符；未生成成功记录。")
    if app.get("TongxingContentOrigin") != ORIGINS[origin_name]:
        raise ValueError("Archive 的内容源与请求不符；未生成成功记录。")
    registered_schemes = [value for item in app.get("CFBundleURLTypes", []) for value in item.get("CFBundleURLSchemes", [])]
    if app.get("TongxingURLScheme") != url_scheme or registered_schemes != [url_scheme]:
        raise ValueError("Archive 的 App 返回链接或注册 URL scheme 与渠道不符；未生成成功记录。")
    version, build = app.get("CFBundleShortVersionString"), app.get("CFBundleVersion")
    if not version or not build:
        raise ValueError("Archive 缺少版本或构建号；未生成成功记录。")
    extensions = [read_plist(path / "Info.plist") for path in (apps[0] / "PlugIns").glob("*.appex")]
    extension_ids = sorted(item.get("CFBundleIdentifier", "") for item in extensions)
    if extension_ids != [identifier + ".listening-activity"]:
        raise ValueError("Archive 的扩展身份与渠道不符；未生成成功记录。")
    if any(item.get("CFBundleShortVersionString") != version or item.get("CFBundleVersion") != build for item in extensions):
        raise ValueError("Archive 的 App 与扩展版本不一致；未生成成功记录。")
    if any(item.get("TongxingURLScheme") != url_scheme for item in extensions):
        raise ValueError("Archive 的扩展返回链接与渠道不符；未生成成功记录。")
    manifest_sha256, file_count = archive_digest(archive)
    check_source(commit)
    record = {
        "schemaVersion": 1,
        "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "sourceCommit": commit,
        "sourceTree": tree,
        "iosModuleTree": module_tree,
        "channel": args.channel,
        "scheme": scheme,
        "configuration": configuration,
        "version": str(version),
        "build": str(build),
        "bundleID": identifier,
        "displayName": display_name,
        "extensionIDs": extension_ids,
        "urlScheme": url_scheme,
        "contentOrigin": app["TongxingContentOrigin"],
        "xcode": toolchain,
        "sdk": {"name": "iphoneos", "version": sdk, "build": app.get("DTSDKBuild")},
        "archivePath": str(archive),
        "archiveManifestSHA256": manifest_sha256,
        "archiveFileCount": file_count,
        "archiveManifestAlgorithm": "sha256(canonical JSON v1: sorted relative path, kind, file sha256 or symlink target); excludes filesystem timestamps",
        "status": "archive_succeeded",
        "upload": {"status": "not_run"},
        "device": {"status": "not_run"},
        "venue": {"status": "not_run"},
    }
    record_path = output / "release-record.json"
    with record_path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(f"Archive 成功，版本 {version}（{build}）；记录：{record_path}")
    print("上传、手机验收与现场验收均为 not_run；本命令没有发布 App。")
    return 0


try:
    sys.exit(main())
except (ValueError, OSError, plistlib.InvalidFileException) as error:
    print(f"错误：{error}", file=sys.stderr)
    sys.exit(1)
PY
