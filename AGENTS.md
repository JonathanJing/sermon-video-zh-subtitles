# Repository Agent Guide

Help attendees follow English sermons in their target language. Use this file as a task router: start from the requested deliverable and its current evidence, and read only the references needed for that path. [Workflow map](docs/workflows/README.zh.md) describes product scope, while dated reports record past runs rather than current readiness. For new runs, use the current runtime and release policies linked below; existing runs retain their frozen identities. Historical model names or readiness statements in linked overviews do not override these policies or current producer gates.

Treat an action request as permission to complete its reversible preparation and verification. Make routine choices from existing policy and evidence, carry the work past the first draft, and ask only when missing input materially changes the result or an irreversible step lacks authorization. Prior authorization remains valid for the same bound action. A review checkpoint should name the exact artifact, changed evidence, and decision needed; it is not a generic pause after each layer.

| Task | Open when needed |
|---|---|
| Prepared multilingual text, audio, or weekly page | [Four-layer contract](docs/multilingual-production-interfaces.zh.md), then the affected layer's producer/runbook |
| Canonical multilingual App delivery | [Layer 4 public delivery](docs/layer4-four-product-public-delivery.zh.md) and [weekly release](docs/tongxing-weekly-release.zh.md) |
| Resume a weekly production run | [Local production runbook](docs/codex-local-production-runbook.zh.md) and the existing run artifacts |
| Manual dual-PDF production | [Stable post-live workflow](docs/stable-post-live-reading-pdf-workflow.md) |
| Supervisor state or tools | [Supervisor contract](docs/sermon-production-supervisor-agent.md) |
| Sunday live captions or offline backup | [Live POC instructions](experiments/local-live-poc/AGENTS.md) or [fallback skill](skills/live-caption-zh-fallback/SKILL.md) |
| iOS client | [iOS instructions](apps/tongxing-ios/AGENTS.md) |
| Benchmark, model trial, or post-training | README Discovery links and that experiment's contract |

For prepared local production, follow [the compute policy](docs/local-production-compute-policy.zh.md): DGX Spark is the default host for local model compute and MacBook is the fallback; API translation and review retain their configured provider. Preserve an existing job's verified backend/cache identity. Fail over only for confirmed infrastructure/runtime failures, never content, identity, review failures or an unknown remote outcome. Canonical producers without a cross-host adapter still require explicit dispatch; do not claim automatic fallback from policy alone.

For new dev and formal Layer 2 runs, follow [the runtime model policy](docs/production-model-runtime-policy.zh.md): translation uses `gpt-6.1-sol` high and independent review uses `gpt-6.1-sol` medium, both through OpenAI API by default, per the user decision on 2026-10-06. Unbound standalone API requests are refused before dispatch. Authorized standalone runs use `--budget-config` with `--budget-authorization` to dispatch through the canonical controller and reuse its budget contract and approved tier. The Supervisor remains `gpt-6-luna` medium fast through ChatGPT-authenticated Codex CLI. Preserve existing run/cache identities; automatic backend fallback is disabled. The approved [quota fallback design](docs/codex-quota-api-fallback-design.zh.md) is a future contract, not implementation or spending authorization.

For local OpenAI API calls, including transcription, translation, review and audio, reuse the configured `tongxing-dev` / `tongxing-prod` projects and `tongxing-dev-runtime` / `tongxing-prod-runtime` keys through [the explicit environment launcher](docs/openai-minimal-project-setup.zh.md). Development, Beta tests and experiments use dev; formal content generation uses prod. Start the whole supervisor/controller under the launcher, never switch by replacing the legacy `.env` key, and do not create additional keys for routine stages. Keep key values in ignored `.env.openai`, never in logs or Git. Existing running jobs retain their original credential/backend identity; cloud services retain Secret Manager configuration until explicitly migrated.

Before translating or reviewing sermon wording, preparing dubbing, or delivering a series page, use the relevant entries in the [shared terminology table](docs/series-terminology.zh.md). Add a verified new series with source evidence when it enters production. Reading or updating this table does not establish that a producer consumed it.

## Prepared production: four layers

Follow the versioned [four-layer contract](docs/multilingual-production-interfaces.zh.md). Each stage consumes matching upstream hashes and produces its own package:

