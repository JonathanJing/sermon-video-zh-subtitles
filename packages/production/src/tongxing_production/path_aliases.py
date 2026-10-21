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
    # workflows/compute W3a: the versioned review prompts, moved byte for byte.
    'scripts/review_prompts.py': _SOURCE + 'review_prompts.py',
    'scripts/sermon_sentence_interpretation.py': _SOURCE + 'sentence_interpretation.py',
    'scripts/prepare_sentence_interpretation_shadow.py': _SOURCE + 'sentence_interpretation_shadow.py',
    'scripts/mfa_alignment.py': _SOURCE + 'mfa_alignment.py',
    'scripts/sermon_source_producer_compatibility.py': _SOURCE + 'producer_compatibility.py',
    'scripts/sermon_source_failure.py': _SOURCE + 'failure.py',
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
    'scripts/sermon_cuv_translation.py': _TEXT + 'cuv_translation.py',
    'scripts/cuv_preflight.py': _TEXT + 'cuv_preflight.py',
    'scripts/sermon_review_diagnostics.py': _TEXT + 'review_diagnostics.py',
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
    # L3 A3, the identity generation (closure window G1).
    'scripts/validate_target_language_audio_unit.py': _AUDIO + 'unit_integrity.py',
    'scripts/screen_target_language_audio_units.py': _AUDIO + 'screening.py',
    'scripts/build_target_language_audio_package.py': _AUDIO + 'package.py',
    'scripts/render_formal_target_language_speech.py': _AUDIO + 'renderer.py',
    'scripts/compact_formal_target_audio.py': _AUDIO + 'compaction.py',
    'scripts/target_audio_predicted_schedule.py': _AUDIO + 'predicted_schedule.py',
    'scripts/target_audio_timing_plan.py': _AUDIO + 'timing_plan.py',
    # L3 A4, stage entry and operator tools.
    'scripts/sermon_unified_audio.py': _AUDIO + 'unified_stage.py',
    'scripts/render_speculative_target_language_speech.py': _AUDIO + 'speculative.py',
    'scripts/inspect_canonical_audio.py': _AUDIO + 'inspect.py',
}

# Shared compute (tongxing_production.compute): stage 1, infrastructure I0b and the audio batches.
COMPUTE = {
    'scripts/sermon_provider_limits.py': PRODUCTION + 'compute/provider_limits.py',
    # Infrastructure I0b: waiver closure members, moved byte for byte.
    'scripts/sermon_openai_runtime.py': PRODUCTION + 'compute/openai_runtime.py',
    'scripts/sermon_transcription_request.py': PRODUCTION + 'compute/transcription_request.py',
    # Layer 3 A1: the audio CPU limiter, moved byte for byte.
    'scripts/bounded_audio_cpu.py': PRODUCTION + 'compute/bounded_audio_cpu.py',
    # L3 A3: the Spark TTS workers, moved byte for byte.
    'scripts/spark_tts_replica_pool.py': PRODUCTION + 'compute/spark_tts_replica_pool.py',
    'scripts/spark_tts_window_scheduler.py': PRODUCTION + 'compute/spark_tts_window_scheduler.py',
    # workflows/compute C1: byte-identical leaves.
    'scripts/sermon_provider_http.py': PRODUCTION + 'compute/provider_http.py',
    'scripts/sermon_provider_error.py': PRODUCTION + 'compute/sermon_provider_error.py',
    'scripts/layer2_api_concurrency.py': PRODUCTION + 'compute/api_concurrency.py',
    'scripts/production_concurrency_profile.py': PRODUCTION + 'compute/concurrency_profile.py',
    'scripts/sermon_unified_runtime_identity.py': PRODUCTION + 'compute/runtime_identity.py',
    'scripts/spark_exclusive_session.py': PRODUCTION + 'compute/spark_exclusive_session.py',
    # workflows/compute C2: admission and reconciliation.
    'scripts/api_cli_outcomes.py': PRODUCTION + 'compute/outcomes.py',
    'scripts/production_spark_admission.py': PRODUCTION + 'compute/spark_admission.py',
    'scripts/strict_budget_capability.py': PRODUCTION + 'compute/budget_capability.py',
    # workflows/compute C3: the transports, one identity generation.
    'scripts/claude_layer2_transport.py': PRODUCTION + 'compute/transports/claude_layer2.py',
    'scripts/codex_layer2_transport.py': PRODUCTION + 'compute/transports/codex_layer2.py',
    'scripts/openai_layer2_transport.py': PRODUCTION + 'compute/transports/openai_layer2.py',
    'scripts/codex_layer2_resources.py': PRODUCTION + 'compute/transports/codex_resources.py',
    'scripts/sermon_codex_transport.py': PRODUCTION + 'compute/transports/codex_cli.py',
    # Closure window G1: the audio QC transport (in W; computes T).
    'scripts/machine_qc_audio_transports.py': PRODUCTION + 'compute/qc_audio_transports.py',
}

