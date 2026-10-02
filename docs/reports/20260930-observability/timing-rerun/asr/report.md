# Weekly Pipeline Report

Status: projected

Projected means a computable recorded DAG, not complete telemetry. Content/device/venue/release acceptance: not evaluated.

## Run 1b88421e72ff

End-to-end wall seconds: 11.40558409690857
Active critical-path seconds: 11.373646

| Executor | Leaf elapsed seconds (parallel subtotal) |
|---|---:|
| decision_agent | 0 (not_observed; completed spans only) |
| deterministic_program | 1.75473 (measured_completed_spans; completed spans only) |
| engineering_codex | 0 (not_observed; completed spans only) |
| external_service | 0 (not_observed; completed spans only) |
| human | 0 (not_observed; completed spans only) |
| production_model | 9.618916 (measured_completed_spans; completed spans only) |

Coverage: {"crossProcessCriticalPath": "not_established", "locales": "not_observed", "logCompleteness": "not_established", "orchestrationOverhead": "missing_instrumentation", "pageReady": "not_observed", "queueTiming": "missing_instrumentation", "sourceDuration": "recorded", "statusMeaning": "projected_means_computable_recorded_DAG_not_complete_telemetry"}

| Stage / attempt | Executor / models | Cache | Start → finish | Dependencies | Queue |
|---|---|---|---|---|---|
| diagnostic.local_asr / 978e04f6ef01 | production_model / mlx-community/whisper-large-v3-turbo-q4 | False | 2026-09-30T15:00:44.703011+00:00 → 2026-09-30T15:00:54.322122+00:00 | 9de080300d28 | missing_instrumentation |
| diagnostic.local_asr_setup / 2ef5eb143153 | deterministic_program /  | False | 2026-09-30T15:00:43.154420+00:00 → 2026-09-30T15:00:44.702816+00:00 | 3cb80a7839e0 | missing_instrumentation |
| diagnostic.source_decode / f5aee407442e | deterministic_program /  | False | 2026-09-30T15:00:42.951526+00:00 → 2026-09-30T15:00:43.154099+00:00 |  | missing_instrumentation |
| diagnostic.local_asr_output / 136f318b45da | deterministic_program /  | False | 2026-09-30T15:00:54.322567+00:00 → 2026-09-30T15:00:54.326503+00:00 | b5f962168df8 | missing_instrumentation |

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
