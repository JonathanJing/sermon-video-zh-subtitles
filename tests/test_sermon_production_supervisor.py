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
    def make_config(self, root: Path, state: Path):
        return mod.SupervisorConfig(
            sunday="2026-08-02",
            state_file=str(state),
            work_root=root,
            gcs_bucket=None,
            python_executable="/test/python",
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
                note="Verified against completed livestream.",
            )
            snapshot = mod.production_snapshot(config)

        self.assertTrue(approval["humanApproval"])
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

    def test_timeline_lease_blocks_duplicate_subprocess(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            result = mod.run_timeline_probe(
                self.make_config(root, state),
                runner=runner,
                lease_acquirer=lambda *args, **kwargs: None,
            )

        self.assertEqual(result["status"], "already_running")
        self.assertEqual(calls, [])

    def test_generation_command_uses_approval_not_model_arguments(self):
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
            )
            snapshot = mod.production_snapshot(config)
            approval = json.loads(
                Path(snapshot["locations"]["windowApprovalLocal"]).read_text(encoding="utf-8")
            )
            command = mod.build_generation_command(config, snapshot, approval)

        self.assertEqual(command[command.index("--start-time") + 1], "00:21:10")
        self.assertEqual(command[command.index("--end-time") + 1], "00:57:36")
        self.assertIn("--output-mode", command)
        self.assertEqual(command[command.index("--output-mode") + 1], "reading")

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
            write_json(Path(locations["generationReportLocal"]), {"status": "completed"})
            write_json(Path(locations["readingQaLocal"]), {"status": "pass"})
            write_json(Path(locations["readingQualityLocal"]), {"status": "pass"})
            completed = mod.production_snapshot(config)

        self.assertEqual(completed["recommendedAction"]["action"], "complete")

    def test_timecode_validation(self):
        self.assertEqual(mod.parse_timecode("01:02:03.500"), 3723.5)
        self.assertEqual(mod.canonical_timecode(3723.5), "01:02:03.500")
        with self.assertRaises(ValueError):
            mod.parse_timecode("1:2:3")


if __name__ == "__main__":
    unittest.main()
