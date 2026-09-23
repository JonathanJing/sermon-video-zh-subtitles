import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import four_layer_measure as measure
from scripts import four_layer_progress as progress
from scripts import sermon_accounting as accounting


class FourLayerMeasureTest(unittest.TestCase):
    def test_real_command_span_is_linked_to_step(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger_path = Path(temp) / "four-layer-progress.json"
            progress.save(ledger_path, progress.new_ledger("test-page", ["ko"]))
            measure.execute(ledger_path, "L2-02@ko", [sys.executable, "-c", "pass"])
            events, damaged = accounting.read_events(ledger_path.parent / "accounting")
            self.assertFalse(damaged)
            report = measure.timing_audit(progress.load(ledger_path), events)
            row = next(row for row in report["rows"] if row["step"] == "L2-02@ko")
            self.assertEqual(row["executionAttempts"], 1)
            self.assertGreaterEqual(row["measuredExecutionSeconds"], 0)
            self.assertEqual(row["failedExecutionAttempts"], 0)
            self.assertEqual(progress.load(ledger_path)["steps"]["L2-02@ko"]["status"], "pending")

    def test_review_wait_is_operator_timestamp_and_missing_is_unknown(self):
        ledger = progress.new_ledger("test-page", ["ko"])
        ledger["history"] = [
            {"at": "2026-09-23T12:00:00+00:00", "action": "update", "step": "L2-04@ko", "status": "waiting_review"},
            {"at": "2026-09-23T12:20:00+00:00", "action": "update", "step": "L2-04@ko", "status": "complete"},
        ]
        report = measure.timing_audit(ledger, [])
        row = next(row for row in report["rows"] if row["step"] == "L2-04@ko")
        self.assertEqual(row["operatorReviewWaitSeconds"], 1200)
        self.assertIsNone(row["measuredExecutionSeconds"])

    def test_invalidation_closes_review_wait_before_new_cycle(self):
        ledger = progress.new_ledger("test-page", ["ko"])
        ledger["history"] = [
            {"at": "2026-09-23T12:00:00+00:00", "action": "update", "step": "L2-04@ko", "status": "waiting_review"},
            {"at": "2026-09-23T12:05:00+00:00", "action": "invalidate", "steps": ["L2-04@ko"]},
            {"at": "2026-09-23T12:10:00+00:00", "action": "update", "step": "L2-04@ko", "status": "waiting_review"},
            {"at": "2026-09-23T12:20:00+00:00", "action": "update", "step": "L2-04@ko", "status": "complete"},
        ]
        report = measure.timing_audit(ledger, [])
        row = next(row for row in report["rows"] if row["step"] == "L2-04@ko")
        self.assertEqual(row["closedReviewWaits"], 2)
        self.assertEqual(row["operatorReviewWaitSeconds"], 900)
        self.assertFalse(row["openReviewWait"])

    def test_unknown_step_cannot_run(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger_path = Path(temp) / "four-layer-progress.json"
            progress.save(ledger_path, progress.new_ledger("test-page", ["ko"]))
            with self.assertRaisesRegex(ValueError, "belong"):
                measure.execute(ledger_path, "L2-02@es", [sys.executable, "-c", "pass"])
            self.assertFalse((ledger_path.parent / "accounting").exists())

    def test_failed_command_retains_attempt_and_does_not_complete_step(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger_path = Path(temp) / "four-layer-progress.json"
            progress.save(ledger_path, progress.new_ledger("test-page", ["ko"]))
            with self.assertRaises(subprocess.CalledProcessError):
                measure.execute(ledger_path, "L3-02@ko", [sys.executable, "-c", "raise SystemExit(7)"])
            events, damaged = accounting.read_events(ledger_path.parent / "accounting")
            self.assertFalse(damaged)
            report = measure.timing_audit(progress.load(ledger_path), events)
            row = next(row for row in report["rows"] if row["step"] == "L3-02@ko")
            self.assertEqual((row["executionAttempts"], row["failedExecutionAttempts"]), (1, 1))
            self.assertEqual(progress.load(ledger_path)["steps"]["L3-02@ko"]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
