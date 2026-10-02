"""Durable local mock-TTS client: original intents, observations and admission.

Controller observations and physical worker attempts are distinct. Unknown is
never permission to resubmit. Reconciliation reads original evidence only.
"""
from copy import deepcopy
import json
import re
from pathlib import Path
import subprocess
import sys
import time

from scripts import sermon_accounting as accounting
from scripts import sermon_completion as completion
from scripts import sermon_durable_accounting as durable
from scripts import sermon_log_profile as profile
from scripts import sermon_log_contract as log_contract
from scripts import sermon_mock_tts_contract as contract
from scripts import sermon_mock_tts_worker as worker
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_release_workflow import _safe_path

POLICY = 'sermon-mock-tts-control-policy-v1'
INTENT = 'sermon-mock-tts-intent-v1'
OBSERVATION = 'sermon-mock-tts-observation-v1'
ADMISSION = 'sermon-mock-tts-admission-v1'


class SubmissionError(c.ContractError):
    """A safe failure code plus whether this call entered its fixed launcher."""
    def __init__(self, reason, *, launch_entered):
        super().__init__(reason)
        self.launch_entered = launch_entered


def _save(path, value):
    path = _safe_path(Path(path)); path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _safe_path(path.parent); result = public.save_once(path, value)
    jobs._sync_directory_ancestry(path.parent)
    return result


def validate_policy(value):
    return contract.validate_policy(value)


