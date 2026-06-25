# System Design Gap Analysis

Last updated: 2026-06-23

Chinese version: [system-design-gap-analysis.zh.md](./system-design-gap-analysis.zh.md)

## Scope

This review checks the current repository and deployed proof of concept against the product north star:

```text
Chinese-speaking congregants should have usable captions during the Sunday 11:30 PT sermon.
```

The current POC is valuable, but it is not yet the production system described in [system-design.md](./system-design.md). The main risk is confusing a successful offline/live-archive replay with a reliable Sunday 11:30 congregation service.

## Current Evidence

| Area | Current state | Evidence |
|---|---|---|
| Public VOD timing analysis | Done | Public VOD availability is too late for the 11:30 use case; the design correctly moved to earlier live sources. |
| Live archive POC | Partial | `scripts/prepare_live_link_playback.py` can prepare playback data from a live archive URL and write local/GCS artifacts. |
| OpenAI translation E2E | Partial | `scripts/translate_playback_with_openai.py` can replace placeholder Chinese with real segment-level translations for a prepared playback file. |
| Static PWA | Partial | The Cloud Run deployment serves the current web prototype and local/remote E2E checks pass. |
| Public disclaimer and secret hygiene | Partial | Public UI includes disclaimer text, tests scan browser playback output, and generated public artifacts avoid raw keys and Secret Manager resource names. |
| Backend scaffold | Partial | `backend/` defines public Sunday read APIs, admin generation APIs, realtime session/event APIs, manifest filtering, and a worker planner. The current Dockerfile starts `python -m backend.app`. |
| GCS artifact storage | Partial | Generated artifacts can be uploaded to GCS, but there is no stable Sunday promotion flow that public clients can rely on every week. |

## Requirement Matrix

| Requirement | Status | Gap |
|---|---|---|
| Manual admin trigger with live URL and optional sermon start hint | Partial | UI concept exists and backend planner accepts fields, but the deployed service does not expose a working admin generation API. |
| Scheduled automatic live-source discovery | Missing | No implemented `live-source-monitor`, Cloud Scheduler trigger, same-sermon confidence check, or 09:58 fallback alert. |
| Same Sunday, same artifact set for all users | Partial | The storage model is documented, but there is no promoted `sundays/YYYY-MM-DD/cloud-manifest.json` pointer flow. |
| Read-only congregation view | Missing | Current page still mixes congregation playback with operator controls. Public users should not see generation, export, publish, or admin controls. |
| 11:25 readiness and publish gate | Missing | There is no durable readiness state, publish timestamp, published artifact URI, or fallback state. |
| Real generated Chinese captions | Partial | Batch OpenAI translation exists for prepared playback and the worker plan includes prepare -> translate -> notes -> upload -> promote; production verification still needs real Sunday inputs. |
| Offline ASR fallback | Partial | When no English captions are available, the live-archive preparation path can extract audio and request `gpt-4o-transcribe` before `gpt-5.5-mini` translation, but this still needs live YouTube/archive validation. |
| Realtime low-latency captioning | Partial | Admin iPad/iPhone mic can create an OpenAI Realtime translation session, send browser WebRTC audio, post English/Chinese deltas to backend memory/JSONL, and stream them to the public caption view over SSE. `scripts/realtime_media_worker.py` can create backend-only sessions, plan authorized audio/YouTube source preparation, and replay/publish events into the same session stream. `scripts/stabilize_realtime_deltas_with_openai.py` can use `gpt-5.5-mini` to turn saved realtime English windows into stable Chinese corrections. Production server-side OpenAI Realtime audio streaming and durable state storage are still missing. |
| Scripture/name/term priority | Missing | Static scripture/sidebar examples exist, but no deterministic Bible index, glossary resolver, or review queue. |
| Notes and quote extraction | Partial | Worker plan includes `generate_notes_with_openai.py` with `gpt-5.5-mini`; production review and UI surfacing still need hardening. |
| Cloud Run API deployment | Partial | Current `Dockerfile` starts `backend.app`; deployment still needs environment verification for `/api/*`, Secret Manager, and realtime session creation. |
| Firestore state | Missing | Session and caption state are modeled in docs but not persisted. |
| GCS/Secret boundary | Partial | Artifacts are sanitized, but automated worker logs, runbooks, and future manifests must keep the same boundary. |

