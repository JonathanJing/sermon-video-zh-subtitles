import argparse
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "configure_live_source_scheduler.py"
SPEC = importlib.util.spec_from_file_location("configure_live_source_scheduler", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ConfigureLiveSourceSchedulerTest(unittest.TestCase):
    def make_args(self, **overrides):
        values = {
            "project": "ai-for-god",
            "location": "us-west1",
            "job_id": "sermon-live-source-discovery",
            "service_url": "https://caption.example.test/",
            "action": "discover-source",
            "sunday": "current",
            "schedule": "55 9 * * SUN",
            "timezone": "America/Los_Angeles",
            "service": "auto",
            "operator_alert_time": "09:58",
            "expected_title": None,
            "manual_url": [],
            "include_candidates": False,
            "no_auto_generate": False,
            "slug": None,
            "input": None,
            "chunk_seconds": None,
            "timeline_model": None,
            "start_time": None,
            "end_time": None,
            "plan_only": False,
            "attempt_deadline": "180s",
            "internal_task_token_env": "INTERNAL_TASK_TOKEN",
            "apply": False,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_builds_current_sunday_discovery_job_payload(self):
        plan = mod.build_scheduler_plan(
            self.make_args(expected_title="The Cure", manual_url=["https://audio.example.test/live"]),
            internal_task_token="task-token-value",
        )

        self.assertEqual(
            plan.endpoint,
            "https://caption.example.test/api/admin/sundays/current/discover-source",
        )
        self.assertEqual(plan.payload["triggerSource"], "cloud-scheduler")
        self.assertEqual(plan.payload["service"], "auto")
        self.assertTrue(plan.payload["autoGenerate"])
        self.assertEqual(plan.payload["expectedTitle"], "The Cure")
        self.assertEqual(plan.payload["manualUrls"], ["https://audio.example.test/live"])
        self.assertIn("X-Internal-Task-Token=task-token-value", " ".join(plan.update_command))
        self.assertIn(json.dumps(plan.payload, ensure_ascii=False, separators=(",", ":")), plan.create_command)

    def test_builds_saturday_530_discovery_job_payload(self):
        plan = mod.build_scheduler_plan(
            self.make_args(
                job_id="sermon-sat-530-source-discovery",
                sunday="upcoming",
                schedule="*/2 17 * * SAT",
                service="sat530",
                operator_alert_time="17:50",
                no_auto_generate=True,
            ),
            internal_task_token="task-token-value",
        )

        self.assertEqual(
            plan.endpoint,
            "https://caption.example.test/api/admin/sundays/upcoming/discover-source",
        )
        self.assertEqual(plan.payload["service"], "sat530")
        self.assertEqual(plan.payload["operatorAlertTime"], "17:50")
        self.assertFalse(plan.payload["autoGenerate"])
        self.assertIn("*/2 17 * * SAT", plan.create_command)

    def test_builds_single_saturday_auto_discovery_job_payload(self):
        plan = mod.build_scheduler_plan(
            self.make_args(
                job_id="sermon-sat-auto-source-discovery",
                sunday="upcoming",
                schedule="*/5 8-17 * * SAT",
                service="sat-auto",
                operator_alert_time="17:50",
                no_auto_generate=True,
            ),
            internal_task_token="task-token-value",
        )

        self.assertEqual(plan.payload["service"], "sat-auto")
        self.assertEqual(plan.payload["operatorAlertTime"], "17:50")
        self.assertFalse(plan.payload["autoGenerate"])
        self.assertIn("*/5 8-17 * * SAT", plan.create_command)

    def test_sanitized_report_redacts_internal_task_token(self):
        plan = mod.build_scheduler_plan(self.make_args(), internal_task_token="test-redaction-value")
        report = mod.sanitized_report(plan, {"status": "dry-run"})
        text = json.dumps(report)

        self.assertEqual(report["status"], "dry-run")
        self.assertFalse(report["authMaterialIncluded"])
        self.assertNotIn("test-redaction-value", text)
        self.assertIn("X-Internal-Task-Token=REDACTED", text)

    def test_builds_post_live_subtitles_job_payload(self):
        plan = mod.build_scheduler_plan(
            self.make_args(
                job_id="sermon-sat-post-live-subtitles",
                action="post-live-subtitles",
                sunday="upcoming",
                schedule="*/10 18-23 * * SAT",
                slug="mariners_MEZHufeQBjc",
                start_time="00:22:10",
                end_time="00:55:36",
            ),
            internal_task_token="task-token-value",
        )

        self.assertEqual(
            plan.endpoint,
            "https://caption.example.test/api/admin/sundays/upcoming/post-live-subtitles",
        )
        self.assertEqual(plan.payload["triggerSource"], "cloud-scheduler")
        self.assertEqual(plan.payload["mode"], "generate-reviewed")
        self.assertEqual(plan.payload["slug"], "mariners_MEZHufeQBjc")
        self.assertEqual(plan.payload["startTime"], "00:22:10")
        self.assertEqual(plan.payload["endTime"], "00:55:36")
        self.assertNotIn("autoGenerate", plan.payload)
        self.assertIn("*/10 18-23 * * SAT", plan.create_command)

    def test_builds_post_live_timeline_probe_job_payload(self):
        plan = mod.build_scheduler_plan(
            self.make_args(
                job_id="sermon-sat-post-live-timeline",
                action="post-live-timeline",
                sunday="upcoming",
                schedule="*/10 18-23 * * SAT",
                slug="0D6yZW4_uEA",
                input="/tmp/sermon-post-live-subtitles/2026-07-05/0D6yZW4_uEA/download/source_audio.m4a",
                chunk_seconds=120.0,
                timeline_model="gpt-4o-transcribe",
            ),
            internal_task_token="task-token-value",
        )

        self.assertEqual(
            plan.endpoint,
            "https://caption.example.test/api/admin/sundays/upcoming/post-live-subtitles",
        )
        self.assertEqual(plan.payload["triggerSource"], "cloud-scheduler")
        self.assertEqual(plan.payload["mode"], "timeline-probe")
        self.assertEqual(plan.payload["slug"], "0D6yZW4_uEA")
        self.assertEqual(plan.payload["input"], "/tmp/sermon-post-live-subtitles/2026-07-05/0D6yZW4_uEA/download/source_audio.m4a")
        self.assertEqual(plan.payload["chunkSeconds"], 120.0)
        self.assertEqual(plan.payload["timelineModel"], "gpt-4o-transcribe")
        self.assertNotIn("startTime", plan.payload)
        self.assertNotIn("endTime", plan.payload)

    def test_ensure_scheduler_job_updates_when_job_exists(self):
        calls = []

        def fake_runner(command, capture_output, text):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        plan = mod.build_scheduler_plan(self.make_args(), internal_task_token="token")
        result = mod.ensure_scheduler_job(plan, runner=fake_runner)

        self.assertEqual(result["status"], "updated")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][3], "update")

    def test_ensure_scheduler_job_creates_after_missing_update(self):
        calls = []

        def fake_runner(command, capture_output, text):
            calls.append(command)
            return subprocess.CompletedProcess(command, 1 if len(calls) == 1 else 0, "", "missing")

        plan = mod.build_scheduler_plan(self.make_args(), internal_task_token="token")
        result = mod.ensure_scheduler_job(plan, runner=fake_runner)

        self.assertEqual(result["status"], "created")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][3], "update")
        self.assertEqual(calls[1][3], "create")


if __name__ == "__main__":
    unittest.main()