# Layer 4 Delivery (tongxing_production.delivery), batches D1-D9.
_DELIVERY = PRODUCTION + 'delivery/'
_LEGACY = PRODUCTION + 'adapters/legacy/'
LAYER4 = {
    'scripts/delivery_contract.py': _DELIVERY + 'contract.py',
    'scripts/build_published_english_reference.py': _DELIVERY + 'published_english_reference.py',
    'scripts/bind_published_alignment_catalog.py': _DELIVERY + 'published_alignment_catalog.py',
    'scripts/study_artifacts.py': _DELIVERY + 'study_artifacts.py',
    'scripts/release_asset_io.py': _DELIVERY + 'asset_io.py',
    'scripts/sermon_delivery_intent.py': _DELIVERY + 'intent.py',
    'scripts/guarded_hosting_publish.py': _DELIVERY + 'publication.py',
    'scripts/prepare_dev_simulated_publication.py': _DELIVERY + 'baseline.py',
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
    # L4 D2: the formal stage and the release builders.
    'scripts/stage_formal_multilingual_dev.py': _DELIVERY + 'formal_stage.py',
    'scripts/build_formal_dev_release_assets.py': _DELIVERY + 'formal_assets.py',
    'scripts/build_full_video_app_release.py': _DELIVERY + 'app_release.py',
    # L4 D5: the unified delivery stage entry.
    'scripts/sermon_unified_delivery.py': _DELIVERY + 'unified_stage.py',
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
    # Review R2: the adjudicators outside the waiver closure and the review budget ledger.
    'scripts/source_meaning_machine_adjudication.py': _REVIEW + 'source_meaning.py',
    'scripts/scripture_adjudication.py': _REVIEW + 'scripture.py',
    'scripts/scripture_machine_adjudication.py': _REVIEW + 'scripture_machine.py',
    'scripts/sermon_review_budget.py': _REVIEW + 'review_budget.py',
    # R3: waiver and machine QC implementation closure.
    'scripts/machine_quality_waiver.py': _REVIEW + 'waiver.py',
    'scripts/machine_quality_release_basis.py': _REVIEW + 'release_basis.py',
    'scripts/target_text_auto_qc.py': _REVIEW + 'text_qc.py',
    'scripts/target_audio_auto_qc.py': _REVIEW + 'audio_qc.py',
    'scripts/auto_qc_seeded_errors.py': _REVIEW + 'seeded_errors.py',
    'scripts/machine_qc_budget_authorization.py': _REVIEW + 'qc_budget_authorization.py',
    'scripts/spoken_condensation.py': _REVIEW + 'condensation.py',
    # R4: review intake and post-QC consumers outside the waiver closure.
    'scripts/machine_audio_waiver_acceptance.py': _REVIEW + 'audio_waiver_acceptance.py',
    'scripts/implementation_freeze.py': _REVIEW + 'implementation_freeze.py',
    'scripts/sermon_unified_reviews.py': _REVIEW + 'unified_reviews.py',
    'scripts/run_machine_qc_clip_test.py': _REVIEW + 'qc_text_run.py',
    'scripts/run_machine_qc_audio_test.py': _REVIEW + 'qc_audio_run.py',
}

