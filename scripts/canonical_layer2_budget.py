"""Explicit L2 budget authority, shared conservative ledger and capped transport.

Frozen provider rates are planning upper-bound assumptions, never invoice proof.
No missing/unknown reservation is released or retried automatically.
"""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import time
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
LEDGER_SCOPES = {SCHEMA: 'run', LOCALE_SCHEMA: 'locale'}
# A locale shard holds a whole sermon plus repairs: about 4,900 reservations.
LOCALE_LEDGER_MAX_BYTES = 8 * 1024 * 1024
# Busy only ever delays admission, settlement or a replayed result; it never
# repeats an external request, so waiting longer is safe under group concurrency.
LEDGER_BUSY_WAIT_SECONDS = 120


def sha(path):
    return hashlib.sha256(_safe_path(Path(path)).read_bytes()).hexdigest()


def require(ok, code):
    if not ok:
        raise ValueError(code)


def load_authorization(config, path, code_identity, expected_sha=None):
    path = _safe_path(Path(path).absolute())
    actual_sha = sha(path)
    require(expected_sha is None or expected_sha == actual_sha, 'budget_authorization_changed')
    value = jobs._read(path)
    base_keys = {'schemaVersion', 'productionRunId', 'configurationSha256', 'codeIdentitySha256',
                 'requestLimits', 'authority', 'approvalReceipt'}
    require(isinstance(value, dict) and value.get('schemaVersion') in LEDGER_SCOPES
            and set(value) == (base_keys if value['schemaVersion'] == SCHEMA else base_keys | {'ledgerScope'}),
            'invalid_budget_authorization')
    scope = LEDGER_SCOPES[value['schemaVersion']]
    require(scope == 'run' or value['ledgerScope'] == 'locale', 'invalid_budget_authorization')
    require(value['productionRunId'] == config.run_id
            and value['configurationSha256'] == config.sha256
            and value['codeIdentitySha256'] == code_identity, 'budget_execution_binding_changed')
    selected = limits.validate_request_limits(value['requestLimits'])
    authority = budget._authority(value['authority'])
    receipt_path = _safe_path(path.parent / value['approvalReceipt'])
    receipt = jobs._read(receipt_path)
    root = config.job_root.parent / f'.{config.job_root.name}.layer2-budget'
    expected = {'productionRunId': config.run_id, 'configurationSha256': config.sha256,
                'codeIdentitySha256': code_identity, 'budgetRoot': str(root),
                'requestLimits': selected, 'globalBounds': authority['globalBounds'],
                'unitBounds': authority['unitBounds'], 'limits': authority['limits']}
    if scope == 'locale':
        expected['ledgerScope'] = 'locale'
    require(sha(receipt_path) == authority['approvalSha256']
            and receipt.get('schemaVersion') == 'sermon-canonical-layer2-budget-approval-v1'
            and receipt.get('binding') == expected and receipt.get('humanApproval') is True
            and receipt.get('decision') == 'approved' and receipt.get('operatorEvidence')
            and receipt.get('reviewedBy') and receipt.get('reviewedAt'), 'budget_approval_not_bound')
    return {'path': path, 'sha256': actual_sha, 'value': value, 'root': root, 'limits': selected,
            'scope': scope}


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
    def __init__(self, authorization, config, source, anchor, policy, *, transport=None):
        self.auth, self.config, self.policy = authorization, config, policy
        self.source, self.anchor = source, anchor
        require(authorization.get('scope', 'run') == 'run' or policy['targetLocale'] in config.lanes,
                'budget_locale_not_registered')
        self.root = ledger_root(authorization, policy['targetLocale'])
        self.store = budget.BudgetStore(
            self.root, authorization['value']['authority'],
            max_ledger_bytes=LOCALE_LEDGER_MAX_BYTES if authorization.get('scope') == 'locale' else None)
        self.transport = transport

    def __call__(self, key, payload):
        from scripts.sermon_openai_runtime import project_headers
        selected_headers = project_headers(key)
        load_authorization(self.config, self.auth['path'],
                           self.auth['value']['codeIdentitySha256'], self.auth['sha256'])
        from scripts.strict_budget_capability import require_bounded_api_payload
        require_bounded_api_payload(payload, self.auth['limits'], surface='canonical_api')
        capped = limits.bounded_payload(payload, self.auth['limits'])
        require(capped == payload, 'model_payload_must_be_bounded_before_cache_identity')
        fingerprint = jobs._digest(payload)
        roles = [name for name in ('translator', 'reviewer')
                 if payload['model'] == self.policy[name]['model']
                 and payload['reasoning_effort'] == self.policy[name]['reasoningEffort']]
        require(len(roles) == 1, 'budgeted_model_role_ambiguous')
        role = roles[0]
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
                      'modelCallId': attempt_id, 'priceAssumptionVersion': limits.PRICE_ASSUMPTION_VERSION,
                      'invoiceVerified': False}
            jobs._persist(returned, record)
            observed.append(record)
        # The trusted injected transport is only a local test seam. Production
        # uses the existing isolated, single-attempt, wall-deadline HTTP executor.
        if self.transport is None:
            request = urllib.request.Request('https://api.openai.com/v1/chat/completions',
                data=json.dumps(payload).encode(), method='POST',
                headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                         **selected_headers})
            request.accounting_model = payload['model']
            request.accounting_settings = pipeline.request_metadata(payload)
            response = pipeline.request_json(request, retries=1, response_observer=preserve,
                request_executor=lambda req: http.execute(req, self.auth['limits']['wallTimeMs'] / 1000))
        else:
            response = self.transport(key, payload)
        elapsed_ms = int((time.monotonic() - start) * 1000) + 1
        record = observed[0] if observed else {'payloadSha256': fingerprint, 'response': response,
                  'reservationId': reservation['reservationId'], 'elapsedMs': elapsed_ms,
                  'priceAssumptionVersion': limits.PRICE_ASSUMPTION_VERSION, 'invoiceVerified': False}
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
