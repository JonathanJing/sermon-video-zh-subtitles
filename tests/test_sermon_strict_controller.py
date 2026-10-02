"""Actual D3/D5 composition with synthetic transports; no acceptance/model run."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from scripts import sermon_accounting as accounting
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_controller as controller
from scripts import sermon_workflow_jobs as jobs
from scripts import sermon_strict_budget_adapter as adapter
from scripts import sermon_provider_limits as limits
from scripts import sermon_strict_layer2 as strict
from tests import test_sermon_strict_budget_adapter as fixtures


class StrictControllerTests(unittest.TestCase):
    def setUp(self):
        self.runtime = fixtures.StrictBudgetTests(); self.runtime.setUp()
        self.addCleanup(self.runtime.doCleanups)
        self.f, self.store = self.runtime.f, self.runtime.store
        self.root = self.f.root / 'controller'
        self.job_root = self.f.root / 'jobs'
        self.graph = [dict(workUnitId=self.f.prepared['workUnitId'], layer=2,
                           targetLocale='zh-Hans', dependsOn=[])]

    def run_group(self, **options):
        values = dict(root=self.root, store=self.store, job_root=self.job_root,
            production_run_id='7'*64, graph=self.graph, candidate_id='candidate',
            api_key='synthetic', caller=self.f.transport, bounds=fixtures.bounds(),
            usage_resolver=fixtures.measured, created_at='2026-09-30T00:00:00Z')
        values.update(options)
        return controller.run_group(self.f.prepared, **values)

    def snapshot(self):
        return self.store.snapshot(adapter.chain_identity(self.f.prepared))

    def test_real_pass_and_restart_select_same_immutable_revision_without_calls(self):
        with self.f.session():
            first = self.run_group()
            self.assertEqual(first['status'], 'machine_review_passed')
            self.assertEqual(first['reviewAttempt'], 1)
            self.assertEqual(first['reviewReceipt']['reviewVerdict'], 'pass')
            self.assertEqual(first['executionAuthority'], 'none')
            path = Path(first['root']) / 'candidate.json'; before = path.read_bytes()
            self.store = budget.BudgetStore(self.store.root, fixtures.authority())
            second = self.run_group()
            self.assertEqual(second['root'], first['root'])
            self.assertEqual(second['candidateRevision'], first['candidateRevision'])
            self.assertEqual(second['reviewReceipt'], first['reviewReceipt'])
            self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self.f.calls), 2)
        self.assertEqual(len(self.snapshot()['reservations']), 2)

    def test_returned_structural_failure_keeps_specific_reason_and_stops_before_review(self):
        self.f.f.evidence['groups'][0]['coverage'] = {}
        with self.f.session():
            result = self.run_group()
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(result['reasonCode'], 'invalid_candidate_coverage')
            self.assertEqual(result['failureEvidence']['providerOutcome'], 'returned')
            self.assertIsNone(result['candidateRevision'])
            self.assertIsNone(result['reviewReceipt'])
            self.assertEqual(self.run_group()['failureEvidence'], result['failureEvidence'])
        self.assertEqual(len(self.f.calls), 1)
        self.assertFalse(self.snapshot()['unknownReservations'])

    def test_known_returned_structural_failure_does_not_invent_missing_usage(self):
        self.f.f.evidence['groups'][0]['coverage'] = {}
        with self.f.session():
            result = self.run_group(usage_resolver=lambda _: None)
            self.assertEqual(result['status'], 'reconciliation_required')
            self.assertEqual(result['reasonCode'], 'invalid_candidate_coverage')
            self.assertEqual(result['failureEvidence']['providerOutcome'], 'returned')
        self.assertTrue(self.snapshot()['unknownReservations'])
        self.assertEqual(len(self.f.calls), 1)

    def test_safe_contract_reason_is_preserved_but_exception_body_is_not(self):
        with self.f.session(), patch.object(adapter.StrictBudgetAdapter, 'generate',
                side_effect=c.ContractError('provider_input_bound_exceeded')):
            self.assertEqual(self.run_group()['reasonCode'], 'provider_input_bound_exceeded')
        private = 'private text /Users/secret API_KEY=secret'
        with self.f.session(), patch.object(adapter.StrictBudgetAdapter, 'generate',
                side_effect=c.ContractError(private)):
            result = self.run_group()
            self.assertEqual(result['reasonCode'], 'current_evidence_not_validated')
            self.assertNotIn(private, json.dumps(result))
        self.assertEqual(self.f.calls, [])

    def test_actual_input_preflight_preserves_reason_without_reservation_or_dispatch(self):
        class InputBoundCaller:
            def preflight(self, prepared, kind, root, repair):
                selected = dict(limits.DEFAULT_REQUEST_LIMITS, maxInputTokens=1)
                payload = strict._payload(prepared, 'translator', strict.prompt(prepared, 'translator'))
                return limits.request_bounds(payload, selected)

            def __call__(self, *args, **kwargs):
                raise AssertionError('preflight failure must not dispatch')

        with self.f.session():
            result = self.run_group(caller=InputBoundCaller())
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(result['reasonCode'], 'provider_input_bound_exceeded')
            self.assertIsNone(result['candidateRevision'])
        self.assertEqual(self.f.calls, [])
        self.assertEqual(self.snapshot()['reservations'], [])
        self.assertEqual(adapter.safe_failure_reason(ValueError('private transcript /Users/secret')),
                         'current_evidence_not_validated')

    def test_review_pre_dispatch_refusal_is_a_known_stop_and_restart_never_retries(self):
        attempts = []; executor = Mock(side_effect=AssertionError('must not dispatch'))
        refused = fixtures.refused_before_observer(attempts, executor)
        original = self.f.transport
        def caller(key, payload, **options):
            return (original if payload['model'] == 'gpt-6-astra' else refused)(key, payload, **options)
        with self.f.session():
            result = self.run_group(caller=caller)
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(result['reasonCode'], 'provider_request_limit')
            self.assertEqual(result['failureEvidence']['providerOutcome'], 'not_dispatched')
            self.assertIsNone(result['reviewReceipt'])
            self.assertEqual(self.run_group(caller=caller)['failureEvidence'], result['failureEvidence'])
        self.assertEqual(len(self.f.calls), 1)
        self.assertEqual(len(attempts), 1)
        self.assertFalse(self.snapshot()['unknownReservations'])
        executor.assert_not_called()

    def test_known_review_execution_failure_retries_only_review(self):
        reviews = []; original = self.f.transport
        def responder(key, payload, **kwargs):
            if payload['model'] == 'gpt-6-sol':
                reviews.append(1)
                self.f.mode = 'rewrite' if len(reviews) == 1 else 'pass'
            return original(key, payload, **kwargs)
        with self.f.session():
            value = self.run_group(caller=responder)
            self.assertEqual(value['status'], 'machine_review_passed')
            self.assertEqual(value['reviewAttempt'], 2)
            self.run_group(caller=responder)
        self.assertEqual([p['model'] for p in self.f.calls], ['gpt-6-astra','gpt-6-sol','gpt-6-sol'])

    def test_two_known_review_failures_stop_without_generation_or_third_attempt(self):
        self.f.mode = 'rewrite'
        with self.f.session():
            value = self.run_group()
            self.assertEqual(value['reasonCode'], 'review_execution_limit_reached')
            self.assertEqual(value['reviewAttempt'], 2)
            self.assertEqual(value['status'], 'blocked')
            repeated = self.run_group()
            self.assertEqual(repeated['reasonCode'], value['reasonCode'])
        self.assertEqual(len(self.f.calls), 3)

    def test_known_content_failure_creates_reviewed_child_preserving_parent(self):
        original = self.f.transport; generations = []
        def responder(key, payload, **kwargs):
            if payload['model'] == 'gpt-6-astra':
                generations.append(1)
                if len(generations) > 1:
                    self.f.f.evidence['groups'][0]['targetUtterances'][0] += ' 修订'
            self.f.mode = 'fail' if len(generations) == 1 else 'pass'
            return original(key, payload, **kwargs)
        with self.f.session():
            value = self.run_group(caller=responder)
            self.assertEqual(value['status'], 'machine_review_passed')
            self.assertEqual(value['revisionNumber'], 2)
            root = Path(value['root'])
            self.assertEqual((root/'parent-candidate.json').read_bytes(),
                (self.root/'revisions/initial/candidate.json').read_bytes())
            self.assertEqual(value['candidateRevision']['parentRevisionId'], 'initial')
            self.assertTrue((self.store.root/budget.STORE_ID/'repair-planning.json').exists())
            self.store = budget.BudgetStore(self.store.root, fixtures.authority())
            replay = self.run_group(caller=responder)
            self.assertEqual(replay['revisionId'], value['revisionId'])
        self.assertEqual(len(self.f.calls), 4)
        self.assertEqual(self.snapshot()['contentRevisions'], 1)

    def test_repeated_same_failure_stops_at_consumed_fingerprint(self):
        self.f.mode = 'fail'
        with self.f.session():
            value = self.run_group()
            self.assertEqual(value['status'], 'blocked')
            self.assertEqual(value['reasonCode'], 'repeated_failure_without_new_evidence')
            self.assertEqual(value['revisionNumber'], 2)
        self.assertEqual(len(self.f.calls), 4)

    def test_changed_content_can_use_only_two_durable_revisions(self):
        self.f.mode = 'fail'; original = self.f.transport
        def responder(key, payload, **kwargs):
            if payload['model'] == 'gpt-6-astra':
                self.f.f.evidence['groups'][0]['targetUtterances'][0] += ' 修订'
            return original(key, payload, **kwargs)
        with self.f.session():
            value = self.run_group(caller=responder)
            self.assertEqual(value['status'], 'blocked')
            self.assertEqual(value['reasonCode'], 'content_revision_limit_reached')
            self.assertEqual(value['revisionNumber'], 3)
        self.assertEqual(len(self.f.calls), 6)
        self.assertEqual(self.snapshot()['contentRevisions'], 2)

    def test_unknown_review_stops_and_restart_never_retries_transport(self):
        attempts = []; original = self.f.transport
        def responder(key, payload, *, response_observer):
            attempts.append(payload['model'])
            if payload['model'] == 'gpt-6-sol':
                call = accounting.record_api_started(payload['model'], accounting.request_metadata(payload))
                response_observer.request_started(call)
                raise TimeoutError('synthetic lost response')
            return original(key, payload, response_observer=response_observer)
        with self.f.session():
            value = self.run_group(caller=responder)
            self.assertEqual(value['status'], 'reconciliation_required')
            self.assertEqual(value['reviewReceipt']['executionStatus'], 'outcome_unknown')
            self.store = budget.BudgetStore(self.store.root, fixtures.authority())
            value = self.run_group(caller=responder)
            self.assertEqual(value['status'], 'reconciliation_required')
        self.assertEqual(attempts, ['gpt-6-astra','gpt-6-sol'])

    def test_unknown_usage_keeps_real_candidate_but_stops_before_review(self):
        with self.f.session():
            value = self.run_group(usage_resolver=None)
            self.assertEqual(value['status'], 'reconciliation_required')
            self.assertIsNotNone(value['candidateRevision'])
            self.assertIsNone(value['reviewReceipt'])
            self.assertEqual(len(self.f.calls), 1)
            # Trusted complete measurements can settle a saved call locally.
            value = self.run_group()
            self.assertEqual(value['status'], 'machine_review_passed')
        self.assertEqual(len(self.f.calls), 2)

    def test_logging_failure_propagates_without_automatic_paid_retry(self):
        with self.f.session():
            with patch.object(accounting, 'record_api_attempt', side_effect=accounting.AccountingWriteError('synthetic')):
                with self.assertRaises(accounting.AccountingWriteError): self.run_group()
            self.assertEqual(len(self.f.calls), 1)
            self.assertTrue(self.snapshot()['unknownReservations'])
            value = self.run_group()
            self.assertEqual(value['status'], 'machine_review_passed')
        self.assertEqual(len(self.f.calls), 2)

    def test_review_logging_failure_recovers_saved_response_without_second_review(self):
        original = accounting.record_api_attempt
        def fail_review(model, *args, **kwargs):
            if model == 'gpt-6-sol':
                raise accounting.AccountingWriteError('synthetic review logging failure')
            return original(model, *args, **kwargs)
        with self.f.session():
            with patch.object(accounting, 'record_api_attempt', side_effect=fail_review):
                with self.assertRaises(accounting.AccountingWriteError): self.run_group()
            self.assertEqual(len(self.f.calls), 2)
            self.assertTrue(self.snapshot()['unknownReservations'])
            value = self.run_group()
            self.assertEqual(value['status'], 'machine_review_passed')
        self.assertEqual(len(self.f.calls), 2)

    def test_unknown_child_generation_does_not_relabel_parent_as_current_candidate(self):
        original = self.f.transport; generations = []
        self.f.mode = 'fail'
        def responder(key, payload, *, response_observer):
            if payload['model'] == 'gpt-6-astra':
                generations.append(1)
                if len(generations) == 2:
                    call = accounting.record_api_started(payload['model'], accounting.request_metadata(payload))
                    response_observer.request_started(call)
                    raise TimeoutError('synthetic unknown child')
            return original(key, payload, response_observer=response_observer)
        with self.f.session():
            value = self.run_group(caller=responder)
            self.assertEqual(value['status'], 'reconciliation_required')
            self.assertEqual(value['revisionNumber'], 2)
            self.assertIsNone(value['candidateRevision'])
            self.assertTrue((self.root/'revisions/initial/candidate.json').exists())
            again = self.run_group(caller=responder)
            self.assertEqual(again['status'], 'reconciliation_required')
            self.assertIsNone(again['candidateRevision'])
        self.assertEqual(len(generations), 2)
        self.assertEqual(len(self.f.calls), 2)

    def test_missing_current_evidence_and_changed_config_never_regenerate(self):
        with self.f.session():
            value = self.run_group()
            (Path(value['root'])/'generator.raw.json').unlink()
            stopped = self.run_group()
            self.assertEqual(stopped['status'], 'blocked')
            with self.assertRaises(ValueError): self.run_group(candidate_id='different')
            moved = self.run_group(root=self.f.root/'moved')
            self.assertEqual(moved['status'], 'blocked')
        self.assertEqual(len(self.f.calls), 2)

    def reason_transport(self, reason):
        original = self.f.transport; self.f.mode = 'fail'
        def responder(key, payload, *, response_observer):
            if payload['model'] != 'gpt-6-sol':
                return original(key, payload, response_observer=response_observer)
            def observe(response, call, elapsed):
                value = json.loads(response['choices'][0]['message']['content'])
                value['issues'][0]['reasonCode'] = reason
                response['choices'][0]['message']['content'] = json.dumps(value)
                return response_observer(response, call, elapsed)
            observe.request_started = response_observer.request_started
            observe.request_rejected = response_observer.request_rejected
            return original(key, payload, response_observer=observe)
        return responder

    def test_source_ambiguity_stops_for_source_review_without_repair(self):
        with self.f.session():
            value = self.run_group(caller=self.reason_transport('source_ambiguity'))
            self.assertEqual(value['reasonCode'], 'source_ambiguity')
            self.assertEqual(value['planning']['action'], 'request_source_review')
            self.assertEqual(value['status'], 'blocked')
        self.assertEqual(len(self.f.calls), 2)
        self.assertEqual(self.snapshot()['contentRevisions'], 0)

    def test_insufficient_evidence_stops_for_human_without_decision_model(self):
        with self.f.session():
            value = self.run_group(caller=self.reason_transport('evidence_insufficient'))
            self.assertEqual(value['reasonCode'], 'evidence_insufficient')
            self.assertEqual(value['planning']['action'], 'request_human_review')
            self.assertEqual(value['status'], 'blocked')
        self.assertEqual(len(self.f.calls), 2)
        self.assertEqual(self.snapshot()['decisionProposals'], 0)

    def test_cross_group_repair_requires_separate_bound_evidence(self):
        self.f.mode = 'fail'
        self.graph.append(dict(workUnitId='l2.zh-Hans.other', layer=2,
            targetLocale='zh-Hans', dependsOn=[self.f.prepared['workUnitId']]))
        with self.f.session():
            value = self.run_group()
            self.assertEqual(value['reasonCode'], 'dependency_group_repair_required')
        self.assertEqual(len(self.f.calls), 2)
        self.assertEqual(self.snapshot()['contentRevisions'], 0)

    def test_existing_group_lock_blocks_concurrent_runner_before_calls(self):
        lock_id = jobs._digest({'scope': controller.SCHEMA, 'store': self.store.store_sha256,
                              'chain': adapter.chain_identity(self.f.prepared)})
        with self.f.session(), jobs._lock(self.job_root, lock_id) as (_, _, held):
            self.assertTrue(held)
            with self.assertRaisesRegex(ValueError, 'strict_group_controller_busy'): self.run_group()
        self.assertEqual(self.f.calls, [])

    def test_actual_accounting_dependencies_link_group_operations(self):
        completed = []
        with self.f.session():
            with accounting.stage('upstream', executor_type='deterministic_program') as upstream:
                pass
            value = self.run_group(depends_on=[upstream], completion_spans=completed)
            self.assertEqual(value['completedSpans'], completed)
            self.assertTrue(completed)
        events, invalid = accounting.read_events(self.f.root/'logs'); self.assertFalse(invalid)
        starts = {row['spanId']: row for row in events if row['event']=='stage_started'}
        # Actual strict stages retain the explicit upstream edge; review starts
        # after the completed candidate-freeze stage rather than an unrelated root.
        self.assertTrue(any(upstream in (row.get('dependsOn') or []) for row in starts.values()))
        self.assertTrue(any(completed[0] in (row.get('dependsOn') or []) for row in starts.values()))

    def test_invalid_graph_and_missing_profile_fail_before_transport(self):
        with self.assertRaisesRegex(ValueError, 'strict_requires_accounting_profile'): self.run_group()
        with self.f.session():
            with self.assertRaises(ValueError): self.run_group(graph=[])
            with self.assertRaises(ValueError): self.run_group(depends_on=['unsafe dependency'])
            with self.assertRaises(ValueError): self.run_group(depends_on=['span']*65)
            with self.assertRaises(ValueError): self.run_group(completion_spans=())
        self.assertEqual(self.f.calls, [])

    def test_timestamp_contract_rejects_offsets_and_excess_precision_before_calls(self):
        self.f.mode = 'fail'
        with self.f.session():
            for stamp in ('2026-09-30T00:00:00+00:00', '2026-09-30T00:00:00.1234567Z',
                          '2026-09-30', '2026-02-30T00:00:00Z'):
                with self.subTest(stamp=stamp), self.assertRaisesRegex(ValueError, 'invalid_controller_created_at'):
                    self.run_group(created_at=stamp)
            self.assertEqual(self.f.calls, [])
            result = self.run_group(created_at='2026-09-30T00:00:00.123456Z')
            self.assertEqual(result['reasonCode'], 'repeated_failure_without_new_evidence')
        self.assertEqual(len(self.f.calls), 4)


if __name__ == '__main__': unittest.main()
