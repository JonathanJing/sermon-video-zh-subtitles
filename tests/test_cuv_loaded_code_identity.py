"""The moved CUV entry keeps its former load-time code in frozen identities."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CuvLoadedCodeIdentityTests(unittest.TestCase):
    def test_former_load_time_dependencies_are_in_execution_identity(self):
        code = """
import hashlib
import sys
from pathlib import Path
from scripts import tongxing_host
from tongxing_production.text import cuv_translation as sermon_cuv_translation
from tongxing_production.observability.accounting import execution_identity
loaded = execution_identity()['loadedProjectCodeSha256']
for name in ('scripts.sermon_accounting', 'scripts.sermon_pipeline', 'scripts.cuv_scripture'):
    module = sys.modules[name]
    path = Path(module.__file__).resolve()
    key = str(path.relative_to(Path.cwd()))
    assert loaded[key] == hashlib.sha256(path.read_bytes()).hexdigest(), name
assert 'packages/production/src/tongxing_production/text/cuv_translation.py' in loaded
"""
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                                env={key: value for key, value in os.environ.items() if key != 'PYTHONPATH'},
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == '__main__':
    unittest.main()
