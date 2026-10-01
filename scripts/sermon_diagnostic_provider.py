"""Explicit one-run provider seam; no credential lookup, CLI or implicit approval.

The caller must pin ONE existing BudgetStore and externally verified approval.
D5 keeps content/review limits; this provider sidecar, under the SAME global
lock, reserves every new chat request (including source checks) before dispatch.
No reservation is refunded. Unknown outcomes block the whole diagnostic. The
sidecar is an accounting guard, not another job scheduler. gpt-transcribe uses
decoded PCM duration and its verified model-specific duration price. Local
Whisper requires separate explicit user approval and is never a fallback.
"""
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

from scripts import sermon_accounting as accounting
from scripts import sermon_pipeline as pipeline
from scripts import sermon_log_profile as profile
from scripts import sermon_provider_limits as limits
from scripts import sermon_provider_http as http
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from scripts import sermon_workflow_jobs as jobs

SCHEMA = 'sermon-diagnostic-provider-v1'


def _require_before_dispatch(condition, reason_code):
    if not condition:
        raise pipeline.PreDispatchRejection(reason_code)


@lru_cache(maxsize=1)
def boot_identity():
    # A process restart must not reset the monotonic run deadline. Reboot or
    # unsupported clock domain requires operator reconciliation, never a reset.
    if sys.platform == 'darwin':
        raw = subprocess.check_output(['/usr/sbin/sysctl', '-n', 'kern.boottime'], timeout=5)
        match = re.search(rb'sec = (\d+), usec = (\d+)', raw)
        c.require(match is not None, 'provider_clock_domain_unavailable')
        raw = b':'.join(match.groups())
    elif sys.platform.startswith('linux'):
        raw = Path('/proc/sys/kernel/random/boot_id').read_bytes().strip()
    else:
        raise c.ContractError('provider_clock_domain_unavailable')
    return hashlib.sha256(raw).hexdigest()


def validate_config(value):
    keys = {'schemaVersion', 'runId', 'approvalSha256', 'codeSha256',
            'sourceMediaSha256', 'sourceClipSha256', 'sourceAudioSha256', 'sourceWindowSeconds',
            'targetMicrousd', 'hardLimitMicrousd', 'totalWallSeconds',
            'maxRequests', 'credentialReferenceSha256', 'projectId', 'organizationId', 'transcriptionModel'}
    c.require(type(value) is dict and set(value) == keys and value['schemaVersion'] == SCHEMA,
              'invalid_provider_run_config')
    for key in ('runId', 'approvalSha256', 'codeSha256', 'sourceMediaSha256',
                'sourceClipSha256', 'sourceAudioSha256', 'credentialReferenceSha256'):
        budget._hash(value[key])
    c.require(value['transcriptionModel'] == 'gpt-transcribe',
              'local_transcription_requires_specific_user_approval')
    window = value['sourceWindowSeconds']
    c.require(type(window) is list and len(window) == 2 and
              all(type(n) is int and n >= 0 for n in window) and window[1]-window[0] == 180,
              'provider_requires_180_second_window')
    for key, maximum in (('targetMicrousd', 25_000_000), ('hardLimitMicrousd', 40_000_000),
                         ('totalWallSeconds', 5400), ('maxRequests', 124)):
        c.require(type(value[key]) is int and 0 < value[key] <= maximum, 'invalid_provider_run_limit')
    c.require(value['targetMicrousd'] <= value['hardLimitMicrousd'], 'invalid_provider_run_limit')
    for key, prefix in (('projectId', 'proj_'), ('organizationId', 'org-')):
        item = value[key]
        c.require(item is None or (type(item) is str and re.fullmatch(prefix+r'[A-Za-z0-9_-]{1,100}', item)),
                  'invalid_provider_charge_identity')
    return deepcopy(value)


