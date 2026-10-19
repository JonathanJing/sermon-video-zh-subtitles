"""Review R1: the three standard-library review leaves live in the package; only the ledger keeps a facade."""
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts import machine_quality_waiver as waiver
from tongxing_production import path_aliases

ROOT = Path(__file__).resolve().parents[1]
MOVED = {'machine_repair_ledger': 'repair_ledger',
         'audio_qc_human_acceptance': 'audio_qc_acceptance',
         'text_qc_human_acceptance': 'text_qc_acceptance'}
# The two acceptance facades are gone; their legacy keys still resolve.
FACADES = {'machine_repair_ledger': 'repair_ledger'}


class ReviewLeafTests(unittest.TestCase):
    def test_scripts_facades_are_the_package_modules(self):
        for legacy, current in FACADES.items():
            with self.subTest(module=legacy):
                implementation = importlib.import_module('tongxing_production.review.' + current)
                self.assertIs(importlib.import_module('scripts.' + legacy), implementation)
                self.assertIs(sys.modules['scripts.' + legacy], implementation)

    def test_legacy_keys_resolve_into_the_package(self):
        for legacy, current in MOVED.items():
            key = 'scripts/' + legacy + '.py'
            with self.subTest(key=key):
                self.assertEqual(path_aliases.resolve(key), path_aliases.PRODUCTION + 'review/' + current + '.py')
                self.assertTrue((ROOT/path_aliases.resolve(key)).is_file())

    def test_waiver_identity_reads_the_moved_ledger(self):
        key = 'scripts/machine_repair_ledger.py'
        self.assertIn(key, waiver.IMPLEMENTATION_FILES)
        self.assertEqual(waiver.implementation_path(key), ROOT/path_aliases.resolve(key))
        moved_key = path_aliases.resolve(key)
        self.assertIn(moved_key, waiver.IMPLEMENTATION_PHYSICAL_FILES)
        before = waiver.implementation_sha256()
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            for name in waiver.IMPLEMENTATION_PHYSICAL_FILES:
                source = ROOT/name
                target = checkout/name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            changed = checkout/moved_key
            moved = changed.read_bytes()
            self.assertEqual(waiver.implementation_sha256(checkout), before)
            changed.write_bytes(moved + b'\n# changed\n')
            self.assertNotEqual(waiver.implementation_sha256(checkout), before)
            changed.write_bytes(moved)
            self.assertEqual(waiver.implementation_sha256(checkout), before)

    def test_facades_import_with_only_the_spark_container_path(self):
        """Spark containers run without site-packages and put <code>/packages/production/src
        and <code> on PYTHONPATH (clip_e2e_spark.PACKAGE_SRC)."""
        from scripts import clip_e2e_spark
        environment = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
        environment['PYTHONPATH'] = os.pathsep.join([str(ROOT/clip_e2e_spark.PACKAGE_SRC), str(ROOT)])
        code = ''.join(f'import scripts.{legacy} as m\n'
                       f'assert m.__name__ == "tongxing_production.review.{current}", m.__name__\n'
                       for legacy, current in FACADES.items())
        with tempfile.TemporaryDirectory() as elsewhere:
            result = subprocess.run([sys.executable, '-S', '-c', code], cwd=elsewhere, env=environment,
                                    capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])


if __name__ == '__main__':
    unittest.main()
