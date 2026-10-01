# Offline run progress and ETA

`scripts/sermon_run_progress.py` projects a frozen business plan and validated local observations. It makes no model, media, TTS, network, dispatch, budget, or publication calls. It writes only a separate progress projection. This implements the offline component of [the progress/ETA and Prefect pilot requirements](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/182); controller/Prefect integration and real-run calibration remain with their owners.

## Stable local API v1

```python
from scripts import sermon_run_progress as progress

plan = progress.freeze_plan(
    plan_id, version, run_id, units, resources,
    dag_version="sermon-canonical-pipeline-v1",
    weight_policy_version="explicit-unit-weights-v1",
)
snapshot = progress.project_progress(
    plan, receipts, samples=samples, at=observed_at,
    previous=previous_projection, resource_state=resource_state,
    input_issues=integrity_reason_codes,
)
progress.write_progress(output_path, snapshot)
```

The versioned schemas are `sermon-run-progress-plan-v1`, `sermon-run-progress-status-v1`, and `sermon-run-progress-v1`. `planSha256` hashes the entire normalized plan, including DAG version, weight policy, unit identities, dependencies, weights, required evidence, priors and resource configuration. The denominator is an exact decimal string. A positive weight measures planned work, not elapsed time. Retries/rework do not change that denominator.

Each unit explicitly supplies:

```json
{
  "id": "translate.ko.group01", "identitySha256": "<input-policy-revision SHA256>",
  "stage": "translation", "model": "<actual comparable model>", "locale": "ko",
  "lengthBucket": "short", "cacheClass": "fresh", "resourceClass": "api-profile-v1",
  "dependsOn": [], "weight": 1, "resources": ["api", "workflow"],
  "requiredEvidence": ["executionSucceeded", "contentReviewPassed", "realHumanApproved", "admitted"]
}
```

The integration owner must map **all applicable existing business gates** into `requiredEvidence`, or separate dependent gate units. `executionSucceeded` is always required; machine review, actual human approval, simulated human approval and admission are independent requirements. A generation-only unit can require execution alone, but this never substitutes for the planned review/admission units. Bind identity hashes to the actual source, policy, revision and locale; an output hash becomes available through validated receipts after execution.

Resources are named pools such as paid API, GPU, CPU or a global workflow limit. A unit reserves one slot in **every** listed pool together. Freeze capacities/classes, for example `{"api":{"capacity":2,"resourceClass":"api-profile-v1"}}`. Hardware/RAM limits must be encoded in the chosen real capacities/classes by the local admission owner. Changing those frozen values requires a versioned plan, rather than assuming nominal framework concurrency is actual availability.

## Full observation snapshots

`status_receipt` wraps a **full** observation from a local trusted validator. It defaults every positive evidence field to false/unknown and grants no validation itself:

```python
receipt = progress.status_receipt(
    plan, unit_id, event_id=event_id, attempt_id=attempt_id,
    sequence=unit_observation_sequence, observed_at=observed_at,
    executionStatus="succeeded", phase="complete",
    evidenceValidated=True, artifactSha256=artifact_hash,
    evidenceRefs=[validated_receipt_id],
    reviewVerdict="pass", reviewedArtifactSha256=artifact_hash,
    humanReviewKind="real", humanApprovalStatus="approved",
    humanReviewedArtifactSha256=artifact_hash,
    admissionStatus="admitted",
)
```

The adapter must validate the original package/RQC/human receipt with the existing validator and check exact run/source/unit/revision/artifact bindings before setting `evidenceValidated=True`. This module checks its closed envelope and matching review/human artifact hashes, not original content or signatures. A single full snapshot prevents joining review and human approvals for different artifacts. Receipt references are bounded local identifier labels, not raw logs, paths, text or secrets. Additional fields are rejected.

