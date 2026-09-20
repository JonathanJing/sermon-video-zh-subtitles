import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from scripts import run_saturday_harness as harness


class SaturdayHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "bridge.json"
        self.config.write_text(json.dumps({"schemaVersion": "sermon-saturday-dubbing-bridge-v1",
            "weeks": {"2026-09-06": {}}, "voiceRuns": {}}))
        self.supervisor = self.root / "supervisor.json"
        self.bridge_path = self.root / "bridge-report.json"
        self.argv = ["--sunday", "2026-09-06", "--state-file", str(self.root / "state.json"),
            "--work-root", str(self.root / "runs"), "--supervisor-report", str(self.supervisor),
            "--bridge-config", str(self.config), "--gcs-bucket", "existing-bucket",
            "--api-key-secret", "projects/test/secrets/openai/versions/latest",
            "--youtube-api-key-secret", "projects/test/secrets/youtube/versions/latest"]

    def bridge(self, route="live_archive"):
        return {"schemaVersion": "sermon-saturday-dubbing-bridge-report-v1", "week": "2026-09-06",
            "config": {"sha256": hashlib.sha256(self.config.read_bytes()).hexdigest()},
            "selectedRoute": route, "status": "waiting_conversation_review", "routes": {
                "same_video": {"sourceId": "same-source", "status": "waiting_source"},
                "live_archive": {"sourceId": "archive-source", "status": "waiting_conversation_review",
                    "candidateEvidence": {"timingReportSha256": "abc"}}}, "nextActions": []}

    def write_pdf(self, status="blocked"):
        self.supervisor.write_text(json.dumps({"sunday": "2026-09-06", "status": status,
            "finalSnapshot": {"sunday": "2026-09-06", "slug": "sermon_archive-source",
                "recommendedAction": {"action": "wait_for_source"}}}))

    def test_execute_passes_bridge_config_to_producer_without_mutating_environment(self):
        before = os.environ.get("SERMON_DUBBING_CONFIG")
        def child(command, **kwargs):
            if "run_codex_local_sermon_production.py" in command[1]:
                self.assertEqual(kwargs["env"]["SERMON_DUBBING_CONFIG"], str(self.config.resolve()))
                self.write_pdf()
                return subprocess.CompletedProcess(command, 2)
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(self.bridge()))
        harness.run(harness.parse_args(self.argv + ["--mode", "execute"]), runner=child)
        self.assertEqual(os.environ.get("SERMON_DUBBING_CONFIG"), before)

    def test_default_inspect_has_no_subprocess_or_writes(self):
        runner = Mock(side_effect=AssertionError("read-only called subprocess"))
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        report = harness.run(harness.parse_args(self.argv), runner=runner)
        self.assertEqual(report["status"], "inspection_only")
        self.assertEqual(report["executions"], [])
        runner.assert_not_called()
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_shadow_marks_saved_complete_unverified(self):
        self.write_pdf("complete")
        self.bridge_path.write_text(json.dumps(self.bridge()))
        runner = Mock()
        report = harness.run(harness.parse_args(self.argv + ["--mode", "shadow", "--bridge-report", str(self.bridge_path)]), runner=runner)
        self.assertFalse(report["workflowComplete"])
        self.assertEqual(report["stages"]["pdf"]["evidenceFreshness"], "saved_snapshot_unverified")
        routes = report["stages"]["audioCandidate"]["routes"]
        self.assertNotEqual(routes["same_video"]["sourceId"], routes["live_archive"]["sourceId"])
        self.assertEqual(routes["live_archive"]["humanReview"]["status"], "not_verified_by_harness")
        runner.assert_not_called()

    def test_waiting_pdf_still_allows_bridge_fallback_after_fresh_snapshot(self):
        calls = []
        def runner(command, **kwargs):
            calls.append(command)
            if len(calls) == 1:
                self.write_pdf()
                return subprocess.CompletedProcess(command, 2)
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(self.bridge()))
        report = harness.run(harness.parse_args(self.argv + ["--mode", "execute"]), runner=runner)
        self.assertIn("run_codex_local_sermon_production.py", calls[0][1])
        self.assertIn("continue_saturday_dubbing.py", calls[1][1])
        self.assertEqual(report["stages"]["audioCandidate"]["selectedRoute"], "live_archive")
        self.assertEqual(report["stages"]["pdf"]["evidenceFreshness"], "current_supervisor_validation")
        self.assertFalse(report["workflowComplete"])
        self.assertFalse(report["audioPublicationAttempted"])

    def test_stale_pdf_report_does_not_launch_bridge(self):
        self.write_pdf()
        runner = Mock(return_value=subprocess.CompletedProcess([], 1))
        report = harness.run(harness.parse_args(self.argv + ["--mode", "execute"]), runner=runner)
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(report["status"], "needs_attention")

    def test_existing_pdf_contract_and_notification_boundary(self):
        args = harness.parse_args(self.argv)
        pdf, bridge = harness.commands(args)
        self.assertEqual(pdf[pdf.index("--gcs-bucket") + 1], "existing-bucket")
        self.assertNotIn("--skip-source-refresh", pdf)
        self.assertNotIn("--approve-window", pdf)
        for flag in ("--notify-sendgrid-secret", "--notify-recipients-secret", "--notify-sender-secret"):
            self.assertEqual(pdf[pdf.index(flag) + 1], "")
        self.assertIn("--execute", bridge)
        args.skip_source_refresh = True
        self.assertIn("--skip-source-refresh", harness.commands(args)[0])

    def test_wrong_week_and_wrong_config_are_rejected_without_mutation(self):
        runner = Mock()
        self.supervisor.write_text(json.dumps({"sunday": "2026-09-13"}))
        with self.assertRaisesRegex(ValueError, "another Sunday"):
            harness.run(harness.parse_args(self.argv), runner=runner)
        self.supervisor.unlink()
        bridge = self.bridge()
        bridge["config"]["sha256"] = "changed"
        self.bridge_path.write_text(json.dumps(bridge))
        with self.assertRaisesRegex(ValueError, "different configuration"):
            harness.run(harness.parse_args(self.argv + ["--bridge-report", str(self.bridge_path)]), runner=runner)
        runner.assert_not_called()

    def test_explicit_week_config_required(self):
        with self.assertRaisesRegex(ValueError, "explicitly contain"):
            harness.run(harness.parse_args(self.argv + ["--sunday", "2026-09-13"]), runner=Mock())

    def test_inspection_cannot_write_output(self):
        out = self.root / "new.json"
        with self.assertRaisesRegex(ValueError, "read-only"):
            harness.run(harness.parse_args(self.argv + ["--out", str(out)]), runner=Mock())
        self.assertFalse(out.exists())

    def test_bridge_failure_is_reported_without_claiming_completion(self):
        def runner(command, **kwargs):
            if "--state-file" in command:
                self.write_pdf()
                return subprocess.CompletedProcess(command, 2)
            return subprocess.CompletedProcess(command, 2, stdout="")
        report = harness.run(harness.parse_args(self.argv + ["--mode", "execute"]), runner=runner)
        self.assertEqual(report["status"], "needs_attention")
        self.assertFalse(report["workflowComplete"])

    def test_report_cannot_overwrite_bridge_configuration(self):
        runner = Mock()
        with self.assertRaisesRegex(ValueError, "must not overwrite"):
            harness.run(harness.parse_args(self.argv + ["--mode", "execute", "--out", str(self.config)]), runner=runner)
        runner.assert_not_called()

    def test_malformed_snapshot_fails_before_starting_any_child(self):
        self.supervisor.write_text(json.dumps({"sunday": "2026-09-06", "finalSnapshot": "not-an-object"}))
        runner = Mock()
        with self.assertRaisesRegex(ValueError, "Expected object"):
            harness.run(harness.parse_args(self.argv + ["--mode", "execute"]), runner=runner)
        runner.assert_not_called()

    def test_pdf_timeout_is_reported_and_does_not_start_bridge(self):
        runner = Mock(side_effect=subprocess.TimeoutExpired("pdf", 1))
        report = harness.run(harness.parse_args(self.argv + ["--mode", "execute", "--pdf-timeout", "1"]), runner=runner)
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(runner.call_args.kwargs["timeout"], 1)
        self.assertEqual(report["executions"][0]["status"], "timed_out")
        self.assertEqual(report["status"], "needs_attention")

    def test_bridge_timeout_keeps_remote_uncertainty_visible(self):
        def runner(command, **kwargs):
            if "--state-file" in command:
                self.write_pdf()
                return subprocess.CompletedProcess(command, 2)
            self.assertEqual(kwargs["timeout"], 12)
            raise subprocess.TimeoutExpired(command, 12)
        report = harness.run(harness.parse_args(self.argv + ["--mode", "execute", "--bridge-timeout", "12"]), runner=runner)
        self.assertEqual(report["executions"][-1]["status"], "timed_out")
        self.assertIn("reconciliation", report["errors"][0])
        self.assertFalse(report["workflowComplete"])

    def test_nonfinite_timeout_rejected_without_starting_child(self):
        runner = Mock()
        with self.assertRaisesRegex(ValueError, "positive and finite"):
            harness.run(harness.parse_args(self.argv + ["--mode", "execute", "--pdf-timeout", "nan"]), runner=runner)
        runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
