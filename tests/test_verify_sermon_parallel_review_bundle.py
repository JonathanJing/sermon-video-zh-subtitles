import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_sermon_parallel_review_bundle.py"
SPEC = importlib.util.spec_from_file_location("verify_sermon_parallel_review_bundle", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class VerifySermonParallelReviewBundleTest(unittest.TestCase):
    def test_add_check_records_state(self):
        checks = []
        mod.add_check(checks, "a", True, 1)
        mod.add_check(checks, "b", False, 2)
        self.assertEqual([item["state"] for item in checks], ["pass", "fail"])


if __name__ == "__main__":
    unittest.main()
