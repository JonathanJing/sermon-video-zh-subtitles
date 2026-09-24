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
            ("schemas/sermon-multilingual-catalog-v2.schema.json", "contract"),
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


if __name__ == "__main__":
    unittest.main()
