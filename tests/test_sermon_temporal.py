"""Optional Temporal contract/adapter tests: importing this file needs no SDK."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.sermon_temporal import adapter, client, fixtures, worker_service
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


class TemporalBackendBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bridge = self.root / "bridge.json"
        self.bridge.write_text('{}')
        self.path = self.root / "config.json"
        self.config = {
            "schemaVersion": "sermon-temporal-operator-v1", "sunday": "2026-09-06",
            "sourceKey": "source:original", "expectedPdfSlug": "original",
            "expectedSources": {"live_archive": "original"}, "bridgeConfigSha256": file_sha(self.bridge),
            "harnessArgv": ["--sunday", "2026-09-06", "--state-file", str(self.root / "state.json"),
                "--work-root", str(self.root), "--supervisor-report", str(self.root / "report.json"),
                "--bridge-config", str(self.bridge), "--gcs-bucket", "fixture-bucket",
                "--api-key-secret", "fixture-api-reference", "--youtube-api-key-secret", "fixture-youtube-reference",
                "--skip-source-refresh"]}

    def write_config(self):
        self.path.write_text(json.dumps(self.config))

    def persisted_request(self):
        self.write_config()
        # Exercise the real client construction and persisted Activity payload.
        request = client.build_request(self.path, profile="production")
        return Request(**json.loads(json.dumps(asdict(request))))

    def backend_command(self, request, default):
        from scripts import run_saturday_harness as harness
        original_parser = harness.parse_args
        # Change the parser's implicit backend while retaining real argv parsing.
        def changed_parser(argv):
            return original_parser(["--agent-backend", default, *argv])
        with patch.object(harness, "parse_args", side_effect=changed_parser):
            args = adapter.production_args(adapter.load_config(request))
        command, _ = harness.commands(args)
        return command[command.index("--agent-backend") + 1]

    def test_legacy_persisted_request_replay_retains_agents_api_across_parser_defaults(self):
        request = self.persisted_request()
        original_bytes, original_id = self.path.read_bytes(), request.workflow_id()
        for default in ("codex-cli", "sdk"):
            with self.subTest(default=default):
                self.assertEqual(self.backend_command(request, default), "agents-api")
        self.assertEqual(self.path.read_bytes(), original_bytes)
        self.assertEqual(file_sha(self.path), request.config_sha256)
        self.assertEqual(request.workflow_id(), original_id)
        self.assertNotIn("--agent-backend", adapter.load_config(request)["harnessArgv"])

    def test_new_explicit_cli_is_stable_through_persisted_request_and_command(self):
        self.config["schemaVersion"] = "sermon-temporal-operator-v2"
        self.config["harnessArgv"].append("--agent-backend=codex-cli")
        request = self.persisted_request()
        for default in ("agents-api", "sdk"):
            with self.subTest(default=default):
                self.assertEqual(self.backend_command(request, default), "codex-cli")
        self.assertEqual(file_sha(self.path), request.config_sha256)

    def test_v1_explicit_backend_is_not_replaced_by_legacy_default(self):
        original_argv = list(self.config["harnessArgv"])
        for backend in ("codex-cli", "agents-api", "sdk"):
            with self.subTest(backend=backend):
                self.config["harnessArgv"] = original_argv + ["--agent-backend", backend]
                request = self.persisted_request()
                self.assertEqual(self.backend_command(request, "codex-cli"), backend)

    def test_v2_missing_or_ambiguous_pin_fails_client_and_activity_load(self):
        self.config["schemaVersion"] = "sermon-temporal-operator-v2"
        original_argv = list(self.config["harnessArgv"])
        for pin in ([], ["--agent-backend", "codex-cli", "--agent-backend=agents-api"],
                    ["--agent-b", "codex-cli"], ["--agent-backend", "agents-api"],
                    ["--agent-backend", "sdk"]):
            with self.subTest(pin=pin):
                self.config["harnessArgv"] = original_argv + pin
                self.write_config()
                with self.assertRaises(ValueError):
                    client.build_request(self.path, profile="production")
                # A crafted/persisted request cannot bypass creation validation.
                request = Request(REQUEST_SCHEMA, "production", "2026-09-06", "source:original",
                                  str(self.path), file_sha(self.path))
                with self.assertRaises(ValueError):
                    adapter.load_config(request)

    def test_pin_migration_changes_identity_and_old_request_cannot_adopt_bytes(self):
        legacy = self.persisted_request()
        self.config["schemaVersion"] = "sermon-temporal-operator-v2"
        self.config["harnessArgv"] += ["--agent-backend", "codex-cli"]
        current = self.persisted_request()
        self.assertNotEqual(legacy.workflow_id(), current.workflow_id())
        with self.assertRaisesRegex(ValueError, "configuration changed"):
            adapter.load_config(legacy)
        self.assertEqual(self.backend_command(current, "agents-api"), "codex-cli")

    def test_operator_v2_cannot_enter_fixture_profile(self):
        self.config["schemaVersion"] = "sermon-temporal-operator-v2"
        self.config["harnessArgv"] += ["--agent-backend", "codex-cli"]
        self.write_config()
        with self.assertRaisesRegex(ValueError, "profile"):
            client.build_request(self.path, profile="fixture")


if __name__ == "__main__":
    unittest.main()
