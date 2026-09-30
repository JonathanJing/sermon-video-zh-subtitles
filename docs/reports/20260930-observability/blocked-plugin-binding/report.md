# Weekly Pipeline Report

Status: projected

Projected means a computable recorded DAG, not complete telemetry. Content/device/venue/release acceptance: not evaluated.

## Run 38046d429fac

End-to-end wall seconds: 2.505422830581665
Active critical-path seconds: 2.258317

| Executor | Leaf elapsed seconds (parallel subtotal) |
|---|---:|
| decision_agent | 0 (not_observed; completed spans only) |
| deterministic_program | 2.270131 (measured_completed_spans; completed spans only) |
| engineering_codex | 0 (not_observed; completed spans only) |
| external_service | 0 (not_observed; completed spans only) |
| human | 0 (not_observed; completed spans only) |
| production_model | 0 (not_observed; completed spans only) |

Coverage: {"crossProcessCriticalPath": "not_established", "locales": "recorded", "logCompleteness": "not_established", "orchestrationOverhead": "missing_instrumentation", "pageReady": "not_observed", "queueTiming": "missing_instrumentation", "sourceDuration": "recorded", "statusMeaning": "projected_means_computable_recorded_DAG_not_complete_telemetry"}

| Stage / attempt | Executor / models | Cache | Start → finish | Dependencies | Queue |
|---|---|---|---|---|---|
| diagnostic.real_source_decode / 800372b3fecf | deterministic_program /  | False | 2026-09-30T14:38:47.962338+00:00 → 2026-09-30T14:38:50.214156+00:00 |  | missing_instrumentation |
| layer2.source_admission.zh-Hans / 6b6a0ca0d68d | deterministic_program /  | False | 2026-09-30T14:38:50.275460+00:00 → 2026-09-30T14:38:50.280992+00:00 | f27c3cadfc38 | missing_instrumentation |
| layer2.source_admission.es / 7b43662543c2 | deterministic_program /  | False | 2026-09-30T14:38:50.403654+00:00 → 2026-09-30T14:38:50.408221+00:00 | f27c3cadfc38 | missing_instrumentation |
| layer2.source_admission.ko / 75c44fe70ec0 | deterministic_program /  | False | 2026-09-30T14:38:50.339187+00:00 → 2026-09-30T14:38:50.343598+00:00 | f27c3cadfc38 | missing_instrumentation |
| layer2.run_admission.ko / f1cde88e3311 | deterministic_program /  | False | 2026-09-30T14:38:50.343954+00:00 → 2026-09-30T14:38:50.345879+00:00 | 55b9bc891d95 | missing_instrumentation |
| layer2.run_admission.es / 81678efed840 | deterministic_program /  | False | 2026-09-30T14:38:50.408590+00:00 → 2026-09-30T14:38:50.410321+00:00 | 1c1739edfbd5 | missing_instrumentation |
| layer2.run_admission.zh-Hans / c4f2a52ce9c0 | deterministic_program /  | False | 2026-09-30T14:38:50.281280+00:00 → 2026-09-30T14:38:50.283043+00:00 | cca4b083dfab | missing_instrumentation |

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
