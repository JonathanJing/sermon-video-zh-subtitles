"""Keep checks that no workflow would otherwise run wired into the required Python check."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/python-tests.yml").read_text(encoding="utf-8")
ICON_CHECK = "run: python scripts/check_tongxing_icon_alignment.py"


def job_text(name: str) -> str:
    start = WORKFLOW.index(f"\n  {name}:\n")
    following = [WORKFLOW.find(f"\n  {other}:\n", start + 1) for other in ("native_contracts", "test_group", "unittest")]
    return WORKFLOW[start:min((index for index in following if index > 0), default=len(WORKFLOW))]


class WorkflowCoverageTests(unittest.TestCase):
    def test_root_node_tests_run_through_the_glob_the_workflow_uses(self):
        self.assertIn("run: node --test tests/*.mjs", job_text("test_group"))
        self.assertTrue(sorted((ROOT / "tests").glob("*.mjs")), "the workflow glob would match nothing")

    def test_icon_alignment_runs_for_web_changes_and_for_native_only_changes(self):
        # Native-only pull requests skip test_group, so each route needs its own step.
        self.assertIn(ICON_CHECK, job_text("test_group"))
        self.assertIn(ICON_CHECK, job_text("native_contracts"))


if __name__ == "__main__":
    unittest.main()
