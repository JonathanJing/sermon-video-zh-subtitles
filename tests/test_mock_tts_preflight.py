"""Native startup probes and early-stop checks; no DAG jobs or model calls."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from tests import mock_tts_preflight as preflight


class MockTTSPreflightTests(unittest.TestCase):
    def test_native_isolated_python_uses_real_scrubbing_and_submits_no_jobs(self):
        actual = preflight.subprocess.run
        calls = []
        def capture(command, **kwargs):
            if command[:3] == [sys.executable, '-I', '-c']:
                calls.append((command, kwargs))
            return actual(command, **kwargs)
        with patch.object(preflight.subprocess, 'run', side_effect=capture), \
                patch.object(preflight.worker, 'submit', side_effect=AssertionError('no job')), \
                patch.object(preflight.worker, 'execute', side_effect=AssertionError('no worker')):
            result = preflight.native_worker_preflight()
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(result['scope'], 'native_isolated_startup_environment_only')
        self.assertEqual(result['jobSubmissions'], 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0][:3], [sys.executable, '-I', '-c'])
        self.assertIs(calls[0][1]['stderr'], subprocess.DEVNULL)
        self.assertFalse(Path(calls[0][1]['cwd']).exists())
        for key in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_DATASETS_OFFLINE', 'HF_HUB_DISABLE_TELEMETRY'):
            self.assertEqual(calls[0][1]['env'][key], '1')

    def test_native_unknown_environment_key_still_fails_closed_without_leaking(self):
        actual = preflight.worker.environment
        def invalid(root):
            return {**actual(root), 'UNAUTHORIZED_PREFLIGHT_TEST_KEY': 'do-not-print-this-value'}
        with patch.object(preflight.worker, 'environment', side_effect=invalid):
            result = preflight.native_worker_preflight()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['reasonCode'], 'mock_tts_environment_not_scrubbed')
        self.assertNotIn('do-not-print', json.dumps(result))
        self.assertNotIn('UNAUTHORIZED_PREFLIGHT', json.dumps(result))

    def test_native_offline_guard_remains_required(self):
        actual = preflight.worker.environment
        def invalid(root):
            result = actual(root)
            result.pop('HF_HUB_OFFLINE')
            return result
        with patch.object(preflight.worker, 'environment', side_effect=invalid):
            result = preflight.native_worker_preflight()
        self.assertEqual(result['reasonCode'], 'mock_tts_environment_not_scrubbed')

    def test_child_timeout_is_bounded_and_has_no_exception_output(self):
        with patch.object(preflight.subprocess, 'run', side_effect=subprocess.TimeoutExpired('secret-command', 15)):
            result = preflight.native_worker_preflight()
        self.assertEqual(result['reasonCode'], 'isolated_startup_timeout')
        self.assertNotIn('secret-command', json.dumps(result))

    def test_early_preflight_failure_prevents_fixture_creation_and_records_progress(self):
        from tests import test_sermon_fresh_full_dag as scenarios
        result = {'schemaVersion': preflight.SCHEMA, 'scope': preflight.SCOPE,
            'status': 'failed', 'reasonCode': 'mock_tts_environment_not_scrubbed',
            'wallSeconds': 0.01, 'jobSubmissions': 0, 'providerCalls': 0,
            'modelCalls': 0, 'productionEligible': False}
        output = io.StringIO()
        with patch.object(preflight, 'native_worker_preflight', return_value=result), \
                patch.object(scenarios, 'FullFreshDAGFixture') as fixture, \
                patch('tests.mock_experiment_progress.emit_progress') as progress, \
                contextlib.redirect_stdout(output):
            with self.assertRaisesRegex(RuntimeError, '^mock_worker_preflight_failed:mock_tts_environment_not_scrubbed$'):
                scenarios.run_clean_scenario('/unused-repository', 'happy')
        fixture.assert_not_called()
        self.assertEqual([call.args[0] for call in progress.call_args_list], ['preflight_started', 'preflight_finished'])
        self.assertEqual(progress.call_args_list[-1].kwargs['status'], 'failed')
        self.assertLess(len(output.getvalue()), 1024)
        self.assertEqual(json.loads(output.getvalue().split(' ', 1)[1])['scope'], preflight.SCOPE)


if __name__ == '__main__':
    unittest.main()
