"""Execution recovery regressions: fake SSH, real cache validators, no models/network."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run_weekly_dubbing as runner
from poc import sha256, write_json
from scripts import sermon_accounting as accounting
from scripts.sermon_execution_harness import RemoteOutcomeUnknown, WorkAlreadyRunning, work_lock
from test_resume_integrity import candidate_fixture, snapshot
import test_weekly_accounting as weekly_accounting
from weekly_dubbing import read


class ExecutionRecoveryTests(unittest.TestCase):
    def setUp(self):
        transport = patch("spark_transport.bridge", return_value="")
        transport.start()
        self.addCleanup(transport.stop)
        identity = patch.object(accounting, "execution_identity", return_value={"gitCommit": None})
        identity.start()
        self.addCleanup(identity.stop)

    def fixture(self, folder):
        # Reuse its fixtures without inheriting/re-running its accounting suite.
        return weekly_accounting.WeeklyAccountingTests().fixture(folder)

    def test_ssh_timeout_or_disconnect_persists_unknown_without_repair_or_download(self):
        for kind in ("timeout", "disconnect"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f:
                def fail_model(argv, **kwargs):
                    result = f.command(argv, **kwargs)
                    if os.environ.get("SERMON_ACCOUNTING_STAGE") == "render":
                        if kind == "timeout":
                            raise subprocess.TimeoutExpired(argv, 1)
                        raise subprocess.CalledProcessError(255, argv)
                    return result

                f.process.side_effect = fail_model
                with self.assertRaises(RemoteOutcomeUnknown):
                    runner.main()
                state = read(f.work / "accounting/harness/latest.json")
                remote = read(f.work / "accounting/harness/remote-attempt.json")
                self.assertEqual(state["status"], "waiting_remote_reconciliation")
                self.assertEqual(state["errorType"], "RemoteOutcomeUnknown")
                self.assertEqual(remote["status"], "outcome_unknown")
                self.assertEqual(remote["jobSha256"], sha256(f.work / "job.json"))
                self.assertEqual(remote["attemptId"], state["attemptId"])
                stages = [row["stage"] for row in f.commands]
                self.assertEqual(stages.count("render"), 1)
                self.assertNotIn("render_recovery", stages)
                self.assertNotIn("transfer_download", stages)
                self.assertFalse(any("/work/retry_weekly_unit.py" in row["argv"][-1] for row in f.commands))
                f.mocks["assemble"].assert_not_called()
                f.mocks["validate_candidate"].assert_not_called()
                self.assertFalse((f.work / "workflow-receipt.json").exists())

    def test_existing_remote_container_blocks_upload_and_model_launch(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f:
            def running_container(argv, **kwargs):
                result = f.command(argv, **kwargs)
                if argv[-1].startswith("docker ps "):
                    return subprocess.CompletedProcess(argv, 0, stdout="running\n", stderr="")
                return result

            f.process.side_effect = running_container
            with self.assertRaises(RemoteOutcomeUnknown):
                runner.main()
            self.assertEqual(len(f.commands), 1)
            self.assertEqual(f.commands[0]["argv"][0], "ssh")
            self.assertTrue(f.commands[0]["argv"][-1].startswith("docker ps "))
            self.assertEqual(read(f.work / "accounting/harness/latest.json")["status"], "waiting_remote_reconciliation")
            self.assertFalse((f.work / "accounting/harness/remote-attempt.json").exists())
            f.mocks["assemble"].assert_not_called()
            f.mocks["validate_render"].assert_not_called()

    def test_canonical_work_lock_blocks_before_validation_or_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f:
            alias = Path(tmp) / "same-job-alias"
            alias.symlink_to(f.work, target_is_directory=True)
            with work_lock(alias), self.assertRaises(WorkAlreadyRunning):
                runner.run(SimpleNamespace(), f.work)
            f.process.assert_not_called()
            for validator in ("validated_job", "validate_cached_stages", "validate_render", "validate_candidate"):
                f.mocks[validator].assert_not_called()
            self.assertFalse((f.work / "accounting/harness/latest.json").exists())

    def test_reconciled_complete_remote_output_skips_another_model_attempt(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f:
            write_json(f.work / "accounting/harness/remote-attempt.json", {
                "schemaVersion": 1, "status": "outcome_unknown", "jobSha256": sha256(f.work / "job.json")})

            def completed_output(work, job, fetch):
                # The accounting fixture's render is deliberately synthetic.
                # Actual quarantine/merge validation is tested below separately.
                write_json(work / "render/report.json", f.mocks["validate_render"].return_value)

            with patch.object(runner, "reconcile_remote", side_effect=completed_output) as reconcile:
                runner.main()
            reconcile.assert_called_once()
            self.assertEqual(read(f.work / "accounting/harness/remote-attempt.json")["status"], "output_reconciled")
            self.assertFalse(any("/work/render_weekly_audio.py" in row["argv"][-1] or "/work/retry_weekly_unit.py" in row["argv"][-1] for row in f.commands))
            self.assertNotIn("transfer_download", [row["stage"] for row in f.commands])
            self.assertTrue((f.work / "workflow-receipt.json").exists())


class RemoteCacheReconciliationTests(unittest.TestCase):
    def fixture(self, root):
        work = root / "work"
        work.mkdir()
        candidate_fixture(work)
        remote = root / "fake-spark-render"
        shutil.copytree(work / "render", remote)
        job = read(work / "job.json")
        fetched = []

        def fetch(quarantine):
            fetched.append(quarantine)
            shutil.copytree(remote, quarantine / "render")

        return work, remote, job, fetch, fetched

    def remove_completed_local_stage(self, work):
        for name in ("unit-0001.wav", "unit-0001.json", "chinese.raw.wav", "report.json"):
            (work / "render" / name).unlink()

    def test_only_missing_files_are_imported_and_existing_units_are_not_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, remote, job, fetch, fetched = self.fixture(Path(tmp))
            self.remove_completed_local_stage(work)
            retained = work / "render/unit-0000.wav"
            old_stat = retained.stat()
            old_digest = sha256(retained)
            with patch.object(runner, "process_run", side_effect=AssertionError("no model/SSH from merge")):
                runner.reconcile_remote(work, job, fetch)
            self.assertEqual(sha256(retained), old_digest)
            self.assertEqual((retained.stat().st_ino, retained.stat().st_mtime_ns), (old_stat.st_ino, old_stat.st_mtime_ns))
            self.assertEqual(sha256(work / "render/unit-0001.wav"), sha256(remote / "unit-0001.wav"))
            self.assertEqual(runner.validate_render(work, job)["sha256"], sha256(work / "render/chinese.raw.wav"))
            self.assertEqual(len(fetched), 1)
            self.assertTrue(fetched[0].is_relative_to((work / "accounting/remote-recovery").resolve()))
            self.assertEqual(fetched[0].stat().st_mode & 0o777, 0o700)

    def test_local_collision_rejects_the_entire_merge_and_preserves_both_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, remote, job, fetch, fetched = self.fixture(Path(tmp))
            self.remove_completed_local_stage(work)
            (work / "render/unit-0000.wav").write_bytes(b"different local audio; must be preserved")
            before = snapshot(work)
            with self.assertRaisesRegex(ValueError, "Local and remote output differ"):
                runner.reconcile_remote(work, job, fetch)
            self.assertEqual(snapshot(work), before)
            self.assertFalse((work / "render/unit-0001.wav").exists(), "merge wrote a later file despite collision")
            self.assertEqual(sha256(fetched[0] / "render/unit-0000.wav"), sha256(remote / "unit-0000.wav"))

    def test_remote_wav_without_receipt_is_rejected_before_local_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, remote, job, fetch, fetched = self.fixture(Path(tmp))
            self.remove_completed_local_stage(work)
            (remote / "unit-0001.json").unlink()
            before = snapshot(work)
            with self.assertRaises((OSError, ValueError)):
                runner.reconcile_remote(work, job, fetch)
            self.assertEqual(snapshot(work), before)
            self.assertTrue((fetched[0] / "render/unit-0001.wav").exists())

    def test_interrupted_quarantine_fetch_does_not_modify_local_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, remote, job, _, _ = self.fixture(Path(tmp))
            self.remove_completed_local_stage(work)
            before = snapshot(work)

            def broken_fetch(quarantine):
                (quarantine / "render").mkdir()
                shutil.copyfile(remote / "unit-0001.wav", quarantine / "render/unit-0001.wav")
                raise subprocess.TimeoutExpired("fixture-scp", 1)

            with self.assertRaises(subprocess.TimeoutExpired):
                runner.reconcile_remote(work, job, broken_fetch)
            self.assertEqual(snapshot(work), before)
            quarantines = list((work / "accounting/remote-recovery").iterdir())
            self.assertEqual(len(quarantines), 1)
            self.assertTrue((quarantines[0] / "render/unit-0001.wav").exists())

    def test_imported_repair_receipt_keeps_its_referenced_diagnostic_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, remote, job, fetch, _ = self.fixture(Path(tmp))
            diagnostic = remote / "diagnostics/failed-unit-0001.wav"
            diagnostic.parent.mkdir()
            diagnostic.write_bytes(b"failed waveform preserved for review")
            write_json(diagnostic.with_suffix(".failure.json"), {"unit": 1, "reason": "duration_or_signal"})
            receipt = read(remote / "unit-0001.json")
            receipt["generationOverride"] = {"kind": "isolated_unit_retry", "seed": 142,
                "failedAudioSha256": sha256(diagnostic), "failedAudioPreserved": str(diagnostic.relative_to(remote)), "humanReview": "pending"}
            write_json(remote / "unit-0001.json", receipt)
            self.remove_completed_local_stage(work)
            runner.reconcile_remote(work, job, fetch)
            copied = read(work / "render/unit-0001.json")
            self.assertEqual(copied, receipt)
            referenced = work / "render" / copied["generationOverride"]["failedAudioPreserved"]
            self.assertTrue(referenced.is_file(), "recovered receipt lost the failed audio it references")
            self.assertEqual(sha256(referenced), copied["generationOverride"]["failedAudioSha256"])
            self.assertEqual(runner.validate_render(work, job)["status"], "complete_candidate_render")


if __name__ == "__main__":
    unittest.main()
