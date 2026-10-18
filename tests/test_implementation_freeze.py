import json
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import implementation_freeze as freeze
from scripts import machine_quality_waiver as waiver
from scripts import run_machine_qc_audio_test as audio_driver
from scripts import run_machine_qc_clip_test as text_driver


class ImplementationFreezeTests(unittest.TestCase):
    def test_current_checkout_matches_its_own_hash(self):
        self.assertIsNone(freeze.mismatch(waiver.implementation_sha256()))
        self.assertEqual(set(freeze.file_hashes()), set(waiver.IMPLEMENTATION_PHYSICAL_FILES))

    def test_other_hash_is_reported_with_the_changed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in waiver.IMPLEMENTATION_PHYSICAL_FILES:
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(freeze.ROOT / name, destination)
            frozen_hash = waiver.implementation_sha256(root)
            frozen_files = freeze.file_hashes(root)
            self.assertEqual(frozen_hash, waiver.implementation_sha256())
            edited = waiver.implementation_path("scripts/target_audio_auto_qc.py", root)
            edited.write_text(edited.read_text(encoding="utf-8") + "\n# edited after the run plan froze\n", encoding="utf-8")
            report = freeze.mismatch(frozen_hash, recorded_files=frozen_files, root=root)
            self.assertEqual(report["status"], "implementation_mismatch")
            self.assertEqual(report["expectedImplementationSha256"], frozen_hash)
            self.assertNotEqual(report["currentImplementationSha256"], frozen_hash)
            self.assertEqual(report["changedFiles"], ["packages/production/src/tongxing_production/review/audio_qc.py"])
            self.assertEqual(report["exitCode"], 2)
            # Without recorded per-file hashes the report still names the current hashes.
            self.assertIsNone(freeze.mismatch(frozen_hash, root=root)["changedFiles"])
        with self.assertRaisesRegex(ValueError, "64-hex"):
            freeze.mismatch("not-a-sha")

    def test_facade_target_and_alias_resolver_each_invalidate_freeze(self):
        baseline = waiver.implementation_sha256()
        frozen_files = freeze.file_hashes()
        original = Path.read_bytes
        for name in ("scripts/machine_quality_waiver.py",
                     "packages/production/src/tongxing_production/review/waiver.py",
                     "packages/production/src/tongxing_production/path_aliases.py",
                     "scripts/implementation_freeze.py"):
            target = freeze.ROOT / name
            with self.subTest(name=name), patch.object(Path, "read_bytes",
                    lambda path: original(path) + b"\n# changed physical file\n"
                    if path == target else original(path)):
                report = freeze.mismatch(baseline, recorded_files=frozen_files)
                self.assertEqual(report["changedFiles"], [name])
                self.assertNotEqual(report["currentImplementationSha256"], baseline)
                self.assertNotEqual(report["files"][name], frozen_files[name])

    def test_pre_facade_freeze_is_refused(self):
        old = hashlib.sha256()
        for name in waiver.IMPLEMENTATION_FILES:
            old.update(name.encode("utf-8") + b"\0" + waiver.implementation_path(name).read_bytes() + b"\0")
        old_hash = old.hexdigest()
        self.assertNotEqual(old_hash, waiver.implementation_sha256())
        self.assertEqual(freeze.mismatch(old_hash)["status"], "implementation_mismatch")

    def test_both_drivers_refuse_other_code_before_doing_anything(self):
        stale = "0" * 64
        for driver, extra in ((audio_driver, ["--backend", "fake"]), (text_driver, ["--text-backend", "fake"])):
            with self.subTest(driver=driver.__name__), tempfile.TemporaryDirectory() as directory:
                out = Path(directory) / "out"
                with patch("sys.stderr") as stderr:
                    code = driver.main(["--out", str(out), "--expected-implementation", stale, *extra])
                self.assertEqual(code, 2)
                self.assertFalse(out.exists())
                written = "".join(str(call.args[0]) for call in stderr.write.call_args_list if call.args)
                self.assertIn("implementation_mismatch", written)
                report = json.loads(written.strip().splitlines()[0])
                self.assertEqual(report["currentImplementationSha256"], waiver.implementation_sha256())


if __name__ == "__main__":
    unittest.main()
