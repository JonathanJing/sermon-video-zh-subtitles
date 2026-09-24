import unittest
import copy
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

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

    def test_poc_ledger_binds_exact_source_window_without_granting_approval(self):
        ledger = tracker.new_poc_ledger(
            "2026-09-27-sermon-clip", ["zh-Hans", "ko", "es"], target="dev",
            service_date="2026-09-27", source_id="video-id",
            source_url_sha256="a" * 64,
            window_start_seconds=2109.16, window_end_seconds=2287.32)
        binding = ledger["history"][0]["source"]
        self.assertEqual(binding["sourceId"], "video-id")
        self.assertEqual(binding["approvalStatus"], "proposed_not_approved")
        self.assertEqual(tracker.summary(ledger)["complete"], 0)
        original_identity = tracker.ledger_identity(ledger)
        binding["windowEndSeconds"] = 2300.0
        self.assertNotEqual(tracker.ledger_identity(ledger), original_identity)

    def test_poc_ledger_rejects_ambiguous_identity_and_window(self):
        kwargs = dict(target="dev", service_date="2026-09-27", source_id="video-id",
                      source_url_sha256="a" * 64,
                      window_start_seconds=10.0, window_end_seconds=20.0)
        with self.assertRaisesRegex(ValueError, "page ID"):
            tracker.new_poc_ledger("other/page", ["ko"], **kwargs)
        with self.assertRaisesRegex(ValueError, "window"):
            tracker.new_poc_ledger("good-page", ["ko"], **{**kwargs, "window_end_seconds": 10.0})
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            tracker.new_poc_ledger("good-page", ["ko"], **{**kwargs, "source_url_sha256": "unknown"})

    def test_init_poc_cli_creates_once_and_preserves_existing_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            args = ["progress", str(path), "init-poc", "--page-id", "test-page",
                    "--locales", "ko", "es", "--service-date", "2026-09-27",
                    "--source-id", "video-id", "--source-url-sha256", "a" * 64,
                    "--window-start-seconds", "10", "--window-end-seconds", "20"]
            with patch.object(sys, "argv", args):
                tracker.main()
            original = path.read_bytes()
            with patch.object(sys, "argv", args), self.assertRaises(SystemExit):
                tracker.main()
            self.assertEqual(path.read_bytes(), original)

    def test_approve_source_requires_exact_existing_human_receipt_and_keeps_timing_identity(self):
        ledger = tracker.new_poc_ledger(
            "test-page", ["ko"], target="dev", service_date="2026-09-20",
            source_id="clip-id", source_url_sha256="a" * 64,
            source_media_sha256="b" * 64,
            window_start_seconds=0, window_end_seconds=138)
        identity = tracker.ledger_identity(ledger)
        original_source = copy.deepcopy(ledger["history"][0]["source"])
        legacy_value = json.dumps({"ledger": ledger["ledgerId"], "pocSource": original_source},
                                  sort_keys=True, ensure_ascii=False)
        self.assertEqual(identity, hashlib.sha256(legacy_value.encode()).hexdigest())
        receipt = {"schemaVersion": "sermon-clip-window-approval-v1",
                   "sourceId": "clip-id", "sourceUrlHash": "a" * 64,
                   "sourceMediaSha256": "b" * 64, "startTime": "00:00:00",
                   "endTime": "00:02:18.000", "status": "approved", "humanApproval": True,
                   "approvedAt": "2026-09-24T18:51:31Z", "approvedBy": "user",
                   "evidence": "Approved this exact source and clip window."}
        for changed in ({"sourceId": "other"}, {"sourceUrlHash": "c" * 64},
                        {"sourceMediaSha256": "c" * 64}, {"endTime": "00:02:17.999"},
                        {"humanApproval": False}):
            with self.assertRaises(ValueError):
                tracker.approve_poc_source(ledger, {**receipt, **changed}, "c" * 64)
            self.assertEqual(ledger["history"][0]["source"], original_source)
        self.assertTrue(tracker.approve_poc_source(ledger, receipt, "c" * 64))
        source = tracker.poc_source_identity(ledger)
        self.assertEqual(source["approvalStatus"], "approved")
        self.assertEqual(source["approvalReceiptSha256"], "c" * 64)
        self.assertEqual(ledger["history"][-1]["action"], "poc_source_approved")
        self.assertEqual(tracker.ledger_identity(ledger), identity)
        self.assertFalse(tracker.approve_poc_source(ledger, receipt, "c" * 64))
        with self.assertRaisesRegex(ValueError, "different receipt"):
            tracker.approve_poc_source(ledger, receipt, "d" * 64)

    def test_approve_source_cli_hashes_receipt_bytes_and_does_not_change_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger_path = root / "progress.json"
            receipt_path = root / "clip-window-approval.json"
            ledger = tracker.new_poc_ledger(
                "test-page", ["ko"], target="dev", service_date="2026-09-20",
                source_id="clip-id", source_url_sha256="a" * 64,
                source_media_sha256="b" * 64,
                window_start_seconds=0, window_end_seconds=138)
            tracker.save_new(ledger_path, ledger)
            receipt = {"schemaVersion": "sermon-clip-window-approval-v1",
                       "sourceId": "clip-id", "sourceUrlHash": "a" * 64,
                       "sourceMediaSha256": "b" * 64, "startTime": "00:00:00",
                       "endTime": "00:02:18.000", "status": "approved", "humanApproval": True,
                       "approvedAt": "2026-09-24T18:51:31Z", "approvedBy": "user",
                       "evidence": "Approved this exact source and clip window."}
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with patch.object(sys, "argv", ["progress", str(ledger_path), "approve-source",
                                            "--receipt", str(receipt_path)]):
                tracker.main()
            actual = tracker.load(ledger_path)
            self.assertEqual(tracker.poc_source_identity(actual)["approvalReceiptSha256"],
                             hashlib.sha256(receipt_path.read_bytes()).hexdigest())
            self.assertEqual(tracker.summary(actual)["complete"], 0)

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
