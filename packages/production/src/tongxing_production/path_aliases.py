"""Where a file named by a legacy identity key lives today.

Hash tables, closures and loaded-code maps keep the ``scripts/...`` names they
were recorded under. A file that moved into the production package with
unchanged bytes is reached through its alias, so a hash recorded under the
legacy key still describes the same file. One section per layer; each batch
adds the files it moves.
"""

PRODUCTION = 'packages/production/src/tongxing_production/'

# Layer 1 Source (tongxing_production.source), batches S1-S4.
_SOURCE = PRODUCTION + 'source/'
LAYER1 = {
    'scripts/sermon_sentence_interpretation.py': _SOURCE + 'sentence_interpretation.py',
    'scripts/mfa_alignment.py': _SOURCE + 'mfa_alignment.py',
    'scripts/sermon_source_producer_compatibility.py': _SOURCE + 'producer_compatibility.py',
    'scripts/sermon_mfa_identity.py': _SOURCE + 'mfa_identity.py',
    'scripts/build_english_source_package.py': _SOURCE + 'english_source_package.py',
    'scripts/judge_english_source_for_translation.py': _SOURCE + 'english_source_judge.py',
    'scripts/english_source_judge_cache.py': _SOURCE + 'english_source_judge_cache.py',
    'scripts/run_sentence_interpretation_models.py': _SOURCE + 'sentence_interpretation_models.py',
    'scripts/sermon_source_budget.py': _SOURCE + 'budget.py',
    'scripts/sermon_source_text_review.py': _SOURCE + 'text_review.py',
    'scripts/mfa_backend.py': _SOURCE + 'mfa_backend.py',
    'scripts/mfa_spark.py': _SOURCE + 'mfa_spark.py',
    'scripts/sermon_unified_source.py': _SOURCE + 'unified_stage.py',
}

# Layer 2 Text (tongxing_production.text), batches T1-T4.
_TEXT = PRODUCTION + 'text/'
LAYER2 = {
    'scripts/target_language_policy.py': _TEXT + 'policy.py',
    'scripts/target_language_policy_preview.py': _TEXT + 'policy_preview.py',
    'scripts/produce_target_language_candidate.py': _TEXT + 'candidate.py',
    'scripts/target_language_rule_preflight.py': _TEXT + 'rule_preflight.py',
    'scripts/run_target_language_models.py': _TEXT + 'models.py',
    'scripts/migrate_target_language_model_cache.py': _TEXT + 'model_cache_migration.py',
    'scripts/canonical_layer2_budget.py': _TEXT + 'budget.py',
    'scripts/canonical_layer2_controller.py': _TEXT + 'controller.py',
    'scripts/layer2_auto_repair.py': _TEXT + 'auto_repair.py',
    'scripts/layer2_human_ruling.py': _TEXT + 'human_ruling.py',
    'scripts/canonical_layer2_cache_recovery.py': _TEXT + 'cache_recovery.py',
    'scripts/canonical_layer2_reconciliation.py': _TEXT + 'reconciliation.py',
    'scripts/review_target_language_candidate.py': _TEXT + 'human_review.py',
    'scripts/sermon_unified_layer2_binding.py': _TEXT + 'unified_binding.py',
}

# Layer 3 Audio (tongxing_production.audio), batches A1-A4.
_AUDIO = PRODUCTION + 'audio/'
LAYER3 = {
    'scripts/target_audio_anomaly.py': _AUDIO + 'anomaly.py',
    'scripts/target_audio_recovery.py': _AUDIO + 'recovery.py',
    'scripts/clip_timeline_map.py': _AUDIO + 'clip_timeline.py',
    'scripts/review_target_language_audio.py': _AUDIO + 'human_review.py',
    'scripts/dev_audio_test_profile.py': _AUDIO + 'dev_profile.py',
    'scripts/dev_audio_test_receipts.py': _AUDIO + 'dev_receipts.py',
    'scripts/prepare_target_language_speech_job.py': _AUDIO + 'speech_job.py',
}

# Shared compute (tongxing_production.compute): stage 1, infrastructure I0b and the audio batches.
COMPUTE = {
    'scripts/sermon_provider_limits.py': PRODUCTION + 'compute/provider_limits.py',
    # Infrastructure I0b: waiver closure members, moved byte for byte.
    'scripts/sermon_openai_runtime.py': PRODUCTION + 'compute/openai_runtime.py',
    'scripts/sermon_transcription_request.py': PRODUCTION + 'compute/transcription_request.py',
    # Layer 3 A1: the audio CPU limiter, moved byte for byte.
    'scripts/bounded_audio_cpu.py': PRODUCTION + 'compute/bounded_audio_cpu.py',
    # workflows/compute C1: byte-identical leaves.
    'scripts/sermon_provider_http.py': PRODUCTION + 'compute/provider_http.py',
    'scripts/sermon_provider_error.py': PRODUCTION + 'compute/sermon_provider_error.py',
    'scripts/layer2_api_concurrency.py': PRODUCTION + 'compute/api_concurrency.py',
    'scripts/production_concurrency_profile.py': PRODUCTION + 'compute/concurrency_profile.py',
    'scripts/sermon_unified_runtime_identity.py': PRODUCTION + 'compute/runtime_identity.py',
}

