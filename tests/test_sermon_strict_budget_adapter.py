"""Actual D3 plus D5 with synthetic transport only; no paid calls or admission."""
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error

from scripts import sermon_accounting as accounting
from scripts import sermon_pipeline as pipeline
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as contracts
from scripts import sermon_repair_planning as planning
from scripts import sermon_strict_budget_adapter as adapter
from scripts import sermon_strict_layer2 as strict
from tests import test_sermon_strict_layer2 as strict_fixtures


def bounds():
    return dict(requests=1, inputTokens=1000, outputTokens=1000, wallTimeMs=10000, costMicrousd=1000)


def authority():
    limits = {key: value * 10 for key, value in bounds().items()}
    return dict(approvalSha256='f'*64, globalBounds=limits, unitBounds=limits,
                limits=deepcopy(budget.DEFAULT_LIMITS))


def measured(_):
    # Explicit synthetic fixture measurements, never the reservation bounds.
    return dict(requests=1, inputTokens=100, outputTokens=20, wallTimeMs=10, costMicrousd=50)


def refused_before_observer(attempts, executor):
    """Use the real pipeline lifecycle: guard denies before strict call proof."""
    def caller(key, payload, *, response_observer):
        req = pipeline.urllib.request.Request(pipeline.CHAT_URL)
        req.accounting_model = payload['model']
        req.accounting_settings = accounting.request_metadata(payload)
        def observer(response, call_id, elapsed):
            response_observer(response, call_id, elapsed)
        def guard(call_id):
            attempts.append(call_id)
            raise pipeline.PreDispatchRejection('provider_request_limit')
        observer.request_started = guard
        return pipeline.request_json(req, response_observer=observer, request_executor=executor)
    return caller


