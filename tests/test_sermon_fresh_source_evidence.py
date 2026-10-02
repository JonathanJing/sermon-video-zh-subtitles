"""Fresh-specific Source inspection over actual synthetic builders and receipts."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch

from scripts import sermon_fresh_source_evidence as subject
from scripts import sermon_public_snapshot as public, sermon_review_budget as budget, sermon_review_contracts as c
from tests import test_sermon_fresh_diagnostic as fresh_fixtures
from tests import test_sermon_cached_fresh_diagnostic_source as cache_fixtures


def freeze_current(fixture):
    prepared = fixture.prepare()
    public.save_once(fixture.root/'run-plan.json', fixture.plan)
    public.save_once(fixture.root/'fresh-source-recipe.json', {'files': {key: {'path': str(value),
        'sha256': subject.cache._ref(value)['bytesSha256']} for key, value in fixture.recipe.items() if key.endswith('_path')},
        'runMFA': False, 'authorizationSha256': c.canonical_sha256(fixture.authorization)})
    return prepared


def existing_bytes(*roots):
    return {str(path): path.read_bytes() for root in roots for path in root.rglob('*') if path.is_file()}


class CurrentFreshEvidenceTests(unittest.TestCase):
    def setUp(self):
        f = fresh_fixtures.FreshSourceTests(); f.setUp(); self.addCleanup(f.doCleanups)
        self.f = f; self.prepared = freeze_current(f)
        self.calls = len(f.f.transport.observations)

    def inspect(self):
        return subject.validate_fresh_source_evidence(self.f.root, self.f.plan, self.f.subject,
            self.prepared['context'], self.prepared['evidence'])

    def test_actual_current_receipts_hash_only_read_only_repeat_without_locks_or_calls(self):
        before = existing_bytes(self.f.f.root)
        with patch.object(self.f.subject, '_locked', side_effect=AssertionError('lock forbidden')), \
             patch.object(self.f.subject, 'source_check_payload', side_effect=AssertionError('provider method forbidden')):
            first = self.inspect(); self.assertEqual(first, self.inspect())
        self.assertEqual(first['schemaVersion'], subject.SCHEMA)
        self.assertEqual(first['currentSourceProviderCalls'], 2)
        self.assertEqual(first['historicalSourceProviderCalls'], 0)
        self.assertEqual(first['humanAcceptance'], 'pending'); self.assertFalse(first['productionEligible'])
        self.assertEqual(first['modelCalls'], 0)
        self.assertEqual(before, existing_bytes(self.f.f.root))
        self.assertEqual(self.calls, len(self.f.f.transport.observations))
        self.assertNotIn(str(self.f.root), json.dumps(first))
        self.assertNotIn(self.f.f.transcript, json.dumps(first))

    def test_no_legacy_files_or_four_findings_contract_is_required(self):
        self.assertFalse((self.f.root/'simulated-review-inputs').exists())
        self.assertEqual(self.inspect()['status'], 'fresh_source_evidence_validated')

    def test_wrong_schema_expected_plan_context_and_receipt_cannot_fallback(self):
        for key, value in (('schemaVersion', 'unknown'), ('sourceReviewStatus', 'approved'), ('sourceReviewContentSha256', 'f'*64)):
            original = deepcopy(self.prepared['evidence']); self.prepared['evidence'][key] = value
            with self.subTest(key=key), self.assertRaises(c.ContractError): self.inspect()
            self.prepared['evidence'] = original
        for name in ('run-plan.json', 'diagnostic-context.json', 'fresh-source-evidence.json'):
            path = self.f.root/name; raw = path.read_bytes(); changed = json.loads(raw)
            if name == 'run-plan.json': changed['providerConfig']['maxRequests'] -= 1
            elif name == 'diagnostic-context.json': changed['productionEligible'] = True
            else: changed['sourceReviewStatus'] = 'approved'
            path.write_bytes(c.canonical_bytes(changed))
            with self.subTest(name=name), self.assertRaises(c.ContractError): self.inspect()
            path.write_bytes(raw)
        path = self.f.root/'fresh-source-evidence.json'; raw = path.read_bytes(); path.unlink()
        with self.assertRaises(FileNotFoundError): self.inspect()
        path.write_bytes(raw)

    def test_source_alignment_recipe_audio_summary_and_producer_drift_rejected(self):
        paths = [self.f.root/'aligned-segments.json', self.f.audio, self.f.root/'source-summary.json']
        for path in paths:
            original = path.read_bytes(); path.write_bytes(original+b' ')
            with self.subTest(path=path.name), self.assertRaises(c.ContractError): self.inspect()
            path.write_bytes(original)
        original = self.f.plan['executionIdentity']['loadedProjectCodeSha256']['scripts/sermon_fresh_diagnostic_source.py']
        self.f.plan['executionIdentity']['loadedProjectCodeSha256']['scripts/sermon_fresh_diagnostic_source.py'] = 'f'*64
        (self.f.root/'run-plan.json').write_bytes(c.canonical_bytes(self.f.plan))
        with self.assertRaises(c.ContractError): self.inspect()
        self.f.plan['executionIdentity']['loadedProjectCodeSha256']['scripts/sermon_fresh_diagnostic_source.py'] = original

    def test_usage_cannot_be_fabricated_even_when_raw_refs_are_rebound(self):
        folder = self.f.root/'budget'/budget.STORE_ID/'provider-run'
        reference = self.prepared['evidence']['sourceCheck']; path = folder/(reference['modelCallId']+'.json')
        receipt, _ = public.read_snapshot(path); receipt['response']['usage']['prompt_tokens'] += 1
        path.write_bytes(c.canonical_bytes(receipt)); new_sha = c.bytes_sha256(path.read_bytes())
        state, _ = public.read_snapshot(folder/'state.json'); state['requests'][reference['modelCallId']]['receiptSha256'] = new_sha
        (folder/'state.json').write_bytes(c.canonical_bytes(state)); reference['receiptSha256'] = new_sha
        simulation, _ = public.read_snapshot(self.f.root/'simulation-authorization.json')
        simulation['sourceReviewReceiptSha256'] = new_sha
        (self.f.root/'simulation-authorization.json').write_bytes(c.canonical_bytes(simulation))
        self.prepared['context']['simulationAuthorizationRef'] = c.canonical_sha256(simulation)
        (self.f.root/'diagnostic-context.json').write_bytes(c.canonical_bytes(self.prepared['context']))
        self.prepared['evidence']['contextSha256'] = c.canonical_sha256(self.prepared['context'])
        (self.f.root/'fresh-source-evidence.json').write_bytes(c.canonical_bytes(self.prepared['evidence']))
        with self.assertRaisesRegex(c.ContractError, 'fresh_delivery_source_usage_changed'): self.inspect()

    def test_unknown_provider_and_source_changes_during_inspection_rejected(self):
        path = self.f.root/'budget'/budget.STORE_ID/'provider-run/state.json'; state, raw = public.read_snapshot(path)
        next(iter(state['requests'].values()))['state'] = 'outcome_unknown'; path.write_bytes(c.canonical_bytes(state))
        with self.assertRaisesRegex(c.ContractError, 'outcome_unknown'): self.inspect()
        path.write_bytes(raw)
        original = subject._Snapshots.recheck
        def mutate(files):
            source = self.f.root/'source.json'; source.write_bytes(source.read_bytes()+b' ')
            return original(files)
        with patch.object(subject._Snapshots, 'recheck', mutate), self.assertRaisesRegex(c.ContractError, 'snapshot_changed'):
            self.inspect()


class CachedFreshEvidenceTests(unittest.TestCase):
    def setUp(self):
        f = cache_fixtures.CachedFreshSourceTests(); f.setUp(); self.addCleanup(f.doCleanups)
        self.f = f; self.prepared = f.prepare()

    def inspect(self):
        return subject.validate_fresh_source_evidence(self.f.root, self.f.plan, self.f.subject,
            self.prepared['context'], self.prepared['evidence'])

    def test_closed_parent_cache_proof_remains_historical_no_new_ledger_or_calls(self):
        before = existing_bytes(self.f.parent, self.f.root)
        with patch.object(self.f.subject, '_locked', side_effect=AssertionError('lock forbidden')):
            result = self.inspect(); self.assertEqual(result, self.inspect())
        self.assertEqual(result['historicalSourceProviderCalls'], 2); self.assertEqual(result['currentSourceProviderCalls'], 0)
        self.assertIsNone(result['asrReceiptSha256']); self.assertEqual(result['modelCalls'], 0)
        self.assertEqual(before, existing_bytes(self.f.parent, self.f.root))
        self.assertEqual(self.f.calls, len(self.f.fixture.f.transport.observations))
        self.assertNotIn(str(self.f.root), json.dumps(result))

    def test_missing_expected_schema_proof_context_or_parent_closure_fail_closed(self):
        for name in ('cached-source-proof.json', 'cached-source-authorization.json', 'simulation-authorization.json'):
            path = self.f.root/name; raw = path.read_bytes(); path.unlink()
            with self.subTest(name=name), self.assertRaises(FileNotFoundError): self.inspect()
            path.write_bytes(raw)
        closed = self.f.parent/'budget'/budget.STORE_ID/'provider-run/closed.json'; closed.unlink()
        with self.assertRaisesRegex(c.ContractError, 'closed_parent_required'): self.inspect()

    def test_cache_source_and_scope_drift_reject_without_dispatch(self):
        path = self.f.root/'source.json'; raw = path.read_bytes(); source = json.loads(raw)
        source['review']['humanApproval'] = True; path.write_bytes(c.canonical_bytes(source))
        with self.assertRaises(c.ContractError): self.inspect()
        path.write_bytes(raw)
        original = deepcopy(self.prepared['evidence']); self.prepared['evidence']['newASRCalls'] = 1
        with self.assertRaises(c.ContractError): self.inspect()
        self.prepared['evidence'] = original
        self.assertEqual(self.f.calls, len(self.f.fixture.f.transport.observations))


class MigratedCachedFreshEvidenceTests(unittest.TestCase):
    def migration_fixture(self, *, approved_identity=False):
        from scripts import sermon_source_producer_compatibility as compatibility
        from scripts import sermon_diagnostic_attempts as attempts, sermon_diagnostic_provider as provider
        f = fresh_fixtures.FreshSourceTests(); f.setUp(); self.addCleanup(f.doCleanups)
        prepared = freeze_current(f)
        current_identity = deepcopy(f.plan['executionIdentity'])
        if approved_identity:
            current_identity['loadedProjectCodeSha256'].update(compatibility.CURRENT_SOURCE_SHA256)
        # Build a synthetic historical parent before closing it. The approved
        # identity models only the three reviewed producer changes; the actual
        # current negative case deliberately retains additional code drift.
        # No live/historical receipt is edited.
        parent_plan = deepcopy(f.plan)
        parent_plan['executionIdentity']['loadedProjectCodeSha256'].update(compatibility.HISTORICAL_SOURCE_SHA256)
        parent_plan['providerConfig']['codeSha256'] = c.canonical_sha256(parent_plan['executionIdentity'])
        (f.root/'run-plan.json').write_bytes(c.canonical_bytes(parent_plan))
        state_path = f.root/'budget'/budget.STORE_ID/'provider-run/state.json'
        state, _ = public.read_snapshot(state_path); state['config'] = parent_plan['providerConfig']
        state_path.write_bytes(c.canonical_bytes(state))
        context = deepcopy(prepared['context']); context['runConfigSha256'] = c.canonical_sha256(parent_plan['providerConfig'])
        (f.root/'diagnostic-context.json').write_bytes(c.canonical_bytes(context))
        evidence = deepcopy(prepared['evidence']); evidence['contextSha256'] = c.canonical_sha256(context)
        (f.root/'fresh-source-evidence.json').write_bytes(c.canonical_bytes(evidence))
        attempts.close_parent(f.root/'run-plan.json', instruction_reference_sha256='f'*64)
        old = attempts.terminal_parent(parent_plan)
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()/'next'
        authorization = {'schemaVersion': attempts.AUTH_SCHEMA, 'parentPlanSha256': c.canonical_sha256(parent_plan),
            'parentSnapshotsSha256': c.canonical_sha256([old]), 'instructionReferenceSha256': 'f'*64,
            'newMaxRequests': 4, 'newHardLimitMicrousd': 1000000, 'newTotalWallSeconds': 1200,
            'cumulativeMaxRequests': 130, 'cumulativeHardLimitMicrousd': 50000000}
        plan, lineage = attempts.prepare_new_attempt(parent_plan, new_root=root, authorization=authorization,
            execution_identity=current_identity)
        attempts.persist_new_attempt(plan, lineage, authorization)
        runtime = provider.DiagnosticProvider(budget.BudgetStore(root/'budget', plan['authority']),
            plan['providerConfig'], executor=f.f.transport)
        with runtime._locked(): pass
        return f, root, plan, runtime

    def test_synthetic_approved_identity_v2_migration_zero_calls_and_tamper_rejection(self):
        from scripts import sermon_source_producer_compatibility as compatibility
        from scripts import sermon_log_profile as profile
        f, root, plan, runtime = self.migration_fixture(approved_identity=True)
        repository = Path(subject.cache.__file__).resolve().parents[1]
        approved_paths = {repository/path: sha for path, sha in compatibility.CURRENT_SOURCE_SHA256.items()}
        original_ref = subject.cache._ref
        observed_producers = set()
        def approved_fixture_ref(path):
            # Model only the read-only producer identity observation for the
            # reviewed historical transition. Actual current code is checked
            # independently below; receipts/media/state still use real bytes.
            ref = original_ref(path)
            resolved = Path(ref['path'])
            if resolved in approved_paths:
                observed_producers.add(resolved)
                ref = {**ref, 'bytesSha256': approved_paths[resolved]}
            return ref
        with patch.object(subject.cache, '_ref', side_effect=approved_fixture_ref):
            with profile.session(root/'logs', 'migration-fixture', work_kind='engineering', evidence_mode='synthetic'):
                result = subject.cache.prepare_source(plan, runtime, parent_plan_path=f.root/'run-plan.json', authorization=f.authorization)
            self.assertEqual(observed_producers, set(approved_paths))
            self.assertEqual(result['evidence']['schemaVersion'], 'sermon-cached-fresh-diagnostic-source-v2')
            self.assertEqual(result['evidence']['sourceProducerCompatibility']['migrationId'], compatibility.MIGRATION)
            self.assertEqual(result['evidence']['sourceProducerCompatibility']['currentInspectorProducerSha256'],
                             compatibility.CURRENT_SOURCE_SHA256)
            before = existing_bytes(f.root, root); calls = len(f.f.transport.observations)
            with patch.object(runtime, '_locked', side_effect=AssertionError('lock forbidden')):
                proof = subject.validate_fresh_source_evidence(root, plan, runtime, result['context'], result['evidence'])
            self.assertEqual(proof['sourceEvidenceSchema'], 'sermon-cached-fresh-diagnostic-source-v2')
            self.assertEqual(proof['currentSourceProviderCalls'], 0); self.assertEqual(proof['historicalSourceProviderCalls'], 2)
            self.assertEqual(before, existing_bytes(f.root, root)); self.assertEqual(calls, len(f.f.transport.observations))
            result['evidence']['sourceProducerCompatibility']['binding']['asrReceiptSha256'] = 'f'*64
            with self.assertRaises(c.ContractError):
                subject.validate_fresh_source_evidence(root, plan, runtime, result['context'], result['evidence'])

    def test_actual_current_unknown_revision_rejects_without_calls_locks_or_cache_artifacts(self):
        from scripts import sermon_source_producer_compatibility as compatibility
        f, root, plan, runtime = self.migration_fixture()
        repository = Path(subject.cache.__file__).resolve().parents[1]
        actual = {path: subject.cache._ref(repository/path)['bytesSha256']
                  for path in compatibility.CURRENT_SOURCE_SHA256}
        self.assertNotEqual(actual, compatibility.CURRENT_SOURCE_SHA256)
        self.assertTrue(all(plan['executionIdentity']['loadedProjectCodeSha256'][path] == sha
                            for path, sha in actual.items()))
        before = existing_bytes(f.root, root); calls = len(f.f.transport.observations)
        with patch.object(runtime, '_locked', side_effect=AssertionError('lock forbidden')):
            with self.assertRaisesRegex(c.ContractError, '^source_producer_compatibility_unknown_revision$'):
                subject.cache.prepare_source(plan, runtime, parent_plan_path=f.root/'run-plan.json', authorization=f.authorization)
        self.assertEqual(before, existing_bytes(f.root, root))
        self.assertEqual(calls, len(f.f.transport.observations))
        for name in ('source.json', 'anchor-manifest.json', 'cached-source-proof.json', 'diagnostic-context.json'):
            self.assertFalse((root/name).exists())


class CurrentMFAEvidenceTests(unittest.TestCase):
    def test_actual_builders_over_synthetic_mfa_receipt_replay_no_alignment_and_runtime_drift_rejected(self):
        from scripts import sermon_log_profile as profile, sermon_fresh_diagnostic_source as adapter
        f = fresh_fixtures.FreshSourceTests(); f.setUp(); self.addCleanup(f.doCleanups)
        folder = f.root/'budget'/budget.STORE_ID/'provider-run'
        state, _ = public.read_snapshot(folder/'state.json')
        call = next(key for key, row in state['requests'].items() if row['operationId'] == 'transcription.initial')
        asr_path = folder/(call+'.json'); receipt, _ = public.read_snapshot(asr_path)
        receipt['response']['text'] += ' Amen.'; asr_path.write_bytes(c.canonical_bytes(receipt))
        state['requests'][call]['receiptSha256'] = c.bytes_sha256(asr_path.read_bytes())
        (folder/'state.json').write_bytes(c.canonical_bytes(state))
        payload = f.subject.source_check_payload()
        review_call = next(key for key, row in state['requests'].items() if row['operationId'] == 'source.initial')
        review_path = folder/(review_call+'.json'); review, _ = public.read_snapshot(review_path)
        review['payloadSha256'] = c.canonical_sha256(payload); review_path.write_bytes(c.canonical_bytes(review))
        state['requests'][review_call]['receiptSha256'] = c.bytes_sha256(review_path.read_bytes())
        state['requests'][review_call]['requestSha256'] = review['payloadSha256']
        (folder/'state.json').write_bytes(c.canonical_bytes(state))
        from tests.test_sermon_mfa_identity import runtime_fixture, alignment_fixture
        runtime_path = f.root/'synthetic-runtime.json'
        runtime = runtime_fixture(f.root)
        files = runtime['runtime']['files']
        seed = deepcopy(runtime)
        seed['runtime'].update(adapterSha256='d'*64, executionHost='private-previous-host')
        runtime_path.write_bytes(c.canonical_bytes(seed))
        aligned = public.read_snapshot(f.recipe['prior_aligned_path'])[0]
        aligned[-1]['text'] += ' Amen.'; end = aligned[-1]['end']; aligned[-1]['end'] = end+.5
        aligned[-1]['wordTimes'].append({'text': 'Amen.', 'start': end, 'end': end+.5})
        def simulated_alignment(chunks, audio_path, outdir, **options):
            self.assertFalse(options['allow_spark_fallback']); self.assertIsNotNone(options['deadline_monotonic'])
            return alignment_fixture(f.plan, runtime, chunks, aligned)
        recipe = dict(f.recipe, run_mfa=True, local_runtime_path=runtime_path)
        with patch.object(adapter.mfa_backend, 'align_reference_chunks', side_effect=simulated_alignment) as align:
            prepared = f.prepare(run_mfa=True, local_runtime_path=runtime_path)
        align.assert_called_once(); self.assertEqual(prepared['evidence']['alignmentMode'], 'fresh_local_mfa')
        public.save_once(f.root/'run-plan.json', f.plan)
        public.save_once(f.root/'fresh-source-recipe.json', {'files': {key: {'path': str(value),
            'sha256': subject.cache._ref(value)['bytesSha256']} for key, value in recipe.items() if key.endswith('_path')},
            'runMFA': True, 'authorizationSha256': c.canonical_sha256(f.authorization)})
        before = existing_bytes(f.f.root); calls = len(f.f.transport.observations)
        with patch.object(adapter.mfa_backend, 'align_reference_chunks', side_effect=AssertionError('alignment forbidden')), \
             patch.object(f.subject, '_locked', side_effect=AssertionError('lock forbidden')):
            result = subject.validate_fresh_source_evidence(f.root, f.plan, f.subject, prepared['context'], prepared['evidence'])
        self.assertEqual(result['newMFACalls'], 0); self.assertEqual(result['modelCalls'], 0)
        self.assertEqual(before, existing_bytes(f.f.root)); self.assertEqual(calls, len(f.f.transport.observations))
        self.assertEqual(result['identity_comparison']['acceptance']['result'], 'accepted')
        # New evidence cannot silently downgrade if its comparison is missing.
        comparison_path = f.root/'mfa-identity-comparison.json'
        comparison_raw = comparison_path.read_bytes(); comparison_path.unlink()
        with self.assertRaises(FileNotFoundError):
            subject.validate_fresh_source_evidence(f.root, f.plan, f.subject, prepared['context'], prepared['evidence'])
        comparison_path.write_bytes(comparison_raw)
        # Inspect a synthetic legacy receipt without inventing an old event time
        # or rewriting its original evidence into the new contract.
        legacy = deepcopy(prepared['evidence'])
        legacy['schemaVersion'] = subject.CURRENT
        for key in ('mfaIdentityComparisonSha256', 'mfaIdentityPreflightSha256', 'sourceCausalitySha256'):
            legacy.pop(key)
        evidence_path = f.root/'fresh-source-evidence.json'; evidence_raw = evidence_path.read_bytes()
        evidence_path.write_bytes(c.canonical_bytes(legacy)); legacy_before = existing_bytes(f.f.root)
        historical = subject.validate_fresh_source_evidence(f.root, f.plan, f.subject, prepared['context'], legacy)
        self.assertIsNone(historical['identity_comparison']['observedAt'])
        self.assertEqual(legacy_before, existing_bytes(f.f.root))
        evidence_path.write_bytes(evidence_raw)
        # The real closed-parent cache path consumes the parent's MFA producer,
        # rechecks all bytes, and leaves original evidence/receipts unchanged.
        from scripts import sermon_diagnostic_attempts as attempts, sermon_diagnostic_provider as provider
        attempts.close_parent(f.root/'run-plan.json', instruction_reference_sha256='f'*64)
        terminal = attempts.terminal_parent(f.plan)
        new_root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()/'successor'
        authorization = {'schemaVersion': attempts.AUTH_SCHEMA, 'parentPlanSha256': c.canonical_sha256(f.plan),
            'parentSnapshotsSha256': c.canonical_sha256([terminal]), 'instructionReferenceSha256': 'f'*64,
            'newMaxRequests': 4, 'newHardLimitMicrousd': 1000000, 'newTotalWallSeconds': 1200,
            'cumulativeMaxRequests': 130, 'cumulativeHardLimitMicrousd': 50000000}
        new_plan, lineage = attempts.prepare_new_attempt(f.plan, new_root=new_root, authorization=authorization,
            execution_identity=f.plan['executionIdentity'])
        attempts.persist_new_attempt(new_plan, lineage, authorization)
        runtime_reader = provider.DiagnosticProvider(budget.BudgetStore(new_root/'budget', new_plan['authority']),
            new_plan['providerConfig'], executor=f.f.transport)
        with runtime_reader._locked(): pass
        frozen_parent = existing_bytes(f.root)
        with profile.session(new_root/'logs', 'cached-mfa-fixture', work_kind='engineering', evidence_mode='synthetic'):
            cached = subject.cache.prepare_source(new_plan, runtime_reader, parent_plan_path=f.root/'run-plan.json',
                                                  authorization=f.authorization)
        with patch.object(runtime_reader, '_locked', side_effect=AssertionError('lock forbidden')):
            checked = subject.validate_fresh_source_evidence(new_root, new_plan, runtime_reader,
                cached['context'], cached['evidence'])
        self.assertEqual(checked['historicalSourceProviderCalls'], 2)
        self.assertEqual(checked['newMFACalls'], 0)
        self.assertEqual(frozen_parent, existing_bytes(f.root))
        self.assertEqual(calls, len(f.f.transport.observations))
        Path(files['acoustic_model']['path']).write_bytes(b'changed weights')
        with self.assertRaisesRegex(c.ContractError, 'dependency_file_changed'):
            subject.validate_fresh_source_evidence(new_root, new_plan, runtime_reader, cached['context'], cached['evidence'])
        with self.assertRaisesRegex(c.ContractError, 'mfa_identity_receipt_changed|dependency_file_changed'):
            subject.validate_fresh_source_evidence(f.root, f.plan, f.subject, prepared['context'], prepared['evidence'])


if __name__ == '__main__':
    unittest.main()
