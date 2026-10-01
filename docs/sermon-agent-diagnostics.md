# Offline Agents API diagnostic adapter

This implements the diagnostic lane of the [pilot interface spec at PR #182, commit f8f411d](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/f8f411d22eccb43a89fa645b0b9eda6ee8d6813a/docs/prefect-agents-diagnostic-pilot.zh.md#interfaces), under `DEV-SPD-006`. Implementation and fixed fixtures precede the paused real test. It does not close the epic or resume that run.

**Offline only; live Agents API compatibility and diagnostic usefulness are untested.** No client is constructed, credential inspected, network called, subscription created, budget reserved, or production integration enabled. `diagnose` requires an injected client whose `offline` assertion is `True`. Injected code is trusted application code, not a sandbox. The current US$40 production/diagnostic-run ledger is never accessed. A live binding requires separate data-scope, model, budget, call/turn/time-limit and stop-condition approval, followed by live compatibility testing.

## Contract and mapping

The private [input schema](../schemas/sermon-agent-diagnostic-input-v1.schema.json) accepts a metadata-only event/receipt manifest: exact run/source hash, locale/stage, state revision, package/plan/policy/revision versions, evidence cutoff, failed unit/version pairs, event/receipt/version-diff records, and explicitly missing evidence types. Record hashes cover sorted, compact UTF-8 JSON excluding only `sha256`; they are hashes of redacted metadata, not proof of original artifacts, provider truth or successful review. Actual artifact/receipt verification remains upstream.

No free log text is accepted. Each record has a closed operational reason-code enum; raw prompts, responses, audio, transcripts, private paths, URLs, commands, credentials and unknown fields fail validation. Callers first reduce their authorized source data to this schema. There is no automatic importer of raw logs and no opt-in private-content escape hatch. A missing evidence request does not grant permission to export that content.

`build_context_bundle(manifest)` validates hashes, cutoff, complete identity and failed unit versions, takes an independent copy, then creates snapshot-scoped opaque aliases for local identities, unit versions, evidence/provider-call/attempt/model IDs and original hashes. Local identity and alias mapping remain in the private bundle. The outgoing packet includes only the redacted manifest, snapshot/context binding, recommendation enum and limits. Alias hashes support equality; they are not encryption and stable metadata such as locale, stage and timestamps remains visible within the approved packet scope.

| Pilot draft interface | Implemented v1 mapping |
|---|---|
| `DiagnosticPacket` | `sermon-agent-diagnostic-packet-v1`: `snapshotId`, `contextSha256`, `redactedManifest`, `allowedRecommendationKinds`, `limits`. `failedUnitRefs` map to `failedUnits[].unitId/unitVersion`; events, receipts and version diffs map to their named collections. |
| `DiagnosticReport` | [Output schema](../schemas/sermon-agent-diagnosis-v1.schema.json), `sermon-agent-diagnosis-v1`: `snapshotId`, opaque `identity`, `contextSha256`, `hypotheses[]`, `missingDataRequests`, `limitations`. The output deliberately permits only `classification: hypothesis`; it cannot assert a proven cause. |
| Finding and repair | Each hypothesis includes reason/evidence IDs, confidence and reason, affected units, stage/blocking scope and progress/quality/cost risks, reproduction status/evidence and unknowns. `suggestedRepair.action` maps to draft `kind`; `unitIds` maps to target refs. Preconditions/rationale are inert prose; `requiresDeterministicValidation` is always true. |
| `RecommendationValidation` | `validate_recommendation(diagnosis, bundle, current_identity=...)` checks the report against the frozen bundle and rejects changed identity/state revision. Success means structurally compliant advice only. It does not produce a gate receipt or dispatch a job. |

Recommendation enums are `none`, `inspect_evidence`, `reconcile_unknown`, `request_engineering_review`, `propose_new_revision`, and `propose_version_revalidation`. They have no executable command or tool arguments. Missing or unsupported evidence requires low/unknown confidence, explicit unknowns and a missing-data request. `replayable` requires every cited record to be explicitly typed as reproduction evidence with `status: succeeded`; failed, blocked, not-run and uncertain records cannot establish replayability. Artifact verification remains the exporter’s responsibility. Forbidden URL, credential-marker and private-path patterns are scanned across all lines, including ASCII case variants. All referenced IDs must exist and intersect the hypothesis's affected units; suggestions stay within those units. A Layer 2/3 finding cannot claim all-locale downstream impact.

## API and permission boundary

The outgoing Agents API payload sets `environment: none`, disables delegation, and defines exactly these function tools:

- `read_diagnostic_packet(snapshotId)`
- `read_evidence(snapshotId, evidenceId)`
- `read_version_diff(snapshotId, diffId)`

Handlers return independent copies from the same frozen in-memory bundle. Closed arguments reject extra fields, cross-snapshot evidence, arbitrary paths/URLs and production tools. They never call `inspect_job` (which can reconcile/write), a producer, controller, gate, budget store or approval/publication entry point. Raw evidence cannot expand tools or permissions; report prose is untrusted display data and must never be executed or converted into tool arguments.

The actual adapter follows the [official Agents API function contract](https://developers.openai.com/api/docs/guides/agents-api/tools/functions): pending `required_actions` supply function/turn/call identity and tool results carry `agent.session.input.tool_result`. It uses the root turn's terminal status and a persisted completed final-answer message, per [events/items](https://developers.openai.com/api/docs/guides/agents-api/sessions/events). Idle, a stream ending, a tool acknowledgement and subagent completion do not prove success. No Agents SDK loop or Responses API fallback is used. Final JSON is locally schema-validated; no unsupported provider-side structured-output feature is assumed.

The injected `OfflineAgentsClient` uses the repository client's method names with required `timeout_seconds`: `create_session`, `retrieve_session`, `list_turns`, `list_items`, `submit_tool_result`. The existing live `AgentsAPIClient` is not instantiated or accepted directly. A future live bridge must verify SDK/wire types, terminal item shape, bounded pagination, timeout enforcement and cleanup policy against the then-current API. Official documentation was checked on 2026-10-01; it does not establish live compatibility.

## Bounds and recovery

Defaults are 64 KiB input, 32 KiB diagnosis, depth 12/8,000 JSON nodes, 32 failed units, 64 events, 64 receipts, 16 version diffs, 8 polling steps, 16 distinct tool reads, 30 seconds including earlier saved elapsed time, and 256 KiB per transport response. Hard maxima cap configurable steps/reads/time. Total transport calls are also capped, including repeated pending-result submissions. Input validation occurs before any client call. The transport must bound underlying I/O and honor the remaining deadline; elapsed-time checks cannot forcibly interrupt arbitrary synchronous injected Python code.

The result includes a private serializable checkpoint. The caller owns durable storage and must persist it before attempting explicit recovery. This module performs no file writes and has no background activity. It caches pure tool results before submitting them, keys them by session/turn/call/action hash, and preserves unresolved outcomes. On explicit `checkpoint=...` resume it verifies the payload, snapshot, cumulative bounds and cached result content, retrieves the same session, and reuses results only for matching pending calls. A changed call under the same ID is rejected. It never creates a replacement session, reruns a business operation or automatically retries a transport error. A lost creation response without a session ID blocks recovery. A crash before the caller durably saves the checkpoint remains a limitation; do not restart blindly.

Provenance records session/turn/call IDs, requested/available actual model, snapshot/payload/context hashes, transport outcomes and saved tool-result hashes. Session and root-turn usage remain separate, with missing values `null`, explicit zeros preserved and `costUsd: null`. No usage totals are invented or aggregated twice. Reported usage is best effort, per [official usage documentation](https://developers.openai.com/api/docs/guides/agents-api/observability), and cannot establish a final bill. `executionAuthorized` is always false.

Before any future action, the existing deterministic controller must reread current identity, artifact/receipt validity, dependencies, human gates, leases, resource capacity, shared budget and existing authorization. A valid/high-confidence diagnosis grants none of those permissions. Prefect/DAG integration and progress/ETA are separate owners; shared budget, controller, accounting/logging/progress, README and public client contracts are untouched.

## Offline verification

Run with the repository's existing `jsonschema` dependency installed:

```sh
python -m unittest tests.test_sermon_agent_diagnostics -v
python -m py_compile scripts/sermon_agent_diagnostics.py scripts/sermon_agent_diagnostics_contracts.py
```

The [fixtures](../tests/fixtures/sermon_agent_diagnostics/) contain synthetic identities and metadata only. Tests cover schemas/hashes, secret/private-content/instruction rejection, opaque exports, scope/version/cutoff mismatches, extra tools/URLs/paths, fabricated evidence and cause/reproduction claims, uncertainty requests, stale identity, limits, repeated-result replay, lost acknowledgements, unknown creation, tampered checkpoints, terminal identity and null-versus-zero usage. The success case forbids socket/subprocess execution and runs without environment credentials. These establish offline contract behavior, not live diagnostic quality, cost savings, production readiness or real-media sign-off.
