# Frozen local mock DAG inspection

This caller integrates the reviewed Prefect (#185), progress/ETA (#184), and offline diagnostic (#183) components. Production business adapters and live Agents transport remain **unwired**. This does not resume the paused real-media diagnostic or access its budget, media, credentials or receipts.

## One read-only entry

After the local mock flow exits:

```sh
python scripts/inspect_sermon_prefect_pilot.py --root /absolute/mock-run --offline-diagnosis
```

The command prints a private JSON report to stdout; it writes no run state or report file. The optional diagnostic uses the known in-memory `OfflineReplayClient`, with a synthetic request for missing evidence. It is a lifecycle demonstration, not model reasoning. There is no arbitrary injected client, live model, action execution or paid retry in this entry.

The reader obtains the existing harness lock without creating it, refuses an active writer, rejects linked evidence, hashes a bounded original-file inventory, and verifies the same inventory before returning. Durable jobs use `peek_job`, never mutating inspection. A concurrent change aborts the report rather than presenting a mixed snapshot. This version supports **frozen inspection**, not periodic live monitoring.

`runId`, `sourceIdentitySha256`, `executionPlanSha256`, runtime/reader code hashes, source ledger digest and original-file digests bind the report. `validatedNodeEvidence` joins each unit to its durable job, receipt and span. The observer deliberately ignores `snapshot.json` completion, review and reconciliation claims.

## Evidence and progress

Positive facts require a current succeeded durable job plus original matching artifact, completed accounting span and receipt-hash observation. L2 also requires a settled matching shared budget receipt. Controlled failures require their original immutable failure and matching durable result. Unknown or damaged evidence remains unknown; this reader never reconciles or launches work. The fixed mock protocol has one attempt per node; generic revision/reconciliation proof import is not implemented.

The progress plan freezes all canonical dependencies, resource capacities, equal node weights, artifact/review/admission requirements and explicit simulated-versus-real human gates. The primary field is `progress.plannedProcessedPercent`; `gateCompletionPercent` is separate. Failed processed work contributes only to the processed bar. Unknown work gives a null percentage with known lower bound. A mock 100% grants no production eligibility or real human approval.

A validated `synthetic_pass`/`mock_only` receipt maps to mock-plan review/admission only. All outputs retain `evidenceMode=synthetic` and `productionEligible=false`; actual human approval count stays zero. Do not export these status receipts into a production plan or approval store.

Elapsed samples are measured mock worker durations bound to original receipts and accounting spans. They are not production model priors. Resource queues and heartbeat are unknown without a real monitor; ETA remains null for unfinished/blocked work. Complete mock work can report zero remaining mock work. Synthetic quota values are never reported as actual provider usage or spend; actual model, tokens and costs in the offline diagnostic remain null.

## Validation and remaining boundaries

```sh
python -m unittest tests.test_sermon_pilot_evidence tests.test_sermon_run_progress tests.test_sermon_agent_diagnostics
SERMON_TEST_PREFECT=1 python -m unittest tests.test_sermon_pilot_evidence tests.test_sermon_prefect_runtime
```

Tests exercise actual durable mock subprocesses, real local Prefect execution, independent locale completion after one branch fails, replay without another job/reservation, artifact/job corruption, abandoned jobs, active-writer rejection, immutable evidence, simulated-human separation and the offline diagnostic session lifecycle. Hosted optional Prefect CI includes the integrated engine test.

Remaining production integration: source/L2/L3/L4 callback adapters; original production artifact/review/approval validators; durable revision/reconciliation adapter; authoritative resource/liveness observation; empirical model-duration calibration; separately approved live diagnostic transport. No rollout, real model run, real-content acceptance, human sign-off, native/device acceptance or publication is established here.
