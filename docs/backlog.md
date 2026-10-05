# Development Backlog

> The canonical, unified Dev backlog is maintained in Chinese at [Dev 统一 Backlog](./backlog.zh.md). It owns cross-layer priorities, stable IDs, dependencies, and completion boundaries for Layer 1–4, Firebase Dev, Web/iOS, far-field alignment, CI, review tooling, and the separate live session.
>
> The English sections below are the preserved 2026-06-22 live-caption snapshot. They are not the current top-level plan; active work is mapped in the canonical backlog.

Latest remaining-work plan: [PR #242 backlog](./backlog.zh.md#pr242-remaining-backlog), with 24 implementation and acceptance tasks mapped to existing parent IDs. Historical checkpoints below retain their original evidence scope.

Prompt governance follow-up: [per-stage prompt library, review and iteration](./backlog.zh.md#prompt-library-review-iteration), tracked as `DEV-PROMPT-001`–`004`. Translation and reviewer prompts are the first priority; the inventory includes actual builders, rules, schemas and CLI wrappers. These are pending implementation requirements and do not change production prompts or authorize paid evaluation.

Current status refresh: [2026-10-05 audit and missing work](./backlog.zh.md#backlog-status-audit-20261005). Merged software, bounded prior acceptance, open-PR work and uncommitted Spark work are separated from remaining real production evidence; `DEV-R242-025`–`028` cover model migration acceptance, strict CLI budgets, quota fallback and Spark session exclusivity.

Latest real-run follow-up: [180-second diagnostic issues and acceptance criteria](./backlog.zh.md#dev-180s-diagnostic-followup), tracked as `DEV-DIAG-001`–`014` under existing engineering items. With the authorized allowance increase, 39 groups passed Astra→Sol→language-plugin admission and an independent preview renderer produced 39 fresh, fully decoded WAVs. The 298-file Dev deployment and short browser playback in all three languages passed. [Continuation evidence](./reports/20260930-dev-180s-continuation.zh.md) preserves the native TTS worker import failures, partial critical-path evidence and missing live Agent diagnosis; this remains a diagnostic preview, not a formal four-layer release.

The [2026-10-01 retrospective coverage audit](./backlog.zh.md#dev-180s-first-implementation-batch) maps all ten flow stages to existing IDs and explicitly adds back-transcription, full listening/synchronization and unified delivery acceptance. The first implementation batch addresses `DEV-DIAG-011/012/013` and the pre-dispatch API terminal gap in `008` on `codex/dev-diagnostic-contract-fixes-20261001`; these remain `in_progress` until merge and required real-path evidence.

Legacy snapshot last updated: 2026-06-22

Canonical backlog: [backlog.zh.md](./backlog.zh.md)

Dated implementation evidence and the remaining gates for all 38 active items: [2026-09-30 checkpoint (Chinese)](./reports/20260930-overnight-implementation-checkpoint.zh.md). Draft PRs and synthetic tests do not establish merged, real-media, device, or venue acceptance.

Progress and ETA follow-up: [canonical requirements and acceptance fixtures](./backlog.zh.md#progress-eta-followup), under existing `DEV-TRACK-001` / `DEV-SPD-002` / `DEV-SPD-001`. The earlier sequencing checkpoint (L2 0/39, TTS 0) is historical: the user subsequently authorized continuing and exposing issues, resulting in the preview delivery above. Retain ASR, source evidence and ledgers; frozen denominators, separate processing/review/actual-versus-simulated human approval, and resource-aware ETA ranges remain requirements. A complete live DAG and production ETA have not been verified.

The [Prefect and Agents API pilot contract (Chinese)](./prefect-agents-diagnostic-pilot.zh.md) extends `DEV-SPD-006` with editable interfaces, existing-code mappings and a failure acceptance matrix. Prefect wraps existing local jobs, receipts, budgets and gates. Agents API diagnoses redacted evidence with no business mutation or execution authority. The original $40 run allocation did not fund live Agent diagnosis; later user authorization raised the diagnostic allowance, but the current live adapter still refuses dispatch. A funded allowance does not establish a working integration. This documentation does not activate either integration or production rollout.

CI/CD implementation details: [CI/CD backlog (Chinese)](./ci-cd-backlog.zh.md). The canonical backlog retains the priorities and stable IDs.

Current native-client requests are maintained in the [Tongxing iOS backlog (Chinese)](../apps/tongxing-ios/BACKLOG.zh.md): Dynamic Island, on-demand microphone alignment, localization, and bilingual transcripts.

This backlog keeps implementation work aligned with the product north star: Chinese-speaking congregants should have usable Chinese captions during the Sunday 11:30 PT sermon.

## Current POC State

- The live-link POC can discover a matching edited sermon VOD from a live archive link, infer sermon start, and extract existing captions.
- The web prototype can show operator controls, sermon title, source status, generated-state captions, scripture sidebar, and VTT/SRT export actions.
- Generated reports, subtitles, playback data, and cloud manifests can be published to GCS.
- API/model key material is not written into artifacts; Secret Manager resource names are validated when provided.
- The next product step is replacing placeholder Chinese captions with real model-generated Chinese captions while keeping the public congregation view clean.

## P0 - Service-Time Caption Usability

### P0.1 Translation Provider Integration

Goal: replace `AI 中文待生成` placeholders with real Chinese captions while preserving English sidecar text.

Acceptance criteria:

- Add a provider interface for realtime or segment-level translation.
- Support at least one model provider in a mockable way.
- Apply glossary constraints for Bible books, names, and common theological terms.
- Keep API keys only in Secret Manager or runtime env vars, never in generated reports, manifests, JS, logs, or subtitle files.
- Tests cover successful translation, fallback behavior, empty segments, and secret hygiene.

### P0.2 Separate Congregation And Operator Views

Goal: the 11:30 congregation sees a clean caption page; only operators see monitoring and review controls.

Acceptance criteria:

- Support `operator` and `congregation` view modes.
- Congregation view hides monitor, simulation, export, publish, and log controls.
- Operator view keeps source status, review, scripture sidebar, and publish controls.
- Public playback JS contains no secret values or Secret Manager resource names.
- iPhone/iPad portrait and landscape layouts remain readable.

### P0.3 Readiness And Publish State

Goal: the operator can decide by 11:25 PT whether captions are ready for the 11:30 service.

Acceptance criteria:

- Track readiness states: `source_detected`, `caption_generating`, `needs_review`, `ready`, `published`, `fallback`.
- Show source URL, sermon title, generated segment count, last update time, and warnings.
- Record publish timestamp and published artifact URI.
- Store state in a shape that can move from local POC to Firestore.

### P0.4 Cloud-Readable Artifact Manifest

Goal: Cloud Run or the web app can load generated content from GCS through a stable manifest.

Acceptance criteria:

- `cloud-manifest.json` includes playback JS, report, subtitle files, generation time, live URL, sermon title, and translation status.
- Manifest marks completion state so partial GCS uploads are not treated as valid.
- Manifest can be loaded by server-side Cloud Run code.
- Public browser artifacts do not expose secret references.

## P1 - Realtime Reliability And Review

### P1.1 Scripture And Term Resolver

Goal: realtime captions should prefer stable Bible, name, and theological terminology.

Acceptance criteria:

- Add a deterministic Bible-book/name glossary.
- Detect explicit references such as `Numbers 16` / `John 3:16`.
- Attach scripture candidates to caption segments.
- Low-confidence terms enter the operator review list.

### P1.2 Latency Metrics

Goal: monitor whether captions are fast enough for the 11:30 congregation.

Acceptance criteria:

- Segment data includes `received_at`, `generated_at`, `published_at`, or equivalent timestamps.
- Operator view shows latest, average, and worst caption latency.
- Warnings appear when stable/published latency exceeds target thresholds.
- Logs or manifests include a latency summary.

### P1.3 Live Source Monitor

Goal: move from manual live archive POC to Sunday source discovery.

Acceptance criteria:

- Monitor Mariners Online, YouTube streams, and manually configured fallbacks.
- Output structured evidence: source URL, state, timestamp, title, and same-sermon confidence.
- Mark 10:00 PT as the conservative fallback if earlier sources fail.
- Alert the operator by 09:58 PT if no usable source is found.
- Tests use fixtures/mocks instead of live network calls.

### P1.4 Minimal Timeline Review Tool

Goal: the operator can fix alignment instead of only watching simulation playback.

Acceptance criteria:

- Support segment offset, split, merge, and lock.
- Batch offset does not modify locked segments.
- Edited timeline exports valid VTT/SRT.
- iPad landscape operator view remains usable.

## P2 - Offline Enhancement

### P2.1 Notes And Quote Extraction

Goal: after service, generate traceable sermon notes, summary, application questions, and quote candidates.

Acceptance criteria:

- Generate notes from reviewed/published captions.
- Each quote keeps source segment id, English source text, Chinese caption, and timecode.
- Results write to GCS under `insights/*.json`.
- UI can display the notes tab.

### P2.2 Cloud Run Deployment Skeleton

Goal: move the POC from local static files to a deployable service.

Acceptance criteria:

- Minimal Cloud Run service serves PWA static assets and manifest/playback data.
- Deployment docs cover service account, GCS bucket, and Secret Manager permissions.
- Use [Cloud Run deployment prep](./cloud-run-deployment-prep.md) as the pre-deploy checklist.
- Local start and deployment commands are documented.
- Health check endpoint is available.

### P2.3 Historical Quality Replay Set

Goal: continuously test translation quality and UI stability against multiple sermons.

Acceptance criteria:

- Maintain a small set of metadata-only replay fixtures.
- Do not commit long transcripts or generated sermon content.
- Quality regression checks detect placeholder Chinese, empty captions, reversed timecodes, and secret leakage.

## Coordination Notes

- UI work should prioritize the congregation view first, then operator controls.
- Dev work should keep provider interfaces mockable and artifact storage explicit.
- Review/testing should focus on secret hygiene, public JS boundaries, GCS manifest validity, and latency calculations.
- Debug work should start with playback simulation, secret boundaries, and manifest loading.
