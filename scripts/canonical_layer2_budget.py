"""Explicit L2 budget authority, shared conservative ledger and capped transport.

Frozen provider rates are planning upper-bound assumptions, never invoice proof.
No missing/unknown reservation is released or retried automatically.
"""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
import re
from pathlib import Path
import time
import urllib.error
import urllib.request

from scripts import sermon_provider_limits as limits
from scripts import sermon_provider_http as http
from scripts import sermon_pipeline as pipeline
from scripts import sermon_review_budget as budget
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_release_workflow import _safe_path

CURRENT_LIMITS = ContextVar('canonical_layer2_request_limits', default=None)
SCHEMA = 'sermon-canonical-layer2-budget-authorization-v1'
# v2 shards the ledger by locale: each locale gets its own BudgetStore under the
# run's budget root, and every bound in the authority applies per locale. The
# approval binding names that scope, so a person signs per-locale amounts.
LOCALE_SCHEMA = 'sermon-canonical-layer2-budget-authorization-v2'
RUNTIME_SCHEMA = 'sermon-canonical-layer2-budget-authorization-v3'
RUNTIME_APPROVAL_SCHEMA = 'sermon-canonical-layer2-budget-approval-v2'
LEDGER_SCOPES = {SCHEMA: 'run', LOCALE_SCHEMA: 'locale', RUNTIME_SCHEMA: None}
# A locale shard holds a whole sermon plus repairs: about 4,900 reservations.
LOCALE_LEDGER_MAX_BYTES = 8 * 1024 * 1024
# Busy only ever delays admission, settlement or a replayed result; it never
# repeats an external request, so waiting longer is safe under group concurrency.
LEDGER_BUSY_WAIT_SECONDS = 120
# These statuses arrive without a completion document: OpenAI's own 500/502/503/504,
# and Cloudflare's 520-523 when the origin answered with nothing usable (the
# 2026-10-11 run lost four whole-sermon locale jobs to single 503s and one 520).
# 524 (origin timeout) is left out: the origin may still have completed the call.
RETRYABLE_PROVIDER_STATUSES = frozenset({500, 502, 503, 504, 520, 521, 522, 523})
PROVIDER_RETRY_ATTEMPTS = 5


def execute_with_provider_retry(req, wall_seconds, *, executor=None, sleep=time.sleep):
    """Run the isolated single-request executor, retrying 5xx error documents within the wall deadline.

    The strict transport treats any HTTP error it sees as outcome-unknown. A 5xx
    reply is an error document, not a completion, so it is retried here before the
    transport sees it; the reservation stays live and no second completion can be
    produced for the same attempt."""
    executor = executor or http.execute
    deadline = time.monotonic() + wall_seconds
    for attempt in range(PROVIDER_RETRY_ATTEMPTS):
        try:
            return executor(req, wall_seconds, deadline=deadline)
        except urllib.error.HTTPError as error:
            wait = 2 ** attempt
            if (error.code not in RETRYABLE_PROVIDER_STATUSES or attempt == PROVIDER_RETRY_ATTEMPTS - 1
                    or time.monotonic() + wait >= deadline):
                raise
            sleep(wait)


def sha(path):
    return hashlib.sha256(_safe_path(Path(path)).read_bytes()).hexdigest()


def require(ok, code):
    if not ok:
        raise ValueError(code)


def selected_runtime_identity(key=None):
    from scripts.sermon_openai_runtime import selected_route
    route = selected_route()
    require(route is not None, 'layer2_runtime_requires_explicit_launcher')
    actual = os.environ.get('OPENAI_API_KEY')
    require(isinstance(actual, str) and bool(actual) and (key is None or key == actual),
            'layer2_runtime_credential_changed')
    return {'openaiRoute': route, 'credentialSha256': hashlib.sha256(actual.encode()).hexdigest()}


