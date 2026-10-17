"""Safe Source terminal metadata, never provider text, paths or a refund."""
from scripts import sermon_review_contracts as c
from scripts.sermon_pipeline import PreDispatchRejection,PRE_DISPATCH_REASONS
SCHEMA='sermon-fresh-diagnostic-source-failure-v2'
REASONS=frozenset(['attempt_parent_reconciliation_required', 'diagnostic_continuation_code_changed', 'diagnostic_dag_binding_changed', 'diagnostic_prior_outcome_requires_reconciliation', 'fresh_alignment_prior_artifact_changed', 'fresh_alignment_prior_asr_changed', 'fresh_alignment_prior_source_changed', 'fresh_alignment_required', 'fresh_alignment_snapshot_invalid', 'fresh_anchor_contract_invalid', 'fresh_english_source_contract_invalid', 'fresh_local_mfa', 'fresh_local_mfa_runtime_required', 'fresh_mfa_alignment_invalid', 'fresh_mfa_command_failed', 'fresh_mfa_original_deadline_changed', 'fresh_mfa_original_deadline_reached', 'fresh_mfa_runtime_file_changed', 'fresh_mfa_runtime_unavailable', 'fresh_source_asr_text_missing', 'fresh_source_audio_changed', 'fresh_source_cache_alignment_binding_changed', 'fresh_source_cache_alignment_mode_invalid', 'fresh_source_cache_anchor_artifact_changed', 'fresh_source_cache_artifact_changed', 'fresh_source_cache_artifact_invalid', 'fresh_source_cache_artifact_required', 'fresh_source_cache_attempt_authorization_changed', 'fresh_source_cache_audio_changed', 'fresh_source_cache_clip_changed', 'fresh_source_cache_closed_parent_required', 'fresh_source_cache_code_binding_changed', 'fresh_source_cache_current_source_changed', 'fresh_source_cache_distinct_parent_required', 'fresh_source_cache_fixed_provider_required', 'fresh_source_cache_frozen_evidence_changed', 'fresh_source_cache_lineage_changed', 'fresh_source_cache_mfa_backend_changed', 'fresh_source_cache_mfa_file_changed', 'fresh_source_cache_parent_close_changed', 'fresh_source_cache_parent_not_in_lineage', 'fresh_source_cache_parent_unsettled', 'fresh_source_cache_producer_code_changed', 'fresh_source_cache_provider_receipt_changed', 'fresh_source_cache_review_asr_binding_changed', 'fresh_source_cache_review_content_changed', 'fresh_source_cache_runtime_binding_changed', 'fresh_source_cache_simulation_changed', 'fresh_source_cache_source_evidence_changed', 'fresh_source_cache_source_implementation_changed', 'fresh_source_cache_source_scope_changed', 'fresh_source_cache_summary_changed', 'fresh_source_cache_test_authorization_required', 'fresh_source_check_asr_binding_changed', 'fresh_source_check_response_incomplete', 'fresh_source_check_response_invalid', 'fresh_source_prior_summary_changed', 'fresh_source_provider_binding_changed', 'fresh_source_provider_outcome_unknown', 'fresh_source_provider_snapshot_changed', 'fresh_source_receipt_binding_changed', 'fresh_source_returned_receipt_required', 'fresh_source_test_authorization_required'])
RECONCILIATION=frozenset({'fresh_source_provider_outcome_unknown',
    'diagnostic_prior_outcome_requires_reconciliation','attempt_parent_reconciliation_required'})


def receipt(error,*,plan,provider_snapshot):
    reason=str(error) if type(error) is c.ContractError and str(error) in REASONS else 'source_preparation_not_confirmed'
    if isinstance(error,PreDispatchRejection) and error.reason_code in PRE_DISPATCH_REASONS:
        reason=error.reason_code
    if type(error) is c.ContractError and str(error)=='invalid_snapshot_file':
        reason='fresh_source_snapshot_invalid'
    known=type(provider_snapshot) is dict and type(provider_snapshot.get('unknownModelCallIds')) is list
    unknown=len(provider_snapshot['unknownModelCallIds']) if known else None
    reconciliation=not known or bool(unknown) or reason in RECONCILIATION
    return {'schemaVersion':SCHEMA,'status':'reconciliation_required' if reconciliation else 'blocked',
        'reasonCode':reason,'errorType':type(error).__name__,'runId':plan['providerConfig']['runId'],
        'planSha256':c.canonical_sha256(plan),'providerSnapshotSha256':c.canonical_sha256(provider_snapshot) if known else None,
        'providerUnknownCount':unknown,'requiresReconciliation':reconciliation,
        'budgetBasis':'original_worst_case_reservations_no_refunds',
        'productionEligible':False,'humanAcceptance':'pending','executionAuthority':'none'}
