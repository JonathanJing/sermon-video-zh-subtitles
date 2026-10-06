"""Real local Prefect control plane, existing-source continuation, synthetic TTS.

The trusted diagnostic session still owns source/text validation and its original
budget/deadline. This opt-in graph uses actual durable jobs and returned WAVs;
there is no Fresh-source, native-model, formal-audio or publication adapter.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from scripts import sermon_accounting as accounting
from scripts import sermon_completion as completion
from scripts import sermon_dag_evidence as evidence
from scripts import sermon_diagnostic_prefect_flow as diagnostic
from scripts import sermon_durable_accounting as durable
from scripts import sermon_log_profile as profile
from scripts import sermon_mock_tts_contract as contract
from scripts import sermon_mock_tts_control as control
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_candidate_bridge as bridge
from scripts import run_bounded_diagnostic_continuation as continuation
from scripts.sermon_diagnostic_dag_session import DiagnosticSession
from scripts.sermon_execution_harness import work_lock
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-mock-tts-dag-v1'
INPUT = 'sermon-mock-tts-unit-input-v1'
PERMISSIONS = {'realProviderCalls': False, 'nativeModelCalls': False, 'sourceRerun': False,
    'mockWorkerDispatch': True, 'automaticWorkerRetry': False, 'humanApproval': False,
    'formalAudio': False, 'productionWrites': False, 'publication': False}
QUALIFICATIONS = {'evidenceMode': 'synthetic', 'humanAcceptance': 'pending',
    'listeningAcceptance': 'not_performed', 'formalAudioEligible': False,
    'productionEligible': False, 'publicationAuthorized': False}


def _save(path, value):
    # Same durable immutable writer as the client; never follow redirected roots.
    return control._save(path, value)


def _groups(session, diagnostic_config):
    result = {}
    for locale, lane in sorted(diagnostic_config['locales'].items()):
        _, groups = continuation.preflight_locale_inputs(session.subject, session.context, lane['localeSpec'])
        for group in groups:
            unit = locale + '.' + group['translationGroupId']
            c.require(contract.label(unit) and len(unit) <= 80 and unit not in result,
                'mock_dag_unit_identity_invalid')
            result[unit] = {'unitId': unit, 'targetLocale': locale,
                'translationGroupId': group['translationGroupId'],
                'sourceUnitIds': group['sourceUnitIds'], 'groupPlanSha256': c.canonical_sha256(group)}
    c.require(1 <= len(result) <= contract.MAX_TESTED_UNITS and all(sum(row['targetLocale'] == locale
        for row in result.values()) <= contract.MAX_TESTED_UNITS for locale in diagnostic_config['locales']), 'mock_dag_unit_limit')
    return result


def _graph(units, *, source_node='source.existing'):
    nodes = [{'id': source_node, 'operation': 'source', 'locale': None, 'unitId': None, 'dependsOn': []}]
    locales = sorted({row['targetLocale'] for row in units.values()})
    for locale in locales:
        nodes.append({'id': 'text.'+locale, 'operation': 'text', 'locale': locale,
            'unitId': None, 'dependsOn': [source_node]})
        for unit, row in units.items():
            if row['targetLocale'] != locale:
                continue
            prior = 'text.'+locale
            for operation in ('input', 'submit', 'observe', 'verify', 'gate'):
                name = 'mock.'+operation+'.'+unit
                nodes.append({'id': name, 'operation': operation, 'locale': locale,
                    'unitId': unit, 'dependsOn': [prior]})
                prior = name
        nodes.append({'id': 'join.'+locale, 'operation': 'join', 'locale': locale, 'unitId': None,
            'dependsOn': ['mock.gate.'+unit for unit, row in units.items() if row['targetLocale'] == locale]})
    nodes.append({'id': 'final.readonly', 'operation': 'final', 'locale': None, 'unitId': None,
        'dependsOn': ['join.'+locale for locale in locales]})
    return nodes


def _code_files():
    identity = accounting.execution_identity()
    paths = set(identity['loadedProjectCodeSha256'])
    paths.update('scripts/'+name for name in ('sermon_mock_tts_dag.py', 'sermon_mock_tts_control.py',
        'sermon_mock_tts_contract.py', 'sermon_mock_tts_worker.py', 'sermon_durable_accounting.py',
        'sermon_completion.py', 'sermon_diagnostic_dag_session.py', 'sermon_diagnostic_prefect_flow.py'))
    return {name: diagnostic._hash_file(diagnostic.pilot.REPO/name) for name in sorted(paths)}


def policy_and_faults(units, config):
    """Shared closed mock policy preflight, before any Source/text callback."""
    policy = control.validate_policy(config['mockPolicy'])
    c.require(policy['units'] == {unit: row['targetLocale'] for unit, row in units.items()},
        'mock_dag_policy_membership_changed')
    c.require(type(config['faults']) is dict and set(config['faults']) <= set(units),
        'mock_dag_fault_membership_changed')
    faults = {unit: deepcopy(config['faults'].get(unit,
        {'mode': 'none', 'queueDelaySeconds': 0, 'runDelaySeconds': 0})) for unit in units}
    for fault in faults.values():
        c.require(type(fault) is dict and set(fault) == {'mode', 'queueDelaySeconds', 'runDelaySeconds'}
            and fault['mode'] in contract.FAULTS
            and contract.number(fault['queueDelaySeconds'], 0, 5)
            and contract.number(fault['runDelaySeconds'], 0, 5)
            and fault['queueDelaySeconds']+fault['runDelaySeconds'] < policy['workerTimeoutSeconds'],
            'mock_dag_fault_invalid')
    return policy, faults


class MockTTSDAG:
    """Frozen closed graph; Prefect schedules, original ledgers decide business state."""
    def __init__(self, session, config, *, recovery=None):
        c.require(type(session) is DiagnosticSession and session.offline_fixture
            and session.evidence_mode == 'synthetic', 'mock_dag_offline_continuation_required')
        c.require(type(config) is dict and set(config) == {'schemaVersion', 'diagnostic', 'mockPolicy', 'faults'}
            and config['schemaVersion'] == SCHEMA and c._strict_json(config), 'mock_dag_config_invalid')
        self.session = session
        self.diagnostic = diagnostic.DiagnosticDAG(session, config['diagnostic'])
        self.units = _groups(session, self.diagnostic.config)
        self.policy, self.faults = policy_and_faults(self.units, config)
        self.nodes = _graph(self.units)
        self.binding = {'schemaVersion': SCHEMA, 'scope': 'existing_source_continuation_group_mock_tts',
            'diagnosticBinding': deepcopy(self.diagnostic.binding), 'units': deepcopy(self.units),
            'nodes': deepcopy(self.nodes), 'permissions': deepcopy(PERMISSIONS),
            'graphLimits': {'maxUnits': contract.MAX_TESTED_UNITS,
                'maxLocaleUnits': contract.MAX_TESTED_UNITS, 'maxDependencies': 64,
                'scaleQualification': 'two_unit_offline_acceptance_only'},
            'mockPolicy': deepcopy(self.policy), 'faults': deepcopy(self.faults),
            'codeFiles': _code_files(), 'mockImplementationSha256': contract.implementation_sha256(),
            'engine': {'name': 'prefect', 'version': version('prefect'), 'maxWorkers': 1,
                'retries': 0, 'cache': False, 'persistResult': False},
            'recovery': {'automaticRetry': False, 'explicitRetry': 'same_input_confirmed_worker_failed_only',
                'selection': 'unitId_to_exact_prior_request_sha256',
                'retryFaultChange': 'mode_only_to_none', 'bounds': 'frozen_mock_policy',
                'normalResume': 'latest_submitted_original_attempt_receipt_revalidation'},
            'batchSemantics': 'one_mock_job_per_frozen_translation_group', **QUALIFICATIONS}
        self.plan_sha256 = c.canonical_sha256(self.binding)
        self.root = _safe_path(session.root/'mock-tts-dag'/self.plan_sha256, recursive=True)
        self.invocation = uuid.uuid4().hex
        self.recovery = deepcopy({} if recovery is None else recovery)
        c.require(type(self.recovery) is dict and set(self.recovery) <= set(self.units)
            and all(contract.sha(value) for value in self.recovery.values()), 'mock_dag_recovery_selection_invalid')
        self.invocation_binding = {'schemaVersion': 'sermon-mock-tts-invocation-v1',
            'invocationId': self.invocation, 'planSha256': self.plan_sha256,
            'recoveryRequests': deepcopy(self.recovery), **QUALIFICATIONS}
        self.prior_synthetic_dispatches = len(session.transport.observations)
        self.results, self.observations, self.task_ids = {}, {}, {}
        self.stream, self.client = None, None
        self._reliability_failure = None

    def _check(self):
        self.diagnostic._check()
        c.require(self.recovery == self.invocation_binding['recoveryRequests']
            and self.invocation_binding['planSha256'] == self.plan_sha256
            and self.invocation_binding['invocationId'] == self.invocation, 'mock_dag_invocation_changed')
        c.require(c.canonical_sha256(self.binding) == self.plan_sha256
            and self.nodes == self.binding['nodes'] == _graph(self.units)
            and self.units == self.binding['units'] == _groups(self.session, self.diagnostic.config)
            and self.policy == self.binding['mockPolicy']
            and self.faults == self.binding['faults']
            and self.binding['permissions'] == PERMISSIONS
            and self.binding['mockImplementationSha256'] == contract.implementation_sha256(),
            'mock_dag_frozen_plan_changed')
        c.require(all(diagnostic._hash_file(diagnostic.pilot.REPO/name) == digest
            for name, digest in self.binding['codeFiles'].items()), 'mock_dag_code_identity_changed')
        c.require(self.root == _safe_path(self.session.root/'mock-tts-dag'/self.plan_sha256, recursive=True),
            'mock_dag_scope_changed')
        _safe_path(self.root.parent/'.harness-locks', recursive=True)
        if (self.root/'plan.json').exists():
            c.require(public.read_snapshot(self.root/'plan.json')[0] == self.binding, 'mock_dag_saved_plan_changed')
        invocation_path = self.root/'invocations'/(self.invocation+'.json')
        if invocation_path.exists():
            c.require(public.read_snapshot(invocation_path)[0] == self.invocation_binding, 'mock_dag_saved_invocation_changed')

    def freeze(self):
        self._check()
        _save(self.root/'plan.json', self.binding)
        _save(self.root/'invocations'/(self.invocation+'.json'), self.invocation_binding)
        self.stream = durable.open_stream(self.root/'accounting', scope_id='mock-tts-dag',
            plan_sha256=self.plan_sha256, production_run_id=self._production_run_id(),
            purpose='mock_tts_dag_continuation', create=True)

    def activate(self):
        """Call only inside this stream's synthetic context (also used by component tests)."""
        self._check()
        self.client = control.MockTTSClient(self.root/'mock-control', self.stream, self.policy, create=True)
        # Reject unknown/unconfirmed recovery before scheduling any callbacks.
        for unit, prior_sha in self.recovery.items():
            self._retry_parent(unit, prior_sha)

    def _production_run_id(self):
        return self.session.context['runId']

    def _control_leaf(self, node, result, dependencies):
        digest = c.canonical_sha256(result)
        revision = c.canonical_sha256([self.plan_sha256, node['id'], digest])
        job = c.canonical_sha256(['mock_dag_control', self.plan_sha256, node['id']])
        # This leaf measures receipt persistence and terminal binding only.
        # Earlier callbacks/validation/dispatch are timed by their own spans
        # and the containing invocation; this leaf is never a model call.
        with profile.context(jobId=job, revisionId=revision):
            with accounting.stage_outcome('mock_dag.'+node['operation'],
                    work_unit_id=node['id'], attempt_id='control.'+uuid.uuid4().hex,
                    depends_on=list(dict.fromkeys(dependencies))) as attempt:
                _save(self.root/'results'/node['id']/(digest+'.json'), result)
                accounting.record_workload('mock_dag.control_receipt_commit', {'resultSha256': digest,
                    'measurementScope': 'receipt_persistence_and_terminal_binding_only',
                    'syntheticFixtureOnly': True, 'productionEligible': False})
                attempt.finish('completed', artifact_sha256=digest)
            return completion.capture_synthetic(attempt.span_id,
                production_run_id=self._production_run_id(), artifact_sha256=digest,
                artifact_kind='control_receipt', job_id=job, revision_id=revision)

    def _parents(self, node, upstream):
        c.require(type(upstream) is list and len(upstream) == len(node['dependsOn']), 'mock_dag_dependency_membership_changed')
        parents = []
        for key, passed in zip(node['dependsOn'], upstream):
            c.require(key in self.observations and passed == self.observations[key], 'mock_dag_dependency_result_changed')
            parents.append(self.observations[key])
        _, events = completion.current_events()
        checks = [{'handle': handle} for parent in parents if parent['readyForDownstream']
            for handle in parent['completionHandles']]
        if checks:
            completion.validate_synthetic_many(checks, events, production_run_id=self._production_run_id())
        return parents

    def _locale_spec(self, locale):
        return self.diagnostic.config['locales'][locale]['localeSpec']

    def _validate_callback(self, operation, locale, result):
        return self.diagnostic._validate(operation, locale, result)

    def _final_result(self, expected):
        return {'schemaVersion': 'sermon-mock-tts-final-v1', 'status': 'synthetic_complete',
            'planSha256': self.plan_sha256, 'expectedLocales': expected,
            'localeJoinSha256': {locale: c.canonical_sha256(self.results['join.'+locale]) for locale in expected},
            'formalAudioPackageCreated': False, 'realProviderCalls': 0,
            'realModelCalls': 0, 'newSourceCalls': 0, **QUALIFICATIONS}

    def _candidate(self, locale):
        result = self.results['text.'+locale]['callbackResult']
        self._validate_callback('locale', locale, result)
        candidate = public.read_snapshot(Path(result['output'])/'candidate.json')[0]
        spec = self._locale_spec(locale)
        raw, _ = continuation.preflight_locale_inputs(self.session.subject, self.session.context, spec)
        revisions = [(self.session._path(row['root']), row['reviewAttempt']) for row in result['revisions']]
        # Re-run the strict receipt, plugin and public-candidate validators from
        # original artifacts; dictionary shape alone never admits target text.
        checked = bridge.compile_candidate(*raw, revisions, plugin_path=Path(spec['pluginPath']),
            expected_plugin_sha256=spec['pluginSha256'], diagnostic_context=self.session.context)
        c.require(checked['candidate'] == candidate, 'mock_dag_candidate_revalidation_changed')
        expected = [row for row in self.units.values() if row['targetLocale'] == locale]
        actual = candidate['groups']
        c.require([row['translationGroupId'] for row in actual] == [row['translationGroupId'] for row in expected]
            and all(group['sourceUnitIds'] == member['sourceUnitIds'] for group, member in zip(actual, expected)),
            'mock_dag_candidate_membership_changed')
        return candidate

    def _submitted_requests(self, unit):
        rows = []
        for path in (self.client.root/'requests').glob('*/mock-tts-request/request.json'):
            request = contract.read_request(path)
            if request['unitId'] != unit or not self.client._intent_path(request).exists():
                continue
            request, path = self.client._request(path)
            rows.append((request, path))
        c.require(len({row['attemptNumber'] for row, _ in rows}) == len(rows), 'mock_dag_attempt_conflict')
        return sorted(rows, key=lambda item: item[0]['attemptNumber'])

    def _retry_parent(self, unit, prior_sha):
        selected = [(row, path) for row, path in self._submitted_requests(unit)
            if c.canonical_sha256(row) == prior_sha]
        c.require(len(selected) == 1, 'mock_dag_recovery_parent_missing')
        previous, path = selected[0]
        c.require(previous['attemptNumber'] < self.policy['maxAttemptsPerUnit'], 'mock_dag_recovery_attempt_limit')
        probe = {**previous, 'attemptNumber': previous['attemptNumber']+1, 'retryOfRequestSha256': prior_sha}
        self.client._require_retry(probe)  # Original observed/receipt-proven failure only.
        return previous

    def _selection(self, unit):
        existing = self._submitted_requests(unit['unitId'])
        for request, _ in existing:
            c.require(all(request[key] == value for key, value in unit.items()), 'mock_dag_recovery_input_changed')
            if request['attemptNumber'] > 1:
                self.client._require_retry(request)
        if unit['unitId'] in self.recovery:
            previous = self._retry_parent(unit['unitId'], self.recovery[unit['unitId']])
            attempt, retry_of = previous['attemptNumber']+1, c.canonical_sha256(previous)
            c.require(not existing or existing[-1][0]['attemptNumber'] <= attempt,
                'mock_dag_recovery_selection_stale')
            fault = {**self.faults[unit['unitId']], 'mode': 'none'}
        elif existing:
            selected = existing[-1][0]
            attempt, retry_of, fault = selected['attemptNumber'], selected['retryOfRequestSha256'], selected['fault']
        else:
            attempt, retry_of, fault = 1, None, self.faults[unit['unitId']]
        expected_fault = self.faults[unit['unitId']] if attempt == 1 else {**self.faults[unit['unitId']], 'mode': 'none'}
        c.require(fault == expected_fault, 'mock_dag_retry_fault_changed')
        return attempt, retry_of, fault

    def _derive_input(self, node, *, candidate=None):
        candidate = self._candidate(node['locale']) if candidate is None else candidate
        member = self.units[node['unitId']]
        group = next(g for g in candidate['groups'] if g['translationGroupId'] == member['translationGroupId'])
        spec = self._locale_spec(node['locale'])
        binding = {'schemaVersion': INPUT, 'unitId': member['unitId'], 'targetLocale': member['targetLocale'],
            'sourceUnitIds': member['sourceUnitIds'], 'groupPlanSha256': member['groupPlanSha256'],
            'sourceCanonicalSha256': candidate['englishSourcePackageJsonSha256'],
            'anchorCanonicalSha256': candidate['anchorManifestSha256'], 'policySha256': candidate['translationPolicySha256'],
            'rubricSha256': c.canonical_sha256(public.read_snapshot(Path(spec['rubric']))[0]),
            'pluginSha256': spec['pluginSha256'],
            'utteranceSha256': c.canonical_sha256({'targetText': group['targetText'],
                'targetUtterances': group['targetUtterances'], 'coverage': group['coverage']}),
            'reviewedGroupSha256': c.canonical_sha256({'semanticReview': group['semanticReview'],
                'languageReview': group['languageReview']})}
        digest = c.canonical_sha256(binding)
        unit = {'unitId': node['unitId'], 'targetLocale': node['locale'],
            'inputSha256': digest, 'revisionId': c.canonical_sha256(['mock_group_revision', binding])}
        return unit, binding

    def _input(self, node, parents):
        unit, binding = self._derive_input(node)
        handles = [handle for parent in parents for handle in parent['completionHandles']]
        attempt, retry_of, fault = self._selection(unit)
        request, path = self.client.prepare_request(unit, handles, input_binding=binding,
            fault=fault, attempt_number=attempt, retry_of=retry_of)
        return {'requestPath': str(path), 'requestSha256': c.canonical_sha256(request),
            'inputBinding': binding, 'unit': unit, 'jobId': request['jobId'],
            'workerAttemptId': request['attemptId'], 'attemptNumber': request['attemptNumber'],
            'revisionId': request['revisionId']}, [request['parentCompletion']]

    def _request(self, unit):
        item = self.results['mock.input.'+unit]
        request, path = self.client._request(item['requestPath'])
        c.require(c.canonical_sha256(request) == item['requestSha256']
            and request['inputSha256'] == c.canonical_sha256(item['inputBinding']), 'mock_dag_request_changed')
        return request, path

    def _join(self, node, parents):
        expected = [unit for unit, row in self.units.items() if row['targetLocale'] == node['locale']]
        c.require([parent['nodeId'] for parent in parents] == ['mock.gate.'+unit for unit in expected],
            'mock_dag_join_membership_changed')
        gates = {}
        for unit in expected:
            request, path = self._request(unit)
            saved = self.results['mock.gate.'+unit]
            current = self.client.gate(path, self.client.verify_for_admission(path))
            c.require(saved == current and current['gate']['unitId'] == unit
                and current['gate']['revisionId'] == request['revisionId'], 'mock_dag_join_gate_changed')
            gates[unit] = {'gateSha256': c.canonical_sha256(saved), 'jobId': request['jobId'],
                'revisionId': request['revisionId'], 'inputSha256': request['inputSha256']}
        return {'schemaVersion': 'sermon-mock-tts-locale-join-v1', 'targetLocale': node['locale'],
            'expectedUnitIds': expected, 'admittedUnits': gates, 'status': 'synthetic_complete', **QUALIFICATIONS}

    def observed_edges(self):
        """Verify every ready executable edge against actual typed control leaves."""
        _, events = completion.current_events()
        edges, checks = [], []
        for node in self.nodes:
            row = self.observations[node['id']]
            if not row['readyForDownstream']:
                c.require(not row['completionHandles'], 'mock_dag_blocked_completion_forbidden')
                continue
            c.require(len(row['completionHandles']) == 1, 'mock_dag_control_leaf_required')
            handle = row['completionHandles'][0]
            checks.append({'handle': handle, 'stage': 'mock_dag.'+node['operation'],
                'artifact_sha256': c.canonical_sha256(self.results[node['id']])})
            for parent_id in node['dependsOn']:
                parent = self.observations[parent_id]
                c.require(parent['readyForDownstream'], 'mock_dag_upstream_not_completed')
                parent_span = parent['completionHandles'][0]['spanId']
                c.require(parent_span in handle['dependsOn'], 'mock_dag_observed_edge_missing')
                edges.append({'fromNode': parent_id, 'toNode': node['id'],
                    'fromSpanId': parent_span, 'toSpanId': handle['spanId']})
        if checks:
            completion.validate_synthetic_many(checks, events, production_run_id=self._production_run_id())
        return edges

    def _before_operation(self, node, parents):
        """Trusted extension point for a stricter enclosing frozen graph."""

    def execute(self, node_id, upstream):
        """A single node body. Only run() supplies the actual scheduler evidence."""
        node = next((row for row in self.nodes if row['id'] == node_id), None)
        c.require(node is not None, 'mock_dag_node_not_authorized')
        observed = {'nodeId': node_id, 'operation': node['operation'], 'unitId': node['unitId'],
            'executionStatus': 'blocked', 'readyForDownstream': False, 'completionHandles': [],
            'processed': False, **QUALIFICATIONS}
        dispatched = False
        with diagnostic._LOCK:
            if self._reliability_failure is not None:
                raise self._reliability_failure
            try:
                self._check()
                parents = self._parents(node, upstream)
                if any(not p['readyForDownstream'] for p in parents):
                    observed['reason'] = 'upstream_not_completed'
                else:
                    self._before_operation(node, parents)
                    handles = [h for p in parents for h in p['completionHandles']]
                    spans = [h['spanId'] for h in handles]
                    op, unit = node['operation'], node['unitId']
                    ready, status = True, 'completed'
                    if op in {'source', 'text'}:
                        with accounting.stage('mock_dag.callback.'+op, depends_on=spans,
                                work_unit_id=node_id+'.callback', executor_type='deterministic_program') as callback_span:
                            dispatched = op == 'text'
                            value = (self.session.inspect_source() if op == 'source' else
                                self.session.run_locale(node['locale'], self._locale_spec(node['locale']), depends_on=spans))
                            ready, reason, _ = self._validate_callback('source' if op == 'source' else 'locale', node['locale'], value)
                        result = {'callbackResult': value, 'businessStatus': reason, **QUALIFICATIONS}
                        self.results[node_id] = result
                        if ready:
                            if op == 'text': self._candidate(node['locale'])
                            leaves = evidence.current_terminal_leaves(callback_span)
                            handles = [self._control_leaf(node, result, list(dict.fromkeys(spans+leaves)))]
                        else:
                            status = 'outcome_unknown' if any(g.get('status') == 'reconciliation_required'
                                for g in value.get('groups', [])) else 'failed'
                            handles = []
                    elif op == 'input':
                        result, original_handles = self._input(node, parents)
                        handles = [self._control_leaf(node, result, spans+[h['spanId'] for h in original_handles])]
                    elif op == 'submit':
                        _, path = self._request(unit)
                        result = self.client.submit(path)
                        dispatched = result['launchEntered']
                        # Submission is acknowledgement/intent only, not worker completion.
                        dispatch_handle = result.get('dispatchCompletion')
                        supplemental = [dispatch_handle['spanId']] if dispatch_handle is not None else []
                        handles = [self._control_leaf(node, result, spans+supplemental)]
                    elif op == 'observe':
                        request, path = self._request(unit)
                        prior_observation = (self.client._observation_path(request).exists()
                            or self.client._recovery_observation_path(request).exists())
                        original = self.client.observe(path)
                        # A fresh timeout remains unknown for this invocation. A
                        # later normal invocation reconciles only the original job.
                        reconciled = (self.client.reconcile(path) if prior_observation
                            and original['status'] == 'outcome_unknown' else None)
                        state = reconciled['status'] if reconciled else original['status']
                        result = {'observation': original, 'reconciliation': reconciled}
                        ready = state == 'succeeded'
                        status = 'completed' if ready else 'failed' if state == 'failed' else 'outcome_unknown'
                        handles = [self._control_leaf(node, result, spans+[original['observerSpanId']])] if ready else []
                    elif op == 'verify':
                        _, path = self._request(unit)
                        result = self.client.verify_for_admission(path)
                        handles = [self._control_leaf(node, result, spans+[result['completion']['spanId']])]
                    elif op == 'gate':
                        _, path = self._request(unit)
                        result = self.client.gate(path, self.results['mock.verify.'+unit])
                        handles = [self._control_leaf(node, result, spans+[result['completion']['spanId']])]
                    elif op == 'join':
                        result = self._join(node, parents)
                        handles = [self._control_leaf(node, result, spans)]
                    else:
                        expected = sorted({row['targetLocale'] for row in self.units.values()})
                        c.require([p['nodeId'] for p in parents] == ['join.'+locale for locale in expected],
                            'mock_dag_final_membership_changed')
                        for locale in expected:
                            join_node = next(row for row in self.nodes if row['id'] == 'join.'+locale)
                            checked = self._join(join_node, [self.observations[key] for key in join_node['dependsOn']])
                            c.require(checked == self.results['join.'+locale], 'mock_dag_final_join_changed')
                        result = self._final_result(expected)
                        handles = [self._control_leaf(node, result, spans)]
                    self.results[node_id] = result
                    digest = c.canonical_sha256(result)
                    _save(self.root/'results'/node_id/(digest+'.json'), result)
                    if unit is not None:
                        input_result = self.results.get('mock.input.'+unit, {})
                        observed.update({key: input_result[key] for key in ('jobId', 'workerAttemptId',
                            'attemptNumber', 'revisionId', 'requestSha256') if key in input_result})
                    observed.update(executionStatus=status, readyForDownstream=ready,
                        processed=None if status == 'outcome_unknown' else True,
                        resultSha256=digest, completionHandles=handles)
            except Exception as exc:
                if isinstance(exc, accounting.AccountingWriteError) or getattr(exc, 'sermon_logging_failed', False):
                    self._reliability_failure = exc
                    raise
                if isinstance(exc, control.SubmissionError):
                    dispatched = exc.launch_entered
                reason = str(exc) if isinstance(exc, ValueError) and re.fullmatch(r'[a-z][a-z0-9_]{0,119}', str(exc)) else 'evidence_not_confirmed'
                observed.update(executionStatus='outcome_unknown' if dispatched else 'blocked',
                    processed=None if dispatched else False, reason=reason, errorType=type(exc).__name__)
            self.observations[node_id] = observed
            _save(self.root/'observations'/self.invocation/node_id, observed)
            return observed


