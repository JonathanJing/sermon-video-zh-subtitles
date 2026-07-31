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
        writes = {}

        def writer(uri, text):
            writes[uri] = json.loads(text)

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
                gcs_writer=writer,
            )
            snapshot = mod.production_snapshot(
                mod.SupervisorConfig(
                    sunday=config.sunday,
                    state_file=config.state_file,
                    work_root=config.work_root,
                    gcs_bucket=None,
                )
            )

        self.assertTrue(approval["humanApproval"])
        self.assertEqual(approval["startTime"], "00:20:30")
        self.assertEqual(approval["endTime"], "00:58:45.250")
        self.assertEqual(snapshot["recommendedAction"]["action"], "run_reading_pdf_generation")
        self.assertEqual(len(writes), 1)

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
