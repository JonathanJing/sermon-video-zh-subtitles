"""Bounded source ASR/judge requests with a pinned, conservative durable ledger.

Audio reservations use requests/time/cost only. Unreported audio token counts
remain absent. Every uncertain call retains its full bound across restarts.
"""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import json
import os
import re
from pathlib import Path
import time
import urllib.request
import uuid

from scripts import sermon_workflow_jobs as jobs
from scripts import production_spark_admission as spark_admission
from scripts import sermon_provider_http as http
from scripts import sermon_provider_limits as text_limits
from scripts import sermon_pipeline as pipeline
from scripts import sermon_transcription_request as transcription
from scripts import english_source_judge_cache as immutable

JUDGE_LIMITS = ContextVar('source_judge_request_limits', default=None)
METRICS = ('requests', 'wallTimeMs', 'costMicrousd')
LOCK = jobs._digest({'purpose': 'source-budget-v1'})
LEDGER_V2 = 'sermon-source-budget-ledger-v2'


def require(ok, code):
    if not ok:
        raise ValueError(code)


@contextmanager
def judge_limits(limits):
    token = JUDGE_LIMITS.set(limits)
    try:
        yield
    finally:
        JUDGE_LIMITS.reset(token)


def bound_judge_payload(payload):
    limits = JUDGE_LIMITS.get()
    if limits is None:
        return payload
    require(payload['model'] != 'gpt-6.1-sol', 'codex_cli_provider_output_cap_unsupported')
    from scripts import judge_english_source_for_translation as judge
    text_limits.validate_request_limits(limits)
    require(payload['model'] == 'gpt-6-astra'
            and payload['response_format']['json_schema']['schema'] == judge._response_schema(),
            'unsupported_source_judge_payload')
    require(text_limits._input_upper_bound(payload) <= limits['maxInputTokens'], 'source_judge_input_bound_exceeded')
    return dict(payload, max_completion_tokens=limits['maxCompletionTokens'], service_tier=limits['serviceTier'])


