import io
import json
import unittest
from contextlib import redirect_stdout

from backend.observability import command_stage, log_event, trigger_source, url_summary


class ObservabilityTest(unittest.TestCase):
    def test_trigger_source_detects_cloud_scheduler(self):
        self.assertEqual(
            trigger_source({"User-Agent": "Google-Cloud-Scheduler", "X-CloudScheduler": "true"}),
            "cloud-scheduler",
        )

    def test_trigger_source_prefers_payload_override(self):
        self.assertEqual(trigger_source({}, {"triggerSource": "manual-live-test"}), "manual-live-test")

    def test_url_summary_hashes_full_url(self):
        summary = url_summary("https://www.youtube.com/watch?v=abc123")
        self.assertEqual(summary["host"], "www.youtube.com")
        self.assertEqual(summary["path"], "/watch")
        self.assertNotIn("abc123", json.dumps(summary))

    def test_command_stage_labels_pipeline_steps(self):
        self.assertEqual(command_stage(["python", "scripts/prepare_live_link_playback.py"]), "prepare-live-playback")
        self.assertEqual(command_stage(["python", "scripts/translate_playback_with_openai.py"]), "translate-captions")
        self.assertEqual(command_stage(["gcloud", "storage", "cp", "a", "b"]), "upload-translated-playback")
        self.assertEqual(command_stage(["python", "scripts/promote_sunday_manifest.py"]), "promote-sunday-manifest")

    def test_log_event_writes_structured_json(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            log_event("captions_ready", sunday="2026-06-28", sessionId="worker-test")
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["event"], "captions_ready")
        self.assertEqual(payload["sunday"], "2026-06-28")
        self.assertEqual(payload["severity"], "INFO")


if __name__ == "__main__":
    unittest.main()
