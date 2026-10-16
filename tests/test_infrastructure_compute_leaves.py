"""Infrastructure I0b: the two standard-library compute leaves live in the package behind facades."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import machine_qc_audio_transports as transports
from scripts import machine_quality_waiver as waiver
from tongxing_production import path_aliases

ROOT = Path(__file__).resolve().parents[1]
MOVED = {'sermon_openai_runtime': 'openai_runtime', 'sermon_transcription_request': 'transcription_request'}


class ComputeLeafTests(unittest.TestCase):
    def test_scripts_facades_are_the_package_modules(self):
        import importlib
        for legacy, current in MOVED.items():
            with self.subTest(module=legacy):
                implementation = importlib.import_module('tongxing_production.compute.' + current)
                self.assertIs(importlib.import_module('scripts.' + legacy), implementation)
                self.assertIs(sys.modules['scripts.' + legacy], implementation)

    def test_closure_keys_stay_legacy_and_resolve_into_the_package(self):
        for legacy, current in MOVED.items():
            key = 'scripts/' + legacy + '.py'
            with self.subTest(key=key):
                self.assertIn(key, waiver.IMPLEMENTATION_FILES)
                self.assertEqual(path_aliases.resolve(key), path_aliases.PRODUCTION + 'compute/' + current + '.py')
                self.assertEqual(waiver.implementation_path(key), ROOT/path_aliases.resolve(key))
                self.assertTrue(waiver.implementation_path(key).is_file())

    def test_transport_identity_reads_the_moved_request_builder(self):
        moved = (ROOT/path_aliases.resolve('scripts/sermon_transcription_request.py')).read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory)/'transcription_request.py'
            changed.write_bytes(moved + b'\n# changed\n')
            before = transports.implementation_sha256()
            from unittest.mock import patch
            with patch.dict(path_aliases.PATH_ALIASES, {'scripts/sermon_transcription_request.py': str(changed)}):
                self.assertNotEqual(transports.implementation_sha256(), before)

    def test_facades_import_with_only_the_spark_container_path(self):
        """Spark containers run without site-packages and put <code>/packages/production/src
        and <code> on PYTHONPATH (clip_e2e_spark.PACKAGE_SRC)."""
        from scripts import clip_e2e_spark
        environment = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
        environment['PYTHONPATH'] = os.pathsep.join([str(ROOT/clip_e2e_spark.PACKAGE_SRC), str(ROOT)])
        code = ('import sys\n'
                'import scripts.sermon_openai_runtime as a, scripts.sermon_transcription_request as b\n'
                'assert a.__name__ == "tongxing_production.compute.openai_runtime", a.__name__\n'
                'assert b.__name__ == "tongxing_production.compute.transcription_request", b.__name__\n')
        with tempfile.TemporaryDirectory() as elsewhere:
            result = subprocess.run([sys.executable, '-S', '-c', code], cwd=elsewhere, env=environment,
                                    capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])


if __name__ == '__main__':
    unittest.main()
