"""Explicit L2 budget authority, shared conservative ledger and capped transport.

Frozen provider rates are planning upper-bound assumptions, never invoice proof.
No missing/unknown reservation is released or retried automatically.
"""
from __future__ import annotations
import copy
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

from ..compute import provider_limits as limits
from . import backend as _text
from . import policy_preview


class _HostCollaborator:
    """A host collaborator looked up at each call, so the package imports without a host."""
    def __init__(self, get):
        self._get = get

    def __getattr__(self, name):
        return getattr(self._get(), name)


jobs = _HostCollaborator(lambda: _text.current().core.jobs)
budget = _HostCollaborator(lambda: _text.current().unmoved.review_budget())  # review/ owns the D5 ledger
pipeline = _HostCollaborator(lambda: _text.current().provider)              # request_json, request_metadata


def _safe_path(path):
    return _text.current().core.safe_path(path)

CURRENT_LIMITS = ContextVar('canonical_layer2_request_limits', default=None)
SCHEMA = 'sermon-canonical-layer2-budget-authorization-v1'
# v2 shards the ledger by locale: each locale gets its own BudgetStore under the
# run's budget root, and every bound in the authority applies per locale. The
# approval binding names that scope, so a person signs per-locale amounts.
LOCALE_SCHEMA = 'sermon-canonical-layer2-budget-authorization-v2'
RUNTIME_SCHEMA = 'sermon-canonical-layer2-budget-authorization-v3'
RUNTIME_APPROVAL_SCHEMA = 'sermon-canonical-layer2-budget-approval-v2'
REUSE_SCHEMA = 'sermon-canonical-layer2-budget-authorization-v4'
REUSE_APPROVAL_SCHEMA = 'sermon-canonical-layer2-budget-approval-v3'
LEDGER_SCOPES = {SCHEMA: 'run', LOCALE_SCHEMA: 'locale', RUNTIME_SCHEMA: None,
                 REUSE_SCHEMA: None}
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
    executor = executor or _text.current().provider.http_execute
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
    route = _text.current().provider.route.selected()
    require(route is not None, 'layer2_runtime_requires_explicit_launcher')
    actual = os.environ.get('OPENAI_API_KEY')
    require(isinstance(actual, str) and bool(actual) and (key is None or key == actual),
            'layer2_runtime_credential_changed')
    return {'openaiRoute': route, 'credentialSha256': hashlib.sha256(actual.encode()).hexdigest()}


def validate_runtime_identity(value):
    safe_route = _text.current().provider.route.safe
    require(type(value) is dict and set(value) == {'openaiRoute', 'credentialSha256'}
            and safe_route(value['openaiRoute']) is not None
            and safe_route(value['openaiRoute']) == value['openaiRoute']
            and isinstance(value['credentialSha256'], str)
            and re.fullmatch('[a-f0-9]{64}', value['credentialSha256']) is not None,
            'invalid_layer2_runtime_identity')
    return value


def validate_reuse_budget_roots(value, config, destination_root, scope):
    require(type(value) is dict and set(value) == set(config.lanes),
            'invalid_layer2_reuse_budget_roots')
    result = {}
    for locale, roots in value.items():
        require(type(roots) is list and roots and all(type(root) is str for root in roots),
                'invalid_layer2_reuse_budget_roots')
        resolved = [Path(root).resolve() for root in roots]
        require(len(set(resolved)) == len(resolved)
                and all(Path(raw).is_absolute() and str(path) == raw
                        for raw, path in zip(roots, resolved)),
                'invalid_layer2_reuse_budget_roots')
        destination = destination_root if scope == 'run' else destination_root / locale
        require(destination.resolve() not in resolved, 'invalid_layer2_reuse_budget_roots')
        result[locale] = resolved
    return result


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
    version = value.get('schemaVersion') if isinstance(value, dict) else None
    runtime_version = version in (RUNTIME_SCHEMA, REUSE_SCHEMA)
    extra = ({'ledgerScope', 'runtimeIdentity', 'reuseBudgetRoots'} if version == REUSE_SCHEMA
             else {'ledgerScope', 'runtimeIdentity'} if version == RUNTIME_SCHEMA
             else set() if isinstance(value, dict) and value.get('schemaVersion') == SCHEMA else {'ledgerScope'})
    require(isinstance(value, dict) and value.get('schemaVersion') in LEDGER_SCOPES
            and set(value) == base_keys | extra,
            'invalid_budget_authorization')
    runtime = (validate_runtime_identity(value['runtimeIdentity']) if runtime_version else None)
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
    reuse_roots = None
    if version == REUSE_SCHEMA:
        reuse_roots = validate_reuse_budget_roots(value['reuseBudgetRoots'], config, root, scope)
        expected['reuseBudgetRoots'] = {locale: [str(path) for path in roots]
                                        for locale, roots in reuse_roots.items()}
    require(sha(receipt_path) == authority['approvalSha256']
            and receipt.get('schemaVersion') == (REUSE_APPROVAL_SCHEMA if version == REUSE_SCHEMA
                else RUNTIME_APPROVAL_SCHEMA if runtime is not None
                else 'sermon-canonical-layer2-budget-approval-v1')
            and receipt.get('binding') == expected and receipt.get('humanApproval') is True
            and receipt.get('decision') == 'approved' and receipt.get('operatorEvidence')
            and receipt.get('reviewedBy') and receipt.get('reviewedAt'), 'budget_approval_not_bound')
    return {'path': path, 'sha256': actual_sha, 'value': value, 'root': root, 'limits': selected,
            'scope': scope, **({'runtimeIdentity': runtime} if runtime is not None else {}),
            **({'reuseBudgetRoots': reuse_roots} if reuse_roots is not None else {})}


