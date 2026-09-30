import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker
from scripts import sermon_log_contract as contract
from scripts import sermon_accounting as accounting
from scripts import export_observability_trace as safe
from scripts import export_sermon_trace as otlp
from scripts import weekly_pipeline_report as weekly

FIXTURES = Path(__file__).parent / 'fixtures/accounting_log_contract'


def fixture(name):
    return json.loads((FIXTURES / (name + '.json')).read_text())


def ledger(directory, rows):
    (Path(directory) / 'events.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))


class ContractTests(unittest.TestCase):
    def test_positive_fixtures_share_jsonschema_and_python_contract(self):
        validator = Draft202012Validator(json.loads(contract.SCHEMA_PATH.read_text()), format_checker=contract.format_checker())
        for name in ('stage-start', 'stage-finish', 'api-receipt'):
            row = fixture(name)
            self.assertTrue(validator.is_valid(row), name)
            self.assertIs(contract.validate_event(row), row)
            self.assertTrue(accounting._valid_event(row))

    def test_negative_types_and_bounds_rejected_by_both_readers(self):
        validator = Draft202012Validator(json.loads(contract.SCHEMA_PATH.read_text()), format_checker=contract.format_checker())
        changes = [('sequence', True), ('sequence', 0), ('sequence', 2**53), ('event', 'arbitrary'),
                   ('runId', '/private/path'), ('runId', 'private\n'), ('runId', 'x'*101), ('contractVersion', 'future'),
                   ('recordedAt', '2026-09-30T00:00:00'), ('recordedAt', '2026-02-30T00:00:00Z'),
                   ('executorType', 'fixed_program'), ('prompt', 'private'), ('dependsOn', ['same', 'same']),
                   ('dependsOn', [f'span-{i}' for i in range(65)]), ('queuedAt', 0)]
        for key, value in changes:
            row = fixture('stage-start'); row[key] = value
            with self.subTest(key=key, value=str(value)[:20]):
                self.assertFalse(validator.is_valid(row))
                self.assertFalse(accounting._valid_event(row))
        for key in fixture('stage-start'):
            if key in {'monotonicStartNs', 'contractVersion'}: continue
            row = fixture('stage-start'); del row[key]
            self.assertFalse(accounting._valid_event(row), key)

    def test_no_bool_or_nonfinite_or_implicit_integer_conversion(self):
        for key, value in [('sequence', 1.0), ('elapsedSeconds', float('nan')),
                           ('elapsedSeconds', float('inf')), ('elapsedSeconds', True)]:
            row = fixture('stage-finish'); row[key] = value
            self.assertFalse(accounting._valid_event(row))

    def test_null_reasons_aliases_and_monotonic_identity(self):
        row = fixture('api-receipt'); del row['missingReasons']['cachedInputTokens']
        self.assertFalse(accounting._valid_event(row))
        for key in ('modelCallId', 'providerResponseId'):
            row = fixture('api-receipt'); row[key] = 'contradiction'
            self.assertFalse(accounting._valid_event(row))
        row = fixture('stage-finish'); row['monotonicEndNs'] = '5000000000'
        self.assertFalse(accounting._valid_event(row))

    def test_bounded_event_rejects_before_any_storage_side_effect(self):
        row = fixture('stage-start'); row['extra'] = 'x' * contract.MAX_EVENT_BYTES
        with self.assertRaisesRegex(contract.ContractError, '^event_size_limit$'):
            contract.validate_event(row)

    def test_unknown_profile_quarantined_with_raw_hash_and_legacy_unchanged(self):
        profile = fixture('stage-start'); profile['contractVersion'] = 'future'
        legacy = {k:v for k,v in fixture('stage-start').items() if k != 'contractVersion'}
        with tempfile.TemporaryDirectory() as directory:
            ledger(directory, [profile, legacy])
            events, damaged = accounting.read_events(directory)
            self.assertEqual(events, [legacy]); self.assertEqual(len(damaged), 1)
            self.assertEqual(len(damaged[0]['sha256']), 64)
            self.assertNotIn('sequence', {k:v for k,v in events[0].items() if k not in legacy})

    def test_replay_reordering_duplicates_conflicts_and_gaps(self):
        start, end = fixture('stage-start'), fixture('stage-finish')
        self.assertEqual(contract.replay_integrity([end, start])['status'], 'consistent')
        self.assertEqual(contract.replay_integrity([end, start, copy.deepcopy(end)])['equivalentDuplicatesIgnored'], 1)
        conflicting = dict(end, elapsedSeconds=3.0, monotonicEndNs='4000000000')
        for rows in ([start, end, conflicting], [conflicting, end, start]):
            result = contract.replay_integrity(rows)
            self.assertEqual(result['status'], 'partial')
            self.assertIn('event_conflict', [d['code'] for d in result['diagnostics']])
            self.assertIn(id(end), result['_excluded'])
        collision = dict(end, sequence=1)
        result = contract.replay_integrity([start, collision])
        self.assertIn('producer_sequence_conflict', [d['code'] for d in result['diagnostics']])
        huge = dict(end, sequence=2**53-1)
        result = contract.replay_integrity([start, huge])
        gap = next(d for d in result['diagnostics'] if d['code'] == 'sequence_gap')
        self.assertEqual((gap['first'], gap['last']), (2, 2**53-2))

    def test_start_finish_binding_and_terminal_cannot_reopen(self):
        start, end = fixture('stage-start'), fixture('stage-finish')
        changed = dict(end, attemptId='other')
        result = contract.replay_integrity([start, changed])
        self.assertIn('start_finish_identity_conflict', [d['code'] for d in result['diagnostics']])
        second = dict(end, eventId='7'*32, sequence=3)
        result = contract.replay_integrity([start, end, second])
        self.assertIn('attempt_reopened_or_multiple_terminal', [d['code'] for d in result['diagnostics']])
        self.assertEqual(contract.replay_integrity([start])['status'], 'partial')

    def test_reader_conflicts_and_safe_export_are_order_independent(self):
        start, end, api = fixture('stage-start'), fixture('stage-finish'), fixture('api-receipt')
        conflict = copy.deepcopy(api); conflict['usage']['inputTokens'] = 200
        for rows in ([start, end, api, conflict], [conflict, api, end, start]):
            with tempfile.TemporaryDirectory() as directory:
                ledger(directory, rows)
                reports = [weekly.project(directory), otlp.export(directory)[1]]
                reports.append(accounting._summarize_locked(Path(directory)))
                for report in reports:
                    self.assertEqual(report['receiptIntegrity']['status'], 'conflicted')
                    self.assertEqual(report['eventIntegrity']['status'], 'partial')
                safe.export(Path(directory), Path(directory)/'export')
                projected = weekly.project(Path(directory)/'export')
                self.assertEqual(projected['receiptIntegrity']['status'], 'conflicted')

    def test_receipts_separate_provider_scopes_and_unknown_scope_calls(self):
        a = fixture('api-receipt'); b = copy.deepcopy(a)
        b.update(eventId='7'*32, sequence=4, modelCallId='call-2', attemptId='call-2')
        self.assertEqual(accounting.receipt_integrity([a,b])['equivalentDuplicatesIgnored'], 1)
        b['providerScopeKey'] = '8'*64
        self.assertEqual(accounting.receipt_integrity([a,b])['equivalentDuplicatesIgnored'], 0)
        for row in (a,b):
            row['providerScopeKey'] = None; row['missingReasons']['providerScopeKey'] = 'not_observed'
        self.assertEqual(accounting.receipt_integrity([a,b])['equivalentDuplicatesIgnored'], 0)

    def test_safe_export_preserves_profile_context_and_hashes_aliases_together(self):
        row = fixture('api-receipt')
        row.update(parentWorkflowId='parent', dispatchSpanId='dispatch', jobId='job',
                   settings={'requestPayloadSha256':'9'*64})
        result = safe.safe_event(row)
        self.assertEqual(result['responseId'], result['providerResponseId'])
        self.assertNotEqual(result['responseId'], row['responseId'])
        for key in ('parentWorkflowId','dispatchSpanId','jobId','settings','missingReasons','sequence','producerId'):
            self.assertEqual(result[key], row[key])

    def test_step_transitions_do_not_grant_execution_or_reopen_terminal(self):
        base = fixture('stage-start')
        for key in ('stage','startedAt','dependsOn','blockedBy','dependencyReadyAt','queuedAt','clockDomainId','monotonicStartNs'):
            base.pop(key)
        transitions = [(None,'pending'),('pending','ready'),('ready','running'),('running','waiting_human'),
                       ('waiting_human','ready'),('ready','running'),('running','succeeded')]
        rows = [dict(base,event='step_state_changed',eventId=f'{i:032x}',sequence=i,stepId='step',
                     stateRevision='a'*64,reasonCode='observed',fromState=old,toState=new)
                for i,(old,new) in enumerate(transitions,1)]
        self.assertEqual(contract.replay_integrity(rows)['status'], 'consistent')
        rows.append(dict(rows[-1],eventId='b'*32,sequence=8,fromState='succeeded',toState='running'))
        result = contract.replay_integrity(rows)
        self.assertEqual(result['executionAuthority'],'none')
        self.assertIn('illegal_step_transition',[d['code'] for d in result['diagnostics']])


if __name__ == '__main__': unittest.main()
