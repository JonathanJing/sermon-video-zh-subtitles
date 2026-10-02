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


class FreshDeliveryInspectionTests(unittest.TestCase):
    def setUp(self):
        from tests import test_sermon_fresh_diagnostic as fixtures
        from tests.test_sermon_fresh_source_evidence import freeze_current
        f = fixtures.FreshSourceTests(); f.setUp(); self.addCleanup(f.doCleanups)
        self.f = f; self.prepared = freeze_current(f)
        self.entries = {locale: {} for locale in ('es', 'ko', 'zh-Hans')}

    def inspect(self, **overrides):
        options = dict(expected_locales=tuple(self.entries), plan=self.f.plan, source_evidence=self.prepared['evidence'])
        options.update(overrides)
        return subject.inspect_fresh_delivery(self.f.root, self.f.subject, self.prepared['context'], self.entries, **options)

    def test_fresh_contract_avoids_legacy_four_pending_and_keeps_full_locale_gate(self):
        from tests.test_sermon_fresh_source_evidence import existing_bytes
        before = existing_bytes(self.f.f.root); calls = len(self.f.f.transport.observations)
        with patch.object(subject.source_evidence, 'validate_prior_source_evidence', side_effect=AssertionError('legacy forbidden')), \
             patch.object(subject, '_inspect_preview', side_effect=lambda root, runtime, context, locale, envelope, files:
                 {'previewStatus': 'preview_only', 'targetLocale': locale, 'realHumanAcceptance': 'pending'}) as native, \
             patch.object(self.f.subject, '_locked', side_effect=AssertionError('lock forbidden')):
            first = self.inspect(); self.assertEqual(first, self.inspect())
        self.assertEqual(native.call_count, 6)
        self.assertEqual(first['schemaVersion'], subject.FRESH_SCHEMA)
        self.assertEqual(set(first['locales']), set(self.entries)); self.assertEqual(first['modelCalls'], 0)
        self.assertEqual(first['sourceMachineStatus'], 'returned_review_human_pending')
        self.assertEqual(set(first['pendingRealGates'].values()), {'pending'})
        self.assertFalse(first['publicationAuthorized']); self.assertFalse(first['productionEligible'])
        self.assertEqual(before, existing_bytes(self.f.f.root)); self.assertEqual(calls, len(self.f.f.transport.observations))
        self.assertNotIn(str(self.f.root), json.dumps(first))
        # The default legacy entry still rejects this actual Fresh directory.
        with self.assertRaises(FileNotFoundError):
            subject.inspect_delivery(self.f.root, self.f.subject, self.prepared['context'], self.entries, expected_locales=tuple(self.entries))

    def test_unknown_provider_missing_locale_and_source_tamper_block_before_native(self):
        with patch.object(subject, '_inspect_preview') as native:
            with self.assertRaisesRegex(c.ContractError, 'locale_coverage'):
                self.inspect(expected_locales=('es', 'ko'))
            path = self.f.root/'budget'/budget.STORE_ID/'provider-run/state.json'
            state = json.loads(path.read_bytes()); original = path.read_bytes()
            next(iter(state['requests'].values()))['state'] = 'outcome_unknown'; path.write_bytes(c.canonical_bytes(state))
            with self.assertRaisesRegex(c.ContractError, 'unknown_provider'): self.inspect()
            path.write_bytes(original)
            self.prepared['evidence']['sourceReviewStatus'] = 'approved'
            with self.assertRaises(c.ContractError): self.inspect()
            native.assert_not_called()

    def test_expired_closed_inspection_repeats_without_dispatch_deadline_reset_or_original_result_write(self):
        from scripts import sermon_diagnostic_attempts as attempts
        from tests.test_sermon_fresh_source_evidence import existing_bytes
        # Time can pass while inspecting complete evidence; it cannot authorize
        # another execution. Real worker deadline/native proofs remain tested
        # by PreviewInspectionTests and the dedicated worker integrations.
        attempts.close_parent(self.f.root/'run-plan.json', instruction_reference_sha256='f'*64)
        original_result = self.f.root/'original-incomplete-result.json'
        original_result.write_bytes(c.canonical_bytes({'status': 'incomplete', 'delivery': 'failed'}))
        before = existing_bytes(self.f.f.root)
        with patch.object(subject, '_inspect_preview', return_value={'previewStatus': 'preview_only'}), \
             patch.object(self.f.subject, '_locked', side_effect=AssertionError('lock forbidden')), \
             patch.object(self.f.subject, '_remaining', side_effect=AssertionError('deadline execution forbidden')), \
             patch.object(self.f.subject, 'monotonic', return_value=10**20):
            first = subject.inspect_completed_fresh_delivery(self.f.root, self.f.subject, self.prepared['context'], self.entries,
                expected_locales=tuple(self.entries), plan=self.f.plan, source_evidence=self.prepared['evidence'])
            second = subject.inspect_completed_fresh_delivery(self.f.root, self.f.subject, self.prepared['context'], self.entries,
                expected_locales=tuple(self.entries), plan=self.f.plan, source_evidence=self.prepared['evidence'])
        self.assertEqual(first, second); self.assertEqual(first['schemaVersion'], subject.REINSPECTION_SCHEMA)
        self.assertTrue(first['inspectionOnly']); self.assertFalse(first['grantsExecutionAuthority'])
        self.assertEqual(first['modelCalls'], 0); self.assertEqual(first['ledgerWrites'], 0)
        self.assertEqual(first['originalPlanSha256'], c.canonical_sha256(self.f.plan))
        self.assertEqual(before, existing_bytes(self.f.f.root))
        closed = self.f.root/'budget'/budget.STORE_ID/'provider-run/closed.json'
        closed.write_bytes(c.canonical_bytes({'budgetStateFileSha256': 'f'*64, 'closureEvidenceSha256': 'f'*64}))
        with patch.object(subject, '_inspect_preview') as native, self.assertRaisesRegex(c.ContractError, 'closed_evidence_changed'):
            subject.inspect_completed_fresh_delivery(self.f.root, self.f.subject, self.prepared['context'], self.entries,
                expected_locales=tuple(self.entries), plan=self.f.plan, source_evidence=self.prepared['evidence'])
        native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
