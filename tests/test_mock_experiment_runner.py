import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tests import run_mock_dag_experiment as runner
from tests.mock_experiment_progress import emit_progress


class RunnerTests(unittest.TestCase):
    def test_progress_is_optional_and_rejects_unbounded_labels(self):
        with patch.dict(os.environ, {}, clear=True):
            emit_progress('invocation_started', scenario='happy', invocation=1)
        for kwargs in ({'scenario': 'private-value'}, {'scenario': 'happy', 'invocation': 3},
                       {'scenario': 'happy', 'status': 'private-value'},
                       {'scenario': 'happy', 'wall_seconds': float('nan')}):
            with self.assertRaises(ValueError):
                emit_progress('invocation_started', **kwargs)

    def test_progress_roundtrip_and_symlink_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'progress.jsonl'
            with patch.dict(os.environ, {'SERMON_MOCK_EXPERIMENT_PROGRESS_FILE': str(path)}):
                emit_progress('invocation_finished', scenario='happy', invocation=1,
                              status='synthetic_complete', wall_seconds=1.2)
            data = json.loads(path.read_text())
            self.assertEqual(data['wallSeconds'], 1.2)
            self.assertIn('diagnostic', data['scope'])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cursor = runner.show_progress(Path(directory), 'happy', 0)
                runner.show_progress(Path(directory), 'happy', cursor)
            self.assertEqual(len(out.getvalue().splitlines()), 1)
            link = Path(directory)/'link'; link.symlink_to(path)
            before = path.read_bytes()
            with patch.dict(os.environ, {'SERMON_MOCK_EXPERIMENT_PROGRESS_FILE': str(link)}):
                with self.assertRaises(OSError):
                    emit_progress('scenario_verified', scenario='happy')
            self.assertEqual(path.read_bytes(), before)

    def test_process_failure_saves_timing_and_preserves_log(self):
        class Process:
            def wait(self, timeout):
                return 1
        with tempfile.TemporaryDirectory() as directory, patch.object(runner.subprocess, 'Popen', return_value=Process()), contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            result = runner.run_scenario('failure', root, {})
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(json.loads((root/'failure-timing.json').read_text())['exitCode'], 1)
            self.assertTrue((root/'failure.log').exists())
            self.assertNotIn('shell', result['command'])

    def test_matrix_stops_after_failure_and_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner.subprocess, 'check_output', side_effect=lambda command, **kw: '' if 'status' in command else 'a'*40), patch.object(runner, 'run_scenario', return_value={'scenario': 'happy', 'exitCode': 1}) as run:
            output = Path(directory)/'run'
            self.assertEqual(runner.main(['--output-dir', str(output)]), 1)
            run.assert_called_once()
            summary = json.loads((output/'summary.json').read_text())
            self.assertEqual(summary['status'], 'failed')
            before = (output/'summary.json').read_bytes()
            with self.assertRaises(FileExistsError):
                runner.main(['--output-dir', str(output)])
            self.assertEqual((output/'summary.json').read_bytes(), before)

    def test_candidate_change_stops_before_first_scenario(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner.subprocess, 'check_output',
                side_effect=['', 'a'*40, 'b'*40, '']), patch.object(runner, 'run_scenario') as run:
            output = Path(directory)/'run'
            with self.assertRaisesRegex(ValueError, 'candidate_changed'):
                runner.main(['--output-dir', str(output)])
            run.assert_not_called()
            self.assertEqual(json.loads((output/'summary.json').read_text())['status'], 'runner_error')

    def test_dirty_tree_fails_before_output_creation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner.subprocess, 'check_output', return_value=' M file'), contextlib.redirect_stderr(io.StringIO()):
            output = Path(directory)/'run'
            with self.assertRaises(SystemExit):
                runner.main(['--output-dir', str(output)])
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
