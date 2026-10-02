"""Read-only projections must not confuse scheduler completion with recovery."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import sermon_accounting as accounting
from tests.mock_tts_sdk_diagnostics import result_summary, status_diagnostics
from tests.test_accounting_log_contract import fixture


class SDKStatusDiagnosticsTests(unittest.TestCase):
    def value(self, status='synthetic_complete'):
        return {'status': status, 'nodes': {'submit': {'executionStatus': 'completed'}},
                'engineEvidence': {'submit': {'engineState': 'Completed'}}}

    def events(self, status='outcome_unknown', reconciled=True):
        start, finish = fixture('stage-start'), fixture('stage-finish')
        finish['status'] = status
        rows = [start, finish]
        if reconciled:
            row = {**start, 'event': 'attempt_reconciled', 'eventId': '5'*32, 'sequence': 3,
                   'reconcilesAttemptId': finish['attemptId'], 'result': 'succeeded',
                   'evidenceSha256': 'a'*64, 'reasonCode': 'original_job_observed'}
            rows.append(row)
        self.assertTrue(all(accounting._valid_event(row) for row in rows))
        return rows

    def test_engine_completed_does_not_imply_business_completion(self):
        result = status_diagnostics(self.value('incomplete'), self.events(reconciled=False), [])
        self.assertEqual(result['engine']['aggregate'], 'all_tasks_completed')
        self.assertEqual(result['business']['status'], 'incomplete')
        self.assertEqual(result['history']['errorEventCount'], 1)
        self.assertEqual(result['history']['errors'][0]['reconciliation'], 'unknown')
        self.assertEqual(result['executionAuthority'], 'none')

    def test_business_success_does_not_reconcile_historical_failure(self):
        result = status_diagnostics(self.value(), self.events('failed', False), [])
        self.assertEqual(result['business']['status'], 'synthetic_complete')
        self.assertEqual(result['history']['errors'][0]['reconciliation'], 'unknown')

    def test_explicit_reconciliation_preserves_error_and_deduplicates_replay(self):
        rows = self.events()
        rows += copy.deepcopy(rows)
        result = status_diagnostics(self.value(), rows, [])
        self.assertEqual(result['history']['integrity'], 'consistent')
        self.assertEqual(result['history']['errorEventCount'], 1)
        self.assertEqual(result['history']['reconciliationEventCount'], 1)
        self.assertEqual(result['history']['errors'][0]['reconciliation'], 'recorded')
        self.assertEqual(result['history']['errors'][0]['reconciliationResult'], 'succeeded')

    def test_damaged_or_unbound_evidence_cannot_claim_reconciliation(self):
        for mode in ('damaged', 'different_attempt', 'different_job', 'duplicate_reconciliation'):
            with self.subTest(mode=mode):
                rows = self.events()
                if mode == 'different_attempt': rows[-1]['reconcilesAttemptId'] = 'other-attempt'
                if mode == 'different_job': rows[-1]['jobId'] = 'other-job'
                if mode == 'duplicate_reconciliation':
                    rows.append({**rows[-1], 'eventId': '6'*32, 'sequence': 4})
                result = status_diagnostics(self.value(), rows, [{}] if mode == 'damaged' else [])
                self.assertEqual(result['history']['errors'][0]['reconciliation'], 'unknown')

    def test_missing_engine_evidence_is_unknown(self):
        value = self.value(); value.pop('engineEvidence')
        result = status_diagnostics(value, [], [])
        self.assertEqual(result['engine']['aggregate'], 'unknown')
        self.assertEqual(result['history']['integrity'], 'unknown')
        self.assertIsNone(result['history']['errorEventCount'])

    def test_result_summary_reads_real_ledger_without_modifying_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/'accounting'; folder.mkdir()
            ledger = folder/'events.jsonl'
            ledger.write_text(''.join(json.dumps(row)+'\n' for row in self.events()))
            before = ledger.read_bytes()
            summary = result_summary(self.value(), tmp)
            self.assertEqual(summary['status'], 'synthetic_complete')
            self.assertEqual(summary['statusDiagnostics']['history']['errors'][0]['reconciliation'], 'recorded')
            self.assertEqual(ledger.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
