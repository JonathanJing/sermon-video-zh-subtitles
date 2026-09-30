# Weekly Pipeline Report

Status: projected

Projected means a computable recorded DAG, not complete telemetry. Content/device/venue/release acceptance: not evaluated.

## Run acba25512100

End-to-end wall seconds: 8.0
Active critical-path seconds: 8

| Executor | Leaf elapsed seconds (parallel subtotal) |
|---|---:|
| decision_agent | 0 (not_observed; completed spans only) |
| deterministic_program | 3 (measured_completed_spans; completed spans only) |
| engineering_codex | 0 (not_observed; completed spans only) |
| external_service | 0 (not_observed; completed spans only) |
| human | 0 (not_observed; completed spans only) |
| production_model | 8 (measured_completed_spans; completed spans only) |

Coverage: {"crossProcessCriticalPath": "not_established", "locales": "not_observed", "logCompleteness": "not_established", "orchestrationOverhead": "missing_instrumentation", "pageReady": "not_observed", "queueTiming": "missing_instrumentation", "sourceDuration": "missing_or_conflicting", "statusMeaning": "projected_means_computable_recorded_DAG_not_complete_telemetry"}

| Stage / attempt | Executor / models | Cache | Start → finish | Dependencies | Queue |
|---|---|---|---|---|---|
| ko / 1fdbc74ccfd6 | production_model /  | None | 2026-09-30T00:00:02+00:00 → 2026-09-30T00:00:07+00:00 | 41cf6794ba42 | missing_instrumentation |
| zh / 60cae1d01739 | production_model /  | None | 2026-09-30T00:00:02+00:00 → 2026-09-30T00:00:05+00:00 | 41cf6794ba42 | missing_instrumentation |
| source / 41cf6794ba42 | deterministic_program /  | None | 2026-09-30T00:00:00+00:00 → 2026-09-30T00:00:02+00:00 |  | missing_instrumentation |
| join / 58393216032b | deterministic_program /  | None | 2026-09-30T00:00:07+00:00 → 2026-09-30T00:00:08+00:00 | 1fdbc74ccfd6,60cae1d01739 | missing_instrumentation |

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