# Prepared-workflow composition (tongxing_production.workflows.prepared), batch W2.
_PREPARED = PRODUCTION + 'workflows/prepared/'
WORKFLOWS = {
    'scripts/sermon_unified_continuation.py': _PREPARED + 'continuation.py',
    'scripts/sermon_unified_capabilities.py': _PREPARED + 'capabilities.py',
    'scripts/sermon_unified_canonical_binding.py': _PREPARED + 'canonical_binding.py',
    'scripts/sermon_unified_study.py': _PREPARED + 'study.py',
    'scripts/sermon_study_generation.py': _PREPARED + 'study_generation.py',
    # Orchestration-internal stages (tongxing_production.orchestration.unified), batch W1.
    'scripts/sermon_unified_parallel.py': PRODUCTION + 'orchestration/unified/parallel.py',
    'scripts/sermon_unified_accounting.py': PRODUCTION + 'orchestration/unified/accounting.py',
    # Closure window G1: the durable job store (its file primitives went to storage/files.py).
    'scripts/sermon_workflow_jobs.py': PRODUCTION + 'orchestration/jobs.py',
    # dual_pdf (tongxing_production.workflows.dual_pdf), batch W3a.
    'scripts/sermon_pipeline.py': PRODUCTION + 'workflows/dual_pdf/pipeline.py',
    'scripts/run_post_live_subtitle_generation.py': PRODUCTION + 'workflows/dual_pdf/post_live.py',  # W3c
    'scripts/run_post_live_timeline_job.py': PRODUCTION + 'workflows/dual_pdf/timeline.py',
    'scripts/post_live_run_status.py': PRODUCTION + 'workflows/dual_pdf/run_status.py',
    'scripts/render_mobile_pdf_from_srt.py': PRODUCTION + 'workflows/dual_pdf/mobile_pdf.py',
    'scripts/render_sermon_interpretation_pdf.py': PRODUCTION + 'workflows/dual_pdf/interpretation_pdf.py',
    'scripts/run_local_post_live_download.py': PRODUCTION + 'workflows/dual_pdf/local_post_live_download.py',
    'scripts/run_codex_local_sermon_production.py': PRODUCTION + 'workflows/dual_pdf/codex_local.py',  # W3c
}

# Shared infrastructure, batches I1-I4 (docs/design/infrastructure-injection.zh.md).
CONTRACTS = {       # tongxing_production.contracts, batch I1
    'scripts/canonical_pipeline_definition.py': PRODUCTION + 'contracts/pipeline_definition.py',
}
STORAGE = {         # tongxing_production.storage, batch I2
    'scripts/sermon_public_snapshot.py': PRODUCTION + 'storage/snapshot.py',
}
OBSERVABILITY = {   # tongxing_production.observability, batches I3-I4
    'scripts/weekly_pipeline_report.py': PRODUCTION + 'observability/weekly_projection.py',
    # I3: the accounting ring and its leaves.
    'scripts/sermon_accounting.py': PRODUCTION + 'observability/accounting.py',
    'scripts/sermon_log_contract.py': PRODUCTION + 'observability/log_contract.py',
    'scripts/sermon_log_outbox.py': PRODUCTION + 'observability/outbox.py',
    'scripts/sermon_durable_accounting.py': PRODUCTION + 'observability/durable.py',
    'scripts/sermon_log_profile.py': PRODUCTION + 'observability/profile.py',
    'scripts/sermon_clock_evidence.py': PRODUCTION + 'observability/clock_evidence.py',
    'scripts/sermon_model_call_observation.py': PRODUCTION + 'observability/model_call_observation.py',
    'scripts/sermon_review_observation.py': PRODUCTION + 'observability/review_observation.py',
    'scripts/sermon_model_call_report.py': PRODUCTION + 'observability/model_call_report.py',
    'scripts/sermon_workflow_evidence.py': PRODUCTION + 'observability/workflow_evidence.py',
    'scripts/sermon_dispatch_observation.py': PRODUCTION + 'observability/dispatch_observation.py',
    'scripts/codex_credit_usage.py': PRODUCTION + 'observability/codex_credit_usage.py',
    'scripts/sermon_completion.py': PRODUCTION + 'observability/completion.py',
    'scripts/sermon_cache_observation.py': PRODUCTION + 'observability/cache_observation.py',
    # I4: the four-layer timing audit and progress ledger.
    'scripts/four_layer_measure.py': PRODUCTION + 'observability/measure.py',
    'scripts/four_layer_progress.py': PRODUCTION + 'observability/progress.py',
}

