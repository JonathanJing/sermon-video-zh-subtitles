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
from scripts import sermon_transcription_request as transcription
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.source import backend as _source
from scripts import english_source_judge_cache as immutable

JUDGE_LIMITS = ContextVar('source_judge_request_limits', default=None)
METRICS = ('requests', 'wallTimeMs', 'costMicrousd')
LOCK = jobs._digest({'purpose': 'source-budget-v1'})
LEDGER_V2 = 'sermon-source-budget-ledger-v2'
# v3 is v2 plus a measured ``settlement`` on every returned row. v2 stays exactly
# as its frozen readers expect: new code never writes settlement into a v2 ledger,
# and only migrate_to_v3() upgrades one. New ledgers start at v4.
LEDGER_V3 = 'sermon-source-budget-ledger-v3'
LEDGER_V4 = 'sermon-source-budget-ledger-v4'
CONCURRENT_LEDGERS = (LEDGER_V2, LEDGER_V3, LEDGER_V4)
SETTLED_LEDGERS = (LEDGER_V3, LEDGER_V4)
# 'reused': a response another approved budget root already paid for; it costs nothing here.
SETTLEMENT_STATUSES_V3 = {'estimated_upper_bound', 'unknown'}
SETTLEMENT_STATUSES = SETTLEMENT_STATUSES_V3 | {'reused'}


def require(ok, code):
    if not ok:
        raise ValueError(code)


def settlement(identity, response, elapsed):
    """What a returned response actually used, next to the reservation it was booked under.

    The ledger row's ``bounds.costMicrousd`` is the worst-case reservation; until now
    nothing recorded the measured tokens, so every retrospective summed them by hand
    from cached responses. This records the provider's token counts and prices them
    at the requested model's frozen rate (``sermon_provider_limits._cost``). A
    response without usable usage, or for a model without a price, settles as
    ``unknown`` with the reason; nothing is invented and no row is settled to zero.
    """
    usage = response.get('usage') if isinstance(response, dict) else None
    model = identity.get('model') if isinstance(identity, dict) else None
    result = {'costStatus': 'unknown', 'costMicrousd': None, 'usage': None, 'reasonCode': None,
              'requestedModel': model, 'providerModel': response.get('model') if isinstance(response, dict) else None,
              'elapsedSeconds': elapsed, 'priceBasis': 'requested_model_frozen_worst_case_rate', 'invoiceVerified': False}
    if not isinstance(usage, dict):
        return dict(result, reasonCode='missing_provider_usage')
    inputs = usage.get('prompt_tokens', usage.get('input_tokens'))
    outputs = usage.get('completion_tokens', usage.get('output_tokens'))
    if not all(type(value) is int and value >= 0 for value in (inputs, outputs)):
        return dict(result, reasonCode='missing_or_invalid_token_counts')
    details_in = usage.get('prompt_tokens_details') if isinstance(usage.get('prompt_tokens_details'), dict) else {}
    details_out = usage.get('completion_tokens_details') if isinstance(usage.get('completion_tokens_details'), dict) else {}
    result['usage'] = {'inputTokens': inputs, 'outputTokens': outputs,
                       'cachedInputTokens': details_in.get('cached_tokens'),
                       'reasoningTokens': details_out.get('reasoning_tokens'),
                       'totalTokens': usage.get('total_tokens', inputs + outputs)}
    if model not in text_limits.PRICES_USD_PER_MILLION:
        return dict(result, reasonCode='no_frozen_price_for_model')
    return dict(result, costStatus='estimated_upper_bound', costMicrousd=text_limits._cost(model, inputs, outputs))


def saved_settlement(saved):
    """The settlement recorded with a saved response, or one computed from it when the file predates settlement."""
    recorded = saved.get('settlement')
    if isinstance(recorded, dict) and recorded.get('costStatus') in SETTLEMENT_STATUSES:
        return recorded
    return settlement(saved.get('requestIdentity'), saved.get('response'), saved.get('elapsedSeconds'))


def _valid_settlement(value, *, version=LEDGER_V4):
    statuses = SETTLEMENT_STATUSES if version == LEDGER_V4 else SETTLEMENT_STATUSES_V3
    return (isinstance(value, dict) and value.get('costStatus') in statuses
            and (value.get('costStatus') != 'reused' or type(value.get('costMicrousd')) is int and value['costMicrousd'] == 0)
            and (value.get('costMicrousd') is None or type(value['costMicrousd']) is int and value['costMicrousd'] >= 0))


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
    return bounded_source_judge_payload(payload, limits)