## P0 Blocking Gaps

1. **Split public and operator surfaces.** The 11:30 congregation page must be a clean read-only caption view. Operator controls belong behind an admin route or authenticated mode.
2. **Verify and deploy the backend/API surface.** The repository container now serves static assets and `/api/*` from `backend.app`; production still needs environment verification for routing, auth, Secret Manager, and realtime session creation.
3. **Promote stable Sunday manifests.** Each Sunday needs a stable server-side pointer such as `gs://<bucket>/sundays/YYYY-MM-DD/cloud-manifest.json`, with completion/readiness state.
4. **Validate the real generation chain on a fresh Sunday input.** `backend.worker` now plans prepare -> translate -> notes -> upload -> promote, but it needs an end-to-end run with live archive captions and the no-caption ASR fallback.
5. **Add readiness/publish state.** Operators need `source_detected`, `caption_generating`, `needs_review`, `ready`, `published`, and `fallback` states before 11:25 PT.
6. **Implement source discovery.** Manual links are useful, but the Sunday system still needs automatic discovery of 8:30/10:00 live sources and same-sermon validation.

## P1/P2 Gaps

- Durable realtime session/segment storage and latency budget enforcement.
- Server-side OpenAI Realtime audio streaming from YouTube live / authorized audio sources beyond the current media-worker source-prep and event-publishing scaffold.
- Firestore or equivalent durable session/segment state.
- Cloud Scheduler/Tasks configuration for Sunday monitor and worker jobs.
- Dedicated service account and IAM least-privilege wiring for GCS and Secret Manager.
- Operator authentication fully wired to deployed admin APIs.
- Deterministic scripture, Bible book, person-name, and theology-term resolver.
- Timeline editing persistence for split, merge, lock, and reviewed exports.
- Notes, summaries, application questions, and quote extraction with source segment traceability.
- Historical replay fixtures for regression testing translation quality and UI stability.
- English/Chinese documentation parity where the Chinese system design has deeper API/data-model detail than the English version.

## Validation Gaps To Add

- Congregation-mode DOM/E2E test: the public view must not show monitoring, manual trigger, simulation playback, export, publish, logs, or other operator controls.
- Manifest contract test: a public Sunday manifest must include readiness/completion state, generation time, live URL, sermon title, translation status, and complete output references before being treated as ready.
- Docker/API shape test: prevent a deployment from being described as production-ready when `/api/*`, auth, Secret Manager, and realtime session creation are not verified.
- 11:25 no-go checklist: document the exact evidence an operator needs before publishing to the 11:30 congregation.
- 11:30 congregation smoke evidence: record mobile/tablet access, subtitle readability, current Sunday slice, and whether the published captions are generated or placeholder text.

## Recommended Next Build Order

1. **P0-A: Public/operator split.** Add explicit congregation and operator modes, hide all admin controls from public mode, and update E2E coverage for iPhone/iPad widths.
2. **P0-B: Sunday manifest promotion.** Write a small promotion command that validates a run manifest and copies/promotes it to the stable Sunday pointer.
3. **P0-C: Verify backend API deployment.** Deploy or redeploy the `backend.app` container and smoke test `/api/health`, admin status, realtime session creation, and public Sunday reads.
4. **P0-D: Full worker chain E2E.** Run prepare -> ASR fallback if needed -> translate -> notes -> upload -> promote with a dry-run mode and tests.
5. **P0-E: Readiness/publish gate.** Persist readiness state and expose it to the operator UI and public Sunday read path.
6. **P1: Scheduled live monitor.** Add Sunday source discovery with fixture-based tests before relying on live network behavior.

## Deployment Decision

The current PWA can remain deployed for UI and playback simulation testing. A production-style redeploy should use the `backend.app` container and should not be treated as ready until `/api/health`, admin status, realtime session creation, Sunday manifest reads, and Secret Manager access have all been smoke-tested in Cloud Run.
