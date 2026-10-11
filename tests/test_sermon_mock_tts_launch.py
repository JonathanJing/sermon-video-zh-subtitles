"""Narrow macOS startup compatibility and non-authoritative launch diagnostics."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_log_contract as logs
from scripts import sermon_mock_tts_control as control
from scripts import sermon_mock_tts_worker as worker
from scripts import sermon_review_contracts as c
from tests.test_sermon_mock_tts_worker import WorkerFixture


class MockTTSLaunchTests(WorkerFixture):
    def test_native_isolated_interpreter_accepts_scrubbed_runtime_environment(self):
        # Reproduces framework Python adding a CoreFoundation hint *after* exec.
        # No job, task or provider is launched by this probe.
        env = worker.environment(self.scope/'probe')
        code = ('import sys; sys.path.insert(0, sys.argv[1]); '
                'from scripts.sermon_mock_tts_worker import require_environment; '
                'require_environment(); print("validated")')
        result = subprocess.run([sys.executable, '-I', '-c', code,
            str(Path(worker.__file__).resolve().parents[1])], env=env,
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'validated')
        self.assertFalse((self.scope/'jobs').exists())

    def test_corefoundation_exception_is_platform_uid_and_shape_bound(self):
        env = worker.environment(self.scope/'probe')
        good = f'0x{os.getuid():X}:0x0:0x0'
        with patch.object(worker.sys, 'platform', 'darwin'), patch.dict(os.environ,
                {**env, '__CF_USER_TEXT_ENCODING': good}, clear=True):
            worker.require_environment()
        bad = (f'0x{os.getuid()+1:X}:0x0:0x0', good+'\n', good+':extra',
               f'0x{os.getuid():X}:0x123456789:0x0', '/private/secret', '')
        for value in bad:
            with self.subTest(value=value), patch.object(worker.sys, 'platform', 'darwin'), \
                    patch.dict(os.environ, {**env, '__CF_USER_TEXT_ENCODING': value}, clear=True):
                with self.assertRaisesRegex(c.ContractError, '^mock_tts_environment_not_scrubbed$'):
                    worker.require_environment()
        with patch.object(worker.sys, 'platform', 'linux'), patch.dict(os.environ,
                {**env, '__CF_USER_TEXT_ENCODING': good}, clear=True):
            with self.assertRaisesRegex(c.ContractError, '^mock_tts_environment_not_scrubbed$'):
                worker.require_environment()

    def test_no_ambient_hint_or_secret_is_inherited_and_other_unknowns_still_fail(self):
        with patch.dict(os.environ, {'__CF_USER_TEXT_ENCODING': 'private-ambient',
                'OPENAI_API_KEY': 'private-ambient'}):
            env = worker.environment(self.scope/'probe')
        self.assertNotIn('__CF_USER_TEXT_ENCODING', env)
        self.assertNotIn('OPENAI_API_KEY', env)
        with patch.dict(os.environ, {**env, 'UNEXPECTED_STARTUP_KEY': 'private-ambient'}, clear=True):
            with self.assertRaisesRegex(c.ContractError, '^mock_tts_environment_not_scrubbed$'):
                worker.require_environment()

    def check_unconfirmed(self, *, result=None, exception=None, reason, exit_code=None):
        request, path = self.make_request()
        client = control.MockTTSClient(self.scope, self.stream, self.policy, create=True)
        with patch.object(control.subprocess, 'run', return_value=result, side_effect=exception) as launch:
            returned = client.submit(path)
        launch.assert_called_once()
        self.assertIsNone(returned['newDispatch'])
        self.assertTrue(returned['launchEntered'])
        self.assertTrue(returned['reconciliationRequired'])
        self.assertFalse((self.scope/'jobs').exists())
        events, errors = accounting.read_events(self.stream.directory)
        self.assertFalse(errors)
        recorded = [e for e in events if e.get('code') == 'mock_tts.launcher_unconfirmed']
        self.assertEqual(len(recorded), 1)
        event = recorded[0]
        self.assertEqual(event['jobId'], request['jobId'])
        self.assertEqual(event['fields']['status'], 'outcome_unknown')
        self.assertEqual(event['fields']['reasonCode'], reason)
        self.assertEqual(event['fields'].get('exitCode'), exit_code)
        self.assertEqual(event['level'], 'ERROR')
        self.assertNotIn('private-ambient', json.dumps(events))
        self.assertEqual(logs.replay_integrity(events)['status'], 'consistent')
        before = (self.stream.directory/'events.jsonl').read_bytes()
        with patch.object(control.subprocess, 'run', side_effect=AssertionError('must not redispatch')):
            repeated = client.submit(path)
        self.assertFalse(repeated['newDispatch'])
        self.assertFalse(repeated['launchEntered'])
        self.assertTrue(repeated['reconciliationRequired'])
        self.assertEqual(before, (self.stream.directory/'events.jsonl').read_bytes())

    def test_known_environment_rejection_logs_fixed_reason_without_retry_authority(self):
        result = subprocess.CompletedProcess([], 1, 'private-ambient',
            'private-ambient\nscripts.sermon_review_contracts.ContractError: mock_tts_environment_not_scrubbed\n')
        self.check_unconfirmed(result=result, reason='mock_tts_environment_not_scrubbed', exit_code=1)

    def test_import_error_never_copies_module_name_or_stderr(self):
        result = subprocess.CompletedProcess([], 1, '', "ModuleNotFoundError: No module named 'private-ambient'\n")
        self.check_unconfirmed(result=result, reason='mock_tts_launcher_import_error', exit_code=1)

    def test_unrecognized_child_output_is_not_an_error_code(self):
        result = subprocess.CompletedProcess([], 2, 'private-ambient',
            'scripts.sermon_review_contracts.ContractError: private-ambient\n')
        self.check_unconfirmed(result=result, reason='mock_tts_launcher_nonzero_exit', exit_code=2)

    def test_timeout_logs_no_command_output_or_exception_body(self):
        self.check_unconfirmed(exception=subprocess.TimeoutExpired(['private-ambient'], 10,
            output='private-ambient', stderr='private-ambient'), reason='mock_tts_launcher_timeout')

    def test_os_error_does_not_leak_exception_path(self):
        self.check_unconfirmed(exception=OSError('private-ambient'), reason='mock_tts_launcher_os_error')

    def test_invalid_reply_preserves_unknown_without_logging_reply(self):
        result = subprocess.CompletedProcess([], 0, 'private-ambient', 'private-ambient')
        self.check_unconfirmed(result=result, reason='mock_tts_submit_ack_invalid', exit_code=0)


if __name__ == '__main__':
    unittest.main()
