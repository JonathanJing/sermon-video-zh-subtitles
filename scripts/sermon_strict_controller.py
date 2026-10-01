"""Explicit deterministic strict L2 group runner; no production default switch.

run_group composes the real immutable generator/reviewer, shared durable budget,
and current-file repair planner. A trusted caller supplies prepared inputs, one
pinned store/job root, approved bounds, and a single-attempt transport. Existing
jobs locks serialize this group; this module creates no worker/job system. Only
known, planner-authorized review recovery or one-group content repair can call
again. Logging failures propagate; unknown outcomes never trigger a new call.

The return selects one immutable revision directory for the caller's whole-locale
bridge. machine_review_passed is not plugin/public/human admission. Multi-group
repair closures, human/source review and ambiguous scope remain explicit stops.
No credentials are read and no default provider, CLI, publication or L3 is wired.
"""
from __future__ import annotations

from pathlib import Path

from scripts import sermon_accounting as accounting
from scripts import sermon_log_profile as profile
from scripts import sermon_repair_planning as planning
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_budget_adapter as adapter
from scripts import sermon_strict_layer2 as strict
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_strict_repair_planner import RepairPlanner
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-strict-group-controller-v1'


def _timestamp(value):
    # Use the downstream Gate contract before any transport. Python's ISO
    # parser also accepts offsets/precision the frozen D1 contract rejects.
    validator = c.validator('sermon-review-gate-decision-v1')
    c.require(validator.evolve(schema=validator.schema['$defs']['utc']).is_valid(value),
              'invalid_controller_created_at')
    return value


def run_group(prepared, *, root, store, job_root, production_run_id, graph,
              candidate_id, api_key, caller, bounds, usage_resolver=None,
              initial_revision_id='initial', created_at=None, depends_on=None,
              completion_spans=None):
    """Run/resume one group, returning a selected revision and explicit stop.

    root is a pinned group directory; outputs live in revisions/<revisionId>.
    Reinvocation verifies current cached outputs. Never delete/rename a revision
    to retry: BudgetStore retains the same chain and reservations across roots.
    AccountingWriteError (including after a response) propagates without retry.
    Missing provider usage may yield reconciliation_required with valid content.
    The caller must retain all whole-locale plugin/human/downstream gates.
    """
    c.require(profile.current() is not None, 'strict_requires_accounting_profile')
    c.require(type(store) is budget.BudgetStore, 'trusted_budget_store_required')
    c.require(callable(caller) and (usage_resolver is None or callable(usage_resolver)),
              'invalid_controller_transport')
    strict.label(candidate_id); strict.label(initial_revision_id); budget._hash(production_run_id)
    dependencies = accounting._labels(depends_on)
    c.require(completion_spans is None or type(completion_spans) is list, 'invalid_controller_span_sink')
    budget._amounts(bounds, positive=True)
    c.require(bounds['requests'] == 1, 'reservation_requires_one_request')
    if 'diagnosticContext' in prepared:
        from scripts.sermon_diagnostic_context import validate_runtime
        validate_runtime(prepared['diagnosticContext'], run_id=production_run_id, store_sha256=store.store_sha256)
    identity = adapter.chain_identity(prepared)
    closure = planning.dependency_closure(graph, [prepared['workUnitId']])
    c.require(prepared['workUnitId'] in closure['regenerateWorkUnitIds'], 'controller_requires_layer2_group')
    root, job_root = _safe_path(Path(root)), _safe_path(Path(job_root))
    binding = {'schemaVersion': SCHEMA, 'productionRunId': production_run_id,
        'root': str(root), 'jobRoot': str(job_root), 'storeSha256': store.store_sha256,
        'authoritySha256': store.authority_sha256, 'identity': identity,
        'materialBytesSha256': {key: c.bytes_sha256(raw) for key, raw in prepared['bytes'].items()},
        'graphSha256': closure['graphSha256'], 'candidateId': candidate_id,
        'initialRevisionId': initial_revision_id, 'bounds': dict(bounds),
        **({'requestLimits': prepared['requestLimits']} if 'requestLimits' in prepared else {}),
        **({'diagnosticContext': prepared['diagnosticContext']} if 'diagnosticContext' in prepared else {})}
    # Identity excludes output/revision/issue names, so a second local caller
    # cannot run the same chain concurrently by choosing another output folder.
    lock_id = jobs._digest({'scope': SCHEMA, 'store': store.store_sha256, 'chain': identity})
    with jobs._lock(job_root, lock_id) as (_, _, held):
        c.require(held, 'strict_group_controller_busy')
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = root / 'controller-input.json'
        if path.exists():
            saved, _ = c.read_snapshot(path)
            stamp = _timestamp(saved.get('planningCreatedAt'))
            c.require(created_at is None or stamp == _timestamp(created_at), 'controller_created_at_changed')
        else:
            stamp = _timestamp(created_at or strict.utc())
        strict.save_once(path, dict(binding, planningCreatedAt=stamp))
        jobs._sync_directory_ancestry(root)
        runner = _Runner(prepared, root, store, job_root, production_run_id, graph,
                         candidate_id, api_key, caller, bounds, usage_resolver, stamp,
                         dependencies, initial_revision_id)
        result = runner.run()
        # Business verdict and executable stage completion are separate facts.
        accounting.record_log('rqc_group_controller', fields={
            'status': result['status'], 'reasonCode': result['reasonCode'],
            'workUnitId': prepared['workUnitId'], 'revisionId': result['revisionId']})
        if completion_spans is not None:
            completion_spans.extend(runner.completed)
        return result


