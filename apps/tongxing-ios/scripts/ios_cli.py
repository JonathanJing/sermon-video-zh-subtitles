#!/usr/bin/env python3
"""Project-local simulator commands; no signing, global Xcode switch or paid stages."""

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import signal
import subprocess
import sys
import uuid

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parents[1]
PROJECT = APP_ROOT / "Tongxing.xcodeproj"


class CommandFailed(Exception):
    def __init__(self, code):
        self.code = code if code >= 0 else 128 - code


class Runner:
    def __init__(self, environment, log=None):
        self.environment, self.log, self.commands = environment, log, []

    def run(self, command, capture=False):
        command = list(map(str, command))
        if self.log:
            self.log.write("\n$ " + shlex.join(command) + "\n")
            self.log.flush()
        lines = []
        with subprocess.Popen(command, cwd=APP_ROOT, env=self.environment,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, errors="replace", bufsize=1) as process:
            try:
                for line in process.stdout:
                    if capture:
                        lines.append(line)
                    if self.log:
                        self.log.write(line)
                        self.log.flush()
                    if not capture:
                        print(line, end="", flush=True)
                code = process.wait()
            except KeyboardInterrupt:
                process.send_signal(signal.SIGINT)
                process.wait()
                raise
        self.commands.append({"argv": command, "returncode": code})
        if code:
            if capture:
                print("".join(lines[-30:]), file=sys.stderr, end="")
            raise CommandFailed(code)
        return "".join(lines)

    def json(self, command):
        return json.loads(self.run(command, capture=True))


def arguments():
    parser = argparse.ArgumentParser(
        description="同行 iOS 模拟器构建、定向测试和启动；不执行 SwiftPM、线上下载或签名。",
        epilog="示例：ios.sh build；ios.sh test --simulator UDID；ios.sh test --ui；ios.sh launch --dry-run")
    parser.add_argument("action", choices=["build", "test", "launch"])
    parser.add_argument("--developer-dir", help="完整 Xcode 的 .app 或 Contents/Developer；覆盖 DEVELOPER_DIR")
    parser.add_argument("--scheme", help="默认发现并使用 Tongxing scheme")
    parser.add_argument("--simulator", metavar="UDID", help="指定已有模拟器；测试/启动优先复用唯一已启动的 iPhone")
    parser.add_argument("--configuration", choices=["Debug", "Release"], default="Debug")
    parser.add_argument("--derived-data", type=Path, help="复用构建目录，默认当日 artifacts/cli/DerivedData")
    parser.add_argument("--artifacts-dir", type=Path, help="日志与唯一结果目录的父路径，默认当日 artifacts/cli")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--ui", action="store_true", help="test 仅执行 TongxingUITests")
    selection.add_argument("--only-testing", action="append", metavar="TARGET[/CLASS[/METHOD]]",
                           help="test 精确选择，可重复；默认仅 TongxingTests")
    parser.add_argument("--app", type=Path, help="launch 安装已有 .app；默认从所选 scheme 构建设置查找")
    parser.add_argument("--launch-arg", action="append", default=[], help="launch 的 App 参数，可重复；以 - 开头时使用 =")
    parser.add_argument("--dry-run", action="store_true", help="只读查询 scheme、设备和构建设置，打印命令；不构建/测试/启动")
    args = parser.parse_args()
    if args.action != "test" and (args.ui or args.only_testing):
        parser.error("--ui / --only-testing 只用于 test")
    if args.action != "launch" and (args.app or args.launch_arg):
        parser.error("--app / --launch-arg 只用于 launch")
    if args.simulator is not None:
        try:
            args.simulator = str(uuid.UUID(args.simulator)).upper()
        except ValueError:
            parser.error("--simulator 必须是现有模拟器的完整 UDID，不能是空值或设备名")
    for selected in args.only_testing or []:
        if not re.fullmatch(r"(?:TongxingTests|TongxingUITests)(?:/[A-Za-z_][A-Za-z0-9_]*){0,2}", selected):
            parser.error("测试选择须为 TongxingTests 或 TongxingUITests，可接 /Class/Method")
    return args


def developer_directory(value):
    explicit = value or os.environ.get("DEVELOPER_DIR")
    candidates = [Path(explicit)] if explicit else [
        Path("/Applications/Xcode-beta.app/Contents/Developer"),
        Path("/Applications/Xcode.app/Contents/Developer"),
    ]
    for path in candidates:
        path = path.expanduser().resolve()
        if path.suffix == ".app":
            path = path / "Contents/Developer"
        if (path / "usr/bin/xcodebuild").is_file() and (path / "Platforms/iPhoneSimulator.platform").is_dir():
            return path
    raise ValueError("未找到完整 Xcode；使用 --developer-dir /Applications/Xcode.app/Contents/Developer。")


def select_simulator(runner, requested):
    devices = runner.json(["/usr/bin/xcrun", "simctl", "list", "devices", "available", "--json"])
    available = []
    for runtime, entries in devices.get("devices", {}).items():
        match = re.search(r"\.iOS-(\d+(?:-\d+)*)$", runtime)
        if not match:
            continue
        version = tuple(map(int, match[1].split("-")))
        if version < (17,):
            continue
        for device in entries:
            if device.get("isAvailable"):
                available.append(dict(device, runtime=runtime, version=version))
    if requested:
        matches = [device for device in available if device["udid"].lower() == requested.lower()]
        if not matches:
            raise ValueError("指定 UDID 不属于可用的 iOS 17+ 模拟器。用 xcrun simctl list devices available 查询。")
        return matches[0]
    phones = [device for device in available if ".iPhone-" in device.get("deviceTypeIdentifier", "")]
    booted = [device for device in phones if device["state"] == "Booted"]
    if len(booted) > 1:
        choices = ", ".join(device["name"] + " " + device["udid"] for device in booted)
        raise ValueError("有多个已启动 iPhone，请用 --simulator 指定共享设备：" + choices)
    if booted:
        return booted[0]
    if not phones:
        raise ValueError("没有可用的 iOS 17+ iPhone 模拟器；先在 Xcode 安装所需 runtime。")
    return sorted(phones, key=lambda device: (device["version"], device.get("lastUsedAt", ""),
                                              device["name"], device["udid"]), reverse=True)[0]


