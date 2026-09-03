import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_sermon_split_manifest.py"
SPEC = importlib.util.spec_from_file_location("verify_sermon_split_manifest", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class VerifySermonSplitManifestTest(unittest.TestCase):
    def test_hash_leakage_only_reports_cross_split_duplicates(self):
        rows = [
            {"videoId": "a", "split": "train", "hash": "same"},
            {"videoId": "b", "split": "train", "hash": "same"},
            {"videoId": "c", "split": "test", "hash": "other"},
        ]
        self.assertEqual(mod.hash_leakage(rows, "hash"), [])
        rows[-1]["hash"] = "same"
        leaks = mod.hash_leakage(rows, "hash")
        self.assertEqual(len(leaks), 1)
        self.assertEqual({item["split"] for item in leaks[0]["items"]}, {"train", "test"})


if __name__ == "__main__":
    unittest.main()
