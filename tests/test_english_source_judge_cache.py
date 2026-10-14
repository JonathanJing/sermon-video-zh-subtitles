import json
import multiprocessing
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts import english_source_judge_cache as cache
from tests.test_api_cli_outcomes import reconciliation_evidence


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

    def test_sibling_unknown_blocks_before_marker_then_explicit_reconciliation_allows_work(self):
        from threading import Event
        from scripts import api_cli_outcomes as outcomes
        from scripts.production_spark_admission import SessionBoundCaller
        entered, release, sibling_started = Event(), Event(), Event()
        root = self.root / 'api-cli-outcomes'
        def provider(key, payload):
            self.calls.append(payload['group'])
            if payload['group'] == 0:
                entered.set()
                if not release.wait(3):
                    raise AssertionError('test did not release provider')
                raise TimeoutError('actual unknown')
            return {'id': 'request-1', 'model': 'test', 'choices': [
                {'finish_reason': 'stop', 'message': {'content': '{"ok": true}'}}]}
        wrapped = SessionBoundCaller(provider, requires_spark=False, outcome_directory=root)
        def sibling():
            sibling_started.set()
            return self.call(index=1, caller=wrapped)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.call, 0, wrapped)
            self.assertTrue(entered.wait(3))
            second = pool.submit(sibling)
            try:
                self.assertTrue(sibling_started.wait(3))
                # While the first provider owns the shared gate, only its real
                # dispatch can have a marker. The waiting sibling has none.
                self.assertEqual(len(list((self.root/'cache').glob('*.started.json'))), 1)
            finally:
                release.set()
            with self.assertRaisesRegex(TimeoutError, 'actual unknown'):
                first.result(timeout=3)
            with self.assertRaisesRegex(ValueError, 'reconciliation_required'):
                second.result(timeout=3)
        self.assertEqual(self.calls, [0])
        self.assertEqual(len(list((self.root/'cache').glob('*.started.json'))), 1)
        paths = list(root.glob('*/outcome.json'))
        self.assertEqual(len(paths), 1)  # no manufactured unknown outcome for sibling
        row = json.loads(paths[0].read_text())
        self.assertEqual(row['status'], 'unknown')
        with self.assertRaisesRegex(ValueError, 'reconciliation_required'):
            self.call(0, wrapped)
        recovered = {'id': 'request-0', 'model': 'test', 'choices': [
            {'finish_reason': 'stop', 'message': {'content': '{"ok": true}'}}]}
        outcomes.reconcile(root, row['requestSha256'], recovered, reconciliation_evidence(row['requestSha256'], recovered))
        self.assertEqual(self.call(0, wrapped)[1]['responseId'], 'request-0')
        self.assertEqual(self.call(1, wrapped)[1]['responseId'], 'request-1')
        self.assertEqual(self.call(1, wrapped)[1]['responseId'], 'request-1')
        self.assertEqual(self.calls, [0, 1])
        self.assertEqual(len(list(root.glob('*/outcome.json'))), 2)

    def test_existing_cache_cannot_bypass_unknown_sibling_and_replays_after_reconcile(self):
        from scripts import api_cli_outcomes as outcomes
        from scripts.production_spark_admission import SessionBoundCaller
        root = self.root / 'api-cli-outcomes'
        def provider(key, payload):
            self.calls.append(payload['group'])
            if payload['group'] == 1:
                raise TimeoutError('unknown sibling')
            return {'id': 'request-0', 'model': 'test', 'choices': [
                {'finish_reason': 'stop', 'message': {'content': '{"ok": true}'}}]}
        wrapped = SessionBoundCaller(provider, requires_spark=False, outcome_directory=root)
        original = self.call(0, wrapped)
        with self.assertRaisesRegex(TimeoutError, 'unknown sibling'):
            self.call(1, wrapped)
        before = {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.root.rglob('*') if path.is_file()}
        with self.assertRaisesRegex(ValueError, 'reconciliation_required'):
            self.call(0, wrapped)
        after = {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(self.calls, [0, 1])
        row = next(json.loads(path.read_text()) for path in root.glob('*/outcome.json')
                   if json.loads(path.read_text())['status'] == 'unknown')
        outcomes.reconcile(root, row['requestSha256'], {'error': 'explicit terminal failure'},
                           reconciliation_evidence(row['requestSha256'], {'error': 'explicit terminal failure'}, terminal_failure=True), terminal_failure=True)
        self.assertEqual(self.call(0, wrapped), original)
        self.assertEqual(self.calls, [0, 1])

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

    def test_durable_api_return_recovers_before_source_marker_without_dispatch(self):
        from unittest.mock import patch
        from scripts.production_spark_admission import SessionBoundCaller
        wrapped=SessionBoundCaller(self.provider,requires_spark=False,outcome_directory=self.root/'api-cli-outcomes')
        original=cache._atomic
        def crash(path,value):
            if path.parent.name=='cache' and not path.name.endswith('.started.json'):
                raise OSError('crash before source cache receipt')
            original(path,value)
        with patch.object(cache,'_atomic',side_effect=crash):
            with self.assertRaises(OSError):self.call(caller=wrapped)
        self.assertEqual(self.calls,[0])
        result,_=self.call(caller=wrapped)
        self.assertEqual(result,{'ok':True});self.assertEqual(self.calls,[0])

    def test_wrong_request_marker_does_not_recover_another_return(self):
        from unittest.mock import patch
        from scripts.production_spark_admission import SessionBoundCaller
        wrapped=SessionBoundCaller(self.provider,requires_spark=False,outcome_directory=self.root/'api-cli-outcomes')
        original=cache._atomic
        def crash(path,value):
            if path.parent.name=='cache' and not path.name.endswith('.started.json'):raise OSError('crash')
            original(path,value)
        with patch.object(cache,'_atomic',side_effect=crash):
            with self.assertRaises(OSError):self.call(caller=wrapped)
        marker=next((self.root/'cache').glob('*.started.json'))
        row=json.loads(marker.read_text());row['request']['payload']['group']=1;marker.write_text(json.dumps(row))
        with self.assertRaisesRegex(ValueError,'Unknown L1'):self.call(caller=wrapped)
        self.assertEqual(self.calls,[0])
