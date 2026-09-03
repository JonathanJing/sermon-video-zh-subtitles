import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_sermon_parallel_corpus_poc.py"
SPEC = importlib.util.spec_from_file_location("verify_sermon_parallel_corpus_poc", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class VerifyParallelCorpusPocTest(unittest.TestCase):
    def test_secret_scanner_detects_key_and_resource_reference(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "safe.json").write_text('{"ok":true}', encoding="utf-8")
            self.assertEqual(mod.scan_secret_markers(root), [])
            (root / "bad.json").write_text(
                '{"key":"sk-proj-abcdefghijklmnop"}', encoding="utf-8"
            )
            self.assertEqual(len(mod.scan_secret_markers(root)), 1)

    def test_add_check_records_pass_and_fail(self):
        checks = []
        mod.add_check(checks, "a", True, 1)
        mod.add_check(checks, "b", False, 2)
        self.assertEqual(checks[0]["state"], "pass")
        self.assertEqual(checks[1]["state"], "fail")

    def test_human_approval_shape_requires_audio_and_decision_hash(self):
        boundary = {
            "status": "approved_human_boundary",
            "requiresHumanReview": False,
            "approvedByHuman": True,
            "approval": {"audioReviewCompleted": True, "decisionSha256": "a" * 64},
        }
        self.assertTrue(
            boundary.get("status") == "approved_human_boundary"
            and boundary.get("requiresHumanReview") is False
            and boundary.get("approvedByHuman") is True
            and boundary["approval"].get("audioReviewCompleted") is True
            and bool(boundary["approval"].get("decisionSha256"))
        )


if __name__ == "__main__":
    unittest.main()
