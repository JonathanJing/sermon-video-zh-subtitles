"""Live Fresh Session boundaries over synthetic MFA files; no model execution."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_fresh_diagnostic as entry
from scripts import sermon_log_profile as profile
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from tests import test_sermon_fresh_source_causality as fixtures
from tests.test_sermon_mfa_identity import alignment_fixture, runtime_fixture, write_json


class FreshMFABoundaryTests(unittest.TestCase):
    def setUp(self):
        f = fixtures.FreshCausalityTests(); f.setUp(); self.addCleanup(f.doCleanups)
        self.f = f; self.root = f.root
        self.runtime = runtime_fixture(self.root)
        runtime_path = self.root/'runtime.json'; write_json(runtime_path, self.runtime)
        # The prior ASR remains immutable; only this new offline response differs.
        f.f.f.transcript += ' Amen.'
        aligned = public.read_snapshot(f.recipe['prior_aligned_path'])[0]
        aligned[-1]['text'] += ' Amen.'
        end = aligned[-1]['end']; aligned[-1]['end'] = end + .5
        aligned[-1]['wordTimes'].append({'text': 'Amen.', 'start': end, 'end': end + .5})
        self.enterContext(patch.object(accounting, 'execution_identity', return_value=f.plan['executionIdentity']))
        self.session = entry.FreshDiagnosticSession(f.plan, offline_transport=f.f.f.transport)
        self.enterContext(profile.session(self.root/'logs', 'fresh-mfa-boundary-fixture',
            work_kind='engineering', evidence_mode='synthetic'))
        def align(chunks, audio_path, outdir, **options):
            self.assertFalse(options['allow_spark_fallback'])
            return alignment_fixture(f.plan, self.runtime, chunks, deepcopy(aligned))
        with patch.object(entry.source_adapter.mfa_backend, 'align_reference_chunks', side_effect=align) as mocked:
            self.prepared = self.session.prepare_source(dict(f.recipe, run_mfa=True,
                local_runtime_path=runtime_path), f.f.authorization)
        mocked.assert_called_once()
        self.assertEqual(self.prepared['evidence']['alignmentMode'], 'fresh_local_mfa')
        self.assertIsNotNone(self.prepared['evidence']['sourceCausalitySha256'])
        plugin = self.root/'fixture-language-plugin.py'
        plugin.write_bytes(Path(f.f.f.locale_specs['zh-Hans']['pluginPath']).read_bytes())
        self.drafts = {'zh-Hans': {'policy': str(self.root/'policy-draft.json'),
            'rubric': str(self.root/'rubric-draft.json'), 'pluginPath': str(plugin)}}
        write_json(Path(self.drafts['zh-Hans']['policy']), f.f.f.policy)
        write_json(Path(self.drafts['zh-Hans']['rubric']), f.f.f.rubric)
        self.specs = entry.freeze_locale_inputs(self.session, self.drafts)
        self.calls = len(f.f.f.transport.observations)
        self.enterContext(patch.object(entry.source_adapter.mfa_backend, 'align_reference_chunks',
            side_effect=AssertionError('MFA redispatch forbidden')))
        self.dispatch = self.enterContext(patch.object(self.session.runner, 'run_locale',
            side_effect=AssertionError('Layer 2 dispatch forbidden')))

    def snapshot(self):
        return {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}

    def assert_blocked_readonly(self):
        before = self.snapshot()
        boundaries = (self.session.inspect_source,
            lambda: entry.freeze_locale_inputs(self.session, self.drafts),
            lambda: self.session.run_locale('zh-Hans', self.specs['zh-Hans']))
        for action in boundaries:
            with self.assertRaises((c.ContractError, OSError)):
                action()
            self.assertEqual(before, self.snapshot())
            self.assertEqual(self.calls, len(self.f.f.f.transport.observations))
            self.dispatch.assert_not_called()

    def test_missing_and_corrupt_mfa_evidence_block_every_downstream_boundary(self):
        segments = public.read_snapshot(self.root/'aligned-segments.json')[0]
        manifest = Path(segments[0]['mfaManifest'])
        paths = (self.root/'mfa-identity-comparison.json', self.root/'mfa-identity-preflight.json',
            self.root/'mfa/backend.json', manifest, manifest.parent/'aligned/speaker/chunk_0000.json',
            manifest.parent/'segments.json', manifest.parent/'dictionary.dict',
            self.root/'aligned-segments.json', Path(self.runtime['runtime']['files']['acoustic_model']['path']))
        for path in paths:
            original = path.read_bytes()
            for operation in ('missing', 'corrupt'):
                with self.subTest(artifact=path.name, operation=operation):
                    if operation == 'missing': path.unlink()
                    else: path.write_bytes(b'corrupted synthetic evidence')
                    try:
                        self.assert_blocked_readonly()
                    finally:
                        path.write_bytes(original)
            # Restoring exactly the original evidence allows read-only use again.
            before = self.snapshot()
            self.assertEqual(self.session.inspect_source()['sourceEvidence'], self.prepared['evidence'])
            self.assertEqual(before, self.snapshot())
        self.f.f.network.assert_not_called()

    def test_valid_mfa_evidence_allows_locale_boundary_without_realigning(self):
        before = self.snapshot()
        self.assertEqual(self.session.inspect_source()['sourceEvidence'], self.prepared['evidence'])
        self.assertEqual(entry.freeze_locale_inputs(self.session, self.drafts), self.specs)
        self.dispatch.side_effect = None
        self.dispatch.return_value = {'status': 'synthetic_boundary_only'}
        self.assertEqual(self.session.run_locale('zh-Hans', self.specs['zh-Hans']),
            {'status': 'synthetic_boundary_only'})
        self.dispatch.assert_called_once()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.calls, len(self.f.f.f.transport.observations))


if __name__ == '__main__':
    unittest.main()