def bounded_source_judge_payload(payload, limits):
    """Validate the source judge's pinned schema without widening Layer 2."""
    from scripts import judge_english_source_for_translation as judge
    text_limits.validate_request_limits(limits)
    expected_format = {'type': 'json_schema', 'json_schema': {
        'name': 'english_source_machine_judge', 'strict': True, 'schema': judge._response_schema()}}
    require(type(payload) is dict and payload.get('model') in ('gpt-6-astra', 'gpt-6.1-sol')
            and payload.get('response_format') == expected_format,
            'unsupported_source_judge_payload')
    # Reuse the shared text/message/model/cap validator with its own supported
    # format, then account for the actual schema bytes in the input bound below.
    bounded = text_limits.bounded_payload(dict(payload, response_format={'type': 'json_object'}), limits)
    require(text_limits._input_upper_bound(payload) <= limits['maxInputTokens'], 'source_judge_input_bound_exceeded')
    return dict(bounded, response_format=payload['response_format'])


class SourceBudget:
    def __init__(self, root, authority, *, verify, transport=None, max_concurrent=1, resource_policy=None,
                 reuse_roots=()):
        self.root, self.authority, self.verify = Path(root), authority, verify
        # Earlier budget roots of the same run whose returned responses this root may reuse,
        # as named by its approval. Their ledgers/responses are read-only;
        # operation-lock metadata coordinates cache decisions with source workers.
        self.reuse_roots = tuple(Path(root_).resolve() for root_ in reuse_roots)
        require(all(root_.resolve() != self.root.resolve() for root_ in self.reuse_roots)
                and len({root_.resolve() for root_ in self.reuse_roots}) == len(self.reuse_roots), 'invalid_source_reuse_roots')
        self.transport = transport
        require(type(max_concurrent) is int and 1 <= max_concurrent <= 16, 'invalid_source_concurrency')
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
        # Up to 8 concurrent ASR/judge workers contend for this lock; a 1 s wait made a busy
        # worker fail before reserving and orphan its started marker. Wait up to 30 s instead.
        for attempt in range(3000):
            with jobs._lock(self.root, LOCK) as (_, _, held):
                if held:
                    path = self.root / 'source-budget.json'
                    if path.exists():
                        ledger = jobs._read(path)
                        version = ledger.get('schemaVersion')
                        require(version in ('sermon-source-budget-ledger-v1', *CONCURRENT_LEDGERS)
                                and ledger.get('authority') == self.authority
                                and isinstance(ledger.get('requests'), dict)
                                and set(ledger) == ({'schemaVersion', 'authority', 'requests'} if version not in CONCURRENT_LEDGERS
                                    else {'schemaVersion', 'authority', 'requests', 'maxConcurrent', 'resourcePolicySha256'}
                                        | ({'reuseBudgetRoots'} if version == LEDGER_V4 else set()))
                                and (version != LEDGER_V4 or ledger['reuseBudgetRoots'] == [str(root) for root in self.reuse_roots])
                                and (version not in CONCURRENT_LEDGERS or (ledger['maxConcurrent'] == self.max_concurrent
                                    and ledger['resourcePolicySha256'] == self._resource_identity())), 'source_budget_identity_changed')
                        for operation, row in ledger['requests'].items():
                            require(isinstance(operation, str) and re.fullmatch(r'(asr\.[0-9]{4}|judge\.[a-f0-9]{64})', operation)
                                    and isinstance(row, dict) and row.get('status') in {'returned', 'started_response_unconfirmed', 'live_started'}
                                    and set(row) - {'resourceBinding'} == ({'identitySha256', 'bounds', 'status', 'responseSha256'}
                                        | ({'settlement'} if version in SETTLED_LEDGERS else set())
                                        if row.get('status') == 'returned' else {'identitySha256', 'bounds', 'status', 'dispatchOwner'}
                                        if row.get('status') == 'live_started' and version in CONCURRENT_LEDGERS
                                        else {'identitySha256', 'bounds', 'status'})
                                    and isinstance(row.get('identitySha256'), str)
                                    and re.fullmatch('[a-f0-9]{64}', row['identitySha256'])
                                    and isinstance(row.get('bounds'), dict) and set(row['bounds']) == set(METRICS)
                                    and row['bounds']['requests'] == 1
                                    and all(type(v) is int and 0 < v <= 10**15 for v in row['bounds'].values()),
                                    'source_budget_ledger_corrupt')
                            if row['status'] == 'returned':
                                require(isinstance(row.get('responseSha256'), str)
                                    and re.fullmatch('[a-f0-9]{64}', row['responseSha256']), 'source_budget_ledger_corrupt')
                            if 'settlement' in row:
                                # v3 only, every returned row: measured usage, with whether a price applied.
                                require(_valid_settlement(row['settlement'], version=version), 'source_budget_ledger_corrupt')
                            if (row.get('settlement') or {}).get('costStatus') == 'reused':
                                try:
                                    saved = jobs._read(self._response_path(operation, row['identitySha256']))
                                    provenance = saved['reusedFrom']
                                    require(jobs._digest(saved) == row['responseSha256']
                                            and saved.get('settlement') == row['settlement']
                                            and saved.get('identitySha256') == row['identitySha256']
                                            and jobs._digest(saved.get('requestIdentity')) == row['identitySha256']
                                            and saved.get('reservationBounds') == row['bounds']
                                            and provenance.get('budgetRoot') in ledger['reuseBudgetRoots']
                                            and provenance.get('operation') == operation
                                            and re.fullmatch('[a-f0-9]{64}', provenance.get('responseSha256', ''))
                                            and re.fullmatch('[a-f0-9]{64}', provenance.get('sourceAuthoritySha256', ''))
                                            and provenance.get('sourceLedgerVersion') in
                                                ('sermon-source-budget-ledger-v1', *CONCURRENT_LEDGERS)
                                            and _valid_settlement(provenance.get('originalSettlement'), version=LEDGER_V3),
                                            'source_reused_provenance_changed')
                                except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                                    raise ValueError('source_reused_provenance_changed') from error
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
                        if version not in CONCURRENT_LEDGERS:
                            # Serial v1 jobs upgrade conservatively. Unknown rows
                            # stay unknown; explicit migration is required before
                            # changing concurrency or attaching a broker.
                            require(self.max_concurrent == 1 and self.resource_policy is None,
                                    'source_budget_v1_explicit_migration_required')
                            ledger.update(schemaVersion=LEDGER_V2, maxConcurrent=1, resourcePolicySha256=None)
                    else:
                        ledger = {'schemaVersion': LEDGER_V4, 'authority': self.authority, 'requests': {},
                                  'maxConcurrent': self.max_concurrent, 'resourcePolicySha256': self._resource_identity(),
                                  'reuseBudgetRoots': [str(root) for root in self.reuse_roots]}
                    yield ledger, path
                    return
            time.sleep(.01)
        raise ValueError('source_budget_busy')

    def _resource_identity(self):
        if self.resource_policy is None:
            return None
        from scripts.sermon_unified import resources
        return resources._identity(self.resource_policy)

    def _operation_path(self, operation, *, root=None):
        directory = (self.root if root is None else root) / 'live-owners'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        return directory / (jobs._digest(operation) + '.lock')

    @contextmanager
    def _operation_fences(self, operation):
        # The same per-operation OS locks used by source workers must span the
        # cache-miss decision, local reservation, dispatch and durable receipt.
        # Source business artifacts remain read-only. A missing lock file is
        # coordination metadata, never a reservation or ledger migration.
        handles = []
        try:
            for root in sorted({self.root.resolve(), *self.reuse_roots}, key=str):
                handle = self._operation_path(operation, root=root).open('a')
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    handle.close()
                    raise ValueError('source_operation_live') from None
                handles.append(handle)
            yield
        finally:
            for handle in reversed(handles):
                fcntl.flock(handle, fcntl.LOCK_UN)
                handle.close()

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

    def _reusable(self, operation, fingerprint):
        """Inspect approved roots read-only; a known or uncertain call is never a cache miss."""
        candidate = None
        for root in self.reuse_roots:
            try:
                ledger = jobs._read(root / 'source-budget.json')
                require(isinstance(ledger, dict) and ledger.get('schemaVersion') in
                        ('sermon-source-budget-ledger-v1', *CONCURRENT_LEDGERS)
                        and isinstance(ledger.get('requests'), dict)
                        and isinstance(ledger.get('authority'), dict)
                        and set(ledger['authority']) == {'approvalSha256', 'globalBounds', 'requestLimits'}
                        and re.fullmatch('[a-f0-9]{64}', ledger['authority'].get('approvalSha256', ''))
                        and isinstance(ledger['authority'].get('globalBounds'), dict)
                        and set(ledger['authority']['globalBounds']) == set(METRICS)
                        and all(type(value) is int and 0 < value <= 10**15
                                for value in ledger['authority']['globalBounds'].values()),
                        'source_reuse_ledger_corrupt')
                row = ledger['requests'].get(operation)
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                raise ValueError('source_reuse_ledger_reconciliation_required') from error
            if row is None:
                continue
            require(isinstance(row, dict) and isinstance(row.get('identitySha256'), str)
                    and re.fullmatch('[a-f0-9]{64}', row['identitySha256']), 'source_reuse_ledger_reconciliation_required')
            require(row['identitySha256'] == fingerprint, 'source_reuse_identity_changed')
            require(row.get('status') == 'returned', 'source_provider_outcome_unknown')
            path = root / 'responses' / (jobs._digest(operation) + '-' + fingerprint + '.json')
            if not path.exists():
                path = root / 'responses' / (fingerprint + '.json')
            try:
                saved = jobs._read(path)
                valid = (isinstance(saved, dict) and saved.get('identitySha256') == fingerprint
                         and jobs._digest(saved.get('requestIdentity')) == fingerprint
                         and jobs._digest(saved) == row.get('responseSha256')
                         and saved.get('reservationBounds') == row.get('bounds')
                         and isinstance(saved.get('response'), dict)
                         and (ledger['schemaVersion'] not in SETTLED_LEDGERS or
                              _valid_settlement(row.get('settlement'), version=ledger['schemaVersion'])
                              and row['settlement'] == saved_settlement(saved)))
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                raise ValueError('source_reuse_response_reconciliation_required') from error
            require(valid, 'source_reuse_response_reconciliation_required')
            # Approving an intermediate root does not approve its paid ancestor.
            # Only a direct paid receipt may become a new reuse provenance root.
            require('reusedFrom' not in saved
                    and saved_settlement(saved).get('costStatus') != 'reused'
                    and (row.get('settlement') or {}).get('costStatus') != 'reused',
                    'source_reuse_requires_direct_paid_root')
            # Legacy v1/v2 rows have no row-level settlement validation. Check
            # the saved/computed paid settlement before freezing it as v4 reuse
            # provenance; a malformed recorded value must not be recomputed away.
            require(_valid_settlement(saved_settlement(saved), version=LEDGER_V3)
                    and ('settlement' not in saved
                         or _valid_settlement(saved['settlement'], version=LEDGER_V3)),
                    'source_reuse_response_reconciliation_required')
            # Check every root before returning: a later unknown/damaged matching
            # row must not be hidden by an earlier successful cache candidate.
            if candidate is None:
                candidate = root, saved, row, ledger
        # Source business state is read-only: there is no durable cross-root
        # paid reservation on a miss. A later source/destination could otherwise
        # pay again after our fence is released, so reuse never buys a new call.
        require(candidate is not None, 'source_reuse_operation_missing')
        return candidate

    def returned(self, operation, identity):
        """Whether the ledger already holds this operation's returned response for exactly this identity.

        Read-only: a caller uses it to tell a free replay from a new paid request before reserving."""
        fingerprint = jobs._digest(identity)
        with self._locked() as (ledger, _):
            row = ledger['requests'].get(operation)
            return row is not None and row['status'] == 'returned' and row['identitySha256'] == fingerprint

    def call(self, *, operation, identity, bounds, request, api_key, content_type, endpoint):
        self.verify()
        require(isinstance(operation, str) and re.fullmatch(r'(asr\.[0-9]{4}|judge\.[a-f0-9]{64})', operation),
                'invalid_source_operation')
        with self._operation_fences(operation):
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
            require(not self.reuse_roots or ledger['schemaVersion'] == LEDGER_V4,
                    'source_budget_v4_explicit_migration_required')
            reusable = self._reusable(operation, fingerprint) if self.reuse_roots else None
            if reusable is not None:
                # Already paid under another approved root of this run: copy it here at no cost.
                source_root, source_saved, source_row, source_ledger = reusable
                previous_settlement = saved_settlement(source_saved)
                saved = {'identitySha256': fingerprint, 'requestIdentity': identity, 'response': source_saved['response'],
                         'modelCallId': source_saved.get('modelCallId'), 'elapsedSeconds': 0.0,
                         'reservationBounds': bounds, 'invoiceVerified': False,
                         'reusedFrom': {'budgetRoot': str(source_root), 'operation': operation,
                                        'responseSha256': source_row['responseSha256'],
                                        'originalSettlement': previous_settlement,
                                        'sourceAuthoritySha256': jobs._digest(source_ledger['authority']),
                                        'sourceLedgerVersion': source_ledger['schemaVersion']},
                         'settlement': {'costStatus': 'reused', 'costMicrousd': 0,
                                        'usage': previous_settlement.get('usage'), 'reasonCode': 'reused_paid_response',
                                        'requestedModel': previous_settlement.get('requestedModel'),
                                        'providerModel': previous_settlement.get('providerModel'),
                                        'elapsedSeconds': 0.0, 'priceBasis': 'reused_from_approved_budget_root',
                                        'invoiceVerified': False}}
                response_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                immutable._atomic(response_path, saved)
                ledger['requests'][operation] = {'identitySha256': fingerprint, 'bounds': bounds, 'status': 'returned',
                                                 'responseSha256': jobs._digest(saved), 'settlement': saved['settlement']}
                jobs._persist(path, ledger)
                return saved['response']
            require(self.transport is not None or (isinstance(api_key, str) and bool(api_key)
                    and '\n' not in api_key and '\r' not in api_key), 'OPENAI_API_KEY_is_not_configured')
            # Unknown outcomes stop the source lane; they do not buy a fresh
            # operation ID or allow later work to conceal a missing chunk.
            require(all(row['status'] != 'started_response_unconfirmed' for row in ledger['requests'].values()),
                    'source_provider_outcome_unknown')
            require(sum(row['status'] == 'live_started' for row in ledger['requests'].values()) < self.max_concurrent,
                    'source_concurrency_busy')
            # A reused response reserved nothing and cost nothing, so it does not count against the cap.
            used = {key: sum(row['bounds'][key] for row in ledger['requests'].values()
                             if (row.get('settlement') or {}).get('costStatus') != 'reused') for key in METRICS}
            require(all(used[key] + bounds[key] <= self.authority['globalBounds'][key] for key in METRICS),
                    'source_budget_exhausted')
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
                     'reservationBounds': bounds, 'invoiceVerified': False,
                     'settlement': settlement(identity, response, elapsed)}
            immutable._atomic(response_path, saved)
            self.verify()
            with self._locked() as (ledger, path):
                row = ledger['requests'][operation]
                require(row['identitySha256'] == fingerprint, 'source_call_binding_changed')
                row.update(status='returned', responseSha256=jobs._digest(saved))
                if ledger['schemaVersion'] in SETTLED_LEDGERS:
                    row['settlement'] = saved['settlement']
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
        return _source.current().provider.request_json(req, retries=1, response_observer=returned,
            request_executor=spark_admission.SessionBoundCaller(
                lambda r: http.execute(r, bounds['wallTimeMs'] / 1000), purpose='source-audio-api', requires_spark=False, outcome_guarded=True))

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
                if ledger['schemaVersion'] in SETTLED_LEDGERS:
                    # The crash fell between saving the response and booking it; book what it used too.
                    row['settlement'] = saved_settlement(saved)
                    require(_valid_settlement(row['settlement'], version=ledger['schemaVersion']),
                            'source_budget_ledger_corrupt')
                jobs._persist(ledger_path, ledger)
            self._release_resource(row)
        return {'status': 'returned_response_reconciled', 'operation': operation,
                'modelCalls': 0, 'humanApproval': False, 'reservationReleased': False}

    def migrate_to_v3(self):
        """Explicitly upgrade a v2 ledger to v3, settling every returned row from its saved response.

        A v2 ledger is never widened in place: a run resumed with its frozen
        implementation keeps reading v2. This is the one path to v3. It refuses
        while a dispatch is live or when a saved response no longer matches its
        booked hash, and changes nothing in that case. No provider is called.
        """
        self.verify()
        with self._locked() as (ledger, path):
            version = ledger['schemaVersion']
            if version == LEDGER_V3:
                return {'status': 'already_v3', 'settledRows': 0}
            require(version == LEDGER_V2 and path.exists(), 'source_budget_v2_ledger_required')
            rows = ledger['requests']
            require(all(row['status'] != 'live_started' for row in rows.values()), 'source_operation_live')
            settled = {}
            for operation, row in rows.items():
                if row['status'] != 'returned':
                    continue
                response_path = self._response_path(operation, row['identitySha256'])
                require(response_path.is_file(), 'source_returned_response_required')
                saved = jobs._read(response_path)
                require(saved.get('identitySha256') == row['identitySha256']
                        and jobs._digest(saved) == row['responseSha256'], 'source_response_identity_changed')
                settled[operation] = saved_settlement(saved)
                require(_valid_settlement(settled[operation], version=LEDGER_V3), 'source_budget_ledger_corrupt')
            for operation, value in settled.items():
                rows[operation]['settlement'] = value
            ledger['schemaVersion'] = LEDGER_V3
            jobs._persist(path, ledger)
        return {'status': 'migrated', 'from': LEDGER_V2, 'to': LEDGER_V3, 'settledRows': len(settled),
                'unknownCostRows': sum(value['costStatus'] == 'unknown' for value in settled.values()),
                'modelCalls': 0}

    def migrate_to_v4(self):
        """Explicit atomic v2/v3 upgrade, retaining bounds/outcomes and binding reuse roots.

        Source roots are never migrated. No provider is called, no unknown row is
        cleared, and a missing/damaged returned receipt leaves the ledger intact.
        """
        self.verify()
        with self._locked() as (ledger, path):
            version = ledger['schemaVersion']
            if version == LEDGER_V4:
                return {'status': 'already_v4', 'modelCalls': 0}
            require(version in (LEDGER_V2, LEDGER_V3) and path.exists(), 'source_budget_old_ledger_required')
            require(all(row['status'] != 'live_started' for row in ledger['requests'].values()), 'source_operation_live')
            settled = {}
            for operation, row in ledger['requests'].items():
                if row['status'] != 'returned':
                    continue
                try:
                    saved = jobs._read(self._response_path(operation, row['identitySha256']))
                except (OSError, ValueError, TypeError) as error:
                    raise ValueError('source_response_identity_changed') from error
                require(saved.get('identitySha256') == row['identitySha256']
                        and jobs._digest(saved.get('requestIdentity')) == row['identitySha256']
                        and saved.get('reservationBounds') == row['bounds']
                        and jobs._digest(saved) == row['responseSha256'], 'source_response_identity_changed')
                value = saved_settlement(saved)
                require(_valid_settlement(value, version=LEDGER_V3)
                        and (version != LEDGER_V3 or row['settlement'] == value), 'source_budget_ledger_corrupt')
                settled[operation] = value
            for operation, value in settled.items():
                ledger['requests'][operation]['settlement'] = value
            ledger.update(schemaVersion=LEDGER_V4, reuseBudgetRoots=[str(root) for root in self.reuse_roots])
            jobs._persist(path, ledger)
        return {'status': 'migrated', 'from': version, 'to': LEDGER_V4, 'settledRows': len(settled), 'modelCalls': 0}

    def transcribe(self, operation, audio_bytes, audio_sha256, api_key):
        prepared = transcription.build_request(audio_bytes, audio_sha256)
        return self.call(operation=operation, identity=prepared['identity'], bounds=prepared['budgetBounds'],
                         request=prepared['body'], api_key=api_key, content_type=prepared['contentType'],
                         endpoint='https://api.openai.com/v1/audio/transcriptions')

    def judge(self, api_key, payload):
        expected = bounded_source_judge_payload(payload, self.authority['requestLimits'])
        require(payload == expected and 'max_completion_tokens' in payload, 'source_judge_not_bounded')
        limits = self.authority['requestLimits']
        inputs = text_limits._input_upper_bound(payload)
        require(inputs <= limits['maxInputTokens'], 'source_judge_input_bound_exceeded')
        bounds = {'requests': 1, 'wallTimeMs': limits['wallTimeMs'],
                  'costMicrousd': text_limits._cost(payload['model'], inputs, limits['maxCompletionTokens'])}
        return self.call(operation='judge.' + jobs._digest(payload), identity=payload, bounds=bounds,
                         request=json.dumps(payload, ensure_ascii=False).encode(), api_key=api_key,
                         content_type='application/json', endpoint='https://api.openai.com/v1/chat/completions')
