"""Exercise the exact path detector embedded in the required iOS workflow."""

import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import textwrap
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/tongxing-ios.yml"


def detector() -> str:
    text = WORKFLOW.read_text()
    marker = "          python3 - <<'PY'\n"
    start = text.index(marker) + len(marker)
    end = text.index("          PY\n", start)
    return textwrap.dedent(text[start:end])


def required_check_script() -> str:
    text = WORKFLOW.read_text()
    marker = "      - name: Check required iOS result\n"
    start = text.index("        run: |\n", text.index(marker)) + len("        run: |\n")
    return textwrap.dedent(text[start:])


class IOSRouteTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output_temp = TemporaryDirectory()
        self.addCleanup(self.output_temp.cleanup)
        self.repo = Path(self.temp.name)
        for args in (("init", "-q"), ("config", "user.email", "ci@example.test"),
                     ("config", "user.name", "CI")):
            subprocess.run(["git", *args], cwd=self.repo, check=True)
        (self.repo / "README.md").write_text("base\n")
        self.commit()
        self.base = self.sha()

    def commit(self):
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.repo, check=True)

    def sha(self):
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo,
                                       text=True).strip()

    def scope(self, event="pull_request"):
        output = Path(self.output_temp.name) / "action-output"
        output.unlink(missing_ok=True)
        env = {**os.environ, "GITHUB_EVENT_NAME": event, "BASE_SHA": self.base,
               "HEAD_SHA": self.sha(), "GITHUB_OUTPUT": str(output)}
        subprocess.run(["python3", "-c", detector()], cwd=self.repo,
                       env=env, check=True, capture_output=True)
        return output.read_text().strip()

    def test_non_native_contract_and_native_changes(self):
        for path, expected in (
            ("backend/app.py", "none"),
            ("docs/ci-cd-backlog.zh.md", "none"),
            ("experiments/sermon-dubbing-poc/web/styles.css", "none"),
            ("experiments/sermon-dubbing-poc/feedback-api/server.mjs", "none"),
            ("scripts/run_target_language_models.py", "none"),
            ("schemas/sermon-multilingual-catalog-v2.schema.json", "contract"),
            ("schemas/sermon-multilingual-catalog-v3.schema.json", "contract"),
            ("schemas/sermon-multilingual-catalog-v99.schema.json", "contract"),
            ("schemas/sermon-target-language-release-package-v1.schema.json", "contract"),
            ("schemas/sermon-target-language-release-package-v2.schema.json", "contract"),
            ("schemas/sermon-weekly-catalog-v1.schema.json", "contract"),
            ("scripts/assemble_multilingual_v3_update.py", "contract"),
            ("scripts/build_full_video_app_release.py", "contract"),
            ("scripts/build_formal_dev_release_assets.py", "contract"),
            ("firebase/dev/public/formal-dev-adapter.mjs", "contract"),
            ("experiments/sermon-dubbing-poc/web/published-weeks.mjs", "contract"),
            (".github/workflows/tongxing-ios.yml", "native"),
            (".github/workflows/python-tests.yml", "native"),
            (".github/actions/setup/action.yml", "native"),
            (".github/unittest-module-timings.json", "native"),
            ("new-runtime/adapter.py", "native"),
            ("schemas/unknown-contract-v1.schema.json", "native"),
            ("config/unknown-policy.json", "native"),
            ("docs/executable.js", "native"),
            ("scripts/NewClient.swift", "native"),
            ("apps/other-client/main.js", "native"),
            ("experiments/new-client/app.mjs", "native"),
            ("requirements.txt", "native"),
            ("apps/tongxing-ios/App/AppModel.swift", "native"),
        ):
            with self.subTest(path=path):
                subprocess.run(["git", "reset", "--hard", self.base], cwd=self.repo,
                               check=True, capture_output=True)
                target = self.repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(path)
                self.commit()
                self.assertEqual(self.scope(), f"scope={expected}")

    def test_removal_or_rename_of_contract_is_not_treated_as_non_native(self):
        original = self.repo / "schemas/sermon-multilingual-catalog-v3.schema.json"
        original.parent.mkdir(parents=True)
        original.write_text('frozen contract\n')
        self.commit()
        self.base = self.sha()
        for destination in (None, "docs/old-contract.md"):
            with self.subTest(destination=destination):
                subprocess.run(["git", "reset", "--hard", self.base], cwd=self.repo,
                               check=True, capture_output=True)
                if destination:
                    target = self.repo / destination
                    target.parent.mkdir(parents=True, exist_ok=True)
                    original.rename(target)
                else:
                    original.unlink()
                self.commit()
                self.assertEqual(self.scope(), "scope=contract")

    def test_mixed_native_and_shared_contract_uses_native_route(self):
        for name in ("apps/tongxing-ios/App.swift", "schemas/sermon-multilingual-catalog-v3.schema.json"):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        self.commit()
        self.assertEqual(self.scope(), "scope=native")

    def test_unknown_with_contract_forces_broad_route_and_empty_diff_is_conservative(self):
        self.assertEqual(self.scope(), "scope=native")
        for name in ("schemas/sermon-multilingual-catalog-v3.schema.json", "unknown/file.bin"):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        self.commit()
        self.assertEqual(self.scope(), "scope=native")

    def test_unknown_deleted_or_renamed_path_cannot_disappear_from_route(self):
        original = self.repo / "unknown/file.py"
        original.parent.mkdir()
        original.write_text("unknown implementation")
        self.commit()
        self.base = self.sha()
        original.rename(self.repo / "README.md")
        self.commit()
        self.assertEqual(self.scope(), "scope=native")

    def test_manual_validation_forces_native(self):
        self.assertEqual(self.scope(event="workflow_dispatch"), "scope=native")

    def test_required_check_routes_only_release_native_changes_to_simulator(self):
        cases = (
            ("none", "dev", "pull_request", "skipped", "skipped", True),
            ("contract", "dev", "pull_request", "success", "skipped", True),
            ("native", "dev", "pull_request", "success", "skipped", True),
            ("native", "main", "pull_request", "skipped", "success", True),
            ("native", "", "workflow_dispatch", "skipped", "success", True),
            ("native", "main", "pull_request", "skipped", "skipped", False),
        )
        for scope, base, event, contract, ios, expected in cases:
            with self.subTest(scope=scope, base=base, event=event, ios=ios):
                env = {**os.environ, "CHANGE_RESULT": "success", "SCOPE": scope,
                       "BASE_BRANCH": base, "EVENT_NAME": event, "IS_DRAFT": "false",
                       "CONTRACT_RESULT": contract, "IOS_RESULT": ios}
                result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c",
                                         required_check_script()], env=env, capture_output=True)
                self.assertEqual(result.returncode == 0, expected, result.stderr.decode())


    def test_drafts_and_failed_or_cancelled_jobs_never_masquerade_as_execution(self):
        for scope in ("none", "contract", "native"):
            for draft in ("true", "false"):
                for result in ("success", "failure", "cancelled", "skipped"):
                    with self.subTest(scope=scope, draft=draft, result=result):
                        env = {**os.environ, "CHANGE_RESULT": "success", "SCOPE": scope,
                               "BASE_BRANCH": "dev", "EVENT_NAME": "pull_request", "IS_DRAFT": draft,
                               "CONTRACT_RESULT": result, "IOS_RESULT": "skipped"}
                        actual = subprocess.run(["bash", "-e", "-o", "pipefail", "-c",
                                                 required_check_script()], env=env, capture_output=True)
                        expected = result == ("skipped" if draft == "true" or scope == "none" else "success")
                        self.assertEqual(actual.returncode == 0, expected)
        for scope in ("", "unexpected"):
            for draft in ("true", "false"):
                env = {**os.environ, "CHANGE_RESULT": "success", "SCOPE": scope, "BASE_BRANCH": "dev",
                       "EVENT_NAME": "pull_request", "IS_DRAFT": draft, "CONTRACT_RESULT": "skipped", "IOS_RESULT": "skipped"}
                actual = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", required_check_script()],
                                        env=env, capture_output=True)
                self.assertNotEqual(actual.returncode, 0)
        for change in ("failure", "cancelled", "skipped"):
            env = {**os.environ, "CHANGE_RESULT": change, "SCOPE": "none", "BASE_BRANCH": "dev",
                   "EVENT_NAME": "pull_request", "IS_DRAFT": "true", "CONTRACT_RESULT": "skipped", "IOS_RESULT": "skipped"}
            actual = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", required_check_script()],
                                    env=env, capture_output=True)
            self.assertNotEqual(actual.returncode, 0)


if __name__ == "__main__":
    unittest.main()