# Layer 4 Delivery (tongxing_production.delivery), batches D1-D9.
_DELIVERY = PRODUCTION + 'delivery/'
_LEGACY = PRODUCTION + 'adapters/legacy/'
LAYER4 = {
    'scripts/delivery_contract.py': _DELIVERY + 'contract.py',
    'scripts/study_artifacts.py': _DELIVERY + 'study_artifacts.py',
    'scripts/release_asset_io.py': _DELIVERY + 'asset_io.py',
    'scripts/sermon_delivery_intent.py': _DELIVERY + 'intent.py',
    # D7: the legacy v2/v3 group keeps its module names (design decision 5).
    'scripts/assemble_multilingual_hosting.py': _LEGACY + 'assemble_multilingual_hosting.py',
    'scripts/deploy_multilingual_hosting.py': _LEGACY + 'deploy_multilingual_hosting.py',
    'scripts/verify_multilingual_hosting.py': _LEGACY + 'verify_multilingual_hosting.py',
    'scripts/assemble_multilingual_v3_update.py': _LEGACY + 'assemble_multilingual_v3_update.py',
    'scripts/refresh_multilingual_hosting_with_legacy.py': _LEGACY + 'refresh_multilingual_hosting_with_legacy.py',
    'scripts/production_content_release_admission.py': _LEGACY + 'production_content_release_admission.py',
    'scripts/multilingual_dev_preview.py': _LEGACY + 'multilingual_dev_preview.py',
    'scripts/seal_multilingual_dev_catalog.py': _LEGACY + 'seal_multilingual_dev_catalog.py',
    'scripts/build_multilingual_catalog.py': _LEGACY + 'build_multilingual_catalog.py',
    'scripts/inspect_multilingual_v3_release.py': _LEGACY + 'inspect_multilingual_v3_release.py',
    'scripts/verify_v3_bucket_video.py': _LEGACY + 'verify_v3_bucket_video.py',
    'scripts/build_sermon_poster.py': _LEGACY + 'build_sermon_poster.py',
    'scripts/build_multilingual_sermon_posters.py': _DELIVERY + 'posters/build.py',
    'scripts/weekly_poster_template.py': _DELIVERY + 'posters/template.py',
    # D4: the App workflow's implementationSha256 keys stay these legacy paths.
    'scripts/sermon_app_delivery.py': _DELIVERY + 'app_delivery.py',
    'scripts/sermon_app_delivery_workflow.py': _DELIVERY + 'app_workflow.py',
}

# Cross-layer review (tongxing_production.review), batches R1-R4.
_REVIEW = PRODUCTION + 'review/'
REVIEW = {
    # R1: standard-library leaves moved byte for byte; the ledger is a waiver closure member.
    'scripts/machine_repair_ledger.py': _REVIEW + 'repair_ledger.py',
    'scripts/audio_qc_human_acceptance.py': _REVIEW + 'audio_qc_acceptance.py',
    'scripts/text_qc_human_acceptance.py': _REVIEW + 'text_qc_acceptance.py',
    # I1 split the legacy review contract module across review and contracts.
    'scripts/sermon_review_contracts.py': _REVIEW + 'contracts.py',
}

# Prepared-workflow composition (tongxing_production.workflows.prepared), batch W2.
_PREPARED = PRODUCTION + 'workflows/prepared/'
WORKFLOWS = {
    'scripts/sermon_unified_continuation.py': _PREPARED + 'continuation.py',
    'scripts/sermon_unified_capabilities.py': _PREPARED + 'capabilities.py',
    'scripts/sermon_unified_canonical_binding.py': _PREPARED + 'canonical_binding.py',
    'scripts/sermon_unified_study.py': _PREPARED + 'study.py',
    'scripts/sermon_study_generation.py': _PREPARED + 'study_generation.py',
}

# Shared infrastructure, batches I1-I4 (docs/design/infrastructure-injection.zh.md).
CONTRACTS = {       # tongxing_production.contracts, batch I1
    'scripts/canonical_pipeline_definition.py': PRODUCTION + 'contracts/pipeline_definition.py',
}
STORAGE = {}        # tongxing_production.storage, batch I2
OBSERVABILITY = {}  # tongxing_production.observability, batches I3-I4

# I1 moved generic portions of the legacy review module to contracts; include them
# in closures that still identify the combined legacy module.
# Package files that took over part of a split legacy file; closures that listed
# the legacy key list these as well, so they cover the same code as before.
SPLIT_MEMBERS = {
    'scripts/sermon_review_contracts.py': (PRODUCTION + 'contracts/canonical.py', PRODUCTION + 'contracts/schemas.py'),
}

PATH_ALIASES = {**COMPUTE, **CONTRACTS, **STORAGE, **OBSERVABILITY, **LAYER1, **LAYER2, **LAYER3, **LAYER4,
                **REVIEW, **WORKFLOWS}


def resolve(key):
    """Repository-relative path of the file a legacy identity key names today."""
    return PATH_ALIASES.get(key, key)


def recorded(identity, key):
    """Value a loaded-code identity map holds for a key, whichever path recorded it."""
    value = identity.get(resolve(key))
    return identity.get(key) if value is None else value
