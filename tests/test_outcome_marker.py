"""End-of-run outcome marker: written on success, failure, and SystemExit."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import outcome_marker
from scripts.experiments import run_spark_diagnostic_audio as runner


class OutcomeMarkerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'nested' / 'outcome.json'

    def read(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def test_success_writes_succeeded_with_zero_exit(self):
        self.assertEqual(outcome_marker.run_with_outcome(self.path, 'fixture', lambda: 'value'), 'value')
        record = self.read()
        self.assertEqual((record['status'], record['exitCode'], record['command']), ('succeeded', 0, 'fixture'))
        self.assertNotIn('error', record)
        self.assertFalse(self.path.with_name('outcome.json.tmp').exists())

    def test_exception_writes_failed_and_reraises_unchanged(self):
        def boom():
            raise RuntimeError('remote stage missing')
        with self.assertRaisesRegex(RuntimeError, 'remote stage missing'):
            outcome_marker.run_with_outcome(self.path, 'fixture', boom)
        record = self.read()
        self.assertEqual((record['status'], record['exitCode']), ('failed', 1))
        self.assertEqual(record['error'], {'type': 'RuntimeError', 'message': 'remote stage missing'})

    def test_system_exit_keeps_its_code(self):
        def exits():
            raise SystemExit(75)
        with self.assertRaises(SystemExit):
            outcome_marker.run_with_outcome(self.path, 'fixture', exits)
        self.assertEqual((self.read()['status'], self.read()['exitCode']), ('failed', 75))

    def test_a_later_finish_replaces_the_marker(self):
        outcome_marker.write_outcome(self.path, command='c', status='failed', exit_code=1, started_at='t')
        outcome_marker.write_outcome(self.path, command='c', status='succeeded', exit_code=0, started_at='t')
        self.assertEqual(self.read()['status'], 'succeeded')


class RunnerOutcomeTests(unittest.TestCase):
    def test_execute_failure_is_recorded_in_out_directory(self):
        with tempfile.TemporaryDirectory(dir=runner.ROOT / 'artifacts', prefix='test-outcome-') as temp:
            out = Path(temp) / 'audio'
            argv = ['execute', '--fixture', temp, '--layer2-out', temp, '--media', temp,
                    '--out', str(out), '--remote-stage', '/home/achillesjing/dgx-spark-benchmark/results/next-concurrency-fixture']
            with patch.object(runner, 'execute', side_effect=ValueError('layer2_admission_required_before_spark_dispatch')):
                with self.assertRaisesRegex(ValueError, 'layer2_admission_required'):
                    runner.main(argv)
            record = json.loads((out / 'outcome.json').read_text(encoding='utf-8'))
            self.assertEqual(record['status'], 'failed')
            self.assertEqual(record['error']['type'], 'ValueError')
