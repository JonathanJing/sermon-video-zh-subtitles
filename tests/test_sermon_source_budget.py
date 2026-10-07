import concurrent.futures
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path

from scripts import sermon_source_budget as subject
from scripts import sermon_workflow_jobs as jobs


class SourceBudgetConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.authority = {'approvalSha256': 'a' * 64,
            'globalBounds': {'requests': 8, 'wallTimeMs': 8000, 'costMicrousd': 8000},
            'requestLimits': dict(subject.text_limits.DEFAULT_REQUEST_LIMITS)}
        self.bounds = {'requests': 1, 'wallTimeMs': 1000, 'costMicrousd': 1000}

    def call(self, store, index):
        return store.call(operation=f'asr.{index:04d}', identity={'model': 'gpt-transcribe', 'index': index},
            bounds=self.bounds, request=b'fixture', api_key='', content_type='fixture', endpoint='fixture')

    def judge_payload(self):
        from scripts import judge_english_source_for_translation as judge
        with subject.judge_limits(self.authority['requestLimits']):
            return judge._payload([], manifest_hash='b' * 64, anchor_policy={},
                                  model='gpt-6.1-sol', effort='high')

    def test_pinned_structured_judge_dispatches_and_reuses_receipt(self):
        payload = self.judge_payload()
        calls = []
        authority = {**self.authority, 'globalBounds': {
            'requests': 8, 'wallTimeMs': 10**9, 'costMicrousd': 10**9}}
        def transport(endpoint, request, content_type, api_key):
            calls.append(json.loads(request))
            return {'fixture': 'returned'}
        store = subject.SourceBudget(self.root, authority, verify=lambda: None, transport=transport)
        self.assertEqual(store.judge('', payload), {'fixture': 'returned'})
        self.assertEqual(store.judge('', payload), {'fixture': 'returned'})
        self.assertEqual(calls, [payload])
        row = next(iter(jobs._read(self.root / 'source-budget.json')['requests'].values()))
        self.assertEqual(row['bounds']['costMicrousd'], subject.text_limits._cost(
            payload['model'], subject.text_limits._input_upper_bound(payload),
            self.authority['requestLimits']['maxCompletionTokens']))

    def test_unsupported_judge_schema_options_and_caps_fail_before_reservation(self):
        payload = self.judge_payload()
        mutations = [
            lambda p: p['response_format']['json_schema'].update(strict=False),
            lambda p: p['response_format']['json_schema'].update(name='unapproved'),
            lambda p: p['response_format']['json_schema'].update(schema={}),
            lambda p: p.update(response_format={'type': 'json_object'}),
            lambda p: p.update(max_completion_tokens=1),
            lambda p: p.update(service_tier='priority'),
            lambda p: p.update(tools=[]),
            lambda p: p['messages'].append({'role': 'user', 'content': 'x' * 8192}),
        ]
        store = subject.SourceBudget(self.root, self.authority, verify=lambda: None,
                                     transport=lambda *a: self.fail('must not dispatch'))
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(payload)
                mutation(changed)
                with self.assertRaises(ValueError):
                    store.judge('', changed)
                self.assertFalse((self.root / 'source-budget.json').exists())

    def test_judge_schema_bytes_count_toward_the_input_cap(self):
        payload = self.judge_payload()
        cap = subject.text_limits._input_upper_bound(payload) - 1
        limits = {**self.authority['requestLimits'], 'maxInputTokens': cap}
        without_schema = dict(payload, response_format={'type': 'json_object'})
        self.assertLess(subject.text_limits._input_upper_bound(without_schema), cap)
        with self.assertRaisesRegex(ValueError, 'source_judge_input_bound_exceeded'):
            subject.bounded_source_judge_payload(payload, limits)

    def test_four_live_requests_hold_conservative_bounds_and_resume_without_dispatch(self):
        barrier = threading.Barrier(4)
        calls = []
        def transport(*args):
            calls.append(1)
            barrier.wait(timeout=5)
            ledger = jobs._read(self.root / 'source-budget.json')
            self.assertEqual(ledger['schemaVersion'], subject.LEDGER_V2)
            self.assertEqual(sum(r['status'] == 'live_started' for r in ledger['requests'].values()), 4)
            self.assertEqual(sum(r['bounds']['costMicrousd'] for r in ledger['requests'].values()), 4000)
            barrier.wait(timeout=5)
            return {'text': 'fixture'}
        store = subject.SourceBudget(self.root, self.authority, verify=lambda: None, transport=transport, max_concurrent=4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: self.call(store, i), range(4)))
        self.assertEqual(results, [{'text': 'fixture'}] * 4)
        self.assertEqual([self.call(store, i) for i in range(4)], results)
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(r['status'] == 'returned' for r in jobs._read(self.root / 'source-budget.json')['requests'].values()))

    def test_unknown_failure_blocks_new_requests_and_keeps_whole_bound(self):
        calls = []
        def fail(*args):
            calls.append(1)
            raise TimeoutError('fixture unknown')
        store = subject.SourceBudget(self.root, self.authority, verify=lambda: None, transport=fail, max_concurrent=4)
        with self.assertRaises(TimeoutError):
            self.call(store, 0)
        row = jobs._read(self.root / 'source-budget.json')['requests']['asr.0000']
        self.assertEqual(row['status'], 'started_response_unconfirmed')
        self.assertEqual(row['bounds'], self.bounds)
        with self.assertRaisesRegex(ValueError, 'source_provider_outcome_unknown'):
            self.call(store, 1)
        with self.assertRaisesRegex(ValueError, 'source_provider_outcome_unknown'):
            self.call(store, 0)
        self.assertEqual(len(calls), 1)

    def test_crashed_live_owner_becomes_unknown_without_pid_expiry_or_retry(self):
        store = subject.SourceBudget(self.root, self.authority, verify=lambda: None, transport=lambda *a: {}, max_concurrent=4)
        with store._locked() as (ledger, path):
            ledger['requests']['asr.0000'] = {'identitySha256': 'b' * 64, 'bounds': self.bounds,
                'status': 'live_started', 'dispatchOwner': {'token': 'c' * 32, 'pid': 1}}
            jobs._persist(path, ledger)
        with self.assertRaisesRegex(ValueError, 'source_provider_outcome_unknown'):
            self.call(store, 1)
        self.assertEqual(jobs._read(self.root / 'source-budget.json')['requests']['asr.0000']['status'],
                         'started_response_unconfirmed')

    def test_v1_upgrade_is_serial_and_never_unlocks_unknown_reservations(self):
        jobs._persist(self.root / 'source-budget.json', {'schemaVersion': 'sermon-source-budget-ledger-v1',
            'authority': self.authority, 'requests': {'asr.0000': {'identitySha256': 'b' * 64,
                'bounds': self.bounds, 'status': 'started_response_unconfirmed'}}})
        parallel = subject.SourceBudget(self.root, self.authority, verify=lambda: None, transport=lambda *a: {}, max_concurrent=4)
        with self.assertRaisesRegex(ValueError, 'explicit_migration_required'):
            self.call(parallel, 1)
        self.assertEqual(jobs._read(self.root / 'source-budget.json')['schemaVersion'], 'sermon-source-budget-ledger-v1')
        serial = subject.SourceBudget(self.root, self.authority, verify=lambda: None, transport=lambda *a: {})
        with self.assertRaisesRegex(ValueError, 'source_provider_outcome_unknown'):
            self.call(serial, 1)

    def test_new_parallel_reservations_cannot_exceed_existing_hard_cap(self):
        authority = {**self.authority, 'globalBounds': {**self.authority['globalBounds'], 'requests': 1}}
        calls = []
        store = subject.SourceBudget(self.root, authority, verify=lambda: None,
            transport=lambda *a: calls.append(1) or {'text': 'fixture'}, max_concurrent=4)
        self.call(store, 0)
        with self.assertRaisesRegex(ValueError, 'source_budget_exhausted'):
            self.call(store, 1)
        self.assertEqual(len(calls), 1)
