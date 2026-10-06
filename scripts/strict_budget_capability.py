"""DEV-R242-026 admission. No network, credentials, or provider calls.

The 2026-10-05 API-first decision is the independent risk contract: a new
strict text call may reserve only through the frozen default-tier completion
cap. Codex CLI, standalone fast, STE, and quota fallback refuse before any
request. Timeout, average cost, and credit estimates never become a bound.
Unknown observations keep the reservation and do not retry.
"""
from __future__ import annotations

from scripts import sermon_provider_limits as limits

SCHEMA = 'strict-budget-capability-v1'
RESERVING = ('canonical_api', 'study_api', 'source_judge_api')
REFUSED = {
    'codex_cli': 'unsupported_budget_capability',
    'standalone_api': 'fast_tier_lacks_worst_case_authorization',
    'ste': 'ste_not_dispatched',
    'quota_fallback': 'fallback_disabled',
}
IGNORED_SUBSTITUTES = (
    'timeoutSeconds', 'averageCostMicrousd', 'creditEstimate', 'historicalMeanOutputTokens')


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _ignored(substitutes):
    substitutes = {} if substitutes is None else substitutes
    _require(type(substitutes) is dict, 'unknown_budget_substitute')
    _require(set(substitutes) <= set(IGNORED_SUBSTITUTES), 'unknown_budget_substitute')
    return sorted(key for key in IGNORED_SUBSTITUTES if key in substitutes)


def _refused(surface, reason, ignored):
    return {'schemaVersion': SCHEMA, 'surface': surface, 'decision': 'refused',
            'reason': reason, 'requests': 0, 'reservationMicrousd': None,
            'outputTokenCap': None, 'invoiceVerified': False,
            'ignoredSubstitutes': ignored, 'dispatched': False}


def admit(surface, *, payload=None, request_limits=None, substitutes=None):
    """Classify one strict surface. This function never sends a request."""
    ignored = _ignored(substitutes)
    if surface in REFUSED:
        return _refused(surface, REFUSED[surface], ignored)
    _require(surface in RESERVING, 'unknown_strict_budget_surface')
    selected = limits.DEFAULT_REQUEST_LIMITS if request_limits is None else request_limits
    try:
        bounded = limits.bounded_payload(payload, selected)
    except ValueError as exc:
        raise ValueError('unsupported_budget_capability') from exc
    _require(bounded == payload, 'unsupported_budget_capability')
    evidence = limits.request_cost_evidence(payload, selected)
    bounds = evidence['bounds']
    _require(evidence['invoiceVerified'] is False
             and bounds['requests'] == 1
             and bounds['outputTokens'] == selected['maxCompletionTokens']
             and type(bounds['costMicrousd']) is int and bounds['costMicrousd'] > 0,
             'strict_reservation_not_worst_case')
    return {'schemaVersion': SCHEMA, 'surface': surface, 'decision': 'reserved',
            'reason': 'worst_case_completion_cap', 'requests': 1,
            'reservationMicrousd': bounds['costMicrousd'],
            'outputTokenCap': bounds['outputTokens'], 'invoiceVerified': False,
            'ignoredSubstitutes': ignored, 'dispatched': False}


def require_bounded_api_payload(payload, request_limits, *, surface='canonical_api'):
    """Fail before transport unless the payload already carries the worst-case cap."""
    decision = admit(surface, payload=payload, request_limits=request_limits)
    _require(decision['decision'] == 'reserved', decision['reason'])
    return decision


def reject_codex_cli_transport(caller):
    """A bound strict worker cannot use the diagnostic Codex CLI transport."""
    identity = getattr(caller, 'execution_identity', None)
    backend = identity.get('backend') if type(identity) is dict else None
    if backend == 'codex_cli' or caller.__class__.__name__ == 'CodexLayer2Transport':
        raise ValueError('unsupported_budget_capability')


def reconcile_unknown(reservation_microusd, observation=None):
    """Missing usage stays reserved. A measurement is an estimate, not an invoice or a retry."""
    _require(type(reservation_microusd) is int and reservation_microusd > 0, 'reservation_required')
    measured = None if observation is None else limits.usage_resolver(observation)
    if measured is None:
        return {'status': 'unknown', 'reservationMicrousd': reservation_microusd,
                'released': False, 'retry': False, 'settledMicrousd': None, 'invoiceVerified': False}
    _require(measured['costMicrousd'] <= reservation_microusd, 'measured_estimate_exceeds_reservation')
    return {'status': 'estimated', 'reservationMicrousd': reservation_microusd,
            'released': False, 'retry': False, 'settledMicrousd': measured['costMicrousd'],
            'invoiceVerified': False}
