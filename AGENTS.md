# Repository Agent Guide

Help Chinese-speaking attendees follow an English sermon. For GPT-6 agents, use this file as a task router: start from the requested deliverable and its current evidence, and read only the references needed for that path. [Workflow map](docs/workflows/README.zh.md) describes product scope, while dated reports record past runs rather than current readiness.

Treat an action request as permission to complete its reversible preparation and verification. Make routine choices from existing policy and evidence, carry the work past the first draft, and ask only when missing input materially changes the result or an irreversible step lacks authorization. Prior authorization remains valid for the same bound action. A review checkpoint should name the exact artifact, changed evidence, and decision needed; it is not a generic pause after each layer.

| Task | Open when needed |
|---|---|
| Prepared multilingual text, audio, or weekly page | [Four-layer contract](docs/multilingual-production-interfaces.zh.md), then the affected layer's producer/runbook |
| Resume a weekly production run | [Local production runbook](docs/codex-local-production-runbook.zh.md) and the existing run artifacts |
| Manual dual-PDF production | [Stable post-live workflow](docs/stable-post-live-reading-pdf-workflow.md) |
| Supervisor state or tools | [Supervisor contract](docs/sermon-production-supervisor-agent.md) |
| Sunday live captions or offline backup | [Live POC instructions](experiments/local-live-poc/AGENTS.md) or [fallback skill](skills/live-caption-zh-fallback/SKILL.md) |
| iOS client | [iOS instructions](apps/tongxing-ios/AGENTS.md) |
| Benchmark, model trial, or post-training | README Discovery links and that experiment's contract |

Before translating or reviewing sermon wording, preparing dubbing, or delivering a series page, use the relevant entries in the [shared terminology table](docs/series-terminology.zh.md). Add a verified new series with source evidence when it enters production. Reading or updating this table does not establish that a producer consumed it.

## Prepared production: four layers

Follow the versioned [four-layer contract](docs/multilingual-production-interfaces.zh.md). Each stage consumes matching upstream hashes and produces its own package:

1. **Shared English Source & Anchors** → `English Source Package`.
2. **Target-Language Text** → one `Target-Language Candidate` per locale.
3. **Target-Language Audio & Synchronization** → one same-locale `Target-Language Audio Package`, including explicit `audio_unavailable` for text-only delivery.
4. **Multilingual Delivery & Playback** → one `Target-Language Release Package` per `pageId + targetLocale`.

Do not skip a layer, repair upstream content downstream, or turn a machine review into human approval. A changed Layer 1 identity invalidates every locale; a changed Layer 2 or 3 artifact invalidates only that locale's downstream work. Reuse still-valid packages, approvals, hashes, and cached model results; request review again only for changed evidence or a genuinely unresolved decision. Keep each locale independent so one locale's issue does not stall the others.

For Layer 2, follow the checked-in translation policy for that run. Where the approved policy is Astra initial translation → Sol independent review per group, run those roles on the same frozen English units without adding a routine Astra or Gemini third-pass gate. If Sol flags a failure, issue, or uncertainty, retain that evidence, start a new revision for the repair, and rerun its prescribed translator, reviewer, language plugin, and candidate-admission chain. Model review remains machine evidence; the schema's human translation approval remains separate. Gemini A/B judging is experimental unless that run's policy explicitly requires it. Independent groups or locales may run with bounded concurrency when the producer supports it; keep stateful Supervisor transitions and writes lease-protected.

Layer 4 may record `published_http_verified` while device or venue acceptance remains `not_run`; report those fields independently. Do not hold page publication for an unrelated PDF, live session, poster, model benchmark, or venue test. Honor an explicit release plan that requires several locales to finish together. A text-only locale may proceed through its explicit `audio_unavailable` path when the release plan permits it. Existing dual-PDF, Chinese dubbing, catalog, and release tools retain their actual legacy scope until canonical packages and gates exist. Sunday live captions remain a separate `live_session`; a finalized recording reused for durable content starts at Layer 1. Report `dual_pdf`, `live_session`, or `four_layer_release` precisely.

## Evidence and execution

- Use public or user-authorized media; preserve source attribution. This personal project is not affiliated with Mariners Church. Label generated content and review status accurately. Keep credentials, cookies, private media, and personal data out of Git and logs.
- Preserve canonical source ID/URL, date, media hash/duration, approved window, model/prompt identity, and review receipts required by the affected contract. Reuse a human sermon-window approval bound to unchanged source/timeline evidence; ask for a new decision only when that binding changes. Preserve immutable ASR finals and source provenance.
- Resume from verified artifacts rather than repeating downloads or paid stages. Check current branch and relevant diffs before editing; preserve unrelated work. Version any schema change with its migration. Keep ignored media, `artifacts/`, `tmp/`, `output/pdf/`, recordings, environments, and build outputs outside Git.
- Separate code/test results, publication and HTTP evidence, device playback, and venue acceptance. Missing required evidence prevents the corresponding status, not unrelated progress. A screenshot, health check, or replay does not prove live/venue readiness.
- Choose the affected tests and real-path checks from the relevant runbook. For docs-only changes, use `git diff --check` and check affected links/commands. After checks pass, widen or repeat only for a concrete failure, new change, or remaining risk. Report the verified scope and limitations.

For a requested weekly poster, or the default poster following a verified weekly content release, follow [the poster procedure](docs/tongxing-weekly-release.zh.md#每周海报交付). Its image and QR checks are separate from page publication and audio/venue acceptance; it does not block the page. Do not send or upload it without the user's instruction.

Do not commit or push unless requested. Before a requested push, fetch/check the target branch and verify the remote commit. History rewriting requires explicit authorization.
