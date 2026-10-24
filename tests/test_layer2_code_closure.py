"""config/layer2-code-closure.json names every file the Layer 2 code identity binds (DEV-GOV-002).

Two guards: every listed file exists (and is tracked), and the manifest equals the
statically traced import graph, so a new dependency of a Layer 2 entry fails here until
it is reviewed into the closure with ``python3 tools/development/layer2_code_closure.py --write``.
"""
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from scripts.sermon_unified import contracts as unified_contracts
from tongxing_production.text import code_closure
from tongxing_production.text import controller as layer2
from tongxing_production.text import stat_memo
from tools.development import layer2_code_closure as tracer

ROOT = Path(__file__).resolve().parents[1]
REGENERATE = 'python3 tools/development/layer2_code_closure.py --write'
# Files a Layer 2 run does not execute: their edits no longer change the identity.
OUTSIDE = ('packages/production/src/tongxing_production/delivery/publication.py',
           'packages/production/src/tongxing_production/observability/weekly_projection.py',
           'packages/production/src/tongxing_production/audio/unified_stage.py',
           'scripts/check_run_start.py', 'tools/ops/group_tasks.py',
           'tools/development/layer2_code_closure.py')
# Files a Layer 2 run executes or reads: one per kind the manifest covers.
INSIDE = ('packages/production/src/tongxing_production/text/models.py',
          'packages/production/src/tongxing_production/orchestration/group_worker.py',
          'scripts/tongxing_host.py', 'scripts/sermon_unified/__init__.py',
          'scripts/language_review_plugins/common.py', 'scripts/series_terminology.py',
          'schemas/sermon-target-language-candidate-v2.schema.json',
          'schemas/sermon-english-source-package-v1.schema.json',
          'docs/series-terminology.zh.md', 'tools/ops/run.py', 'tools/ops/sermon_unified_preflight.py',
          code_closure.MANIFEST)


def unmemoized():
    # A patched read leaves the file's stat identity unchanged, which the binding memo would
    # rightly treat as unchanged; a fresh memo forces the full hash.
    return patch.object(layer2, '_BINDING_MEMO', stat_memo.StatMemo())


class ManifestTests(unittest.TestCase):
    def test_every_listed_file_exists_and_is_tracked(self):
        files = code_closure.files(ROOT)
        self.assertEqual([name for name in files if not (ROOT / name).is_file()], [])
        self.assertEqual([name for name in files if (ROOT / name).is_symlink()], [])
        listed = subprocess.run(['git', 'ls-files', '--', *files], cwd=ROOT, capture_output=True, text=True)
        if listed.returncode == 0:  # not a git checkout: existence is the only check
            self.assertEqual(sorted(set(files) - set(listed.stdout.split())), [],
                             'closure files must be tracked: an untracked file cannot be part of a frozen identity')

    def test_manifest_equals_the_traced_import_graph(self):
        missing, stale = tracer.difference(ROOT)
        self.assertEqual((missing, stale), ([], []),
                         f'\nnot in manifest (a Layer 2 entry now reaches them): {missing}'
                         f'\nno longer reached: {stale}'
                         f'\nReview whether each belongs in the Layer 2 closure, then run: {REGENERATE}')

    def test_entries_plugins_schemas_and_singles_are_listed(self):
        files = set(code_closure.files(ROOT))
        for name in (*tracer.ENTRIES, *INSIDE):
            with self.subTest(name=name):
                self.assertIn(name, files)
        plugins = {str(p.relative_to(ROOT)) for p in (ROOT / 'scripts/language_review_plugins').glob('*.py')}
        self.assertTrue(plugins and plugins <= files)
        for name in OUTSIDE:
            with self.subTest(name=name):
                self.assertTrue((ROOT / name).is_file())
                self.assertNotIn(name, files)
        self.assertLess(len(files), 300)  # the whole checkout is over 500 .py and schema files

    def test_manifest_shape_is_checked(self):
        value = code_closure.load(ROOT)
        self.assertEqual(value['schemaVersion'], code_closure.SCHEMA)
        self.assertEqual(value['files'], sorted(set(value['files'])))
        with patch.object(Path, 'read_text', return_value='{"schemaVersion": "other", "files": ["a.py"]}'):
            with self.assertRaisesRegex(ValueError, 'invalid_layer2_code_closure'):
                code_closure.load(ROOT)
        with patch.object(Path, 'read_text',
                          return_value=f'{{"schemaVersion": "{code_closure.SCHEMA}", "files": ["../x.py"]}}'):
            with self.assertRaisesRegex(ValueError, 'invalid_layer2_code_closure'):
                code_closure.load(ROOT)


class CodeIdentityTests(unittest.TestCase):
    def test_identity_digests_exactly_the_manifest_files(self):
        self.assertEqual(list(layer2.code_identity_files()), list(code_closure.files(ROOT)))

    def test_only_closure_files_change_the_identity(self):
        baseline = layer2.code_identity()
        original = Path.read_bytes

        def edited(target):
            return lambda path: original(path) + (b'#' if path == target else b'')

        for name in OUTSIDE:
            with self.subTest(name=name), unmemoized(), \
                    patch.object(Path, 'read_bytes', edited((ROOT / name).resolve())):
                self.assertEqual(layer2.code_identity(), baseline)
        for name in INSIDE:
            with self.subTest(name=name), unmemoized(), \
                    patch.object(Path, 'read_bytes', edited((ROOT / name).resolve())):
                self.assertNotEqual(layer2.code_identity(), baseline)
        self.assertEqual(layer2.code_identity(), baseline)

    def test_unified_admission_follows_the_manifest(self):
        modules = set(unified_contracts.required_modules())
        self.assertTrue(set(code_closure.files(ROOT)) <= modules)
        self.assertNotIn('scripts/check_run_start.py', modules)
        outside_schemas = sorted({f'schemas/{p.name}' for p in (ROOT / 'schemas').glob('*.schema.json')}
                                 - set(code_closure.files(ROOT)))
        self.assertTrue(outside_schemas)
        self.assertNotIn(outside_schemas[0], modules)


if __name__ == '__main__':
    unittest.main()
