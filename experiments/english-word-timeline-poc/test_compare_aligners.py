import importlib.util
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("compare_aligners", HERE / "compare_aligners.py")
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)


class AlignerComparisonTest(unittest.TestCase):
    def test_reports_structural_difference_without_accuracy_winner(self):
        qwen = [
            {"text": "We", "start": 0.1, "end": 0.3},
            {"text": "go", "start": 0.4, "end": 0.4},
        ]
        mfa = [
            {"text": "We", "start": 0.12, "end": 0.31},
            {"text": "go.", "start": 0.39, "end": 0.51},
        ]
        report, pairs = comparison.compare("We go.", qwen, mfa, 0.08)
        self.assertTrue(report["normalizedTokenSequenceExactMatch"])
        self.assertEqual(report["structuralResult"], "mfa_pass_qwen_fail")
        self.assertEqual(report["qwen"]["zeroOrNegativeDurationCount"], 1)
        self.assertEqual(report["mfa"]["invalidWordCount"], 0)
        self.assertIsNone(report["timingAccuracyWinner"])
        self.assertIn("qwen_zero_or_negative_duration", pairs[1]["reviewReasons"])

    def test_rejects_token_sequence_changes(self):
        qwen = [{"text": "stay", "start": 0.1, "end": 0.3}]
        mfa = [{"text": "go", "start": 0.1, "end": 0.3}]
        with self.assertRaisesRegex(ValueError, "MFA aligned tokens differ"):
            comparison.compare("Stay.", qwen, mfa, 0.08)

    def test_percentile_interpolates_and_validates_input(self):
        self.assertEqual(comparison.percentile([0, 1, 2], 0.5), 1)
        self.assertAlmostEqual(comparison.percentile([0, 10], 0.9), 9)
        with self.assertRaises(ValueError):
            comparison.percentile([], 0.5)


if __name__ == "__main__":
    unittest.main()
