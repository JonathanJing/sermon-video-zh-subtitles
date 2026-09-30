"""Bounded decision proposals, with no model SDK, tools, credentials or dispatch.

A trusted controller supplies validated, hash-bound facts and reserves an attempt
under its existing durable lock BEFORE invoking the injected structured responder.
This module never turns a response into approval or retries an unknown outcome.
"""
from __future__ import annotations
import copy
import json

from scripts.canonical_pipeline_definition import LOCALES, VERSION, _sha
from scripts.sermon_workflow_jobs import _digest

PACKET_SCHEMA = 'sermon-decision-state-v1'
DECISION_SCHEMA = 'sermon-decision-v1'
MAX_BYTES = 32 * 1024
MAX_EVIDENCE = 16
MAX_ATTEMPTS = 2
MAX_TURNS = 1
ACTIONS = frozenset({'open_text_revision', 'open_audio_revision', 'request_human_review', 'escalate_engineering'})
FAILURES = {
    'semantic_repair_scope_ambiguous': frozenset({'open_text_revision', 'request_human_review', 'escalate_engineering'}),
    'timing_repair_scope_ambiguous': frozenset({'open_text_revision', 'open_audio_revision', 'request_human_review', 'escalate_engineering'}),
}
REASONS = frozenset({'text_repair_needed', 'audio_repair_needed', 'human_evidence_needed', 'unsupported_recovery'})
GATES = frozenset({'not_evaluated', 'blocked', 'pending_human', 'machine_pass_human_pending'})
UNITS = frozenset({'source'} | {f'{phase}.{locale}' for phase in ('text', 'audio', 'page', 'publish', 'verify', 'record') for locale in LOCALES})
PACKET_FIELDS = frozenset({'schemaVersion', 'decisionId', 'productionRunId', 'stateRevision',
    'workflowDefinitionVersion', 'workflowScope', 'currentStage', 'triggeringFailureCode',
    'affectedWorkUnits', 'allowedActions', 'evidenceRefs', 'evidenceIdentitySha256',
    'retryBudget', 'qualityGateSummary', 'priorDecisionSummary'})
DECISION_FIELDS = frozenset({'schemaVersion', 'decisionId', 'stateRevision', 'packetSha256',
                           'selectedAction', 'affectedWorkUnits', 'reasonCode', 'evidenceRefs'})


def _require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _unique(values, maximum, predicate):
    return (isinstance(values, list) and len(values) <= maximum and
            all(predicate(v) for v in values) and len(set(values)) == len(values))


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def validate_packet(packet):
    _require(isinstance(packet, dict) and set(packet) == PACKET_FIELDS, 'invalid_packet_fields')
    _require(len(_encoded(packet)) <= MAX_BYTES, 'packet_byte_budget_exceeded')
    _require(packet['schemaVersion'] == PACKET_SCHEMA and packet['workflowScope'] == 'four_layer_release'
             and packet['workflowDefinitionVersion'] == VERSION, 'unsupported_workflow_identity')
    _require(all(_sha(packet[k]) for k in ('decisionId', 'productionRunId', 'stateRevision', 'evidenceIdentitySha256')), 'invalid_identity')
    _require(isinstance(packet['currentStage'], str) and packet['currentStage'] in {'L1', 'L2', 'L3', 'L4'}, 'invalid_stage')
    failure = packet['triggeringFailureCode']
    _require(isinstance(failure, str) and failure in FAILURES, 'deterministic_or_unknown_failure_not_delegated')
    _require(_unique(packet['affectedWorkUnits'], len(UNITS), lambda v: isinstance(v, str) and v in UNITS)
             and bool(packet['affectedWorkUnits']), 'invalid_work_units')
    _require(_unique(packet['allowedActions'], len(ACTIONS), lambda v: isinstance(v, str) and v in FAILURES[failure])
             and bool(packet['allowedActions']), 'invalid_allowed_actions')
    _require(_unique(packet['evidenceRefs'], MAX_EVIDENCE, _sha) and bool(packet['evidenceRefs']), 'invalid_evidence_refs')
    budget = packet['retryBudget']
    _require(isinstance(budget, dict) and set(budget) == {'remainingDecisionAttempts', 'maxTurns'}
             and type(budget['remainingDecisionAttempts']) is int
             and 1 <= budget['remainingDecisionAttempts'] <= MAX_ATTEMPTS
             and type(budget['maxTurns']) is int and budget['maxTurns'] == MAX_TURNS, 'invalid_decision_budget')
    _require(isinstance(packet['qualityGateSummary'], str) and packet['qualityGateSummary'] in GATES, 'invalid_quality_gate')
    prior = packet['priorDecisionSummary']
    _require(isinstance(prior, list) and len(prior) <= 4, 'invalid_prior_summary')
    for row in prior:
        _require(isinstance(row, dict) and set(row) == {'decisionSha256', 'reasonCode'}
                 and _sha(row['decisionSha256']) and isinstance(row['reasonCode'], str)
                 and row['reasonCode'] in REASONS, 'invalid_prior_summary')
    expected_id = _digest({k: v for k, v in packet.items() if k != 'decisionId'})
    _require(packet['decisionId'] == expected_id, 'changed_packet_identity')
    return copy.deepcopy(packet)