def validate_runtime_identity(value):
    from scripts.sermon_openai_runtime import safe_route
    require(type(value) is dict and set(value) == {'openaiRoute', 'credentialSha256'}
            and safe_route(value['openaiRoute']) is not None
            and safe_route(value['openaiRoute']) == value['openaiRoute']
            and isinstance(value['credentialSha256'], str)
            and re.fullmatch('[a-f0-9]{64}', value['credentialSha256']) is not None,
            'invalid_layer2_runtime_identity')
    return value


def verify_runtime(authorization, key=None):
    frozen = authorization.get('runtimeIdentity')
    if frozen is not None:
        require(selected_runtime_identity(key) == frozen, 'layer2_runtime_identity_changed')
    return frozen


def load_authorization(config, path, code_identity, expected_sha=None):
    path = _safe_path(Path(path).absolute())
    actual_sha = sha(path)
    require(expected_sha is None or expected_sha == actual_sha, 'budget_authorization_changed')
    value = jobs._read(path)
    base_keys = {'schemaVersion', 'productionRunId', 'configurationSha256', 'codeIdentitySha256',
                 'requestLimits', 'authority', 'approvalReceipt'}
    extra = ({'ledgerScope', 'runtimeIdentity'} if isinstance(value, dict) and value.get('schemaVersion') == RUNTIME_SCHEMA
             else set() if isinstance(value, dict) and value.get('schemaVersion') == SCHEMA else {'ledgerScope'})
    require(isinstance(value, dict) and value.get('schemaVersion') in LEDGER_SCOPES
            and set(value) == base_keys | extra,
            'invalid_budget_authorization')
    runtime = (validate_runtime_identity(value['runtimeIdentity']) if value['schemaVersion'] == RUNTIME_SCHEMA else None)
    scope = value['ledgerScope'] if runtime is not None else LEDGER_SCOPES[value['schemaVersion']]
    require(scope in ('run', 'locale') and (scope == 'run' or value['ledgerScope'] == 'locale'), 'invalid_budget_authorization')
    require(value['productionRunId'] == config.run_id
            and value['configurationSha256'] == config.sha256
            and value['codeIdentitySha256'] == code_identity, 'budget_execution_binding_changed')
    selected = limits.validate_request_limits(value['requestLimits'])
    authority = budget._authority(value['authority'])
    receipt_path = _safe_path(path.parent / value['approvalReceipt'])
    receipt = jobs._read(receipt_path)
    root = budget_root(config)
    expected = {'productionRunId': config.run_id, 'configurationSha256': config.sha256,
                'codeIdentitySha256': code_identity, 'budgetRoot': str(root),
                'requestLimits': selected, 'globalBounds': authority['globalBounds'],
                'unitBounds': authority['unitBounds'], 'limits': authority['limits']}
    if scope == 'locale' or runtime is not None:
        expected['ledgerScope'] = scope
    if runtime is not None:
        expected['runtimeIdentity'] = runtime
    require(sha(receipt_path) == authority['approvalSha256']
            and receipt.get('schemaVersion') == (RUNTIME_APPROVAL_SCHEMA if runtime is not None else 'sermon-canonical-layer2-budget-approval-v1')
            and receipt.get('binding') == expected and receipt.get('humanApproval') is True
            and receipt.get('decision') == 'approved' and receipt.get('operatorEvidence')
            and receipt.get('reviewedBy') and receipt.get('reviewedAt'), 'budget_approval_not_bound')
    return {'path': path, 'sha256': actual_sha, 'value': value, 'root': root, 'limits': selected,
            'scope': scope, **({'runtimeIdentity': runtime} if runtime is not None else {})}


def budget_root(config):
    """Keep a Gate 4 revision's new authority separate from the passed chain's ledger."""
    base = config.job_root.parent / f'.{config.job_root.name}.layer2-budget'
    if (getattr(config, 'auto_repair', None) or {}).get('backTranslationQc'):
        return base.with_name(base.name + '-qc-' + config.sha256)
    return base


