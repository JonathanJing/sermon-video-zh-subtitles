"""Paid-call boundaries tested without a network, API key, or model invocation."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts import run_target_language_models as runner
from scripts import sermon_workflow_jobs as jobs


class PaidModelCacheDurabilityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.output = self.root / 'new' / 'locale' / 'group.json'
        self.marker = self.output.with_suffix('.started.json')
        self.raw = self.output.with_suffix('.raw.json')
        self.policy = {'translator': {'model': 'gpt-6-astra', 'reasoningEffort': 'high'}}
        self.prompt = {'instruction': 'Synthetic test only', 'input': {'group': 1}}
        self.calls = 0

    def response(self, _key, payload):
        self.calls += 1
        return {'id': 'synthetic-response', 'model': payload['model'],
                'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}]}

    def call(self, caller=None):
        return runner._model_call('translator', self.prompt, self.policy, self.output,
                                  'synthetic-not-a-key', caller or self.response)

    def test_marker_file_and_all_directory_entries_precede_response_call(self):
        events = []
        fsync = os.fsync
        sync_dir = jobs._sync_directory
        unlink = Path.unlink

        def sync(fd):
            if stat.S_ISREG(os.fstat(fd).st_mode):
                for path in (self.marker, self.raw, self.output):
                    if path.exists() and path.stat().st_ino == os.fstat(fd).st_ino:
                        events.append(('file', path.name))
            return fsync(fd)

        def directory(path):
            events.append(('directory', Path(path).resolve()))
            return sync_dir(path)

        def remove(path, *args, **kwargs):
            if path == self.marker:
                events.append(('remove_marker', None))
            return unlink(path, *args, **kwargs)

        def respond(key, payload):
            events.append(('caller', None))
            return self.response(key, payload)

        with patch.object(os, 'fsync', side_effect=sync), patch.object(jobs, '_sync_directory', side_effect=directory), patch.object(Path, 'unlink', remove):
            self.call(respond)
        called = events.index(('caller', None))
        self.assertIn(('file', self.marker.name), events[:called])
        for directory in (self.output.parent, self.output.parent.parent, self.root, self.root.parent):
            self.assertIn(('directory', directory), events[:called])
        raw = events.index(('file', self.raw.name))
        result = events.index(('file', self.output.name))
        removed = events.index(('remove_marker', None))
        self.assertLess(called, raw)
        self.assertLess(raw, result)
        self.assertLess(result, removed)
        self.assertIn(('directory', self.output.parent), events[result:removed])

    def test_marker_sync_failure_never_calls_responder(self):
        fsync = os.fsync

        def fail_marker_sync(fd):
            # The policy preview is persisted before the request marker. Fail
            # this boundary specifically, rather than its earlier safe write.
            if self.marker.exists() and os.fstat(fd).st_ino == self.marker.stat().st_ino:
                raise OSError('synthetic marker sync failure')
            return fsync(fd)

        for boundary in ('file', 'directory'):
            with self.subTest(boundary=boundary):
                self.output = self.root / boundary / 'group.json'
                self.marker = self.output.with_suffix('.started.json')
                target, name = (os, 'fsync') if boundary == 'file' else (jobs, '_sync_directory_ancestry')
                failure = fail_marker_sync if boundary == 'file' else OSError('synthetic sync failure')
                with patch.object(target, name, side_effect=failure):
                    with self.assertRaises(OSError):
                        self.call()
                self.assertEqual(self.calls, 0)
                self.assertTrue(self.marker.exists())
                with self.assertRaisesRegex(ValueError, 'Uncertain paid'):
                    self.call()
                self.assertEqual(self.calls, 0)

    def test_policy_preview_sync_failure_precedes_request_intent(self):
        with patch.object(os, 'fsync', side_effect=OSError('synthetic preview sync failure')):
            with self.assertRaises(OSError):
                self.call()
        self.assertEqual(self.calls, 0)
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.raw.exists())

    def test_response_sync_failure_keeps_unknown_outcome_blocked_if_unsynced_file_is_lost(self):
        fsync = os.fsync

        def fail_raw(fd):
            if self.raw.exists() and os.fstat(fd).st_ino == self.raw.stat().st_ino:
                raise OSError('synthetic raw persistence failure')
            return fsync(fd)

        with patch.object(os, 'fsync', side_effect=fail_raw):
            with self.assertRaises(OSError):
                self.call()
        self.assertEqual(self.calls, 1)
        self.assertTrue(self.marker.exists())
        self.raw.unlink()  # Model the unconfirmed write being lost on host crash.
        with self.assertRaisesRegex(ValueError, 'Uncertain paid'):
            self.call()
        self.assertEqual(self.calls, 1)

    def test_result_sync_failure_recovers_from_durable_raw_without_second_call(self):
        fsync = os.fsync

        def fail_result(fd):
            if self.output.exists() and os.fstat(fd).st_ino == self.output.stat().st_ino:
                raise OSError('synthetic result persistence failure')
            return fsync(fd)

        with patch.object(os, 'fsync', side_effect=fail_result):
            with self.assertRaises(OSError):
                self.call()
        self.assertTrue(self.marker.exists())
        self.assertTrue(self.raw.exists())
        self.output.unlink()  # Lost unconfirmed result is rebuilt from raw.
        self.assertEqual(self.call()['result'], {'ok': True})
        self.assertEqual(self.calls, 1)

    def test_preexisting_cache_does_not_trigger_durable_rewrite_or_paid_retry(self):
        self.call()
        before = self.output.read_bytes()
        with patch.object(os, 'fsync', side_effect=AssertionError('cache must not be rewritten')):
            self.assertEqual(self.call()['result'], {'ok': True})
        self.assertEqual(self.output.read_bytes(), before)
        self.assertEqual(self.calls, 1)

    def test_same_identity_concurrent_attempt_is_blocked_by_durable_marker(self):
        admitted, release = threading.Event(), threading.Event()

        def responder(key, payload):
            admitted.set()
            self.assertTrue(release.wait(5), 'synthetic responder was not released')
            return self.response(key, payload)

        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.call, responder)
            try:
                self.assertTrue(admitted.wait(5))
                with self.assertRaisesRegex(ValueError, 'Uncertain paid'):
                    self.call()
            finally:
                release.set()
            self.assertEqual(first.result(timeout=5)['result'], {'ok': True})
        self.assertEqual(self.calls, 1)
        self.assertFalse(self.marker.exists())

    def test_process_exit_after_admission_keeps_paid_attempt_unknown(self):
        script = '''import os, sys
from pathlib import Path
from scripts import run_target_language_models as runner

def responder(key, payload):
    os._exit(27)
runner._model_call('translator', {'instruction':'Synthetic test only','input':{'group':1}},
    {'translator':{'model':'gpt-6-astra','reasoningEffort':'high'}}, Path(sys.argv[1]),
    'synthetic-not-a-key', responder)
'''
        child = subprocess.run([sys.executable, '-c', script, str(self.output)],
                               cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=10)
        self.assertEqual(child.returncode, 27, child.stderr)
        self.assertTrue(self.marker.exists())
        with self.assertRaisesRegex(ValueError, 'Uncertain paid'):
            self.call()
        self.assertEqual(self.calls, 0)