1. **Shared English Source & Anchors** → `English Source Package`.
2. **Target-Language Text** → one `Target-Language Candidate` per locale.
3. **Target-Language Audio & Synchronization** → one same-locale `Target-Language Audio Package`, including explicit `audio_unavailable` for text-only delivery.
4. **Multilingual Delivery & Playback** → one `Target-Language Release Package` per `pageId + targetLocale`.

Do not skip a layer, repair upstream content downstream, or turn a machine review into human approval. A changed Layer 1 identity invalidates every locale; a changed Layer 2 or 3 artifact invalidates only that locale's downstream work. Reuse still-valid packages, approvals, hashes, and cached model results; request review again only for changed evidence or a genuinely unresolved decision. Keep approval dependencies separate for each locale. The canonical Layer 2 controller defaults to one active locale job per production run; explicit execution-v2 with the frozen concurrency profile permits up to three. An uncertain owner blocks new dispatch across the run until reconciliation. See [the controller contract](docs/canonical-layer2-controller.zh.md) for actual group/API capacity and migration requirements; do not raise an existing job's limits in place. Preserve the release plan's locale join requirements.

For Layer 2, follow the checked-in translation policy for that run. For new dev and formal runs, use Sol 6.1 high initial translation → Sol 6.1 medium independent review per group through OpenAI API, with the request tier allowed by the entry point and its budget contract; for existing runs retain the frozen policy. Run those roles on the same frozen English units without adding a routine Astra or Gemini third-pass gate. If Sol flags a failure, issue, or uncertainty, retain that evidence, start a new revision for the repair, and rerun its prescribed translator, reviewer, language plugin, and candidate-admission chain. Model review remains machine evidence; the schema's human translation approval remains separate. Gemini A/B judging is experimental unless that run's policy explicitly requires it. Independent groups or locales may run with bounded concurrency when the producer supports it; keep stateful Supervisor transitions and writes lease-protected.

Layer 4 may record `published_http_verified` while device or venue acceptance remains `not_run`; report those fields independently. Do not hold page publication for an unrelated PDF, live session, poster, model benchmark, or venue test. Honor an explicit release plan that requires several locales to finish together. A text-only locale may proceed through `audio_unavailable` only when the release plan, producer and clients support it. Use [canonical Layer 4 delivery](docs/layer4-four-product-public-delivery.zh.md) for canonical packages and retain its current human text, listening, study and metadata gates. Legacy tools retain their documented scope and cannot replace this path. Sunday live captions remain a separate `live_session`; a finalized recording reused for durable content starts at Layer 1. Report `dual_pdf`, `live_session`, or `four_layer_release` precisely.

## Evidence and execution

- Use public or user-authorized media; preserve source attribution. This personal project is not affiliated with Mariners Church. Label generated content and review status accurately. Keep credentials, cookies, private media, and personal data out of Git and logs.
- Preserve canonical source ID/URL, date, media hash/duration, approved window, model/prompt identity, and review receipts required by the affected contract. Reuse a human sermon-window approval bound to unchanged source/timeline evidence; ask for a new decision only when that binding changes. Preserve immutable ASR finals and source provenance.
- Resume from verified artifacts rather than repeating downloads or paid stages. Check current branch and relevant diffs before editing; preserve unrelated work. Version any schema change with its migration. Keep ignored media, `artifacts/`, `tmp/`, `output/pdf/`, recordings, environments, and build outputs outside Git.
- Separate code/test results, publication and HTTP evidence, device playback, and venue acceptance. Missing required evidence prevents the corresponding status, not unrelated progress. A screenshot, health check, or replay does not prove live/venue readiness.
- Choose the affected tests and real-path checks from the relevant runbook. For docs-only changes, use `git diff --check` and check affected links/commands. After checks pass, widen or repeat only for a concrete failure, new change, or remaining risk. Report the verified scope and limitations.

For a requested weekly poster, or the default poster following a verified weekly content release, follow [the poster procedure](docs/tongxing-weekly-release.zh.md#每周海报交付). Its image and QR checks are separate from page publication and audio/venue acceptance; it does not block the page. Do not send or upload it without the user's instruction.

After completing scoped work and its relevant verification, commit and push it to the working branch without a separate request. Before pushing, fetch/check the target branch and verify the remote commit. History rewriting requires explicit authorization.
