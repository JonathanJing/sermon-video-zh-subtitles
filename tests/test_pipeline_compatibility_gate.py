import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.pipeline_compatibility_gate import evaluate


class CompatibilityGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        for name in ('apps/tongxing-ios/App.swift', 'schemas/catalog.json',
                     'experiments/sermon-dubbing-poc/web/app.mjs', 'scripts/sermon_accounting.py'):
            self.write(name, 'original')
        self.base = self.save()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args]).decode().strip()

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def save(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        return self.git('rev-parse', 'HEAD')

    def test_audited_backend_only_exact_head_receipt(self):
        self.write('scripts/sermon_accounting.py', 'new')
        head = self.save()
        result = evaluate(self.root, self.base, head)
        self.assertEqual(result['headCommit'], head)
        self.assertEqual(result['status'], 'backend_only_unchanged')
        self.assertIs(result['ios_review_required'], False)
        self.assertEqual(result['compatibilitySignoff'], 'not_evaluated')
        self.assertEqual(result['baseSnapshot']['sha256'], result['headSnapshot']['sha256'])

    def test_client_schema_privacy_and_unknown_changes_fail_closed(self):
        for name in ('apps/tongxing-ios/App.swift', 'schemas/catalog-v3.json',
                     'firebase/dev/public/adapter.mjs', 'new/Privacy.xcprivacy',
                     'scripts/new_delivery_builder.py'):
            with self.subTest(name=name):
                self.write(name, 'new')
                head = self.save()
                result = evaluate(self.root, self.base, head)
                self.assertEqual(result['status'], 'review_required')
                self.assertIsNone(result['ios_review_required'])

    def test_deleted_surface_blocks_and_blob_contents_not_exposed(self):
        (self.root / 'schemas/catalog.json').unlink()
        self.write('apps/tongxing-ios/App.swift', 'PRIVATE_CONTENT')
        result = evaluate(self.root, self.base, self.save())
        self.assertIn('schemas/', result['missingSurfaces'])
        self.assertEqual(result['status'], 'review_required')
        self.assertNotIn('PRIVATE_CONTENT', json.dumps(result))

    def test_identical_final_trees_do_not_infer_changes_from_ancestry(self):
        self.write('apps/tongxing-ios/App.swift', 'intermediate')
        self.save()
        self.write('apps/tongxing-ios/App.swift', 'original')
        result = evaluate(self.root, self.base, self.save())
        self.assertEqual(result['status'], 'backend_only_unchanged')


if __name__ == '__main__':
    unittest.main()
