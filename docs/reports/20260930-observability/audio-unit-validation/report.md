# Weekly Pipeline Report

Status: projected

Projected means a computable recorded DAG, not complete telemetry. Content/device/venue/release acceptance: not evaluated.

## Run 66e8b9fa0999

End-to-end wall seconds: 7.554074048995972
Active critical-path seconds: 2.524389

| Executor | Leaf elapsed seconds (parallel subtotal) |
|---|---:|
| decision_agent | 0 (not_observed; completed spans only) |
| deterministic_program | 7.260393 (measured_completed_spans; completed spans only) |
| engineering_codex | 0 (not_observed; completed spans only) |
| external_service | 0 (not_observed; completed spans only) |
| human | 0 (not_observed; completed spans only) |
| production_model | 0 (not_observed; completed spans only) |

Coverage: {"crossProcessCriticalPath": "not_established", "locales": "not_observed", "logCompleteness": "not_established", "orchestrationOverhead": "missing_instrumentation", "pageReady": "not_observed", "queueTiming": "missing_instrumentation", "sourceDuration": "missing_or_conflicting", "statusMeaning": "projected_means_computable_recorded_DAG_not_complete_telemetry"}

| Stage / attempt | Executor / models | Cache | Start → finish | Dependencies | Queue |
|---|---|---|---|---|---|
| diagnostic.audio.zh-Hans / cb7e976e271b | deterministic_program /  | False | 2026-09-30T14:38:46.747088+00:00 → 2026-09-30T14:38:49.271661+00:00 |  | missing_instrumentation |
| diagnostic.audio.ko / 4959cf879abc | deterministic_program /  | False | 2026-09-30T14:38:49.346985+00:00 → 2026-09-30T14:38:51.772535+00:00 |  | missing_instrumentation |
| diagnostic.audio.es / 55b4203a3c10 | deterministic_program /  | False | 2026-09-30T14:38:51.856149+00:00 → 2026-09-30T14:38:54.166866+00:00 |  | missing_instrumentation |

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
