# Development Backlog

> The canonical, unified Dev backlog is maintained in Chinese at [Dev 统一 Backlog](./backlog.zh.md). It owns cross-layer priorities, stable IDs, dependencies, and completion boundaries for Layer 1–4, Firebase Dev, Web/iOS, far-field alignment, CI, review tooling, and the separate live session.
>
> This page is only an English index into the canonical backlog. The 2026-06-22 live-caption snapshot that used to follow it has been removed and remains in git history; its still-valid requirements are tracked as `DEV-LIVE-001`.

Remaining-work plan (historical 2026-10-04 baseline): [PR #242 backlog](./backlog.zh.md#pr242-remaining-backlog), with the original 24 tasks plus follow-ups 025–028 mapped to existing parent IDs. Historical checkpoints below retain their original evidence scope.

Prompt governance follow-up: [per-stage prompt library, review and iteration](./backlog.zh.md#prompt-library-review-iteration), tracked as `DEV-PROMPT-001`–`004`. Translation and reviewer prompts are the first priority; the inventory includes actual builders, rules, schemas and CLI wrappers. These are pending implementation requirements and do not change production prompts or authorize paid evaluation.

Per-group pipeline: [2026-10-18 per-group independent tasks from Layer 2 through Layer 3](./backlog.zh.md#backlog-per-group-20261018), tracked as `DEV-GRP-001`–`008`; design (Chinese): [per-group independent pipeline](./design/per-group-independent-pipeline.zh.md). Design only; nothing implemented or run.

W42 plan: [2026-10-11 weekly-release retrospective evidence and W42 development plan](./backlog.zh.md#backlog-w42-plan-20261011). The first real three-locale production release advances existing Layer 1–4, rollback and second-week IDs without closing them; three new sub-tasks take stable IDs: `DEV-R242-029` release-entry gates (shell closure, live baseline, browser smoke, feedback catalog), `DEV-R242-030` ASR scoring normalization with conditional secondary ASR, and `DEV-R242-031` post-publication listening sample sheet. Branches, merge order and the freeze timeline are in section 16 of the [retrospective](./reports/20261011-weekly-release-resi-54475d42-retrospective.zh.md).

Current status refresh: [2026-10-10 merged-PR audit](./backlog.zh.md#backlog-status-refresh-20261010), checked against `dev@704d2572`. New Layer 2 runs use budget-bound Sol high/medium OpenAI API; shadow candidate scaffolding remains blocked before transport. The refresh records plugin-concurrency boundaries, Dev shell/bucket guards, isolated experiments, cloud designs, speed evidence and report review. Merged code and passing CI do not establish deployment, production quality, device or venue acceptance. The [2026-10-05 audit](./backlog.zh.md#backlog-status-audit-20261005) retains its historical evidence.

Historical 2026-09-30 real-run checkpoint: [180-second diagnostic issues and acceptance criteria](./backlog.zh.md#dev-180s-diagnostic-followup), tracked as `DEV-DIAG-001`–`014` under existing engineering items. With the authorized allowance increase, 39 groups passed Astra→Sol→language-plugin admission and an independent preview renderer produced 39 fresh, fully decoded WAVs. The 298-file Dev deployment and short browser playback in all three languages passed. [Continuation evidence](./reports/20260930-dev-180s-continuation.zh.md) preserves the native TTS worker import failures, partial critical-path evidence and missing live Agent diagnosis; this remains a diagnostic preview, not a formal four-layer release.

The [2026-10-01 retrospective coverage audit](./backlog.zh.md#dev-180s-first-implementation-batch) maps all ten flow stages to existing IDs and explicitly adds back-transcription, full listening/synchronization and unified delivery acceptance. The first implementation batch addresses `DEV-DIAG-011/012/013` and the pre-dispatch API terminal gap in `008` on `codex/dev-diagnostic-contract-fixes-20261001`; the [later bounded acceptance](./backlog.zh.md#dev-180s-first-implementation-batch) records subsequent implementation and recovery evidence; broader formal production gates remain independent.

Canonical backlog: [backlog.zh.md](./backlog.zh.md)

Dated implementation evidence and the remaining gates for all 38 active items: [2026-09-30 checkpoint (Chinese)](./reports/20260930-overnight-implementation-checkpoint.zh.md). Draft PRs and synthetic tests do not establish merged, real-media, device, or venue acceptance.

Progress and ETA follow-up: [canonical requirements and acceptance fixtures](./backlog.zh.md#progress-eta-followup), under existing `DEV-TRACK-001` / `DEV-SPD-002` / `DEV-SPD-001`. The earlier sequencing checkpoint (L2 0/39, TTS 0) is historical: the user subsequently authorized continuing and exposing issues, resulting in the preview delivery above. Retain ASR, source evidence and ledgers; frozen denominators, separate processing/review/actual-versus-simulated human approval, and resource-aware ETA ranges remain requirements. A complete live DAG and production ETA have not been verified.

The [Prefect and Agents API pilot contract (Chinese)](./prefect-agents-diagnostic-pilot.zh.md) extends `DEV-SPD-006` with editable interfaces, existing-code mappings and a failure acceptance matrix. Prefect wraps existing local jobs, receipts, budgets and gates. Agents API diagnoses redacted evidence with no business mutation or execution authority. The original $40 allocation and adapter block are historical. Later authorized read-only diagnosis completed with `needs_more_evidence` (`DEV-DIAG-004`); that receipt does not grant production execution authority. The separate Agents trials runner currently refuses live mode pending a canonical budget adapter. This documentation does not activate either integration or production rollout.

CI/CD implementation details: [CI/CD backlog (Chinese)](./ci-cd-backlog.zh.md). The canonical backlog retains the priorities and stable IDs.

Current native-client requests are maintained in the [Tongxing iOS backlog (Chinese)](../apps/tongxing-ios/BACKLOG.zh.md): Dynamic Island, on-demand microphone alignment, localization, and bilingual transcripts.
