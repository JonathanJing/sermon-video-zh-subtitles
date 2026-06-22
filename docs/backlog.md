# Development Backlog

Last updated: 2026-06-22

Chinese version: [backlog.zh.md](./backlog.zh.md)

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
