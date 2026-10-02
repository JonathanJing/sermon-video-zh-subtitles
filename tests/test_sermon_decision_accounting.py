import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_decision_accounting as observations
from scripts import sermon_decision_budget as budget_module
from scripts import weekly_pipeline_report
from tests.test_sermon_decision_budget import packet, response


class DecisionAccountingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.ledger = self.root / 'accounting'
        self.budget = budget_module.Budget(self.root / 'jobs', 'a' * 64)

    def propose(self, p=None, responder=response, fresh=None):
        p = p or packet()
        return budget_module.propose(p, budget=self.budget, responder=responder,
                                     fresh_packet=fresh or (lambda: p))

    def evidence(self):
        events, damaged = accounting.read_events(self.ledger)
        self.assertEqual(damaged, [])
        rows = [observations.safe_observation(e['fields']) for e in events
                if e['event'] == 'log' and e.get('code') == observations.CODE]
        return events, rows

    def test_real_ledger_separates_fixed_work_model_and_commit_without_inventing_usage(self):
        p = packet()
        with accounting.accounting_session(self.ledger, 'decision_test'):
            result = self.propose(p)
        events, rows = self.evidence()
        self.assertEqual(result['status'], 'proposal_requires_locked_admission')
        self.assertEqual([r['phase'] for r in rows], ['turn', 'commit'])
        self.assertEqual(rows[0]['observationId'], rows[1]['observationId'])
        self.assertEqual(rows[0]['statePacketSha256'], result['packetSha256'])
        self.assertEqual(rows[0]['statePacketBytes'], result['packetBytes'])
        self.assertIsNone(rows[0]['timings']['statePacketBuildMs'])
        self.assertIsNone(rows[0]['timings']['stateCommitMs'])
        self.assertIsNone(rows[1]['timings']['modelLatencyMs'])
        self.assertGreaterEqual(rows[1]['timings']['stateCommitMs'], 0)
        leaves = [e for e in events if e['event'] == 'stage_started' and e['stage'].startswith('decision.')]
        self.assertEqual(len(leaves), 5)
        self.assertEqual([e['executorType'] for e in leaves], ['deterministic_program', 'deterministic_program',
                         'decision_agent', 'deterministic_program', 'deterministic_program'])
        self.assertIsNone(leaves[0]['dependsOn'])  # Upstream producer DAG is not fabricated.
        for before, after in zip(leaves, leaves[1:]):
            self.assertEqual(after['dependsOn'], [before['spanId']])
        self.assertEqual({e['decisionId'] for e in leaves}, {p['decisionId']})
        projected = weekly_pipeline_report.project(self.ledger)['runs'][0]
        self.assertEqual(sorted(projected['decisionObservations'], key=lambda r: r['phase']),
                         sorted(rows, key=lambda r: r['phase']))
        self.assertIn('Decision observations', weekly_pipeline_report.markdown({'status': 'partial', 'runs': [projected]}))
        self.assertEqual(projected['usage']['directReceipts'], [])
        self.assertEqual(projected['usage']['sdkAggregates'], [])
        self.assertIsNone(projected['usage']['combinedTokenTotal'])
        raw = (self.ledger / 'events.jsonl').read_text()
        self.assertNotIn('evidenceRefs', raw)
        self.assertNotIn('allowedActions', raw)

    def test_budget_replay_has_no_second_model_span_and_leaves_unknown_latency(self):
        calls = []
        def responder(p): calls.append(1); return response(p)
        with accounting.accounting_session(self.ledger, 'decision_test'):
            self.propose(responder=responder)
            again = self.propose(responder=responder)
        events, rows = self.evidence()
        self.assertEqual(again['reasonCode'], 'decision_budget_unavailable')
        self.assertEqual(calls, [1])
        self.assertEqual(sum(e['event'] == 'stage_started' and e.get('executorType') == 'decision_agent' for e in events), 1)
        self.assertIsNone(rows[-1]['timings']['modelLatencyMs'])

    def test_unknown_response_and_invalid_output_never_log_private_payloads(self):
        for failure in ('unknown', 'invalid'):
            with self.subTest(failure=failure):
                ledger = self.root / failure
                self.budget = budget_module.Budget(self.root / (failure + '-jobs'), 'a' * 64)
                def responder(p):
                    if failure == 'unknown': raise RuntimeError('PRIVATE PROMPT AND CREDENTIAL')
                    return {'private': 'PRIVATE PROMPT AND CREDENTIAL'}
                with accounting.accounting_session(ledger, 'decision_test'):
                    result = self.propose(responder=responder)
                self.assertNotIn('PRIVATE', (ledger / 'events.jsonl').read_text())
                self.assertFalse(result['dispatchEnabled'])
                self.assertEqual(result['reasonCode'], 'decision_outcome_unknown' if failure == 'unknown' else 'decision_rejected')

    def test_logging_failure_before_model_blocks_call_and_consumes_uncertain_reservation(self):
        original = accounting._emit
        def emit(event):
            if event.get('event') == 'stage_started' and event.get('stage') == 'decision.modelLatencyMs':
                raise accounting.AccountingWriteError('injected')
            return original(event)
        with accounting.accounting_session(self.ledger, 'decision_test'):
            with patch.object(accounting, '_emit', side_effect=emit), patch(__name__ + '.response') as responder:
                result = self.propose(responder=responder)
                responder.assert_not_called()
            self.assertEqual(result['reasonCode'], 'decision_outcome_unknown')
        self.assertEqual(self.budget.remaining(), 0)

    def test_logging_failure_after_model_cannot_retry_or_release_unknown_budget(self):
        original = accounting._emit
        calls = []
        def emit(event):
            if event.get('code') == observations.CODE:
                raise accounting.AccountingWriteError('injected')
            return original(event)
        def responder(p): calls.append(1); return response(p)
        with accounting.accounting_session(self.ledger, 'decision_test'):
            with patch.object(accounting, '_emit', side_effect=emit):
                with self.assertRaises(accounting.AccountingWriteError): self.propose(responder=responder)
            self.assertEqual(self.propose(responder=responder)['reasonCode'], 'decision_budget_unavailable')
        self.assertEqual(calls, [1]); self.assertEqual(self.budget.remaining(), 0)

    def test_validation_log_failure_is_not_semantic_rejection_or_retry_permission(self):
        original = accounting._emit
        for boundary in ('stage_started', 'stage_finished'):
            with self.subTest(boundary=boundary):
                self.budget = budget_module.Budget(self.root / boundary / 'jobs', 'a' * 64)
                ledger = self.root / boundary / 'ledger'
                calls, failures = [], []
                def emit(event):
                    if (event.get('event') == boundary and event.get('stage') == 'decision.decisionValidationMs'
                            and not failures):
                        failures.append(1)
                        raise accounting.AccountingWriteError('transient validation log failure')
                    return original(event)
                def responder(p):
                    calls.append(p['decisionId'])
                    return response(p)
                with accounting.accounting_session(ledger, 'decision_test'):
                    with patch.object(accounting, '_emit', side_effect=emit):
                        with self.assertRaises(accounting.AccountingWriteError):
                            self.propose(responder=responder)
                    self.assertEqual(self.budget.remaining(), 0)
                    self.assertEqual(self.propose(packet(1, 'e' * 64), responder=responder)['reasonCode'],
                                     'decision_budget_unavailable')
                self.assertEqual(len(calls), 1)
                self.assertEqual(failures, [1])
                events, damaged = accounting.read_events(ledger)
                self.assertEqual(damaged, [])
                rows = [e['fields'] for e in events if e.get('code') == observations.CODE]
                self.assertFalse(any(row['status'] in {'decision_rejected', 'commit_recorded'} for row in rows))
                saved = budget_module.jobs._read(self.budget.folder / 'state.json')
                self.assertEqual([row['status'] for row in saved['attempts']], ['reserved'])

    def test_commit_log_failure_preserves_actual_durable_outcome_without_replay(self):
        original = accounting._emit
        calls = []
        def emit(event):
            if event.get('event') == 'stage_finished' and event.get('stage') == 'decision.stateCommitMs':
                raise accounting.AccountingWriteError('injected after durable commit')
            return original(event)
        def responder(p): calls.append(1); return response(p)
        with accounting.accounting_session(self.ledger, 'decision_test'):
            with patch.object(accounting, '_emit', side_effect=emit):
                with self.assertRaises(accounting.AccountingWriteError): self.propose(responder=responder)
            self.assertEqual(self.budget.remaining(), 1)
            self.assertEqual(self.propose(responder=responder)['reasonCode'], 'decision_budget_unavailable')
        self.assertEqual(calls, [1])
        _, rows = self.evidence()
        self.assertFalse(any(row['status'] == 'commit_failed' for row in rows))

    def test_conflicting_observation_payloads_are_not_first_writer_wins(self):
        with accounting.accounting_session(self.ledger, 'decision_test'):
            self.propose()
        events, rows = self.evidence()
        original = next(e for e in events if e.get('code') == observations.CODE)
        duplicate = copy.deepcopy(original); duplicate['eventId'] = 'equivalent-copy'
        path = self.ledger / 'events.jsonl'
        baseline = path.read_text()
        path.write_text(baseline + json.dumps(duplicate) + '\n')
        report = weekly_pipeline_report.project(self.ledger)
        self.assertEqual(len(report['runs'][0]['decisionObservations']), 2)
        conflict = copy.deepcopy(duplicate); conflict['eventId'] = 'conflicting-copy'
        conflict['fields']['timings']['modelLatencyMs'] += 100
        conflicting = [*events, conflict]
        outcomes = []
        for ordered in (conflicting, list(reversed(conflicting))):
            path.write_text(''.join(json.dumps(event) + '\n' for event in ordered))
            run = weekly_pipeline_report.project(self.ledger)['runs'][0]
            self.assertIn('conflicting_decision_observations', run['diagnostics'])
            self.assertIsNone(run['criticalPath'])
            self.assertEqual(len(run['decisionObservations']), 1)
            outcomes.append(run['decisionObservations'])
        self.assertEqual(*outcomes)

    def test_read_side_rejects_sensitive_extra_fields_invalid_counts_and_nonfinite_timings(self):
        good = observations.Observation(packet()).fields
        for change in ({'parentContextInherited': True}, {'evidenceRefCount': 17}, {'statePacketBytes': True},
                       {'statePacketSha256': '/private/path'}, {'selectedAction': 'delete_all'},
                       {'phase': 'commit'}, {'private': 'PRIVATE'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                observations.safe_observation({**good, **change})
        bad = copy.deepcopy(good); bad['timings']['modelLatencyMs'] = float('inf')
        with self.assertRaises(ValueError): observations.safe_observation(bad)
        with accounting.accounting_session(self.ledger, 'decision_test'):
            accounting._emit({'event': 'log', 'code': observations.CODE, 'level': 'INFO',
                              'fields': {**good, 'private': 'PRIVATE'}})
        report = weekly_pipeline_report.project(self.ledger)
        self.assertIn('invalid_decision_observation', report['runs'][0]['diagnostics'])
        self.assertNotIn('PRIVATE', json.dumps(report))
        self.assertIsNone(report['runs'][0]['criticalPath'])


if __name__ == '__main__':
    unittest.main()
