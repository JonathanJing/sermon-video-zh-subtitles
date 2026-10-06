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
