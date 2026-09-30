import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import evaluate_canonical_stage0 as subject


class Stage0EvidenceTests(unittest.TestCase):
    def test_zero_tests_skips_timeout_and_failed_process_cannot_claim_pass(self):
        cases = [('Ran 0 tests in 0s\nOK\n', 0),
                 ('Ran 2 tests in 0s\nOK (skipped=1)\n', 0),
                 ('Ran 2 tests in 0s\nOK\n', 1), ('partial output', None)]
        for output, code in cases:
            with self.subTest(output=output), tempfile.TemporaryDirectory() as directory:
                def run(*args, **kwargs):
                    kwargs['stdout'].write(output.encode())
                    if code is None:
                        raise subprocess.TimeoutExpired(args[0], 1)
                    return subprocess.CompletedProcess(args[0], code)
                row = subject.run_suite('bounded_decision', subject.SUITES['bounded_decision'],
                                        Path(directory), runner=run)
                self.assertEqual(row['status'], 'failed')
                self.assertEqual(row['logSha256'], hashlib.sha256(output.encode()).hexdigest())

    def test_unknown_command_and_existing_log_are_not_executed_or_overwritten(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(subject.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                subject.run_suite('bounded_decision', ['untrusted.module'], Path(directory), runner=run)
            log = Path(directory) / 'bounded_decision.log'; log.write_text('earlier evidence')
            with self.assertRaises(FileExistsError):
                subject.run_suite('bounded_decision', subject.SUITES['bounded_decision'], Path(directory), runner=run)
            self.assertEqual(log.read_text(), 'earlier evidence')
            run.assert_not_called()

    def test_green_components_never_generate_human_approval_or_stage_promotion(self):
        identity = {'headCommit': 'a' * 40, 'workingTreeClean': True, 'workingTreeStatusSha256': 'b' * 64}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(subject.compatibility, 'commit', return_value='c' * 40), \
             patch.object(subject.compatibility, 'evaluate', return_value={'status': 'review_required'}), \
             patch.object(subject, 'repository_identity', return_value=identity), \
             patch.object(subject, 'run_suite', return_value={'status': 'passed', 'testCount': 1}), \
             patch.object(subject.backend, 'evaluate', return_value={'status': 'pass'}):
            output = Path(directory) / 'evidence'
            report = subject.evaluate(output, base='baseline')
            signoff = json.loads((output / 'stage0-signoff.json').read_text())
            self.assertEqual(report['status'], 'component_checks_passed_stage_incomplete')
            self.assertFalse(report['stage1PromotionAllowed'])
            self.assertFalse(signoff['automaticApproval'])
            self.assertEqual(signoff['engineering']['status'], 'pending')
            self.assertIn('compatibility_review_required', signoff['blockers'])
            self.assertTrue(report['unimplementedRequirements'])
            self.assertEqual(signoff['reportSha256'], hashlib.sha256((output / 'stage0-report.json').read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError): subject.evaluate(output, base='baseline')

    def test_changed_or_dirty_head_is_failed_evidence(self):
        clean = {'headCommit': 'a' * 40, 'workingTreeClean': True}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(subject.compatibility, 'commit', return_value='c' * 40), \
             patch.object(subject.compatibility, 'evaluate', return_value={'status': 'backend_only_unchanged'}), \
             patch.object(subject, 'repository_identity', side_effect=[clean, {**clean, 'workingTreeClean': False}]), \
             patch.object(subject, 'run_suite', return_value={'status': 'passed', 'testCount': 1}), \
             patch.object(subject.backend, 'evaluate', return_value={'status': 'pass'}):
            report = subject.evaluate(Path(directory) / 'evidence', base='baseline')
            self.assertEqual(report['status'], 'component_checks_failed')
            self.assertFalse(report['cleanStableHead'])


if __name__ == '__main__':
    unittest.main()