# Closure window D-5: the files the host, the Prefect and mock TTS closures, Temporal's
# dependencySha256 and the L1 compatibility table named, moved with one recalibration.
D5_WINDOW = {
    # the harness, guarded command, job liveness, release workflow and canonical durable jobs
    'scripts/canonical_durable_jobs.py': PRODUCTION + 'orchestration/canonical_durable_jobs.py',
    'scripts/sermon_execution_harness.py': PRODUCTION + 'orchestration/execution_harness.py',
    'scripts/sermon_guarded_command.py': PRODUCTION + 'orchestration/guarded_command.py',
    'scripts/sermon_job_liveness.py': PRODUCTION + 'orchestration/job_liveness.py',
    'scripts/sermon_release_workflow.py': PRODUCTION + 'orchestration/release_workflow.py',
    # the mock-only Prefect pilot (its code_identity() keys)
    'scripts/run_sermon_prefect_dag.py': PRODUCTION + 'orchestration/prefect/run.py',
    'scripts/sermon_dag_contract.py': PRODUCTION + 'orchestration/prefect/contract.py',
    'scripts/sermon_model_resources.py': PRODUCTION + 'orchestration/prefect/model_resources.py',
    'scripts/sermon_prefect_dag.py': PRODUCTION + 'orchestration/prefect/dag.py',
    # the decision budget and the Gemini snapshot transport
    'scripts/sermon_decision_budget.py': PRODUCTION + 'orchestration/supervisor/decision_budget.py',
    'scripts/sermon_gemini_supervisor.py': PRODUCTION + 'orchestration/supervisor/gemini.py',
    # the synthetic TTS job (its implementation_sha256() keys)
    'scripts/sermon_mock_tts_contract.py': PRODUCTION + 'compute/mock_tts/contract.py',
    'scripts/sermon_mock_tts_control.py': PRODUCTION + 'compute/mock_tts/control.py',
    'scripts/sermon_mock_tts_worker.py': PRODUCTION + 'compute/mock_tts/worker.py',
    # the trace export and run progress
    'scripts/export_observability_trace.py': PRODUCTION + 'observability/observability_trace.py',
    'scripts/sermon_run_progress.py': PRODUCTION + 'observability/run_progress.py',
    # the strict Layer 2 chain
    'scripts/sermon_strict_budget_adapter.py': PRODUCTION + 'text/strict/budget_adapter.py',
    'scripts/sermon_strict_candidate_bridge.py': PRODUCTION + 'text/strict/candidate_bridge.py',
    'scripts/sermon_strict_controller.py': PRODUCTION + 'text/strict/controller.py',
    'scripts/sermon_strict_gate_admission.py': PRODUCTION + 'text/strict/gate_admission.py',
    'scripts/sermon_strict_layer2.py': PRODUCTION + 'text/strict/layer2.py',
    'scripts/sermon_strict_locale.py': PRODUCTION + 'text/strict/locale.py',
    'scripts/sermon_strict_repair_planner.py': PRODUCTION + 'text/strict/repair_planner.py',
    # the production supervisor and its agents (Temporal dependencySha256 names it)
    'scripts/run_sermon_production_supervisor_agent.py': PRODUCTION + 'workflows/supervisor/agent.py',
    'scripts/sermon_agents_supervisor.py': PRODUCTION + 'workflows/supervisor/agents.py',
    'scripts/sermon_codex_supervisor.py': PRODUCTION + 'workflows/supervisor/codex.py',
    'scripts/sermon_deterministic_controller.py': PRODUCTION + 'workflows/supervisor/deterministic_controller.py',
    'scripts/sermon_end_to_end.py': PRODUCTION + 'workflows/supervisor/end_to_end.py',
    'scripts/sermon_production_supervisor.py': PRODUCTION + 'workflows/supervisor/production.py',
    # the diagnostic chain (decision D-4) and the agent diagnostic contracts moved in N4
    'scripts/inspect_sermon_prefect_pilot.py': PRODUCTION + 'workflows/diagnostic/inspect_prefect_pilot.py',
    'scripts/run_bounded_diagnostic.py': PRODUCTION + 'workflows/diagnostic/bounded.py',
    'scripts/run_bounded_diagnostic_continuation.py': PRODUCTION + 'workflows/diagnostic/bounded_continuation.py',
    'scripts/run_diagnostic_new_attempt.py': PRODUCTION + 'workflows/diagnostic/new_attempt.py',
    'scripts/sermon_agent_diagnostics.py': PRODUCTION + 'workflows/diagnostic/agent_diagnostics.py',
    'scripts/sermon_agent_diagnostics_contracts.py': PRODUCTION + 'workflows/diagnostic/agent_contracts.py',
    'scripts/sermon_agent_diagnostics_live.py': PRODUCTION + 'workflows/diagnostic/agent_diagnostics_live.py',
    'scripts/sermon_bounded_business_callbacks.py': PRODUCTION + 'workflows/diagnostic/bounded_business_callbacks.py',
    'scripts/sermon_business_prefect_flow.py': PRODUCTION + 'workflows/diagnostic/business_prefect_flow.py',
    'scripts/sermon_business_progress.py': PRODUCTION + 'workflows/diagnostic/business_progress.py',
    'scripts/sermon_cached_fresh_diagnostic_source.py': PRODUCTION + 'workflows/diagnostic/cached_fresh_source.py',
    'scripts/sermon_delivery_intent_binding.py': PRODUCTION + 'workflows/diagnostic/delivery_intent_binding.py',
    'scripts/sermon_dev_diagnostic_snapshot.py': PRODUCTION + 'workflows/diagnostic/dev_snapshot.py',
    'scripts/sermon_diagnostic_attempts.py': PRODUCTION + 'workflows/diagnostic/attempts.py',
    'scripts/sermon_diagnostic_context.py': PRODUCTION + 'workflows/diagnostic/context.py',
    'scripts/sermon_diagnostic_dag_session.py': PRODUCTION + 'workflows/diagnostic/dag_session.py',
    'scripts/sermon_diagnostic_delivery_preflight.py': PRODUCTION + 'workflows/diagnostic/delivery_preflight.py',
    'scripts/sermon_diagnostic_prefect_flow.py': PRODUCTION + 'workflows/diagnostic/prefect_flow.py',
    'scripts/sermon_diagnostic_preview_worker.py': PRODUCTION + 'workflows/diagnostic/preview_worker.py',
    'scripts/sermon_diagnostic_provider.py': PRODUCTION + 'workflows/diagnostic/provider.py',
    'scripts/sermon_diagnostic_source_evidence.py': PRODUCTION + 'workflows/diagnostic/source_evidence.py',
    'scripts/sermon_fresh_diagnostic.py': PRODUCTION + 'workflows/diagnostic/fresh.py',
    'scripts/sermon_fresh_diagnostic_source.py': PRODUCTION + 'workflows/diagnostic/fresh_source.py',
    'scripts/sermon_fresh_full_dag.py': PRODUCTION + 'workflows/diagnostic/fresh_full_dag.py',
    'scripts/sermon_fresh_source_evidence.py': PRODUCTION + 'workflows/diagnostic/fresh_source_evidence.py',
    'scripts/sermon_fresh_source_prefect.py': PRODUCTION + 'workflows/diagnostic/fresh_source_prefect.py',
    'scripts/sermon_fresh_source_stages.py': PRODUCTION + 'workflows/diagnostic/fresh_source_stages.py',
    'scripts/sermon_historical_layer2.py': PRODUCTION + 'workflows/diagnostic/historical_layer2.py',
    'scripts/sermon_historical_native_seed.py': PRODUCTION + 'workflows/diagnostic/historical_native_seed.py',
    'scripts/sermon_local_business_callbacks.py': PRODUCTION + 'workflows/diagnostic/local_business_callbacks.py',
    'scripts/sermon_mock_tts_dag.py': PRODUCTION + 'workflows/diagnostic/mock_tts_dag.py',
    'scripts/sermon_native_preview_runtime.py': PRODUCTION + 'workflows/diagnostic/native_preview_runtime.py',
    'scripts/sermon_pilot_evidence.py': PRODUCTION + 'workflows/diagnostic/pilot_evidence.py',
    # operator and development tools outside the package (Temporal dependencySha256 names the Saturday harness)
    'scripts/codex_layer2_diagnostic.py': 'tools/development/codex_layer2_diagnostic.py',
    'scripts/run_codex_layer2_test.py': 'tools/development/run_codex_layer2_test.py',
    'scripts/run_saturday_harness.py': 'tools/ops/run_saturday_harness.py',
}