`sequence` increases per unit across attempts; it is not local to a framework task or an attempt. Every input snapshot includes the exact frozen plan/run/unit identity. Exact event duplicates are idempotent; conflicting event IDs, equal unit sequences, missing/mismatched bindings and future observations prevent overall completion and numeric ETA. Keep the entire relevant observation history, including attempts with unknown outcomes. A later success cannot erase an unresolved old attempt. Only a validator-produced reconciliation snapshot with `reconcilesAttemptIds` may close those attempts, after checking the existing durable reconciliation evidence.

| Counter | Meaning |
|---|---|
| `processed` | Observed succeeded/failed/cancelled execution; unknown outcome excluded |
| `executionSucceeded` | Succeeded execution plus validated artifact evidence |
| `contentReviewPassed` | Same-artifact machine review pass with succeeded execution |
| `realHumanApproved` | Same-artifact actual human approval; machine/simulated approval excluded |
| `simulatedHumanApproved` | Same-artifact explicitly simulated approval |
| `admitted` | Explicit validated admission observation |
| `done` | All frozen requirements and dependencies met, explicit complete phase, no unresolved attempt/blocker |

The weighted percentage uses `done` only. Per-stage/locale totals retain planned, failed and unknown units. Incomplete projections are capped below 100 even if display rounding would otherwise produce 100. Global input integrity failures also prevent 100. This is evidence coverage of the local plan, with `executionAuthority=none`; it never grants production, HTTP, device or venue acceptance.

Phases are `pending/running/retrying/waiting_review/blocked/complete/unknown_outcome`. `workKind=rework` and distinct attempt IDs supply extra-work counts; they are separate from planned weight. Cost stays `not_projected` here; use the existing accounting/weekly report for known costs and missing-usage coverage instead of adding provider receipts or inventing zero cost.

## Empirical estimates, queue and liveness

A sample supplies `sampleId`, `sourceRef`, `observedAt`, `executionStatus=succeeded`, `measurementKind=empirical`, positive `elapsedSeconds`, and all six matching dimensions: stage/model/locale/lengthBucket/cacheClass/resourceClass. Duplicate sample IDs are deduplicated; conflicting samples invalidate ETA. Current-run status receipts update the empirical set only with `measurementValidated=True`, a stable `timingSampleId`, and an explicitly measured successful duration. Use the same ID/source reference for an external representation of that measurement so it cannot be counted twice. The local validator must establish the measurement basis; do not use file timestamps or synthesize historical spans.

For fewer than five comparable samples the duration envelope is `[0.5 × observed minimum, 2 × observed maximum]`, confidence `low`. At least five samples use `[0.8 × minimum, 1.5 × maximum]`, confidence `medium`. These are conservative scenario ranges, **not calibrated probability intervals**. No model/locale/cache borrowing or percentage-based extrapolation occurs. Without comparable history, an optional unit `priorSeconds={"lower":5,"upper":90,"sourceRef":"planning-prior"}` is explicitly labelled `explicit_cold_start_prior`, with zero empirical samples and low confidence; absent a prior, ETA is unknown. Samples are never automatically synthesized from expected work.

`resource_state` is a fresh, local observed snapshot for every frozen pool:

```json
{
  "api": {
    "capacity": 2, "resourceClass": "api-profile-v1", "status": "ready",
    "queueSeconds": [0, 30], "observedAt": "2026-10-01T01:00:00Z", "maxAgeSeconds": 60
  }
}
```

`queueSeconds` contains known remaining **external** occupation per slot, excluding active units in this plan; a zero slot is currently available. Every required pool, capacity and class must match. Missing/unknown/outage/stale queues or impossible active-resource occupancy give unknown ETA. `queueRemainingSeconds` on a unit is its known remaining not-before delay, combined by `max` with dependency/pool availability rather than added twice. Global workflow concurrency can be enforced by listing a workflow pool alongside stage pools.

The estimator computes remaining serial work, dependency-only critical path, and non-preemptive list schedules for both duration endpoints using all resources, current active units, dependencies and known queues. It reports lower/upper remaining seconds and UTC completion times, per-unit estimates, sample count, confidence, assumptions, estimator version and update time. List scheduling is an explicit deterministic scenario, not a promise of optimal scheduling; future arrivals, undeclared retries/rework and future outages are excluded. Known current rework/retry attempts retain their actual history and count as remaining planned units until their gates pass.

