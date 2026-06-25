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
| Scheduled automatic live-source discovery | Partial | `scripts/live_source_monitor.py` can evaluate Mariners Online, YouTube streams, and manual authorized URLs; fixture tests cover same-sermon confidence, 8:30 -> 10:00 fallback, and 09:58 operator-audio alert. `/api/admin/sundays/{sunday}/discover-source` exposes the same handoff and can return a sanitized generation-plan summary. `scripts/configure_live_source_scheduler.py` now generates a redacted Cloud Scheduler job plan for `/api/admin/sundays/current/discover-source`; real Cloud Scheduler apply, Cloud Logging evidence, and real page validation are still missing. |
| Same Sunday, same artifact set for all users | Partial | The storage model is documented, but there is no promoted `sundays/YYYY-MM-DD/cloud-manifest.json` pointer flow. |
| Read-only congregation view | Implemented locally | `web/index.html` is now a read-only caption view with no operator controls in the DOM; `web/admin.html` keeps generation, export, test, and publish controls. `tests/test_public_admin_boundary.py` and browser E2E checks guard the split. Deployment smoke evidence is still needed. |
| 11:25 readiness and publish gate | Partial | `promote_sunday_manifest.py` now writes a `readiness` contract with state, checks, publish time, published manifest URI, source mode, fallback reason, and model routing. `SundaySliceService` and `/api/admin/status` expose it. Deployment smoke evidence and real Sunday publish evidence are still missing. |
| Real generated Chinese captions | Partial | Batch OpenAI translation exists for prepared playback and the default worker plan now runs prepare -> translate -> export zh VTT/SRT -> validate offline chain -> upload playback/manifest -> promote. Optional notes run only when requested, so they do not block caption publication. `validate_production_readiness.py` can now aggregate offline, promoted-manifest, and realtime JSONL evidence; production verification still needs real Sunday inputs. |
| Offline ASR fallback | Partial | When no English captions are available, the live-archive preparation path can extract audio and request `gpt-4o-transcribe` before `gpt-5.5-mini` translation, but this still needs live YouTube/archive validation. |
| Realtime low-latency captioning | Partial | Admin iPad/iPhone mic can create an OpenAI Realtime translation session, send browser WebRTC audio, post English/Chinese deltas to backend memory/JSONL, and stream them to the public caption view over SSE. `scripts/realtime_media_worker.py` can create backend-only sessions, accept local authorized audio files, venue-provided authorized HTTP(S) audio streams, or authorized YouTube sources, stream 24 kHz PCM16 audio to the OpenAI translation WebSocket, and publish English/Chinese deltas into the same session stream. `scripts/realtime_openai_smoke_test.py` now verifies a short authorized audio clip through OpenAI Realtime and backend SSE when credentials/source audio are available. `scripts/stabilize_realtime_deltas_with_openai.py` can use `gpt-5.5-mini` to turn saved realtime English windows into stable Chinese corrections and post them back as `caption_final` events; `scripts/run_realtime_stabilizer_loop.py` repeats that delayed pass and skips already-posted segments. Production live validation with real authorized sources and durable state storage are still missing. |
| Scripture/name/term priority | Missing | Static scripture/sidebar examples exist, but no deterministic Bible index, glossary resolver, or review queue. |
| Notes and quote extraction | Partial | Worker plan can append `generate_notes_with_openai.py` with `gpt-5.5-mini` when `includeInsights` is requested; production review and UI surfacing still need hardening. |
| Cloud Run API deployment | Partial | Current `Dockerfile` starts `backend.app`; deployment still needs environment verification for `/api/*`, Secret Manager, and realtime session creation. |
| Firestore state | Missing | Session and caption state are modeled in docs but not persisted. |
| GCS/Secret boundary | Partial | Artifacts are sanitized, but automated worker logs, runbooks, and future manifests must keep the same boundary. |

## P0 Blocking Gaps

1. **Verify and deploy the backend/API surface.** The repository container now serves static assets and `/api/*` from `backend.app`; production still needs environment verification for routing, auth, Secret Manager, realtime session creation, and the read-only public/admin split.
2. **Validate stable Sunday manifest promotion in Cloud Run/GCS.** Each Sunday needs the stable pointer `gs://<bucket>/sundays/YYYY-MM-DD/cloud-manifest.json` to be written and read back with readiness state.
3. **Validate the real generation chain on a fresh Sunday input.** `backend.worker` now plans prepare -> translate -> export zh VTT/SRT -> validate offline chain -> upload playback/manifest -> promote with `gpt-4o-transcribe` and `gpt-5.5-mini`, and `validate_production_readiness.py` can bundle the evidence, but it still needs an end-to-end run with live archive captions and the no-caption ASR fallback.
4. **Validate scheduled source discovery in Cloud Run.** `scripts/live_source_monitor.py`, `/api/admin/sundays/{sunday}/discover-source`, and `scripts/configure_live_source_scheduler.py` exist with fixture tests and a redacted dry-run path, but they still need `--apply` verification, Cloud Logging evidence, and real Mariners/YouTube page validation.

## P1/P2 Gaps

- Durable realtime session/segment storage and latency budget enforcement.
- Real-source live validation and hardening for server-side OpenAI Realtime audio streaming from YouTube live / authorized audio sources; the smoke runner exists, but a real credentialed source pass is still required.
- Firestore or equivalent durable session/segment state.
- Cloud Scheduler/Tasks production verification for Sunday monitor and worker jobs.
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
4. **P0-D: Full worker chain E2E.** Run prepare -> ASR fallback if needed -> translate -> export zh VTT/SRT -> validate offline chain -> upload playback/manifest -> promote with a dry-run mode and tests; run optional notes separately with `includeInsights`.
5. **P0-E: Readiness/publish gate.** Persist readiness state and expose it to the operator UI and public Sunday read path.
6. **P1: Scheduled live monitor.** Apply and verify the Sunday source discovery Scheduler job in Cloud Run before relying on live network behavior.

## Deployment Decision

The current PWA can remain deployed for UI and playback simulation testing. A production-style redeploy should use the `backend.app` container and should not be treated as ready until `/api/health`, admin status, realtime session creation, Sunday manifest reads, and Secret Manager access have all been smoke-tested in Cloud Run.
