import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "verify_sermon_parallel_quality_catalog.py"
)
SPEC = importlib.util.spec_from_file_location(
    "verify_sermon_parallel_quality_catalog", SCRIPT_PATH
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class VerifySermonParallelQualityCatalogTest(unittest.TestCase):
    def item(self, boundary_approved=False, priority="normal", issues=None):
        return {
            "priority": priority,
            "issues": (
                [mod.GENERIC_NORMAL_ISSUE] if issues is None else list(issues)
            ),
            "source": {"english": "Hello"},
            "candidate": {"chinese": "你好"},
            "boundary": {
                "approvedByHuman": boundary_approved,
                "status": (
                    "approved_human_boundary"
                    if boundary_approved
                    else "model_candidate_requires_human_review"
                ),
            },
        }

    def test_unreviewed_normal_requires_boundary_for_silver_candidate(self):
        isolated = mod.expected_release_state(self.item(False), None)
        self.assertEqual(isolated["qualityTier"], "isolated_reference")
        silver = mod.expected_release_state(self.item(True), None)
        self.assertEqual(silver["qualityTier"], "silver_automatic_candidate")
        self.assertIn("silver_precision_calibration_not_passed", silver["trainingBlockers"])

    def test_substantive_issue_never_becomes_automatic_silver(self):
        item = self.item(True, issues=["sourceAsrRisk"])
        state = mod.expected_release_state(item, None)
        self.assertEqual(state["qualityTier"], "isolated_reference")

    def test_human_approval_requires_boundary_for_gold(self):
        decision = {
            "status": "approved",
            "approvedEnglish": "Corrected",
            "approvedChinese": "修订",
        }
        blocked = mod.expected_release_state(self.item(False), decision)
        self.assertEqual(blocked["qualityTier"], "human_reviewed_boundary_blocked")
        gold = mod.expected_release_state(self.item(True), decision)
        self.assertEqual(gold["qualityTier"], "gold_human_reviewed")
        self.assertTrue(mod.RIGHTS_BLOCKERS <= gold["trainingBlockers"])


if __name__ == "__main__":
    unittest.main()
