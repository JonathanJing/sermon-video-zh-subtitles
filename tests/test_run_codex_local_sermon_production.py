import argparse
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts import run_codex_local_sermon_production as mod


class RunCodexLocalSermonProductionTest(unittest.TestCase):
    def test_script_help_runs_from_repo_root(self):
        completed = subprocess.run(
            [sys.executable, str(mod.REPO_ROOT / "scripts" / "run_codex_local_sermon_production.py"), "--help"],
            cwd=mod.REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("local Codex automation", completed.stdout)
        self.assertIn("environment", completed.stdout)

    def test_defaults_to_persistent_repo_artifacts_and_current_upcoming_sunday(self):
        args = argparse.Namespace(
            sunday="2026-08-02",
            mode="execute",
            state_file=mod.DEFAULT_STATE_URI,
            work_root=mod.REPO_ROOT / "artifacts" / "post-live-runs",
            out=None,
            gcs_bucket=mod.DEFAULT_BUCKET,
            gcs_prefix="sundays",
            api_key_secret=mod.DEFAULT_OPENAI_SECRET,
            youtube_api_key_secret=mod.DEFAULT_YOUTUBE_API_SECRET,
            youtube_cookies_secret=None,
            youtube_cookies=None,
            notify_sendgrid_secret=mod.DEFAULT_SENDGRID_SECRET,
            notify_recipients_secret=mod.DEFAULT_RECIPIENTS_SECRET,
            notify_sender_secret=mod.DEFAULT_SENDER_SECRET,
            model="gpt-5.6",
            max_turns=8,
            skip_source_refresh=False,
        )

        built = mod.make_agent_args(args)

        self.assertEqual(built.mode, "execute")
        self.assertFalse(built.skip_source_refresh)
        self.assertEqual(built.sunday, "2026-08-02")
        self.assertEqual(
            built.out,
            mod.REPO_ROOT
            / "artifacts"
            / "sermon-production-supervisor"
            / "2026-08-02"
            / "latest.json",
        )
        self.assertEqual(
            built.work_root,
            mod.REPO_ROOT / "artifacts" / "post-live-runs",
        )

    def test_rejects_two_cookie_sources(self):
        args = argparse.Namespace(
            sunday="2026-08-02",
            mode="execute",
            state_file=mod.DEFAULT_STATE_URI,
            work_root=Path("artifacts/post-live-runs"),
            out=None,
            gcs_bucket=mod.DEFAULT_BUCKET,
            gcs_prefix="sundays",
            api_key_secret=mod.DEFAULT_OPENAI_SECRET,
            youtube_api_key_secret=mod.DEFAULT_YOUTUBE_API_SECRET,
            youtube_cookies_secret="projects/p/secrets/cookies",
            youtube_cookies=Path("/tmp/cookies.txt"),
            notify_sendgrid_secret=mod.DEFAULT_SENDGRID_SECRET,
            notify_recipients_secret=mod.DEFAULT_RECIPIENTS_SECRET,
            notify_sender_secret=mod.DEFAULT_SENDER_SECRET,
            model="gpt-5.6",
            max_turns=8,
            skip_source_refresh=False,
        )

        with self.assertRaises(SystemExit):
            mod.make_agent_args(args)

    def test_local_source_refresh_writes_same_gcs_contract(self):
        writes = []
        monitor_services = []
        original_run_monitor = mod.live_source_monitor.run_monitor
        original_read_state = mod.live_source_monitor.read_state
        original_write_state = mod.live_source_monitor.write_state
        original_build_notification = mod.live_source_monitor.build_notification
        original_discovery_service = mod.discovery_service_for_run
        try:
            mod.live_source_monitor.read_state = lambda _path: {}
            mod.discovery_service_for_run = lambda _sunday: "sat-auto"

            def run_monitor(monitor_args):
                monitor_services.append(monitor_args.service)
                return {
                    "schemaVersion": 1,
                    "status": "source_detected",
                    "sunday": "2026-08-02",
                    "selectedSource": {
                        "kind": "youtube-streams",
                        "service": "sat530",
                        "state": "upcoming",
                        "url": "https://www.youtube.com/watch?v=agentTest123",
                    },
                    "generationRequest": {
                        "sunday": "2026-08-02",
                        "liveUrl": "https://www.youtube.com/watch?v=agentTest123",
                    },
                    "operatorAlert": False,
                }

            mod.live_source_monitor.run_monitor = run_monitor
            mod.live_source_monitor.build_notification = lambda _report, _previous: {
                "shouldNotify": False
            }
            mod.live_source_monitor.write_state = (
                lambda path, report, previous, notification: writes.append(
                    (path, report, previous, notification)
                )
            )
            with tempfile.TemporaryDirectory() as tempdir:
                args = argparse.Namespace(
                    sunday="2026-08-02",
                    state_file="gs://bucket/state.json",
                    youtube_api_key_secret=mod.DEFAULT_YOUTUBE_API_SECRET,
                    notify_sendgrid_secret=None,
                    notify_recipients_secret=None,
                    notify_sender_secret=None,
                )
                original_root = mod.REPO_ROOT
                mod.REPO_ROOT = Path(tempdir)
                try:
                    result = mod.refresh_source_state(args)
                    saved = json.loads(
                        (
                            Path(tempdir)
                            / "artifacts"
                            / "live-source-monitor"
                            / "2026-08-02"
                            / "local-refresh.json"
                        ).read_text(encoding="utf-8")
                    )
                finally:
                    mod.REPO_ROOT = original_root
        finally:
            mod.live_source_monitor.run_monitor = original_run_monitor
            mod.live_source_monitor.read_state = original_read_state
            mod.live_source_monitor.write_state = original_write_state
            mod.live_source_monitor.build_notification = original_build_notification
            mod.discovery_service_for_run = original_discovery_service

        self.assertEqual(result["status"], "source_detected")
        self.assertEqual(monitor_services, ["sat-auto"])
        self.assertEqual(writes[0][0], "gs://bucket/state.json")
        self.assertEqual(saved["generationRequest"]["sunday"], "2026-08-02")

    def test_discovery_service_switches_to_sunday_auto_on_run_day(self):
        self.assertEqual(
            mod.discovery_service_for_run(
                "2026-08-02",
                local_date=date(2026, 8, 1),
            ),
            "sat-auto",
        )
        self.assertEqual(
            mod.discovery_service_for_run(
                "2026-08-02",
                local_date=date(2026, 8, 2),
            ),
            "auto",
        )

    def test_existing_same_sunday_source_is_preserved_without_discovery(self):
        original_read_state = mod.live_source_monitor.read_state
        original_run_monitor = mod.live_source_monitor.run_monitor
        try:
            mod.live_source_monitor.read_state = lambda _path: {
                "lastSunday": "2026-08-02",
                "lastSelectedSource": {
                    "service": "sat530",
                    "url": "https://www.youtube.com/watch?v=agentTest123",
                },
                "lastGenerationRequest": {
                    "sunday": "2026-08-02",
                    "liveUrl": "https://www.youtube.com/watch?v=agentTest123",
                },
            }

            def unexpected_monitor(_args):
                raise AssertionError("source discovery should not run")

            mod.live_source_monitor.run_monitor = unexpected_monitor
            args = argparse.Namespace(
                sunday="2026-08-02",
                state_file="gs://bucket/state.json",
                youtube_api_key_secret=mod.DEFAULT_YOUTUBE_API_SECRET,
                notify_sendgrid_secret=None,
                notify_recipients_secret=None,
                notify_sender_secret=None,
            )

            result = mod.refresh_source_state(args)
        finally:
            mod.live_source_monitor.read_state = original_read_state
            mod.live_source_monitor.run_monitor = original_run_monitor

        self.assertEqual(result["status"], "existing_source_preserved")
        self.assertEqual(result["selectedSource"]["service"], "sat530")


if __name__ == "__main__":
    unittest.main()
