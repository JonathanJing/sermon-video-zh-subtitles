import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import sermon_production_supervisor as mod


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_state(path: Path, sunday: str = "2026-08-02"):
    write_json(
        path,
        {
            "lastSunday": sunday,
            "lastSelectedSource": {
                "kind": "manual-url",
                "service": "manual",
                "state": "manual_available",
                "url": "https://www.youtube.com/watch?v=agentTest123",
            },
            "lastGenerationRequest": {
                "liveUrl": "https://www.youtube.com/watch?v=agentTest123",
            },
        },
    )


class SermonProductionSupervisorTest(unittest.TestCase):
    def make_config(self, root: Path, state: Path, **overrides):
        values = {
            "sunday": "2026-08-02",
            "state_file": str(state),
            "work_root": root,
            "gcs_bucket": None,
            "python_executable": "/test/python",
        }
        values.update(overrides)
        return mod.SupervisorConfig(
            **values,
        )

    def test_snapshot_recommends_timeline_probe_after_source_is_saved(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            snapshot = mod.production_snapshot(self.make_config(root, state))

        self.assertEqual(snapshot["recommendedAction"]["action"], "run_timeline_probe")
        self.assertFalse(snapshot["recommendedAction"]["humanActionRequired"])
        self.assertEqual(snapshot["liveSource"]["host"], "www.youtube.com")

    def test_snapshot_waits_for_matching_sunday_instead_of_using_stale_url(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state, sunday="2026-07-26")
            snapshot = mod.production_snapshot(self.make_config(root, state))

        self.assertEqual(
            snapshot["recommendedAction"]["action"],
            "waiting_for_matching_sunday",
        )

    def test_source_lock_prevents_later_discovery_from_changing_video(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            config = self.make_config(root, state)
            initial = mod.production_snapshot(config)
            lock = mod.ensure_source_lock(config, initial)
            write_json(
                state,
                {
                    "lastSunday": "2026-08-02",
                    "lastSelectedSource": {
                        "kind": "youtube-streams",
                        "service": "sat530",
                        "state": "was_live",
                        "url": "https://www.youtube.com/watch?v=laterSource999",
                    },
                    "lastGenerationRequest": {
                        "liveUrl": "https://www.youtube.com/watch?v=laterSource999",
                    },
                },
            )
            locked = mod.production_snapshot(config)

        self.assertEqual(lock["sourceUrlHash"], mod.stable_hash("https://www.youtube.com/watch?v=agentTest123"))
        self.assertEqual(locked["slug"], "sermon_agentTest123")
        self.assertEqual(locked["sourceLock"]["status"], "locked")

    def test_timeline_review_requires_durable_human_approval(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            config = self.make_config(root, state)
            initial = mod.production_snapshot(config)
            write_json(
                Path(initial["locations"]["timelineReportLocal"]),
                {
                    "status": "requires_operator_review",
                    "suggestedWindow": {
                        "startTimecode": "00:20:30",
                        "endTimecode": "00:58:45",
                    },
                },
            )
            snapshot = mod.production_snapshot(config)

        self.assertEqual(snapshot["recommendedAction"]["action"], "request_window_approval")
        self.assertTrue(snapshot["recommendedAction"]["humanActionRequired"])

    def test_approved_window_is_bound_to_sunday_and_source(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            config = self.make_config(root, state)
            initial = mod.production_snapshot(config)
            write_json(
                Path(initial["locations"]["timelineReportLocal"]),
                {"status": "requires_operator_review"},
            )
            approval = mod.approve_window(
                config,
                start_time="00:20:30",
                end_time="00:58:45.250",
                approved_by="operator@example.test",
                content_scope="sermon_only",
                note="Verified against completed livestream.",
            )
            snapshot = mod.production_snapshot(config)

        self.assertTrue(approval["humanApproval"])
        self.assertEqual(approval["contentScope"], "sermon_only")
        self.assertEqual(approval["startTime"], "00:20:30")
        self.assertEqual(approval["endTime"], "00:58:45.250")
        self.assertEqual(snapshot["recommendedAction"]["action"], "run_reading_pdf_generation")

    def test_unavailable_gcs_is_an_access_issue_not_missing_evidence(self):
        original = mod.read_gcs_text
        try:
            mod.read_gcs_text = lambda _uri: (_ for _ in ()).throw(ConnectionError("offline"))
            with tempfile.TemporaryDirectory() as tempdir:
                root = Path(tempdir)
                state = root / "state.json"
                write_state(state)
                config = mod.SupervisorConfig(
                    sunday="2026-08-02",
                    state_file=str(state),
                    work_root=root,
                    gcs_bucket="test-bucket",
                )
                snapshot = mod.production_snapshot(config)
        finally:
            mod.read_gcs_text = original

        self.assertTrue(snapshot["accessIssues"])
        self.assertEqual(snapshot["recommendedAction"]["action"], "restore_artifact_access")

    def test_supervisor_state_propagates_gcs_access_failures(self):
        original = mod.live_source_monitor.read_state_text
        try:
            mod.live_source_monitor.read_state_text = lambda _uri: (
                _ for _ in ()
            ).throw(ConnectionError("offline"))
            with self.assertRaises(ConnectionError):
                mod.read_supervisor_state("gs://bucket/state.json")
        finally:
            mod.live_source_monitor.read_state_text = original

    def test_gcs_timeline_evidence_precedes_stale_local_cache(self):
        class NotFound(Exception):
            pass

        original = mod.read_gcs_text
        try:
            with tempfile.TemporaryDirectory() as tempdir:
                root = Path(tempdir)
                state = root / "state.json"
                write_state(state)
                config = mod.SupervisorConfig(
                    sunday="2026-08-02",
                    state_file=str(state),
                    work_root=root,
                    gcs_bucket="test-bucket",
                )
                initial = mod.production_snapshot(
                    mod.SupervisorConfig(
                        sunday="2026-08-02",
                        state_file=str(state),
                        work_root=root,
                        gcs_bucket=None,
                    )
                )
                write_json(
                    Path(initial["locations"]["timelineReportLocal"]),
                    {
                        "status": "requires_operator_review",
                        "suggestedWindow": {"startTimecode": "00:10:00"},
                    },
                )

                def read_gcs(uri):
                    if uri.endswith("/timeline/job-report.json"):
                        return json.dumps(
                            {
                                "status": "requires_operator_review",
                                "suggestedWindow": {"startTimecode": "00:20:00"},
                            }
                        )
                    raise NotFound("404")

                mod.read_gcs_text = read_gcs
                snapshot = mod.production_snapshot(config)
        finally:
            mod.read_gcs_text = original

        self.assertEqual(snapshot["timeline"]["suggestedWindow"]["startTimecode"], "00:20:00")

    def test_missing_gcs_evidence_does_not_fall_back_to_local_cache(self):
        class NotFound(Exception):
            pass

        original = mod.read_gcs_text
        try:
            with tempfile.TemporaryDirectory() as tempdir:
                root = Path(tempdir)
                state = root / "state.json"
                write_state(state)
                local_config = self.make_config(root, state)
                initial = mod.production_snapshot(local_config)
                write_json(
                    Path(initial["locations"]["timelineReportLocal"]),
                    {"status": "requires_operator_review"},
                )
                mod.read_gcs_text = lambda _uri: (
                    _ for _ in ()
                ).throw(NotFound("404"))
                snapshot = mod.production_snapshot(
                    mod.SupervisorConfig(
                        sunday="2026-08-02",
                        state_file=str(state),
                        work_root=root,
                        gcs_bucket="test-bucket",
                    )
                )
        finally:
            mod.read_gcs_text = original

        self.assertIsNone(snapshot["timeline"])
        self.assertEqual(snapshot["recommendedAction"]["action"], "run_timeline_probe")

    def test_generation_evidence_publishes_commit_marker_last(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            config = mod.SupervisorConfig(
                sunday="2026-08-02",
                state_file=str(state),
                work_root=root,
                gcs_bucket="test-bucket",
            )
            locations = mod.artifact_locations(config, "agentTest123")
            write_json(Path(locations["runStatusLocal"]), {"status": "blocked"})
            write_json(Path(locations["readingQualityLocal"]), {"status": "fail"})
            writes = []

            mod.publish_generation_evidence(
                locations,
                {"status": "failed", "reason": "quality gate"},
                gcs_writer=lambda uri, text: writes.append((uri, json.loads(text))),
            )

        self.assertEqual(writes[-1][0], locations["generationReportGcs"])
        self.assertEqual(writes[-1][1]["status"], "failed")
        self.assertEqual(writes[0][0], locations["runStatusGcs"])

    def test_failed_generation_is_a_human_inspection_gate(self):
        result = mod.recommend_action(
            sunday="2026-08-02",
            live_url="https://www.youtube.com/watch?v=agentTest123",
            state={"lastSunday": "2026-08-02"},
            timeline_report={"status": "requires_operator_review"},
            approval_valid=True,
            approval_reason=None,
            generation_report={"status": "failed", "reason": "subprocess failed"},
            run_status=None,
            reading_qa=None,
            reading_quality=None,
        )

        self.assertEqual(result["action"], "inspect_generation_failure")
        self.assertTrue(result["humanActionRequired"])

    def test_completed_generation_requires_publication_parity_when_gcs_is_configured(self):
        result = mod.recommend_action(
            sunday="2026-08-02",
            live_url="https://www.youtube.com/watch?v=agentTest123",
            state={"lastSunday": "2026-08-02"},
            timeline_report={"status": "requires_operator_review"},
            approval_valid=True,
            approval_reason=None,
            generation_report={"status": "completed"},
            run_status={"status": "complete"},
            reading_qa={"status": "pass"},
            reading_quality={"status": "pass"},
            publication_required=True,
        )

        self.assertEqual(result["action"], "inspect_publication_evidence")
        self.assertTrue(result["humanActionRequired"])

    def test_structured_generation_failure_uses_run_status_and_quality_evidence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            locations = {
                "runStatusLocal": str(root / "run-status.json"),
                "readingQualityLocal": str(root / "reading-quality.json"),
            }
            write_json(
                Path(locations["runStatusLocal"]),
                {
                    "currentStage": "reviewed",
                    "blocker": {
                        "stage": "reviewed",
                        "reason": "reading_quality_needs_review",
                    },
                },
            )
            write_json(
                Path(locations["readingQualityLocal"]),
                {
                    "status": "needs_revision",
                    "failures": ["unexpected_english_tokens"],
                },
            )

            report = mod.build_generation_failure_report(
                subprocess.CompletedProcess(["generation"], 1, stdout="", stderr=""),
                locations,
            )

        self.assertEqual(2, report["schemaVersion"])
        self.assertEqual("reviewed", report["failure"]["stage"])
        self.assertEqual(
            ["unexpected_english_tokens"],
            report["failure"]["qualityFailures"],
        )
        self.assertTrue(report["failure"]["resumeEligible"])

    def test_timeline_lease_blocks_duplicate_subprocess(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            config = self.make_config(root, state)
            result = mod.run_timeline_probe(
                config,
                runner=runner,
                lease_acquirer=lambda *args, **kwargs: None,
            )
            source_lock_local, _ = mod.source_lock_locations(config)
            source_lock_exists = Path(source_lock_local).exists()

        self.assertEqual(result["status"], "already_running")
        self.assertEqual(calls, [])
        self.assertFalse(source_lock_exists)

    def test_source_lock_fails_closed_if_state_changes_after_snapshot(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            config = self.make_config(root, state)
            snapshot = mod.production_snapshot(config)
            write_state_payload = {
                "lastSunday": "2026-08-02",
                "lastSelectedSource": {
                    "kind": "manual-url",
                    "service": "manual",
                    "state": "manual_available",
                    "url": "https://www.youtube.com/watch?v=laterSource999",
                },
                "lastGenerationRequest": {
                    "liveUrl": "https://www.youtube.com/watch?v=laterSource999",
                },
            }
            write_json(state, write_state_payload)

            with self.assertRaisesRegex(RuntimeError, "source changed"):
                mod.ensure_source_lock(config, snapshot)

    def test_generation_command_uses_approval_not_model_arguments(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            cookies = root / "youtube.cookies.txt"
            cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            write_state(state)
            config = self.make_config(root, state, youtube_cookies_file=cookies)
            initial = mod.production_snapshot(config)
            write_json(
                Path(initial["locations"]["timelineReportLocal"]),
                {"status": "requires_operator_review"},
            )
            mod.approve_window(
                config,
                start_time="00:21:10",
                end_time="00:57:36",
                approved_by="Jony",
                content_scope="sermon_only",
            )
            snapshot = mod.production_snapshot(config)
            approval = json.loads(
                Path(snapshot["locations"]["windowApprovalLocal"]).read_text(encoding="utf-8")
            )
            command = mod.build_generation_command(config, snapshot, approval)

        self.assertEqual(command[command.index("--start-time") + 1], "00:21:10")
        self.assertEqual(command[command.index("--end-time") + 1], "00:57:36")
        self.assertEqual(
            command[command.index("--content-scope") + 1],
            "sermon_only",
        )
        self.assertEqual(
            command[command.index("--approval-evidence") + 1],
            snapshot["locations"]["windowApprovalLocal"],
        )
        self.assertEqual(
            command[command.index("--live-url") + 1],
            "https://www.youtube.com/watch?v=agentTest123",
        )
        self.assertIn("--output-mode", command)
        self.assertEqual(command[command.index("--output-mode") + 1], "reading")
        self.assertEqual(command[command.index("--youtube-cookies") + 1], str(cookies))
        redacted = mod.redact_command(command)
        self.assertEqual(
            redacted[redacted.index("--live-url") + 1],
            "REDACTED_LIVE_SOURCE",
        )
        self.assertEqual(
            redacted[redacted.index("--youtube-cookies") + 1],
            "REDACTED_SECRET_RESOURCE",
        )

    def test_explicit_resume_archives_failed_report_and_reuses_valid_approval(self):
        class Lease:
            pass

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            config = self.make_config(root, state)
            initial = mod.production_snapshot(config)
            write_json(
                Path(initial["locations"]["timelineReportLocal"]),
                {"status": "requires_operator_review"},
            )
            mod.approve_window(
                config,
                start_time="00:21:10",
                end_time="00:57:36",
                approved_by="Jony",
                content_scope="sermon_only",
            )
            failed_snapshot = mod.production_snapshot(config)
            write_json(
                Path(failed_snapshot["locations"]["generationReportLocal"]),
                {"schemaVersion": 2, "status": "failed", "reason": "quality gate"},
            )

            def runner(command, **_kwargs):
                report_path = Path(command[command.index("--out") + 1])
                write_json(
                    report_path,
                    {
                        "schemaVersion": 2,
                        "status": "completed",
                        "publication": {"status": "not_configured"},
                    },
                )
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            result = mod.resume_failed_reading_pdf_generation(
                config,
                runner=runner,
                lease_acquirer=lambda *_args, **_kwargs: Lease(),
                lease_releaser=lambda _lease: None,
            )

            archived = Path(result["archivedFailure"]["local"])

        self.assertEqual("completed", result["status"])
        self.assertTrue(archived.name.startswith("agent-generation-report.failed-"))

    def test_execute_generation_materializes_authoritative_approval_locally(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            config = self.make_config(root, state)
            initial = mod.production_snapshot(config)
            write_json(
                Path(initial["locations"]["timelineReportLocal"]),
                {"status": "requires_operator_review"},
            )
            approval = mod.approve_window(
                config,
                start_time="00:21:10",
                end_time="00:57:36",
                approved_by="Jony",
                content_scope="sermon_only",
            )
            snapshot = mod.production_snapshot(config)
            approval_path = Path(snapshot["locations"]["windowApprovalLocal"])
            approval_path.unlink()

            def runner(command, **_kwargs):
                materialized = json.loads(approval_path.read_text(encoding="utf-8"))
                self.assertEqual(materialized, approval)
                report_path = Path(command[command.index("--out") + 1])
                write_json(
                    report_path,
                    {
                        "schemaVersion": 2,
                        "status": "completed",
                        "publication": {"status": "not_configured"},
                    },
                )
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            result = mod.execute_reading_pdf_generation(
                config,
                snapshot,
                approval,
                runner=runner,
            )

        self.assertEqual(result["status"], "completed")

    def test_timeline_command_passes_local_access_and_notification_configuration(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            cookies = root / "youtube.cookies.txt"
            cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            write_state(state)
            config = mod.SupervisorConfig(
                sunday="2026-08-02",
                state_file=str(state),
                work_root=root,
                gcs_bucket=None,
                youtube_cookies_file=cookies,
                notify_sendgrid_secret="projects/p/secrets/sendgrid",
                notify_recipients_secret="projects/p/secrets/recipients",
                notify_sender_secret="projects/p/secrets/sender",
            )
            snapshot = mod.production_snapshot(config)
            command = mod.build_timeline_command(config, snapshot)

        self.assertEqual(command[command.index("--youtube-cookies") + 1], str(cookies))
        self.assertIn("--notify-sendgrid-secret", command)
        self.assertIn("--notify-recipients-secret", command)
        self.assertIn("--notify-sender-secret", command)
        redacted = mod.redact_command(command)
        self.assertEqual(
            redacted[redacted.index("--youtube-cookies") + 1],
            "REDACTED_SECRET_RESOURCE",
        )

    def test_generation_tool_blocks_without_approval(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            config = self.make_config(root, state)
            initial = mod.production_snapshot(config)
            write_json(
                Path(initial["locations"]["timelineReportLocal"]),
                {"status": "requires_operator_review"},
            )
            result = mod.run_reading_pdf_generation(config, runner=runner)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(calls, [])

    def test_replacing_timeline_report_invalidates_old_approval(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            config = self.make_config(root, state)
            initial = mod.production_snapshot(config)
            timeline_path = Path(initial["locations"]["timelineReportLocal"])
            write_json(
                timeline_path,
                {
                    "status": "requires_operator_review",
                    "suggestedWindow": {"startTimecode": "00:20:30", "endTimecode": "00:58:45"},
                },
            )
            mod.approve_window(
                config,
                start_time="00:21:10",
                end_time="00:57:36",
                approved_by="Jony",
                content_scope="sermon_only",
            )
            write_json(
                timeline_path,
                {
                    "status": "requires_operator_review",
                    "suggestedWindow": {"startTimecode": "00:22:00", "endTimecode": "00:59:00"},
                },
            )
            snapshot = mod.production_snapshot(config)

        self.assertEqual(snapshot["recommendedAction"]["action"], "request_window_approval")
        self.assertIn("current timeline report", snapshot["windowApproval"]["reason"])

    def test_completed_generation_requires_both_quality_reports(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            config = self.make_config(root, state)
            snapshot = mod.production_snapshot(config)
            locations = snapshot["locations"]
            write_json(
                Path(locations["timelineReportLocal"]),
                {
                    "status": "requires_operator_review",
                    "suggestedWindow": {
                        "startTimecode": "00:20:30",
                        "endTimecode": "00:58:45",
                    },
                },
            )
            mod.approve_window(
                config,
                start_time="00:21:10",
                end_time="00:57:36",
                approved_by="Jony",
                content_scope="sermon_only",
            )
            write_json(Path(locations["generationReportLocal"]), {"status": "completed"})
            write_json(Path(locations["readingQaLocal"]), {"status": "pass"})
            write_json(Path(locations["readingQualityLocal"]), {"status": "pass"})
            completed = mod.production_snapshot(config)

        self.assertEqual(completed["recommendedAction"]["action"], "complete")

    def test_completed_generation_does_not_bypass_invalidated_window_approval(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            config = self.make_config(root, state)
            snapshot = mod.production_snapshot(config)
            locations = snapshot["locations"]
            timeline_path = Path(locations["timelineReportLocal"])
            write_json(
                timeline_path,
                {
                    "status": "requires_operator_review",
                    "suggestedWindow": {
                        "startTimecode": "00:20:30",
                        "endTimecode": "00:58:45",
                    },
                },
            )
            mod.approve_window(
                config,
                start_time="00:21:10",
                end_time="00:57:36",
                approved_by="Jony",
                content_scope="sermon_only",
            )
            write_json(Path(locations["generationReportLocal"]), {"status": "completed"})
            write_json(Path(locations["readingQaLocal"]), {"status": "pass"})
            write_json(Path(locations["readingQualityLocal"]), {"status": "pass"})
            write_json(
                timeline_path,
                {
                    "status": "requires_operator_review",
                    "suggestedWindow": {
                        "startTimecode": "00:22:00",
                        "endTimecode": "00:59:00",
                    },
                },
            )
            completed = mod.production_snapshot(config)

        self.assertEqual(
            completed["recommendedAction"]["action"],
            "request_window_approval",
        )
        self.assertTrue(completed["recommendedAction"]["humanActionRequired"])
        self.assertIn("current timeline report", completed["recommendedAction"]["reason"])

    def test_timecode_validation(self):
        self.assertEqual(mod.parse_timecode("01:02:03.500"), 3723.5)
        self.assertEqual(mod.canonical_timecode(3723.5), "01:02:03.500")
        with self.assertRaises(ValueError):
            mod.parse_timecode("1:2:3")


if __name__ == "__main__":
    unittest.main()