def build_packet(**facts):
    # No free-text extraction, truncation or conversion from a conversation.
    packet = {'schemaVersion': PACKET_SCHEMA, 'workflowDefinitionVersion': VERSION,
              'workflowScope': 'four_layer_release', **copy.deepcopy(facts)}
    packet['decisionId'] = _digest({k: v for k, v in packet.items() if k != 'decisionId'})
    return validate_packet(packet)


def validate_decision(packet, decision, fresh_packet):
    original, fresh = validate_packet(packet), validate_packet(fresh_packet)
    _require(original == fresh, 'stale_state_or_evidence_or_budget')
    _require(isinstance(decision, dict) and set(decision) == DECISION_FIELDS, 'invalid_decision_fields')
    _require(len(_encoded(decision)) <= MAX_BYTES, 'decision_byte_budget_exceeded')
    _require(decision['schemaVersion'] == DECISION_SCHEMA and decision['decisionId'] == original['decisionId']
             and decision['stateRevision'] == original['stateRevision']
             and decision['packetSha256'] == _digest(original), 'changed_decision_identity')
    _require(isinstance(decision['selectedAction'], str) and decision['selectedAction'] in original['allowedActions'], 'action_not_allowed')
    _require(_unique(decision['affectedWorkUnits'], len(UNITS), lambda v: isinstance(v, str) and v in original['affectedWorkUnits'])
             and bool(decision['affectedWorkUnits']), 'work_units_not_allowed')
    phase = {'open_text_revision': 'text.', 'open_audio_revision': 'audio.'}.get(decision['selectedAction'])
    _require(phase is None or all(unit.startswith(phase) for unit in decision['affectedWorkUnits']), 'action_work_unit_mismatch')
    _require(_unique(decision['evidenceRefs'], MAX_EVIDENCE, lambda v: _sha(v) and v in original['evidenceRefs']), 'evidence_not_allowed')
    _require(isinstance(decision['reasonCode'], str) and decision['reasonCode'] in REASONS, 'reason_not_allowed')
    return copy.deepcopy(decision)


def propose(packet, *, reserve_attempt, responder, fresh_packet):
    """Make at most one reserved, tool-free structured call; never execute it.

    reserve_attempt must atomically enforce the run/decision budget in existing
    controller state. A crash after reservation consumes it; outcome is unknown.
    fresh_packet reads the original admitted budget plus current evidence (the
    reservation itself must not mint a new production revision).
    """
    packet = validate_packet(packet)
    packet_hash = _digest(packet)
    metadata = {'packetSha256': packet_hash, 'packetBytes': len(_encoded(packet)),
                'evidenceRefCount': len(packet['evidenceRefs']), 'parentContextInherited': False,
                'dispatchEnabled': False, 'mutationTools': [], 'maxTurns': MAX_TURNS}
    if reserve_attempt(copy.deepcopy(packet)) is not True:
        return {**metadata, 'status': 'blocked', 'reasonCode': 'decision_budget_unavailable'}
    try:
        # Only a packet copy crosses the boundary, no conversation/tool handles.
        result = responder(copy.deepcopy(packet))
    except Exception:
        return {**metadata, 'status': 'blocked', 'reasonCode': 'decision_outcome_unknown'}
    try:
        decision = validate_decision(packet, result, fresh_packet())
    except Exception:
        return {**metadata, 'status': 'blocked', 'reasonCode': 'decision_rejected'}
    return {**metadata, 'status': 'proposal_requires_locked_admission', 'decision': decision}
