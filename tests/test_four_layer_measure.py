import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import four_layer_measure as measure
from scripts import four_layer_progress as progress
from scripts import sermon_accounting as accounting


class FourLayerMeasureTest(unittest.TestCase):
    def test_canonical_producer_records_workload_and_failure_without_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger_path = Path(temp) / "four-layer-progress.json"
            progress.save(ledger_path, progress.new_ledger("test-page", ["ko"]))
            with measure.producer_step(ledger_path, "L2-03@ko", locale="ko") as metrics:
                metrics.update(sourceUnits=45, policySha256="a" * 64)
            with self.assertRaisesRegex(ValueError, "fixture failure"):
                with measure.producer_step(ledger_path, "L2-03@ko", locale="ko") as metrics:
                    metrics["sourceUnits"] = 45
                    raise ValueError("fixture failure")
            events, damaged = accounting.read_events(ledger_path.parent / "accounting")
            self.assertFalse(damaged)
            run = next(event for event in events if event["event"] == "run_started")
            self.assertEqual(run["metadata"]["pageId"], "test-page")
            self.assertEqual(run["metadata"]["target"], "dev")
            self.assertEqual(run["metadata"]["targetLocale"], "ko")
            self.assertEqual(run["metadata"]["ledgerIdentitySha256"],
                             progress.ledger_identity(progress.load(ledger_path)))
            workloads = [event for event in events if event["event"] == "workload"
                         and event["stage"] == "four_layer.L2-03:ko"]
            self.assertEqual(len(workloads), 2)
            self.assertEqual(workloads[0]["metrics"]["sourceUnits"], 45)
            report = measure.timing_audit(progress.load(ledger_path), events)
            row = next(row for row in report["rows"] if row["step"] == "L2-03@ko")
            self.assertEqual((row["executionAttempts"], row["failedExecutionAttempts"]), (2, 1))
            self.assertEqual(row["lastExecutionStatus"], "failed")
            self.assertFalse(row["openExecution"])
            self.assertEqual([attempt["status"] for attempt in row["attemptHistory"]],
                             ["completed", "failed"])
            self.assertEqual(row["attemptHistory"][0]["workload"]["sourceUnits"], 45)
            self.assertEqual(progress.load(ledger_path)["steps"]["L2-03@ko"]["status"], "pending")

    def test_producer_rejects_other_locale_before_logging(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger_path = Path(temp) / "four-layer-progress.json"
            progress.save(ledger_path, progress.new_ledger("test-page", ["ko"]))
            with self.assertRaisesRegex(ValueError, "does not belong"):
                with measure.producer_step(ledger_path, "L2-03@ko", locale="es"):
                    pass
            self.assertFalse((ledger_path.parent / "accounting").exists())

    def test_weekly_ledger_environment_connects_producer_without_extra_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger_path = Path(temp) / "four-layer-progress.json"
            progress.save(ledger_path, progress.new_ledger("test-page", ["es"]))
            with patch.dict("os.environ", {"SERMON_FOUR_LAYER_LEDGER": str(ledger_path)}):
                with measure.producer_step(None, "L2-01@es", locale="es") as metrics:
                    metrics["sourceUnits"] = 3
            events, damaged = accounting.read_events(ledger_path.parent / "accounting")
            self.assertFalse(damaged)
            self.assertTrue(any(event["event"] == "stage_finished"
                                and event["stage"] == "four_layer.L2-01:es" for event in events))

    def test_unfinished_span_is_not_reported_as_completed_time(self):
        ledger = progress.new_ledger("test-page", ["ko"])
        report = measure.timing_audit(ledger, [
            {"event": "workflow_started", "workflowId": "w1",
             "metadata": {"pageId": "test-page", "target": "dev",
                          "ledgerIdentitySha256": progress.ledger_identity(ledger)}},
            {"event": "stage_started", "workflowId": "w1",
             "stage": "four_layer.L3-01:ko", "spanId": "interrupted"}])
        row = next(row for row in report["rows"] if row["step"] == "L3-01@ko")
        self.assertTrue(row["openExecution"])
        self.assertIsNone(row["measuredExecutionSeconds"])
        self.assertEqual(row["attemptHistory"][0]["status"], "unfinished")

    def test_reinitialized_ledger_does_not_inherit_old_attempts(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger_path = Path(temp) / "four-layer-progress.json"
            old = progress.new_ledger("test-page", ["ko"])
            progress.save(ledger_path, old)
            with measure.producer_step(ledger_path, "L2-01@ko", locale="ko"):
                pass
            newer = progress.new_ledger("test-page", ["ko"])
            self.assertNotEqual(progress.ledger_identity(old), progress.ledger_identity(newer))
            progress.save(ledger_path, newer)
            events, _ = accounting.read_events(ledger_path.parent / "accounting")
            old_row = next(row for row in measure.timing_audit(old, events)["rows"]
                           if row["step"] == "L2-01@ko")
            new_row = next(row for row in measure.timing_audit(newer, events)["rows"]
                           if row["step"] == "L2-01@ko")
            self.assertEqual(old_row["executionAttempts"], 1)
            self.assertEqual(new_row["executionAttempts"], 0)
            self.assertIsNone(new_row["measuredExecutionSeconds"])

    def test_poc_source_window_change_excludes_old_timing_and_reports_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger_path = Path(temp) / "four-layer-progress.json"
            ledger = progress.new_poc_ledger(
                "test-page", ["ko"], target="dev", service_date="2026-09-27",
                source_id="video-id", source_url_sha256="a" * 64,
                window_start_seconds=10, window_end_seconds=20)
            progress.save(ledger_path, ledger)
            measure.execute(ledger_path, "L2-01@ko", [sys.executable, "-c", "pass"])
            events, _ = accounting.read_events(ledger_path.parent / "accounting")
            progress.update_step(ledger, "L2-01@ko", "complete", evidence="policy.json")
            self.assertEqual(measure.timing_audit(ledger, events)["completedWithoutMeasuredExecutionCount"], 0)
            ledger["history"][0]["source"]["windowEndSeconds"] = 21.0
            audit = measure.timing_audit(ledger, events)
            self.assertEqual(audit["measuredStepCount"], 0)
            self.assertEqual(audit["completedWithoutMeasuredExecution"], ["L2-01@ko"])
            self.assertEqual(audit["completedWithoutMeasuredExecutionCount"], 1)

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
