"""Opt-in D3/D5 integration for immutable generation and bounded review.

The caller supplies a BudgetStore with externally verified authority and one
pinned shared root, explicit bounds, and a trusted single-attempt transport.
There is no network default, scheduler, approval, Gate admission, or independent repair
producer here. A complete trusted usage resolver may settle known execution;
missing measurements leave the reservation blocked, not the content unknown.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import time

from scripts import sermon_accounting as accounting
from scripts import sermon_log_profile as profile
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_pipeline import TransportRejection
from scripts.sermon_pipeline import PreDispatchRejection, PRE_DISPATCH_REASONS
from scripts.sermon_release_workflow import _safe_path

DISPATCH_LOCK_ATTEMPTS = 100
DISPATCH_LOCK_DELAY_SECONDS = 0.05

# Only fixed program codes may cross the diagnostic boundary. Provider/library
# exception messages can contain transcript text, credentials or local paths.
GENERATION_FAILURE_REASONS = frozenset({
    'invalid_generated_candidate', 'invalid_frozen_group_artifact',
    'invalid_translation_group_id', 'candidate_group_scope_mismatch',
    'invalid_candidate_utterances', 'candidate_target_unit_mapping_mismatch',
    'invalid_candidate_coverage', 'candidate_source_coverage_mismatch',
    'candidate_coverage_text_not_present', 'invalid_strict_raw_content',
    'invalid_json_bytes', 'invalid_json_value', 'duplicate_json_key',
    'nonfinite_json_number', 'invalid_review_contract_schema',
})
SAFE_FAILURE_REASONS = GENERATION_FAILURE_REASONS | frozenset({
    'provider_input_bound_exceeded', 'provider_output_cap_mismatch',
    'provider_request_limit', 'provider_cost_limit',
    'provider_bounds_exceed_authorized_operation', 'budget_store_busy',
    'strict_budget_raw_binding_changed', 'strict_raw_receipt_binding_changed',
    'strict_raw_content_changed', 'immutable_candidate_changed',
    'candidate_changed_during_review', 'strict_budget_call_binding_changed',
    'controller_repair_evidence_missing', 'strict_repair_context_required',
})


def safe_failure_reason(error, fallback='current_evidence_not_validated'):
    if type(error) is PreDispatchRejection and error.reason_code in PRE_DISPATCH_REASONS:
        return error.reason_code
    if type(error) in (c.ContractError, ValueError) and len(error.args) == 1 and type(error.args[0]) is str and error.args[0] in SAFE_FAILURE_REASONS:
        return error.args[0]
    return fallback


def chain_identity(prepared):
    expected = strict.prepare(*(prepared['bytes'][key] for key in
        ('englishSource', 'anchor', 'policy', 'rubric')), prepared['group'], request_limits=prepared.get('requestLimits'), diagnostic_context=prepared.get('diagnosticContext'), rule_preflight=prepared.get('rulePreflight'), rule_context=prepared.get('ruleContext'))
    c.require(prepared == expected, 'strict_prepared_inputs_changed')
    return budget.chain_identity({
        'sourceIdentitySha256': prepared['source']['downstreamInvalidationKey'],
        'sourcePackageSha256': c.canonical_sha256(prepared['source']),
        'anchorSha256': c.canonical_sha256(prepared['anchor']),
        'policySha256': c.canonical_sha256(prepared['policy']),
        'rubricSha256': c.canonical_sha256(prepared['rubric']),
        'targetLocale': prepared['policy']['targetLocale'], 'workUnitId': prepared['workUnitId']})


def operation_binding(kind, prepared, root, candidate_id, revision_id, attempt_number=1, repair=None):
    """Read-only current-input fingerprint shared with fixed Gate validation."""
    c.require(kind in ('initial_generation', 'content_revision', 'review'), 'invalid_strict_budget_kind')
    c.require(type(attempt_number) is int and 1 <= attempt_number <= (2 if kind == 'review' else 1),
              'invalid_review_attempt_number')
    c.require((kind == 'content_revision') == (repair is not None), 'strict_budget_repair_kind_mismatch')
    root = _safe_path(Path(root))
    strict.label(candidate_id); strict.label(revision_id)
    identity = chain_identity(prepared)
    manifest = None
    revision_number = 1
    if repair is not None:
        strict.validate_repair(prepared, candidate_id, revision_id, repair)
        revision_number = repair['parentRevision']['revisionNumber'] + 1
    if kind == 'review':
        manifest, manifest_bytes = c.read_snapshot(root / 'revision.json')
        artifact, artifact_bytes = c.read_snapshot(root / 'candidate.json')
        c.validate_candidate_artifact(manifest, artifact_bytes)
        revision_number = manifest['revisionNumber']
        if revision_number > 1:
            repair = strict.load_repair(root)
            strict.validate_repair(prepared, candidate_id, revision_id, repair)
        for key, value in strict.common_identity(prepared, candidate_id, revision_id).items():
            c.require(manifest[key] == value, 'review_current_identity_changed')
        inputs = strict.input_manifest(prepared, manifest, artifact_bytes)
        c.validate_contract(inputs)
        request = strict.prompt(prepared, 'reviewer', candidate=artifact, input_manifest=inputs)
        role = 'reviewer'
    else:
        request = strict.prompt(prepared, 'translator') if repair is None else strict.generation_prompt(prepared, repair)
        role = 'translator'
    payload_sha256 = c.canonical_sha256(strict._payload(prepared, role, request))
    operation_id = kind + '.' + c.canonical_sha256({
        'chainId': c.canonical_sha256(identity), 'revisionId': revision_id,
        'kind': kind, 'attemptNumber': attempt_number})
    input_sha256 = c.canonical_sha256({
        'payloadSha256': payload_sha256, 'candidateId': candidate_id, 'revisionId': revision_id,
        **({'requestLimits': prepared['requestLimits']} if 'requestLimits' in prepared else {}),
        **({'diagnosticContext': prepared['diagnosticContext']} if 'diagnosticContext' in prepared else {}),
        'materialBytesSha256': {key: c.bytes_sha256(value) for key, value in prepared['bytes'].items()},
        'revisionBytesSha256': c.bytes_sha256(manifest_bytes) if manifest is not None else None,
        'repair': None if repair is None else {**{key: value for key, value in repair.items()
            if key not in ('parentCandidateBytes', 'sidecars')},
            'parentCandidateBytesSha256': c.bytes_sha256(repair['parentCandidateBytes']),
            'sidecarBytesSha256': {key: c.bytes_sha256(value) for key, value in repair['sidecars'].items()}}})
    suffix = '' if attempt_number == 1 else '-' + str(attempt_number)
    output = root / ('generator.json' if kind != 'review' else 'reviewer' + suffix + '.json')
    return {'identity': identity, 'operationId': operation_id, 'inputSha256': input_sha256,
            'payloadSha256': payload_sha256, 'outputName': output.name, 'revisionNumber': revision_number}


class StrictBudgetAdapter:
    def __init__(self, store):
        c.require(isinstance(store, budget.BudgetStore), 'strict_budget_store_required')
        self.store = store

    def generate(self, prepared, root, candidate_id, revision_id, api_key, caller, *,
                 bounds, usage_resolver=None, depends_on=None, completion_spans=None, repair=None):
        """Generate initial or validated repair revision with separate budget state."""
        return self._run('initial_generation' if repair is None else 'content_revision', prepared, root, candidate_id, revision_id,
                         api_key, caller, bounds, usage_resolver, 1, depends_on, completion_spans, repair)

    def review(self, prepared, root, candidate_id, revision_id, api_key, caller, *,
               bounds, attempt_number=1, usage_resolver=None, depends_on=None, completion_spans=None):
        """A caller must explicitly request attempt 2; the ledger must permit it."""
        c.require(type(attempt_number) is int and 1 <= attempt_number <= 2,
                  'invalid_review_attempt_number')
        return self._run('review', prepared, root, candidate_id, revision_id, api_key,
                         caller, bounds, usage_resolver, attempt_number, depends_on, completion_spans, None)

    def _run(self, kind, prepared, root, candidate_id, revision_id, api_key, caller,
             bounds, usage_resolver, attempt_number, depends_on, completion_spans, repair):
        c.require(profile.current() is not None, 'strict_requires_accounting_profile')
        if 'diagnosticContext' in prepared:
            c.require(prepared['diagnosticContext']['storeSha256'] == self.store.store_sha256,
                      'diagnostic_budget_store_changed')
        root = _safe_path(Path(root))
        operation = operation_binding(kind, prepared, root, candidate_id, revision_id, attempt_number, repair)
        identity, operation_id = operation['identity'], operation['operationId']
        input_sha256, payload_sha256 = operation['inputSha256'], operation['payloadSha256']
        output, revision_number = root / operation['outputName'], operation['revisionNumber']
        if hasattr(caller, 'preflight'):
            # Pre-dispatch pure checks run before reserving D5 or creating a cache marker.
            actual_bounds = caller.preflight(prepared, kind, root, repair)
            budget._amounts(bounds, positive=True)
            c.require(all(actual_bounds[k] <= bounds[k] for k in budget.METRICS),
                      'provider_bounds_exceed_authorized_operation')
            bounds = actual_bounds
        before = self.store.snapshot(identity)
        existing = next((row for row in before['reservations'] if row['operationId'] == operation_id), None)
        if kind == 'review':
            manifest, _ = c.read_snapshot(root / 'revision.json')
            c.require(any(row['kind'] in ('initial_generation', 'content_revision') and row['revisionId'] == revision_id
                          and row['executionStatus'] == 'succeeded'
                          and row['receiptSha256'] == c.canonical_sha256(manifest)
                          for row in before['reservations']), 'strict_budget_generation_not_recorded')
        if repair is not None:
            c.require(any(row['kind'] == 'review' and row['revisionId'] == repair['parentRevision']['revisionId']
                          and row['receiptSha256'] == c.canonical_sha256(repair['triggerReview'])
                          and row['executionStatus'] == 'succeeded' for row in before['reservations']),
                      'strict_budget_trigger_review_not_recorded')
        if kind == 'review' and existing is None:
            count = before['revisions'].get(str(revision_number), {}).get('reviewAttempts', 0)
            c.require(attempt_number == count + 1, 'strict_budget_review_attempt_sequence')
        # Do not silently adopt an earlier, unreserved D3 call/cache as new work.
        binding_path = output.with_suffix('.budget-binding.json')
        if not binding_path.exists():
            c.require(not any(path.exists() for path in (output, output.with_suffix('.started.json'),
                output.with_suffix('.raw.json'), output.with_suffix('.call.json'),
                output.with_suffix('.rejection.json'))), 'strict_budget_unbound_existing_call')
        reservation = self.store.reserve(identity, operation_id=operation_id, kind=kind,
            revision_id=revision_id, revision_number=revision_number, input_sha256=input_sha256, bounds=bounds,
            locked_check=(lambda folder, ledger: self._repair_guard(folder, ledger, operation, repair))
                if repair is not None else None)
        rid = reservation['reservationId']
        binding = {'schemaVersion': 'sermon-strict-budget-binding-v1', 'reservationId': rid,
            'chainId': c.canonical_sha256(identity), 'operationId': operation_id,
            'inputSha256': input_sha256, 'payloadSha256': payload_sha256,
            'authoritySha256': self.store.authority_sha256, 'storeSha256': self.store.store_sha256}
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        strict.save_once(binding_path, binding)
        jobs._sync_directory_ancestry(root)
        transport = self._transport(output, binding, reservation, caller)
        options = dict(cache_only=not reservation['created'], depends_on=depends_on,
                       completion_spans=completion_spans)
        failure = None
        not_dispatched = False
        try:
            prior_rejection = self._non_dispatch_failure(output, binding)
            if prior_rejection is not None:
                stopped = PreDispatchRejection(prior_rejection['reasonCode'])
                stopped.bind_attempt(prior_rejection['modelCallId'])
                raise stopped
            if kind != 'review':
                if repair is not None: options['repair'] = repair
                artifact = strict.generate(prepared, root, candidate_id, revision_id, api_key, transport, **options)
                status, content = 'succeeded', 'not_assessed'
                receipt_sha256 = c.canonical_sha256(artifact)
            else:
                artifact = strict.review(prepared, root, candidate_id, revision_id, api_key, transport,
                                         attempt_number=attempt_number, **options)
                status = artifact['executionStatus']
                content = {'pass': 'pass', 'needs_rework': 'fail', 'inconclusive': 'uncertain',
                           'not_assessed': 'not_assessed'}[artifact['reviewVerdict']]
                receipt_sha256 = c.canonical_sha256(artifact)
        except PreDispatchRejection as exc:
            if getattr(exc, 'sermon_logging_failed', False):
                raise
            rejected = self._non_dispatch_failure(output, binding)
            c.require(rejected is not None and rejected['modelCallId'] == exc.attempt_id and
                rejected['reasonCode'] == exc.reason_code, 'strict_budget_non_dispatch_unproven')
            artifact = None
            status, content = 'failed', 'not_assessed'
            receipt_sha256 = c.canonical_sha256(rejected)
            failure = {'reasonCode': rejected['reasonCode'], 'providerOutcome': 'not_dispatched',
                'receipt': strict.reference('generation-or-review-non-dispatch',
                    output.with_suffix('.non-dispatch.json').read_bytes())}
            not_dispatched = True
        except TransportRejection as exc:
            if kind == 'review' or getattr(exc, 'sermon_logging_failed', False):
                raise
            # Generation has no D1 review receipt. Its verified typed rejection
            # is execution evidence, never a fabricated Candidate/Review object.
            rejection = strict._transport_rejection(output, payload_sha256)
            c.require(rejection is not None, 'strict_budget_unproven_rejection')
            artifact = None
            status, content = 'failed', 'not_assessed'
            receipt_sha256 = c.canonical_sha256(rejection)
        except (ValueError, TypeError, KeyError) as exc:
            if kind == 'review' or getattr(exc, 'sermon_logging_failed', False):
                raise
            # A mismatched/tampered binding is not evidence of a new structural
            # model failure. Only verified returned proof may settle this call.
            if isinstance(exc, c.ContractError) and (len(exc.args) != 1 or
                    type(exc.args[0]) is not str or exc.args[0] not in GENERATION_FAILURE_REASONS):
                raise
            if not output.with_suffix('.raw.json').is_file():
                raise
            observed = self._evidence(output, binding, 'failed', None,
                requested_model=prepared['policy']['translator']['model'],
                service_tier=(prepared.get('requestLimits') or {}).get('serviceTier'))
            _, raw_bytes = c.read_snapshot(output.with_suffix('.raw.json'))
            c.require(c.bytes_sha256(raw_bytes) == observed['rawResponseBytesSha256'],
                      'strict_budget_raw_binding_changed')
            failure = {
                **binding,
                'schemaVersion': 'sermon-strict-generation-artifact-failure-v1',
                'executionStatus': 'failed', 'contentStatus': 'not_assessed',
                'providerOutcome': 'returned',
                'reasonCode': safe_failure_reason(exc, 'invalid_generated_candidate_response'),
                'errorType': type(exc).__name__,
                'candidateId': candidate_id, 'revisionId': revision_id,
                'workUnitId': prepared['workUnitId'], 'kind': kind,
                'modelCallId': observed['modelCallId'],
                'rawResponse': strict.reference('generation-raw', raw_bytes),
            }
            # Private versioned sidecar, not a Candidate or a Review Receipt.
            failure_bytes = strict.save_once(output.with_suffix('.artifact-failure.json'), failure)
            jobs._sync_directory_ancestry(root)
            artifact = None
            status, content = 'failed', 'not_assessed'
            receipt_sha256 = c.canonical_sha256(failure)
            failure = {'reasonCode': failure['reasonCode'], 'providerOutcome': 'returned',
                'receipt': strict.reference('generation-artifact-failure', failure_bytes)}
        if not_dispatched:
            observed = None
        elif failure is None:
            observed = self._evidence(output, binding, status, artifact,
                requested_model=prepared['policy']['reviewer' if kind == 'review' else 'translator']['model'],
                service_tier=(prepared.get('requestLimits') or {}).get('serviceTier'))
        result = {'executionStatus': status, 'contentStatus': content,
                  'receiptSha256': receipt_sha256, 'usage': None}
        result_path = output.with_suffix('.budget-result.json')
        if result_path.exists():
            saved, _ = c.read_snapshot(result_path)
            budget._result(saved)
            c.require(all(saved[key] == result[key] for key in result if key != 'usage'),
                      'strict_budget_result_binding_changed')
            result = saved
        elif status != 'outcome_unknown':
            # The typed guard proves zero provider execution/usage. D5 counts a
            # logical reservation, and max(bound, usage) retains EVERY bound.
            # This is neither measured billing nor a refund of reserved capacity.
            usage = ({key: int(key == 'requests') for key in budget.METRICS} if not_dispatched else
                usage_resolver(deepcopy(dict(observed, kind=kind, executionStatus=status,
                    receiptSha256=receipt_sha256))) if usage_resolver is not None else None)
            if usage is not None:
                c.require(type(usage) is dict and set(usage) <= set(budget.METRICS),
                          'invalid_strict_budget_measured_usage')
            if usage is None or set(usage) != set(budget.METRICS) or any(value is None for value in usage.values()):
                return self._public(artifact, result, rid, 'reconciliation_required', failure)
            result['usage'] = usage
        budget._result(result)
        strict.save_once(result_path, result)
        if reservation['created'] or status == 'outcome_unknown':
            self.store.record_result(rid, result)
        else:
            # Local D3 validation happened first. Only its exact saved result can
            # reconcile pending accounting; replays never regain dispatch rights.
            self.store.reconcile(rid, result=result, evidence_sha256=receipt_sha256)
        budget_status = 'reconciliation_required' if status == 'outcome_unknown' else 'recorded'
        if result['usage'] is not None and any(result['usage'][key] > bounds[key] for key in budget.METRICS):
            budget_status = 'bound_exceeded'
        return self._public(artifact, result, rid, budget_status, failure)

    @staticmethod
    def _repair_guard(folder, ledger, operation, repair):
        """Bind the durable planner proposal at the atomic reservation boundary.

        Pure/schema-valid plans carry no execution authority. Current sidecars
        and the complete prior repair chain must exist in this same store; a
        previously consumed failure cannot purchase another content revision.
        """
        history, _ = c.read_snapshot(folder / 'repair-planning.json')
        c.require(type(history) is dict and set(history) ==
                  {'schemaVersion', 'productionRunId', 'chains'} and
                  history['schemaVersion'] == 'sermon-strict-repair-history-v1',
                  'strict_repair_history_changed')
        budget._hash(history['productionRunId'])
        c.require(type(history['chains']) is dict, 'strict_repair_history_changed')
        entries = history['chains'].get(c.canonical_sha256(operation['identity']))
        c.require(type(entries) is dict, 'strict_repair_not_durably_planned')
        plan = repair['plan']
        entry = entries.get(plan['repairPlanId'])
        c.require(type(entry) is dict and set(entry) == {'plan', 'fingerprint', 'sidecars'} and
                  entry['plan'] == plan and entry['sidecars'] ==
                  {key: c.decode_json(raw) for key, raw in repair['sidecars'].items()},
                  'strict_repair_not_durably_planned')
        parent, review, inputs = repair['parentRevision'], repair['triggerReview'], repair['inputManifest']
        context = inputs['materialRefs']['context']
        fingerprint = c.canonical_sha256({
            **{key: parent[key] for key in ('candidateId', 'artifactSha256', 'sourceIdentitySha256',
                'sourcePackageSha256', 'anchorSha256', 'policySha256')},
            'rubricSha256': review['rubricSha256'],
            'contextSha256': context['canonicalJsonSha256'] or context['fileBytesSha256'],
            'contextSourceUnitIds': inputs['contextSourceUnitIds'],
            'reasonCodes': sorted({issue['reasonCode'] for issue in review['issues']})})
        c.require(entry['fingerprint'] == fingerprint, 'strict_repair_fingerprint_changed')
        snapshot = entry['sidecars'][plan['budgetRef']['artifactId']]
        c.require(snapshot['production_run_id'] == history['productionRunId'],
                  'strict_repair_history_changed')
        for prior in repair['priorRepairs']:
            saved = entries.get(prior['repairPlanId'])
            c.require(type(saved) is dict and saved.get('plan') == prior,
                      'strict_repair_history_incomplete')
        rows = [row for row in ledger['reservations'].values()
                if row['request']['identity'] == operation['identity']]
        # reserve already checked exact request equality for existing operations.
        if any(row['request']['operationId'] == operation['operationId'] for row in rows):
            return
        consumed = {row['request']['revisionId'] for row in rows
                    if row['request']['kind'] == 'content_revision'}
        for saved in entries.values():
            c.require(type(saved) is dict and set(saved) == {'plan', 'fingerprint', 'sidecars'},
                      'strict_repair_history_changed')
            c.require(not (saved['plan']['toRevisionId'] in consumed and
                           saved['fingerprint'] == fingerprint),
                      'repeated_failure_without_new_evidence')

    def _transport(self, output, binding, reservation, caller):
        invoked = False
        def dispatch(api_key, payload, *, response_observer):
            nonlocal invoked
            c.require(reservation['created'] and not invoked, 'strict_budget_transport_forbidden')
            c.require(callable(caller), 'strict_budget_transport_required')
            c.require(c.canonical_sha256(payload) == binding['payloadSha256'], 'strict_budget_payload_changed')
            invoked = True
            rid = reservation['reservationId']
            for attempt in range(DISPATCH_LOCK_ATTEMPTS):
                try:
                    self.store.mark_request(rid)
                    break
                except c.ContractError as exc:
                    # Only this live invocation still owns the unconsumed permit.
                    # A busy nonblocking lock did not attempt persistence or a
                    # provider call. Never retry an uncertain write, an exhausted
                    # wait, a restarted adapter, or any other validation failure.
                    if (exc.args != ('budget_store_busy',) or rid not in self.store._execution_permits
                            or attempt == DISPATCH_LOCK_ATTEMPTS - 1):
                        raise
                    time.sleep(DISPATCH_LOCK_DELAY_SECONDS)
            observed_call = None
            def started(model_call_id):
                nonlocal observed_call
                c.require(observed_call is None, 'strict_budget_second_transport_attempt')
                observed_call = strict.label(model_call_id)
                strict.save_once(output.with_suffix('.budget-call.json'), {
                    'schemaVersion': 'sermon-strict-budget-call-v1', 'reservationId': reservation['reservationId'],
                    'payloadSha256': binding['payloadSha256'], 'modelCallId': observed_call})
                response_observer.request_started(observed_call)
                jobs._sync_directory_ancestry(output.parent)
            def returned(response, model_call_id, elapsed):
                c.require(observed_call is not None and model_call_id == observed_call,
                          'strict_budget_transport_call_changed')
                return response_observer(response, model_call_id, elapsed)
            def rejected(error, model_call_id):
                c.require(observed_call is not None and model_call_id == observed_call,
                          'strict_budget_transport_call_changed')
                return response_observer.request_rejected(error, model_call_id)
            returned.request_started = started
            returned.request_rejected = rejected
            try:
                return caller(api_key, payload, response_observer=returned)
            except PreDispatchRejection as exc:
                if getattr(exc, 'sermon_logging_failed', False):
                    raise
                c.require(type(exc) is PreDispatchRejection and exc.reason_code in PRE_DISPATCH_REASONS,
                          'strict_budget_non_dispatch_unproven')
                call_id = exc.attempt_id
                c.require(type(call_id) is str and len(call_id) == 32 and
                    all(ch in '0123456789abcdef' for ch in call_id) and
                    (observed_call is None or observed_call == call_id), 'strict_budget_non_dispatch_unproven')
                stopped = {**binding, 'schemaVersion': 'sermon-strict-non-dispatch-failure-v1',
                    'modelCallId': call_id, 'reasonCode': exc.reason_code, 'dispatched': False,
                    'providerOutcome': 'not_dispatched', 'executionStatus': 'failed',
                    'usageBasis': 'verified_not_dispatched_zero_provider_usage_logical_reservation_retained'}
                strict.save_once(output.with_suffix('.non-dispatch.json'), stopped)
                jobs._sync_directory_ancestry(output.parent)
                self._non_dispatch_failure(output, binding)
                raise
        return dispatch

    @staticmethod
    def _non_dispatch_failure(output, binding):
        path = output.with_suffix('.non-dispatch.json')
        if not path.exists():
            return None
        stopped, _ = c.read_snapshot(path)
        c.require(type(stopped) is dict and set(stopped) == set(binding) | {
            'modelCallId', 'reasonCode', 'dispatched', 'providerOutcome', 'executionStatus', 'usageBasis'},
            'strict_budget_non_dispatch_binding_changed')
        expected = {**binding, 'schemaVersion': 'sermon-strict-non-dispatch-failure-v1',
            'modelCallId': stopped['modelCallId'], 'reasonCode': stopped['reasonCode'], 'dispatched': False,
            'providerOutcome': 'not_dispatched', 'executionStatus': 'failed',
            'usageBasis': 'verified_not_dispatched_zero_provider_usage_logical_reservation_retained'}
        c.require(stopped == expected and type(stopped['modelCallId']) is str and
            len(stopped['modelCallId']) == 32 and all(ch in '0123456789abcdef' for ch in stopped['modelCallId']) and
            stopped['reasonCode'] in PRE_DISPATCH_REASONS, 'strict_budget_non_dispatch_binding_changed')
        marker, _ = c.read_snapshot(output.with_suffix('.started.json'))
        c.require(marker.get('payloadSha256') == binding['payloadSha256'] and
            marker.get('status') == 'started_response_unconfirmed', 'strict_budget_non_dispatch_binding_changed')
        c.require(not any(p.exists() for p in (output, output.with_suffix('.raw.json'),
            output.with_suffix('.rejection.json'))), 'strict_budget_non_dispatch_conflicting_evidence')
        for suffix in ('.call.json', '.budget-call.json'):
            if output.with_suffix(suffix).exists():
                call, _ = c.read_snapshot(output.with_suffix(suffix))
                expected_call = ({'modelCallId': stopped['modelCallId']} if suffix == '.call.json' else {
                    'schemaVersion': 'sermon-strict-budget-call-v1',
                    'reservationId': binding['reservationId'], 'payloadSha256': binding['payloadSha256'],
                    'modelCallId': stopped['modelCallId']})
                c.require(call == expected_call,
                          'strict_budget_non_dispatch_binding_changed')
        return stopped

    @staticmethod
    def _evidence(output, binding, status, artifact, *, requested_model=None, service_tier=None):
        proof, _ = c.read_snapshot(output.with_suffix('.budget-call.json'))
        call, _ = c.read_snapshot(output.with_suffix('.call.json'))
        c.require(type(proof) is dict and set(proof) ==
                  {'schemaVersion', 'reservationId', 'payloadSha256', 'modelCallId'}, 'invalid_strict_budget_call')
        c.require(proof['schemaVersion'] == 'sermon-strict-budget-call-v1' and
                  proof['reservationId'] == binding['reservationId'] and
                  proof['payloadSha256'] == binding['payloadSha256'] and
                  proof['modelCallId'] == strict.label(call['modelCallId']), 'strict_budget_call_binding_changed')
        if artifact is not None and artifact.get('schemaVersion') == 'sermon-review-receipt-v1':
            c.require(artifact['modelCallId'] == proof['modelCallId'], 'strict_budget_receipt_call_changed')
        rejection = strict._transport_rejection(output, binding['payloadSha256'])
        if rejection is not None:
            c.require(status == 'failed' and rejection['modelCallId'] == proof['modelCallId'],
                      'strict_budget_rejection_status_changed')
            return {'modelCallId': proof['modelCallId'], 'providerUsage': None,
                    'elapsedSeconds': None, 'httpStatus': rejection['httpStatus']}
        if status == 'outcome_unknown':
            return {'modelCallId': proof['modelCallId'], 'providerUsage': None,
                    'elapsedSeconds': None, 'httpStatus': None}
        raw, raw_bytes = c.read_snapshot(output.with_suffix('.raw.json'))
        c.require(type(raw) is dict and type(raw.get('response')) is dict and
                  raw.get('payloadSha256') == binding['payloadSha256'] and
                  raw.get('accounting', {}).get('modelCallId') == proof['modelCallId'],
                  'strict_budget_raw_binding_changed')
        if status == 'succeeded' and artifact is not None and artifact.get('schemaVersion') == 'sermon-review-receipt-v1':
            saved, saved_bytes = c.read_snapshot(output)
            strict.require_call_binding(output, saved)
            evidence_ref = strict.reference('review-result', saved_bytes)
            c.require(evidence_ref in artifact['evidenceRefs'], 'strict_budget_review_evidence_changed')
            manifest, _ = c.read_snapshot(output.parent / 'revision.json')
            assessment = strict.review_result(saved['result'], manifest, evidence_ref)
            c.require(all(artifact[key] == value for key, value in assessment.items()),
                      'strict_budget_review_assessment_changed')
        return {'modelCallId': proof['modelCallId'],
                'rawResponseBytesSha256': c.bytes_sha256(raw_bytes),
                'providerUsage': accounting.normalize_usage(raw['response'].get('usage')),
                'providerModel': raw['response'].get('model'),
                'requestedModel': requested_model,
                'serviceTier': raw['response'].get('service_tier', service_tier),
                'elapsedSeconds': raw.get('accounting', {}).get('elapsedSeconds'), 'httpStatus': 200}

    @staticmethod
    def _public(artifact, result, rid, budget_status, failure=None):
        return {'artifact': artifact, 'executionStatus': result['executionStatus'],
                'contentStatus': result['contentStatus'], 'receiptSha256': result['receiptSha256'],
                'reservationId': rid, 'budgetStatus': budget_status, 'executionAuthority': 'none',
                **({'failureEvidence': {**failure,
                    'budgetUsageStatus': 'complete' if result['usage'] is not None else 'missing_or_incomplete'}}
                   if failure is not None else {})}
