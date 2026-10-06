import concurrent.futures
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
