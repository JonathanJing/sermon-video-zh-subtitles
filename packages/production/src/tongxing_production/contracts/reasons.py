"""Fixed reason codes shared across layers."""

# Fixed guard codes only. This type is proof supplied by a trusted guard before
# its transport executor is invoked, never inferred from an exception message.
PRE_DISPATCH_REASONS = frozenset({
    'provider_run_deadline_reached', 'provider_attempt_deadline_reached',
    'provider_request_limit', 'provider_cost_limit', 'provider_source_call_limit',
    'provider_outcome_reconciliation_required', 'provider_call_already_reserved',
    'provider_operation_already_reserved', 'provider_configuration_blocked',
    'provider_run_permanently_closed',
})
