"""Pure D5 planning over D1 receipts; no artifact IO, calls, or execution grants.

The caller supplies complete dependency data and a durable budget *observation*.
Counters include reserved/failed/unknown attempts and never reset with directories,
issue IDs or revisions. They are NOT reservations. Before execution, the existing
controller must re-read evidence/state under its lock, atomically reserve both
unit-chain and run request/token/time/cost budgets, and reconcile unknown intents.
Store/job, partial-repair producer, accounting, and locked admission integration
remain pending. This module does not implement a second scheduler or budget store.

Returned sidecars use canonical_bytes verbatim when persisted. Their references
describe proposed bytes, not proof of persistence. D1 lineage is one group per
Repair Plan; dependency groups require their own evidence/plans before dispatch.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
import re
from types import MappingProxyType

from scripts import sermon_bounded_decision as decision
from scripts import sermon_review_contracts as c

ROUTING_VERSION = 'rqc-layer2-failure-routing-v1'
CONTENT_FAILURES = frozenset({'meaning_omission', 'meaning_addition', 'negation_error',
    'number_error', 'name_error', 'quotation_attribution_error', 'source_coverage_missing',
    'terminology_error', 'language_rule_failed'})
FAILURE_ACTIONS = MappingProxyType({**{code: 'repair_translation' for code in CONTENT_FAILURES},
    'review_execution_failed': 'retry_review', 'review_outcome_unknown': 'reconcile',
    'log_persistence_failed': 'reconcile', 'source_ambiguity': 'request_source_review',
    'evidence_insufficient': 'request_human_review', 'contradictory_reviews': 'request_human_review'})
REQUIRED_DURABLE_CHECKS = (
    'recheck_state_evidence_and_complete_dependency_graph_under_lock',
    'atomically_reserve_unit_chain_and_global_request_token_time_cost_budgets',
    'retain_reservations_for_failed_cancelled_and_unknown_requests',
    'reuse_stable_operation_identity_and_reconcile_existing_intents',
    'persist_plan_sidecars_and_new_revision_without_overwriting_prior_artifacts',
    'bind_partial_repair_to_existing_cache_and_run_prescribed_review_plugin_admission',
)


@dataclass(frozen=True)
class Limits:
    content_revisions: int = 2  # after the initial candidate
    review_attempts_per_revision: int = 2
    decision_proposals_per_chain: int = 1


@dataclass(frozen=True)
class BudgetSnapshot:
    """Trusted store inputs, including consumed AND reserved attempts.

    authorization_sha256 and global_budget_sha256 identify caller-verified run
    authorization and aggregate request/token/time/cost ledger evidence; hashes
    alone do not establish authorization. Missing snapshot blocks new paid work.
    review_attempts_reserved includes the supplied receipt's execution attempt.
    prior_failure_fingerprints must survive the complete unit revision chain.
    """
    production_run_id: str
    state_revision: str
    candidate_id: str
    work_unit_id: str
    chain_root_revision_id: str
    current_revision_id: str
    authorization_sha256: str
    global_budget_sha256: str
    content_revisions_reserved: int
    review_attempts_reserved: int
    decision_proposals_reserved: int
    unresolved_operation_ids: tuple[str, ...] = ()
    prior_failure_fingerprints: tuple[str, ...] = ()
    limits: Limits = Limits()


def _label(value):
    return type(value) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', value) is not None


def _sha(value):
    return type(value) is str and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def route_failure(code, *, version=ROUTING_VERSION):
    """Unknown codes escalate; known codes never invoke a decision model."""
    c.require(version == ROUTING_VERSION, 'unsupported_failure_routing_version')
    c.require(_label(code), 'invalid_failure_code')
    return FAILURE_ACTIONS.get(code, 'escalate_engineering')


def dependency_closure(graph, seeds):
    """Follow data/context dependents, never prerequisites or unrelated locales.

    graph is a complete list of {workUnitId, layer, targetLocale, dependsOn}.
    Layer 1 uses null locale; other layers use lN.<locale>.<unit> identities.
    Edges mean actual data/context dependence, not mere scheduling order.
    """
    c.require(type(graph) is list and 1 <= len(graph) <= 1024, 'invalid_dependency_graph')
    nodes = {}
    for row in graph:
        c.require(type(row) is dict and set(row) == {'workUnitId', 'layer', 'targetLocale', 'dependsOn'}, 'invalid_dependency_node')
        unit, layer, locale, deps = (row[k] for k in ('workUnitId', 'layer', 'targetLocale', 'dependsOn'))
        c.require(_label(unit) and unit not in nodes and type(layer) is int and 1 <= layer <= 4, 'invalid_dependency_identity')
        c.require((layer == 1 and locale is None) or (layer > 1 and type(locale) is str and locale in {'zh-Hans', 'ko', 'es'}
                  and unit.startswith(f'l{layer}.{locale}.')), 'dependency_locale_mismatch')
        c.require(type(deps) is list and len(deps) <= 1024 and all(_label(d) for d in deps)
                  and len(deps) == len(set(deps)) and unit not in deps, 'invalid_dependency_edges')
        nodes[unit] = copy.deepcopy(row)
    dependents = {unit: [] for unit in nodes}
    for unit, row in nodes.items():
        for dep in row['dependsOn']:
            c.require(dep in nodes, 'missing_dependency_node')
            parent = nodes[dep]
            c.require(parent['layer'] <= row['layer'], 'upstream_dependency_on_downstream')
            c.require(parent['layer'] == 1 or parent['targetLocale'] == row['targetLocale'], 'cross_locale_dependency')
            dependents[dep].append(unit)
    # Deterministic Kahn traversal rejects cycles, even in an unaffected lane.
    counts = {unit: len(row['dependsOn']) for unit, row in nodes.items()}
    ready = sorted(unit for unit in nodes if counts[unit] == 0)
    order = []
    while ready:
        unit = ready.pop(0)
        order.append(unit)
        for child in sorted(dependents[unit]):
            counts[child] -= 1
            if counts[child] == 0:
                ready.append(child)
                ready.sort()
    c.require(len(order) == len(nodes), 'cyclic_dependency_graph')
    c.require(type(seeds) is list and seeds and all(_label(s) and s in nodes for s in seeds)
              and len(seeds) == len(set(seeds)), 'invalid_closure_seeds')
    affected = set(seeds)
    for unit in order:
        if unit in affected:
            affected.update(dependents[unit])
    normalized = [dict(nodes[u], dependsOn=sorted(nodes[u]['dependsOn'])) for u in sorted(nodes)]
    return {'schemaVersion': 'sermon-repair-dependency-closure-v1',
            'graphSha256': c.canonical_sha256(normalized), 'seedWorkUnitIds': sorted(seeds),
            'affectedWorkUnitIds': [u for u in order if u in affected],
            'regenerateWorkUnitIds': [u for u in order if u in affected and nodes[u]['layer'] == 2],
            'invalidateWorkUnitIds': [u for u in order if u in affected and nodes[u]['layer'] >= 3],
            'reuseEligibleWorkUnitIds': [u for u in order if u not in affected]}


def _lineage(candidate, prior_revisions, prior_repairs):
    c.require(type(prior_revisions) in (list, tuple) and type(prior_repairs) in (list, tuple)
              and len(prior_revisions) == len(prior_repairs) == candidate['revisionNumber'] - 1, 'incomplete_revision_chain')
    chain = [*prior_revisions, candidate]
    c.validate_revision_lineage(chain[0])
    for i in range(1, len(chain)):
        c.validate_revision_lineage(chain[i], chain[i-1], prior_repairs[i-1])
    c.require(len({r['revisionId'] for r in chain}) == len(chain), 'reused_revision_identity')
    return chain[0]['revisionId']


def _budget(snapshot, candidate, root_revision, state_revision):
    if snapshot is None:
        return None
    c.require(type(snapshot) is BudgetSnapshot and type(snapshot.limits) is Limits, 'invalid_budget_snapshot')
    c.require(all(_sha(getattr(snapshot, key)) for key in ('production_run_id', 'state_revision',
              'authorization_sha256', 'global_budget_sha256')), 'invalid_budget_evidence')
    c.require((snapshot.candidate_id, snapshot.work_unit_id, snapshot.chain_root_revision_id,
               snapshot.current_revision_id, snapshot.state_revision) == (candidate['candidateId'],
               candidate['workUnitIds'][0], root_revision, candidate['revisionId'], state_revision), 'budget_binding_mismatch')
    for key, maximum in (('content_revisions', 2), ('review_attempts_per_revision', 2), ('decision_proposals_per_chain', 1)):
        value = getattr(snapshot.limits, key)
        c.require(type(value) is int and 0 <= value <= maximum, 'invalid_planning_limit')
    for key in ('content_revisions_reserved', 'review_attempts_reserved', 'decision_proposals_reserved'):
        c.require(type(getattr(snapshot, key)) is int and getattr(snapshot, key) >= 0, 'invalid_reserved_counter')
    c.require(snapshot.content_revisions_reserved >= candidate['revisionNumber'] - 1
              and snapshot.review_attempts_reserved >= 1, 'budget_counter_reset')
    for key, predicate in (('unresolved_operation_ids', _label), ('prior_failure_fingerprints', _sha)):
        values = getattr(snapshot, key)
        c.require(type(values) is tuple and len(values) <= 1024 and all(predicate(v) for v in values)
                  and len(values) == len(set(values)), 'invalid_budget_history')
    # Canonical JSON has lists, not Python tuples.
    row = asdict(snapshot)
    row['unresolved_operation_ids'] = list(snapshot.unresolved_operation_ids)
    row['prior_failure_fingerprints'] = list(snapshot.prior_failure_fingerprints)
    return row


def _ref(kind, value):
    digest = c.canonical_sha256(value)
    return {'artifactId': kind + '.' + digest, 'canonicalJsonSha256': digest,
            'fileBytesSha256': c.bytes_sha256(c.canonical_bytes(value)), 'mediaType': 'application/json'}


def plan_repair(*, candidate, candidate_bytes, review, review_bytes, rubric, input_manifest,
                gate, state_revision, graph, budget=None, prior_revisions=(), prior_repairs=(),
                scope_ambiguous=False, saved_review_response=False, persistence_failed=False):
    """Return a proposal plus sidecars; executionAuthority is always 'none'.

    gate uses the unchanged D1 Gate Decision contract, supplied by D4. Raw saved
    response/persistence flags are trusted durable-job observations, not model
    output. A saved response is recovered without a fresh review request. Unknown
    operation identities always require reconciliation before any new work.
    """
    c.validate_candidate_artifact(candidate, candidate_bytes)
    c.require(c.decode_json(review_bytes) == review, 'review_bytes_mismatch')
    c.validate_review_binding(review, candidate, rubric, input_manifest)
    c.validate_contract(gate)
    c.require(gate['schemaVersion'] == 'sermon-review-gate-decision-v1' and _sha(state_revision)
              and gate['stateRevision'] == state_revision, 'stale_gate_state')
    for key in ('candidateId', 'revisionId', 'targetLocale', 'workUnitIds', 'artifactSha256', 'policySha256'):
        c.require(gate[key] == candidate[key], 'gate_candidate_binding_mismatch')
    c.require(gate['rubricSha256'] == review['rubricSha256'], 'gate_rubric_mismatch')
    c.require(any(ref['canonicalJsonSha256'] == c.canonical_sha256(review)
                  and ref['fileBytesSha256'] == c.bytes_sha256(review_bytes)
                  for ref in gate['reviewReceiptRefs']), 'gate_review_reference_missing')
    c.require(all(type(v) is bool for v in (scope_ambiguous, saved_review_response, persistence_failed)), 'invalid_recovery_observation')
    root_revision = _lineage(candidate, prior_revisions, prior_repairs)
    budget_row = _budget(budget, candidate, root_revision, state_revision)
    closure = dependency_closure(graph, candidate['workUnitIds'])
    c.require(candidate['workUnitIds'][0] in closure['regenerateWorkUnitIds'], 'candidate_not_layer2_dependency')
    reasons = sorted({issue['reasonCode'] for issue in review['issues']})
    fingerprint = c.canonical_sha256({'candidateId': candidate['candidateId'],
        'artifactSha256': candidate['artifactSha256'], 'sourceIdentitySha256': candidate['sourceIdentitySha256'],
        'sourcePackageSha256': candidate['sourcePackageSha256'], 'anchorSha256': candidate['anchorSha256'],
        'policySha256': candidate['policySha256'], 'rubricSha256': review['rubricSha256'], 'reasonCodes': reasons})
    action, reason = None, 'no_repair_required'
    if review['executionStatus'] == 'outcome_unknown' or budget is not None and budget.unresolved_operation_ids:
        action, reason = 'reconcile', 'review_outcome_unknown'
    elif persistence_failed or saved_review_response and review['executionStatus'] in {'failed', 'cancelled'}:
        action, reason = 'reconcile', 'recover_persisted_review_evidence'
    elif 'stale_identity' in gate['reasonCodes'] or 'unknown_rubric' in gate['reasonCodes']:
        action, reason = 'reconcile', 'invalid_gate_evidence'
    elif 'review_conflict' in gate['reasonCodes'] or 'contradictory_reviews' in reasons:
        action, reason = 'request_human_review', 'contradictory_reviews'
    elif 'source_not_ready' in gate['reasonCodes'] or 'source_ambiguity' in reasons:
        action, reason = 'request_source_review', 'source_ambiguity'
    elif review['executionStatus'] in {'failed', 'cancelled'}:
        action, reason = 'retry_review', 'review_execution_failed'
    elif review['reviewVerdict'] in {'inconclusive', 'not_assessed'} or 'evidence_insufficient' in reasons:
        action, reason = 'request_human_review', 'evidence_insufficient'
    elif review['reviewVerdict'] == 'needs_rework':
        action, reason = 'repair_translation', 'known_content_failure'
        if not reasons or not set(reasons) <= CONTENT_FAILURES:
            action, reason = 'escalate_engineering', 'unsupported_content_failure'
    elif gate['admissionStatus'] != 'admitted':
        action, reason = 'request_human_review', 'gate_requires_review'
    status = 'proposal' if action else 'no_repair'
    # Recovery is a stop condition even if a stale/buggy gate offered a retry.
    if action == 'reconcile':
        status = 'reconciliation_required'
    elif action is not None and action not in gate['allowedNextActions']:
        status, reason = 'blocked', 'gate_action_not_allowed'
    if action in {'repair_translation', 'retry_review'} and status == 'proposal':
        if budget is None:
            status, reason = 'blocked', 'durable_budget_snapshot_required'
        elif action == 'repair_translation' and budget.content_revisions_reserved >= budget.limits.content_revisions:
            status, reason = 'blocked', 'content_revision_limit_reached'
        elif action == 'retry_review' and budget.review_attempts_reserved >= budget.limits.review_attempts_per_revision:
            status, reason = 'blocked', 'review_execution_limit_reached'
        elif action == 'repair_translation' and fingerprint in budget.prior_failure_fingerprints:
            status, reason = 'blocked', 'repeated_failure_without_new_evidence'
    if scope_ambiguous and action != 'reconcile':
        c.require(action == 'repair_translation', 'only_content_scope_can_be_delegated')
        if status == 'proposal':
            if budget.decision_proposals_reserved >= budget.limits.decision_proposals_per_chain:
                status, reason = 'blocked', 'decision_proposal_limit_reached'
            else:
                status, reason = 'decision_proposal_required', 'semantic_repair_scope_ambiguous'
    constraints = {'schemaVersion': 'sermon-repair-constraints-v1', 'routingVersion': ROUTING_VERSION,
        'candidateId': candidate['candidateId'], 'rootRevisionId': root_revision,
        'stateRevision': state_revision, 'executionAuthority': 'none',
        'requiredDurableChecks': list(REQUIRED_DURABLE_CHECKS),
        'preserveSourcePolicyRubric': True, 'preservePriorArtifacts': True,
        'requireGenerationReviewPluginAndAdmission': action == 'repair_translation'}
    effective_closure = closure if action in {'repair_translation', 'request_source_review'} else None
    result = {'routingVersion': ROUTING_VERSION, 'status': status, 'action': action, 'reasonCode': reason,
        'executionAuthority': 'none', 'durableIntegration': 'pending', 'candidateId': candidate['candidateId'],
        'targetLocale': candidate['targetLocale'], 'workUnitIds': candidate['workUnitIds'][:],
        'revisionNumber': candidate['revisionNumber'],
        'allowedGateActions': sorted(gate['allowedNextActions']),
        'fromRevisionId': candidate['revisionId'], 'toRevisionId': candidate['revisionId'],
        'stateRevision': state_revision, 'failureFingerprint': fingerprint,
        'repairPlan': None, 'dependencyClosure': effective_closure, 'constraints': constraints,
        'budgetSnapshot': budget_row, 'requiredDurableChecks': list(REQUIRED_DURABLE_CHECKS),
        'requiresFreshProviderRequest': status == 'proposal' and action in {'repair_translation', 'retry_review'},
        'dependencyGroupsRequiringOwnPlans': []}
    if action != 'repair_translation' or status != 'proposal':
        # D1 permits same-candidate recovery plans, but reconcile has no such
        # action and outcome_unknown must never pass validate_repair_binding.
        if action != 'retry_review' or status != 'proposal':
            return result
    if action == 'repair_translation':
        identity = {key: candidate[key] for key in ('candidateId', 'revisionId', 'artifactSha256', 'policySha256')}
        identity.update(triggerReceiptSha256=review['receiptSha256'], routingVersion=ROUTING_VERSION)
        result['toRevisionId'] = 'revision.' + c.canonical_sha256(identity)
        result['dependencyGroupsRequiringOwnPlans'] = [u for u in closure['regenerateWorkUnitIds'] if u not in candidate['workUnitIds']]
    # Review-only recovery has an empty invalidation closure.
    plan_closure = effective_closure or {'schemaVersion': 'sermon-repair-dependency-closure-v1',
        'graphSha256': closure['graphSha256'], 'seedWorkUnitIds': candidate['workUnitIds'][:],
        'affectedWorkUnitIds': candidate['workUnitIds'][:], 'regenerateWorkUnitIds': [],
        'invalidateWorkUnitIds': [], 'reuseEligibleWorkUnitIds': sorted(
            set(closure['affectedWorkUnitIds'] + closure['reuseEligibleWorkUnitIds']))}
    result['dependencyClosure'] = plan_closure
    plan = {key: candidate[key] for key in ('candidateId', 'targetLocale', 'sourceIdentitySha256',
            'sourcePackageSha256', 'anchorSha256', 'policySha256')}
    plan.update(schemaVersion='sermon-review-repair-plan-v1', triggerReviewId=review['reviewId'],
        triggerReceiptSha256=review['receiptSha256'], rubricSha256=review['rubricSha256'],
        fromRevisionId=candidate['revisionId'], toRevisionId=result['toRevisionId'],
        affectedWorkUnitIds=candidate['workUnitIds'][:], dependencyClosureRef=_ref('closure', plan_closure),
        reasonCodes=reasons if action == 'repair_translation' else ['review_execution_failed'],
        repairAction=action, constraintsRef=_ref('constraints', constraints), budgetRef=_ref('budget', budget_row),
        stateRevision=state_revision, createdAt=gate['createdAt'])
    plan['repairPlanId'] = 'repair.' + c.canonical_sha256(plan)
    c.validate_repair_binding(plan, review, candidate)
    result['repairPlan'] = plan
    return copy.deepcopy(result)


def build_ambiguous_packet(planning, *, budget):
    """Prepare existing bounded-decision input; never invoke propose/responder.

    The legacy packet's text.<locale> granularity is bound to the exact group and
    closure through evidenceIdentitySha256; it cannot authorize locale-wide work.
    """
    c.require(planning['status'] == 'decision_proposal_required' and planning['executionAuthority'] == 'none'
              and planning['durableIntegration'] == 'pending', 'not_an_ambiguous_proposal')
    target_locale = planning['targetLocale']
    c.require(type(budget) is BudgetSnapshot and target_locale in {'zh-Hans', 'ko', 'es'}
              and planning['workUnitIds'] == [budget.work_unit_id]
              and budget.work_unit_id.startswith(f'l2.{target_locale}.')
              and planning['budgetSnapshot'] == _budget(budget,
                  {'candidateId': planning['candidateId'], 'workUnitIds': [budget.work_unit_id],
                   'revisionId': planning['fromRevisionId'], 'revisionNumber': planning['revisionNumber']},
                  planning['constraints']['rootRevisionId'], planning['stateRevision']), 'decision_budget_binding_mismatch')
    c.require(not budget.unresolved_operation_ids and budget.decision_proposals_reserved < budget.limits.decision_proposals_per_chain,
              'decision_proposal_limit_reached')
    mapping = {'repair_translation': 'open_text_revision', 'request_human_review': 'request_human_review',
               'escalate_engineering': 'escalate_engineering'}
    allowed_gate_actions = planning['allowedGateActions']
    c.require(type(allowed_gate_actions) is list and all(type(a) is str for a in allowed_gate_actions), 'invalid_decision_actions')
    actions = sorted({mapping[a] for a in allowed_gate_actions if a in mapping})
    c.require(len(actions) >= 2, 'decision_requires_multiple_allowed_actions')
    evidence = c.canonical_sha256(planning)
    return decision.build_packet(productionRunId=budget.production_run_id, stateRevision=budget.state_revision,
        currentStage='L2', triggeringFailureCode='semantic_repair_scope_ambiguous',
        affectedWorkUnits=['text.' + target_locale], allowedActions=actions, evidenceRefs=[evidence],
        evidenceIdentitySha256=evidence, retryBudget={'remainingDecisionAttempts': 1, 'maxTurns': 1},
        qualityGateSummary='blocked', priorDecisionSummary=[])


def validate_ambiguous_proposal(packet, proposal, fresh_packet):
    """Validate only; controller must still reserve/admit in the durable store."""
    packet = decision.validate_packet(packet)
    c.require(packet['currentStage'] == 'L2'
              and packet['triggeringFailureCode'] == 'semantic_repair_scope_ambiguous'
              and len(packet['affectedWorkUnits']) == 1
              and packet['affectedWorkUnits'][0].startswith('text.'), 'unsupported_rqc_decision_scope')
    c.require(packet['retryBudget'] == {'remainingDecisionAttempts': 1, 'maxTurns': 1}, 'invalid_rqc_decision_limit')
    checked = decision.validate_decision(packet, proposal, fresh_packet)
    mapping = {'open_text_revision': ('repair_translation', 'text_repair_needed'),
               'request_human_review': ('request_human_review', 'human_evidence_needed'),
               'escalate_engineering': ('escalate_engineering', 'unsupported_recovery')}
    c.require(checked['selectedAction'] in mapping, 'unsupported_rqc_decision_action')
    action, reason = mapping[checked['selectedAction']]
    c.require(checked['reasonCode'] == reason and checked['evidenceRefs'] == packet['evidenceRefs'], 'decision_evidence_or_reason_mismatch')
    return {'action': action, 'proposal': checked, 'executionAuthority': 'none',
            'durableIntegration': 'pending', 'requiredDurableChecks': list(REQUIRED_DURABLE_CHECKS)}
