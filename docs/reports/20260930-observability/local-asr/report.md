# Weekly Pipeline Report

Status: projected

Projected means a computable recorded DAG, not complete telemetry. Content/device/venue/release acceptance: not evaluated.

## Run a3b97ee1fad4

End-to-end wall seconds: 12.493408918380737
Active critical-path seconds: 12.461977

| Executor | Leaf elapsed seconds (parallel subtotal) |
|---|---:|
| decision_agent | 0 (not_observed; completed spans only) |
| deterministic_program | 0.51144 (measured_completed_spans; completed spans only) |
| engineering_codex | 0 (not_observed; completed spans only) |
| external_service | 0 (not_observed; completed spans only) |
| human | 0 (not_observed; completed spans only) |
| production_model | 11.950537 (measured_completed_spans; completed spans only) |

Coverage: {"crossProcessCriticalPath": "not_established", "locales": "not_observed", "logCompleteness": "not_established", "orchestrationOverhead": "missing_instrumentation", "pageReady": "not_observed", "queueTiming": "missing_instrumentation", "sourceDuration": "recorded", "statusMeaning": "projected_means_computable_recorded_DAG_not_complete_telemetry"}

| Stage / attempt | Executor / models | Cache | Start → finish | Dependencies | Queue |
|---|---|---|---|---|---|
| diagnostic.local_asr / 19b07091c313 | production_model / mlx-community/whisper-large-v3-turbo-q4 | False | 2026-09-30T14:38:44.608121+00:00 → 2026-09-30T14:38:56.558752+00:00 | 4f3a68b57cf5 | missing_instrumentation |
| diagnostic.source_decode / e3e15cd69bb9 | deterministic_program /  | False | 2026-09-30T14:38:44.095781+00:00 → 2026-09-30T14:38:44.367194+00:00 |  | missing_instrumentation |
| diagnostic.model_identity / 540b55b037dc | deterministic_program /  | False | 2026-09-30T14:38:44.367648+00:00 → 2026-09-30T14:38:44.607880+00:00 | 4447e0b1b8e6 | missing_instrumentation |

Direct receipt usage (SDK aggregates remain separate):

| Executor | Calls | Input | Cached | Non-cached | Output | Reasoning |
|---|---:|---:|---:|---:|---:|---:|
| decision_agent | 0 | None | None | None | None | None |
| deterministic_program | 0 | None | None | None | None | None |
| engineering_codex | 0 | None | None | None | None | None |
| external_service | 0 | None | None | None | None | None |
| human | 0 | None | None | None | None | None |
| production_model | 0 | None | None | None | None | None |
| unknown | 0 | None | None | None | None | None |

Diagnostics:
