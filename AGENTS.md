# Repository Agent Guide

Purpose: help attendees follow English sermons in their own language, on time and honestly labeled. This file holds only what must hold on every task and where to look next. Start from the requested deliverable and its current evidence, and read only the references that path needs. Model names, limits, thresholds and status live in the owning document linked below; do not copy them here. The [workflow map](docs/workflows/README.zh.md) describes product scope; dated reports record past runs, not current readiness.

## How to work

- Treat an action request as permission to complete its reversible preparation and verification. Make routine choices from existing policy and evidence, carry the work past the first draft, and ask only when missing input materially changes the result or an irreversible step lacks authorization. Prior authorization stays valid for the same bound action. A review checkpoint names the exact artifact, the changed evidence and the decision needed; it is not a generic pause after each layer.
- Resume from verified artifacts instead of repeating downloads or paid stages. Check the current branch and relevant diffs before editing and preserve unrelated work. Version any schema change with its migration.
- Pick the affected tests and real-path checks from the relevant runbook. For docs-only changes use `git diff --check` and check affected links and commands. Widen or repeat checks only for a concrete failure, a new change or a remaining risk, and report the verified scope with its limits.
- After scoped work and its verification, commit and push to the working branch without a separate request: fetch and check the target branch first, then verify the remote commit. History rewriting requires explicit authorization.
- After every formal or test run, pass or fail, export its redacted [run report](docs/test-run-retrospective.zh.md) and open its docs-only PR so cloud sessions can review it. Never commit raw logs, `artifacts/`, `tmp/`, `output/pdf/`, recordings, environments or build outputs.

## Invariants

1. **Honest labels.** Label generated content and its review status accurately. A machine review or waiver is never human approval: keep `humanApproval=false`, record `review=waived` and show the disclosure; a waiver binds the current implementation, runtime settings, frozen source, candidate and audio. Code support is not evidence of a calibrated run or of an active unattended publisher. Use public or user-authorized media with source attribution; this personal project is not affiliated with Mariners Church.
2. **Bound identity.** Bind every artifact to its inputs by hash: canonical source ID and URL, date, media hash and duration, approved window, model and prompt identity, review receipts, immutable ASR finals. Existing runs keep their frozen model, backend, cache and credential identity; new runs follow the current policies. Reuse a human window approval while its source and timeline binding is unchanged.
3. **Four layers.** Layer 1 English Source & Anchors, then Layer 2 Target-Language Candidate per locale, then Layer 3 Audio & Synchronization package per locale (explicit `audio_unavailable` for text-only delivery), then Layer 4 Release Package per `pageId + targetLocale`. Do not skip a layer or repair upstream content downstream. A changed Layer 1 identity invalidates every locale; a changed Layer 2 or 3 artifact invalidates only that locale's downstream work. Reuse still-valid packages, approvals and cached results, and ask for review again only for changed evidence or a genuinely unresolved decision. Keep approvals per locale and honor the release plan's join requirements.
4. **Separate evidence.** Code and test results, publication and HTTP evidence, browser rendering, device playback and venue acceptance are separate statuses. Missing evidence blocks only its own claim, never unrelated progress; do not hold page publication for an unrelated PDF, live session, poster, benchmark or venue test. A screenshot, health check or replay does not prove live or venue readiness. Report the delivery type precisely: `dual_pdf`, `live_session` or `four_layer_release`. Sunday live captions are a separate `live_session`; a recording reused for durable content starts at Layer 1.
5. **Cost and failure.** Resume paid and remote work instead of retrying it blindly; an unknown outcome stops new dispatch until it is reconciled. Fail over compute only for a confirmed infrastructure failure, never for a content, identity or review failure or an unknown remote outcome.
6. **Secrets and data.** Credentials, cookies, private media and personal data stay out of Git and logs. Use the configured OpenAI projects only through the explicit environment launcher, with no extra keys for routine stages.
7. **Terminology.** Before translating or reviewing sermon wording, preparing dubbing or delivering a series page, use the entries in the [shared terminology table](docs/series-terminology.zh.md). Add a verified new series with source evidence when it enters production. The table is hashed into frozen translation policies, so editing it mid-run means freezing a new policy; reading or updating it does not establish that a producer consumed it.

## Where to look

| Task | Open |
|---|---|
| Prepared multilingual text, audio or weekly page | [Four-layer contract](docs/multilingual-production-interfaces.zh.md), then the affected layer's producer or runbook |
| Layer 2 translation and review: models, budget, tier | [Runtime model policy](docs/production-model-runtime-policy.zh.md); [controller](docs/canonical-layer2-controller.zh.md) for concurrency and recovery |
| Compute host for local model work | [Compute policy](docs/local-production-compute-policy.zh.md) |
| OpenAI keys and projects | [Environment launcher](docs/openai-minimal-project-setup.zh.md) |
| Machine-checked text or audio, or publication without manual review | [Machine-quality waiver](docs/machine-quality-waiver.zh.md): calibration, repair limits, degradation, current wiring limits |
| Canonical App delivery | [Layer 4 public delivery](docs/layer4-four-product-public-delivery.zh.md) and [weekly release](docs/tongxing-weekly-release.zh.md) |
| Weekly poster | [Poster procedure](docs/tongxing-weekly-release.zh.md#每周海报交付): separate from page publication; do not send or upload it without the user's instruction |
| Resume a weekly production run | [Local production runbook](docs/codex-local-production-runbook.zh.md) and the existing run artifacts |
| Manual dual-PDF production | [Stable post-live workflow](docs/stable-post-live-reading-pdf-workflow.md) |
| Supervisor state or tools | [Supervisor contract](docs/sermon-production-supervisor-agent.md) |
| Sunday live captions or offline backup | [Live POC instructions](experiments/local-live-poc/AGENTS.md) or [fallback skill](skills/live-caption-zh-fallback/SKILL.md) |
| iOS client | [iOS instructions](apps/tongxing-ios/AGENTS.md) |
| Priorities, stable IDs and status | [Dev backlog](docs/backlog.zh.md), the only top-level backlog; find an ID's rows with `python3 scripts/backlog_ids.py <ID or prefix>` |
| Benchmark, model trial or post-training | README Discovery links and that experiment's contract |
