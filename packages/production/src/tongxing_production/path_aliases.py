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
}

# Shared compute (tongxing_production.compute), stage 1.
COMPUTE = {
    'scripts/sermon_provider_limits.py': PRODUCTION + 'compute/provider_limits.py',
}

# Layer 4 Delivery (tongxing_production.delivery), batches D1-D9.
_DELIVERY = PRODUCTION + 'delivery/'
LAYER4 = {
    'scripts/delivery_contract.py': _DELIVERY + 'contract.py',
    'scripts/study_artifacts.py': _DELIVERY + 'study_artifacts.py',
    'scripts/release_asset_io.py': _DELIVERY + 'asset_io.py',
    'scripts/sermon_delivery_intent.py': _DELIVERY + 'intent.py',
}

# Shared infrastructure, batches I1-I4 (docs/design/infrastructure-injection.zh.md).
CONTRACTS = {}      # tongxing_production.contracts, batch I1
STORAGE = {}        # tongxing_production.storage, batch I2
OBSERVABILITY = {}  # tongxing_production.observability, batches I3-I4

PATH_ALIASES = {**COMPUTE, **CONTRACTS, **STORAGE, **OBSERVABILITY, **LAYER1, **LAYER2, **LAYER4}


def resolve(key):
    """Repository-relative path of the file a legacy identity key names today."""
    return PATH_ALIASES.get(key, key)


def recorded(identity, key):
    """Value a loaded-code identity map holds for a key, whichever path recorded it."""
    value = identity.get(resolve(key))
    return identity.get(key) if value is None else value
