import unittest
from datetime import datetime, timezone

from scripts import four_layer_progress as tracker


class FourLayerProgressTest(unittest.TestCase):
    def setUp(self):
        self.ledger = tracker.new_ledger("sermon-2026-09-20", ["zh-Hans", "ko", "es"])

    def test_separate_locale_progress_and_evidence_gate(self):
        with self.assertRaisesRegex(ValueError, "evidence"):
            tracker.update_step(self.ledger, "L2-04@ko", "complete")
        tracker.update_step(self.ledger, "L2-04@ko", "complete", evidence="review/ko-approval.json")
        report = tracker.summary(self.ledger)
        ko = next(row for row in report["rows"] if row["layer"] == 2 and row["locale"] == "ko")
        es = next(row for row in report["rows"] if row["layer"] == 2 and row["locale"] == "es")
        self.assertEqual((ko["complete"], es["complete"]), (1, 0))
        self.assertIsNone(report["earliestContinuousEta"])

    def test_eta_requires_all_estimates_and_no_waiting_review(self):
        for key in self.ledger["steps"]:
            tracker.update_step(self.ledger, key, "pending", estimate_minutes=10)
        tracker.update_step(self.ledger, "L3-02@ko", "running", elapsed_minutes=4)
        instant = datetime(2026, 9, 23, 17, 0, tzinfo=timezone.utc)
        report = tracker.summary(self.ledger, at=instant)
        self.assertEqual(report["remainingSerialMinutes"], 456)
        self.assertEqual(report["earliestContinuousEta"], "2026-09-24T00:36+00:00")
        tracker.update_step(self.ledger, "L3-05@ko", "waiting_review", reason="等待韩语全文听审")
        self.assertIsNone(tracker.summary(self.ledger, at=instant)["earliestContinuousEta"])

    def test_measured_unit_rate_and_invalidation_scope(self):
        tracker.update_step(self.ledger, "L3-02@ko", "running", elapsed_minutes=30,
                            done_units=10, total_units=40)
        self.assertEqual(tracker.remaining_minutes(self.ledger["steps"]["L3-02@ko"]), 90)
        tracker.update_step(self.ledger, "L2-04@ko", "complete", evidence="ko-review.json")
        tracker.update_step(self.ledger, "L2-04@es", "complete", evidence="es-review.json")
        changed = tracker.invalidate(self.ledger, 2, "ko", "译文修订")
        self.assertIn("L4-04@ko", changed)
        self.assertNotIn("L2-04@es", changed)
        self.assertEqual(self.ledger["steps"]["L2-04@ko"]["status"], "pending")
        self.assertEqual(self.ledger["steps"]["L2-04@es"]["status"], "complete")
        tracker.update_acceptance(self.ledger, "es", "device", "passed", evidence="iphone-es.json")
        tracker.update_acceptance(self.ledger, "ko", "device", "passed", evidence="iphone-ko.json")
        tracker.invalidate(self.ledger, 3, "ko", "音轨修订")
        self.assertEqual(self.ledger["acceptance"]["ko"]["device"]["status"], "not_run")
        self.assertEqual(self.ledger["acceptance"]["es"]["device"]["status"], "passed")
        all_changed = tracker.invalidate(self.ledger, 1, None, "英文锚点变化")
        self.assertEqual(len(all_changed), len(self.ledger["steps"]))


if __name__ == "__main__":
    unittest.main()