For active work, supply monitor-derived `activeElapsedSeconds`, `heartbeatStatus`, `heartbeatAgeSeconds` and `heartbeatTimeoutSeconds`. UTC observation aging can only refuse a stale ETA; it never renews a lease or claims the process is live. Missing/stale liveness, active duration beyond the empirical envelope, failed/cancelled/unknown outcomes, blocked work and unresolved post-execution gates leave completion ETA unknown. Remaining human approvals also have unknown delivery ETA; machine duration samples cannot estimate human response time. A passed plan reports complete/zero remaining work independent of historical timing coverage.

## Reusing existing evidence

- `plan_from_tracker(ledger, plan_id, version, run_id, unit_specs, resources, **freeze_kwargs)` reuses [the existing formal checkpoint dependencies](../scripts/build_four_layer_timeline.py). Every checkpoint needs an explicit unit specification. Tracker completion and estimates are never imported as execution/review proof.
- `samples_from_accounting(plan, events, bindings)` reuses [the existing weekly leaf-span projector](../scripts/weekly_pipeline_report.py), including its interval/monotonic checks and parent-child exclusion. Binding is `spanId -> {accountingRunId, accountingWorkUnitId, unitId, identitySha256, stage, model, locale, lengthBucket, cacheClass, resourceClass}`. Stage/model/native work-unit must match, and cache/length/resource comparability must be independently verified. Unbound, ambiguous, unfinished or failed spans supply no sample. Returned `statusReceipts` is always empty: process exit and heartbeat do not establish content/admission.
- Read native logs through `sermon_accounting.read_event_snapshot(directory)`, which locks and hashes the same bytes without rewriting the ledger. Pass damaged/conflicting/unresolved evidence reason codes through `input_issues`. No accounting summary generation is needed.
- `PilotNodeObservation`/Prefect state is supplementary observation. Map it to full snapshots only after reading and validating the original business receipts; flow/task completion, task counts and framework cache hits supply no business denominator or human gate.

The module is local/private. Publishing to an existing public Tracker or exporting remote diagnostic packets requires the existing sanitized exporter; raw identities/hashes from this JSON must not be sent directly.

## CLI and persistence

`freeze` takes a JSON object with the `freeze_plan` keyword arguments and exclusively creates the plan. `project` reads a frozen plan, a JSON list/JSONL of full status snapshots, optional sample list and resource state, then writes a separate JSON projection:

```sh
python scripts/sermon_run_progress.py freeze --input plan-spec.json --output new-plan.json
python scripts/sermon_run_progress.py project --plan new-plan.json --receipts status-snapshots.jsonl \
  --samples timing-samples.json --resource-state observed-resources.json --output run-progress.json
```

Writes use an output-specific lock, temporary file, file fsync, atomic replacement and directory fsync. A freeze cannot overwrite an existing file; projection updates refuse another schema/identity, older projections, symlinks, or an output matching an input. Existing run ledgers are preserved. For a changed denominator/DAG/identity/resource configuration, create a higher `planVersion` with `supersedes=<old planSha256>` and `migration_reason=<explicit code>`, then project against the previous output. The projection records both denominators and the migration reason. New-plan receipts need the new binding; old receipts cannot silently carry approval across revisions.

Offline validation:

```sh
python -m unittest tests.test_sermon_run_progress tests.test_weekly_pipeline_report \
  tests.test_four_layer_progress tests.test_timeline_accounting
```

[Synthetic scheduling fixtures](../tests/fixtures/sermon_run_progress/offline-scenarios.json) cover serial/parallel/queue/capacity/convergence. Dedicated tests cover retry/rework/reconciliation, stale/unknown evidence, review/human isolation, sample matching/cold start, explicit drift/migration, input invariance, CLI and crash-safe writes. These are code acceptance tests; real production calibration, Prefect integration and the paused real diagnostic are separate evidence.
