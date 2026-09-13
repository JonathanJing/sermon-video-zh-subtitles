"""Optional Temporal contract/adapter tests: importing this file needs no SDK."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.sermon_temporal import adapter, fixtures, worker_service
from scripts.sermon_temporal.contracts import REQUEST_SCHEMA, Request
from scripts.sermon_temporal.local_io import TEMPORAL_ROOT, file_sha


class TemporalContractTests(unittest.TestCase):
    def request(self, **changes):
        result = Request(REQUEST_SCHEMA, "fixture", "2026-09-06", "fixture:source", "/fixture/config.json", "a" * 64)
        return replace(result, **changes)

    def test_execution_permission_or_location_changes_do_not_evade_duplicate_identity(self):
        original = self.request()
        original.validate()
        self.assertEqual(original.workflow_id(), self.request(allow_execute=True).workflow_id())
        self.assertEqual(original.workflow_id(), self.request(config_path="/another/config.json").workflow_id())
        self.assertNotEqual(original.workflow_id(), self.request(profile="production").workflow_id())
        self.assertNotEqual(original.task_queue(), self.request(profile="production").task_queue())

    def test_unknown_schema_relative_paths_and_nonfinite_timeouts_fail(self):
        for changes in ({"schema_version": "future"}, {"config_path": "relative"},
                        {"activity_timeout_seconds": 400, "heartbeat_timeout_seconds": 300},
                        {"activity_timeout_seconds": float("nan")}, {"allow_execute": "yes"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.request(**changes).validate()

    def test_fixture_authoring_refuses_production_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "under artifacts/temporal"):
                fixtures.initialize(Path(tmp) / "outside")

    def test_worker_stop_refuses_pid_identity_change_before_signal(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(worker_service, "TEMPORAL_ROOT", Path(tmp)), \
                patch.object(worker_service, "status", return_value={"ownedProcessAlive": True, "pid": 123,
                                                                      "process_identity": "original"}), \
                patch.object(worker_service, "process_identity", return_value="changed"), \
                patch.object(worker_service.os, "killpg") as kill:
            with self.assertRaisesRegex(ValueError, "identity changed"):
                worker_service.stop()
            kill.assert_not_called()

    def test_worker_stop_does_not_signal_stale_saved_pid(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(worker_service, "TEMPORAL_ROOT", Path(tmp)), \
                patch.object(worker_service, "status", return_value={"ownedProcessAlive": False, "pid": 123}), \
                patch.object(worker_service.os, "killpg") as kill:
            self.assertFalse(worker_service.stop()["stoppedByThisCall"])
            kill.assert_not_called()

    def test_existing_job_binding_uses_audio_bytes_and_job_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            audio = work / "source.m4a"
            audio.write_bytes(b"source fixture")
            job = {"sourceId": "actual-source", "inputs": {"sourceAudio": {"path": str(audio), "sha256": file_sha(audio)}}}
            (work / "job.json").write_text(json.dumps(job))
            bridge = {"routes": {"live_archive": {"status": "ready_to_resume", "work": str(work), "sourceId": "actual-source"}}}
            binding = adapter.route_bindings(bridge, None)["live_archive"]
            self.assertEqual(binding["sourceAudioSha256"], file_sha(audio))
            self.assertEqual(binding["jobSha256"], file_sha(work / "job.json"))
            audio.write_bytes(b"changed actual source")
            with self.assertRaisesRegex(ValueError, "source changed"):
                adapter.route_bindings(bridge, None)

    def test_fixture_uses_original_window_validator_and_rejects_changed_timeline(self):
        TEMPORAL_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMPORAL_ROOT) as tmp:
            path = fixtures.initialize(Path(tmp), name="unit-test")
            config = json.loads(path.read_text())
            request = self.request(source_key=config["sourceKey"], config_path=str(path), config_sha256=file_sha(path))
            config = adapter.load_config(request)
            state_dir = Path(tmp) / "state"
            state_dir.mkdir()
            missing = adapter.fixture_observation(request, config, state_dir)
            self.assertFalse(missing.approval_valid)
            fixtures.write_approval(path)
            valid = adapter.fixture_observation(request, config, state_dir)
            self.assertTrue(valid.approval_valid)
            self.assertEqual(missing.source_binding, valid.source_binding)
            timeline = Path(tmp) / "timeline.json"
            data = json.loads(timeline.read_text()); data["revision"] = 2
            timeline.write_text(json.dumps(data))
            changed = adapter.fixture_observation(request, config, state_dir)
            self.assertFalse(changed.approval_valid)
            self.assertNotEqual(valid.source_binding, changed.source_binding)


if __name__ == "__main__":
    unittest.main()