class DiagnosticProvider:
    """Inject as caller + usage_resolver into the explicit strict locale runner.

    No auth discovery occurs here. Project/org may be unknown (None), meaning
    the reused key's existing default account, never a guessed project header.
    Injected executor is a trusted offline test seam; normal executor is bounded
    subprocess HTTP. Config hashes bind evidence; they do not grant approval.
    """
    def __init__(self, store, config, request_limits=None, *, executor=http.execute,
                 monotonic=time.monotonic, domain=boot_identity):
        c.require(type(store) is budget.BudgetStore, 'trusted_budget_store_required')
        self.store, self.config = store, validate_config(config)
        c.require(self.config['approvalSha256']==store.authority['approvalSha256'] and
                  self.config['hardLimitMicrousd']<=store.authority['globalBounds']['costMicrousd'] and
                  self.config['maxRequests']<=store.authority['globalBounds']['requests'],
                  'provider_authority_exceeds_shared_budget')
        self.limits = limits.validate_request_limits(request_limits or limits.DEFAULT_REQUEST_LIMITS)
        self.executor, self.monotonic, self.domain = executor, monotonic, domain
        self._scoped_payloads = set()

    @contextmanager
    def _locked(self):
        with self.store._locked() as (folder, _):
            root = folder / 'provider-run'
            if not root.exists():
                root.mkdir(mode=0o700)
                jobs._sync_directory_ancestry(root)
                state = {'schemaVersion': SCHEMA, 'config': self.config,
                         'authoritySha256': self.store.authority_sha256,
                         'clockDomain': self.domain(), 'startedMonotonic': self.monotonic(),
                         'requests': {}}
                jobs._persist(root / 'state.json', state)
            state, _ = c.read_snapshot(root / 'state.json')
            c.require(set(state) == {'schemaVersion', 'config', 'authoritySha256', 'clockDomain',
                                    'startedMonotonic', 'requests'} and state['schemaVersion'] == SCHEMA and
                      state['config'] == self.config and state['authoritySha256'] == self.store.authority_sha256,
                      'provider_run_identity_changed')
            start = state['startedMonotonic']
            c.require(type(start) in (int, float) and math.isfinite(start) and start >= 0 and
                      state['clockDomain'] == self.domain(), 'provider_clock_domain_changed')
            c.require(type(state['requests']) is dict and len(state['requests']) <= self.config['maxRequests'],
                      'invalid_provider_requests')
            for key, row in state['requests'].items():
                strict.label(key)
                c.require(type(row) is dict and set(row) == {'requestSha256', 'bounds', 'model', 'state', 'receiptSha256', 'operationId'},
                          'invalid_provider_request')
                budget._hash(row['requestSha256'])
                if row['operationId'] is not None:strict.label(row['operationId'])
                if row['model'] == 'gpt-transcribe':
                    c.require(type(row['bounds']) is dict and set(row['bounds']) == {'requests','wallTimeMs','costMicrousd'} and
                        all(type(v) is int and 0<v<=10**15 for v in row['bounds'].values()), 'invalid_audio_budget_bounds')
                else:budget._amounts(row['bounds'], positive=True)
                c.require(row['bounds']['requests'] == 1 and row['model'] in ('gpt-6-astra', 'gpt-6-sol', 'gpt-transcribe') and
                          row['state'] in ('reserved', 'returned', 'rejected', 'outcome_unknown'), 'invalid_provider_request')
                if row['state'] == 'reserved':
                    c.require(row['receiptSha256'] is None, 'invalid_provider_request')
                else:budget._hash(row['receiptSha256'])
            yield root, state

    def _remaining(self, state):
        elapsed = self.monotonic() - state['startedMonotonic']
        _require_before_dispatch(0 <= elapsed < self.config['totalWallSeconds'], 'provider_run_deadline_reached')
        return self.config['totalWallSeconds'] - elapsed

    def _save(self, root, state):
        budget.BudgetStore._check_serialized_size(state)
        jobs._persist(root / 'state.json', state)

    def snapshot(self):
        with self._locked() as (_, state):
            reserved = sum(row['bounds']['costMicrousd'] for row in state['requests'].values())
            return {'configSha256': c.canonical_sha256(self.config),
                    'reservedMicrousd': reserved,
                    'remainingMicrousd': self.config['hardLimitMicrousd']-reserved,
                    'targetHeadroomUsedMicrousd': max(0, reserved-self.config['targetMicrousd']),
                    'requestCount': len(state['requests']),
                    'unknownModelCallIds': sorted(k for k,v in state['requests'].items() if v['state'] in ('reserved','outcome_unknown')),
                    'budgetBasis': 'worst_case_reservations_no_refunds', 'invoiceVerified': False}

    def _reserve(self, call_id, payload, request_limits, operation_id=None, audio_bounds=None):
        bound = audio_bounds if audio_bounds is not None else limits.request_bounds(payload, request_limits)
        with self._locked() as (root, state):
            self._remaining(state)
            deadline = min(state['startedMonotonic'] + self.config['totalWallSeconds'],
                           self.monotonic() + request_limits['wallTimeMs']/1000)
            _require_before_dispatch(not any(row['state'] in ('reserved','outcome_unknown') for row in state['requests'].values()),
                      'provider_outcome_reconciliation_required')
            _require_before_dispatch(call_id not in state['requests'], 'provider_call_already_reserved')
            _require_before_dispatch(operation_id is None or not any(row['operationId'] == operation_id
                for row in state['requests'].values()), 'provider_operation_already_reserved')
            model=payload.get('model',payload.get('api',{}).get('model'))
            if operation_id is not None:
                audio = model=='gpt-transcribe'
                _require_before_dispatch(sum(row['operationId'] is not None and (row['model']=='gpt-transcribe')==audio
                              for row in state['requests'].values())<2, 'provider_source_call_limit')
            _require_before_dispatch(len(state['requests']) < self.config['maxRequests'], 'provider_request_limit')
            used = sum(row['bounds']['costMicrousd'] for row in state['requests'].values())
            _require_before_dispatch(used + bound['costMicrousd'] <= self.config['hardLimitMicrousd'], 'provider_cost_limit')
            state['requests'][strict.label(call_id)] = {
                'requestSha256': c.canonical_sha256(payload), 'bounds': bound,
                'model': model, 'state': 'reserved', 'receiptSha256': None, 'operationId':operation_id}
            # Reserve enough bytes for a known receipt before dispatch too.
            projected = deepcopy(state)
            for row in projected['requests'].values():
                row.update(state='returned', receiptSha256='f'*64)
            budget.BudgetStore._check_serialized_size(projected)
            self._save(root, state)
            jobs._sync_directory_ancestry(root)
            return deadline

    def _cached_source(self, operation_id, payload):
        with self._locked() as (root,state):
            rows=[(key,row) for key,row in state['requests'].items() if row['operationId']==operation_id]
            if not rows:return None
            c.require(len(rows)==1, 'provider_operation_identity_conflict')
            call_id,row=rows[0]
            c.require(row['requestSha256']==c.canonical_sha256(payload), 'provider_operation_input_changed')
            c.require(row['state'] == 'returned' and row['receiptSha256'] is not None,
                      'provider_outcome_reconciliation_required')
            value,raw=c.read_snapshot(root/(call_id+'.json'))
            c.require(c.bytes_sha256(raw)==row['receiptSha256'] and value['modelCallId']==call_id and
                      value['payloadSha256']==row['requestSha256'] and type(value.get('response')) is dict,
                      'provider_saved_response_changed')
            accounting.record_workload('diagnostic.source_response_recovery', {
                'requestPayloadSha256':row['requestSha256'], 'providerReceiptSha256':row['receiptSha256'],
                'modelCallIdSha256':c.canonical_sha256(call_id), 'newTransportAttempts':0})
            return value['response']

    def _receipt(self, call_id, value, status):
        with self._locked() as (root, state):
            row = state['requests'].get(call_id)
            c.require(row is not None and row['state']=='reserved', 'provider_receipt_not_reserved')
            # Full response is private, bounded, and durable before any observer
            # or accounting finish can fail. No request content or key is saved.
            raw = strict.save_once(root / (call_id+'.json'), value)
            if status == 'returned' and row['model'] == 'gpt-transcribe':
                cost = value['costEvidence']
                if (cost.get('providerDurationStatus') not in ('reported','not_reported') or
                        (cost.get('costMicrousd') is not None and cost['costMicrousd']>row['bounds']['costMicrousd']) or
                        value['response'].get('model','gpt-transcribe')!='gpt-transcribe'):
                    status='outcome_unknown'
            elif status == 'returned':
                observed = value['usageObservation']
                measured = limits.usage_resolver(observed)
                if measured is None or any(measured[k] > row['bounds'][k] for k in
                        ('inputTokens','outputTokens','costMicrousd')):
                    status = 'outcome_unknown'
            row.update(state=status, receiptSha256=c.bytes_sha256(raw))
            self._save(root, state)
            if status == 'outcome_unknown':
                accounting.record_workload('diagnostic.provider_reconciliation', {
                    'modelCallIdSha256':c.canonical_sha256(call_id),
                    'providerReceiptSha256':c.bytes_sha256(raw),
                    'outcomeStatus':'outcome_unknown', 'reservationRetained':True})
                raise c.ContractError('provider_outcome_reconciliation_required')

    def _check_source(self, prepared):
        source = prepared['source']['source']
        window = source['approvedWindow']
        c.require(source['media']['sha256'] == self.config['sourceMediaSha256'] and
                  [window['startSeconds'], window['endSeconds']] == self.config['sourceWindowSeconds'],
                  'provider_approved_source_scope_changed')

    def source_check_payload(self):
        # Source checks can inspect ONLY the known successful ASR response from
        # this run's hash-bound audio. No arbitrary caller-authored prompt/input.
        with self._locked() as (root, state):
            rows = [(key,row) for key,row in state['requests'].items()
                    if row['model'] == 'gpt-transcribe' and row['state'] == 'returned']
            c.require(len(rows) == 1, 'provider_verified_transcription_required')
            key,row = rows[0]
            receipt,raw = c.read_snapshot(root / (key+'.json'))
            c.require(c.bytes_sha256(raw) == row['receiptSha256'] and receipt['modelCallId'] == key,
                      'provider_saved_response_changed')
            text = receipt['response'].get('text')
            c.require(type(text) is str and text.strip(), 'provider_transcription_text_required')
        return limits.bounded_payload({'model':'gpt-6-astra','reasoning_effort':'high',
            'messages':[{'role':'system','content':'Check the supplied English ASR for internal uncertainty. Return JSON with issues and uncertainty. Do not translate, invent unheard words, or grant human approval.'},
                {'role':'user','content':json.dumps({'sourceMediaSha256':self.config['sourceMediaSha256'],
                    'sourceAudioSha256':self.config['sourceAudioSha256'],
                    'sourceWindowSeconds':self.config['sourceWindowSeconds'],'transcript':text},sort_keys=True)}],
            'response_format':{'type':'json_object'}}, limits.MAX_REQUEST_LIMITS)

    def preflight_locale(self, prepared_groups):
        c.require(type(prepared_groups) is list and 1<=len(prepared_groups)<=18,
                  'diagnostic_locale_group_limit')
        # Validate every initial generator input before buying the first group.
        # Review inputs include future generated content and are checked again
        # at their own pre-dispatch boundary without truncation.
        for prepared in prepared_groups:
            self._check_source(prepared)
            c.require(prepared.get('requestLimits')==self.limits,'provider_request_limits_not_bound')
            limits.request_bounds(strict._payload(prepared,'translator',strict.prompt(prepared,'translator')),
                                  self.limits)

    def preflight(self, prepared, kind, root, repair=None):
        self._check_source(prepared)
        c.require(prepared.get('requestLimits') == self.limits, 'provider_request_limits_not_bound')
        if kind == 'review':
            manifest, _ = c.read_snapshot(root / 'revision.json')
            artifact, data = c.read_snapshot(root / 'candidate.json')
            request = strict.prompt(prepared, 'reviewer', candidate=artifact,
                                   input_manifest=strict.input_manifest(prepared, manifest, data))
            role = 'reviewer'
        else:
            request = strict.generation_prompt(prepared, repair)
            role = 'translator'
        payload = strict._payload(prepared, role, request)
        bound = limits.request_bounds(payload, self.limits)
        self._scoped_payloads.add(c.canonical_sha256(payload))
        return bound

    def __call__(self, api_key, payload, *, response_observer):
        return self.chat(api_key, payload, response_observer=response_observer)

    def chat(self, api_key, payload, *, response_observer=None, request_limits=None, operation_id=None):
        """Source-check and strict L2 calls share the identical global guard.

        Payload MUST already contain frozen limits, never silently injected here.
        No retries, credential reads, tool calls, provider fallback or redirects.
        """
        settings = limits.validate_request_limits(request_limits or self.limits)
        c.require(limits.bounded_payload(payload, settings) == payload, 'provider_payload_not_bounded')
        c.require(type(api_key) is str and 1 <= len(api_key) <= 1024 and '\n' not in api_key and '\r' not in api_key,
                  'provider_credential_required')
        if response_observer is None:
            c.require(payload == self.source_check_payload(), 'provider_source_check_payload_changed')
            operation_id = strict.label(operation_id or 'source.'+c.canonical_sha256(payload))
            recovered = self._cached_source(operation_id, payload)
            if recovered is not None:return recovered
        else:
            c.require(c.canonical_sha256(payload) in self._scoped_payloads, 'provider_unscoped_strict_payload')
            c.require(operation_id is None, 'strict_provider_operation_is_budget_bound')
        headers = {'Authorization': 'Bearer '+api_key, 'Content-Type': 'application/json'}
        for name, key in (('OpenAI-Project','projectId'),('OpenAI-Organization','organizationId')):
            if self.config[key] is not None:headers[name] = self.config[key]
        req = urllib.request.Request(pipeline.CHAT_URL, data=json.dumps(payload, allow_nan=False).encode(),
                                     headers=headers, method='POST')
        req.accounting_model = payload['model'];req.accounting_settings = accounting.request_metadata(payload)
        state = {}
        def started(call_id):
            state['id'] = call_id
            state['deadline'] = self._reserve(call_id, payload, settings, operation_id)
            if response_observer is not None:response_observer.request_started(call_id)
        def returned(response, call_id, elapsed):
            c.require(call_id == state['id'], 'provider_call_identity_changed')
            observed = {'requestedModel':payload['model'], 'providerModel':response.get('model'),
                        'providerUsage':accounting.normalize_usage(response.get('usage')),
                        'elapsedSeconds':elapsed, 'serviceTier':response.get('service_tier','default')}
            evidence = {'usageObservation':observed, 'modelCallId':call_id, 'payloadSha256':c.canonical_sha256(payload),
                        'response':response, 'elapsedSeconds':elapsed,
                        'costEvidence':limits.usage_cost_evidence(observed),
                        'reservationEvidence':limits.request_cost_evidence(payload,settings)}
            self._receipt(call_id, evidence, 'returned')
            if response_observer is not None:response_observer(response, call_id, elapsed)
            cost = limits.usage_cost_evidence(observed)
            accounting.record_workload('diagnostic.provider_usage', {
                'modelCallIdSha256':c.canonical_sha256(call_id), 'requestPayloadSha256':c.canonical_sha256(payload),
                'runConfigSha256':c.canonical_sha256(self.config),
                'priceEvidenceSha256':c.canonical_sha256(cost),
                'estimatedCostMicrousd':cost.get('costMicrousd'),
                'costIsEstimate':True, 'invoiceVerified':False,
                'cachedInputTokens':observed['providerUsage']['cachedInputTokens'],
                'cacheWriteTokens':observed['providerUsage']['cacheWriteTokens']})
        def rejected(error, call_id):
            self._receipt(call_id, {'modelCallId':call_id,'httpStatus':error.http_status,
                                   'payloadSha256':c.canonical_sha256(payload)}, 'rejected')
            if response_observer is not None:response_observer.request_rejected(error,call_id)
        returned.request_started=started;returned.request_rejected=rejected
        def execute(request):
            left = state['deadline']-self.monotonic()
            _require_before_dispatch(left>0, 'provider_attempt_deadline_reached')
            return self.executor(request,left,deadline=state['deadline'])
        # A session root is a deterministic wrapper, not a model span. Strict
        # adapters supply their own model span together with the observer;
        # standalone source review must always create its own measured child.
        span = (nullcontext() if response_observer is not None else
                accounting.stage('diagnostic.source_model', billing='api', executor_type='production_model'))
        context = profile.current()
        c.require(context is not None, 'diagnostic_requires_accounting_profile')
        with profile.context(logicalCallId=context.get('logicalCallId') or
                'diagnostic.'+c.canonical_sha256(payload),
                providerScopeKey=c.canonical_sha256({k:self.config[k] for k in
                    ('credentialReferenceSha256','projectId','organizationId')})), span:
            return pipeline.request_json(req,retries=1,response_observer=returned,request_executor=execute)

    def transcribe(self, api_key, wav_bytes, *, operation_id='transcription.initial'):
        """Fresh gpt-transcribe only. PCM duration/hash fixes the charged input.

        Explicit subsequent attempt requires a distinct stable operation ID;
        any unknown outcome blocks it. All attempts count against the same40USD.
        No token cap is invented for duration-billed audio; tokens stay unknown.
        """
        from scripts import sermon_transcription_request as audio
        prepared=audio.build_request(wav_bytes,self.config['sourceAudioSha256'])
        payload=prepared['identity'];operation_id=strict.label(operation_id)
        recovered=self._cached_source(operation_id,payload)
        if recovered is not None:return recovered
        c.require(type(api_key) is str and 1<=len(api_key)<=1024 and '\n' not in api_key and '\r' not in api_key,
                  'provider_credential_required')
        headers={'Authorization':'Bearer '+api_key,'Content-Type':prepared['contentType']}
        for name,key in (('OpenAI-Project','projectId'),('OpenAI-Organization','organizationId')):
            if self.config[key] is not None:headers[name]=self.config[key]
        request=urllib.request.Request(pipeline.TRANSCRIBE_URL,data=prepared['body'],headers=headers,method='POST')
        request.accounting_model='gpt-transcribe'
        request.accounting_settings={'requestPayloadSha256':c.canonical_sha256(payload)}
        state={}
        def started(call_id):
            state['id']=call_id
            state['deadline']=self._reserve(call_id,payload,{'wallTimeMs':300000},operation_id,
                                           audio_bounds=prepared['budgetBounds'])
        def returned(response,call_id,elapsed):
            cost=audio.usage_cost_evidence(response,payload['audio']['decodedDurationSeconds'])
            self._receipt(call_id,{'modelCallId':call_id,'payloadSha256':c.canonical_sha256(payload),
                'response':response,'elapsedSeconds':elapsed,'costEvidence':cost,
                'reservationEvidence':prepared['budgetBounds']},'returned')
            accounting.record_workload('diagnostic.transcription',{
                'sourceAudioSha256':self.config['sourceAudioSha256'],
                'requestPayloadSha256':c.canonical_sha256(payload),
                'inputAudioSeconds':payload['audio']['decodedDurationSeconds'],
                'priceEvidenceSha256':c.canonical_sha256(cost),
                'estimatedCostMicrousd':cost.get('costMicrousd'),'invoiceVerified':False})
        def rejected(error,call_id):
            self._receipt(call_id,{'modelCallId':call_id,'httpStatus':error.http_status,
                'payloadSha256':c.canonical_sha256(payload)},'rejected')
        returned.request_started=started;returned.request_rejected=rejected
        def execute(req):
            remaining=state['deadline']-self.monotonic()
            _require_before_dispatch(remaining>0,'provider_attempt_deadline_reached')
            return self.executor(req,remaining,deadline=state['deadline'])
        c.require(profile.current() is not None,'diagnostic_requires_accounting_profile')
        with profile.context(logicalCallId=operation_id,
                providerScopeKey=c.canonical_sha256({k:self.config[k] for k in
                    ('credentialReferenceSha256','projectId','organizationId')})), \
                accounting.stage('diagnostic.transcription',billing='api',executor_type='production_model'):
            return pipeline.request_json(request,retries=1,response_observer=returned,request_executor=execute)

    @staticmethod
    def usage_resolver(observation):
        return limits.usage_resolver(observation)