def budget_root(config):
    """Keep a Gate 4 revision's new authority separate from the passed chain's ledger."""
    base = config.job_root.parent / f'.{config.job_root.name}.layer2-budget'
    if (getattr(config, 'auto_repair', None) or {}).get('backTranslationQc'):
        return base.with_name(base.name + '-qc-' + config.sha256)
    if getattr(config, 'group_revision', None):
        # A group revision has its own authorization, like a Gate 4 revision.
        return base.with_name(base.name + '-revision-' + config.sha256)
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
    def __init__(self, authorization, config, source, anchor, policy, *, transport=None, claude_transport=None,
                 claude_transports=None):
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
        approved_reuse = authorization.get('reuseBudgetRoots', {})
        store_reuse_roots = (approved_reuse.get(policy['targetLocale'], ())
            if authorization.get('scope') == 'locale'
            else tuple(dict.fromkeys(path for locale in sorted(approved_reuse)
                                     for path in approved_reuse[locale])))
        self.store = budget.BudgetStore(
            self.root, authorization['value']['authority'],
            max_ledger_bytes=LOCALE_LEDGER_MAX_BYTES if authorization.get('scope') == 'locale' else None,
            reuse_roots=store_reuse_roots)
        self.transport = transport
        # Subscription-login Claude CLI transports by role. A translator-only transport serves the
        # historical Opus-translator experiment; both roles exist only for a claude_cli_opus policy.
        from . import policy as policies
        self.claude_transports = dict(claude_transports or {})
        if claude_transport is not None:
            require('translator' not in self.claude_transports, 'claude_transport_required')
            self.claude_transports['translator'] = claude_transport
        require('reviewer' not in self.claude_transports or policies.layer2_backend(policy) == 'claude_cli_opus',
                'claude_reviewer_requires_claude_cli_opus_policy')
        self.claude_transport = self.claude_transports.get('translator')
        self._plugin_policy_migrations = {}

    def remaining_cost_microusd(self):
        """The authorization's USD cap (micro-USD) not yet reserved or spent in this ledger.

        Unknown outcomes keep their full reservation, as at every admission."""
        with self.store._locked() as (_, ledger):
            used = budget._sum(ledger['reservations'].values())
        return max(0, self.store.authority['globalBounds']['costMicrousd'] - used['costMicrousd'])

    def verify_execution(self, key):
        load_authorization(self.config, self.auth['path'], self.auth['value']['codeIdentitySha256'], self.auth['sha256'])
        verify_runtime(self.auth, key)

    def _call_binding(self, payload, *, policy=None):
        selected_policy = self.policy if policy is None else policy
        require_bounded_api_payload = _text.current().compute.admit
        require_bounded_api_payload(payload, self.auth['limits'], surface='canonical_api')
        capped = limits.bounded_payload(payload, self.auth['limits'])
        require(capped == payload, 'model_payload_must_be_bounded_before_cache_identity')
        fingerprint = jobs._digest({'payload': payload, 'runtimeIdentity': self.auth['runtimeIdentity']}
                                   if self.auth.get('runtimeIdentity') is not None else payload)
        roles = [name for name in ('translator', 'reviewer')
                 if payload['model'] == selected_policy[name]['model']
                 and payload['reasoning_effort'] == selected_policy[name]['reasoningEffort']]
        require(len(roles) == 1, 'budgeted_model_role_ambiguous')
        role = roles[0]
        identity = budget.chain_identity({
            'sourceIdentitySha256': self.source['downstreamInvalidationKey'],
            'sourcePackageSha256': jobs._digest(self.source), 'anchorSha256': jobs._digest(self.anchor),
            'policySha256': jobs._digest(selected_policy), 'rubricSha256': jobs._digest({'role': role}),
            'targetLocale': selected_policy['targetLocale'],
            'workUnitId': 'l2.' + selected_policy['targetLocale'] + '.call-' + fingerprint})
        bounds = limits.request_bounds(payload, self.auth['limits'])
        request = budget._request(identity, 'model.' + fingerprint,
            'initial_generation' if role == 'translator' else 'review', 'initial', 1,
            fingerprint, bounds)
        return fingerprint, role, identity, bounds, request

    def _plugin_only_migration_request(self, payload, migration):
        require(isinstance(migration, dict) and set(migration) == {'before', 'after'},
                'layer2_plugin_policy_migration_required')
        before, after = migration['before'], migration['after']
        require(isinstance(before, dict) and isinstance(after, dict)
                and after.get('payload') == payload
                and after.get('policy') == self.policy,
                'layer2_plugin_policy_migration_required')
        try:
            change = policy_preview.compare_previews(
                before, after, prior_outcome='succeeded')
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError('layer2_plugin_policy_migration_required') from error
        require(change['classification'] == 'plugin_only_migration'
                and change['modelPayloadUnchanged'] is True
                and change['blockedByPriorOutcome'] is False,
                'layer2_plugin_policy_migration_required')
        current = self._call_binding(payload)
        prior = self._call_binding(payload, policy=before['policy'])
        require(prior[0] == current[0] and prior[1] == current[1]
                and before.get('role') == current[1] == after.get('role'),
                'layer2_plugin_policy_migration_required')
        return prior[4]

    @staticmethod
    def _store_snapshot(root, max_bytes):
        _, folder, _ = jobs._paths(Path(root).resolve(), budget.STORE_ID)
        ledger, _ = budget.read_snapshot(folder / 'state.json', max_bytes=max_bytes)
        version = ledger.get('schemaVersion') if isinstance(ledger, dict) else None
        expected = {'schemaVersion', 'authority', 'storeSha256', 'reservations'}
        if version == budget.REUSE_SCHEMA:
            expected.update(('reuseBudgetRoots', 'migration'))
        require(isinstance(ledger, dict) and set(ledger) == expected
                and version in (budget.SCHEMA, budget.REUSE_SCHEMA)
                and isinstance(ledger.get('authority'), dict)
                and isinstance(ledger.get('reservations'), dict),
                'layer2_reuse_ledger_reconciliation_required')
        store = budget.BudgetStore(root, ledger['authority'], max_ledger_bytes=max_bytes,
            reuse_roots=ledger.get('reuseBudgetRoots', ()))
        require(ledger['storeSha256'] == store.store_sha256,
                'layer2_reuse_ledger_reconciliation_required')
        if version == budget.REUSE_SCHEMA:
            budget._migration(ledger['migration'])
        for rid, row in ledger['reservations'].items():
            store._validate_row(rid, row, version=version,
                                reuse_roots=ledger.get('reuseBudgetRoots', ()))
        return store, folder, ledger

    @classmethod
    def _direct_paid_provenance(cls, root, expected_request, fingerprint, response,
                                *, max_bytes):
        try:
            store, folder, ledger = cls._store_snapshot(root, max_bytes)
            rid = store._reservation_id(expected_request)
            row = ledger['reservations'].get(rid)
            require(row is not None and row.get('request') == expected_request,
                    'layer2_reuse_operation_missing')
            require(row.get('phase') == 'result'
                    and (row.get('result') or {}).get('executionStatus') != 'outcome_unknown',
                    'layer2_reuse_provider_outcome_unknown')
            require('settlement' not in row, 'layer2_reuse_requires_direct_paid_root')
            result = budget._result(row['result'])
            require(result['executionStatus'] == 'succeeded'
                    and result['usage']['requests'] == 1,
                    'layer2_reuse_requires_direct_paid_root')
            marker, _ = budget.read_snapshot(folder / (rid + '.result.json'))
            require(marker == {'reservationId': rid, 'result': result},
                    'layer2_reuse_response_reconciliation_required')
            record = jobs._read(Path(root) / 'responses' / (fingerprint + '.json'))
            require(isinstance(record, dict) and record.get('payloadSha256') == fingerprint
                    and record.get('reservationId') == rid and record.get('response') == response
                    and result['receiptSha256'] == jobs._digest(record),
                    'layer2_reuse_response_reconciliation_required')
            return {'schemaVersion': budget.REUSE_PROVENANCE_SCHEMA,
                    'budgetRoot': str(Path(root).resolve()),
                    'ledgerSchemaVersion': ledger['schemaVersion'],
                    'storeSha256': ledger['storeSha256'],
                    'authoritySha256': store.authority_sha256,
                    'reservationId': rid, 'operationId': expected_request['operationId'],
                    'inputSha256': fingerprint,
                    'resultMarkerSha256': jobs._digest(marker),
                    'responseSha256': jobs._digest(record)}
        except ValueError:
            raise
        except (OSError, KeyError, TypeError, AttributeError) as error:
            raise ValueError('layer2_reuse_response_reconciliation_required') from error

    def paid_response_provenance(self, key, payload, response):
        """Return immutable direct-paid evidence for a just-settled exact payload."""
        self.verify_execution(key)
        fingerprint, _, _, _, request = self._call_binding(payload)
        max_bytes = LOCALE_LEDGER_MAX_BYTES if self.auth.get('scope') == 'locale' else None

        def read_current_result():
            # Other group workers settle into this same mutable locale ledger. Hold
            # its writer lock while collecting the exact result, marker and response
            # closure so a legitimate atomic state.json replacement cannot look like
            # tampering. Prior reuse roots remain lock-free and immutable by contract.
            with self.store._locked():
                return self._direct_paid_provenance(
                    self.root, request, fingerprint, response, max_bytes=max_bytes)

        return self._ledger(read_current_result)

    def validate_recovery_source(self, key, source_root):
        """Require a terminal immutable direct-paid shard before any recovery call."""
        self.verify_execution(key)
        require(self.auth.get('reuseBudgetRoots') is not None,
                'layer2_reuse_authorization_required')
        root = Path(source_root).resolve()
        approved = self.auth['reuseBudgetRoots'][self.policy['targetLocale']]
        require(root in approved, 'layer2_recovery_budget_root_not_approved')
        max_bytes = LOCALE_LEDGER_MAX_BYTES if self.auth.get('scope') == 'locale' else None
        _, _, ledger = self._store_snapshot(root, max_bytes)
        require(ledger['schemaVersion'] == budget.SCHEMA
                and bool(ledger['reservations'])
                and all(row.get('phase') == 'result'
                        and (row.get('result') or {}).get('executionStatus') == 'succeeded'
                        and 'settlement' not in row
                        for row in ledger['reservations'].values()),
                'layer2_recovery_source_not_terminal_direct_paid')

    def recover_returned_response(self, key, payload, response, source_root, *,
                                  policy_migration=None):
        """Bind one returned failed-round response to its direct-paid closure."""
        self.verify_execution(key)
        require(self.auth.get('reuseBudgetRoots') is not None,
                'layer2_reuse_authorization_required')
        root = Path(source_root).resolve()
        require(root in self.auth['reuseBudgetRoots'][self.policy['targetLocale']],
                'layer2_recovery_budget_root_not_approved')
        fingerprint, _, _, _, request = self._call_binding(payload)
        max_bytes = LOCALE_LEDGER_MAX_BYTES if self.auth.get('scope') == 'locale' else None
        try:
            return self._direct_paid_provenance(
                root, request, fingerprint, response, max_bytes=max_bytes)
        except ValueError as error:
            if str(error) != 'layer2_reuse_operation_missing':
                raise
        prior_request = self._plugin_only_migration_request(payload, policy_migration)
        provenance = self._direct_paid_provenance(
            root, prior_request, fingerprint, response, max_bytes=max_bytes)
        self._plugin_policy_migrations[(str(root), fingerprint)] = copy.deepcopy(policy_migration)
        return provenance

    def record_reuse(self, key, payload, response, provenance):
        """Validate an exact direct-paid hit, recording only cross-root reuse.

        A later repair round can read a success sidecar produced by an earlier
        round of this same durable job.  Its exact operation is already settled
        as direct-paid in this store, so validate that immutable closure and
        return the existing result without rewriting it as a reused row.
        """
        self.verify_execution(key)
        require(isinstance(provenance, dict), 'layer2_reuse_provenance_changed')
        fingerprint, _, identity, bounds, request = self._call_binding(payload)
        if provenance.get('budgetRoot') == str(Path(self.root).resolve()):
            # Unlike approved predecessor roots, this store remains active for
            # the durable job.  Hold its ordinary budget lock so another group
            # cannot change the ledger between the state and result reads.
            def read_current_result():
                with self.store._locked():
                    return self._direct_paid_provenance(
                        self.root, request, fingerprint, response,
                        max_bytes=LOCALE_LEDGER_MAX_BYTES if self.auth.get('scope') == 'locale' else None)

            selected = self._ledger(read_current_result)
            require(selected == provenance, 'layer2_reuse_provenance_changed')
            return {'reservationId': selected['reservationId'], 'created': False,
                    'executionAllowed': False, 'status': 'succeeded', 'phase': 'result'}
        require(self.auth.get('reuseBudgetRoots') is not None,
                'layer2_reuse_authorization_required')
        selected = None
        for root in self.auth['reuseBudgetRoots'][self.policy['targetLocale']]:
            try:
                found = self._direct_paid_provenance(root, request, fingerprint, response,
                    max_bytes=LOCALE_LEDGER_MAX_BYTES if self.auth.get('scope') == 'locale' else None)
            except ValueError as error:
                if str(error) != 'layer2_reuse_operation_missing':
                    raise
                migration = self._plugin_policy_migrations.get((str(root), fingerprint))
                if migration is None:
                    continue
                prior_request = self._plugin_only_migration_request(payload, migration)
                found = self._direct_paid_provenance(
                    root, prior_request, fingerprint, response,
                    max_bytes=LOCALE_LEDGER_MAX_BYTES if self.auth.get('scope') == 'locale' else None)
            if str(root) == provenance.get('budgetRoot'):
                selected = found
        require(selected is not None, 'layer2_reuse_operation_missing')
        require(selected == provenance, 'layer2_reuse_provenance_changed')
        return self._ledger(lambda: self.store.record_reuse(identity,
            operation_id=request['operationId'], kind=request['kind'], revision_id='initial',
            revision_number=1, input_sha256=fingerprint, bounds=bounds,
            reused_from=selected))

    def _guard_no_paid_reuse_miss(self, request, fingerprint):
        """A missing lane sidecar cannot turn a known/unknown prior call into a second payment."""
        if self.auth.get('reuseBudgetRoots') is None:
            return
        max_bytes = LOCALE_LEDGER_MAX_BYTES if self.auth.get('scope') == 'locale' else None
        for root in self.auth['reuseBudgetRoots'][self.policy['targetLocale']]:
            try:
                store, _, ledger = self._store_snapshot(root, max_bytes)
                rid = store._reservation_id(request)
                row = ledger['reservations'].get(rid)
                if row is None:
                    continue
                require(row.get('request') == request,
                        'layer2_reuse_response_reconciliation_required')
                require(row.get('phase') == 'result'
                        and (row.get('result') or {}).get('executionStatus') != 'outcome_unknown',
                        'layer2_reuse_provider_outcome_unknown')
                require('settlement' not in row, 'layer2_reuse_requires_direct_paid_root')
                record = jobs._read(Path(root) / 'responses' / (fingerprint + '.json'))
                self._direct_paid_provenance(root, request, fingerprint, record.get('response'),
                                             max_bytes=max_bytes)
            except ValueError:
                raise
            except (OSError, KeyError, TypeError, AttributeError) as error:
                raise ValueError('layer2_reuse_response_reconciliation_required') from error
            raise ValueError('layer2_reuse_success_receipt_required')

    def __call__(self, key, payload):
        self.verify_execution(key)
        project_headers = _text.current().provider.route.project_headers
        selected_headers = project_headers(key)
        load_authorization(self.config, self.auth['path'],
                           self.auth['value']['codeIdentitySha256'], self.auth['sha256'])
        fingerprint, role, identity, bounds, request = self._call_binding(payload)
        self._guard_no_paid_reuse_miss(request, fingerprint)
        # Configuration errors are not paid unknown outcomes. Validate the
        # selected transport before reserving or marking any budget request.
        if payload['model'] in limits.CLAUDE_MODELS:
            selected_transport = self.claude_transports.get(role)
            require(self.transport is None and selected_transport is not None
                    and payload['model'] == selected_transport.model
                    and payload['reasoning_effort'] == selected_transport.effort, 'claude_transport_required')
        # Separate immutable request chains prevent content revisions from
        # resetting one shared global ledger. Each exact payload is one operation.
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
            # Claude is reachable only through its subscription CLI, as the role the policy froze.
            chat_envelope = _text.current().transports.claude_chat_envelope
            response = chat_envelope(self.claude_transports[role]('', payload, role=role), payload['model'])
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
