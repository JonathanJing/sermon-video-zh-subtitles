"""Infrastructure I0b: the two standard-library compute leaves live in the package; the D window removed their facades."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.compute import qc_audio_transports as transports
from tongxing_production.review import waiver
from tongxing_production import path_aliases

ROOT = Path(__file__).resolve().parents[1]
MOVED = {'sermon_openai_runtime': 'openai_runtime', 'sermon_transcription_request': 'transcription_request'}


class ComputeLeafTests(unittest.TestCase):
    def test_closure_keys_stay_legacy_and_resolve_into_the_package(self):
        for legacy, current in MOVED.items():
            key = 'scripts/' + legacy + '.py'
            with self.subTest(key=key):
                self.assertIn(key, waiver.IMPLEMENTATION_FILES)
                self.assertEqual(path_aliases.resolve(key), path_aliases.PRODUCTION + 'compute/' + current + '.py')
                self.assertEqual(waiver.implementation_path(key), ROOT/path_aliases.resolve(key))
                self.assertTrue(waiver.implementation_path(key).is_file())

    def test_transport_identity_reads_the_moved_request_builder(self):
        key = path_aliases.resolve('scripts/sermon_transcription_request.py')
        self.assertIn(key, transports.TRANSPORT_PHYSICAL_FILES)
        before = transports.implementation_sha256()
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            for name in transports.TRANSPORT_PHYSICAL_FILES:
                source = ROOT/name
                target = checkout/name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            changed = checkout/key
            moved = changed.read_bytes()
            with patch.object(transports, '_checkout_root', return_value=checkout):
                self.assertEqual(transports.implementation_sha256(), before)
            changed.write_bytes(moved + b'\n# changed\n')
            with patch.object(transports, '_checkout_root', return_value=checkout):
                self.assertNotEqual(transports.implementation_sha256(), before)
            changed.write_bytes(moved)
            with patch.object(transports, '_checkout_root', return_value=checkout):
                self.assertEqual(transports.implementation_sha256(), before)

    def test_package_modules_import_with_only_the_spark_container_path(self):
        """Spark containers run without site-packages and put <code>/packages/production/src
        and <code> on PYTHONPATH (clip_e2e_spark.PACKAGE_SRC)."""
        from scripts import clip_e2e_spark
        environment = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
        environment['PYTHONPATH'] = os.pathsep.join([str(ROOT/clip_e2e_spark.PACKAGE_SRC), str(ROOT)])
        code = ('import sys\n'
                'import tongxing_production.compute.openai_runtime as a\n'
                'import tongxing_production.compute.transcription_request as b\n'
                'assert a.__name__ == "tongxing_production.compute.openai_runtime", a.__name__\n'
                'assert b.__name__ == "tongxing_production.compute.transcription_request", b.__name__\n')
        with tempfile.TemporaryDirectory() as elsewhere:
            result = subprocess.run([sys.executable, '-S', '-c', code], cwd=elsewhere, env=environment,
                                    capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])


if __name__ == '__main__':
    unittest.main()
