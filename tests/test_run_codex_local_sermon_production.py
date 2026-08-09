import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from scripts import run_codex_local_sermon_production as mod


class RunCodexLocalSermonProductionTest(unittest.TestCase):
    def automation_args(self, root: Path) -> argparse.Namespace:
        return argparse.Namespace(
            sunday="2026-08-02",
            mode="execute",
            state_file="gs://bucket/state.json",
            work_root=root / "post-live-runs",
            out=root / "latest.json",
            gcs_bucket="bucket",
            gcs_prefix="sundays",
            api_key_secret="projects/p/secrets/openai",
            youtube_api_key_secret="projects/p/secrets/youtube",
            youtube_cookies_secret=None,
            youtube_cookies=None,
            glossary=None,
            notify_sendgrid_secret=None,
            notify_recipients_secret=None,
            notify_sender_secret=None,
            model="gpt-5.6",
            max_turns=8,
            skip_source_refresh=False,
            force_after_complete=False,
        )

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
        self.assertFalse(built.resume_failed_generation)
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

    def test_completed_report_requires_all_authoritative_pass_evidence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            args = mod.make_agent_args(self.automation_args(Path(tempdir)))
            snapshot = {
                "generation": {
                    "status": "completed",
                    "publication": {"status": "pass"},
                },
                "quality": {
                    "readingEdition": {"status": "pass"},
                    "readingPdf": {"status": "pass"},
                    "sermonCompanionPdf": {"status": "pass"},
                },
                "recommendedAction": {"action": "complete"},
                "locations": {
                    "readingPdfGcs": "gs://bucket/final.pdf",
                    "companionPdfGcs": "gs://bucket/companion.pdf",
                },
            }
            with mock.patch.object(
                mod.sermon_production_supervisor,
                "production_snapshot",
                return_value=snapshot,
            ):
                report = mod.completed_production_report(args)

        self.assertEqual("already_complete", report["decision"]["action"])
        self.assertTrue(report["completionLatch"]["skippedSecretAccess"])
        self.assertEqual("skipped", report["sourceRefresh"]["status"])

    def test_main_short_circuits_before_refresh_and_agent(self):
        with tempfile.TemporaryDirectory() as tempdir:
            raw_args = self.automation_args(Path(tempdir))
            completed = {
                "schemaVersion": 1,
                "status": "complete",
                "decision": {"action": "already_complete"},
            }
            with (
                mock.patch.object(mod, "parse_args", return_value=raw_args),
                mock.patch.object(mod, "completed_production_report", return_value=completed),
                mock.patch.object(mod, "refresh_source_state") as refresh,
                mock.patch.object(
                    mod.run_sermon_production_supervisor_agent,
                    "run_agent",
                ) as agent,
            ):
                result = mod.main()

            saved = json.loads(raw_args.out.read_text(encoding="utf-8"))

        self.assertEqual(0, result)
        self.assertEqual("already_complete", saved["decision"]["action"])
        refresh.assert_not_called()
        agent.assert_not_called()

    def test_local_terminal_report_short_circuits_after_current_gcs_readback(self):
        with tempfile.TemporaryDirectory() as tempdir:
            args = mod.make_agent_args(self.automation_args(Path(tempdir)))
            artifact_root = Path(tempdir) / "completed"
            reading_pdf = artifact_root / "reading.pdf"
            companion_pdf = artifact_root / "companion.pdf"
            reading_quality = artifact_root / "reading-quality.json"
            reading_qa = artifact_root / "reading-qa.json"
            companion_qa = artifact_root / "companion-qa.json"
            run_status = artifact_root / "run-status.json"
            generation_report = artifact_root / "generation-report.json"
            artifact_root.mkdir(parents=True)
            reading_pdf.write_bytes(b"%PDF-1.4\n")
            companion_pdf.write_bytes(b"%PDF-1.4\n")
            reading_pdf_sha256 = hashlib.sha256(reading_pdf.read_bytes()).hexdigest()
            generation_report.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "publication": {
                            "status": "pass",
                            "artifacts": [
                                {
                                    "gcsUri": "gs://bucket/final.pdf",
                                    "localSha256": reading_pdf_sha256,
                                    "gcsSha256": reading_pdf_sha256,
                                    "localSize": reading_pdf.stat().st_size,
                                    "gcsSize": reading_pdf.stat().st_size,
                                },
                                {
                                    "gcsUri": "gs://bucket/companion.pdf",
                                    "localSha256": reading_pdf_sha256,
                                    "gcsSha256": reading_pdf_sha256,
                                    "localSize": companion_pdf.stat().st_size,
                                    "gcsSize": companion_pdf.stat().st_size,
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            reading_quality.write_text(
                json.dumps({"status": "pass"}),
                encoding="utf-8",
            )
            reading_qa.write_text(
                json.dumps({"status": "pass"}),
                encoding="utf-8",
            )
            companion_qa.write_text(
                json.dumps({"status": "pass"}),
                encoding="utf-8",
            )
            run_status.write_text(
                json.dumps({"status": "complete"}),
                encoding="utf-8",
            )
            snapshot = {
                "generation": {"status": "completed"},
                "quality": {
                    "readingEdition": {"status": "pass"},
                    "readingPdf": {"status": "pass"},
                    "sermonCompanionPdf": {"status": "pass"},
                },
                "recommendedAction": {"action": "complete"},
                "locations": {
                    "readingPdfLocal": str(reading_pdf),
                    "readingPdfGcs": "gs://bucket/final.pdf",
                    "companionPdfLocal": str(companion_pdf),
                    "companionPdfGcs": "gs://bucket/companion.pdf",
                    "generationReportLocal": str(generation_report),
                    "readingQualityLocal": str(reading_quality),
                    "readingQaLocal": str(reading_qa),
                    "companionQaLocal": str(companion_qa),
                    "runStatusLocal": str(run_status),
                },
            }
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                json.dumps(
                    {
                        "sunday": args.sunday,
                        "status": "complete",
                        "finalSnapshot": snapshot,
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                mod.sermon_production_supervisor,
                "production_snapshot",
            ) as production_snapshot:
                report = mod.completed_production_report(
                    args,
                    gcs_reader=lambda _uri: reading_pdf.read_bytes(),
                )

        self.assertEqual(
            "local_previous_terminal_report",
            report["completionLatch"]["source"],
        )
        production_snapshot.assert_not_called()

    def test_local_terminal_report_rejects_pdf_changed_after_verified_upload(self):
        with tempfile.TemporaryDirectory() as tempdir:
            args = mod.make_agent_args(self.automation_args(Path(tempdir)))
            artifact_root = Path(tempdir) / "completed"
            artifact_root.mkdir(parents=True)
            reading_pdf = artifact_root / "reading.pdf"
            reading_pdf.write_bytes(b"%PDF-1.4\noriginal")
            original_sha256 = hashlib.sha256(reading_pdf.read_bytes()).hexdigest()
            locations = {
                "readingPdfLocal": str(reading_pdf),
                "readingPdfGcs": "gs://bucket/final.pdf",
                "generationReportLocal": str(artifact_root / "generation-report.json"),
                "readingQualityLocal": str(artifact_root / "reading-quality.json"),
                "readingQaLocal": str(artifact_root / "reading-qa.json"),
                "runStatusLocal": str(artifact_root / "run-status.json"),
            }
            Path(locations["generationReportLocal"]).write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "publication": {
                            "status": "pass",
                            "artifacts": [
                                {
                                    "gcsUri": locations["readingPdfGcs"],
                                    "localSha256": original_sha256,
                                    "gcsSha256": original_sha256,
                                    "localSize": reading_pdf.stat().st_size,
                                    "gcsSize": reading_pdf.stat().st_size,
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            for key in ("readingQualityLocal", "readingQaLocal"):
                Path(locations[key]).write_text(
                    json.dumps({"status": "pass"}),
                    encoding="utf-8",
                )
            Path(locations["runStatusLocal"]).write_text(
                json.dumps({"status": "complete"}),
                encoding="utf-8",
            )
            snapshot = {
                "generation": {"status": "completed"},
                "quality": {
                    "readingEdition": {"status": "pass"},
                    "readingPdf": {"status": "pass"},
                },
                "recommendedAction": {"action": "complete"},
                "locations": locations,
            }
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                json.dumps(
                    {
                        "sunday": args.sunday,
                        "status": "complete",
                        "finalSnapshot": snapshot,
                    }
                ),
                encoding="utf-8",
            )
            reading_pdf.write_bytes(b"%PDF-1.4\nlocally repaired")
            with mock.patch.object(
                mod.sermon_production_supervisor,
                "production_snapshot",
                return_value={
                    "generation": {"status": "failed"},
                    "quality": {},
                    "recommendedAction": {"action": "inspect_publication_evidence"},
                    "locations": locations,
                },
            ) as production_snapshot:
                report = mod.completed_production_report(
                    args,
                    gcs_reader=lambda _uri: b"%PDF-1.4\noriginal",
                )

        self.assertIsNone(report)
        production_snapshot.assert_called_once()

    def test_local_terminal_report_rejects_current_gcs_pdf_drift(self):
        with tempfile.TemporaryDirectory() as tempdir:
            args = mod.make_agent_args(self.automation_args(Path(tempdir)))
            artifact_root = Path(tempdir) / "completed"
            artifact_root.mkdir(parents=True)
            reading_pdf = artifact_root / "reading.pdf"
            reading_pdf.write_bytes(b"%PDF-1.4\nverified")
            verified_sha256 = hashlib.sha256(reading_pdf.read_bytes()).hexdigest()
            locations = {
                "readingPdfLocal": str(reading_pdf),
                "readingPdfGcs": "gs://bucket/final.pdf",
                "generationReportLocal": str(artifact_root / "generation-report.json"),
                "readingQualityLocal": str(artifact_root / "reading-quality.json"),
                "readingQaLocal": str(artifact_root / "reading-qa.json"),
                "runStatusLocal": str(artifact_root / "run-status.json"),
            }
            Path(locations["generationReportLocal"]).write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "publication": {
                            "status": "pass",
                            "artifacts": [
                                {
                                    "gcsUri": locations["readingPdfGcs"],
                                    "localSha256": verified_sha256,
                                    "gcsSha256": verified_sha256,
                                    "localSize": reading_pdf.stat().st_size,
                                    "gcsSize": reading_pdf.stat().st_size,
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            for key in ("readingQualityLocal", "readingQaLocal"):
                Path(locations[key]).write_text(
                    json.dumps({"status": "pass"}),
                    encoding="utf-8",
                )
            Path(locations["runStatusLocal"]).write_text(
                json.dumps({"status": "complete"}),
                encoding="utf-8",
            )
            snapshot = {
                "generation": {"status": "completed"},
                "quality": {
                    "readingEdition": {"status": "pass"},
                    "readingPdf": {"status": "pass"},
                },
                "recommendedAction": {"action": "complete"},
                "locations": locations,
            }
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                json.dumps(
                    {
                        "sunday": args.sunday,
                        "status": "complete",
                        "finalSnapshot": snapshot,
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                mod.sermon_production_supervisor,
                "production_snapshot",
                return_value={
                    "generation": {"status": "failed"},
                    "quality": {},
                    "recommendedAction": {"action": "inspect_publication_evidence"},
                    "locations": locations,
                },
            ) as production_snapshot:
                report = mod.completed_production_report(
                    args,
                    gcs_reader=lambda _uri: b"%PDF-1.4\nchanged!",
                )

        self.assertIsNone(report)
        production_snapshot.assert_called_once()

    def test_force_after_complete_bypasses_latch(self):
        with tempfile.TemporaryDirectory() as tempdir:
            args = mod.make_agent_args(self.automation_args(Path(tempdir)))
            args.force_after_complete = True

            report = mod.completed_production_report(args)

        self.assertIsNone(report)

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
