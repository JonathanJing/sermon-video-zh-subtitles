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
| Backend scaffold | Partial, not deployed | `backend/` defines public Sunday read APIs, admin generation APIs, manifest filtering, and a worker planner, but the current Dockerfile only serves static `web/` files. |
| GCS artifact storage | Partial | Generated artifacts can be uploaded to GCS, but there is no stable Sunday promotion flow that public clients can rely on every week. |

## Requirement Matrix

| Requirement | Status | Gap |
|---|---|---|
| Manual admin trigger with live URL and optional sermon start hint | Partial | UI concept exists and backend planner accepts fields, but the deployed service does not expose a working admin generation API. |
| Scheduled automatic live-source discovery | Missing | No implemented `live-source-monitor`, Cloud Scheduler trigger, same-sermon confidence check, or 09:58 fallback alert. |
| Same Sunday, same artifact set for all users | Partial | The storage model is documented, but there is no promoted `sundays/YYYY-MM-DD/cloud-manifest.json` pointer flow. |
| Read-only congregation view | Missing | Current page still mixes congregation playback with operator controls. Public users should not see generation, export, publish, or admin controls. |
| 11:25 readiness and publish gate | Missing | There is no durable readiness state, publish timestamp, published artifact URI, or fallback state. |
| Real generated Chinese captions | Partial | Batch OpenAI translation exists for prepared playback, but the worker planner does not yet run the translation step automatically. |
| Realtime low-latency captioning | Missing | No streaming audio ingest, realtime ASR/translation provider, WebSocket/SSE caption stream, or latency instrumentation. |
| Scripture/name/term priority | Missing | Static scripture/sidebar examples exist, but no deterministic Bible index, glossary resolver, or review queue. |
| Notes and quote extraction | Missing | Planned only; no traceable `insights/*.json` output or UI integration. |
| Cloud Run API deployment | Missing | Current `Dockerfile` runs `python -m http.server` over `web/`; `/api/*` is not served by the deployed Cloud Run service. |
| Firestore state | Missing | Session and caption state are modeled in docs but not persisted. |
| GCS/Secret boundary | Partial | Artifacts are sanitized, but automated worker logs, runbooks, and future manifests must keep the same boundary. |

## P0 Blocking Gaps

1. **Split public and operator surfaces.** The 11:30 congregation page must be a clean read-only caption view. Operator controls belong behind an admin route or authenticated mode.
2. **Deploy the backend/API surface.** The current Cloud Run service is static-only. Production needs a combined static/API service or separate `web` and `api` services with documented routing.
3. **Promote stable Sunday manifests.** Each Sunday needs a stable server-side pointer such as `gs://<bucket>/sundays/YYYY-MM-DD/cloud-manifest.json`, with completion/readiness state.
4. **Make backend generation run the real translation chain.** `backend.worker` currently plans `prepare_live_link_playback.py`; it does not automatically run OpenAI translation, publish translated playback, and promote the Sunday manifest.
5. **Add readiness/publish state.** Operators need `source_detected`, `caption_generating`, `needs_review`, `ready`, `published`, and `fallback` states before 11:25 PT.
6. **Implement source discovery.** Manual links are useful, but the Sunday system still needs automatic discovery of 8:30/10:00 live sources and same-sermon validation.

## P1/P2 Gaps

- Realtime streaming provider interface and latency budget enforcement.
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
- Docker/API shape test: prevent a deployment from being described as an API deployment when the container only serves static files.
- 11:25 no-go checklist: document the exact evidence an operator needs before publishing to the 11:30 congregation.
- 11:30 congregation smoke evidence: record mobile/tablet access, subtitle readability, current Sunday slice, and whether the published captions are generated or placeholder text.

## Recommended Next Build Order

1. **P0-A: Public/operator split.** Add explicit congregation and operator modes, hide all admin controls from public mode, and update E2E coverage for iPhone/iPad widths.
2. **P0-B: Sunday manifest promotion.** Write a small promotion command that validates a run manifest and copies/promotes it to the stable Sunday pointer.
3. **P0-C: Deploy backend API.** Replace the static-only Cloud Run container with an API server that also serves static assets, or deploy a separate API service and update docs.
4. **P0-D: Full worker chain.** Make the backend worker run prepare -> translate -> sanitize -> upload -> promote, with a dry-run mode and tests.
5. **P0-E: Readiness/publish gate.** Persist readiness state and expose it to the operator UI and public Sunday read path.
6. **P1: Scheduled live monitor.** Add Sunday source discovery with fixture-based tests before relying on live network behavior.

## Deployment Decision

The current static PWA can remain deployed for UI and playback simulation testing. A production-style redeploy should wait until at least the public/operator split and backend API routing are implemented. Deploying the current static-only image again would not reduce the main 11:30 service risk because it still cannot trigger, publish, or serve Sunday manifests through the backend API.
