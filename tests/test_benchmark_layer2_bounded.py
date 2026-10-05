"""Real production prompt/cache/transport seams with an offline provider."""
import copy
import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

from scripts.experiments import benchmark_layer2_bounded as subject
from scripts import sermon_accounting as accounting
from tests import test_run_target_language_models as fixtures


class BoundedLayer2BenchmarkTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.RunTargetLanguageModelsTests('test_astra_then_sol_each_group_and_admit_human_pending')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.fixture, self.f, self.out = fixture, fixture.fixture, fixture.out
        self.request = subject.producer.prepare_request(self.f.source, self.f.anchor, self.f.policy)
        self.plan = subject.production.group_plan(self.request, self.f.anchor)
        self.selected = subject.capture_prompts(self.f.source, self.f.anchor, self.f.policy,
            self.plan, [0, 1], self.out / 'capture', self.f.plugin_path)
        for name, value in (('source', self.f.source), ('anchor', self.f.anchor)):
            subject.save(self.out / 'frozen' / (name + '.json'), value)
        policies = {}
        for workers in (1, 2, 3):
            policy = copy.deepcopy(self.f.policy); policy['batching']['workers'] = workers
            policy['componentSha256']['batching'] = subject.policy_tools.canonical_sha256(policy['batching'])
            policies[str(workers)] = policy
        self.manifest = {'policies': policies, 'selected': self.selected, 'fullOriginalGroups': 2,
            'requestLimits': subject.LIMITS,
            'plugin': {'path': str(self.f.plugin_path), 'implementationSha256': self.f.plugin_sha}}
        self.ledger = subject.Ledger(self.out, 'a' * 64)
        self.calls, self.active, self.peak = [], 0, 0
        self.lock = threading.Lock()

    def response(self, request, *_args, **_kwargs):
        payload = json.loads(request.data)
        data = json.loads(payload['messages'][1]['content'])
        group = next(g for g in self.f.evidence['groups'] if g['sourceUnitIds'] == data['sourceUnitIds'])
        with self.lock:
            self.calls.append(copy.deepcopy(payload)); number = len(self.calls)
        keys = ['sourceUnitIds', 'targetUtterances', 'coverage']
        if payload['model'] == 'gpt-6-sol':
            keys.append('semanticReview')
            self.assertEqual(data['astraDraft']['targetUtterances'], group['targetUtterances'])
            self.assertNotIn('实验占位', str(data['astraDraft']))
        result = {key: copy.deepcopy(group[key]) for key in keys}
        result['translationGroupId'] = data['translationGroupId']
        return {'id': f'fixture-response-{number}', 'model': payload['model'], 'service_tier': 'default',
            'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150,
                'prompt_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0},
                'completion_tokens_details': {'reasoning_tokens': 10}},
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}]}

    def test_captured_prompts_match_actual_production_and_keep_full_context(self):
        actual = []
        def call(key, payload):
            answer = self.fixture.fake_call(key, payload)
            actual.append(payload)
            return answer
        # Compare the same pinned-plugin production path that capture_prompts
        # uses; omitting the plugin deliberately selects the legacy prompt.
        formal_out = self.out / 'formal-fixture'
        subject.production.run(self.f.source, self.f.anchor, self.f.policy,
            formal_out, 'fixture-key', call, plugin_path=self.f.plugin_path)
        receipt = subject.read(formal_out / 'rule-preflight.json')
        for index, row in enumerate(self.selected):
            translate = subject.production.model_payload('translator', row['prompts']['translator'], self.f.policy)
            self.assertEqual(translate, actual[index * 2])
            self.assertIn('modelRules', row['prompts']['translator']['input'])
            subject.production.rule_preflight.verify_model_prompt(
                'translator', row['prompts']['translator'], receipt, self.f.policy)
            reviewed = copy.deepcopy(row['prompts']['reviewer'])
            reviewed['input']['astraDraft'] = json.loads(actual[index * 2 + 1]['messages'][1]['content'])['astraDraft']
            self.assertEqual(subject.production.model_payload('reviewer', reviewed, self.f.policy), actual[index * 2 + 1])
            subject.production.rule_preflight.verify_model_prompt('reviewer', reviewed, receipt, self.f.policy)
        partial = subject.capture_prompts(self.f.source, self.f.anchor, self.f.policy,
            self.plan, [0], self.out / 'partial-capture', self.f.plugin_path)
        self.assertEqual(partial[0]['prompts']['translator']['input']['context']['after'], self.request['sourceUnits'][1:])
        self.assertFalse((self.out / 'partial-capture/evidence.json').exists())

    def test_parallel_real_transport_seam_order_accounting_and_cache_no_repayment(self):
        barrier = threading.Barrier(2)
        def execute(request, *_args, **_kwargs):
            payload = json.loads(request.data)
            with self.lock: self.active += 1; self.peak = max(self.active, self.peak)
            try:
                if payload['model'] == 'gpt-6-astra':
                    barrier.wait(timeout=5)
                    if self.plan[0]['translationGroupId'] in payload['messages'][1]['content']: time.sleep(.02)
                return self.response(request)
            finally:
                with self.lock: self.active -= 1
        with patch.object(subject.transport, 'execute', execute):
            result = subject.run_arm(self.out, self.manifest, 2, 'fixture-key', self.ledger)
        self.assertEqual(self.peak, 2)
        self.assertEqual([g['translationGroupId'] for g in result['groups']], [g['translationGroupId'] for g in self.plan])
        self.assertEqual(len(self.calls), 4)
        self.assertFalse(result['formalCoverageComplete'] or result['humanApproval'] or result['releaseEligible'])
        events, damaged = accounting.read_events(self.out / 'workers-2/accounting')
        self.assertFalse(damaged)
        finishes = [event for event in events if event.get('event') == 'stage_finished']
        review = [e for e in finishes if str(e.get('stage', '')).startswith('experiment.reviewer.group')]
        self.assertTrue(review and all(e.get('dependsOn') for e in review))
        ledger_before = subject.read(self.ledger.path)
        (self.out / 'workers-2/partial-results.json').unlink()
        # Recover a returned raw under a marker; successes remain immutable.
        cache = self.out / 'workers-2/group-0002-sol.json'; original = cache.read_bytes(); cache.unlink()
        subject.save(cache.with_suffix('.started.json'), {'status': 'returned_raw_recovery'})
        with patch.object(subject.transport, 'execute', side_effect=AssertionError('Cache recovery repaid')):
            subject.run_arm(self.out, self.manifest, 2, 'fixture-key', self.ledger)
        self.assertEqual(cache.read_bytes(), original)
        self.assertEqual(subject.read(self.ledger.path), ledger_before)

    def test_unknown_request_stops_whole_arm_and_preserves_marker_without_retry(self):
        with patch.object(subject.transport, 'execute', side_effect=subject.transport.ProviderTimeout('fixture_unknown')) as call:
            with self.assertRaises(subject.transport.ProviderTimeout):
                subject.run_arm(self.out, self.manifest, 1, 'fixture-key', self.ledger)
        self.assertEqual(call.call_count, 1)
        marker = self.out / 'workers-1/group-0001-astra.started.json'
        self.assertTrue(marker.exists())
        self.assertFalse(marker.with_name('group-0001-astra.raw.json').exists())
        with self.assertRaisesRegex(ValueError, 'halted'):
            subject.Ledger(self.out, 'a' * 64)
        self.assertEqual(len(subject.read(self.ledger.path)['reservations']), 1)

    def test_incomplete_response_remains_raw_and_blocks_sol(self):
        def incomplete(request, *_args):
            response = self.response(request)
            response['choices'][0]['finish_reason'] = 'length'
            return response
        with patch.object(subject.transport, 'execute', incomplete):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                subject.run_arm(self.out, self.manifest, 1, 'fixture-key', self.ledger)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue((self.out / 'workers-1/group-0001-astra.raw.json').exists())
        failure = subject.read(self.out / 'workers-1/group-0001-failure.json')
        self.assertEqual(failure['failureCategory'], 'response_validation_failed')

    def test_semantic_failure_is_separate_from_successful_api_execution(self):
        def fail_review(request, *_args):
            response = self.response(request)
            if response['model'] == 'gpt-6-sol':
                result = json.loads(response['choices'][0]['message']['content'])
                result['semanticReview']['status'] = 'fail'; result['semanticReview']['issues'] = ['fixture concern']
                response['choices'][0]['message']['content'] = json.dumps(result)
            return response
        with patch.object(subject.transport, 'execute', fail_review):
            with self.assertRaises(subject.SemanticFailed):
                subject.run_arm(self.out, self.manifest, 1, 'fixture-key', self.ledger)
        self.assertEqual(len(self.calls), 2)
        rows = subject.read(self.ledger.path)['reservations'].values()
        self.assertTrue(all(row['status'] == 'response_returned' and row['usage'] is not None for row in rows))
        self.assertEqual(subject.read(self.out / 'workers-1/group-0001-failure.json')['failureCategory'], 'semantic_failed')

    def test_full_matrix_maximum_pricing_caps_are_recomputable(self):
        self.assertEqual(24 * (subject.cost('gpt-6-astra', 8192, 2048) + subject.cost('gpt-6-sol', 8192, 2048)), 5_898_240)
        self.assertEqual(24 * (subject.cost('gpt-6-astra', 8192, 2048, worst=False) + subject.cost('gpt-6-sol', 8192, 2048, worst=False)), 5_308_416)
        self.assertEqual(subject.CAPS['callsPerArm'] * 3, subject.CAPS['calls'])
        self.assertGreater(subject.CAPS['costMicrousd'], 5_898_240)

    def test_unsynced_reservation_never_calls_provider(self):
        with patch.object(subject, 'persist_budget', side_effect=subject.BudgetWriteFailed('fixture sync failure')), \
                patch.object(subject.transport, 'execute', side_effect=AssertionError('Unsynced budget paid')) as call:
            with self.assertRaises(subject.BudgetWriteFailed):
                subject.run_arm(self.out, self.manifest, 1, 'fixture-key', self.ledger)
        self.assertEqual(call.call_count, 0)
        self.assertTrue((self.out / 'workers-1/group-0001-astra.started.json').exists())

    def test_tampered_cache_cannot_override_returned_raw(self):
        with patch.object(subject.transport, 'execute', self.response):
            subject.run_arm(self.out, self.manifest, 1, 'fixture-key', self.ledger)
        (self.out / 'workers-1/partial-results.json').unlink()
        path = self.out / 'workers-1/group-0001-astra.json'
        value = subject.read(path); value['result']['targetUtterances'] = ['篡改。']
        value['result']['coverage'][0]['targetText'] = '篡改。'
        path.write_text(json.dumps(value))
        with patch.object(subject.transport, 'execute', side_effect=AssertionError('Tampered cache paid')):
            with self.assertRaisesRegex(ValueError, 'Cached response changed'):
                subject.run_arm(self.out, self.manifest, 1, 'fixture-key', self.ledger)

    def local_pause(self):
        # Smaller portable instance of the real thirteen-cache pause: complete
        # one group, return next Astra, reject its Sol locally before dispatch.
        row=self.selected[1]
        draft={key:copy.deepcopy(self.f.evidence['groups'][1][key]) for key in
               ('sourceUnitIds','targetUtterances','coverage')}
        draft['translationGroupId']=row['group']['translationGroupId']
        prompt=copy.deepcopy(row['prompts']['reviewer']);prompt['input']['astraDraft']=draft
        payload=subject.production.model_payload('reviewer',prompt,self.f.policy)
        row['prompts']['reviewer']['instruction']+=' '*(8193-subject.provider_limits._input_upper_bound(payload))
        parent={**self.manifest,'schemaVersion':subject.SCHEMA,'experimentOnly':True,'formalCoverageComplete':False,
                'caps':subject.CAPS,'code':subject.frozen_code()}
        subject.save(self.out/'frozen/baseline-policy.json',self.f.policy)
        subject.save(self.out/'frozen/group-plan.json',self.plan)
        parent['inputHashes']={name:subject.digest(self.out/'frozen'/(name+'.json')) for name in
                              ('source','anchor','baseline-policy','group-plan')}
        subject.save(self.out/'frozen/manifest.json',parent)
        self.ledger.path.unlink()
        self.ledger=subject.Ledger(self.out,subject.digest(self.out/'frozen/manifest.json'))
        with patch.object(subject.transport,'execute',self.response):
            with self.assertRaisesRegex(ValueError,'provider_input_bound_exceeded'):
                subject.run_arm(self.out,parent,1,'fixture-key',self.ledger)
        self.assertEqual(len(self.calls),3)
        subject.save(self.out/'status.json',{'status':'stopped','errorClass':'ValueError'})
        subject.archive(self.out/'local-admission-revision/parent-benchmark.py',Path(subject.__file__).read_bytes())
        return parent

    def test_explicit_local_revision_preserves_caches_budget_and_api_payload(self):
        parent=self.local_pause()
        old_manifest=(self.out/'frozen/manifest.json').read_bytes()
        old_ledger=(self.out/'budget-ledger.json').read_bytes()
        old_files={p:p.read_bytes() for p in (self.out/'workers-1').glob('group-*.json') if '-failure' not in p.name}
        with patch.object(subject.transport,'execute',side_effect=AssertionError('Migration paid')):
            record=subject.revise_local_input_admission(self.out,expected_returned_calls=3)
        self.assertEqual(record['cachedCallsPreserved'],3)
        self.assertEqual((self.out/'frozen/manifest.json').read_bytes(),old_manifest)
        self.assertEqual((self.out/'local-admission-revision/parent-ledger.json').read_bytes(),old_ledger)
        active=subject.checked(self.out)
        self.assertEqual(active['caps'],parent['caps'])
        self.assertEqual(active['requestLimits']['maxInputTokens'],16384)
        for key in ('translator','reviewer'):
            if key=='reviewer':continue  # paused Sol had never passed old gate
            self.assertEqual(subject.production.model_payload(key,self.selected[0]['prompts'][key],self.f.policy,subject.LIMITS),
                             subject.production.model_payload(key,self.selected[0]['prompts'][key],self.f.policy,active['requestLimits']))
        ledger=subject.Ledger(self.out,subject.digest(subject.manifest_path(self.out)))
        with patch.object(subject.transport,'execute',self.response):
            result=subject.run_arm(self.out,active,1,'fixture-key',ledger)
        self.assertEqual(len(self.calls),4)  # old three paid caches were not sent
        self.assertTrue(result['recoveredBaseline'])
        self.assertFalse(result['activeSegmentSumIsUninterruptedWall'])
        for p,data in old_files.items():self.assertEqual(p.read_bytes(),data)

    def test_unknown_cannot_migrate_or_release_halt(self):
        self.local_pause()
        path=self.out/'budget-ledger.json';state=subject.read(path)
        next(iter(state['reservations'].values()))['status']='request_unconfirmed'
        subject.atomic_json(path,state);before=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'Unknown/invalid usage'):
            subject.revise_local_input_admission(self.out,expected_returned_calls=3)
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse((self.out/'active-experiment.json').exists())

    def test_prior_arm_or_raw_path_tampering_denies_revision(self):
        self.local_pause()
        path=self.out/'budget-ledger.json';state=subject.read(path);row=next(iter(state['reservations'].values()))
        for key,value in (('arm',2),('rawPath','different.json')):
            original=row[key];row[key]=value;subject.atomic_json(path,state);before=path.read_bytes()
            with self.assertRaisesRegex(ValueError,'arm/raw path identity'):
                subject.revise_local_input_admission(self.out,expected_returned_calls=3)
            self.assertEqual(path.read_bytes(),before);row[key]=original

    def test_migration_interruption_stays_pending_and_never_dispatches(self):
        self.local_pause();original=subject.save
        def interrupt(path,value):
            if Path(path).name=='active-experiment.json':raise OSError('fixture pointer write failed')
            original(path,value)
        with patch.object(subject,'save',interrupt),self.assertRaises(OSError):
            subject.revise_local_input_admission(self.out,expected_returned_calls=3)
        state=subject.read(self.out/'budget-ledger.json')
        self.assertEqual(state['haltReason'],'local_admission_revision_pending')
        self.assertFalse((self.out/'active-experiment.json').exists())
        with self.assertRaisesRegex(ValueError,'halted'):
            subject.Ledger(self.out,state['identitySha256'])


if __name__ == '__main__': unittest.main()