class StrictBudgetTests(unittest.TestCase):
    def setUp(self):
        self.f = strict_fixtures.StrictAdapterTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.root = self.f.root / 'revision'
        self.store = budget.BudgetStore(self.f.root / 'shared-budget', authority())
        self.subject = adapter.StrictBudgetAdapter(self.store)

    def generate(self, **options):
        return self.subject.generate(self.f.prepared, self.root, 'candidate', 'r1', 'synthetic-key',
            options.pop('caller', self.f.transport), bounds=options.pop('bounds', bounds()),
            usage_resolver=options.pop('usage_resolver', measured), **options)

    def review(self, **options):
        return self.subject.review(self.f.prepared, self.root, 'candidate', 'r1', 'synthetic-key',
            options.pop('caller', self.f.transport), bounds=options.pop('bounds', bounds()),
            usage_resolver=options.pop('usage_resolver', measured), **options)

    def restart(self):
        self.store = budget.BudgetStore(self.store.root, authority())
        self.subject = adapter.StrictBudgetAdapter(self.store)

    def snapshot(self):
        return self.store.snapshot(adapter.chain_identity(self.f.prepared))

    def test_other_chain_dispatch_lock_contention_retries_only_live_invocation(self):
        held=threading.Event();release=threading.Event();failures=[]
        def other_chain():
            try:
                with self.store._locked():
                    held.set()
                    if not release.wait(3):raise AssertionError('test lock not released')
            except BaseException as exc:failures.append(exc);held.set()
        thread=threading.Thread(target=other_chain)
        original=self.store.mark_request;attempts=[]
        def contend(rid):
            attempts.append(rid)
            if len(attempts)==1:
                thread.start();self.assertTrue(held.wait(3))
            return original(rid)
        def unlock(_):
            self.assertEqual(len(self.f.calls),0)
            release.set();thread.join(3);self.assertFalse(thread.is_alive())
        try:
            with self.f.session(), patch.object(self.store,'mark_request',side_effect=contend), \
                    patch.object(adapter.time,'sleep',side_effect=unlock):
                result=self.generate()
        finally:
            release.set()
            if thread.ident is not None:thread.join(3)
        self.assertEqual(failures,[])
        self.assertEqual(len(attempts),2);self.assertEqual(len(set(attempts)),1)
        self.assertEqual(result['budgetStatus'],'recorded');self.assertEqual(len(self.f.calls),1)
        self.assertEqual(len(self.snapshot()['reservations']),1)

    def test_dispatch_lock_wait_is_bounded_and_restart_does_not_regain_call_permission(self):
        with self.f.session(), patch.object(self.store,'mark_request',
                side_effect=contracts.ContractError('budget_store_busy')) as mark, \
                patch.object(adapter.time,'sleep') as sleep:
            with self.assertRaisesRegex(ValueError,'budget_store_busy'):self.generate()
        self.assertEqual(mark.call_count,adapter.DISPATCH_LOCK_ATTEMPTS)
        self.assertEqual(sleep.call_count,adapter.DISPATCH_LOCK_ATTEMPTS-1)
        self.assertEqual(len(self.f.calls),0)
        self.restart()
        with self.f.session(), self.assertRaises(ValueError):self.generate()
        self.assertEqual(len(self.f.calls),0)
        self.assertEqual(len(self.snapshot()['reservations']),1)

    def test_uncertain_mark_write_is_never_retried_even_if_error_looks_busy(self):
        original=self.store.mark_request
        def uncertain(rid):
            original(rid)
            raise contracts.ContractError('budget_store_busy')
        with self.f.session(), patch.object(self.store,'mark_request',side_effect=uncertain) as mark, \
                patch.object(adapter.time,'sleep') as sleep:
            with self.assertRaisesRegex(ValueError,'budget_store_busy'):self.generate()
        self.assertEqual(mark.call_count,1);sleep.assert_not_called()
        self.assertEqual(len(self.f.calls),0)
        self.restart()
        with self.f.session(), self.assertRaises(ValueError):self.generate()
        self.assertEqual(len(self.f.calls),0)

    def test_generation_and_review_bind_and_settle_without_changing_parent(self):
        with self.f.session():
            generated = self.generate(); before = (self.root / 'candidate.json').read_bytes()
            reviewed = self.review()
            self.assertEqual(generated['executionStatus'], 'succeeded')
            self.assertEqual(generated['contentStatus'], 'not_assessed')
            self.assertEqual(reviewed['contentStatus'], 'pass')
            self.assertEqual(reviewed['budgetStatus'], 'recorded')
            self.assertEqual(reviewed['executionAuthority'], 'none')
            self.assertIsNone(generated['artifact']['parentRevisionId'])
            self.assertEqual((self.root / 'candidate.json').read_bytes(), before)
            self.assertEqual(self.generate(), generated); self.assertEqual(self.review(), reviewed)
        self.assertEqual(len(self.f.calls), 2)
        self.assertFalse(self.snapshot()['unknownReservations'])
        self.assertEqual(len(self.snapshot()['reservations']), 2)

    def test_missing_or_partial_usage_preserves_known_result_and_blocks_next_call(self):
        with self.f.session():
            result = self.generate(usage_resolver=lambda _: {'requests': 1, 'costMicrousd': None})
            self.assertEqual(result['executionStatus'], 'succeeded')
            self.assertEqual(result['budgetStatus'], 'reconciliation_required')
            self.assertEqual(self.snapshot()['unknownReservations'], [result['reservationId']])
            with self.assertRaisesRegex(ValueError, 'generation_not_recorded'): self.review()
            self.restart()
            settled = self.generate()
            self.assertEqual(settled['artifact'], result['artifact'])
            self.assertEqual(settled['budgetStatus'], 'recorded')
        self.assertEqual(len(self.f.calls), 1)

    def test_returned_invalid_coverage_is_known_failure_not_unknown_transport(self):
        self.f.f.evidence['groups'][0]['coverage'] = {'invalid': 'shape'}
        with self.f.session():
            result = self.generate()
            self.assertEqual(result['executionStatus'], 'failed')
            self.assertEqual(result['contentStatus'], 'not_assessed')
            self.assertIsNone(result['artifact'])
            self.assertEqual(result['budgetStatus'], 'recorded')
            self.assertEqual(result['failureEvidence']['reasonCode'], 'invalid_candidate_coverage')
            self.assertEqual(result['failureEvidence']['providerOutcome'], 'returned')
            failure, data = contracts.read_snapshot(self.root / 'generator.artifact-failure.json')
            self.assertEqual(failure['rawResponse']['fileBytesSha256'],
                contracts.bytes_sha256((self.root / 'generator.raw.json').read_bytes()))
            self.assertEqual(failure['modelCallId'], contracts.read_snapshot(self.root / 'generator.call.json')[0]['modelCallId'])
            self.assertEqual(result['receiptSha256'], contracts.canonical_sha256(failure))
            self.assertNotIn('response', failure)
            self.assertFalse((self.root / 'revision.json').exists())
            self.assertFalse((self.root / 'candidate.json').exists())
            self.assertFalse(self.snapshot()['unknownReservations'])
            self.assertEqual(self.snapshot()['remaining']['global']['costMicrousd'],
                authority()['globalBounds']['costMicrousd'] - bounds()['costMicrousd'])
            self.restart()
            self.assertEqual(self.generate(), result)
            with self.assertRaises((ValueError, OSError)): self.review()
        self.assertEqual(len(self.f.calls), 1)

    def test_returned_invalid_artifact_missing_usage_stays_reserved_then_reconciles_from_cache(self):
        self.f.f.evidence['groups'][0]['coverage'] = {}
        with self.f.session():
            result = self.generate(usage_resolver=lambda _: None)
            self.assertEqual(result['executionStatus'], 'failed')
            self.assertEqual(result['failureEvidence']['providerOutcome'], 'returned')
            self.assertEqual(result['budgetStatus'], 'reconciliation_required')
            self.assertEqual(result['failureEvidence']['budgetUsageStatus'], 'missing_or_incomplete')
            self.assertTrue(self.snapshot()['unknownReservations'])
            self.restart()
            recovered = self.generate()
            self.assertEqual(recovered['failureEvidence']['receipt'], result['failureEvidence']['receipt'])
            self.assertEqual(recovered['failureEvidence']['budgetUsageStatus'], 'complete')
            self.assertEqual(recovered['budgetStatus'], 'recorded')
            self.assertFalse(self.snapshot()['unknownReservations'])
        self.assertEqual(len(self.f.calls), 1)

    def test_returned_failure_rejects_tampered_proof_without_settlement_or_redispatch(self):
        self.f.f.evidence['groups'][0]['coverage'] = {}
        with self.f.session():
            self.generate(usage_resolver=lambda _: None)
            path = self.root / 'generator.raw.json'
            value = contracts.read_snapshot(path)[0]; value['payloadSha256'] = '0'*64
            path.write_bytes(contracts.canonical_bytes(value))
            before = self.snapshot()
            self.restart()
            with self.assertRaises(ValueError): self.generate()
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(self.f.calls), 1)

    def test_guard_refusal_before_strict_observer_settles_and_replays_without_dispatch(self):
        attempts = []; executor = Mock(side_effect=AssertionError('must not dispatch'))
        caller = refused_before_observer(attempts, executor)
        resolver = Mock(side_effect=AssertionError('not measured provider usage'))
        with self.f.session():
            result = self.generate(caller=caller, usage_resolver=resolver)
            self.assertEqual(result['executionStatus'], 'failed')
            self.assertEqual(result['failureEvidence']['providerOutcome'], 'not_dispatched')
            self.assertEqual(result['failureEvidence']['reasonCode'], 'provider_request_limit')
            self.assertEqual(result['budgetStatus'], 'recorded')
            self.assertFalse(self.snapshot()['unknownReservations'])
            self.assertFalse((self.root / 'generator.call.json').exists())
            self.assertFalse((self.root / 'generator.budget-call.json').exists())
            self.assertEqual(contracts.read_snapshot(self.root / 'generator.non-dispatch.json')[0]['modelCallId'], attempts[0])
            self.assertEqual(self.snapshot()['remaining']['global'],
                {key: authority()['globalBounds'][key] - value for key, value in bounds().items()})
            self.restart()
            self.assertEqual(self.generate(caller=caller, usage_resolver=resolver), result)
        self.assertEqual(len(attempts), 1)
        executor.assert_not_called(); resolver.assert_not_called()
        rows, _ = accounting.read_events(self.f.root / 'logs')
        ended = [row for row in rows if row['event'] == 'api_attempt']
        self.assertEqual(len(ended), 1)
        self.assertIs(ended[0]['metrics']['dispatched'], False)

    def test_review_guard_refusal_is_not_a_fabricated_or_unknown_review_receipt(self):
        attempts = []; executor = Mock(side_effect=AssertionError('must not dispatch'))
        caller = refused_before_observer(attempts, executor)
        with self.f.session():
            self.generate()
            result = self.review(caller=caller)
            self.assertIsNone(result['artifact'])
            self.assertEqual(result['failureEvidence']['providerOutcome'], 'not_dispatched')
            self.assertFalse((self.root / 'review-receipt.json').exists())
            self.assertFalse(self.snapshot()['unknownReservations'])
            self.restart()
            self.assertEqual(self.review(caller=caller), result)
        self.assertEqual(len(self.f.calls), 1)
        self.assertEqual(len(attempts), 1); executor.assert_not_called()

    def test_unbound_guard_refusal_cannot_settle(self):
        def unbound(*args, **kwargs): raise pipeline.PreDispatchRejection('provider_request_limit')
        with self.f.session(), self.assertRaisesRegex(ValueError, 'non_dispatch_unproven'):
            self.generate(caller=unbound)
        self.assertTrue(self.snapshot()['unknownReservations'])
        self.assertFalse((self.root / 'generator.non-dispatch.json').exists())

    def test_logging_failed_guard_refusal_cannot_settle_or_redispatch(self):
        attempts = []; executor = Mock(side_effect=AssertionError('must not dispatch'))
        caller = refused_before_observer(attempts, executor)
        with self.f.session():
            with patch.object(pipeline, 'record_api_attempt', side_effect=accounting.AccountingWriteError('fault')):
                with self.assertRaises(pipeline.PreDispatchRejection) as raised:
                    self.generate(caller=caller)
            self.assertTrue(raised.exception.sermon_logging_failed)
            self.assertEqual(raised.exception.attempt_id, attempts[0])
            self.assertTrue(self.snapshot()['unknownReservations'])
            self.assertFalse((self.root / 'generator.non-dispatch.json').exists())
            self.assertFalse((self.root / 'generator.budget-result.json').exists())
            before = self.snapshot(); self.restart()
            with self.assertRaises(ValueError): self.generate(caller=caller)
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(attempts), 1); executor.assert_not_called()

    def test_tampered_non_dispatch_proof_is_not_adopted_or_refunded(self):
        attempts = []; executor = Mock(side_effect=AssertionError('must not dispatch'))
        caller = refused_before_observer(attempts, executor)
        with self.f.session():
            self.generate(caller=caller)
            path = self.root / 'generator.non-dispatch.json'
            value = contracts.read_snapshot(path)[0]; value['payloadSha256'] = '0'*64
            path.write_bytes(contracts.canonical_bytes(value))
            before = self.snapshot(); self.restart()
            with self.assertRaisesRegex(ValueError, 'non_dispatch_binding_changed'):
                self.generate(caller=caller)
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(attempts), 1); executor.assert_not_called()

    def test_saved_generation_response_recovers_after_finish_log_failure(self):
        with self.f.session():
            with patch.object(accounting, 'record_api_attempt', side_effect=accounting.AccountingWriteError('fault')):
                with self.assertRaises(accounting.AccountingWriteError): self.generate()
            self.assertTrue((self.root / 'generator.raw.json').exists())
            self.assertEqual(len(self.snapshot()['unknownReservations']), 1)
            self.restart()
            self.assertEqual(self.generate()['budgetStatus'], 'recorded')
        self.assertEqual(len(self.f.calls), 1)

    def test_saved_review_response_recovers_after_finish_log_failure(self):
        with self.f.session():
            self.generate()
            with patch.object(accounting, 'record_api_attempt', side_effect=accounting.AccountingWriteError('fault')):
                with self.assertRaises(accounting.AccountingWriteError): self.review()
            self.assertTrue((self.root / 'reviewer.raw.json').exists())
            self.assertFalse((self.root / 'review-receipt.json').exists())
            self.restart()
            result = self.review()
            self.assertEqual(result['executionStatus'], 'succeeded')
            self.assertEqual(result['budgetStatus'], 'recorded')
        self.assertEqual(len(self.f.calls), 2)

    def test_saved_exact_settlement_replays_after_ledger_finish_failure(self):
        original = self.store._save
        def fail(folder, ledger):
            if any(row['request']['kind'] == 'review' and row['phase'] == 'result'
                   for row in ledger['reservations'].values()): raise OSError('ledger finish fault')
            return original(folder, ledger)
        with self.f.session():
            self.generate()
            with patch.object(self.store, '_save', side_effect=fail):
                with self.assertRaises(OSError): self.review()
            self.assertTrue((self.root / 'reviewer.budget-result.json').exists())
            self.assertEqual(len(self.snapshot()['unknownReservations']), 1)
            self.restart()
            original = self.store._save
            resolver = Mock(side_effect=AssertionError('saved measured usage must be reused'))
            with patch.object(self.store, '_save', side_effect=fail):
                with self.assertRaises(OSError): self.review(usage_resolver=resolver)
            self.assertEqual(len(self.snapshot()['unknownReservations']), 1)
            self.assertEqual(self.review(usage_resolver=resolver)['budgetStatus'], 'recorded')
            resolver.assert_not_called()
        self.assertEqual(len(self.f.calls), 2)

    def test_moved_directory_recovers_but_empty_directory_cannot_reset_chain(self):
        with self.f.session():
            result = self.generate()
            moved = self.f.root / 'moved'
            shutil.copytree(self.root, moved); self.root = moved; self.restart()
            self.assertEqual(self.generate(), result)
            self.root = self.f.root / 'empty-new-output'
            with self.assertRaises(ValueError): self.generate()
        self.assertEqual(len(self.f.calls), 1)
        self.assertEqual(len(self.snapshot()['reservations']), 1)

    def test_semantic_failure_cannot_buy_second_review_or_new_candidate_identity(self):
        with self.f.session():
            self.generate(); self.f.mode = 'fail'
            result = self.review()
            self.assertEqual(result['executionStatus'], 'succeeded')
            self.assertEqual(result['contentStatus'], 'fail')
            with self.assertRaisesRegex(ValueError, 'retry_requires_execution_failure'):
                self.review(attempt_number=2)
            with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
                self.subject.generate(self.f.prepared, self.f.root / 'changed-candidate', 'new-candidate',
                    'r1', 'synthetic-key', self.f.transport, bounds=bounds(), usage_resolver=measured)
        self.assertEqual(len(self.f.calls), 2)

    def test_known_rejection_allows_only_explicit_second_review(self):
        with self.f.session():
            self.generate()
            error = urllib.error.HTTPError(pipeline.CHAT_URL, 429, 'private', {}, io.BytesIO(b'private'))
            with patch.object(pipeline.urllib.request, 'urlopen', side_effect=error) as calls:
                result = self.review(caller=self.f.http_caller)
                self.assertEqual(result['executionStatus'], 'failed')
                self.assertEqual(result['contentStatus'], 'not_assessed')
                self.assertEqual(self.review(caller=self.f.http_caller), result)
            self.assertEqual(calls.call_count, 1)
            self.assertEqual(self.review(attempt_number=2)['executionStatus'], 'succeeded')
            with self.assertRaisesRegex(ValueError, 'invalid_review_attempt_number'):
                self.review(attempt_number=3)
        self.assertEqual(self.snapshot()['revisions']['1']['reviewAttempts'], 2)

    def test_rejection_after_finish_log_failure_recovers_without_transport(self):
        with self.f.session():
            self.generate()
            error = urllib.error.HTTPError(pipeline.CHAT_URL, 400, 'private', {}, io.BytesIO(b'private'))
            with patch.object(pipeline.urllib.request, 'urlopen', side_effect=error) as calls:
                with patch.object(pipeline, 'record_api_attempt', side_effect=accounting.AccountingWriteError('fault')):
                    with self.assertRaises(pipeline.TransportRejection): self.review(caller=self.f.http_caller)
                self.restart()
                self.assertEqual(self.review(caller=self.f.http_caller)['executionStatus'], 'failed')
            self.assertEqual(calls.call_count, 1)

    def test_unknown_blocks_explicit_retry_and_same_attempt_replays_no_transport(self):
        calls = []
        def lost(key, payload, *, response_observer):
            calls.append(1)
            aid = accounting.record_api_started(payload['model'])
            response_observer.request_started(aid)
            raise TimeoutError('private error')
        with self.f.session():
            self.generate()
            result = self.review(caller=lost)
            self.assertEqual(result['executionStatus'], 'outcome_unknown')
            self.assertEqual(result['budgetStatus'], 'reconciliation_required')
            self.restart()
            self.assertEqual(self.review(caller=lost), result)
            with self.assertRaisesRegex(ValueError, 'reconciliation_required'):
                self.review(caller=lost, attempt_number=2)
        self.assertEqual(calls, [1])
        for path in self.store.root.rglob('*.json'):
            self.assertNotIn('private error', path.read_text())

    def test_intent_crash_before_mark_request_does_not_dispatch_on_restart(self):
        caller = Mock(wraps=self.f.transport)
        with self.f.session():
            with patch.object(self.store, 'mark_request', side_effect=OSError('crash before request')):
                with self.assertRaises(OSError): self.generate(caller=caller)
            self.restart()
            with self.assertRaises(ValueError): self.generate(caller=caller)
        caller.assert_not_called()
        self.assertEqual(len(self.snapshot()['unknownReservations']), 1)

    def test_changed_returned_call_identity_cannot_settle_budget(self):
        with self.f.session():
            self.generate()
            def changed(key, payload, *, response_observer):
                response = self.f.transport(key, payload, response_observer=response_observer)
                path = self.root / 'reviewer.raw.json'
                raw = json.loads(path.read_text()); raw['accounting']['modelCallId'] = 'other-call'
                path.write_text(json.dumps(raw))
                return response
            with self.assertRaisesRegex(ValueError, 'raw_binding_changed'):
                self.review(caller=changed)
        self.assertEqual(len(self.snapshot()['unknownReservations']), 1)
        self.assertEqual(len(self.f.calls), 2)

    def test_bounds_missing_and_review_attempt_two_first_never_call(self):
        with self.f.session():
            with self.assertRaises(ValueError): self.generate(bounds={})
            self.assertFalse(self.f.calls)
            self.generate()
            with self.assertRaisesRegex(ValueError, 'attempt_sequence'): self.review(attempt_number=2)
        self.assertEqual(len(self.f.calls), 1)

    def test_review_full_receipt_hash_and_missing_usage_are_separate_from_content(self):
        with self.f.session():
            self.generate()
            result = self.review(usage_resolver=None)
            self.assertEqual(result['executionStatus'], 'succeeded')
            self.assertEqual(result['contentStatus'], 'pass')
            self.assertEqual(result['budgetStatus'], 'reconciliation_required')
            self.assertEqual(result['receiptSha256'], contracts.canonical_sha256(result['artifact']))
            self.assertNotEqual(result['receiptSha256'], result['artifact']['receiptSha256'])
            self.restart()
            settled = self.review()
            row = next(row for row in self.snapshot()['reservations'] if row['kind'] == 'review')
            self.assertEqual(row['receiptSha256'], result['receiptSha256'])
            self.assertEqual(settled['budgetStatus'], 'recorded')
        self.assertEqual(len(self.f.calls), 2)

    def test_generation_rejection_is_execution_evidence_without_fabricated_candidate(self):
        error = urllib.error.HTTPError(pipeline.CHAT_URL, 401, 'private', {}, io.BytesIO(b'private'))
        with self.f.session(), patch.object(pipeline.urllib.request, 'urlopen', side_effect=error) as calls:
            result = self.generate(caller=self.f.http_caller)
            self.assertEqual(result['executionStatus'], 'failed')
            self.assertEqual(result['contentStatus'], 'not_assessed')
            self.assertIsNone(result['artifact'])
            self.assertFalse((self.root / 'revision.json').exists())
            self.restart()
            self.assertEqual(self.generate(caller=self.f.http_caller), result)
        self.assertEqual(calls.call_count, 1)

    def test_request_is_durable_before_transport_and_second_start_is_blocked(self):
        observed = []
        def caller(key, payload, *, response_observer):
            self.assertEqual(self.snapshot()['reservations'][-1]['phase'], 'request')
            aid = accounting.record_api_started(payload['model'])
            response_observer.request_started(aid)
            self.assertTrue((self.root / 'generator.budget-call.json').is_file())
            self.assertTrue((self.root / 'generator.call.json').is_file())
            observed.append('first')
            response_observer.request_started('attempt-two')
            observed.append('second')
        with self.f.session(), self.assertRaisesRegex(ValueError, 'second_transport_attempt'):
            self.generate(caller=caller)
        self.assertEqual(observed, ['first'])
        self.assertEqual(len(self.snapshot()['unknownReservations']), 1)

    def test_measured_overrun_is_recorded_and_blocks_later_work(self):
        def overrun(evidence):
            value = measured(evidence); value['costMicrousd'] = bounds()['costMicrousd'] + 1
            return value
        with self.f.session():
            self.assertEqual(self.generate(usage_resolver=overrun)['budgetStatus'], 'bound_exceeded')
            with self.assertRaisesRegex(ValueError, 'bound_exceeded'): self.review()
        self.assertTrue(self.snapshot()['boundExceeded'])
        self.assertEqual(len(self.f.calls), 1)

    def test_return_before_raw_response_persistence_remains_unknown(self):
        calls = []
        def returned_without_saved_response(key, payload, *, response_observer):
            aid = accounting.record_api_started(payload['model'])
            response_observer.request_started(aid)
            calls.append(1)
            return {'id': 'unsaved', 'model': payload['model']}
        with self.f.session():
            self.generate()
            result = self.review(caller=returned_without_saved_response)
            self.assertEqual(result['executionStatus'], 'outcome_unknown')
            self.restart()
            self.assertEqual(self.review(caller=returned_without_saved_response), result)
        self.assertEqual(calls, [1])

    def repair_context(self, parent, review, root, *, prior_revisions=(), prior_repairs=(), fingerprints=()):
        from scripts.sermon_strict_repair_planner import RepairPlanner
        result = RepairPlanner(self.store, self.f.root / 'jobs', '7'*64).plan_group(
            self.f.prepared, root,
            [dict(workUnitId=self.f.prepared['workUnitId'],layer=2,targetLocale='zh-Hans',dependsOn=[])],
            created_at='2026-09-30T00:00:00Z')
        self.assertIsNotNone(result['repair'])
        return result['repair'], result['planning']['failureFingerprint']

    def pure_repair_context(self, parent, review, root, *, prior_revisions=(), prior_repairs=(), fingerprints=()):
        snapshot = self.snapshot(); state = snapshot['stateRevision']
        unit = self.f.prepared['workUnitId']; number = parent['revisionNumber']
        plan_budget = planning.BudgetSnapshot('7'*64, state, 'candidate', unit,
            prior_revisions[0]['revisionId'] if prior_revisions else parent['revisionId'], parent['revisionId'],
            snapshot['authoritySha256'], snapshot['stateRevision'], snapshot['contentRevisions'],
            snapshot['revisions'][str(number)]['reviewAttempts'], snapshot['decisionProposals'],
            prior_failure_fingerprints=tuple(fingerprints))
        inputs = contracts.read_snapshot(root / 'review-input.json')[0]
        gate = dict(schemaVersion='sermon-review-gate-decision-v1',
            **{key: parent[key] for key in ('candidateId','revisionId','targetLocale','workUnitIds','artifactSha256','policySha256')},
            gateDecisionId='synthetic-gate', gateVersion='rqc-layer2-gate-v1', stateRevision=state,
            reviewReceiptRefs=[strict.reference('review', (root / 'review-receipt.json').read_bytes())],
            rubricSha256=contracts.canonical_sha256(self.f.prepared['rubric']), approvalReceiptRefs=[],
            admissionStatus='blocked', reasonCodes=['review_failed'], allowedNextActions=['repair_translation'],
            createdAt='2026-09-30T00:00:00Z')
        value = planning.plan_repair(candidate=parent, candidate_bytes=(root / 'candidate.json').read_bytes(),
            review=review, review_bytes=(root / 'review-receipt.json').read_bytes(), rubric=self.f.prepared['rubric'],
            input_manifest=inputs, gate=gate, state_revision=state, budget=plan_budget,
            prior_revisions=prior_revisions, prior_repairs=prior_repairs,
            graph=[dict(workUnitId=unit,layer=2,targetLocale='zh-Hans',dependsOn=[])])
        plan = value['repairPlan']; self.assertIsNotNone(plan)
        repair = dict(parentRevision=parent, parentCandidateBytes=(root / 'candidate.json').read_bytes(),
            plan=plan, triggerReview=review, inputManifest=inputs,
            priorRevisions=list(prior_revisions), priorRepairs=list(prior_repairs),
            sidecars={plan[key]['artifactId']: contracts.canonical_bytes(value[field]) for key,field in
                [('constraintsRef','constraints'),('budgetRef','budgetSnapshot'),('dependencyClosureRef','dependencyClosure')]})
        return repair, value['failureFingerprint']

    def generate_repair(self, root, repair, **options):
        return self.subject.generate(self.f.prepared, root, 'candidate', repair['plan']['toRevisionId'],
            'synthetic-key', self.f.transport, bounds=bounds(), usage_resolver=measured, repair=repair, **options)

    def test_content_revision_uses_existing_helpers_and_preserves_parent(self):
        with self.f.session():
            parent = self.generate()['artifact']; self.f.mode = 'fail'
            failed = self.review()['artifact']; before = (self.root / 'candidate.json').read_bytes()
            repair, _ = self.repair_context(parent, failed, self.root)
            child_root = self.f.root / 'repair-2'
            child = self.generate_repair(child_root, repair)
            self.assertEqual(child['artifact']['revisionNumber'], 2)
            self.assertEqual(child['artifact']['parentRevisionId'], parent['revisionId'])
            self.assertEqual((self.root / 'candidate.json').read_bytes(), before)
            self.assertEqual(self.snapshot()['contentRevisions'], 1)
            self.f.mode = 'pass'
            reviewed = self.subject.review(self.f.prepared, child_root, 'candidate', child['artifact']['revisionId'],
                'synthetic-key', self.f.transport, bounds=bounds(), usage_resolver=measured)
            self.assertEqual(reviewed['contentStatus'], 'pass')
            self.restart(); self.assertEqual(self.generate_repair(child_root, repair), child)
        self.assertEqual(len(self.f.calls), 4)

    def test_repair_raw_response_recovers_without_duplicate_or_parent_regeneration(self):
        with self.f.session():
            parent = self.generate()['artifact']; self.f.mode = 'fail'; failed = self.review()['artifact']
            repair, _ = self.repair_context(parent, failed, self.root)
            child_root = self.f.root / 'repair-2'
            with patch.object(accounting, 'record_api_attempt', side_effect=accounting.AccountingWriteError('fault')):
                with self.assertRaises(accounting.AccountingWriteError): self.generate_repair(child_root, repair)
            self.restart()
            self.assertEqual(self.generate_repair(child_root, repair)['budgetStatus'], 'recorded')
        self.assertEqual(len(self.f.calls), 3)
        self.assertEqual(self.snapshot()['contentRevisions'], 1)

    def test_two_content_revisions_are_shared_across_directories_and_stop_at_three(self):
        with self.f.session():
            parent = self.generate()['artifact']; self.f.mode = 'fail'; failed = self.review()['artifact']
            repair2, fingerprint1 = self.repair_context(parent, failed, self.root)
            self.f.f.evidence['groups'][0]['targetUtterances'][0] += ' 修订一'
            root2 = self.f.root / 'revision-2'; child2 = self.generate_repair(root2, repair2)['artifact']
            review2 = self.subject.review(self.f.prepared, root2, 'candidate', child2['revisionId'],
                'synthetic-key', self.f.transport, bounds=bounds(), usage_resolver=measured)['artifact']
            repair3, _ = self.repair_context(child2, review2, root2, prior_revisions=[parent],
                prior_repairs=[repair2['plan']], fingerprints=[fingerprint1])
            self.f.f.evidence['groups'][0]['targetUtterances'][0] += ' 修订二'
            root3 = self.f.root / 'revision-3'; child3 = self.generate_repair(root3, repair3)['artifact']
            self.assertEqual(child3['revisionNumber'], 3)
            self.assertEqual(self.snapshot()['contentRevisions'], 2)
            self.assertFalse(self.snapshot()['availability']['content_revision'])
            bogus = deepcopy(repair3); bogus['parentRevision'] = child3
            with self.assertRaises(ValueError): self.generate_repair(self.f.root / 'another-output', bogus)
            changed_issue = deepcopy(repair3); changed_issue['plan']['repairPlanId'] += '-another-issue'
            with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
                self.generate_repair(self.f.root / 'moved-third', changed_issue)
        self.assertEqual(len(self.f.calls), 5)

    def test_pure_unrecorded_plan_cannot_reserve_or_call(self):
        with self.f.session():
            parent = self.generate()['artifact']; self.f.mode = 'fail'; failed = self.review()['artifact']
            repair, _ = self.pure_repair_context(parent, failed, self.root)
            before = self.snapshot()
            with self.assertRaises((ValueError, OSError)):
                self.generate_repair(self.f.root / 'unrecorded', repair)
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(self.f.calls), 2)

    def test_replaced_saved_plan_or_fingerprint_blocks_before_transport(self):
        with self.f.session():
            parent = self.generate()['artifact']; self.f.mode = 'fail'; failed = self.review()['artifact']
            repair, _ = self.repair_context(parent, failed, self.root)
            path = self.store.root / budget.STORE_ID / 'repair-planning.json'
            original = path.read_bytes()
            for field in ('plan', 'fingerprint', 'sidecars'):
                value = json.loads(original)
                entry = next(iter(next(iter(value['chains'].values())).values()))
                if field == 'plan': entry[field]['repairPlanId'] += '-changed'
                elif field == 'fingerprint': entry[field] = '0'*64
                else: entry[field] = {}
                path.write_bytes(contracts.canonical_bytes(value))
                before = self.snapshot()
                with self.assertRaises(ValueError): self.generate_repair(self.f.root / field, repair)
                self.assertEqual(self.snapshot(), before)
            path.write_bytes(original)
            self.generate_repair(self.f.root / 'valid', repair)
        self.assertEqual(len(self.f.calls), 3)

    def test_consumed_failure_cannot_bypass_planner_with_new_pure_proposal(self):
        with self.f.session():
            parent = self.generate()['artifact']; self.f.mode = 'fail'; failed = self.review()['artifact']
            repair2, _ = self.repair_context(parent, failed, self.root)
            root2 = self.f.root / 'revision-2'; child = self.generate_repair(root2, repair2)['artifact']
            review = self.subject.review(self.f.prepared, root2, 'candidate', child['revisionId'],
                'synthetic', self.f.transport, bounds=bounds(), usage_resolver=measured)['artifact']
            forged, fingerprint = self.pure_repair_context(child, review, root2,
                prior_revisions=[parent], prior_repairs=[repair2['plan']])
            # Even a stale/imported proposal in durable history must not override
            # the current consumed-failure ledger at the reservation boundary.
            path = self.store.root / budget.STORE_ID / 'repair-planning.json'
            history = contracts.read_snapshot(path)[0]
            entries = next(iter(history['chains'].values()))
            entries[forged['plan']['repairPlanId']] = dict(plan=forged['plan'], fingerprint=fingerprint,
                sidecars={k:contracts.decode_json(v) for k,v in forged['sidecars'].items()})
            path.write_bytes(contracts.canonical_bytes(history))
            before = self.snapshot()
            with self.assertRaisesRegex(ValueError, 'repeated_failure_without_new_evidence'):
                self.generate_repair(self.f.root / 'forbidden-third', forged)
            self.assertEqual(self.snapshot(), before)
            self.restart()
            self.assertEqual(self.generate_repair(root2, repair2)['artifact'], child)
        self.assertEqual(len(self.f.calls), 4)

    def test_plan_guard_rechecks_with_budget_lock_after_preflight_snapshot(self):
        with self.f.session():
            parent = self.generate()['artifact']; self.f.mode = 'fail'; failed = self.review()['artifact']
            repair, _ = self.repair_context(parent, failed, self.root)
            original = self.store.reserve
            def replace_before_reserve(*args, **kwargs):
                path = self.store.root / budget.STORE_ID / 'repair-planning.json'
                history = contracts.read_snapshot(path)[0]; history['chains'] = {}
                path.write_bytes(contracts.canonical_bytes(history))
                return original(*args, **kwargs)
            with patch.object(self.store, 'reserve', side_effect=replace_before_reserve):
                with self.assertRaisesRegex(ValueError, 'not_durably_planned'):
                    self.generate_repair(self.f.root / 'changed-before-lock', repair)
        self.assertEqual(len(self.f.calls), 2)

    def test_gate_operation_binding_is_read_only_and_matches_ledger_request(self):
        with self.f.session():
            self.generate(); self.review()
        before = {str(path): path.read_bytes() for path in self.f.root.rglob('*') if path.is_file()}
        view = adapter.operation_binding('review', self.f.prepared, self.root, 'candidate', 'r1')
        after = {str(path): path.read_bytes() for path in self.f.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        row = next(row for row in self.snapshot()['reservations'] if row['kind'] == 'review')
        self.assertEqual(view['inputSha256'], row['inputSha256'])
        self.assertEqual(view['operationId'], row['operationId'])
        self.assertNotIn(str(self.root), json.dumps(view))

    def test_actual_process_exit_preserves_reservation_and_forbids_restart_dispatch(self):
        code = '''import json,os,sys
from pathlib import Path
from scripts import sermon_strict_layer2 as strict,sermon_accounting as accounting,sermon_log_profile as profile
from scripts.sermon_review_budget import BudgetStore
from scripts.sermon_strict_budget_adapter import StrictBudgetAdapter
from tests.test_sermon_strict_budget_adapter import authority,bounds
value=json.load(sys.stdin)
prepared=strict.prepare(*[text.encode() for text in value['args']],value['group'],rule_preflight=value['rulePreflight'])
def lost(key,payload,*,response_observer):
    aid=accounting.record_api_started(payload['model'])
    response_observer.request_started(aid)
    os._exit(73)
with profile.session(Path(sys.argv[1])/'child-logs','child-budget',work_kind='production',evidence_mode='synthetic'):
    StrictBudgetAdapter(BudgetStore(sys.argv[2],authority())).generate(prepared,Path(sys.argv[1])/'revision','candidate','r1','synthetic',lost,bounds=bounds())
'''
        completed = subprocess.run([sys.executable, '-c', code, str(self.f.root), str(self.store.root)],
            input=json.dumps({'args': [value.decode() for value in self.f.args], 'group': self.f.group,
                              'rulePreflight': self.f.rule_preflight}),
            text=True, capture_output=True)
        self.assertEqual(completed.returncode, 73, completed.stderr)
        caller = Mock(wraps=self.f.transport)
        with self.f.session(), self.assertRaises(ValueError): self.generate(caller=caller)
        caller.assert_not_called()
        self.assertEqual(len(self.snapshot()['unknownReservations']), 1)

if __name__ == '__main__': unittest.main()
