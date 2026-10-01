# Local mock integration evidence (2026-10-01 UTC)

Runtime/caller commit: `f7b56935a130813d30c64e39130e1a4df561be64`. This combines reviewed Prefect `78ed99d8`, diagnostics `8b9641a3`, and progress `abf8c5d2`. The subsequent report-only commit does not change runtime code.

[Bounded safe export](safe-integration-evidence.json) includes original synthetic business receipts/output objects, frozen plans, receipt-hash trace observations, completed/failed stage rows, original synthetic budget ledgers, source/run/job/span bindings, progress/ETA and offline diagnostic results. No media, transcript, prompt, credential or machine-private path is included. Cost fields inside **syntheticBudgetLedger** are fake test quota dimensions, never provider spend. The source identity is a synthetic SHA, not an actual video identity.

| Case | Planned processed | Gates complete | Actual observed result |
|---|---:|---:|---|
| Complete | 100% | 100% | 10 mock nodes; repeated execution reused identical jobs, outputs, receipts and reservations |
| Known Korean text failure | 80% | 70% | 8 processed, 7 successful; Chinese/Spanish pages completed, Korean audio/page blocked |
| Korean text outcome unknown | unknown | 70% | 7 successful, one unknown; unknown reservation remains consumed, no reconciliation or retry granted |

The completed case has 7 simulated-human observations and **0 real-human approvals**. Failed/unknown cases retain null ETA with explicit blocker, missing resource queue and sample-coverage reasons. No numerical estimate for a real model pipeline is established. Offline diagnostic lifecycle outputs completed with `needs_more_evidence`, null actual model/usage/cost and `executionAuthorized=false`; those outputs are programmed fixtures, not inferred causes.

The real Prefect engine used its isolated local server with ten worker futures, bounded API-shaped pool 2 and local-model-shaped pool 1; business callbacks were deterministic mock subprocesses. No provider or model implementation was called. A successful flow state alone was not used as business evidence.

## Reproduce locally

Use the optional pinned environment in `requirements-prefect.txt`. Extract any case's `executionPlan` to a fresh plan JSON, then:

```sh
python scripts/run_sermon_prefect_dag.py mock --root /absolute/new-mock-root --plan /absolute/plan.json
python scripts/inspect_sermon_prefect_pilot.py --root /absolute/new-mock-root --offline-diagnosis
```

Known-failure/unknown runs intentionally return exit status 2. Inspection is read-only and does not retry them. Repeating the completed mock command checks resume without another business dispatch. Existing production/real-diagnostic roots are rejected by the mock initializer.

Validation: 84 combined checks passed, including actual Prefect engine success/failure/replay and the progress/diagnostic suites. Ten focused caller checks passed, covering corruption, abandoned jobs, arbitrary snapshot flags, immutable reads, source bindings, concurrent evidence changes, simulated-vs-real humans and unknown outcomes. Final safe failure-metadata/lifecycle check also passed. Independent review reproduced and closed the offline missing-evidence-request defect.

This report supports local mock integration only. Production business adapters, actual resource/liveness monitor, durable revision/reconciliation importer and live Agents transport remain unwired. The paused real-media run, four-file timing-extension patch and original budget were not modified.

## Follow-up reader isolation fix

Independent review found that one locale's corrupted artifact could poison later unrelated locales through an accumulating global error list. The reader now separates initial global accounting-integrity errors from node-local errors. A three-locale regression corrupts each language in turn: exactly that language's text/audio/page become unknown while the other seven nodes retain their original validated facts. Global accounting corruption still blocks all positive evidence. The 46 caller/progress checks passed, and a dedicated global-corruption regression passed. Reprojecting all three saved runs with the corrected reader preserved every original file and the counts above; no business node was rerun. The checked-in raw demonstration continues to identify its original `f7b56935` capture code accurately.
