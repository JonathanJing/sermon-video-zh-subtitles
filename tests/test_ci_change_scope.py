"""Real Git path routing and execution of the required check's exact shell."""

import ast
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

from scripts.ci_change_scope import change_scope


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/python-tests.yml"


def required_check_script() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    marker = "      - name: Require the selected validation suite\n"
    start = text.index("        run: |\n", text.index(marker)) + len("        run: |\n")
    return textwrap.dedent(text[start:])


class CIChangeScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        for args in (("init", "-q"), ("config", "user.email", "ci@example.invalid"),
                     ("config", "user.name", "CI fixture")):
            self.git(*args)
        self.write("README.md", "base\n")
        self.base = self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True).strip()

    def write(self, name, value="fixture\n"):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return path

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def scope(self, *, event="pull_request", base=None, head=None):
        output = self.repo / ".git/action-output"
        output.unlink(missing_ok=True)
        result = subprocess.run([
            sys.executable, str(ROOT / "scripts/ci_change_scope.py"),
            "--base", self.base if base is None else base,
            "--head", self.git("rev-parse", "HEAD") if head is None else head,
            "--event", event, "--output", str(output),
        ], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return output.read_text(encoding="utf-8").strip()

    def test_real_git_change_matrix(self):
        for paths, pr_scope, push_scope in (
            (("docs/guide.md",), "docs", "docs"),
            (("apps/tongxing-ios/App/AppModel.swift",), "native", "full"),
            (("apps/tongxing-ios/App/Resources/Localizable.xcstrings",), "native", "full"),
            (("apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-release-contracts.json",),
             "native", "full"),
            (("docs/guide.md", "apps/tongxing-ios/App/AppModel.swift"), "native", "full"),
            (("apps/tongxing-ios/App/AppModel.swift", "scripts/build_multilingual_catalog.py"), "full", "full"),
            (("apps/tongxing-ios/App/AppModel.swift", "schemas/catalog.schema.json"), "full", "full"),
            ((".github/workflows/python-tests.yml",), "full", "full"),
            (("new-runtime/unknown.py",), "full", "full"),
            (("docs/executable.py",), "full", "full"),
            (("tests/test_new_behavior.py",), "full", "full"),
            (("requirements.txt",), "full", "full"),
        ):
            with self.subTest(paths=paths):
                self.git("reset", "--hard", self.base)
                self.git("clean", "-fdq")
                for path in paths:
                    self.write(path)
                self.commit()
                self.assertEqual(self.scope(), f"scope={pr_scope}")
                self.assertEqual(self.scope(event="push"), f"scope={push_scope}")

    def test_empty_invalid_and_new_branch_base_fail_closed(self):
        self.assertEqual(self.scope(), "scope=full")
        self.write("apps/tongxing-ios/App/AppModel.swift")
        self.commit()
        for event, base in (("push", "0" * 40), ("pull_request", ""),
                            ("pull_request", "HEAD~1"), ("pull_request", "f" * 40)):
            with self.subTest(event=event, base=base):
                self.assertEqual(self.scope(event=event, base=base), "scope=full")
        self.assertEqual(self.scope(head="invalid"), "scope=full")
        self.assertEqual(change_scope(["apps/tongxing-ios/App.swift"], "workflow_dispatch"), "full")
        self.assertEqual(change_scope(["apps/tongxing-ios/../../scripts/producer.py"], "pull_request"), "full")

    def test_deleted_or_renamed_backend_path_still_requires_full_suite(self):
        original = self.write("scripts/producer.py", "same contents\n")
        self.base = self.commit()
        for destination in (None, "apps/tongxing-ios/App/Producer.swift", "docs/retired.md"):
            with self.subTest(destination=destination):
                self.git("reset", "--hard", self.base)
                self.git("clean", "-fdq")
                if destination:
                    target = self.repo / destination
                    target.parent.mkdir(parents=True, exist_ok=True)
                    original.rename(target)
                else:
                    original.unlink()
                self.commit()
                self.assertEqual(self.scope(), "scope=full")

    def test_deleted_native_fixture_remains_in_native_contract_suite(self):
        original = self.write("apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-catalog-pages.json")
        self.base = self.commit()
        original.unlink()
        self.commit()
        self.assertEqual(self.scope(), "scope=native")
        self.assertEqual(self.scope(event="push"), "scope=full")

    def test_required_shell_accepts_only_success_of_the_selected_suite(self):
        script = required_check_script()
        baselines = (
            {"SCOPE": "docs", "DOCS_ONLY": "true", "TEST_GROUP_RESULT": "skipped", "NATIVE_RESULT": "skipped"},
            {"SCOPE": "native", "DOCS_ONLY": "false", "TEST_GROUP_RESULT": "skipped", "NATIVE_RESULT": "success"},
            {"SCOPE": "full", "DOCS_ONLY": "false", "TEST_GROUP_RESULT": "success", "NATIVE_RESULT": "skipped"},
        )
        for baseline in baselines:
            accepted = {"CHANGE_RESULT": "success", **baseline}
            cases = [(accepted, True)]
            for key in ("CHANGE_RESULT", "TEST_GROUP_RESULT", "NATIVE_RESULT"):
                for result in ("success", "skipped", "failure", "cancelled", "unknown", ""):
                    cases.append(({**accepted, key: result}, result == accepted[key]))
            cases.append(({**accepted, "DOCS_ONLY": "false" if baseline["DOCS_ONLY"] == "true" else "true"}, False))
            for scope in ("", "unknown"):
                cases.append(({**accepted, "SCOPE": scope}, False))
            for env, expected in cases:
                with self.subTest(env=env):
                    result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                            env={**os.environ, **env}, capture_output=True)
                    self.assertEqual(result.returncode == 0, expected, result.stderr.decode())

    def test_native_suite_covers_every_current_shared_native_dependency(self):
        # Guard additions to the cross-client fixtures from silently escaping the
        # smaller suite. Names are discovered from consumers, not a frozen list.
        text = WORKFLOW.read_text(encoding="utf-8")
        start = text.index("  native_contracts:\n")
        end = text.index("  test_group:\n", start)
        native_job = text[start:end]
        for path in (ROOT / "tests").glob("test_*.py"):
            if path.name == Path(__file__).name:
                continue
            content = path.read_text(encoding="utf-8")
            if "apps/tongxing-ios/" in content:
                with self.subTest(consumer=path.name):
                    self.assertRegex(native_job, rf"\btests\.{re.escape(path.stem)}\b")
        for path in (ROOT / "experiments/sermon-dubbing-poc/web").glob("*.test.mjs"):
            if "apps/tongxing-ios/" in path.read_text(encoding="utf-8"):
                with self.subTest(consumer=path.name):
                    self.assertIn(path.relative_to(ROOT).as_posix(), native_job)

    def test_prefect_job_includes_every_opt_in_sdk_test(self):
        workflow = (ROOT / ".github/workflows/prefect-pilot.yml").read_text(encoding="utf-8")
        self.assertIn("SERMON_TEST_PREFECT: '1'", workflow)
        targets = set(re.findall(r"tests\.test_\w+\.\w+", workflow))
        expected = set()
        for path in (ROOT / "tests").glob("test_*.py"):
            source = path.read_text(encoding="utf-8")
            for item in ast.parse(source).body:
                if isinstance(item, ast.ClassDef) and any(
                    "SERMON_TEST_PREFECT" in ast.get_source_segment(source, decorator)
                    for decorator in item.decorator_list
                ):
                    expected.add(f"tests.{path.stem}.{item.name}")
        self.assertTrue(expected)
        self.assertEqual(targets, expected)


if __name__ == "__main__":
    unittest.main()