# I1 moved generic portions of the legacy review module to contracts; include them
# in closures that still identify the combined legacy module.
# Package files that took over part of a split legacy file; closures that listed
# the legacy key list these as well, so they cover the same code as before.
SPLIT_MEMBERS = {
    # Infrastructure I2: the path constraint, atomic writes and work locks.
    'scripts/sermon_release_workflow.py': (PRODUCTION + 'storage/paths.py',),
    'scripts/sermon_execution_harness.py': (PRODUCTION + 'storage/files.py', PRODUCTION + 'storage/locks.py'),
    # Closure window G1: the job store's file primitives.
    'scripts/sermon_workflow_jobs.py': (PRODUCTION + 'storage/files.py',),
    # workflows/compute C4: the remote-call group extracted from the legacy monolith.
    # W3b: the Layer 1 English group and its file helpers.
    'scripts/sermon_pipeline.py': (PRODUCTION + 'compute/legacy_openai.py', PRODUCTION + 'source/post_live_english.py'),
    'scripts/sermon_review_contracts.py': (PRODUCTION + 'contracts/canonical.py', PRODUCTION + 'contracts/schemas.py'),
}

PATH_ALIASES = {**COMPUTE, **CONTRACTS, **STORAGE, **OBSERVABILITY, **LAYER1, **LAYER2, **LAYER3, **LAYER4,
                **REVIEW, **WORKFLOWS, **D5_WINDOW}


def resolve(key):
    """Repository-relative path of the file a legacy identity key names today."""
    return PATH_ALIASES.get(key, key)


def physical_closure_paths(keys):
    """Files executed by an identity closure: each key's current file and the resolver.

    Use actual repository paths as keys so a per-file hash always names the
    bytes it describes. The resolver itself decides which target is reached.
    A moved key names only its target: the D closure window removed the scripts/
    facades the closures used to hash next to it.
    """
    paths = {PRODUCTION + 'path_aliases.py'}
    for key in keys:
        if not key.startswith(('scripts/', 'packages/')):
            raise ValueError(f'Closure key is not a repository-relative file: {key}')
        paths.add(resolve(key))
    return tuple(sorted(paths))


def recorded(identity, key):
    """Value a loaded-code identity map holds for a key, whichever path recorded it."""
    value = identity.get(resolve(key))
    return identity.get(key) if value is None else value
