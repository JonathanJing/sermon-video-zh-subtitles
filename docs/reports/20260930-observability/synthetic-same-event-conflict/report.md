# Weekly Pipeline Report

Status: partial

Projected means a computable recorded DAG, not complete telemetry. Content/device/venue/release acceptance: not evaluated.

## Run a84c701b1b1a

End-to-end wall seconds: 0.05231785774230957
Active critical-path seconds: None

| Executor | Leaf elapsed seconds (parallel subtotal) |
|---|---:|
| decision_agent | 0 (not_observed; completed spans only) |
| deterministic_program | 0 (not_observed; completed spans only) |
| engineering_codex | 0 (not_observed; completed spans only) |
| external_service | 0 (not_observed; completed spans only) |
| human | 0 (not_observed; completed spans only) |
| production_model | 0.000709 (measured_completed_spans; completed spans only) |

Coverage: {"crossProcessCriticalPath": "not_established", "locales": "not_observed", "logCompleteness": "not_established", "orchestrationOverhead": "missing_instrumentation", "pageReady": "not_observed", "queueTiming": "missing_instrumentation", "sourceDuration": "missing_or_conflicting", "statusMeaning": "projected_means_computable_recorded_DAG_not_complete_telemetry"}

| Stage / attempt | Executor / models | Cache | Start → finish | Dependencies | Queue |
|---|---|---|---|---|---|
| synthetic.model / 859452dbbdb0 | production_model / gpt-6-astra,model-a | False | 2026-09-30T14:39:53.913614+00:00 → 2026-09-30T14:39:53.914356+00:00 |  | missing_instrumentation |

Direct receipt usage (SDK aggregates remain separate):

| Executor | Calls | Input | Cached | Non-cached | Output | Reasoning |
|---|---:|---:|---:|---:|---:|---:|
| decision_agent | None | None | None | None | None | None |
| deterministic_program | None | None | None | None | None | None |
| engineering_codex | None | None | None | None | None | None |
| external_service | None | None | None | None | None | None |
| human | None | None | None | None | None | None |
| production_model | None | None | None | None | None | None |
| unknown | None | None | None | None | None | None |

Diagnostics: conflicting_usage_receipts

## Run 56e552de2df8

End-to-end wall seconds: 0.05833005905151367
Active critical-path seconds: None

| Executor | Leaf elapsed seconds (parallel subtotal) |
|---|---:|
| decision_agent | 0 (not_observed; completed spans only) |
| deterministic_program | 0 (not_observed; completed spans only) |
| engineering_codex | 0 (not_observed; completed spans only) |
| external_service | 0 (not_observed; completed spans only) |
| human | 0 (not_observed; completed spans only) |
| production_model | 0.001282 (measured_completed_spans; completed spans only) |

Coverage: {"crossProcessCriticalPath": "not_established", "locales": "not_observed", "logCompleteness": "not_established", "orchestrationOverhead": "missing_instrumentation", "pageReady": "not_observed", "queueTiming": "missing_instrumentation", "sourceDuration": "missing_or_conflicting", "statusMeaning": "projected_means_computable_recorded_DAG_not_complete_telemetry"}

| Stage / attempt | Executor / models | Cache | Start → finish | Dependencies | Queue |
|---|---|---|---|---|---|
| synthetic.model / 4bc4f501a8ad | production_model / gpt-6-astra,model-a | False | 2026-09-30T14:39:53.855024+00:00 → 2026-09-30T14:39:53.856338+00:00 |  | missing_instrumentation |

Direct receipt usage (SDK aggregates remain separate):

| Executor | Calls | Input | Cached | Non-cached | Output | Reasoning |
|---|---:|---:|---:|---:|---:|---:|
| decision_agent | None | None | None | None | None | None |
| deterministic_program | None | None | None | None | None | None |
| engineering_codex | None | None | None | None | None | None |
| external_service | None | None | None | None | None | None |
| human | None | None | None | None | None | None |
| production_model | None | None | None | None | None | None |
| unknown | None | None | None | None | None | None |

Diagnostics: conflicting_usage_receipts

