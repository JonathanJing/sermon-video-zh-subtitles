"""Synthetic local D5 developer checks; no provider, Gate or acceptance runs."""
from copy import deepcopy
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_review_budget as budget
from scripts import sermon_workflow_jobs as jobs


def identity(unit='group-1', locale='zh-Hans'):
    return dict(zip(budget.IDENTITY_FIELDS, ['a'*64, 'b'*64, 'c'*64, 'd'*64, 'e'*64,
                                            locale, f'l2.{locale}.{unit}']))


def amounts(requests=1):
    return {'requests': requests, 'inputTokens': 20*requests, 'outputTokens': 10*requests,
            'wallTimeMs': 100*requests, 'costMicrousd': 50*requests}


def authority(requests=20):
    return {'approvalSha256': 'f'*64, 'globalBounds': amounts(requests),
            'unitBounds': amounts(requests), 'limits': deepcopy(budget.DEFAULT_LIMITS)}


def request(op='op-1', kind='review', revision=1):
    return {'operation_id': op, 'kind': kind, 'revision_id': f'r{revision}',
            'revision_number': revision, 'input_sha256': '1'*64, 'bounds': amounts()}


def result(status='succeeded', content='pass'):
    return {'executionStatus': status, 'contentStatus': content if status == 'succeeded' else 'not_assessed',
            'receiptSha256': '2'*64, 'usage': None if status == 'outcome_unknown' else amounts()}