def ledger_root(authorization, locale):
    """The BudgetStore root for one locale: the run root, or its locale shard."""
    if authorization.get('scope', 'run') == 'run':
        return authorization['root']
    require(isinstance(locale, str) and locale and '/' not in locale and not locale.startswith('.'),
            'invalid_budget_locale')
    return authorization['root'] / locale


@contextmanager
def request_limits(selected):
    token = CURRENT_LIMITS.set(selected)
    try:
        yield
    finally:
        CURRENT_LIMITS.reset(token)


class BudgetedCaller:
    def __init__(self, authorization, config, source, anchor, policy, *, transport=None, claude_transport=None):
        self.auth, self.config, self.policy = authorization, config, policy
        verify_runtime(authorization)
        if authorization.get('runtimeIdentity') is not None:
            # A QC repair has a new, configuration-bound budget authorization but
            # carries unchanged groups from its previous round. Cache identity
            # follows the actual route/key; verify_execution still validates the
            # current authorization on every cache hit and provider dispatch.
            self.execution_identity = {'schemaVersion': 'openai-layer2-budget-transport-identity-v3',
                'backend': 'openai_api', 'runtimeIdentity': authorization['runtimeIdentity']}
        self.source, self.anchor = source, anchor
        require(authorization.get('scope', 'run') == 'run' or policy['targetLocale'] in config.lanes,
                'budget_locale_not_registered')
        self.root = ledger_root(authorization, policy['targetLocale'])
        self.store = budget.BudgetStore(
            self.root, authorization['value']['authority'],
            max_ledger_bytes=LOCALE_LEDGER_MAX_BYTES if authorization.get('scope') == 'locale' else None)
        self.transport = transport
        # Subscription-login Claude CLI for the translator only; never the reviewer.
        self.claude_transport = claude_transport

    def verify_execution(self, key):
        load_authorization(self.config, self.auth['path'], self.auth['value']['codeIdentitySha256'], self.auth['sha256'])
        verify_runtime(self.auth, key)

    def __call__(self, key, payload):
        self.verify_execution(key)
        from scripts.sermon_openai_runtime import project_headers
        selected_headers = project_headers(key)
        load_authorization(self.config, self.auth['path'],
                           self.auth['value']['codeIdentitySha256'], self.auth['sha256'])
        from scripts.strict_budget_capability import require_bounded_api_payload
        require_bounded_api_payload(payload, self.auth['limits'], surface='canonical_api')
        capped = limits.bounded_payload(payload, self.auth['limits'])
        require(capped == payload, 'model_payload_must_be_bounded_before_cache_identity')
        fingerprint = jobs._digest({'payload': payload, 'runtimeIdentity': self.auth['runtimeIdentity']}
                                   if self.auth.get('runtimeIdentity') is not None else payload)
        roles = [name for name in ('translator', 'reviewer')
                 if payload['model'] == self.policy[name]['model']
                 and payload['reasoning_effort'] == self.policy[name]['reasoningEffort']]
        require(len(roles) == 1, 'budgeted_model_role_ambiguous')
        role = roles[0]
        # Configuration errors are not paid unknown outcomes. Validate the
        # selected transport before reserving or marking any budget request.
        if payload['model'] in limits.CLAUDE_MODELS:
            require(self.transport is None and self.claude_transport is not None and role == 'translator'
                    and payload['model'] == self.claude_transport.model
                    and payload['reasoning_effort'] == self.claude_transport.effort, 'claude_transport_required')
        # Separate immutable request chains prevent content revisions from
        # resetting one shared global ledger. Each exact payload is one operation.
        identity = budget.chain_identity({
            'sourceIdentitySha256': self.source['downstreamInvalidationKey'],
            'sourcePackageSha256': jobs._digest(self.source), 'anchorSha256': jobs._digest(self.anchor),
            'policySha256': jobs._digest(self.policy), 'rubricSha256': jobs._digest({'role': role}),
            'targetLocale': self.policy['targetLocale'],
            'workUnitId': 'l2.' + self.policy['targetLocale'] + '.call-' + fingerprint})
        bounds = limits.request_bounds(payload, self.auth['limits'])
        reservation = self._ledger(lambda: self.store.reserve(identity, operation_id='model.' + fingerprint,
            kind='initial_generation' if role == 'translator' else 'review', revision_id='initial',
            revision_number=1, input_sha256=fingerprint, bounds=bounds))
        require(reservation['created'], 'budget_reconciliation_required')
        self._ledger(lambda: self.store.mark_request(reservation['reservationId']))
        start = time.monotonic()
        returned = self.root / 'responses' / (fingerprint + '.json')
        returned.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        observed = []
        def preserve(response, attempt_id, elapsed):
            record = {'payloadSha256': fingerprint, 'response': response,
                      'reservationId': reservation['reservationId'], 'elapsedMs': int(elapsed * 1000) + 1,
                      'modelCallId': attempt_id, 'priceAssumptionVersion': limits.PRICE_ASSUMPTION_VERSION_BY_MODEL.get(payload['model'], limits.PRICE_ASSUMPTION_VERSION),
                      'invoiceVerified': False}
            jobs._persist(returned, record)
            observed.append(record)
        # The trusted injected transport is only a local test seam. Production
        # uses the existing isolated, single-attempt, wall-deadline HTTP executor.
        if payload['model'] in limits.CLAUDE_MODELS:
            # Claude is reachable only as the frozen translator, through its subscription CLI.
            from scripts.claude_layer2_transport import chat_envelope
            response = chat_envelope(self.claude_transport('', payload, role=role), payload['model'])
        elif self.transport is None:
            request = urllib.request.Request('https://api.openai.com/v1/chat/completions',
                data=json.dumps(payload).encode(), method='POST',
                headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                         **selected_headers})
            request.accounting_model = payload['model']
            request.accounting_settings = pipeline.request_metadata(payload)
            response = pipeline.request_json(request, retries=1, response_observer=preserve,
                request_executor=lambda req: execute_with_provider_retry(req, self.auth['limits']['wallTimeMs'] / 1000))
        else:
            response = self.transport(key, payload)
        elapsed_ms = int((time.monotonic() - start) * 1000) + 1
        record = observed[0] if observed else {'payloadSha256': fingerprint, 'response': response,
                  'reservationId': reservation['reservationId'], 'elapsedMs': elapsed_ms,
                  'priceAssumptionVersion': limits.PRICE_ASSUMPTION_VERSION_BY_MODEL.get(payload['model'], limits.PRICE_ASSUMPTION_VERSION), 'invoiceVerified': False}
        jobs._persist(returned, record)
        usage = response.get('usage', {})
        inputs, outputs = usage.get('prompt_tokens'), usage.get('completion_tokens')
        require(type(inputs) is int and inputs >= 0 and type(outputs) is int and outputs >= 0
                and isinstance(response.get('model'), str) and response['model'].startswith(payload['model']),
                'budget_usage_missing_reconciliation_required')
        self._ledger(lambda: self.store.record_result(reservation['reservationId'], {
            'executionStatus': 'succeeded', 'contentStatus': 'not_assessed',
            'receiptSha256': jobs._digest(record),
            'usage': {'requests': 1, 'inputTokens': inputs, 'outputTokens': outputs,
                      'wallTimeMs': elapsed_ms,
                      'costMicrousd': limits._cost(payload['model'], inputs, outputs)}}))
        return response

    @staticmethod
    def _ledger(operation):
        deadline = time.monotonic() + LEDGER_BUSY_WAIT_SECONDS
        delay = 0.01
        while True:
            try:
                return operation()
            except ValueError as exc:
                if str(exc) != 'budget_store_busy' or time.monotonic() >= deadline:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 0.5)
