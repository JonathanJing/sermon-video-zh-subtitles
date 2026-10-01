"""Read-only source and preview evidence checks; all fixtures are synthetic."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import sermon_diagnostic_delivery_preflight as subject
from scripts import sermon_diagnostic_provider as provider
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from tests import test_render_speculative_target_language_speech as previews
from tests import test_sermon_diagnostic_source_evidence as sources
from tests.test_sermon_diagnostic_provider import authority


class PreviewInspectionTests(unittest.TestCase):
    def setUp(self):
        self.f = previews.DiagnosticPreviewTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        f = self.f
        self.root = f.f.root.resolve()
        weights = b'synthetic checkpoint, never loaded'
        checkpoint = self.root / 'checkpoint'
        (checkpoint / 'model.safetensors').write_bytes(weights)
        (checkpoint / 'config.json').write_text(json.dumps({'talker_config': {'spk_id': {f.f.adapter['speakerKey']: 0}}}))
        f.f.registry['speakers'][0]['checkpoint']['checkpointSha256'] = c.bytes_sha256(weights)
        f.f.adapter['conditioningSha256'] = c.bytes_sha256(weights)
        f.f.adapter['registryJsonSha256'] = c.canonical_sha256(f.f.registry)
        for path, value in ((f.f.registry_path, f.f.registry), (f.f.adapter_path, f.f.adapter)):
            path.write_text(json.dumps(value))
        rubric = self.root / 'rubric.json'; rubric.write_text(json.dumps(f.rubric))
        # Actual original validators and real local full decode, only synthesis is fake.
        subject.preview.render(f.preview.paths, f.preview.checkpoint_map, f.preview.policies,
            f.preview.out, strict_rubric=f.rubric, diagnostic_context=f.context,
            deadline_monotonic=subject.preview._monotonic() + 60, synth_factory=previews.FakeSynth)
        self.out = f.preview.out.resolve()
        self.spec = dict(paths={k: str(v.resolve()) for k, v in f.preview.paths.items()},
            checkpoint_map_path=str(f.preview.checkpoint_map.resolve()),
            operation_policies_path=str(f.preview.policies.resolve()), strict_rubric_path=str(rubric), out=str(self.out))
        inputs = [*self.spec['paths'].values(), self.spec['checkpoint_map_path'],
                  self.spec['operation_policies_path'], str(rubric)]
        self.receipt = dict(schemaVersion=subject.WORKER_SCHEMA, status='preview_only',
            humanAcceptance='pending', productionEligible=False, runId=f.context['runId'],
            storeSha256=f.context['storeSha256'], runConfigSha256=f.context['runConfigSha256'],
            diagnosticContextSha256=c.canonical_sha256(f.context), spec=self.spec,
            specSha256=c.canonical_sha256(self.spec), inputs=[self.ref(p) for p in inputs],
            artifacts=[self.ref(p) for p in self.out.rglob('*') if p.is_file()])
        self.save_receipt()

    @staticmethod
    def ref(path):
        path = Path(path)
        return dict(path=str(path.resolve()), fileBytesSha256=c.bytes_sha256(path.read_bytes()))

    def save_receipt(self):
        path = self.out / 'worker-receipt.json'
        path.write_bytes(c.canonical_bytes(self.receipt))
        self.envelope = dict(self.receipt, receiptPath=str(path), receiptFileSha256=c.bytes_sha256(path.read_bytes()))

    def inspect(self):
        # Worker process/attempt evidence has its own dedicated integration
        # tests; exercise this inspector's original renderer and byte checks.
        with patch.object(subject.worker, 'validate_preview_receipt', return_value=self.envelope):
            return subject._inspect_preview(self.root, None, self.f.context, 'zh-Hans', self.envelope, subject._Snapshot())

    def test_actual_preview_revalidated_without_writes_models_or_approval(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        calls = len(previews.FakeSynth.calls)
        first = self.inspect(); self.assertEqual(first, self.inspect())
        self.assertEqual(first['previewStatus'], 'preview_only')
        self.assertEqual(first['realHumanAcceptance'], 'pending')
        self.assertEqual(len(first['units']), 2)
        self.assertEqual(set(first['pendingRealGates'].values()), {'pending'})
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(calls, len(previews.FakeSynth.calls))
        self.assertNotIn(str(self.root), json.dumps(first))
        self.assertNotIn(self.f.candidate['groups'][0]['targetText'], json.dumps(first))

    def test_changed_original_voice_and_checkpoint_fail_closed(self):
        path = self.f.f.registry_path
        registry = json.loads(path.read_text()); registry['speakers'][0]['authorization']['status'] = 'revoked'
        path.write_text(json.dumps(registry))
        self.receipt['inputs'] = [self.ref(row['path']) for row in self.receipt['inputs']]
        self.save_receipt()
        with self.assertRaises(ValueError): self.inspect()

    def test_receipt_audio_snapshot_and_context_tampering_block(self):
        for path in (self.out / 'units/unit-0000.wav', self.out / 'candidate.json',
                     self.out / 'diagnostic_context.json', self.out / 'receipts/unit-0000.json'):
            original = path.read_bytes(); path.write_bytes(original + b' ')
            with self.subTest(path=path.name), self.assertRaises(ValueError): self.inspect()
            path.write_bytes(original)
        self.envelope['receiptFileSha256'] = 'f' * 64
        with self.assertRaises(ValueError): self.inspect()

    def test_rebound_wrong_unit_duration_rejected_by_decode(self):
        path = self.out / 'receipts/unit-0000.json'
        unit = json.loads(path.read_text()); unit['durationSeconds'] = 99
        path.write_text(json.dumps(unit))
        self.receipt['artifacts'] = [self.ref(row['path']) for row in self.receipt['artifacts']]
        self.save_receipt()
        with self.assertRaisesRegex(ValueError, 'duration_changed'): self.inspect()

    def test_incomplete_groups_and_symlink_block(self):
        self.spec['group_ids'] = ['g1']; self.receipt['specSha256'] = c.canonical_sha256(self.spec)
        self.save_receipt()
        with self.assertRaisesRegex(ValueError, 'incomplete_preview'): self.inspect()
        self.spec.pop('group_ids'); self.receipt['specSha256'] = c.canonical_sha256(self.spec); self.save_receipt()
        path = self.out / 'units/unit-0000.wav'; real = path.with_name('saved.wav'); path.rename(real)
        path.symlink_to(real)
        with self.assertRaisesRegex(ValueError, 'Symlink'): self.inspect()

    def test_v2_requires_clock_proof_and_fixture_cannot_claim_runtime(self):
        self.receipt['schemaVersion'] = subject.worker.SCHEMA
        self.save_receipt()
        with self.assertRaisesRegex(ValueError,'worker_clock_missing'):self.inspect()
        self.receipt.update(clockHandshake=dict(launch={},finished={},joined={}),offlineFixture=True,
            nativeRuntimeBinding={'untrusted':'claim'})
        self.save_receipt()
        with patch.object(subject.worker.clock,'validate_worker_handshake',return_value={}):
            with self.assertRaisesRegex(ValueError,'fixture_cannot_claim_runtime'):self.inspect()

    def test_v2_rejects_invalid_real_clock_without_relying_on_worker_mock(self):
        self.receipt.update(schemaVersion=subject.worker.SCHEMA,
            clockHandshake=dict(launch={},finished={},joined={}),offlineFixture=True,nativeRuntimeBinding=None)
        self.save_receipt()
        with self.assertRaises(ValueError):self.inspect()


class OriginalSourceInspectionTests(unittest.TestCase):
    def setUp(self):
        self.f = sources.SourceEvidenceTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.root = self.f.root
        store = budget.BudgetStore(self.root / 'budget', authority())
        self.provider = provider.DiagnosticProvider(store, self.f.config, domain=lambda: '7' * 64)
        self.f.state.update(schemaVersion=provider.SCHEMA, authoritySha256=store.authority_sha256,
                            clockDomain='7' * 64, startedMonotonic=1.)
        self.f.write('budget/' + budget.STORE_ID + '/provider-run/state.json', self.f.state)
        self.f.write('budget/' + budget.STORE_ID + '/state.json', dict(schemaVersion=budget.SCHEMA,
            authority=store.authority, storeSha256=store.store_sha256, reservations={}))

    def inspect(self, expected=('zh-Hans',), entries=None):
        return subject.inspect_delivery(self.root, self.provider, self.f.context,
            {'zh-Hans': {}} if entries is None else entries, expected_locales=expected)

    def test_original_nonconfirmed_source_stays_pending_and_read_only(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(subject, '_inspect_preview', return_value={'previewStatus': 'preview_only'}):
            result = self.inspect()
        self.assertEqual(result['sourceMachineStatus'], 'unconfirmed_findings_human_pending')
        self.assertFalse(result['productionEligible']); self.assertFalse(result['formalAudioPackageCreated'])
        self.assertFalse(result['publicationAuthorized']); self.assertEqual(result['modelCalls'], 0)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_original_review_tamper_and_unknown_provider_block_before_preview(self):
        with patch.object(subject, '_inspect_preview') as inspect:
            self.f.request['machineIssues'][0]['reviewStatus'] = 'approved'; self.f.refresh()
            with self.assertRaises(ValueError): self.inspect()
            inspect.assert_not_called()
        self.f.request['machineIssues'][0]['reviewStatus'] = 'human_pending'; self.f.refresh()
        self.f.state['requests']['review']['state'] = 'outcome_unknown'
        self.f.write('budget/' + budget.STORE_ID + '/provider-run/state.json', self.f.state)
        with self.assertRaisesRegex(ValueError, 'unknown_provider'): self.inspect()

    def test_missing_duplicate_or_extra_locales_rejected(self):
        for expected, entries in ((('zh-Hans', 'ko'), {'zh-Hans': {}}),
                                  (('zh-Hans', 'zh-Hans'), {'zh-Hans': {}}),
                                  (('zh-Hans',), {'zh-Hans': {}, 'ko': {}})):
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, 'locale_coverage'):
                self.inspect(expected, entries)


if __name__ == '__main__':
    unittest.main()
