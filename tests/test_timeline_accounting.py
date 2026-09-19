"""Source media accounting with no transcription or classification API calls."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import sermon_pipeline
from scripts import run_post_live_timeline_job as job
from scripts import sermon_accounting as accounting
from tests.test_run_post_live_timeline_job import make_args, write_state, make_handoff


class TimelineAccountingTests(unittest.TestCase):
    def clean_environment(self):
        for key in accounting.ENV_KEYS:
            os.environ.pop(key, None)

    def test_job_download_failure_has_stage_receipt_without_sensitive_command(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ), mock.patch.object(job.run_post_live_subtitle_generation, "download_archive_audio", side_effect=RuntimeError("secret-cookie-command")), mock.patch("builtins.print"):
            self.clean_environment()
            root = Path(temp)
            state = root/"state.json"
            write_state(state)
            notify = mock.Mock(return_value={"status": "skipped"})
            result = job.run_job(make_args(root, str(state)), metadata_loader=lambda _: {"live_status": "was_live", "was_live": True, "duration": 3600}, marker_reader=lambda _: None, handoff_reader=lambda _: None, marker_writer=lambda *a: None, notifier=notify)
            ledger = (root/"2026-07-12/accounting/events.jsonl").read_text()
            events = [json.loads(line) for line in ledger.splitlines()]
        self.assertEqual(result["status"], "waiting_for_download_access")
        failed = next(e for e in events if e["event"] == "stage_finished" and e["stage"] == "timeline.download_archive")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["errorType"], "RuntimeError")
        self.assertNotIn("secret-cookie-command", ledger)
        self.assertFalse(any(e["event"] == "api_attempt" for e in events))

    def test_source_verification_has_local_receipts_and_zero_model_api_attempts(self):
        def fake_download(uri, target):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"fake")
            return target
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ), mock.patch.object(sermon_pipeline, "chat_json", side_effect=AssertionError("Source verification must not classify")) as classifier, mock.patch.object(sermon_pipeline, "transcribe_openai_audio", side_effect=AssertionError("Source verification must not transcribe")) as asr, mock.patch.object(job.run_post_live_subtitle_generation, "probe_archive_audio", return_value={"format": {"duration": "3600"}, "streams": [{"codec_type": "audio"}]}), mock.patch("builtins.print"):
            self.clean_environment()
            root = Path(temp)
            state = root/"state.json"
            write_state(state)
            result = job.run_job(make_args(root, str(state)), metadata_loader=lambda _: {"live_status": "was_live", "was_live": True, "duration": 3600}, marker_reader=lambda _: None, handoff_reader=lambda _: make_handoff(b"fake"), gcs_downloader=fake_download, uploader=lambda *a: None, marker_writer=lambda *a: None, notifier=lambda *a: {"status": "skipped"})
            events = [json.loads(line) for line in (root/"2026-07-12/accounting/events.jsonl").read_text().splitlines()]
        self.assertEqual(result["status"], "requires_operator_review")
        self.assertEqual(result["schemaVersion"], 2)
        self.assertEqual(result["stage"], "source_media_verified")
        self.assertEqual(result["boundaryMethod"], "operator_supplied")
        self.assertIsNone(result["suggestedWindow"])
        classifier.assert_not_called()
        asr.assert_not_called()
        self.assertFalse(any(e["event"] == "api_attempt" for e in events))
        stages = {e["stage"] for e in events if e["event"] == "stage_finished"}
        self.assertTrue({"saturday_timeline", "timeline.metadata", "timeline.download_handoff", "timeline.verify_source_media", "timeline.upload"} <= stages)
        self.assertNotIn("timeline.probe", stages)
        self.assertFalse(any(name.startswith(("timeline.asr.", "timeline.classify.")) for name in stages))
        self.assertEqual(result["modelsUsed"], [])
        self.assertTrue(result["timelineGcsUri"].endswith("/timeline/source-media-report.json"))
        self.assertNotIn("gs://fake/private.m4a", json.dumps(events))


if __name__ == "__main__":
    unittest.main()
