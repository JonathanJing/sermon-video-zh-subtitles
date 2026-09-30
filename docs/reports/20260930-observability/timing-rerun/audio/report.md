# Weekly Pipeline Report

Status: projected

Projected means a computable recorded DAG, not complete telemetry. Content/device/venue/release acceptance: not evaluated.

## Run 3319b6fe1f68

End-to-end wall seconds: 6.521719932556152
Active critical-path seconds: 6.388333

| Executor | Leaf elapsed seconds (parallel subtotal) |
|---|---:|
| decision_agent | 0 (not_observed; completed spans only) |
| deterministic_program | 6.388333 (measured_completed_spans; completed spans only) |
| engineering_codex | 0 (not_observed; completed spans only) |
| external_service | 0 (not_observed; completed spans only) |
| human | 0 (not_observed; completed spans only) |
| production_model | 0 (not_observed; completed spans only) |

Coverage: {"crossProcessCriticalPath": "not_established", "locales": "not_observed", "logCompleteness": "not_established", "orchestrationOverhead": "missing_instrumentation", "pageReady": "not_observed", "queueTiming": "missing_instrumentation", "sourceDuration": "missing_or_conflicting", "statusMeaning": "projected_means_computable_recorded_DAG_not_complete_telemetry"}

| Stage / attempt | Executor / models | Cache | Start → finish | Dependencies | Queue |
|---|---|---|---|---|---|
| diagnostic.audio.zh-Hans / cc6b1a26ae46 | deterministic_program /  | False | 2026-09-30T15:00:55.517806+00:00 → 2026-09-30T15:00:57.652505+00:00 |  | missing_instrumentation |
| diagnostic.audio.ko / c83c86e11756 | deterministic_program /  | False | 2026-09-30T15:00:57.683311+00:00 → 2026-09-30T15:00:59.817248+00:00 | 8a15b5526024 | missing_instrumentation |
| diagnostic.audio.es / 7489166cbbc9 | deterministic_program /  | False | 2026-09-30T15:00:59.846457+00:00 → 2026-09-30T15:01:01.966415+00:00 | a0f37e2e53b0 | missing_instrumentation |

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
