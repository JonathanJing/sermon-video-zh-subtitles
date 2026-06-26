import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.progress import (
    GenerationProgressStore,
    default_generation_progress_gcs_prefix,
    pipeline_stages_for_command,
    safe_component,
)


class GenerationProgressTest(unittest.TestCase):
    def test_store_builds_pipeline_status_from_worker_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = GenerationProgressStore(Path(tmp))
            store.append(
                event="live_capture_planned",
                sunday="2026-06-28",
                session_id="worker-test",
                run_prefix="sundays/2026-06-28/runs/worker-test",
                command_count=8,
                status="planned",
            )
            store.append(
                event="worker_stage_started",
                sunday="2026-06-28",
                session_id="worker-test",
                run_prefix="sundays/2026-06-28/runs/worker-test",
                command_stage="prepare-live-playback",
                status="running",
            )
            running = store.status("2026-06-28", "worker-test")
            running_stages = {stage["id"]: stage for stage in running["pipelineStages"]}
            self.assertEqual(running["status"], "running")
            self.assertEqual(running["currentCommandStage"], "prepare-live-playback")
            self.assertEqual(running_stages["source-discovery"]["state"], "done")
            self.assertEqual(running_stages["live-capture"]["state"], "active")
            self.assertEqual(running_stages["sermon-start"]["state"], "active")
            self.assertEqual(running_stages["transcript"]["state"], "active")

            store.append(
                event="worker_stage_completed",
                sunday="2026-06-28",
                session_id="worker-test",
                run_prefix="sundays/2026-06-28/runs/worker-test",
                command_stage="prepare-live-playback",
                status="running",
            )
            store.append(
                event="worker_stage_completed",
                sunday="2026-06-28",
                session_id="worker-test",
                run_prefix="sundays/2026-06-28/runs/worker-test",
                command_stage="translate-captions",
                status="running",
            )
            translated = store.status("2026-06-28", "worker-test")
            translated_stages = {stage["id"]: stage for stage in translated["pipelineStages"]}
            self.assertEqual(translated_stages["live-capture"]["state"], "done")
            self.assertEqual(translated_stages["sermon-start"]["state"], "done")
            self.assertEqual(translated_stages["transcript"]["state"], "done")
            self.assertEqual(translated_stages["translation"]["state"], "done")

            store.append(
                event="captions_ready",
                sunday="2026-06-28",
                session_id="worker-test",
                run_prefix="sundays/2026-06-28/runs/worker-test",
                status="completed",
            )
            completed = store.status("2026-06-28", "worker-test")
            self.assertEqual(completed["status"], "completed")
            self.assertTrue(all(stage["state"] == "done" for stage in completed["pipelineStages"]))

    def test_store_marks_failed_stage_and_sanitizes_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = GenerationProgressStore(Path(tmp))
            store.append(
                event="worker_stage_failed",
                sunday="2026/06/28",
                session_id="worker bad/id",
                command_stage="translate-captions",
                error="OpenAI request failed",
                status="failed",
            )

            status = store.status("2026/06/28", "worker bad/id")
            stages = {stage["id"]: stage for stage in status["pipelineStages"]}
            self.assertEqual(status["status"], "failed")
            self.assertEqual(status["failedCommandStage"], "translate-captions")
            self.assertEqual(status["error"], "OpenAI request failed")
            self.assertEqual(stages["translation"]["state"], "failed")
            self.assertEqual(safe_component("worker bad/id"), "worker_bad_id")

    def test_command_stages_map_to_admin_pipeline_stages(self):
        self.assertEqual(
            pipeline_stages_for_command("prepare-live-playback"),
            ["live-capture", "sermon-start", "transcript"],
        )
        self.assertEqual(pipeline_stages_for_command("translate-captions"), ["translation"])
        self.assertEqual(pipeline_stages_for_command("promote-sunday-manifest"), ["promotion", "public-ready"])

    def test_gcs_mirror_writes_session_events_and_latest_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            writes = {}

            def fake_write(uri, text, content_type="application/json; charset=utf-8"):
                writes[uri] = {"text": text, "contentType": content_type}

            with patch("backend.progress.write_gcs_text", side_effect=fake_write):
                store = GenerationProgressStore(
                    Path(tmp),
                    gcs_prefix="gs://sermon-zh-artifacts-ai-for-god/sundays/generation-progress",
                )
                store.append(
                    event="live_capture_planned",
                    sunday="2026-06-28",
                    session_id="worker-test",
                    run_prefix="sundays/2026-06-28/runs/worker-test",
                    command_count=8,
                    status="planned",
                )

            latest_uri = "gs://sermon-zh-artifacts-ai-for-god/sundays/generation-progress/2026-06-28/latest-status.json"
            session_uri = "gs://sermon-zh-artifacts-ai-for-god/sundays/generation-progress/2026-06-28/worker-test.jsonl"
            self.assertIn(latest_uri, writes)
            self.assertIn(session_uri, writes)
            self.assertEqual(writes[session_uri]["contentType"], "application/x-ndjson")
            self.assertIn('"status": "planned"', writes[latest_uri]["text"])

    def test_status_falls_back_to_gcs_latest_status(self):
        latest = '{"schemaVersion":1,"status":"planned","sunday":"2026-06-28","sessionId":"worker-test","pipelineStages":[]}'
        with tempfile.TemporaryDirectory() as tmp:
            with patch("backend.progress.read_gcs_text", return_value=latest) as read:
                store = GenerationProgressStore(
                    Path(tmp),
                    gcs_prefix="gs://sermon-zh-artifacts-ai-for-god/sundays/generation-progress",
                )
                status = store.status("2026-06-28")

        self.assertEqual(status["status"], "planned")
        self.assertEqual(status["sessionId"], "worker-test")
        read.assert_called_once_with(
            "gs://sermon-zh-artifacts-ai-for-god/sundays/generation-progress/2026-06-28/latest-status.json"
        )

    def test_status_prefers_newer_gcs_status_over_stale_local_file(self):
        gcs_status = (
            '{"schemaVersion":1,"status":"running","sunday":"2026-06-28",'
            '"sessionId":"worker-new","updatedAt":"2026-06-28T18:01:00+00:00","pipelineStages":[]}'
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = GenerationProgressStore(Path(tmp))
            store.append(
                event="live_capture_planned",
                sunday="2026-06-28",
                session_id="worker-old",
                run_prefix="sundays/2026-06-28/runs/worker-old",
                status="planned",
            )
            store.gcs_prefix = "gs://sermon-zh-artifacts-ai-for-god/sundays/generation-progress"
            with patch("backend.progress.read_gcs_text", return_value=gcs_status):
                status = store.status("2026-06-28")

        self.assertEqual(status["status"], "running")
        self.assertEqual(status["sessionId"], "worker-new")

    def test_default_gcs_prefix_uses_artifact_bucket_and_prefix(self):
        self.assertEqual(
            default_generation_progress_gcs_prefix("bucket", "sundays", None),
            "gs://bucket/sundays/generation-progress",
        )
        self.assertEqual(
            default_generation_progress_gcs_prefix("bucket", "sundays", "gs://other/progress/"),
            "gs://other/progress",
        )


if __name__ == "__main__":
    unittest.main()