def concurrent_reserve(root, ready, go, output, n):
    store = budget.BudgetStore(root, authority(1))
    ready.put(True); go.wait(5)
    try:
        value = store.reserve(identity(str(n)), **request())
        output.put(value['created'])
    except ValueError as exc:
        output.put(str(exc))


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'shared' / 'budgets'
        self.store = budget.BudgetStore(self.root, authority())

    def run_local(self, op='op-1', kind='review', revision=1, outcome=None):
        return self.store.execute_local(identity(), callback=lambda _: outcome or result(),
                                        **request(op, kind, revision))

    def test_snapshot_closed_identity_and_safe_output(self):
        view = self.store.snapshot(identity())
        self.assertEqual(view['availability'], {'initial_generation': True, 'review': True, 'content_revision': False, 'decision_proposal': True})
        self.assertEqual(view['executionAuthority'], 'none')
        self.assertNotIn(str(self.root), json.dumps(view))
        self.run_local()
        view = self.store.snapshot(identity())
        self.assertEqual(view['revisions']['1']['reviewAttempts'], 1)
        self.assertFalse(view['availability']['review'])
        with self.assertRaisesRegex(ValueError, 'chain_identity'):
            self.store.snapshot(dict(identity(), issueId='another'))

    def test_moving_output_and_changing_issue_cannot_reset_counters(self):
        # Output/issue are caller metadata, deliberately absent from store/API identity.
        for output, issue in [('output-a', 'issue-a'), ('moved-output', 'issue-b')]:
            Path(self.temp.name, output).mkdir()
            store = budget.BudgetStore(self.root, authority())
            if issue == 'issue-a': self.run_local()
            else:
                with self.assertRaisesRegex(ValueError, 'retry_requires_execution_failure'):
                    store.reserve(identity(), **request(issue))
        with self.assertRaisesRegex(ValueError, 'chain_identity'):
            self.store.reserve(dict(identity(), outputDirectory='moved'), **request('new'))

    def test_all_bounds_and_types_are_required(self):
        bad = [None, {}, {'requests': 1}, dict(amounts(), inputTokens=True),
               dict(amounts(), costMicrousd=0), dict(amounts(), wallTimeMs=float('inf')),
               dict(amounts(), outputTokens=-1), dict(amounts(), requests=2)]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.reserve(identity(), **dict(request(), bounds=value))
        for update in [{'targetLocale': []}, {'sourceIdentitySha256': 'a'*64+'\n'},
                       {'workUnitId': '../../escape'}, {'workUnitId': 'l2.ko.a'}, {'rubricSha256': True}]:
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.store.reserve(dict(identity(), **update), **request())
        for value in [None, {}, dict(authority(), globalBounds={}),
                      dict(authority(), limits=dict(budget.DEFAULT_LIMITS, reviewAttemptsPerRevision=3))]:
            with self.assertRaises(ValueError): budget.BudgetStore(self.root, value)

    def test_authority_is_pinned_and_limits_may_only_be_lower_at_creation(self):
        self.store.snapshot(identity())
        for change in [dict(authority(), approvalSha256='3'*64), authority(30),
                       dict(authority(), limits=dict(budget.DEFAULT_LIMITS, decisionProposals=0))]:
            with self.assertRaisesRegex(ValueError, 'authority_changed'):
                budget.BudgetStore(self.root, change).snapshot(identity())
        root = Path(self.temp.name) / 'lower'
        store = budget.BudgetStore(root, dict(authority(), limits=dict(budget.DEFAULT_LIMITS, decisionProposals=0)))
        with self.assertRaisesRegex(ValueError, 'decision_proposal_limit'):
            store.reserve(identity(), **request('d', 'decision_proposal'))

    def test_review_second_attempt_only_known_execution_failure_and_never_third(self):
        self.run_local(outcome=result('failed'))
        self.assertTrue(self.store.snapshot(identity())['availability']['review'])
        self.run_local('op-2', outcome=result('failed'))
        with self.assertRaisesRegex(ValueError, 'review_attempt_limit'):
            self.store.reserve(identity(), **request('op-3'))
        for status, content in [('succeeded', 'fail'), ('succeeded', 'uncertain'), ('cancelled', 'not_assessed')]:
            store = budget.BudgetStore(Path(self.temp.name) / (status+content), authority())
            store.execute_local(identity(), callback=lambda _: result(status, content), **request())
            with self.assertRaisesRegex(ValueError, 'retry_requires_execution_failure'):
                store.reserve(identity(), **request('new'))

    def test_content_revisions_and_one_decision_span_whole_chain(self):
        self.run_local('decision', 'decision_proposal')
        for n in range(1, 4):
            self.run_local('review'+str(n), revision=n, outcome=result(content='fail'))
            if n < 3: self.run_local('repair'+str(n), 'content_revision', n+1)
        view = self.store.snapshot(identity())
        self.assertEqual(view['contentRevisions'], 2)
        self.assertEqual(view['decisionProposals'], 1)
        self.assertFalse(view['availability']['content_revision'])
        with self.assertRaisesRegex(ValueError, 'decision_proposal_limit'):
            self.store.reserve(identity(), **request('new-issue', 'decision_proposal', 3))
        with self.assertRaisesRegex(ValueError, 'revision_identity_changed'):
            self.store.reserve(identity(), **dict(request('same-number', revision=3), revision_id='r-new'))
        with self.assertRaisesRegex(ValueError, 'revision_not_current'):
            self.store.reserve(identity(), **request('stale', revision=1))

    def test_initial_generation_is_budgeted_once_without_consuming_repair_revision(self):
        self.run_local('generate', 'initial_generation')
        view = self.store.snapshot(identity())
        self.assertEqual(view['contentRevisions'], 0)
        self.assertEqual(view['remaining']['unit'], amounts(19))
        self.assertFalse(view['availability']['initial_generation'])
        self.run_local('review')
        with self.assertRaisesRegex(ValueError, 'initial_generation_already_started'):
            self.store.reserve(identity(), **request('generate-again', 'initial_generation'))

    def test_global_and_unit_bounds_and_locale_independence(self):
        config = authority(2); config['unitBounds'] = amounts(1)
        self.store = budget.BudgetStore(self.root, config)
        self.run_local(outcome=result('failed'))
        with self.assertRaisesRegex(ValueError, 'budget_exhausted'):
            self.store.reserve(identity(), **request('retry'))
        self.store.execute_local(identity(locale='ko'), callback=lambda _: result(), **request())
        with self.assertRaisesRegex(ValueError, 'budget_exhausted'):
            self.store.reserve(identity(locale='es'), **request())

    def test_exact_idempotency_conflicts_do_not_launch(self):
        calls = []
        callback = lambda _: calls.append(1) or result()
        first = self.store.execute_local(identity(), callback=callback, **request())
        second = self.store.execute_local(identity(), callback=callback, **request())
        self.assertEqual(calls, [1]); self.assertEqual(first['reservationId'], second['reservationId'])
        self.assertFalse(second['created']); self.assertFalse(second['executionAllowed'])
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.store.reserve(identity(), **dict(request(), input_sha256='4'*64))
        with self.assertRaisesRegex(ValueError, 'conflicting_budget_result'):
            self.store.record_result(first['reservationId'], result('failed'))

    def test_unknown_retains_all_budget_and_requires_explicit_evidence(self):
        reservation = self.run_local(outcome=result('outcome_unknown'))
        rid = reservation['reservationId']
        view = self.store.snapshot(identity())
        self.assertEqual(view['remaining']['unit'], amounts(19))
        self.assertEqual(view['unknownReservations'], [rid])
        self.assertFalse(any(view['availability'].values()))
        self.assertEqual(self.store.reconcile(rid)['status'], 'outcome_unknown')
        with self.assertRaisesRegex(ValueError, 'reconciliation_required'):
            self.store.reserve(identity(), **request('retry'))
        with self.assertRaisesRegex(ValueError, 'conflicting_budget_result'):
            self.store.record_result(rid, result('failed'))
        with self.assertRaises(ValueError): self.store.reconcile(rid, result=result('failed'))
        self.store.reconcile(rid, result=result('failed'), evidence_sha256='2'*64)
        self.assertTrue(self.store.snapshot(identity())['availability']['review'])
        # Reconciliation does not refund request/cost bounds, even with zero tokens.
        self.assertEqual(self.store.snapshot(identity())['remaining']['unit'], amounts(19))

    def test_crash_intent_before_request_cannot_resume_or_refund(self):
        reserved = self.store.reserve(identity(), **request())
        restarted = budget.BudgetStore(self.root, authority())
        with self.assertRaisesRegex(ValueError, 'fresh_reservation'):
            restarted.mark_request(reserved['reservationId'])
        callback = unittest.mock.Mock(return_value=result())
        restarted.execute_local(identity(), callback=callback, **request())
        callback.assert_not_called()
        self.assertEqual(restarted.reconcile(reserved['reservationId'])['phase'], 'intent')

    def test_crash_return_before_saved_marker_keeps_unknown(self):
        callback = unittest.mock.Mock(return_value=result())
        original = jobs._persist
        def persist(path, value):
            if path.name.endswith('.result.json'): raise OSError('injected')
            return original(path, value)
        with patch.object(jobs, '_persist', side_effect=persist), self.assertRaises(OSError):
            self.store.execute_local(identity(), callback=callback, **request())
        callback.assert_called_once()
        restarted = budget.BudgetStore(self.root, authority())
        self.assertEqual(len(restarted.snapshot(identity())['unknownReservations']), 1)
        restarted.execute_local(identity(), callback=callback, **request())
        callback.assert_called_once()

    def test_crash_saved_marker_before_settlement_reconciles_without_callback(self):
        callback = unittest.mock.Mock(return_value=result())
        original = self.store._save
        def save(folder, ledger):
            if any('result' in row for row in ledger['reservations'].values()): raise OSError('injected')
            return original(folder, ledger)
        with patch.object(self.store, '_save', side_effect=save), self.assertRaises(OSError):
            self.store.execute_local(identity(), callback=callback, **request())
        restarted = budget.BudgetStore(self.root, authority())
        rid = restarted.snapshot(identity())['unknownReservations'][0]
        self.assertEqual(restarted.reconcile(rid)['status'], 'succeeded')
        restarted.execute_local(identity(), callback=callback, **request())
        callback.assert_called_once()
        self.assertFalse(restarted.snapshot(identity())['unknownReservations'])

    def test_crash_settlement_before_gate_commit_does_not_repeat_execution(self):
        value = self.run_local()
        restarted = budget.BudgetStore(self.root, authority())
        self.assertEqual(restarted.reconcile(value['reservationId'])['status'], 'succeeded')
        callback = unittest.mock.Mock(return_value=result())
        restarted.execute_local(identity(), callback=callback, **request())
        callback.assert_not_called()
        self.assertEqual(restarted.snapshot(identity())['executionAuthority'], 'none')

    def test_actual_process_restart_never_reruns_unknown_request(self):
        code = '''import json, os, sys
from scripts.sermon_review_budget import BudgetStore
from tests.test_sermon_review_budget import authority, identity, request
s=BudgetStore(sys.argv[1], authority())
s.execute_local(identity(), callback=lambda _: os._exit(73), **request())
'''
        completed = subprocess.run([sys.executable, '-c', code, str(self.root)], capture_output=True)
        self.assertEqual(completed.returncode, 73, completed.stderr)
        callback = unittest.mock.Mock(return_value=result())
        self.store.execute_local(identity(), callback=callback, **request())
        callback.assert_not_called()
        self.assertEqual(len(self.store.snapshot(identity())['unknownReservations']), 1)

    def test_concurrent_process_reservations_cannot_overspend_global_budget(self):
        # Start from a fresh root to also exercise concurrent lock-directory creation.
        ctx = multiprocessing.get_context('spawn')
        ready, output, go = ctx.Queue(), ctx.Queue(), ctx.Event()
        processes = [ctx.Process(target=concurrent_reserve, args=(str(self.root), ready, go, output, n)) for n in range(4)]
        for process in processes: process.start()
        for _ in processes: ready.get(timeout=15)
        go.set()
        outcomes = [output.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(15); self.assertEqual(process.exitcode, 0)
        self.assertEqual(outcomes.count(True), 1, outcomes)
        self.assertTrue(all(x is True or x in ('budget_store_busy', 'budget_exhausted') for x in outcomes))

    def test_fsync_order_and_failures_precede_callback(self):
        events = []
        persist, sync = jobs._persist, jobs._sync_directory_ancestry
        def save(path, value):
            persist(path, value)
            if path.name == 'state.json': events.append('persist-' + next(iter(value['reservations'].values()), {}).get('phase', 'init'))
        def ancestry(path): sync(path); events.append('ancestry')
        def callback(_): events.append('callback'); return result()
        with patch.object(jobs, '_persist', side_effect=save), patch.object(jobs, '_sync_directory_ancestry', side_effect=ancestry):
            self.store.execute_local(identity(), callback=callback, **request())
        self.assertLess(events.index('persist-intent'), events.index('persist-request'))
        at = events.index('callback')
        self.assertEqual(events[at-1], 'ancestry')
        self.assertLess(events.index('persist-request'), at)
        for fail_on in (1, 2, 3):
            root = Path(self.temp.name) / f'fail-{fail_on}'
            store = budget.BudgetStore(root, authority()); count = 0
            def failing(path):
                nonlocal count
                count += 1
                if count == fail_on: raise OSError('fsync failed')
                sync(path)
            callback = unittest.mock.Mock(return_value=result())
            with patch.object(jobs, '_sync_directory_ancestry', side_effect=failing), self.assertRaises(OSError):
                store.execute_local(identity(), callback=callback, **request())
            callback.assert_not_called()

    def test_dispatch_permission_is_consumed_once_and_not_recovered_from_disk(self):
        value = self.store.reserve(identity(), **request())
        self.store.mark_request(value['reservationId'])
        with self.assertRaisesRegex(ValueError, 'fresh_reservation'):
            self.store.mark_request(value['reservationId'])
        with self.assertRaisesRegex(ValueError, 'fresh_reservation'):
            budget.BudgetStore(self.root, authority()).mark_request(value['reservationId'])

    def test_file_fsync_failure_and_intent_rename_failure_never_dispatch(self):
        callback = unittest.mock.Mock(return_value=result())
        with patch.object(jobs.os, 'fsync', side_effect=OSError('injected')), self.assertRaises(OSError):
            self.store.execute_local(identity(), callback=callback, **request())
        callback.assert_not_called()
        # A missing ledger after directory creation remains blocked after restart.
        with self.assertRaises(FileNotFoundError):
            budget.BudgetStore(self.root, authority()).execute_local(identity(), callback=callback, **request())
        root = Path(self.temp.name) / 'rename-failure'
        store = budget.BudgetStore(root, authority())
        store.snapshot(identity())
        with patch.object(jobs.os, 'replace', side_effect=OSError('injected')), self.assertRaises(OSError):
            store.execute_local(identity(), callback=callback, **request())
        callback.assert_not_called()

    def test_all_resource_dimensions_enforce_global_caps(self):
        for dimension in budget.METRICS:
            config = authority(10)
            config['globalBounds'][dimension] = amounts()[dimension]
            store = budget.BudgetStore(Path(self.temp.name) / dimension, config)
            store.execute_local(identity(), callback=lambda _: result(), **request())
            with self.subTest(dimension=dimension), self.assertRaisesRegex(ValueError, 'budget_exhausted'):
                store.reserve(identity('other'), **request())

    def test_callback_exception_never_stores_private_error_body_or_retries(self):
        def callback(_): raise RuntimeError('private-provider-error-body')
        with self.assertRaises(RuntimeError):
            self.store.execute_local(identity(), callback=callback, **request())
        for path in self.root.rglob('*.json'):
            self.assertNotIn('private-provider-error-body', path.read_text())
        self.assertFalse(any(self.store.snapshot(identity())['availability'].values()))

    def test_failed_initial_and_failed_repair_do_not_enable_review(self):
        self.run_local('generate', 'initial_generation', outcome=result('failed'))
        with self.assertRaisesRegex(ValueError, 'initial_generation_not_completed'):
            self.store.reserve(identity(), **request('review'))
        self.store = budget.BudgetStore(Path(self.temp.name) / 'repair-failed', authority())
        self.run_local(outcome=result(content='fail'))
        self.run_local('repair', 'content_revision', 2, result('failed'))
        with self.assertRaisesRegex(ValueError, 'revision_not_completed'):
            self.store.reserve(identity(), **request('review2', revision=2))

    def test_planner_snapshot_fixture_matches_developer_scenario(self):
        self.run_local(outcome=result('failed'))
        actual = self.store.snapshot(identity())
        fixture = json.loads((Path(__file__).parent / 'fixtures/rqc-budget/known-execution-failure.snapshot.json').read_text())
        # Store location and the ledger hash binding it vary with temporary root.
        for value in (actual, fixture):
            value.pop('storeSha256'); value.pop('stateRevision')
        self.assertEqual(actual, fixture)

    def test_missing_corrupt_or_symlink_ledger_fails_closed(self):
        self.store.snapshot(identity())
        path = self.root / budget.STORE_ID / 'state.json'
        before = path.read_bytes()
        for raw in [b'{}', b'{"a":1,"a":2}', b'not json']:
            path.write_bytes(raw)
            with self.assertRaises(ValueError): self.store.reserve(identity(), **request())
        path.unlink()
        with self.assertRaises(FileNotFoundError): self.store.reserve(identity(), **request())
        outside = Path(self.temp.name) / 'outside.json'; outside.write_bytes(before)
        path.symlink_to(outside)
        with self.assertRaises((OSError, ValueError)): self.store.reserve(identity(), **request())
        self.assertEqual(outside.read_bytes(), before)

    def test_unknown_invalid_usage_no_sensitive_payloads_and_overrun_stop(self):
        for update in [{'usage': None}, {'errorBody': 'secret'}, {'usage': {}},
                       {'usage': dict(amounts(), costMicrousd=False)}]:
            with self.assertRaises(ValueError): budget._result(dict(result(), **update))
        oversized = result(); oversized['usage']['costMicrousd'] += 1
        self.run_local(outcome=oversized)
        self.assertTrue(self.store.snapshot(identity())['boundExceeded'])
        with self.assertRaisesRegex(ValueError, 'bound_exceeded'):
            self.store.reserve(identity('another'), **request())


if __name__ == '__main__': unittest.main()
