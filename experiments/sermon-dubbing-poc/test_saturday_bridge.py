"""Frozen Saturday bridge fixtures; no model, SSH, cloud or production writes."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from continue_saturday_dubbing import CANDIDATE_FILES, INPUTS, SCHEMA, continue_saturday, inspect_same_video, source_lock
from poc import sha256, write_json
from weekly_dubbing import prepare


class SaturdayBridgeTests(unittest.TestCase):
    week = "2026-09-06"
    source = "fixture-src"

    def fixture(self, root):
        run = root / "artifacts/post-live-runs" / self.week / ("sermon_" + self.source)
        run.mkdir(parents=True)
        paths = {key: run / relative for key, relative in INPUTS.items()}
        for key, path in paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            if key in {"readingPdf", "companionPdf", "sourceAudio"}:
                path.write_bytes(b"frozen fixture bytes " + key.encode())
            else:
                write_json(path, {})
        timeline = {"status": "requires_operator_review", "input": "frozen source timeline"}
        write_json(paths["timeline"], timeline)
        # Use the production canonical digest rather than a raw-file hash.
        from scripts.sermon_production_supervisor import json_digest, stable_hash
        approval = {"schemaVersion": 2, "status": "approved", "humanApproval": True,
            "sunday": self.week, "sourceUrlHash": stable_hash("https://www.youtube.com/watch?v=" + self.source),
            "timelineReportSha256": json_digest(timeline), "approvedBy": "fixture human", "approvedAt": "2026-09-05T00:00:00Z",
            "startTime": "00:00:10", "endTime": "00:00:20", "contentScope": "sermon_only"}
        write_json(paths["windowApproval"], approval)
        original = root / "original.m4a"
        original.write_bytes(b"original source fixture")
        write_json(paths["clipReceipt"], {"source": {"sha256": sha256(original)}, "startSeconds": 10, "endSeconds": 20})
        write_json(paths["summary"], {"source": str(original), "sermonStartSeconds": 10, "sermonEndSeconds": 20})
        write_json(paths["reading"], [{"id": 0, "en": "Bring your questions to God.", "zh": "把你的问题带到神面前。"}])
        for key in ["readingQuality", "readingPdfQa", "companionPdfQa"]:
            write_json(paths[key], {"status": "pass"})
        write_json(paths["outline"], {"status": "ready", "sermonDate": self.week, "speaker": None})
        write_json(run / "agent-generation-report.json", {"status": "failed"})
        write_json(run / "run-status.json", {"status": "running"})
        voice = root / "voice"
        voice.mkdir()
        write_json(voice / "research-inputs.json", {"speaker": "Eric Geiger", "speakerKey": "eric_pilot"})
        write_json(voice / "training-report.json", {"status": "training_smoke_completed", "speaker": "Eric Geiger", "speakerKey": "eric_pilot",
            "inputManifestSha256": sha256(voice / "research-inputs.json"), "checkpointSha256": "a" * 64,
            "baseModel": "fixture-base", "baseRevision": "fixture-revision"})
        config = {"schemaVersion": SCHEMA, "outputRoot": str(root / "bridge-output"),
            "authorizationStatement": "Fixture existing explicit user authorization for Chinese dubbing.",
            "scopeReference": "fixture-only user instruction; not real approval",
            "voiceRuns": {"Eric Geiger": {"voiceRun": str(voice), "remoteCheckpoint": "/home/achillesjing/dgx-spark-benchmark/results/sermon-fixture/checkpoint"}},
            "weeks": {self.week: {"sourceId": self.source, "speaker": "Eric Geiger", "title": "已核实主题", "scripture": "诗篇 1 篇", "sameVideo": {"source": None}}}}
        config_path = root / "config.json"
        write_json(config_path, config)
        report_path = root / "supervisor.json"
        write_json(report_path, {"sunday": self.week, "status": "blocked", "finalSnapshot": {"sunday": self.week, "slug": run.name,
            "locations": {"runRoot": str(run)}, "recommendedAction": {"action": "inspect_generation_failure"}}})
        return config_path, report_path, config, run

    def inspect(self, config_path, report_path, **kwargs):
        return continue_saturday(config_path, self.week, report_path,
            media_probe=lambda _: {"durationSeconds": 10, "streams": [{"codec_type": "audio"}]}, **kwargs)

    def snapshot(self, root):
        return {str(p.relative_to(root)): sha256(p) for p in root.rglob("*") if p.is_file()}

    def preparer(self, *args):
        from unittest.mock import patch
        with patch("weekly_dubbing.probe", return_value={"durationSeconds": 10}):
            return prepare(*args)

    def write_candidate(self, work):
        for name in CANDIDATE_FILES:
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == ".json":
                write_json(path, {"fixture": True})
            else:
                path.write_bytes(b"candidate fixture")

    def test_inspect_is_no_mutation_and_primary_wait_does_not_block_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, sup, _, _ = self.fixture(root)
            before = self.snapshot(root)
            report = self.inspect(cfg, sup)
            self.assertEqual(report["status"], "ready_to_prepare")
            self.assertEqual(report["routes"]["same_video"]["status"], "waiting_source")
            self.assertEqual(report["selectedRoute"], "live_archive")
            self.assertEqual(self.snapshot(root), before)
            self.assertFalse(report["humanApprovalWritten"])

    def test_configured_python_symlinks_preserve_both_virtual_environment_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, sup, config, run = self.fixture(root)
            python = root / ".venv/bin/python"
            mlx_python = root / "mlx-env/bin/python"
            for executable in [python, mlx_python]:
                executable.parent.mkdir(parents=True)
                executable.symlink_to(sys.executable)
                self.assertTrue(executable.is_file())
                self.assertNotEqual(executable.absolute(), executable.resolve())
            config["pythonExecutable"] = str(python)
            config["mlxPython"] = str(mlx_python.relative_to(root))
            source_alias = root / "source-alias"
            source_alias.symlink_to(run, target_is_directory=True)
            config["weeks"][self.week]["liveArchive"] = {"run": str(source_alias)}
            write_json(cfg, config)
            before = self.snapshot(root)
            report = self.inspect(cfg, sup, root=root)
            self.assertEqual(report["status"], "ready_to_prepare")
            route = report["routes"]["live_archive"]
            command = route["plannedRunnerCommand"]
            self.assertEqual(command[0], str(python.absolute()))
            self.assertEqual(command[command.index("--mlx-python") + 1], str(mlx_python.absolute()))
            self.assertEqual(route["nextActions"][0]["commands"][0][0], str(python.absolute()))
            self.assertEqual(route["run"], str(run.resolve()))
            self.assertEqual(self.snapshot(root), before)

    def test_default_python_retains_sys_executable_virtual_environment_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, sup, _, _ = self.fixture(root)
            python = root / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            python.symlink_to(sys.executable)
            self.assertTrue(python.is_file())
            with patch("continue_saturday_dubbing.sys.executable", str(python)):
                report = self.inspect(cfg, sup, root=root)
            route = report["routes"]["live_archive"]
            self.assertEqual(route["plannedRunnerCommand"][0], str(python.absolute()))
            self.assertEqual(route["nextActions"][0]["commands"][0][0], str(python.absolute()))

    def test_wrong_week_source_report_is_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, sup, _, _ = self.fixture(Path(tmp))
            data = json.loads(sup.read_text())
            data["sunday"] = "2026-09-13"
            write_json(sup, data)
            self.assertEqual(self.inspect(cfg, sup)["status"], "waiting_evidence_repair")

    def test_waiting_source_boundary_metadata_and_voice_are_explicit(self):
        for state in ["source", "boundary", "metadata", "voice"]:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                cfg, sup, config, run = self.fixture(Path(tmp))
                if state == "source":
                    sup.unlink()
                elif state == "boundary":
                    (run / "operator-window-approval.json").unlink()
                elif state == "metadata":
                    config["weeks"][self.week]["speaker"] = None
                else:
                    config["voiceRuns"] = {}
                write_json(cfg, config)
                self.assertEqual(self.inspect(cfg, sup)["status"], "waiting_" + state)

    def test_machine_boundary_record_cannot_become_existing_human_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, sup, _, run = self.fixture(Path(tmp))
            path = run / "operator-window-approval.json"
            approval = json.loads(path.read_text())
            approval.update(humanApproval=False, model="gpt-6-astra", machineApproved=True)
            write_json(path, approval)
            self.assertEqual(self.inspect(cfg, sup)["status"], "waiting_boundary")
            self.assertFalse(json.loads(path.read_text())["humanApproval"])

    def test_changed_source_or_wrong_registered_speaker_stops_before_runner(self):
        for change in ["source", "speaker"]:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                cfg, sup, _, run = self.fixture(Path(tmp))
                if change == "source":
                    (Path(tmp) / "original.m4a").write_bytes(b"changed original")
                else:
                    voice = Path(tmp) / "voice/training-report.json"
                    data = json.loads(voice.read_text()); data["speaker"] = "Christine Caine"
                    write_json(voice, data)
                runner = Mock()
                report = self.inspect(cfg, sup, execute=True, runner=runner)
                self.assertEqual(report["status"], "waiting_evidence_repair")
                runner.assert_not_called()

    def test_execute_creates_bound_job_and_candidate_once_without_upstream_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, sup, config, run = self.fixture(root)
            before = self.snapshot(run)
            def runner(command, **kwargs):
                work = Path(command[command.index("--work") + 1])
                self.write_candidate(work)
                return SimpleNamespace(returncode=0)
            runner = Mock(side_effect=runner)
            validator = Mock(side_effect=lambda work: {"jobSha256": sha256(work / "job.json"), "mp3Sha256": sha256(work / "audio/zh-natural.mp3")})
            report = self.inspect(cfg, sup, execute=True, preparer=self.preparer, runner=runner, validator=validator)
            self.assertEqual(report["status"], "waiting_conversation_review")
            work = Path(report["routes"]["live_archive"]["work"])
            job = json.loads((work / "job.json").read_text())
            self.assertFalse(job["inheritedReview"]["generationComplete"])
            auth = json.loads(Path(job["inputs"]["authorization"]["path"]).read_text())
            self.assertEqual(auth["sources"], [{"sourceId": self.source, "sha256": sha256(run / "pipeline/source_clip.m4a")}])
            self.assertEqual(auth["statement"], config["authorizationStatement"])
            self.assertEqual(self.snapshot(run), before)
            job_hash = sha256(work / "job.json")
            again = self.inspect(cfg, sup, execute=True, preparer=Mock(side_effect=AssertionError("must reuse")), runner=runner, validator=validator)
            self.assertEqual(again["status"], "waiting_conversation_review")
            self.assertEqual(sha256(work / "job.json"), job_hash)
            self.assertEqual(runner.call_count, 1)

    def test_source_lock_prevents_duplicate_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, sup, config, _ = self.fixture(root)
            runner = Mock()
            with source_lock(Path(config["outputRoot"]), self.week, self.source) as acquired:
                self.assertTrue(acquired)
                report = self.inspect(cfg, sup, execute=True, runner=runner)
            self.assertEqual(report["status"], "waiting_active_dubbing_run")
            runner.assert_not_called()

    def test_active_saturday_lease_waits_without_starting_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, sup, _, run = self.fixture(Path(tmp))
            write_json(run / "leases/generation.json", {"status": "active", "expiresAt": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()})
            self.assertEqual(self.inspect(cfg, sup)["status"], "waiting_saturday_run")

    def test_existing_partial_job_resumes_and_complete_stale_reports_do_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, sup, _, _ = self.fixture(root)
            stopped = self.inspect(cfg, sup, execute=True, preparer=self.preparer, runner=Mock(return_value=SimpleNamespace(returncode=1)))
            work = Path(stopped["routes"]["live_archive"]["work"])
            self.assertTrue((work / "job.json").exists())
            self.assertEqual(self.inspect(cfg, sup)["status"], "ready_to_resume")
            self.write_candidate(work)
            runner = Mock()
            report = self.inspect(cfg, sup, execute=True, runner=runner, validator=Mock(side_effect=ValueError("stale ASR report")))
            self.assertEqual(report["status"], "waiting_evidence_repair")
            runner.assert_not_called()

    def test_runner_zero_exit_cannot_replace_current_candidate_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, sup, _, _ = self.fixture(Path(tmp))
            report = self.inspect(cfg, sup, execute=True, preparer=self.preparer, runner=Mock(return_value=SimpleNamespace(returncode=0)),
                validator=Mock(side_effect=ValueError("incomplete evidence")))
            self.assertEqual(report["status"], "waiting_evidence_repair")
            self.assertFalse(report["published"])

    def test_explicit_existing_work_reuses_candidate_outside_new_output_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, sup, config, _ = self.fixture(root)
            def render(command, **kwargs):
                self.write_candidate(Path(command[command.index("--work") + 1]))
                return SimpleNamespace(returncode=0)
            validator = lambda work: {"jobSha256": sha256(work / "job.json")}
            initial = self.inspect(cfg, sup, execute=True, preparer=self.preparer, runner=render, validator=validator)
            old_work = initial["routes"]["live_archive"]["work"]
            config["outputRoot"] = str(root / "new-bridge-root")
            config["weeks"][self.week]["liveArchive"] = {"existingWork": old_work}
            write_json(cfg, config)
            runner = Mock(side_effect=AssertionError("existing candidate must not regenerate"))
            resumed = self.inspect(cfg, sup, execute=True, runner=runner, validator=validator)
            self.assertEqual(resumed["status"], "waiting_conversation_review")
            self.assertEqual(resumed["routes"]["live_archive"]["work"], old_work)
            self.assertFalse((root / "new-bridge-root").exists())

    def test_partial_stale_cache_is_not_reported_as_safely_resumable(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, sup, _, _ = self.fixture(Path(tmp))
            initial = self.inspect(cfg, sup, execute=True, preparer=self.preparer, runner=Mock(return_value=SimpleNamespace(returncode=1)))
            work = Path(initial["routes"]["live_archive"]["work"])
            write_json(work / "render/identity.json", {"jobSha256": "another job"})
            runner = Mock()
            report = self.inspect(cfg, sup, execute=True, runner=runner)
            self.assertEqual(report["status"], "waiting_evidence_repair")
            runner.assert_not_called()

    def test_primary_window_requires_explicit_same_version_sermon_only_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "sermon.mp4"
            media.write_bytes(b"video fixture")
            source = {"week": self.week, "path": str(media), "sha256": sha256(media), "durationSeconds": 10,
                "sameVersionConfirmed": True, "sermonOnly": True, "confirmationReference": "fixture explicit source confirmation"}
            probe = lambda _: {"durationSeconds": 10, "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}
            report = inspect_same_video(self.week, {"source": source}, media_probe=probe)
            self.assertEqual(report["status"], "waiting_same_video_adapter")
            self.assertEqual(report["proposedWindow"]["startSeconds"], 0)
            for field in ["sameVersionConfirmed", "sermonOnly"]:
                changed = {**source, field: False}
                self.assertEqual(inspect_same_video(self.week, {"source": changed}, media_probe=probe)["status"], "waiting_source_confirmation")
            self.assertFalse((Path(tmp) / "operator-window-approval.json").exists())


if __name__ == "__main__":
    unittest.main()
