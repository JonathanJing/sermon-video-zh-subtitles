"""Interrupt a verified local import; no SSH, model, or real media work."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from poc import sha256
import run_weekly_dubbing as runner
from scripts import sermon_accounting as accounting
from test_resume_integrity import candidate_fixture
from weekly_dubbing import read


class RemoteImportResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.work = self.root / "work"
        self.work.mkdir()
        candidate_fixture(self.work)
        self.remote = self.root / "remote-fixture"
        shutil.copytree(self.work / "render", self.remote)
        self.job = read(self.work / "job.json")
        for name in ("unit-0001.wav", "unit-0001.json", "chinese.raw.wav", "report.json"):
            (self.work / "render" / name).unlink()
        self.fetches = []
        identity = patch.object(accounting, "execution_identity", return_value={"gitCommit": None})
        identity.start()
        self.addCleanup(identity.stop)

    def fetch(self, folder):
        self.fetches.append(folder)
        shutil.copytree(self.remote, folder / "render")

    def interrupt_import(self, *, partial_temporary=False):
        copy = shutil.copyfile
        def interrupted(source, destination, *args, **kwargs):
            destination = Path(destination)
            if destination == self.work / "render/unit-0001.json.recovery-tmp":
                if partial_temporary:
                    destination.write_bytes(b"interrupted derived temporary")
                raise KeyboardInterrupt("injected after WAV, before receipt promotion")
            return copy(source, destination, *args, **kwargs)
        with patch.object(runner.shutil, "copyfile", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                runner.reconcile_remote(self.work, self.job, self.fetch)
        self.assertTrue(runner.pending_import_path(self.work).is_file())
        self.assertTrue((self.work / "render/unit-0001.wav").exists())
        self.assertFalse((self.work / "render/unit-0001.json").exists())

    def run_main(self):
        argv = ["run_weekly_dubbing.py", "--work", str(self.work), "--remote-checkpoint",
            runner.REMOTE_ROOT + "/sermon-fixture/checkpoint"]
        with patch.object(sys, "argv", argv), patch("builtins.print"):
            runner.main()

    def snapshot(self):
        return {str(p.relative_to(self.work / "render")): p.read_bytes()
                for p in (self.work / "render").rglob("*") if p.is_file()}

    def test_next_run_finishes_pending_receipt_without_fetch_or_model(self):
        retained = self.work / "render/unit-0000.wav"
        old = retained.stat()
        digest = sha256(retained)
        self.interrupt_import()
        first_imported = self.work / "render/unit-0001.wav"
        imported_stat = first_imported.stat()
        with (patch.object(runner, "process_run", side_effect=AssertionError("no SSH or model")) as process,
              patch.object(runner, "reconcile_remote", side_effect=AssertionError("no second fetch")) as fetch):
            self.run_main()
        process.assert_not_called()
        fetch.assert_not_called()
        self.assertEqual(len(self.fetches), 1)
        self.assertFalse(runner.pending_import_path(self.work).exists())
        self.assertTrue(self.fetches[0].is_dir(), "quarantine must survive successful import")
        self.assertEqual((retained.stat().st_ino, retained.stat().st_mtime_ns, sha256(retained)),
                         (old.st_ino, old.st_mtime_ns, digest))
        self.assertEqual((first_imported.stat().st_ino, first_imported.stat().st_mtime_ns),
                         (imported_stat.st_ino, imported_stat.st_mtime_ns))
        runner.validate_candidate(self.work)

    def test_owned_partial_temporary_can_resume_from_unchanged_quarantine(self):
        self.interrupt_import(partial_temporary=True)
        self.assertTrue(runner.resume_pending_import(self.work, self.job))
        self.assertFalse((self.work / "render/unit-0001.json.recovery-tmp").exists())
        self.assertEqual(sha256(self.work / "render/unit-0001.json"), sha256(self.remote / "unit-0001.json"))

    def test_modified_quarantine_is_rejected_without_copying_more_files(self):
        self.interrupt_import()
        # Keep this a structurally valid receipt change: the pending file hashes,
        # not just the ordinary renderer validator, must reject the mutation.
        receipt = self.fetches[0] / "render/unit-0001.json"
        data = read(receipt)
        data["unexpectedMetadata"] = "changed since pending import was recorded"
        receipt.write_text(json.dumps(data))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "quarantine changed"):
            runner.resume_pending_import(self.work, self.job)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(runner.pending_import_path(self.work).exists())

    def test_changed_job_copy_is_rejected(self):
        self.interrupt_import()
        (self.fetches[0] / "job.json").write_text("{}")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "job copy changed"):
            runner.resume_pending_import(self.work, self.job)
        self.assertEqual(self.snapshot(), before)

    def test_external_or_symlinked_quarantine_is_rejected(self):
        self.interrupt_import()
        pointer = runner.pending_import_path(self.work)
        saved = read(pointer)
        saved["quarantine"] = str(self.root / "external")
        pointer.write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError, "Unsafe remote import quarantine"):
            runner.resume_pending_import(self.work, self.job)
        alias = self.work / "accounting/remote-recovery/alias"
        alias.symlink_to(self.fetches[0], target_is_directory=True)
        saved["quarantine"] = str(alias)
        pointer.write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError, "Unsafe remote import quarantine"):
            runner.resume_pending_import(self.work, self.job)

    def test_no_pending_manifest_does_not_adopt_an_unreceipted_local_wav(self):
        shutil.copyfile(self.remote / "unit-0001.wav", self.work / "render/unit-0001.wav")
        before = self.snapshot()
        with (patch.object(runner, "process_run", side_effect=AssertionError("no SSH or model")) as process,
              patch.object(runner, "reconcile_remote", side_effect=AssertionError("no blind remote recovery")) as fetch):
            with self.assertRaisesRegex(ValueError, "Render cache"):
                self.run_main()
        process.assert_not_called()
        fetch.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_pending_import_checks_all_collisions_before_filling_any_gap(self):
        self.interrupt_import()
        (self.work / "render/unit-0000.wav").write_bytes(b"independent local change")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "Local and remote output differ"):
            runner.resume_pending_import(self.work, self.job)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.work / "render/unit-0001.json").exists())


if __name__ == "__main__":
    unittest.main()