class SourceBudget:
    def __init__(self, root, authority, *, verify, transport=None, max_concurrent=1, resource_policy=None):
        self.root, self.authority, self.verify = Path(root), authority, verify
        self.transport = transport
        require(type(max_concurrent) is int and 1 <= max_concurrent <= 8, 'invalid_source_concurrency')
        self.max_concurrent = max_concurrent
        self.resource_policy = None
        if resource_policy is not None:
            from scripts.sermon_unified import resources
            self.resource_policy = resources.validate_policy(resource_policy)
        require(set(authority) == {'approvalSha256', 'globalBounds', 'requestLimits'}, 'invalid_source_budget_authority')
        require(set(authority['globalBounds']) == set(METRICS)
                and all(type(v) is int and 0 < v <= 10**15 for v in authority['globalBounds'].values()),
                'invalid_source_budget_bounds')
        text_limits.validate_request_limits(authority['requestLimits'])

    @contextmanager
    def _locked(self):
        for attempt in range(100):
            with jobs._lock(self.root, LOCK) as (_, _, held):
                if held:
                    path = self.root / 'source-budget.json'
                    if path.exists():
                        ledger = jobs._read(path)
                        version = ledger.get('schemaVersion')
                        require(version in ('sermon-source-budget-ledger-v1', LEDGER_V2)
                                and ledger.get('authority') == self.authority
                                and isinstance(ledger.get('requests'), dict)
                                and set(ledger) == ({'schemaVersion', 'authority', 'requests'} if version != LEDGER_V2
                                    else {'schemaVersion', 'authority', 'requests', 'maxConcurrent', 'resourcePolicySha256'})
                                and (version != LEDGER_V2 or (ledger['maxConcurrent'] == self.max_concurrent
                                    and ledger['resourcePolicySha256'] == self._resource_identity())), 'source_budget_identity_changed')
                        for operation, row in ledger['requests'].items():
                            require(isinstance(operation, str) and re.fullmatch(r'(asr\.[0-9]{4}|judge\.[a-f0-9]{64})', operation)
                                    and isinstance(row, dict) and row.get('status') in {'returned', 'started_response_unconfirmed', 'live_started'}
                                    and set(row) - {'resourceBinding'} == ({'identitySha256', 'bounds', 'status', 'responseSha256'}
                                        if row.get('status') == 'returned' else {'identitySha256', 'bounds', 'status', 'dispatchOwner'}
                                        if row.get('status') == 'live_started' and version == LEDGER_V2 else {'identitySha256', 'bounds', 'status'})
                                    and isinstance(row.get('identitySha256'), str)
                                    and re.fullmatch('[a-f0-9]{64}', row['identitySha256'])
                                    and isinstance(row.get('bounds'), dict) and set(row['bounds']) == set(METRICS)
                                    and row['bounds']['requests'] == 1
                                    and all(type(v) is int and 0 < v <= 10**15 for v in row['bounds'].values()),
                                    'source_budget_ledger_corrupt')
                            if row['status'] == 'returned':
                                require(isinstance(row.get('responseSha256'), str)
                                    and re.fullmatch('[a-f0-9]{64}', row['responseSha256']), 'source_budget_ledger_corrupt')
                            if 'resourceBinding' in row:
                                require(self.resource_policy is not None
                                    and row['resourceBinding'] == self._resource_binding(operation, row['identitySha256']),
                                    'source_resource_binding_changed')
                            if row['status'] == 'live_started':
                                require(isinstance(row['dispatchOwner'], dict) and set(row['dispatchOwner']) == {'token', 'pid'}
                                    and isinstance(row['dispatchOwner']['token'], str) and len(row['dispatchOwner']['token']) == 32
                                    and type(row['dispatchOwner']['pid']) is int, 'source_budget_ledger_corrupt')
                                if not self._operation_is_live(operation):
                                    row['status'] = 'started_response_unconfirmed'
                                    row.pop('dispatchOwner')
                                    jobs._persist(path, ledger)
                        if version != LEDGER_V2:
                            # Serial v1 jobs upgrade conservatively. Unknown rows
                            # stay unknown; explicit migration is required before
                            # changing concurrency or attaching a broker.
                            require(self.max_concurrent == 1 and self.resource_policy is None,
                                    'source_budget_v1_explicit_migration_required')
                            ledger.update(schemaVersion=LEDGER_V2, maxConcurrent=1, resourcePolicySha256=None)
                    else:
                        ledger = {'schemaVersion': LEDGER_V2, 'authority': self.authority, 'requests': {},
                                  'maxConcurrent': self.max_concurrent, 'resourcePolicySha256': self._resource_identity()}
                    yield ledger, path
                    return
            time.sleep(.01)
        raise ValueError('source_budget_busy')

    def _resource_identity(self):
        if self.resource_policy is None:
            return None
        from scripts.sermon_unified import resources
        return resources._identity(self.resource_policy)

    def _operation_path(self, operation):
        directory = self.root / 'live-owners'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        return directory / (jobs._digest(operation) + '.lock')

    def _operation_is_live(self, operation):
        with self._operation_path(operation).open('a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle, fcntl.LOCK_UN)
            return False

    def _release_resource(self, row):
        if row.get('resourceBinding') is not None:
            require(self.resource_policy is not None, 'source_resource_policy_missing')
            from scripts.sermon_unified import resources
            resources.release(self.resource_policy, **row['resourceBinding'])

    def _resource_binding(self, operation, fingerprint):
        return {'operation_id': 'source-api:' + jobs._digest({'root': str(self.root.resolve()),
            'operation': operation, 'identity': fingerprint}),
            'owner': {'sourceBudgetRoot': str(self.root.resolve()), 'operation': operation, 'identitySha256': fingerprint}}

    def _response_path(self, operation, fingerprint):
        # Equal audio requests in different chunks are independent operations.
        # Sharing one response file would overwrite elapsed/call identity and
        # corrupt an earlier durable receipt. Preserve readable v1 receipts.
        path = self.root / 'responses' / (jobs._digest(operation) + '-' + fingerprint + '.json')
        legacy = self.root / 'responses' / (fingerprint + '.json')
        return legacy if not path.exists() and legacy.exists() else path

    def call(self, *, operation, identity, bounds, request, api_key, content_type, endpoint):
        self.verify()
        require(isinstance(operation, str) and re.fullmatch(r'(asr\.[0-9]{4}|judge\.[a-f0-9]{64})', operation),
                'invalid_source_operation')
        with self._operation_path(operation).open('a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('source_operation_live') from None
            owner = {'token': uuid.uuid4().hex, 'pid': os.getpid()}
            try:
                return self._call(operation=operation, identity=identity, bounds=bounds, request=request,
                    api_key=api_key, content_type=content_type, endpoint=endpoint, owner=owner)
            except BaseException:
                with self._locked() as (ledger, path):
                    row = ledger['requests'].get(operation)
                    if row is not None and row.get('dispatchOwner') == owner:
                        row.update(status='started_response_unconfirmed')
                        row.pop('dispatchOwner')
                        jobs._persist(path, ledger)
                raise
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _call(self, *, operation, identity, bounds, request, api_key, content_type, endpoint, owner):
        self.verify()
        require(set(bounds) == set(METRICS) and bounds['requests'] == 1
                and all(type(v) is int and v > 0 for v in bounds.values()), 'invalid_source_request_bounds')
        fingerprint = jobs._digest(identity)
        response_path = self._response_path(operation, fingerprint)
        with self._locked() as (ledger, path):
            previous = ledger['requests'].get(operation)
            if previous is not None:
                require(previous['identitySha256'] == fingerprint and previous['bounds'] == bounds,
                        'source_operation_identity_changed')
                # This call owns the OS lock. A prior dispatch token under that
                # same operation is abandoned even though our newly acquired
                # lock now makes the path appear live to general inspection.
                if previous['status'] == 'live_started' and previous['dispatchOwner'] != owner:
                    previous['status'] = 'started_response_unconfirmed'
                    previous.pop('dispatchOwner')
                    jobs._persist(path, ledger)
                require(previous['status'] == 'returned', 'source_provider_outcome_unknown')
                saved = jobs._read(response_path)
                require(saved.get('identitySha256') == fingerprint
                        and jobs._digest(saved.get('requestIdentity')) == fingerprint
                        and jobs._digest(saved) == previous['responseSha256'], 'source_response_identity_changed')
                self._release_resource(previous)
                return saved['response']
            require(self.transport is not None or (isinstance(api_key, str) and bool(api_key)
                    and '\n' not in api_key and '\r' not in api_key), 'OPENAI_API_KEY_is_not_configured')
            # Unknown outcomes stop the source lane; they do not buy a fresh
            # operation ID or allow later work to conceal a missing chunk.
            require(all(row['status'] != 'started_response_unconfirmed' for row in ledger['requests'].values()),
                    'source_provider_outcome_unknown')
            require(sum(row['status'] == 'live_started' for row in ledger['requests'].values()) < self.max_concurrent,
                    'source_concurrency_busy')
            used = {key: sum(row['bounds'][key] for row in ledger['requests'].values()) for key in METRICS}
            require(all(used[key] + bounds[key] <= self.authority['globalBounds'][key] for key in METRICS),
                    'source_budget_exhausted')
            if self.transport is None:
                spark_admission.require_session()
            row = {'identitySha256': fingerprint, 'bounds': bounds,
                   'status': 'live_started', 'dispatchOwner': owner}
            if self.resource_policy is not None:
                from scripts.sermon_unified import resources
                binding = self._resource_binding(operation, fingerprint)
                require(resources.reserve(self.resource_policy, **binding, resource='online_api'), 'source_resource_capacity_busy')
                row['resourceBinding'] = binding
            ledger['requests'][operation] = row
            jobs._persist(path, ledger)
        response_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Preserve raw response before telemetry/semantic processing. An observed
        # invalid response remains a known returned response, never a paid retry.
        def returned(response, call_id=None, elapsed=None):
            saved = {'identitySha256': fingerprint, 'requestIdentity': identity, 'response': response,
                     'modelCallId': call_id, 'elapsedSeconds': elapsed,
                     'reservationBounds': bounds, 'invoiceVerified': False}
            immutable._atomic(response_path, saved)
            self.verify()
            with self._locked() as (ledger, path):
                row = ledger['requests'][operation]
                require(row['identitySha256'] == fingerprint, 'source_call_binding_changed')
                row.update(status='returned', responseSha256=jobs._digest(saved))
                row.pop('dispatchOwner', None)
                jobs._persist(path, ledger)
                self._release_resource(row)
        if self.transport is not None:
            start = time.monotonic()
            response = self.transport(endpoint, request, content_type, api_key)
            returned(response, elapsed=time.monotonic() - start)
            return response
        req = urllib.request.Request(endpoint, data=request,
            headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': content_type}, method='POST')
        req.accounting_model = identity['model']
        req.accounting_settings = {'requestPayloadSha256': fingerprint}
        return pipeline.request_json(req, retries=1, response_observer=returned,
            request_executor=spark_admission.SessionBoundCaller(
                lambda r: http.execute(r, bounds['wallTimeMs'] / 1000), purpose='source-audio-api'))

    def reconcile_returned(self, operation, expected_identity_sha256):
        """Explicit local reconciliation after raw return persisted but ledger did not.

        Missing response bytes remain unknown; this never invokes a provider,
        fabricates a response, releases the original bound, or approves content.
        """
        self.verify()
        path = self._response_path(operation, expected_identity_sha256)
        require(path.is_file(), 'source_returned_response_required')
        saved = jobs._read(path)
        require(saved.get('identitySha256') == expected_identity_sha256
                and jobs._digest(saved.get('requestIdentity')) == expected_identity_sha256
                and isinstance(saved.get('response'), dict), 'source_response_identity_changed')
        with self._locked() as (ledger, ledger_path):
            row = ledger['requests'].get(operation)
            require(row is not None and row['identitySha256'] == expected_identity_sha256
                    and saved.get('reservationBounds') == row['bounds'], 'source_reconciliation_binding_changed')
            if row['status'] == 'returned':
                require(row['responseSha256'] == jobs._digest(saved), 'source_response_identity_changed')
            else:
                require(row['status'] != 'live_started', 'source_operation_live')
                row.update(status='returned', responseSha256=jobs._digest(saved))
                jobs._persist(ledger_path, ledger)
            self._release_resource(row)
        return {'status': 'returned_response_reconciled', 'operation': operation,
                'modelCalls': 0, 'humanApproval': False, 'reservationReleased': False}

    def transcribe(self, operation, audio_bytes, audio_sha256, api_key):
        prepared = transcription.build_request(audio_bytes, audio_sha256)
        return self.call(operation=operation, identity=prepared['identity'], bounds=prepared['budgetBounds'],
                         request=prepared['body'], api_key=api_key, content_type=prepared['contentType'],
                         endpoint='https://api.openai.com/v1/audio/transcriptions')

    def judge(self, api_key, payload):
        expected = bound_judge_payload({key: value for key, value in payload.items()
                                       if key not in {'max_completion_tokens', 'service_tier'}})
        require(payload == expected and 'max_completion_tokens' in payload, 'source_judge_not_bounded')
        limits = self.authority['requestLimits']
        inputs = text_limits._input_upper_bound(payload)
        require(inputs <= limits['maxInputTokens'], 'source_judge_input_bound_exceeded')
        bounds = {'requests': 1, 'wallTimeMs': limits['wallTimeMs'],
                  'costMicrousd': text_limits._cost(payload['model'], inputs, limits['maxCompletionTokens'])}
        return self.call(operation='judge.' + jobs._digest(payload), identity=payload, bounds=bounds,
                         request=json.dumps(payload, ensure_ascii=False).encode(), api_key=api_key,
                         content_type='application/json', endpoint='https://api.openai.com/v1/chat/completions')
