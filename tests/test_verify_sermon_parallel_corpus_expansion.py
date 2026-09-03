import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_sermon_parallel_corpus_expansion.py"
SPEC = importlib.util.spec_from_file_location("verify_sermon_parallel_corpus_expansion", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ExpansionVerifierTest(unittest.TestCase):
    def test_receipt_usage_ignores_non_receipts(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "plain.json"
            mod.corpus.write_json(path, {"status": "ok"})
            self.assertIsNone(mod.receipt_usage(path))

    def test_markdown_preserves_training_blocker(self):
        report = {
            "status": "pass_canary_needs_pipeline_revision",
            "counts": {
                "completedSermons": 1,
                "segments": 2,
                "pass": 1,
                "needsAudioReview": 1,
                "mustFix": 0,
                "remainingTrainDev": 158,
                "eligibleTrainDev": 159,
                "testPreservedUntouched": 18,
            },
            "observableUsage": {
                "requests": 4,
                "apiElapsedToContentRatio": 1.2,
                "duplicateSuccessfulStageSegmentBindings": 0,
                "limitation": "in-flight unknown",
            },
            "completed": [
                {
                    "videoId": "v",
                    "split": "train",
                    "segments": 2,
                    "auditCounts": {"pass": 1, "needsAudioReview": 1, "mustFix": 0},
                    "observableReceiptCount": 4,
                    "duplicateSuccessfulStageSegmentBindings": 0,
                }
            ],
        }
        text = mod.markdown(report)
        self.assertIn("trainingEligibility=blocked", text)
        self.assertIn("不自动启动剩余153篇", text)


if __name__ == "__main__":
    unittest.main()
