# Local diagnostic continuation

The explicit entry connects an **existing** diagnostic Source/ASR receipt chain,
strict per-group translation and independent review, isolated preview audio,
and read-only delivery inspection. It does not create a production Audio
Package or grant human approval. The original paused real run is unchanged.

## Entry and boundaries

`scripts.sermon_diagnostic_prefect_flow` accepts an immutable original plan,
separate continuation identity, locale/preview specifications, and a static
request-hash response fixture for offline checks. The fixture marker must
already match the existing provider/store. Live execution is a separate explicit
`--execute --key-fd` mode; credentials enter only through an inherited private
descriptor after original-ledger and input preflight. Neither mode initializes
a fresh provider ledger or extends its clock.

Continuation request limits are frozen in `continuation-request-limits.json`.
All continuation CLI entries reuse this snapshot when `--request-limits` is
omitted; an explicitly supplied limits file must match it exactly. For an
initial continuation without this snapshot, pass `--request-limits` with the
intended bound limits JSON; the entry does not guess a default. A changed limit
is rejected before dispatch and cannot silently reset an existing run to the
default input bound. The command below assumes the snapshot already exists.

```sh
python -m scripts.sermon_diagnostic_prefect_flow \
  --plan /absolute/fixture/run-plan.json \
  --continuation /absolute/fixture/continuation.json \
  --spec /absolute/fixture/flow-spec.json \
  --offline-fixture --fixture-responses /absolute/fixture/responses.json
```

New sessions use `sermon-diagnostic-dag-session-v2`; v2 explicitly freezes
`requestLimits`. Do not edit an existing v1 `plan.json` or move its Prefect
state into a newly computed directory. To resume an existing v1 Prefect DAG,
add `--resume-plan /absolute/run/diagnostic-prefect/<original-plan-hash>/plan.json`
to the continuation command. Both legacy v1 shapes (with and without the
previously unversioned limits field) are supported. If a legacy binding has no
limits, the original limits must come from an existing frozen continuation
snapshot or an explicit `--request-limits` file; limits are never inferred.

The explicit migration retains the original plan bytes, directory, node
observations and business receipts. It freezes
`session-binding-migration-v2.json` beside the original plan (any older v1
sidecar stays unchanged), mapping the active
v2 execution binding to that original hash. Existing limits, source evidence,
store, deadline, configuration and input hashes must still match. All migration
admission completes before a new immutable limits snapshot is written; a rejected
limit or outer mock plan cannot poison a later valid resume.

For a genuine cross-code migration, provide a newly authorized current-code
`--continuation` and also `--legacy-continuation /absolute/original-continuation.json`.
The latter must match both original continuation and context hashes. All context
fields except the authorized continuation code commit remain fixed. The migration
receipt binds both complete authorizations and the current execution binding;
current clean-code checks still apply, and the old authorization alone is rejected.
Validated legacy context remains attached to existing paid locale request/cache
identities. The strict locale's explicit legacy admission may block reuse when
its original evidence does not prove the newly required rule consumption.

The mock TTS entry point supports the same options, with `--resume-plan` naming
`/absolute/run/mock-tts-dag/<original-plan-hash>/plan.json`. Its separate immutable
migration receipt binds the current wrapper code and nested diagnostic migration,
while preserving the original mock root, plan hash and recovery request identities.
The nested legacy diagnostic binding is verified against the original hashed mock
plan rather than written as a fabricated diagnostic plan. Repeating any migration
must match its frozen receipt; neither path retries calls nor extends budget or clock.
Normal v2 plans remain immutable and do not use this compatibility path.

Use the optional environment from `requirements-prefect.txt`. Prefect runs with
local SQLite, isolated settings and telemetry disabled. Tasks are serial in
this process because the network guards affect process-global functions;
Prefect retries, cache and result persistence are disabled. Original business
receipts, locks and budgets remain authoritative for recovery.

The fixed graph is `source.existing → text.<locale> → preview.<locale>`, with
all selected same-locale previews required by `delivery.readonly`. Locale input
files and referenced voice/checkpoint evidence are frozen before execution.
The preview Candidate path comes exclusively from the actual strict locale
result. A failed machine review blocks that locale's preview.

## Executable acceptance checklist

| Check | Implementation and regression evidence | Meaning |
|---|---|---|
| Original Source and prior calls | `sermon_diagnostic_dag_session.py`, `diagnostic_dag_fixture.py`, `test_sermon_diagnostic_dag_session.py` | Original ASR/source receipts and pending machine findings validated; neither call rerun |
| Strict L2 and replay | Same session tests and `test_sermon_diagnostic_prefect_flow.py` | Generator/reviewer/plugin/Candidate chain consumes matching context; replay retains calls, quota and original clock |
| Preview deadline and uncertainty | `sermon_diagnostic_preview_worker.py`, dedicated tests | Fixed subprocess uses original absolute deadline, kills timed-out process group, keeps immutable unknown attempt rather than retrying |
| Preview provenance | Same worker and delivery tests | Captured ledger snapshots bind the attempt; later settled locale calls do not invalidate prior preview; changed original receipts fail |
| Read-only delivery | `sermon_diagnostic_delivery_preflight.py`, dedicated tests | Every selected locale/group, Candidate, source, voice/checkpoint, unit hash and full decode checked without writes |
| Actual local orchestration | `test_sermon_diagnostic_prefect_flow.py`, optional Prefect CI job | Local SDK runs actual business callbacks with synthetic HTTP responses and fake PCM synthesis; no model inference |

`tests/diagnostic_dag_fixture.py` provides one `zh-Hans` lane with two groups:
two original synthetic provider calls, four fresh synthetic L2 calls, and two
preview audio units. This is an integration sample, not evidence of three-locale
real-media completion. Its original source validator is not mocked. Unit tests
that substitute the clean-code identity guard state that explicitly; the SDK
subprocess check runs against committed clean code.

## Evidence interpretation

The flow saves its immutable plan, per-node result hashes, observations and
production-format accounting under the fixture run. Original model receipt and
usage provenance remain in the same provider ledger. Synthetic tokens, costs,
audio and approvals are not measurements of a real provider or human decision.

Successful traversal reports `diagnostic_traversal_complete`,
`productionEligible: false`, `publicationAuthorized: false`, and human
acceptance pending. Source concerns, translation/listening review,
synchronization, formal audio package and delivery acceptance remain separate
pending gates. Preview output cannot serve as a formal release package.

## Remaining gates before a real continuation

The offline session refuses adoption of a real store or a real key; live mode
refuses fixture stores and injected fixture transport. The live branch is
implemented but has not been exercised with paid models. Before invoking it for
the paused real diagnostic, review/CI must be complete and the **same** original
ledger must have an unexpired explicitly authorized timing bound and approved
existing local voice/model assets. This patch does not activate the saved
timing-extension work, reset the clock, add quota, or resume paid requests.
Real content/listening/device approval and production publication remain outside
this diagnostic's completion claim.