class MockTTSClient:
    def __init__(self, root, stream, policy, *, create=False):
        self.root = _safe_path(Path(root)); self.stream = stream; self.policy = validate_policy(policy)
        self.scope = {'schemaVersion': 'sermon-mock-tts-scope-v1',
            'runId': stream.binding['productionRunId'], 'planSha256': stream.binding['planSha256'],
            'implementationSha256': contract.implementation_sha256(), 'policySha256': c.canonical_sha256(self.policy),
            'evidenceMode': 'synthetic', 'productionEligible': False}
        if create:
            c.require(not self.root.exists() or (self.root/'scope.json').exists()
                or not any(self.root.iterdir()), 'mock_tts_requires_dedicated_scope')
            _save(self.root/'scope.json', self.scope)
            _save(self.root/'policy.json', self.policy)
        self._check()

    def _check(self):
        c.require(public.read_snapshot(self.root/'scope.json')[0] == self.scope
            and public.read_snapshot(self.root/'policy.json')[0] == self.policy
            and self.scope['implementationSha256'] == contract.implementation_sha256(),
            'mock_tts_controller_binding_changed')
        durable.open_stream(self.stream.directory, scope_id=self.stream.binding['scopeId'],
            plan_sha256=self.stream.binding['planSha256'], production_run_id=self.scope['runId'],
            purpose=self.stream.binding['purpose'], workflow_id=self.stream.workflow_id)
        current = accounting._identity.get()
        c.require(current == (str(self.stream.directory), self.stream.run_id)
            and (profile.current() or {}).get('evidenceMode') == 'synthetic',
            'mock_tts_controller_context_changed')

    def _request(self, path):
        self._check(); path = _safe_path(Path(path)); request = contract.read_request(path)
        c.require(contract.scope_for_request(path, request) == self.root
            and request['unitId'] in self.policy['units']
            and self.policy['units'][request['unitId']] == request['targetLocale']
            and request['attemptNumber'] <= self.policy['maxAttemptsPerUnit']
            and request['workerTimeoutSeconds'] == self.policy['workerTimeoutSeconds'],
            'mock_tts_request_not_authorized')
        _, events = completion.current_events()
        completion.validate_synthetic(request['parentCompletion'], events,
            production_run_id=request['runId'], artifact_sha256=request['inputSha256'])
        if self._intent_path(request).exists():
            c.require(public.read_snapshot(self._intent_path(request))[0] == self._intent(request),
                'mock_tts_idempotency_conflict')
        return request, path

    def _intent(self, request):
        return contract.intent_for_request(request)

    def _intent_path(self, request):
        return self.root/'intents'/(request['idempotencyKey']+'.json')

    def _observation_path(self, request):
        return self.root/'observations'/(request['idempotencyKey']+'.json')

    def _attempt(self, request):
        return 'observe.' + request['attemptId']

    def _state(self, request):
        events, errors = accounting.read_events(self.stream.directory)
        c.require(not errors, 'mock_tts_controller_log_damaged')
        rows = {row['eventId']: row for row in events if row.get('event') == 'step_state_changed'
            and row.get('runId') == self.stream.run_id and row.get('attemptId') == self._attempt(request)}
        return max(rows.values(), key=lambda row: row['sequence']) if rows else None

    def _transition(self, request, state, reason, *, terminal=None):
        previous = self._state(request)
        if previous and previous['toState'] == state:
            return previous
        before = previous['toState'] if previous else None
        revision = c.canonical_sha256({'requestSha256': c.canonical_sha256(request),
            'previousEventId': previous['eventId'] if previous else None, 'fromState': before, 'toState': state})
        event = {'event': 'step_state_changed', 'stage': 'mock_tts.observe', 'stepId': request['unitId'],
            'fromState': before, 'toState': state, 'stateRevision': revision, 'reasonCode': reason}
        if terminal is not None:
            event['completedAt'] = terminal['completedAt']
        return self.stream.write(event, context={'workUnitId': request['unitId'],
            'attemptId': self._attempt(request), 'jobId': request['jobId'], 'revisionId': request['revisionId']},
            delivery_key='state.'+c.canonical_sha256([request['idempotencyKey'], state]),
            intent={'requestSha256': c.canonical_sha256(request), 'state': state, 'revision': revision})

    def _job(self, request):
        try:
            return jobs.peek_job(self.root/'jobs', request['jobId'])
        except FileNotFoundError:
            return {'jobId': request['jobId'], 'status': 'not_observed'}

    def submit(self, request_path):
        boundary = {'entered': False}
        try:
            result = self._submit(request_path, boundary)
        except Exception as exc:
            if isinstance(exc, accounting.AccountingWriteError) or getattr(exc, 'sermon_logging_failed', False):
                raise
            reason = str(exc) if isinstance(exc, ValueError) and re.fullmatch(r'[a-z][a-z0-9_]{0,119}', str(exc)) else (
                'mock_tts_submission_unconfirmed' if boundary['entered'] else 'mock_tts_prelaunch_rejected')
            raise SubmissionError(reason, launch_entered=boundary['entered']) from exc
        return {**result, 'launchEntered': boundary['entered']}

    def _submit(self, request_path, boundary):
        request, path = self._request(request_path)
        key = c.canonical_sha256({'scope': self.scope, 'purpose': 'admission'})
        with jobs._lock(self.root/'control-locks', key) as (_, _, held):
            c.require(held, 'mock_tts_controller_busy')
            intent = self._intent(request)
            intent_path = self._intent_path(request)
            if intent_path.exists():
                c.require(public.read_snapshot(intent_path)[0] == intent, 'mock_tts_idempotency_conflict')
                result = self._job(request)
                return {**result, 'newDispatch': False, 'reconciliationRequired': result['status'] == 'not_observed',
                    'dispatchCompletion': self._dispatch_completion(request)}
            intents = list((self.root/'intents').glob('*.json')) if (self.root/'intents').exists() else []
            c.require(len(intents) < self.policy['maxJobs'], 'mock_tts_job_budget_exhausted')
            active = 0
            for existing_path in intents:
                existing = public.read_snapshot(existing_path)[0]
                if existing['unitId'] == request['unitId']:
                    c.require(existing['revisionId'] == request['revisionId']
                        and existing['inputSha256'] == request['inputSha256'],
                        'mock_tts_revision_requires_new_plan')
                    c.require(existing['attemptNumber'] != request['attemptNumber'],
                        'mock_tts_attempt_identity_conflict')
                try: status = jobs.peek_job(self.root/'jobs', existing['jobId'])['status']
                except FileNotFoundError: status = 'uncertain'
                if status in {'queued', 'running', 'uncertain'}: active += 1
            c.require(active < self.policy['maxConcurrentJobs'], 'mock_tts_capacity_blocked')
            if request['attemptNumber'] > 1:
                self._require_retry(request)
            _save(intent_path, intent)  # precedes the only possible launch
            for state in ('pending', 'ready', 'queued'):
                self._transition(request, state, 'controller_submit_intent')
            ack = None
            with profile.context(jobId=request['jobId'], revisionId=request['revisionId']):
                with accounting.stage_outcome('mock_tts.dispatch', work_unit_id=request['unitId']+'.dispatch',
                        attempt_id='dispatch.'+request['attemptId'],
                        depends_on=[request['parentCompletion']['spanId']]) as dispatch:
                    # Capture this actual dispatch leaf in the detached job context.
                    env = worker.environment(self.root/'launcher')
                    command = [sys.executable, '-I', worker.__file__, 'submit', '--request', str(path),
                        '--request-sha256', c.canonical_sha256(request)]
                    try:
                        boundary['entered'] = True
                        result = subprocess.run(command,
                            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
                        c.require(result.returncode == 0, 'mock_tts_submit_ack_missing')
                        ack = json.loads(result.stdout)
                        c.require(type(ack) is dict and set(ack) == {'jobId', 'status'}
                            and ack['jobId'] == request['jobId'] and ack['status'] in jobs.STATUSES,
                            'mock_tts_submit_ack_invalid')
                        _save(self.root/'submit-acks'/(request['idempotencyKey']+'.json'), ack)
                        dispatch.finish('completed', artifact_sha256=c.canonical_sha256(ack))
                    except (subprocess.TimeoutExpired, OSError, ValueError):
                        ack = None
                        # A missing launcher ACK says nothing about detached work.
                        dispatch.finish('outcome_unknown')
                if ack is not None:
                    handle = completion.capture_synthetic(dispatch.span_id, production_run_id=request['runId'],
                        artifact_sha256=c.canonical_sha256(ack), artifact_kind='control_receipt',
                        job_id=request['jobId'], revision_id=request['revisionId'])
                    _save(self.root/'dispatch-completions'/(request['idempotencyKey']+'.json'), handle)
                    return {**ack, 'newDispatch': True, 'reconciliationRequired': False, 'dispatchCompletion': handle}
            return {'jobId': request['jobId'], 'status': 'uncertain', 'newDispatch': None,
                'reconciliationRequired': True, 'dispatchCompletion': None}

    def _dispatch_completion(self, request):
        path = self.root/'dispatch-completions'/(request['idempotencyKey']+'.json')
        if not path.exists(): return None
        handle = public.read_snapshot(path)[0]
        ack = public.read_snapshot(self.root/'submit-acks'/(request['idempotencyKey']+'.json'))[0]
        _, events = completion.current_events()
        return completion.validate_synthetic(handle, events, production_run_id=request['runId'],
            job_id=request['jobId'], revision_id=request['revisionId'], artifact_sha256=c.canonical_sha256(ack),
            stage='mock_tts.dispatch', dependencies=[request['parentCompletion']['spanId']])

    def _reconcile_dispatch(self, request, result, evidence_sha256):
        _, events = completion.current_events()
        attempt_id = 'dispatch.'+request['attemptId']
        ends = {e['eventId']: e for e in events if e.get('event') == 'stage_finished'
            and e.get('attemptId') == attempt_id and e.get('runId') == self.stream.run_id}
        if not ends or next(iter(ends.values()))['status'] != 'outcome_unknown': return
        c.require(len(ends) == 1 and next(iter(ends.values())).get('jobId') == request['jobId'],
            'mock_tts_dispatch_terminal_conflict')
        fact = {'event': 'attempt_reconciled', 'stage': 'mock_tts.dispatch_reconcile',
            'reconcilesAttemptId': attempt_id, 'result': result, 'evidenceSha256': evidence_sha256,
            'reasonCode': 'original_job_observed_after_missing_ack'}
        self.stream.write(fact, context={'workUnitId': request['unitId'],
            'jobId': request['jobId'], 'revisionId': request['revisionId']},
            delivery_key='dispatch-reconcile.'+request['idempotencyKey'], intent=fact)

    def _job_request(self, request, path):
        folder = self.root/'jobs'/request['jobId']
        original = public.read_snapshot(folder/'request.json')[0]
        c.require(jobs._request_valid(original, request['jobId'])
            and original == {'schemaVersion': jobs.SCHEMA, 'jobId': request['jobId'],
                'identity': contract.job_identity(request), 'command': worker.command(path, c.canonical_sha256(request)),
                'commandSha256': jobs._digest(worker.command(path, c.canonical_sha256(request))),
                'timeoutSeconds': float(request['workerTimeoutSeconds'])}, 'mock_tts_job_request_changed')
        state = public.read_snapshot(folder/'state.json')[0]
        c.require(state.get('schemaVersion') == jobs.SCHEMA and state.get('jobId') == request['jobId']
            and state.get('status') in jobs.STATUSES and state.get('requestSha256') == jobs._digest(original),
            'mock_tts_job_state_changed')
        context = public.read_snapshot(folder/'accounting-context.json')[0]
        c.require(state.get('accountingContextSha256') == jobs._digest(context), 'mock_tts_job_context_changed')
        restored = profile.restore_job_environment(context, request['jobId'])
        binding = json.loads(restored[profile.CONTEXT_ENV])
        c.require(restored[accounting.ENV_KEYS[1]] == self.stream.run_id
            and binding.get('productionRunId') == request['runId'] and binding.get('evidenceMode') == 'synthetic',
            'mock_tts_job_context_changed')
        return original

    def _recovery_observation_path(self, request):
        return self.root/'observation-recoveries'/(request['idempotencyKey']+'.json')

    def _raw_observation(self, request, path):
        value = public.read_snapshot(path)[0]
        keys = {'schemaVersion', 'requestSha256', 'jobId', 'observerAttemptId', 'observerSpanId',
            'status', 'reasonCode', 'jobStatusObserved', 'evidenceMode', 'productionEligible'}
        recovery = value.get('schemaVersion') == 'sermon-mock-tts-observation-recovery-v1'
        if recovery:
            keys |= {'recoveryOfAttemptId', 'originalStartFactSha256', 'priorObservationSha256'}
        c.require(type(value) is dict and set(value) == keys
            and value['schemaVersion'] in {OBSERVATION, 'sermon-mock-tts-observation-recovery-v1'}
            and value['requestSha256'] == c.canonical_sha256(request) and value['jobId'] == request['jobId']
            and value['evidenceMode'] == 'synthetic' and value['productionEligible'] is False
            and value['status'] in {'succeeded', 'failed', 'outcome_unknown'}, 'mock_tts_observation_changed')
        if not recovery:
            c.require(value['observerAttemptId'] == self._attempt(request), 'mock_tts_observation_changed')
        else:
            c.require(value['recoveryOfAttemptId'] == self._attempt(request)
                and value['status'] == 'outcome_unknown'
                and contract.sha(value['originalStartFactSha256'])
                and (value['priorObservationSha256'] is None or contract.sha(value['priorObservationSha256'])),
                'mock_tts_observation_recovery_changed')
            original = self._observation_path(request)
            c.require((c.canonical_sha256(public.read_snapshot(original)[0]) if original.exists() else None)
                == value['priorObservationSha256'], 'mock_tts_original_observation_changed')
        return value

    def _observation_terminal(self, value, request):
        _, events = completion.current_events()
        ends = {e['eventId']: e for e in events if e.get('event') == 'stage_finished'
            and e.get('runId') == self.stream.run_id and e.get('attemptId') == value['observerAttemptId']}
        expected = {'succeeded': 'completed', 'failed': 'failed', 'outcome_unknown': 'outcome_unknown'}[value['status']]
        c.require(len(ends) == 1 and next(iter(ends.values()))['status'] == expected
            and next(iter(ends.values()))['spanId'] == value['observerSpanId']
            and next(iter(ends.values())).get('jobId') == request['jobId']
            and next(iter(ends.values())).get('revisionId') == request['revisionId']
            and next(iter(ends.values())).get('workUnitId') == request['unitId']+'.observer'
            and next(iter(ends.values())).get('stage') == ('mock_tts.observe' if value['schemaVersion'] == OBSERVATION
                else 'mock_tts.observe_recovery'), 'mock_tts_observer_terminal_required')
        terminal = next(iter(ends.values()))
        bindings = {e['eventId']: e for e in events if e.get('event') == 'workload'
            and e.get('spanId') == terminal['spanId'] and 'receiptSha256' in e.get('metrics', {})}
        c.require(len(bindings) == 1 and next(iter(bindings.values()))['metrics']['receiptSha256']
            == c.canonical_sha256(value), 'mock_tts_observation_receipt_unbound')
        if value['schemaVersion'] != OBSERVATION:
            starts = {e['eventId']: e for e in events if e.get('event') == 'stage_started'
                and e.get('runId') == self.stream.run_id
                and e.get('attemptId') == value['recoveryOfAttemptId']}
            c.require(len(starts) == 1 and log_contract.fact_hash(next(iter(starts.values())))
                == value['originalStartFactSha256'],
                'mock_tts_original_observer_changed')
        return next(iter(ends.values()))

    def _checked_observation(self, request):
        recovered = self._recovery_observation_path(request)
        value = self._raw_observation(request, recovered if recovered.exists() else self._observation_path(request))
        self._observation_terminal(value, request)
        return value

    def _recover_observer(self, request):
        """New observation of a lost observer, never a fabricated old finish."""
        _, events = completion.current_events()
        rows = {e['eventId']: e for e in events}
        starts = [e for e in rows.values() if e.get('event') == 'stage_started'
            and e.get('runId') == self.stream.run_id and e.get('attemptId') == self._attempt(request)]
        ends = [e for e in rows.values() if e.get('event') == 'stage_finished'
            and e.get('runId') == self.stream.run_id and e.get('attemptId') == self._attempt(request)]
        c.require(len(starts) == 1 and not ends and starts[0].get('jobId') == request['jobId'],
            'mock_tts_observer_recovery_not_proven')
        original = self._observation_path(request)
        previous = self._raw_observation(request, original) if original.exists() else None
        c.require(previous is None or previous['observerSpanId'] == starts[0]['spanId'],
            'mock_tts_original_observer_changed')
        original_hash = c.canonical_sha256(previous) if previous else None
        attempt_id = 'recovery.'+c.canonical_sha256([request['idempotencyKey'], starts[0]['eventId'], original_hash])[:32]
        terminals = [e for e in rows.values() if e.get('event') == 'stage_finished' and e.get('attemptId') == attempt_id]
        c.require(len(terminals) <= 1, 'mock_tts_observer_recovery_conflict')
        def recovered_value(span_id):
            return {'schemaVersion': 'sermon-mock-tts-observation-recovery-v1',
                'requestSha256': c.canonical_sha256(request), 'jobId': request['jobId'],
                'observerAttemptId': attempt_id, 'observerSpanId': span_id,
                'status': 'outcome_unknown', 'reasonCode': 'observer_terminal_not_recorded',
                'jobStatusObserved': 'not_observed', 'evidenceMode': 'synthetic', 'productionEligible': False,
                'recoveryOfAttemptId': self._attempt(request),
                'originalStartFactSha256': log_contract.fact_hash(starts[0]), 'priorObservationSha256': original_hash}
        if terminals:
            c.require(terminals[0]['status'] == 'outcome_unknown', 'mock_tts_observer_recovery_conflict')
            span_id = terminals[0]['spanId']
        else:
            # The per-request observer lease proves no earlier observer still
            # owns this operation. The old start remains incomplete in the log.
            with profile.context(jobId=request['jobId'], revisionId=request['revisionId']):
                with accounting.stage_outcome('mock_tts.observe_recovery',
                        work_unit_id=request['unitId']+'.observer', attempt_id=attempt_id,
                        depends_on=[starts[0]['spanId']]) as attempt:
                    accounting.record_workload('mock_tts.observer_lost', {
                        'originalStartFactSha256': log_contract.fact_hash(starts[0]),
                        'persistedObservationSha256': original_hash, 'newDispatch': False,
                        'receiptSha256': c.canonical_sha256(recovered_value(attempt.span_id))})
                    attempt.finish('outcome_unknown')
                span_id = attempt.span_id
        value = recovered_value(span_id)
        _save(self._recovery_observation_path(request), value)
        self._transition(request, 'outcome_unknown', value['reasonCode'], terminal=self._observation_terminal(value, request))
        return value

    def _worker_terminal_binding(self, request, receipt, expected_status):
        _, events = completion.current_events()
        rows = {e['eventId']: e for e in events}
        ends = [e for e in rows.values() if e.get('event') == 'stage_finished'
            and e.get('runId') == self.stream.run_id and e.get('attemptId') == request['attemptId']]
        c.require(len(ends) == 1, 'mock_tts_worker_terminal_unconfirmed')
        end = ends[0]
        starts = [e for e in rows.values() if e.get('event') == 'stage_started' and e.get('spanId') == end['spanId']]
        bindings = [e for e in rows.values() if e.get('event') == 'workload'
            and e.get('spanId') == end['spanId'] and 'receiptSha256' in e.get('metrics', {})]
        c.require(len(starts) == len(bindings) == 1 and end['status'] == expected_status
            and end.get('stage') == 'mock_tts.worker' and end.get('jobId') == request['jobId']
            and end.get('revisionId') == request['revisionId']
            and bindings[0]['metrics']['receiptSha256'] == c.canonical_sha256(receipt),
            'mock_tts_worker_receipt_unbound')
        timing = receipt['timing']; start = starts[0]
        c.require(timing['clockDomainId'] == start['clockDomainId'] == end['clockDomainId']
            and int(start['monotonicStartNs']) <= int(timing['startedMonotonicNs'])
                <= int(timing['completedMonotonicNs']) <= int(end['monotonicEndNs']),
            'mock_tts_worker_timing_changed')
        return end

    def _confirmed_failure(self, request, path, receipt):
        self._job_request(request, path)
        c.require(receipt['status'] == 'worker_failed' and self._job(request)['status'] not in {'queued', 'running'},
            'mock_tts_worker_failure_unconfirmed')
        self._worker_terminal_binding(request, receipt, 'failed')

    def _terminal_receipt(self, request, path):
        root = path.parent.parent/'worker'
        if not (root/'receipt.json').exists(): return None
        return contract.validate_receipt(public.read_snapshot(root/'receipt.json')[0], request)

    def observe(self, request_path, *, timeout_seconds=None):
        request, path = self._request(request_path)
        key = c.canonical_sha256(['observer', request['idempotencyKey']])
        with jobs._lock(self.root/'observation-locks', key) as (_, _, held):
            c.require(held, 'mock_tts_observer_busy')
            return self._observe_locked(path, timeout_seconds=timeout_seconds)

    def _observe_locked(self, request_path, *, timeout_seconds=None):
        request, path = self._request(request_path)
        c.require(self._intent_path(request).exists(), 'mock_tts_submit_required')
        saved_path = self._observation_path(request)
        if self._recovery_observation_path(request).exists():
            value = self._checked_observation(request)
            self._transition(request, value['status'], value['reasonCode'], terminal=self._observation_terminal(value, request))
            if value['status'] in {'succeeded', 'failed'}:
                self._reconcile_dispatch(request, value['status'], c.canonical_sha256(value))
            return value
        if saved_path.exists():
            try:
                value = self._checked_observation(request)
            except c.ContractError as exc:
                if str(exc) != 'mock_tts_observer_terminal_required': raise
                _, events = completion.current_events()
                if any(e.get('event') == 'stage_finished' and e.get('attemptId') == self._attempt(request)
                        for e in events): raise
                return self._recover_observer(request)
            self._transition(request, value['status'], value['reasonCode'], terminal=self._observation_terminal(value, request))
            if value['status'] in {'succeeded', 'failed'}:
                self._reconcile_dispatch(request, value['status'], c.canonical_sha256(value))
            return value
        _, prior_events = completion.current_events()
        if any(e.get('event') == 'stage_started' and e.get('attemptId') == self._attempt(request)
                for e in prior_events):
            return self._recover_observer(request)
        timeout = self.policy['observationTimeoutSeconds'] if timeout_seconds is None else timeout_seconds
        c.require(contract.number(timeout, .01, self.policy['observationTimeoutSeconds']),
            'mock_tts_observation_deadline_invalid')
        self._transition(request, 'running', 'controller_observation_started')
        status, reason, job = 'outcome_unknown', 'observation_timeout', self._job(request)
        with profile.context(jobId=request['jobId'], revisionId=request['revisionId']):
            with accounting.stage_outcome('mock_tts.observe', work_unit_id=request['unitId']+'.observer',
                    attempt_id=self._attempt(request), depends_on=[request['parentCompletion']['spanId']]) as attempt:
                deadline = time.monotonic() + timeout
                while True:
                    job = self._job(request)
                    # The immutable receipt may already be linked while its
                    # writer is still finishing publication/accounting. Only
                    # read it after the physical job leaves its active states;
                    # retain the strict snapshot checks and original deadline.
                    receipt = (None if job['status'] in {'queued', 'running'}
                        else self._terminal_receipt(request, path))
                    if receipt is not None and job['status'] not in {'queued', 'running'}:
                        if receipt['status'] == 'worker_failed':
                            self._confirmed_failure(request, path, receipt)
                            status, reason = 'failed', 'confirmed_worker_failure'
                        elif job['status'] == 'succeeded':
                            self._job_request(request, path)
                            status, reason = 'succeeded', 'original_worker_returned'
                        break
                    if job['status'] in {'failed', 'uncertain', 'not_observed'}:
                        reason = 'original_job_requires_reconciliation'; break
                    if time.monotonic() >= deadline: break
                    time.sleep(min(.025, max(0, deadline-time.monotonic())))
                value = {'schemaVersion': OBSERVATION, 'requestSha256': c.canonical_sha256(request),
                    'jobId': request['jobId'], 'observerAttemptId': self._attempt(request),
                    'observerSpanId': attempt.span_id, 'status': status, 'reasonCode': reason,
                    'jobStatusObserved': job['status'], 'evidenceMode': 'synthetic', 'productionEligible': False}
                _save(saved_path, value)
                accounting.record_workload('mock_tts.observation', {'receiptSha256': c.canonical_sha256(value)})
                attempt.finish({'succeeded': 'completed', 'failed': 'failed', 'outcome_unknown': 'outcome_unknown'}[status])
        self._transition(request, status, reason, terminal=self._observation_terminal(value, request))
        if status in {'succeeded', 'failed'}:
            self._reconcile_dispatch(request, status, c.canonical_sha256(value))
        return value

    def _completion_proof(self, request, path, receipt, *, recover=False):
        root = path.parent.parent/'worker'
        original = root/'completion.json'
        derived_path = self.root/'completion-recoveries'/(request['idempotencyKey']+'.json')
        if original.exists():
            return public.read_snapshot(original)[0]
        if derived_path.exists():
            recovered = public.read_snapshot(derived_path)[0]
            c.require(type(recovered) is dict and set(recovered) == {'schemaVersion', 'requestSha256',
                'workerReceiptSha256', 'proof', 'derivation', 'productionEligible'}
                and recovered['schemaVersion'] == 'sermon-mock-tts-completion-recovery-v1'
                and recovered['requestSha256'] == c.canonical_sha256(request)
                and recovered['workerReceiptSha256'] == c.canonical_sha256(receipt)
                and recovered['derivation'] == 'original_logged_terminals_only'
                and recovered['productionEligible'] is False, 'mock_tts_completion_recovery_changed')
            return recovered['proof']
        c.require(recover and self._job(request)['status'] in {'failed', 'uncertain'},
            'mock_tts_completion_ack_missing')
        end = self._worker_terminal_binding(request, receipt, 'completed')
        _, events = completion.current_events()
        c.require(not any(e.get('event') == 'workflow_finished' and e.get('workflowId') == end['workflowId']
            and e.get('status') == 'completed' for e in events), 'mock_tts_completed_worker_proof_missing')
        handles = {}; previous = request['parentCompletion']['spanId']
        for name in ('received', 'queued', 'worker'):
            attempt_id = request['attemptId'] if name == 'worker' else request['attemptId']+'.'+name
            ends = {e['eventId']: e for e in events if e.get('event') == 'stage_finished'
                and e.get('attemptId') == attempt_id and e.get('runId') == self.stream.run_id}
            c.require(len(ends) == 1, 'mock_tts_completion_terminal_missing')
            terminal = next(iter(ends.values()))
            digest = receipt['artifact']['sha256'] if name == 'worker' else c.canonical_sha256(
                public.read_snapshot(root/'lifecycle'/(name+'.json'))[0])
            handle = completion.capture_synthetic(terminal['spanId'], production_run_id=request['runId'],
                artifact_sha256=digest, artifact_kind='mock_wav' if name == 'worker' else 'control_receipt',
                job_id=request['jobId'], revision_id=request['revisionId'])
            completion.validate_synthetic(handle, events, production_run_id=request['runId'],
                stage='mock_tts.'+name, dependencies=[previous])
            handles[name] = handle; previous = handle['spanId']
        contract.verify_wav(root/'fixture.wav', request, receipt['artifact'])
        proof = {'schemaVersion': contract.COMPLETION, 'requestSha256': c.canonical_sha256(request),
            'receiptSha256': c.canonical_sha256(receipt), 'handles': handles,
            'evidenceMode': 'synthetic', 'productionEligible': False}
        _save(derived_path, {'schemaVersion': 'sermon-mock-tts-completion-recovery-v1',
            'requestSha256': c.canonical_sha256(request), 'workerReceiptSha256': c.canonical_sha256(receipt),
            'proof': proof, 'derivation': 'original_logged_terminals_only', 'productionEligible': False})
        return proof

    def verify(self, request_path):
        request, path = self._request(request_path)
        self._job_request(request, path)
        receipt = self._terminal_receipt(request, path)
        c.require(receipt is not None and receipt['status'] == 'artifact_returned', 'mock_tts_worker_not_completed')
        self._worker_terminal_binding(request, receipt, 'completed')
        root = path.parent.parent/'worker'
        proof = self._completion_proof(request, path, receipt)
        c.require(type(proof) is dict and set(proof) == {'schemaVersion', 'requestSha256', 'receiptSha256',
            'handles', 'evidenceMode', 'productionEligible'} and proof['schemaVersion'] == contract.COMPLETION
            and proof['requestSha256'] == c.canonical_sha256(request)
            and proof['receiptSha256'] == c.canonical_sha256(receipt)
            and proof['evidenceMode'] == 'synthetic' and proof['productionEligible'] is False
            and type(proof['handles']) is dict and set(proof['handles']) == {'received', 'queued', 'worker'},
            'mock_tts_completion_changed')
        _, events = completion.current_events()
        previous = request['parentCompletion']['spanId']
        for name in ('received', 'queued', 'worker'):
            handle = proof['handles'][name]
            digest = receipt['artifact']['sha256'] if name == 'worker' else c.canonical_sha256(
                public.read_snapshot(root/'lifecycle'/(name+'.json'))[0])
            completion.validate_synthetic(handle, events, production_run_id=request['runId'],
                job_id=request['jobId'], revision_id=request['revisionId'], artifact_sha256=digest,
                stage='mock_tts.'+name, dependencies=[previous])
            c.require(handle['artifactKind'] == ('mock_wav' if name == 'worker' else 'control_receipt'),
                'mock_tts_completion_artifact_kind_changed')
            c.require(handle['attemptId'] == (request['attemptId'] if name == 'worker'
                else request['attemptId']+'.'+name), 'mock_tts_completion_attempt_changed')
            previous = handle['spanId']
        artifact = contract.verify_wav(root/'fixture.wav', request, receipt['artifact'])
        return {'schemaVersion': ADMISSION, 'requestSha256': c.canonical_sha256(request),
            'workerReceiptSha256': c.canonical_sha256(receipt), 'completionSha256': c.canonical_sha256(proof),
            'jobId': request['jobId'], 'unitId': request['unitId'], 'revisionId': request['revisionId'],
            'artifact': artifact, 'workerCompletion': proof['handles']['worker'],
            'executionStatus': 'succeeded', 'admissionStatus': 'verified_synthetic',
            'humanAcceptance': 'pending', 'productionEligible': False, 'evidenceMode': 'synthetic'}

    def reconcile(self, request_path):
        """Receipt-only: cannot call submit/start_job and never rewrites old facts."""
        request, path = self._request(request_path)
        original = self._checked_observation(request)
        c.require(original['requestSha256'] == c.canonical_sha256(request)
            and original['status'] == 'outcome_unknown', 'mock_tts_unknown_observation_required')
        _, events = completion.current_events()
        ends = {e['eventId']: e for e in events if e.get('event') == 'stage_finished'
            and e.get('runId') == self.stream.run_id and e.get('attemptId') == original['observerAttemptId']}
        c.require(len(ends) == 1 and next(iter(ends.values()))['status'] == 'outcome_unknown',
            'mock_tts_unknown_terminal_required')
        if self._job(request)['status'] in {'queued', 'running'}:
            return {'status': 'still_unknown', 'newDispatch': False, 'productionEligible': False}
        receipt = self._terminal_receipt(request, path)
        if receipt is None:
            return {'status': 'still_unknown', 'newDispatch': False, 'productionEligible': False}
        if receipt['status'] == 'worker_failed':
            self._confirmed_failure(request, path, receipt)
            result, evidence = 'failed', {'workerReceiptSha256': c.canonical_sha256(receipt)}
        else:
            self._completion_proof(request, path, receipt, recover=True)
            result, evidence = 'succeeded', self.verify(path)
        reconciled = {'schemaVersion': 'sermon-mock-tts-reconciliation-v1',
            'requestSha256': c.canonical_sha256(request), 'observerSha256': c.canonical_sha256(original),
            'status': result, 'evidence': evidence, 'newDispatch': False, 'productionEligible': False}
        digest = c.canonical_sha256(reconciled)
        _save(self.root/'reconciliations'/(request['idempotencyKey']+'.json'), reconciled)
        self.stream.write({'event': 'attempt_reconciled', 'stage': 'mock_tts.reconcile',
            'reconcilesAttemptId': original['observerAttemptId'], 'result': result,
            'evidenceSha256': digest, 'reasonCode': 'original_worker_receipt_verified'},
            context={'workUnitId': request['unitId'], 'jobId': request['jobId'], 'revisionId': request['revisionId']},
            delivery_key='reconcile.'+request['idempotencyKey'], intent=reconciled)
        self._reconcile_dispatch(request, result, digest)
        return reconciled

    def _require_retry(self, request):
        prior = []
        for path in (self.root/'requests').glob('*/mock-tts-request/request.json'):
            value = contract.read_request(path)
            if c.canonical_sha256(value) == request['retryOfRequestSha256']: prior.append((value, path))
        c.require(len(prior) == 1, 'mock_tts_retry_parent_missing')
        previous, path = prior[0]
        c.require(request['attemptNumber'] == previous['attemptNumber'] + 1
            and all(request[k] == previous[k] for k in
                ('runId', 'planSha256', 'unitId', 'targetLocale', 'inputSha256', 'revisionId', 'waveform')),
            'mock_tts_retry_input_changed')
        observation = self._checked_observation(previous)
        if observation['status'] == 'outcome_unknown':
            reconciled = public.read_snapshot(self.root/'reconciliations'/(previous['idempotencyKey']+'.json'))[0]
            _, events = completion.current_events()
            c.require(reconciled['status'] == 'failed' and reconciled['requestSha256'] == c.canonical_sha256(previous)
                and any(e.get('event') == 'attempt_reconciled'
                    and e.get('reconcilesAttemptId') == observation['observerAttemptId']
                    and e.get('result') == 'failed' and e.get('jobId') == previous['jobId']
                    and e.get('evidenceSha256') == c.canonical_sha256(reconciled) for e in events),
                'mock_tts_retry_requires_reconciliation')
        else:
            c.require(observation['status'] == 'failed', 'mock_tts_retry_not_confirmed_failed')
        receipt = self._terminal_receipt(previous, path)
        c.require(receipt is not None and receipt['status'] == 'worker_failed',
            'mock_tts_retry_not_confirmed_failed')
        self._confirmed_failure(previous, path, receipt)

    def prepare_request(self, unit, parent_handles, *, input_binding, fault=None, attempt_number=1, retry_of=None):
        """Bind a producer-validated unit to one immutable local execution key."""
        self._check()
        c.require(type(unit) is dict and set(unit) == {'unitId', 'targetLocale', 'inputSha256', 'revisionId'}
            and self.policy['units'].get(unit['unitId']) == unit['targetLocale']
            and contract.sha(unit['inputSha256']) and contract.sha(unit['revisionId'])
            and type(parent_handles) is list and bool(parent_handles), 'mock_tts_unit_binding_invalid')
        contract.validate_input_binding(input_binding, unit)
        _, events = completion.current_events()
        for handle in parent_handles:
            completion.validate_synthetic(handle, events, production_run_id=self.scope['runId'])
        key = c.canonical_sha256({'runId': self.scope['runId'], 'unitId': unit['unitId'],
            'revisionId': unit['revisionId'], 'attemptNumber': attempt_number})
        request = {'schemaVersion': contract.REQUEST, 'evidenceMode': 'synthetic',
            'controlBatchSemantics': contract.BATCH, 'runId': self.scope['runId'],
            'planSha256': self.scope['planSha256'], **unit, 'attemptId': 'worker.'+key[:32],
            'attemptNumber': attempt_number, 'retryOfRequestSha256': retry_of, 'idempotencyKey': key,
            'implementationSha256': self.scope['implementationSha256'],
            'waveform': {'sampleRate': 16000, 'frames': 2400, 'seed': 1+int(unit['inputSha256'][:4], 16) % 31},
            'fault': deepcopy(fault or {'mode': 'none', 'queueDelaySeconds': 0, 'runDelaySeconds': 0}),
            'workerTimeoutSeconds': self.policy['workerTimeoutSeconds'],
            'productionEligible': False, 'humanAcceptance': 'pending'}
        request['jobId'] = contract.job_id(request)
        path = self.root/'requests'/key/'mock-tts-request/request.json'
        if path.exists():
            previous = contract.read_request(path)
            c.require({k: v for k, v in previous.items() if k != 'parentCompletion'} == request,
                'mock_tts_idempotency_conflict')
            # A recovery task can revalidate the unit through a new parent gate;
            # the original worker request still consumes its original evidence.
            self._request(path)
            return previous, path
        with profile.context(jobId=request['jobId'], revisionId=request['revisionId']):
            with accounting.stage_outcome('mock_tts.input_verified', work_unit_id=unit['unitId']+'.input',
                    attempt_id='input.'+key[:32], depends_on=[h['spanId'] for h in parent_handles]) as attempt:
                _save(path.parent.parent/'unit-input.json', input_binding)
                attempt.finish('completed', artifact_sha256=unit['inputSha256'])
            request['parentCompletion'] = completion.capture_synthetic(attempt.span_id,
                production_run_id=self.scope['runId'], artifact_sha256=unit['inputSha256'],
                artifact_kind='control_receipt', job_id=request['jobId'], revision_id=request['revisionId'])
        _save(path, contract.validate_request(request))
        return request, path

    def _control_operation(self, request, name, dependencies, build):
        """Recover deterministic checks from original facts; never execute TTS."""
        folder = self.root/'admission'/request['idempotencyKey']
        core_path, proof_path = folder/(name+'.json'), folder/(name+'-completion.json')
        persisted = public.read_snapshot(core_path)[0] if core_path.exists() else None
        digest = c.canonical_sha256(persisted) if persisted is not None else None
        _, events = completion.current_events()
        if proof_path.exists():
            c.require(persisted is not None and build() == persisted, 'mock_tts_admission_changed')
            handle = public.read_snapshot(proof_path)[0]
            completion.validate_synthetic(handle, events, production_run_id=request['runId'],
                job_id=request['jobId'], revision_id=request['revisionId'], artifact_sha256=digest,
                stage='mock_tts.'+name, dependencies=dependencies)
            return persisted, handle
        # Only an already-recorded terminal can restore a lost proof ACK.
        ends = {e['eventId']: e for e in events if e.get('event') == 'stage_finished'
            and e.get('stage') == 'mock_tts.'+name and e.get('jobId') == request['jobId']
            and e.get('revisionId') == request['revisionId'] and digest is not None
            and e.get('artifactSha256') == digest and e.get('status') == 'completed'
            and e.get('dependsOn') == dependencies}
        c.require(len(ends) <= 1, 'mock_tts_admission_terminal_conflict')
        if ends:
            c.require(build() == persisted, 'mock_tts_admission_changed')
            core, span_id = persisted, next(iter(ends.values()))['spanId']
        else:
            starts = {e['eventId']: e for e in events if e.get('event') == 'stage_started'
                and e.get('stage') == 'mock_tts.'+name and e.get('jobId') == request['jobId']}
            attempt_id = name+'.'+c.canonical_sha256([request['idempotencyKey'], len(starts)])[:32]
            with profile.context(jobId=request['jobId'], revisionId=request['revisionId']):
                with accounting.stage_outcome('mock_tts.'+name, work_unit_id=request['unitId']+'.'+name,
                        attempt_id=attempt_id, depends_on=dependencies, cache_hit=persisted is not None) as attempt:
                    core = build()  # actual byte/gate validation is inside its measured leaf
                    digest = c.canonical_sha256(core)
                    _save(core_path, core)
                    accounting.record_workload('mock_tts.admission', {'receiptSha256': digest,
                        'syntheticFixtureOnly': True, 'realListeningPerformed': False, 'productionEligible': False})
                    attempt.finish('completed', artifact_sha256=digest)
                span_id = attempt.span_id
        handle = completion.capture_synthetic(span_id, production_run_id=request['runId'],
            artifact_sha256=digest, artifact_kind='control_receipt',
            job_id=request['jobId'], revision_id=request['revisionId'])
        _save(proof_path, handle)
        return core, handle

    def verify_for_admission(self, request_path):
        request, path = self._request(request_path)
        observed = self._checked_observation(request)
        if observed['status'] == 'outcome_unknown':
            reconciled = public.read_snapshot(self.root/'reconciliations'/(request['idempotencyKey']+'.json'))[0]
            _, events = completion.current_events()
            c.require(reconciled['status'] == 'succeeded'
                and reconciled['requestSha256'] == c.canonical_sha256(request)
                and any(e.get('event') == 'attempt_reconciled'
                    and e.get('reconcilesAttemptId') == observed['observerAttemptId']
                    and e.get('result') == 'succeeded'
                    and e.get('evidenceSha256') == c.canonical_sha256(reconciled) for e in events),
                'mock_tts_admission_requires_reconciliation')
        else:
            c.require(observed['status'] == 'succeeded' and self._job(request)['status'] == 'succeeded',
                'mock_tts_admission_worker_failed')
        verified = self.verify(path)
        core, handle = self._control_operation(request, 'verify', [verified['workerCompletion']['spanId']],
            lambda: self.verify(path))
        return {'verification': core, 'completion': handle}

    def gate(self, request_path, verification):
        request, path = self._request(request_path)
        c.require((self.root/'admission'/request['idempotencyKey']/'verify-completion.json').exists(),
            'mock_tts_explicit_verification_required')
        def build_gate():
            current = self.verify_for_admission(path)
            c.require(current == verification, 'mock_tts_gate_verification_changed')
            return {'schemaVersion': 'sermon-mock-tts-gate-v1', 'requestSha256': c.canonical_sha256(request),
                'verificationSha256': c.canonical_sha256(verification), 'unitId': request['unitId'],
                'jobId': request['jobId'], 'revisionId': request['revisionId'],
                'reviewScope': 'synthetic_fixture_bytes_only', 'fixtureGate': 'passed',
                'requiredChecks': ['original_request', 'typed_worker_completion', 'wav_full_decode', 'bytes_hash', 'fixture_bytes'],
                'admissionStatus': 'admitted_synthetic', 'humanAcceptance': 'pending',
                'listeningAcceptance': 'not_performed', 'formalAudioEligible': False,
                'publicationAuthorized': False, 'productionEligible': False, 'evidenceMode': 'synthetic'}
        result, handle = self._control_operation(request, 'gate', [verification['completion']['spanId']], build_gate)
        return {'gate': result, 'completion': handle}
