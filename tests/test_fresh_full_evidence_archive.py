"""Bounded input preservation without SDK execution, workers or network access."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.fresh_full_dag_fixture import (
    FullFreshDAGFixture, archive_fixture_inputs, clean_child, preserve_full_evidence,
)


class FreshFullEvidenceArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base/'fixture'/'real-leaf-run'
        self.root.mkdir(parents=True)
        self.recipe = {}
        for role, relative in {
            'prior_plan_path': 'run-plan.json',
            'prior_source_path': 'simulated-review-inputs/source.json',
            'prior_aligned_path': 'aligned-segments.json',
            'prior_summary_path': 'source-pipeline-summary.json',
            'audio_path': 'fresh-run/source.wav',
        }.items():
            path = self.root.parent/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('synthetic '+role).encode())
            self.recipe[role] = path
        self.clip = self.root.parent/'source-180s.mp4'
        self.clip.write_bytes(b'synthetic media')
        (self.root.parent/'anchor-manifest.json').write_bytes(b'synthetic anchors')
        self.plan = {'sourceClipPath': str(self.clip)}
        self.destination = self.base/'saved'
        self.enterContext(patch.dict('os.environ', {
            'SERMON_FRESH_FULL_TEST_EVIDENCE_DIR': str(self.destination)}))

    def test_frozen_input_bytes_survive_original_cleanup_and_preplan_failure(self):
        originals = {path: path.read_bytes() for path in self.root.parent.rglob('*') if path.is_file()}
        archive_fixture_inputs(self.root, self.recipe, self.plan)
        self.assertEqual(originals, {path: path.read_bytes() for path in originals})
        preserve_full_evidence(self.root, 'failure')
        saved = self.destination/'failure'/'pre-plan'
        manifest = json.loads((saved/'fixture-input-archive'/'manifest.json').read_text())
        self.assertTrue(manifest['auditOnly'])
        self.assertFalse(manifest['dispatchAuthorized'])
        self.assertFalse(manifest['originalReferencesRewritten'])
        self.assertEqual(len(manifest['entries']), 7)
        for path in originals:
            path.unlink()
        for row in manifest['entries']:
            raw = (saved/row['savedPath']).read_bytes()
            self.assertEqual(raw, originals[Path(row['originalPath'])])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row['sha256'])
            self.assertEqual(len(raw), row['sizeBytes'])
        # Reject before even reading a payload, much less importing a worker.
        with self.assertRaisesRegex(ValueError, 'saved_evidence_dispatch_forbidden'):
            clean_child(saved/'sdk-invoke-1.json')

    def test_preserves_failed_frozen_plan_without_a_result(self):
        archive_fixture_inputs(self.root, self.recipe, self.plan)
        plan = self.root/'fresh-full-dag'/('a'*64)
        plan.mkdir(parents=True)
        (plan/'plan.json').write_text('{"status":"incomplete"}')
        preserve_full_evidence(self.root, 'happy')
        saved = self.destination/'happy'/('a'*64)
        self.assertEqual((saved/'fresh-full-dag'/('a'*64)/'plan.json').read_bytes(),
            (plan/'plan.json').read_bytes())
        self.assertTrue((saved/'fixture-input-archive'/'manifest.json').is_file())

    def test_real_fixture_registers_all_seven_inputs_without_running_dag(self):
        fixture = FullFreshDAGFixture()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        manifest = json.loads((fixture.root/'fixture-input-archive'/'manifest.json').read_text())
        self.assertEqual(len(manifest['entries']), 7)
        for row in manifest['entries']:
            self.assertEqual(Path(row['originalPath']).read_bytes(),
                (fixture.root/row['savedPath']).read_bytes())

    def test_rejects_external_reference_without_reading_it(self):
        self.recipe['audio_path'] = self.base/'outside-secret'
        with self.assertRaisesRegex(ValueError, 'input_path_invalid'):
            archive_fixture_inputs(self.root, self.recipe, self.plan)
        self.assertFalse((self.root/'fixture-input-archive').exists())

    def test_rejects_symlink_without_copying_target(self):
        self.clip.unlink()
        self.clip.symlink_to(self.base/'outside-secret')
        with self.assertRaisesRegex(ValueError, 'input_link_rejected'):
            archive_fixture_inputs(self.root, self.recipe, self.plan)
        self.assertFalse((self.root/'fixture-input-archive').exists())

    def test_rejects_oversized_input(self):
        with self.clip.open('wb') as output:
            output.truncate(8*1024*1024+1)
        with self.assertRaisesRegex(ValueError, 'input_size_invalid'):
            archive_fixture_inputs(self.root, self.recipe, self.plan)
        self.assertFalse((self.root/'fixture-input-archive').exists())


if __name__ == '__main__':
    unittest.main()
