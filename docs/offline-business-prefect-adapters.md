# Offline Prefect business callback integration

This followup builds on PR186's reviewed local Prefect, progress and readonly
Agents components. It exercises existing business producers with synthetic
media, explicit fixture transport/synth and original validators. It cannot load
API credentials, enable a production transport, produce human approval or publish.
The paused real diagnostic and its budget are not inputs to these adapters.

## Fixed boundary

`sermon_bounded_business_callbacks.BoundedBusinessCallbacks` requires an exact
`DiagnosticProvider` with an explicit `OfflineHTTPTransport`, fixture declaration,
source clip hash and one original budget store. It calls existing `BoundedRun`
ASR/source-check/strict-L2 methods. A pre-existing provider store without the
fixture marker is refused. Socket and HTTP subprocess access is denied; fixture
code is trusted test Python, not an adversarial-code sandbox.

`sermon_local_business_callbacks` wraps existing speech preparation, rendering,
delivery intent validation and local formal staging. Inputs/outputs/accounting
and inherited progress paths must remain inside the declared fixture scope.
Immutable AdmissionBoundary configuration paths must be absolute and scoped;
they are checked again before direct admission. Existing derived output trees
(including receipts and accounting) are checked for redirects before invoking
the renderer or its synth constructor. Hash-bound embedded filesystem paths must be absolute; relative public asset
paths retain the existing explicit asset-root resolution. The default real synth
is forbidden. Injected PCM fixtures exercise the real renderer and full decode
validation. Original public Candidate, strict gate, human/voice and audio review
validators remain unchanged. Local staging is never publication; an existing
output requires original reconciliation, not a fresh output directory retry.

`sermon_business_prefect_flow.Node` is a trusted Python plan, not a serialized
arbitrary callback or shell registry. Allowed operations are:

- `transcribe`, `source_check`, `locale`;
- `admit_locale`, `prepare_speech`, `render_speech`;
- `delivery_preflight`.

`BusinessDAG(root, callbacks, nodes)` freezes input identities and original-file
hashes. The orchestration root must be a dedicated child of the fixture scope
without overlapping business stores; this is checked before lock or plan writes.
`run(root, callbacks, nodes)` starts one fresh-process local Prefect flow
with one callback worker, zero task retries, no Prefect cache/results and isolated
local metadata. Existing business locks, intents, caches and reservations remain
the durable authority. Serialization is intentional because callback transport
guards are process-global; the prior mock pilot's independent worker parallelism
is not a claim that these in-process callbacks run concurrently.

Only internally recorded predecessor outcomes can admit a successor. Local
boundaries must use the same original BudgetStore/run identity; admission binds
actual revision roots/source/anchor/policy/rubric, preparation binds its actual
admission intent, and rendering binds the prepared job. The flow requires same-locale render ancestry and matching L3 artifacts before
considering delivery. The original audio-review continuation is not yet a DAG
operation: it reports `business_delivery_audio_review_continuation_unsupported`
rather than importing unrelated reviewed files. Standalone delivery callbacks
still validate same-locale L3 audio packages and original reviews. A completed task is not a
content pass or approval. An uncertain post-invocation error becomes
`outcome_unknown`; reservations and retry limitations are preserved.

## Alignment and human limits

The ASR-to-L2 fixture route accepts a frozen aligned Source only after existing
ready-package validation, exact anchor hash and word equivalence with the saved
verified ASR response. Case/spacing/punctuation normalization does not create
fresh alignment. It records `frozen_fixture_alignment_not_generated` and rejects
unrelated text before L2. No fresh MFA/alignment producer is wired here.

An actual strictly reviewed Candidate remains `waiting_human`. Explicit
synthetic approval fixtures can exercise the existing AdmissionBoundary and
speech preparation; they do not establish real approval. Missing voice evidence
stops at `awaiting_voice_authorization`. A rendered package still requires
alignment/listening review before delivery. Individual renderer and three-locale
local delivery fixtures exercise these original functions separately; this is
not one proven fresh ASR-to-published-release run.

## Progress evidence

`sermon_business_progress.update(dag)` rechecks original callback artifacts and
completed accounting spans, freezes equal weights per callback node, retains
immutable status observations, and atomically updates `business-progress.json`.
It is called at initialization, each completed dispatch, and flow completion.
Primary `plannedProcessedPercent` is separate from `gateCompletionPercent`.
Weights describe nodes, not segments, quality or wall-time percentage.
Simulated human validation never increments `realHumanApproved`.

Queue/liveness not measured remains unknown. Actual completed-span durations
can become timing samples, but blocked/human/unknown/resource gaps keep ETA
unknown. A prior unknown observation cannot be erased by restart or a new cache
result; this adapter supplies no invented reconciliation proof. No prompts,
transcript text, credentials or arbitrary exception bodies enter the projection.
Original business evidence is private fixture data; reports carry hashes/IDs.

## Focused verification

Use the optional pinned `requirements-prefect.txt` environment and `ffmpeg`:

```sh
SERMON_TEST_PREFECT=1 python -m unittest \
  tests.test_sermon_bounded_business_callbacks \
  tests.test_sermon_local_business_callbacks \
  tests.test_sermon_business_prefect_flow \
  tests.test_sermon_business_progress -v
```

The SDK test uses a disposable local loopback server, explicit fixture HTTP
responses and original ASR/source/strict-L2 validators. It checks six fixture
transport calls for two groups, same-store replay without extra calls, unknown
reservation retention, mismatched ASR/alignment refusal, source scope, forged
upstream refusal and progress. Separate original-receipt fixtures exercise
admission/preparation, renderer/full decode, delivery validation/local staging,
changed approval, path/ambient ledger refusal and interrupted evidence.
No model, cloud account, real ASR/TTS, live Agents request or publication occurs.
