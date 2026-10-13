"""Offline same-request coordination still consumes the durable SourceBudget result."""
import copy
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from scripts import machine_qc_audio_transports as transports
from scripts import machine_qc_budget_authorization as auth
from scripts.sermon_source_budget import SourceBudget
from tests.auto_qc_fixtures import speech_wav
from tests.test_source_budget_settlement import AUTHORITY
from tests.test_run_machine_qc_audio_test import OPENAI_ENV


class SecondarySingleflightTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = patch.dict('os.environ', OPENAI_ENV)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def secondary(self, send, *, cache='cache', concurrency=1, cap=10):
        from scripts.sermon_openai_runtime import selected_route
        store = SourceBudget(self.root/'budget', copy.deepcopy(AUTHORITY), verify=lambda: None,
                             transport=send, max_concurrent=concurrency)
        # Trusted already-authorized synthetic ledger seam; no provider or GPU.
        store.qc_context = {'schemaVersion': auth.CONTEXT_SCHEMA, 'targetLocale': 'ko',
                            'environment': 'dev', 'openaiRoute': selected_route(),
                            'credentialSha256': auth.credential_fingerprint(OPENAI_ENV['OPENAI_API_KEY'])}
        return transports.OpenAiTranscribeSecondary('ko', cache=self.root/cache, max_calls=cap, budget=store)

    def run_identical(self, first, second, *, expected_texts=None):
        """Keep the sender live until its sibling has attempted the flight lock."""
        attempted = threading.Event()
        entry_lock = threading.Lock()
        entries = []
        original = transports._secondary_flight
        @contextmanager
        def observed(*args):
            with entry_lock:
                entries.append(1)
                if len(entries) == 2:
                    attempted.set()
            with original(*args):
                yield
        start = threading.Barrier(2)
        def run(caller, index):
            start.wait(timeout=3)
            try:
                return (caller.opinion(speech_wav(1), expected_texts[index], 'ko')
                        if expected_texts else caller.transcribe(speech_wav(1)))
            except Exception as exc:
                return exc
        # The transport waits for this event, so this is actual overlap rather
        # than a sequential cache test disguised as a concurrency test.
        self.sibling_attempted = attempted
        with patch.object(transports, '_secondary_flight', observed), ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(run, caller, index) for index, caller in enumerate((first, second))]
            return [future.result(timeout=5) for future in futures]

    def test_identical_across_instances_one_dispatch_both_success(self):
        sent = []
        def send(*args):
            sent.append(args)
            self.assertTrue(self.sibling_attempted.wait(3))
            return {'text': '본문'}
        first = self.secondary(send, cap=1)
        second = self.secondary(send, cache='other', cap=1)
        opinions = self.run_identical(first, second, expected_texts=['본문', '다른 문장'])
        self.assertEqual([opinion['recognized'] for opinion in opinions], ['본문', '본문'])
        self.assertEqual(opinions[0]['audioSha256'], opinions[1]['audioSha256'])
        self.assertNotEqual(opinions[0]['textSha256'], opinions[1]['textSha256'])
        self.assertNotEqual(opinions[0]['similarity'], opinions[1]['similarity'])
        self.assertEqual(len(sent), 1)
        self.assertEqual(first.calls + second.calls, 1)
        rows = json.loads((self.root/'budget/source-budget.json').read_text())['requests']
        self.assertEqual(len(rows), 1)
        self.assertEqual(next(iter(rows.values()))['status'], 'returned')
        self.assertEqual(second.transcribe(speech_wav(1)), '본문')
        self.assertEqual(len(sent), 1)
        self.assertFalse(transports._SECONDARY_FLIGHTS)

    def test_different_audio_dispatches_remain_parallel(self):
        send_barrier = threading.Barrier(2)
        sent = []
        def send(*args):
            sent.append(args)
            send_barrier.wait(timeout=3)
            return {'text': '본문'}
        caller = self.secondary(send, concurrency=2, cap=2)
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(caller.transcribe, speech_wav(seconds)) for seconds in (1, 1.1)]
            self.assertEqual([future.result(timeout=5) for future in futures], ['본문', '본문'])
        self.assertEqual(len(sent), 2)
        self.assertEqual(caller.calls, 2)
        self.assertFalse(transports._SECONDARY_FLIGHTS)

    def test_unknown_waiter_and_later_replay_never_redispatch(self):
        sent = []
        def send(*args):
            sent.append(args)
            self.assertTrue(self.sibling_attempted.wait(3))
            raise TimeoutError('offline uncertain provider result')
        caller = self.secondary(send)
        results = self.run_identical(caller, caller)
        self.assertEqual(sum(isinstance(result, TimeoutError) for result in results), 1)
        self.assertEqual(sum('source_provider_outcome_unknown' in str(result) for result in results), 1)
        with self.assertRaisesRegex(ValueError, 'source_provider_outcome_unknown'):
            caller.transcribe(speech_wav(1))
        self.assertEqual(len(sent), 1)
        self.assertFalse(transports._SECONDARY_FLIGHTS)

    def test_returned_invalid_transcript_waiter_never_redispatches(self):
        sent = []
        def send(*args):
            sent.append(args)
            self.assertTrue(self.sibling_attempted.wait(3))
            return {'text': None}
        caller = self.secondary(send, cap=1)
        results = self.run_identical(caller, caller)
        self.assertTrue(all(isinstance(result, ValueError) and 'no transcript text' in str(result)
                            for result in results), results)
        self.assertEqual(len(sent), 1)
        self.assertEqual(caller.calls, 1)
        self.assertFalse(transports._SECONDARY_FLIGHTS)