def execute(args, runner, artifact_root, run_directory, receipt):
    listing = runner.json(["/usr/bin/xcrun", "xcodebuild", "-project", PROJECT,
                           "-list", "-json", "-disableAutomaticPackageResolution"])["project"]
    schemes = listing.get("schemes", [])
    scheme = args.scheme or ("Tongxing" if "Tongxing" in schemes else schemes[0] if len(schemes) == 1 else None)
    if scheme not in schemes:
        raise ValueError("请用 --scheme 选择实际 scheme：" + ", ".join(schemes))
    simulator = select_simulator(runner, args.simulator) if args.action != "build" or args.simulator else None
    destination = "platform=iOS Simulator,id=" + simulator["udid"] if simulator else "generic/platform=iOS Simulator"
    derived = (args.derived_data or artifact_root / "DerivedData").expanduser().resolve()
    receipt.update(scheme=scheme, destination=destination, derived_data=str(derived))
    if simulator:
        receipt["simulator"] = {key: simulator[key] for key in ("udid", "name", "runtime", "state")}
    common = ["/usr/bin/xcrun", "xcodebuild", "-project", PROJECT, "-scheme", scheme,
              "-configuration", args.configuration, "-sdk", "iphonesimulator", "-destination", destination,
              "-derivedDataPath", derived, "-disableAutomaticPackageResolution",
              "CODE_SIGNING_ALLOWED=NO", "CODE_SIGNING_REQUIRED=NO"]
    if args.action == "launch":
        app = args.app.expanduser().resolve() if args.app else None
        if app is None:
            settings = runner.json(common + ["-showBuildSettings", "-json"])
            apps = [item["buildSettings"] for item in settings
                    if item["buildSettings"].get("PRODUCT_TYPE") == "com.apple.product-type.application"]
            if len(apps) != 1:
                raise ValueError("无法唯一确定 App 构建产物，请用 --app 指定已有 .app。")
            app = Path(apps[0]["TARGET_BUILD_DIR"]) / apps[0]["FULL_PRODUCT_NAME"]
        if (app / "Info.plist").is_file():
            with (app / "Info.plist").open("rb") as info:
                bundle_id = plistlib.load(info)["CFBundleIdentifier"]
        elif not args.dry_run:
            raise ValueError("未找到已有 App：" + str(app) + "。先使用相同 --derived-data 构建。")
        else:
            bundle_id = "<CFBundleIdentifier from " + str(app / "Info.plist") + ">"
        receipt["app"] = str(app)
        commands = []
        if simulator["state"] != "Booted":
            commands.append(["/usr/bin/xcrun", "simctl", "boot", simulator["udid"]])
        commands.extend([
            ["/usr/bin/xcrun", "simctl", "bootstatus", simulator["udid"], "-b"],
            ["/usr/bin/xcrun", "simctl", "install", simulator["udid"], app],
            ["/usr/bin/xcrun", "simctl", "launch", simulator["udid"], bundle_id] + args.launch_arg,
        ])
    else:
        result = run_directory / (args.action + ".xcresult")
        receipt["result_bundle"] = str(result)
        command = common + ["-resultBundlePath", result]
        if args.action == "test":
            selected = ["TongxingUITests"] if args.ui else args.only_testing or ["TongxingTests"]
            missing = {test.split("/")[0] for test in selected} - set(listing.get("targets", []))
            if missing:
                raise ValueError("工程缺少测试目标 " + ", ".join(sorted(missing)) + "；确认 project.yml 与工程已同步。")
            receipt["only_testing"] = selected
            command += ["-parallel-testing-enabled", "NO"] + ["-only-testing:" + test for test in selected]
        commands = [command + [args.action]]
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)
    for command in commands:
        if args.dry_run:
            print(shlex.join(map(str, command)))
        else:
            runner.run(command)


def main():
    args = arguments()
    day = dt.datetime.now().strftime("%Y-%m-%d")
    artifact_root = (args.artifacts_dir or REPO_ROOT / "artifacts/tongxing-ios" / day / "cli").expanduser().resolve()
    unique = dt.datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + args.action + "-" + uuid.uuid4().hex[:8]
    run_directory = artifact_root / unique
    log = None
    if not args.dry_run:
        run_directory.mkdir(parents=True, exist_ok=False)
        log = (run_directory / "run.log").open("x", encoding="utf-8")
    runner = Runner(dict(os.environ), log)
    receipt = {"action": args.action, "dry_run": args.dry_run,
               "started": dt.datetime.now().astimezone().isoformat(), "run_directory": str(run_directory)}
    code = 0
    try:
        developer = developer_directory(args.developer_dir)
        runner.environment["DEVELOPER_DIR"] = str(developer)
        receipt["developer_dir"] = str(developer)
        execute(args, runner, artifact_root, run_directory, receipt)
    except CommandFailed as error:
        code = error.code
    except KeyboardInterrupt:
        code = 130
    except (ValueError, OSError, KeyError) as error:
        code = 2
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        receipt.update(exit_status=code, finished=dt.datetime.now().astimezone().isoformat(), commands=runner.commands)
        if log:
            log.write("\nExit status: " + str(code) + "\n")
            log.close()
            (run_directory / "status.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print("结果与日志：" + str(run_directory), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
