"""Offline admission tests; synthetic intents never authorize a real release."""
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest


CI_SCRIPTS = Path(__file__).resolve().parents[1] / "apps/tongxing-ios/ci_scripts"
SPEC = importlib.util.spec_from_file_location("archive_admission", CI_SCRIPTS / "validate_archive_intent.py")
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)
NOW = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)


def stamp(value):
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def source_configuration(directory, channel):
    project = GUARD.parse_project((directory / "project.pbxproj").read_text())
    objects = project["objects"]
    root = objects[project["rootObject"]]
    _, configuration, _ = GUARD.CHANNELS[channel]
    target_name = "Tongxing"
    targets = [objects[key] for key in root["targets"] if objects[key].get("name") == target_name]
    if len(targets) != 1:
        raise AssertionError(f"expected one {target_name} target")
    configurations = objects[targets[0]["buildConfigurationList"]]["buildConfigurations"]
    matches = [objects[key] for key in configurations if objects[key].get("name") == configuration]
    if len(matches) != 1:
        raise AssertionError(f"expected one {configuration} configuration")
    return matches[0]["buildSettings"]


def fixture(directory, channel="production", now=NOW):
    scheme, config, bundle = GUARD.CHANNELS[channel]
    settings = source_configuration(directory, channel)
    intent = {
        "schemaVersion": 1, "sourceCommit": "a" * 40,
        "channel": channel, "scheme": scheme, "configuration": config,
        "version": settings["MARKETING_VERSION"],
        "sourceBuild": settings["CURRENT_PROJECT_VERSION"],
        # Cloud's separately selected counter need not equal CURRENT_PROJECT_VERSION.
        "cloudBuild": "123", "issuedAt": stamp(now - timedelta(minutes=5)),
        "expiresAt": stamp(now + timedelta(minutes=55)),
        "resourcesSHA256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in GUARD.RESOURCES},
    }
    environment = {
        "CI_XCODE_CLOUD": "TRUE", "CI_XCODEBUILD_ACTION": "archive",
        "CI_COMMIT": intent["sourceCommit"], "CI_BUILD_NUMBER": intent["cloudBuild"],
        "CI_XCODE_SCHEME": scheme, "CI_BUNDLE_ID": bundle,
        "CI_PRODUCT_PLATFORM": "iOS", "CI_START_CONDITION": "push",
        "CI_PRIMARY_REPOSITORY_PATH": "/unavailable-checkout/repository",
        "CI_PROJECT_FILE_PATH": "/unavailable-checkout/repository/apps/tongxing-ios/Tongxing.xcodeproj",
    }
    return intent, environment


class ArchiveAdmissionTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "ci_scripts"
        # Apple materializes the resources linked from ci_scripts into later phases.
        # This copy has no checkout, .git, project directory or tools outside it.
        shutil.copytree(CI_SCRIPTS, self.directory, symlinks=False,
                        ignore=shutil.ignore_patterns("__pycache__"))
        self.intent, self.environment = fixture(self.directory)

    def validate(self, intent=None, environment=None):
        env = dict(self.environment if environment is None else environment)
        env[GUARD.INTENT_ENV] = json.dumps(self.intent if intent is None else intent)
        GUARD.validate(env, self.directory, NOW)

    def hook(self, env):
        return subprocess.run([str(self.directory / "ci_pre_xcodebuild.sh")],
                              cwd=self.temp.name, env={**os.environ, **env}, text=True, capture_output=True)

    def rehash(self, name):
        self.intent["resourcesSHA256"][name] = hashlib.sha256((self.directory / name).read_bytes()).hexdigest()

    def test_both_channels_on_actual_checked_project_with_only_ci_resources(self):
        for channel in GUARD.CHANNELS:
            with self.subTest(channel=channel):
                intent, env = fixture(self.directory, channel)
                self.validate(intent, env)

    def test_real_hook_archive_success_does_not_run_xcodebuild(self):
        intent, env = fixture(self.directory, now=datetime.now(timezone.utc))
        env[GUARD.INTENT_ENV] = json.dumps(intent)
        result = self.hook(env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Apple version/train/build admission and upload remain unverified", result.stdout)
        self.assertEqual(set(path.name for path in Path(self.temp.name).iterdir()), {"ci_scripts"})

    def test_nonarchive_actions_do_not_need_intent_python_or_resources(self):
        for path in self.directory.iterdir():
            if path.name != "ci_pre_xcodebuild.sh":
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        for action in ("build", "analyze", "build-for-testing", "test-without-building"):
            with self.subTest(action=action):
                result = self.hook({"CI_XCODEBUILD_ACTION": action, "PATH": "/no-tools", GUARD.INTENT_ENV: "broken"})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout + result.stderr, "")

    def test_missing_or_unknown_actions_fail_closed(self):
        for action in ("", "Archive", "test", "future-action"):
            with self.subTest(action=action):
                result = self.hook({"CI_XCODEBUILD_ACTION": action})
                self.assertNotEqual(result.returncode, 0)

    def test_all_required_cloud_identity_missing_or_mismatched(self):
        for key in self.environment:
            for replacement in (None, "incorrect"):
                with self.subTest(key=key, replacement=replacement):
                    env = dict(self.environment)
                    env.pop(key) if replacement is None else env.update({key: replacement})
                    with self.assertRaises(GUARD.AdmissionError):
                        self.validate(environment=env)

    def test_cloud_project_path_binding_without_access_to_checkout(self):
        for primary, project in (
            ("", "/repo/apps/tongxing-ios/Tongxing.xcodeproj"),
            ("relative/repo", "relative/repo/apps/tongxing-ios/Tongxing.xcodeproj"),
            ("/repo", "/other/apps/tongxing-ios/Tongxing.xcodeproj"),
            ("/repo", "/repo/other/Tongxing.xcodeproj"),
            ("/repo", "/repo/apps/tongxing-ios/DifferentProject.xcodeproj"),
            ("/repo", "/repo/apps/tongxing-ios/Tongxing.xcworkspace"),
            ("/repo", "/repo/other/../apps/tongxing-ios/Tongxing.xcodeproj"),
            ("/other/../repo", "/repo/apps/tongxing-ios/Tongxing.xcodeproj"),
            ("//repo", "//repo/apps/tongxing-ios/Tongxing.xcodeproj"),
        ):
            with self.subTest(primary=primary, project=project), self.assertRaises(GUARD.AdmissionError):
                self.validate(environment={**self.environment, "CI_PRIMARY_REPOSITORY_PATH": primary,
                                           "CI_PROJECT_FILE_PATH": project})
        # Redundant separators/dots normalize lexically, never via filesystem resolve.
        self.validate(environment={**self.environment, "CI_PRIMARY_REPOSITORY_PATH": "/unavailable/./repo//",
                                   "CI_PROJECT_FILE_PATH": "/unavailable/repo/apps/./tongxing-ios/Tongxing.xcodeproj"})

    def test_pr_synthetic_merge_never_passes_as_frozen_commit(self):
        for change in ({"CI_PULL_REQUEST_NUMBER": "7"}, {"CI_START_CONDITION": "pr_open"}, {"CI_START_CONDITION": "pr_update"}):
            with self.subTest(change=change), self.assertRaises(GUARD.AdmissionError):
                self.validate(environment={**self.environment, **change})

    def test_stale_future_and_unbounded_intents(self):
        for change in (
            {"expiresAt": stamp(NOW)}, {"expiresAt": stamp(NOW - timedelta(seconds=1))},
            {"issuedAt": stamp(NOW + timedelta(seconds=1))},
            {"expiresAt": stamp(NOW + timedelta(days=2))},
            {"issuedAt": "2026-10-02T07:55:00+00:00"},
            {"issuedAt": "not-a-time"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.validate({**self.intent, **change})

    def test_intent_schema_and_frozen_identity(self):
        cases = [None, [], True, {**self.intent, "allowArchive": True}]
        cases += [{k: v for k, v in self.intent.items() if k != field} for field in self.intent]
        cases += [{**self.intent, key: value} for key, value in (
            ("schemaVersion", True), ("schemaVersion", 2), ("sourceCommit", "a" * 7),
            ("sourceCommit", "b" * 40), ("version", "01.26.7"), ("version", "1.26.9"),
            ("version", "1.26.7 Beta"), ("sourceBuild", 51), ("sourceBuild", 50),
            ("cloudBuild", "124"), ("cloudBuild", "0123"), ("cloudBuild", "0"),
            ("channel", "unknown"), ("scheme", "TongxingBeta"), ("configuration", "Debug"),
            ("resourcesSHA256", {}), ("resourcesSHA256", []),
        )]
        for candidate in cases:
            with self.subTest(candidate=candidate):
                env = {**self.environment, GUARD.INTENT_ENV: json.dumps(candidate)}
                with self.assertRaises(ValueError):
                    GUARD.validate(env, self.directory, NOW)

    def test_missing_malformed_duplicate_or_secret_payload_is_not_logged(self):
        sentinel = "SECRET-MUST-NOT-APPEAR"
        payloads = ["", "{", sentinel, json.dumps({"extra": sentinel}),
                    json.dumps(self.intent)[:-1] + ',"schemaVersion":1}', "x" * 8193]
        for payload in payloads:
            with self.subTest(payload=payload[:30]):
                result = self.hook({**self.environment, GUARD.INTENT_ENV: payload})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("archive admission blocked", result.stderr)
                self.assertNotIn(sentinel, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_each_missing_or_changed_resource_fails_closed(self):
        for name in GUARD.RESOURCES:
            path = self.directory / name
            original = path.read_bytes()
            for missing in (True, False):
                with self.subTest(name=name, missing=missing):
                    if missing:
                        path.unlink()
                    else:
                        path.write_bytes(original + b"\n")
                    with self.assertRaises((GUARD.AdmissionError, OSError)):
                        self.validate()
                    path.write_bytes(original)

    def test_changed_project_semantics_rejected_even_with_matching_digest(self):
        path = self.directory / "project.pbxproj"
        original = path.read_text()
        current_version = self.intent["version"]
        current_build = self.intent["sourceBuild"]
        for old, new in (
            (f"MARKETING_VERSION = {current_version};", "MARKETING_VERSION = 1.26.9;"),
            (f"CURRENT_PROJECT_VERSION = {current_build};", "CURRENT_PROJECT_VERSION = 49;"),
            ('PRODUCT_BUNDLE_IDENTIFIER = "com.jonathanjing.tongxing.dev.listening-activity";', "PRODUCT_BUNDLE_IDENTIFIER = wrong;"),
            (f"MARKETING_VERSION = {current_version};", 'MARKETING_VERSION = "$(OVERRIDE_VERSION)";'),
            (f"MARKETING_VERSION = {current_version};", f'MARKETING_VERSION = {current_version}; "MARKETING_VERSION[sdk=iphoneos*]" = 1.2.0;'),
        ):
            with self.subTest(new=new), self.assertRaises(GUARD.AdmissionError):
                self.assertIn(old, original)
                path.write_text(original.replace(old, new))
                self.rehash(path.name)
                self.validate()
        path.write_text(original)
        self.rehash(path.name)

    def test_info_plist_and_scheme_mismatch_with_matching_digests(self):
        for name, old, new in (
            ("App-Info.plist", "$(MARKETING_VERSION)", "1.2.0"),
            ("Extension-Info.plist", "$(CURRENT_PROJECT_VERSION)", "44"),
            ("Tongxing.xcscheme", 'buildConfiguration = "Release"', 'buildConfiguration = "Debug"'),
            ("Tongxing.xcscheme", 'buildForArchiving = "YES"', 'buildForArchiving = "NO"'),
            ("Tongxing.xcscheme", "</ArchiveAction>", "<PreActions><ExecutionAction /></PreActions></ArchiveAction>"),
        ):
            path = self.directory / name
            original = path.read_text()
            with self.subTest(name=name, new=new), self.assertRaises(GUARD.AdmissionError):
                self.assertIn(old, original)
                path.write_text(original.replace(old, new))
                self.rehash(name)
                self.validate()
            path.write_text(original)
            self.rehash(name)

    def test_project_parser_rejects_ambiguity_and_unsupported_shapes(self):
        for raw in ('{a=1;a=2;}', '{a=1;', '{a=(one,two);', '{a=1;}extra', '{a=1;}/*unfinished', '{a="bad\\q";}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                GUARD.parse_project(raw)

    def test_hook_preserves_validator_failure_exit_status(self):
        (self.directory / "validate_archive_intent.py").write_text("import sys\nsys.exit(37)\n")
        self.assertEqual(self.hook(self.environment).returncode, 37)

    def test_downstream_xcodebuild_failure_is_not_wrapped_or_masked(self):
        intent, env = fixture(self.directory, now=datetime.now(timezone.utc))
        env[GUARD.INTENT_ENV] = json.dumps(intent)
        result = subprocess.run(["sh", "-c", '"$1" && exit 65', "test", str(self.directory / "ci_pre_xcodebuild.sh")],
                                env={**os.environ, **env}, capture_output=True)
        self.assertEqual(result.returncode, 65, result.stderr)
        self.assertFalse((CI_SCRIPTS / "ci_post_xcodebuild.sh").exists())


if __name__ == "__main__":
    unittest.main()
