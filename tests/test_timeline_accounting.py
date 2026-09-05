"""Timeline accounting integration with fake media/model/cloud operations."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import build_multistage_post_live_timeline as timeline
from scripts import run_post_live_timeline_job as job
from scripts import sermon_accounting as accounting
from tests.test_run_post_live_timeline_job import make_args, write_state


class TimelineAccountingTests(unittest.TestCase):
    def clean_environment(self):
        for key in accounting.ENV_KEYS:
            os.environ.pop(key, None)

    def test_classifier_cache_and_api_attempt_are_not_double_counted(self):
        def fake_chat(key, payload):
            response = {"id": "classification-response", "model": "test-model",
                        "usage": {"prompt_tokens": 12, "completion_tokens": 4},
                        "choices": [{"message": {"content": '{"startChunkId": 1, "endChunkId": 2}'}}]}
            accounting.record_api_attempt("test-model", response, .01)
            return response
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ), mock.patch.object(timeline.sermon_pipeline, "chat_json", side_effect=fake_chat) as api:
            self.clean_environment()
            root = Path(temp)
            with accounting.accounting_session(root/"accounting", "test_timeline"):
                classify = timeline.make_openai_classifier("private-key", model="test-model", reasoning_effort="high", cache_dir=root/"cache")
                first = classify("coarse", [{"id": 1}, {"id": 2}])
                second = classify("coarse", [{"id": 1}, {"id": 2}])
            events = [json.loads(line) for line in (root/"accounting/events.jsonl").read_text().splitlines()]
        self.assertEqual(first, second)
        api.assert_called_once()
        attempts = [e for e in events if e["event"] == "api_attempt"]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["stage"], "timeline.classify.coarse")
        finished = [e for e in events if e["event"] == "stage_finished" and e["stage"] == "timeline.classify.coarse"]
        self.assertEqual([e["cacheHit"] for e in finished], [False, True])
        self.assertNotIn("private-key", json.dumps(events))

    def test_asr_zone_preserves_absolute_timestamps_and_stage(self):
        def fake_transcribe(**kwargs):
            accounting.record_api_attempt("test-model", {"id": "asr-response", "usage": {"input_tokens": 9, "output_tokens": 2}}, .01)
            return [{"id": 0, "start": 0, "end": 5, "text": "private transcript"}]
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ), mock.patch.object(timeline.build_post_live_timeline, "transcribe_full_audio_chunks", side_effect=fake_transcribe):
            self.clean_environment()
            root = Path(temp)
            with accounting.accounting_session(root/"accounting", "test_timeline"):
                chunks = timeline.transcribe_absolute_chunks(api_key="private-key", source=root/"source.m4a", outdir=root/"start_fine_5s"/"zone_100000_105000", chunk_seconds=5, model="test-model", absolute_offset=100)
            events = [json.loads(line) for line in (root/"accounting/events.jsonl").read_text().splitlines()]
        self.assertEqual((chunks[0]["start"], chunks[0]["end"]), (100, 105))
        self.assertEqual(next(e for e in events if e["event"] == "api_attempt")["stage"], "timeline.asr.start_fine_5s")
        self.assertNotIn("private transcript", json.dumps(events))

    def test_job_download_failure_has_stage_receipt_without_sensitive_command(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ), mock.patch.object(job.run_post_live_subtitle_generation, "download_archive_audio", side_effect=RuntimeError("secret-cookie-command")), mock.patch("builtins.print"):
            self.clean_environment()
            root = Path(temp)
            state = root/"state.json"
            write_state(state)
            notify = mock.Mock(return_value={"status": "skipped"})
            result = job.run_job(make_args(root, str(state)), metadata_loader=lambda _: {"live_status": "was_live", "was_live": True}, marker_reader=lambda _: None, handoff_reader=lambda _: None, marker_writer=lambda *a: None, notifier=notify)
            ledger = (root/"2026-07-12/accounting/events.jsonl").read_text()
            events = [json.loads(line) for line in ledger.splitlines()]
        self.assertEqual(result["status"], "waiting_for_download_access")
        failed = next(e for e in events if e["event"] == "stage_finished" and e["stage"] == "timeline.download_archive")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["errorType"], "RuntimeError")
        self.assertNotIn("secret-cookie-command", ledger)
        self.assertFalse(any(e["event"] == "api_attempt" for e in events))

    def test_handoff_metadata_and_upload_are_timed_without_changing_review_gate(self):
        def fake_download(uri, target):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"fake")
            return target
        def fake_probe(args):
            args.outdir.mkdir(parents=True, exist_ok=True)
            return {"analysis": {"suggestedWindow": {"startSeconds": 10, "endSeconds": 20}}}
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ), mock.patch.object(job.build_multistage_post_live_timeline, "build_multistage_timeline", side_effect=fake_probe), mock.patch("builtins.print"):
            self.clean_environment()
            root = Path(temp)
            state = root/"state.json"
            write_state(state)
            result = job.run_job(make_args(root, str(state)), metadata_loader=lambda _: {"live_status": "was_live", "was_live": True}, marker_reader=lambda _: None, handoff_reader=lambda _: {"status": "complete", "audio": {"gcsUri": "gs://fake/private.m4a"}}, gcs_downloader=fake_download, uploader=lambda *a: None, marker_writer=lambda *a: None, notifier=lambda *a: {"status": "skipped"})
            events = [json.loads(line) for line in (root/"2026-07-12/accounting/events.jsonl").read_text().splitlines()]
        self.assertEqual(result["status"], "requires_operator_review")
        stages = {e["stage"] for e in events if e["event"] == "stage_finished"}
        self.assertTrue({"saturday_timeline", "timeline.metadata", "timeline.download_handoff", "timeline.probe", "timeline.upload"} <= stages)
        self.assertNotIn("gs://fake/private.m4a", json.dumps(events))


if __name__ == "__main__":
    unittest.main()
