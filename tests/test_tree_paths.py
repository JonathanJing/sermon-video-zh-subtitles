"""A test run imports the package sources of its own tree, in process and in Python children."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests import tree_paths

ROOT = tree_paths.ROOT
# What tests/conftest.py and its autouse fixture need, besides the package sources.
COPIED = ('tests/conftest.py', 'tests/tree_paths.py', 'scripts', 'packages/production/src', 'services/api/src')
PROBE = '''
import json, subprocess, sys
from tests import tree_paths
import tongxing_api, tongxing_production

CHILD = [sys.executable, '-c', 'import tongxing_api, tongxing_production as p; print(p.__file__, tongxing_api.__file__)']


def test_probe():
    inherited = subprocess.run(CHILD, capture_output=True, text=True, check=True).stdout.split()
    fresh = subprocess.run(CHILD, env=tree_paths.child_env({}), capture_output=True, text=True, check=True).stdout.split()
    print('PROBE ' + json.dumps({'process': [tongxing_production.__file__, tongxing_api.__file__],
                                 'inherited': inherited, 'fresh': fresh}))
'''


def _copy(target: Path) -> None:
    ignore = shutil.ignore_patterns('__pycache__', '*.pyc')
    for name in COPIED:
        source, destination = ROOT / name, target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, ignore=ignore)
        else:
            shutil.copy2(source, destination)


class TreePathsTests(unittest.TestCase):
    def test_copied_tree_imports_its_own_package_in_process_and_in_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp).resolve() / 'repo-copy'
            _copy(copy)
            (copy / 'tests' / 'test_probe.py').write_text(PROBE, encoding='utf-8')
            # This tree's sources stay on PYTHONPATH, as they would under the outer pytest run.
            env = {**os.environ, 'PYTHONPATH': tree_paths.pythonpath(os.environ.get('PYTHONPATH')),
                   'PYTHONDONTWRITEBYTECODE': '1'}
            result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-s', '-p', 'no:cacheprovider',
                                     'tests/test_probe.py'], cwd=copy, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            line = next(line for line in result.stdout.splitlines() if line.startswith('PROBE '))
            seen = json.loads(line[len('PROBE '):])
            expected = (copy / 'packages/production/src/tongxing_production', copy / 'services/api/src/tongxing_api')
            for where, files in seen.items():
                with self.subTest(where=where):
                    self.assertEqual([Path(file).resolve().parent for file in files], list(expected))

    def test_child_env_puts_this_tree_first_without_duplicates(self):
        first = [str(path) for path in tree_paths.SOURCES]
        env = tree_paths.child_env({'PATH': '/bin', 'PYTHONPATH': os.pathsep.join(['/other', first[0]])})
        self.assertEqual(env['PATH'], '/bin')
        self.assertEqual(env['PYTHONPATH'].split(os.pathsep), first + ['/other'])
        self.assertEqual(tree_paths.child_env({})['PYTHONPATH'].split(os.pathsep), first)


if __name__ == '__main__':
    unittest.main()