class _Runner:
    def __init__(self, prepared, root, store, job_root, run_id, graph, candidate_id,
                 api_key, caller, bounds, usage_resolver, stamp, dependencies, initial):
        self.prepared, self.root, self.store = prepared, root, store
        self.subject, self.planner = adapter.StrictBudgetAdapter(store), RepairPlanner(store, job_root, run_id)
        self.graph, self.candidate_id, self.api_key, self.caller = graph, candidate_id, api_key, caller
        self.bounds, self.usage_resolver, self.stamp = bounds, usage_resolver, stamp
        self.dependencies, self.completed = dependencies, []
        self.identity = adapter.chain_identity(prepared)
        self.revision_id, self.number, self.attempt = initial, 1, 0
        self.current = root / 'revisions' / initial
        self.candidate, self.receipt, self.budget_status = None, None, 'not_observed'

    def result(self, status, reason, *, planning_result=None, error_type=None, failure_evidence=None):
        return {'schemaVersion': SCHEMA, 'status': status, 'reasonCode': reason,
            'root': str(self.current), 'revisionId': self.revision_id, 'revisionNumber': self.number,
            'reviewAttempt': self.attempt, 'candidateRevision': self.candidate,
            'reviewReceipt': self.receipt, 'budgetStatus': self.budget_status,
            'planning': planning_result, 'errorType': error_type,
            'completedSpans': list(self.completed), 'executionAuthority': 'none',
            'remainingGates': ['whole_locale_language_plugin_and_public_candidate',
                               'independent_human_translation_review', 'same_locale_layer3_and_release'],
            **({'failureEvidence': failure_evidence} if failure_evidence is not None else {})}

    def invoke(self, method, *args, **kwargs):
        finished = []
        result = method(*args, depends_on=self.dependencies, completion_spans=finished, **kwargs)
        if finished:
            self.completed.extend(finished)
            # Actual serial execution links to the preceding operation's leaves.
            self.dependencies = finished[-1:]
        return result

    def _options(self):
        return dict(bounds=self.bounds, usage_resolver=self.usage_resolver)

    def run(self):
        try:
            return self.drive()
        except accounting.AccountingWriteError:
            raise
        except (ValueError, OSError) as exc:
            if getattr(exc, 'sermon_logging_failed', False):
                raise
            # Never infer non-execution from an exception or recreate a missing
            # revision. A failed read/write/validation is an explicit stop.
            view = self.store.snapshot(self.identity)
            unknown = bool(view['unknownReservations'])
            if unknown:
                self.budget_status = 'reconciliation_required'
            return self.result('reconciliation_required' if unknown else 'blocked',
                adapter.safe_failure_reason(exc, 'current_evidence_or_execution_unknown'
                    if unknown else 'current_evidence_not_validated'),
                error_type=type(exc).__name__)

    def drive(self):
        view = self.store.snapshot(self.identity)
        if view['revisions']:
            self.number = max(map(int, view['revisions']))
            self.revision_id = view['revisions'][str(self.number)]['revisionId']
            strict.label(self.revision_id)
            self.current = self.root / 'revisions' / self.revision_id
        repair = strict.load_repair(self.current) if self.number > 1 else None
        c.require(self.number == 1 or repair is not None, 'controller_repair_evidence_missing')
        # These hard local bounds supplement, never replace, persistent budgets.
        for _ in range(3):
            self.candidate, self.receipt, self.attempt = None, None, 0
            generated = self.invoke(self.subject.generate, self.prepared, self.current,
                self.candidate_id, self.revision_id, self.api_key, self.caller,
                repair=repair, **self._options())
            self.candidate, self.budget_status = generated['artifact'], generated['budgetStatus']
            failure = generated.get('failureEvidence')
            if failure is not None:
                return self.result('blocked' if self.budget_status == 'recorded' else 'reconciliation_required',
                    failure['reasonCode'], failure_evidence=failure)
            if generated['executionStatus'] != 'succeeded' and hasattr(self.caller,'configuration_stop'):
                stop=self.caller.configuration_stop(self.prepared,'translator')
                if stop is not None:
                    return self.result('blocked' if self.budget_status=='recorded' else 'reconciliation_required',
                        'provider_configuration_blocked',failure_evidence={
                            'providerOutcome':'rejected','diagnostic':stop['diagnostic'],
                            'scopeSha256':stop['scopeSha256'],'stopReceiptSha256':c.canonical_sha256(stop)})
            if self.budget_status != 'recorded':
                return self.result('reconciliation_required', 'generation_budget_' + self.budget_status)
            if generated['executionStatus'] != 'succeeded':
                return self.result('blocked', 'generation_execution_failed')
            view = self.store.snapshot(self.identity)
            self.attempt = max(1, view['revisions'][str(self.number)]['reviewAttempts'])
            for _ in range(2):
                reviewed = self.invoke(self.subject.review, self.prepared, self.current,
                    self.candidate_id, self.revision_id, self.api_key, self.caller,
                    attempt_number=self.attempt, **self._options())
                self.receipt, self.budget_status = reviewed['artifact'], reviewed['budgetStatus']
                failure = reviewed.get('failureEvidence')
                if failure is not None:
                    return self.result('blocked' if self.budget_status == 'recorded' else 'reconciliation_required',
                        failure['reasonCode'], failure_evidence=failure)
                if hasattr(self.caller,'configuration_stop') and reviewed['executionStatus'] != 'succeeded':
                    stop=self.caller.configuration_stop(self.prepared,'reviewer')
                    if stop is not None:
                        return self.result('blocked' if self.budget_status=='recorded' else 'reconciliation_required',
                            'provider_configuration_blocked',failure_evidence={
                                'providerOutcome':'rejected','diagnostic':stop['diagnostic'],
                                'scopeSha256':stop['scopeSha256'],'stopReceiptSha256':c.canonical_sha256(stop)})
                if self.budget_status != 'recorded' or reviewed['executionStatus'] == 'outcome_unknown':
                    return self.result('reconciliation_required', 'review_budget_' + self.budget_status)
                if reviewed['executionStatus'] == 'succeeded' and self.receipt['reviewVerdict'] == 'pass':
                    return self.result('machine_review_passed', 'strict_review_passed')
                planned = self.invoke(self.planner.plan_group, self.prepared, self.current,
                                      self.graph, created_at=self.stamp)
                decision = planned['planning']
                if decision['status'] != 'proposal':
                    status = ('reconciliation_required' if decision['status'] == 'reconciliation_required'
                              else 'blocked')
                    return self.result(status, decision['reasonCode'], planning_result=decision)
                if decision['action'] == 'retry_review':
                    self.attempt += 1
                    continue
                if decision['action'] == 'repair_translation':
                    if decision['dependencyGroupsRequiringOwnPlans']:
                        return self.result('blocked', 'dependency_group_repair_required', planning_result=decision)
                    repair = planned['repair']
                    c.require(repair is not None, 'controller_missing_durable_repair')
                    self.revision_id = decision['toRevisionId']; strict.label(self.revision_id)
                    self.number += 1
                    self.current = self.root / 'revisions' / self.revision_id
                    break
                return self.result('blocked', decision['reasonCode'], planning_result=decision)
            else:
                return self.result('blocked', 'review_execution_limit_reached')
        return self.result('blocked', 'content_revision_limit_reached')
