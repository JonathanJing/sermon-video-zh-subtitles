import json
import multiprocessing
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts import english_source_judge_cache as cache


def crash_during_request(root):
    cache.cached_call(out=Path(root), stage='english-source-judge-000',
                      payload={'model': 'test', 'group': 0}, api_key='',
                      requested_model='test', caller=lambda *args: os._exit(19))


class JudgeSingleFlightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.calls = []

    def call(self, index=0, caller=None):
        return cache.cached_call(out=self.root, stage=f'english-source-judge-{index:03d}',
                                 payload={'model': 'test', 'group': index}, api_key='',
                                 requested_model='test', caller=caller or self.provider)

    def provider(self, key, payload):
        self.calls.append(payload['group'])
        time.sleep(0.005)
        return {'id': f'request-{payload["group"]}', 'model': 'test', 'choices': [
            {'finish_reason': 'stop', 'message': {'content': json.dumps({'ok': True})}}]}

    def test_sixteen_duplicate_prewarm_and_final_groups_single_flight(self):
        # Regression for the observed sixteen duplicated prewarm/final groups.
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(self.call, [i for i in range(16) for _ in range(2)]))
        self.assertEqual(sorted(self.calls), list(range(16)))
        for i in range(16):
            self.assertEqual(results[i * 2], results[i * 2 + 1])

    def test_unknown_blocks_retry_after_owner_exit(self):
        def failed(*args):
            raise RuntimeError('connection lost after dispatch')
        with self.assertRaisesRegex(RuntimeError, 'connection lost'):
            self.call(caller=failed)
        with self.assertRaisesRegex(ValueError, 'Unknown L1 request outcome'):
            self.call()
        self.assertEqual(self.calls, [])

    def test_admission_busy_precedes_started_and_cache_hits_skip_admission(self):
        test = self
        class Caller:
            admissions = 0
            busy = True
            def admit_resource(self, payload):
                self.admissions += 1
                if self.busy:
                    raise ValueError('resource_capacity_busy')
            def __call__(self, key, payload):
                return test.provider(key, payload)
        caller = Caller()
        with self.assertRaisesRegex(ValueError, 'resource_capacity_busy'):
            self.call(caller=caller)
        self.assertEqual(list((self.root / 'cache').glob('*.started.json')), [])
        self.assertEqual(self.calls, [])
        caller.busy = False
        first = self.call(caller=caller)
        self.assertEqual(self.call(caller=caller), first)
        self.assertEqual(caller.admissions, 2)
        self.assertEqual(self.calls, [0])

    def test_invalid_returned_response_is_preserved_and_never_repaid(self):
        def invalid(*args):
            self.calls.append(0)
            return {'model': 'wrong'}
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, 'Unexpected response model'):
                self.call(caller=invalid)
        self.assertEqual(self.calls, [0])

    def test_corrupt_cache_is_not_repaid(self):
        _, receipt = self.call()
        path = Path(receipt['path'])
        value = json.loads(path.read_text())
        value['response']['id'] = 'tampered'
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            self.call()
        self.assertEqual(self.calls, [0])

    def test_explicit_reconciliation_recovers_original_request_without_repayment(self):
        def failed(*args):
            raise RuntimeError('owner exited')
        with self.assertRaises(RuntimeError):
            self.call(caller=failed)
        marker_path = next((self.root / 'cache').glob('*.started.json'))
        marker = json.loads(marker_path.read_text())
        response = self.provider('', {'group': 0})
        cache.reconcile_returned_response(marker_path=marker_path, response=response,
                                          expected_request_sha256=marker['requestSha256'],
                                          requested_model='test')
        self.calls.clear()
        _, receipt = self.call()
        self.assertEqual(receipt['responseId'], response['id'])
        self.assertEqual(self.calls, [])
        self.assertTrue(marker_path.exists())

    def test_process_crash_retains_unknown_marker(self):
        process = multiprocessing.get_context('spawn').Process(
            target=crash_during_request, args=(str(self.root),))
        process.start()
        process.join(timeout=10)
        self.assertEqual(process.exitcode, 19)
        with self.assertRaisesRegex(ValueError, 'Unknown L1 request outcome'):
            self.call()
        self.assertEqual(self.calls, [])
