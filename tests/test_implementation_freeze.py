import json
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.review import implementation_freeze as freeze
from tongxing_production.review import waiver
from tongxing_production.review import qc_audio_run as audio_driver
from tongxing_production.review import qc_text_run as text_driver


class ImplementationFreezeTests(unittest.TestCase):
    def test_current_checkout_matches_its_own_hash(self):
        self.assertIsNone(freeze.mismatch(waiver.implementation_sha256()))
        self.assertEqual(set(freeze.file_hashes()), set(waiver.IMPLEMENTATION_PHYSICAL_FILES))

    def test_guard_alias_and_spark_closure_bind_the_physical_generation(self):
        self.assertEqual(freeze.ROOT, Path(__file__).resolve().parents[1])
        self.assertEqual([str(path) for path in freeze.closure_files(Path())],
                         list(waiver.IMPLEMENTATION_PHYSICAL_FILES))
        self.assertEqual(set(freeze.file_hashes()), set(map(str, freeze.closure_files(Path()))))
        self.assertIn('packages/production/src/tongxing_production/review/implementation_freeze.py',
                      freeze.file_hashes())
        # A4's exact 49-file identity is historical; R4's moved guard refuses it.
        stale_a4 = '74b2f5a23c43dea429a0d31b27c5767ee66740b764cb5294081b89d58202de60'
        self.assertEqual(freeze.mismatch(stale_a4)['exitCode'], 2)

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

    def test_target_and_alias_resolver_each_invalidate_freeze(self):
        baseline = waiver.implementation_sha256()
        frozen_files = freeze.file_hashes()
        original = Path.read_bytes
        # The D closure window removed the scripts/ facades; only their targets are hashed.
        for facade in ("scripts/machine_quality_waiver.py", "scripts/implementation_freeze.py"):
            self.assertNotIn(facade, frozen_files)
        for name in ("packages/production/src/tongxing_production/review/waiver.py",
                     "packages/production/src/tongxing_production/path_aliases.py",
                     "packages/production/src/tongxing_production/review/implementation_freeze.py"):
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
