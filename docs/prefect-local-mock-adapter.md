# Local Prefect mock adapter

This optional adapter runs canonical source → locale text → same-locale audio →
page nodes through **real local durable-job subprocesses and Prefect 3.8.7**.
Every business output, review verdict and budget usage is **synthetic**. No provider,
model, media, real human-approval or publication adapter is exposed. The paused
180-second diagnostic and its budget are unrelated and must not be passed here.

Install `requirements-prefect.txt` into an isolated virtual environment. Production
requirements/defaults do not import Prefect. Run from a fresh CLI process without
ambient `PREFECT_*` settings or working-directory `.env`, `prefect.toml`,
`pyproject.toml` files (even unrelated files are rejected without reading them).
An existing pilot `profiles.toml` is also rejected before SDK import. The adapter pins a temporary loopback server, local
SQLite database, profile and result storage below its own dedicated root; it
rejects imported/cached Prefect settings, pins the memo store, and sets
`DO_NOT_TRACK=1` before import to disable interactive SDK onboarding analytics
as well as cloud/server telemetry. Before importing the SDK it moves this fresh
CLI process into a newly created private config directory under the pilot root,
retained through shutdown, so later file creation in the caller cwd cannot enter
a lazy settings reload or the ephemeral server.

```sh
python - <<'PY'
import json
from pathlib import Path
from scripts.sermon_dag_contract import make_plan
plan = make_plan(run_id='1'*64, input_identity_sha256='2'*64)
Path('/tmp/sermon-mock-plan.json').write_text(json.dumps(plan))
PY
python scripts/run_sermon_prefect_dag.py mock \
  --root artifacts/prefect-mock-demo --plan /tmp/sermon-mock-plan.json
```

The repeated command revalidates existing immutable receipts. It does not launch
another business process or charge another synthetic request. A changed code
closure or plan is rejected; use a separately identified new **mock** experiment,
not a new directory to reset a real run's quota. `--root` must initially be empty.
The CLI exits 2 if any business node is blocked/failed/unknown, even if Prefect's
flow state is Completed. Scheduler completion is not business admission.

## Interfaces and authority

- `sermon_dag_contract.make_plan/validate_plan` freezes canonical dependencies,
  input/run identity, resource capacities, scenario choices, unit weights and
  a synthetic request limit. The mode is closed to `mock_only` and
  `productionEligible=false`; no publish nodes exist.
- `sermon_prefect_dag.run(root, plan)` owns one existing `work_lock`. Prefect
  tasks have zero retries and no result-cache authority. `Runner.execute` uses
  `sermon_workflow_jobs.start_job/inspect_job`; new task IDs grant no attempt.
- Nodes persist a bound request, output and receipt under `nodes/<unit>/`.
  A receipt is accepted only after the job succeeded, its exact hash appears in
  the completed v3 worker span, and any L2 synthetic reservation is settled.
  An exit code or a free-form span ID alone is insufficient.
- L2 uses one shared existing `BudgetStore` per mock plan. Its quota is labeled
  synthetic; dimensions are test values, **not measured provider tokens/cost**.
  Only a known non-mutating busy lock may retry admission within a live call.
- Prefect threads schedule; existing jobs execute processes. In-process pools
  constrain this run. Mock local-model work additionally takes the existing
  cross-process `local_model_slot`; no model is loaded. A polling boundary that
  cannot prove process termination latches dispatch closed **before releasing
  the local permit**. A new owner read-only checks prior jobs and refuses new
  dispatch while any prior worker is active/uncertain.
- Human gates either block before compute allocation or use explicit simulated
  evidence. `realHumanStatus` remains pending, `reviewVerdict=synthetic_pass`
  and `admissionStatus=mock_only`. Text-only audio still creates a same-locale
  mock `audio_unavailable` artifact before page assembly.

`snapshot.json` is an atomic derivative with business `runId`, `planSha256`, unit,
job, flow/task IDs, execution/review/human/admission fields and receipt hashes.
It never grants dispatch. `accounting-sessions/<id>.json` maps accounting runs to
that business plan. The append-only v3 ledger contains actual measured mock
process spans, dependency span edges, readiness/queue timestamps and receipt
hash proofs; actual executor is deterministic, never a pretend model call.
Readiness means dependency validation finished in this adapter. The receipt's
elapsed duration measures its inner mock work; the accounting span additionally
includes logging/persistence. Neither is a real-model speed estimate.

The separate progress API (`sermon_run_progress`) and readonly diagnostic API
(`sermon_agent_diagnostics`) retain their own contracts and owners. Their caller
integration is pending reviewed heads. Do not infer a production completion
percentage from this mock snapshot. No live Agents API adapter is enabled.

## Validation and remaining gates

```sh
python -m unittest tests.test_sermon_prefect_dag -v
SERMON_TEST_PREFECT=1 python -m unittest tests.test_sermon_prefect_runtime -v
```

The second check launches an actual temporary local Prefect engine and checks
three-locale process execution, L2 overlap (maximum 2), L3 capacity 1, all dependency
edges/job bindings, zero provider events, exact replay and unchanged quota.
A separate optional-dependency GitHub workflow runs it; ordinary root CI skips
only this engine test when `SERMON_TEST_PREFECT` is absent.

Focused failures cover quota exhaustion, unknown outcome, corrupt/missing
receipts, real human wait, owner contention, surviving workers, changed plan/code
and ambient Prefect storage configuration. These are developer/mock checks, not
D7 acceptance. Unknown/abandoned work requires reconciliation; this pilot does
not invent a raw-response reconstruction or production retry adapter. Full
real-producer dispatch, production receipt recovery and rollout remain gated.