def _engine_inputs(task_run):
    return {key: sorted(str(ref.id) for ref in refs if ref.input_type == 'task_run')
        for key, refs in task_run.task_inputs.items()}


def _utc(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z') if value is not None else None


def _engine_timing(task_run, states):
    """Persist engine timestamps as reported; never infer worker/provider queues."""
    return {'provenance': 'prefect_persisted_task_run_and_state_history', 'timezone': 'UTC',
        'expectedStartTime': _utc(task_run.expected_start_time),
        'nextScheduledStartTime': _utc(task_run.next_scheduled_start_time),
        'startTime': _utc(task_run.start_time), 'endTime': _utc(task_run.end_time),
        'stateHistory': [{'name': state.name, 'type': state.type.value,
            'timestamp': _utc(state.timestamp), 'scheduledTime': _utc(state.state_details.scheduled_time)}
            for state in states],
        'missingReasons': {'nextScheduledStartTime': 'not_present_in_terminal_task' if
            task_run.next_scheduled_start_time is None else None}}


def timing_coverage():
    return {'criticalPathStatus': 'partial', 'criticalPathSeconds': None,
        'etaSeconds': None, 'resourceQueueSeconds': None, 'providerQueueSeconds': None,
        'controlLeafTimingScope': 'receipt_persistence_and_terminal_binding_only',
        'invocationTimingScope': 'workflow_includes_source_text_callbacks_submit_and_validation',
        'missingReasons': {'criticalPathSeconds': 'cross_process_clock_and_resource_edges_not_complete',
            'etaSeconds': 'synthetic_control_run_not_a_production_estimator',
            'resourceQueueSeconds': 'not_observed', 'providerQueueSeconds': 'not_applicable_no_real_provider'}}


def run(session, config, *, recovery=None):
    """One clean SDK process and one real flow; durable receipts survive invocations."""
    dag = MockTTSDAG(session, config, recovery=recovery)
    with work_lock(dag.root):
        dag.freeze()
        home, database = diagnostic.pilot.isolated_prefect_environment(dag.root)
        os.chdir(tempfile.mkdtemp(prefix='.prefect-config-', dir=dag.root))
        from prefect import flow, task
        from prefect.cache_policies import NO_CACHE
        from prefect.client.orchestration import get_client
        from prefect.context import get_run_context
        from prefect.settings import get_current_settings
        from prefect.task_runners import ThreadPoolTaskRunner
        settings = get_current_settings()
        c.require(settings.api.url is None and settings.api.key is None and settings.home == home
            and settings.server.database.connection_url.get_secret_value() == database
            and settings.results.local_storage_path == home/'storage'
            and settings.server.memo_store_path == home/'memo_store.toml'
            and not settings.server.analytics_enabled and not settings.cloud.enable_orchestration_telemetry,
            'mock_dag_prefect_not_isolated')

        @task(retries=0, cache_policy=NO_CACHE, persist_result=False)
        def dispatch(node_id, upstream):
            ctx = get_run_context()
            node = next(n for n in dag.nodes if n['id'] == node_id)
            engine = {'flowRunId': str(ctx.task_run.flow_run_id), 'taskRunId': str(ctx.task_run.id),
                'taskInputs': _engine_inputs(ctx.task_run)}
            expected = sorted(dag.task_ids[key] for key in node['dependsOn'])
            c.require(engine['taskInputs'].get('upstream', []) == expected, 'mock_dag_engine_dependency_changed')
            dag.task_ids[node_id] = engine['taskRunId']
            _save(dag.root/'engine'/dag.invocation/(node_id+'.json'), engine)
            return dag.execute(node_id, upstream)

        @flow(name='sermon-existing-source-mock-tts', retries=0, persist_result=False,
            task_runner=ThreadPoolTaskRunner(max_workers=1))
        def orchestrate():
            futures = {}
            for node in dag.nodes:
                futures[node['id']] = dispatch.with_options(name=node['id']).submit(
                    node['id'], [futures[key] for key in node['dependsOn']])
            return {key: future.result() for key, future in futures.items()}

        with dag.stream.context(), accounting.accounting_session(dag.root/'accounting', 'mock_tts_dag_invocation',
                {'planSha256': dag.plan_sha256, 'invocationId': dag.invocation}) as invocation_accounting:
            dag.activate()
            results = orchestrate()
            # Read persisted engine records, rather than accepting local wrapper IDs.
            persisted = {}
            with get_client(sync_client=True) as client:
                for node in dag.nodes:
                    task_run = client.read_task_run(uuid.UUID(dag.task_ids[node['id']]))
                    record = public.read_snapshot(dag.root/'engine'/dag.invocation/(node['id']+'.json'))[0]
                    c.require(_engine_inputs(task_run) == record['taskInputs']
                        and str(task_run.flow_run_id) == record['flowRunId']
                        and str(task_run.id) == record['taskRunId']
                        and task_run.state.is_completed() and task_run.run_count == 1
                        and task_run.empirical_policy.retries == 0, 'mock_dag_persisted_engine_evidence_changed')
                    states = client.read_task_run_states(task_run.id)
                    persisted[node['id']] = {**record, 'engineState': task_run.state.name,
                        'timestamps': _engine_timing(task_run, states)}
            final = {'schemaVersion': SCHEMA, 'planSha256': dag.plan_sha256, 'invocationId': dag.invocation,
                'status': 'synthetic_complete' if results['final.readonly']['readyForDownstream'] else 'incomplete',
                'nodes': results, 'engineEvidence': persisted, 'engine': dag.binding['engine'],
                'observedEdges': dag.observed_edges(), 'engineGraphVerified': True,
                'syntheticProviderDispatches': len(session.transport.observations)-dag.prior_synthetic_dispatches,
                'realProviderCalls': 0, 'realModelCalls': 0, 'newSourceCalls': 0,
                'newMockDispatches': sum(dag.results.get(n['id'], {}).get('newDispatch') is True
                    for n in dag.nodes if n['operation'] == 'submit'),
                'unknownDispatchAcknowledgements': sum(dag.results.get(n['id'], {}).get('newDispatch', False) is None
                    for n in dag.nodes if n['operation'] == 'submit'),
                'finalProjection': dag.results.get('final.readonly'),
                'invocationAccounting': {'workflowId': invocation_accounting['workflowId'],
                    'timingSource': 'canonical_workflow_started_and_finished',
                    'scope': 'flow_invocation_after_plan_freeze_including_callbacks_and_control'},
                'timingCoverage': timing_coverage(), **QUALIFICATIONS}
        _save(dag.root/'runs'/(dag.invocation+'.json'), final)
        return final


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--continuation', type=Path, required=True)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--fixture-responses', type=Path, required=True)
    parser.add_argument('--offline-fixture', action='store_true', required=True)
    parser.add_argument('--recovery-manifest', type=Path)
    parser.add_argument('--request-limits', type=Path, help='Initial request limits; resumes reuse the frozen snapshot')
    args = parser.parse_args(argv)
    read = lambda path: public.read_snapshot(diagnostic._path(str(path)))[0]
    session = DiagnosticSession(read(args.plan), read(args.continuation),
        offline_transport=diagnostic.fixture_transport(args.fixture_responses),
        request_limits=read(args.request_limits) if args.request_limits else None)
    print(json.dumps(run(session, read(args.spec),
        recovery=read(args.recovery_manifest) if args.recovery_manifest else None), sort_keys=True))


if __name__ == '__main__':
    main()
