# Documentation Guide

<p>
  <a href="./README.zh.md">
    <img src="https://img.shields.io/badge/Language-中文文档-blue" alt="中文文档索引" />
  </a>
</p>

This page routes readers to the maintained contracts; it does not redefine them. Current project claims require the root [README](../README.md), the [workflow source of truth](workflows/README.zh.md), the relevant runbook, code, and bound run receipts. A design, test, or historical report alone cannot promote production status.

Calibrated on **2026-09-20**. Re-read the actual commit, remote deployment, venue evidence, and physical-device acceptance independently; the document date establishes none of them.

## Start with the task

| Task | First reference | Boundary |
|---|---|---|
| Run future prepared multilingual production | [four-layer contract (Chinese)](multilingual-production-interfaces.zh.md) → [local production runbook (Chinese)](codex-local-production-runbook.zh.md) | Layer 1–4 require separate evidence; legacy completion is not four-layer completion |
| Understand the three product paths and completion gates | [Workflow overview (Chinese)](workflows/README.zh.md) | Current top-level source of truth |
| Produce the Saturday dual PDFs | [Local production runbook (Chinese)](codex-local-production-runbook.zh.md) → [stable workflow](stable-post-live-reading-pdf-workflow.md) | Current operator path |
| Inspect or resume the production Supervisor | [Supervisor contract](sermon-production-supervisor-agent.md) | Local evidence still controls state |
| Turn an English video into Chinese audio and a Tongxing page | [Dubbing runbook (Chinese)](../experiments/sermon-dubbing-poc/SATURDAY_AUDIO_RUNBOOK.zh.md) → [system design](sermon-dubbing-system-design.zh.md) | Current weekly-content path |
| Review CUV quotations and spoken Chinese | [CUV production contract](sermon-cuv-production.zh.md) → [fixed Scripture library](cuv-scripture-library.zh.md) | Translation, captions, and TTS share the locked text |
| Release the Tongxing page and poster | [Weekly release contract](tongxing-weekly-release.zh.md) | Publication, HTTP verification, app acceptance, and poster QA stay separate |
| Prepare Sunday live captions | [Agent entry](sunday-live-agent-runbook.zh.md) → [operations whitepaper](sunday-live-operations-whitepaper.zh.md) | Prepare mode does not start recording |
| Change the local live-caption runtime | [POC README](../experiments/local-live-poc/README.md) → [directory instructions](../experiments/local-live-poc/AGENTS.md) | Code, replay, and venue acceptance are separate |
| Change the Tongxing iOS client | [iOS README (Chinese)](../apps/tongxing-ios/README.zh.md) → [directory instructions](../apps/tongxing-ios/AGENTS.md) | Integrated on `main`; a build is not physical-device or TestFlight acceptance |

## Maintained production contracts

- Four-layer multilingual production: [canonical interfaces (Chinese)](multilingual-production-interfaces.zh.md). This is the required naming, package, and invalidation contract for future prepared releases.
- Source, text, and PDFs: [stable dual-PDF workflow](stable-post-live-reading-pdf-workflow.md), [reading quality](chinese-reading-edition-quality.zh.md), [series terminology](series-terminology.zh.md), [MFA](mfa-production.zh.md), and [bilingual transcript display](bilingual-transcript-display.zh.md).
- Orchestration and evidence: [end-to-end Agents extension](agents-end-to-end-workflow.zh.md), [Saturday harness](saturday-harness.zh.md), [execution protection](sermon-execution-harness.zh.md), [bounded parallelism](parallel-production.zh.md), [dubbing/PDF join contract](parallel-dubbing-contract.zh.md), [quality harness](saturday-quality-harness.zh.md), [accounting](workflow-accounting.zh.md), [trace export](sermon-trace-export.zh.md), and [Temporal](sermon-temporal.zh.md).
- Tongxing content and clients: [dubbing system](sermon-dubbing-system-design.zh.md), [sound alignment](sermon-app-field-alignment.zh.md), [field listening](sermon-app-field-listening.zh.md), [feedback](sermon-listening-feedback.zh.md), [usage](sermon-app-usage.zh.md), [WeChat playback](sermon-app-wechat-playback.zh.md), [brand](sermon-app-brand.zh.md), and [series backfill](sermon-series-backfill.zh.md).
- Safety and public repository: [open-source readiness](open-source-readiness.md) and [Scripture source](scripture-source.md).
- Visual assets: [diagram inventory and regeneration](diagrams/README.md) and [PDF example provenance](assets/pdf-examples/README.md).

## Dated implementation and acceptance records

These preserve observed values and evidence boundaries; they do not track later code automatically:

- [September 20 production record (Chinese)](production-2026-09-20.zh.md) and [CUV retrospective](cuv-retrospective-2026-09-20.zh.md).
- [September 11 Agents API cutover](agents-api-production-cutover-20260911.zh.md) and [September 12 prompt/agent/skill audit](prompt-agent-skill-audit-fixes-20260912.zh.md).
- [September 5 Saturday development check](saturday-development-progress-2026-09-05.zh.md), [full validation](saturday-full-validation-2026-09-05.zh.md), and [dubbing candidate record](sermon-dubbing-astra-review-2026-09-05.zh.md).
- [July 31 reading-PDF production audit](gpt-transcribe-reading-pdf-production-audit-2026-07-31.zh.md).
- `reports/` contains machine-readable sanitized accounting and smoke receipts.

## Research, history, and superseded material

These files are retained for provenance and research, not as operator entrypoints:

- Superseded plans: [speaker-voice plan](saturday-to-sunday-chinese-voice-plan.zh.md) and [Context Pack design/implementation record](saturday-to-sunday-context-pack-plan.zh.md).
- Historical cloud architecture: [system design](system-design.md), [gap analysis](system-design-gap-analysis.md), [Cloud Run deployment prep](cloud-run-deployment-prep.md), [old Sunday cloud runbook](sunday-live-test-runbook.md), [cloud observability](observability.md), and [admin workflow](admin-workflow.md).
- Historical publication and offline implementation: [July 5 publication retrospective](post-live-reviewed-sunday-publication.zh.md) and [old offline subtitle notes](weekly-offline-subtitle-generation.zh.md).
- Early research: [findings](findings-report.md), [source feasibility](youtube-sermon-subtitle-pipeline-analysis.zh-en.md), [archive timing evidence](offline-live-archive-timing-feasibility.zh.md), and [provider comparison](model-provider-comparison.md).
- Benchmark and training Discovery: [live translation](live-sermon-translation-benchmark.zh.md), [local ASR](local-asr-benchmark.zh.md), [MacBook translation](macbook-sermon-translation-benchmark.zh.md), and [MiLMMT post-training](milmmt-sermon-post-training-plan.zh.md).
- Old project records: [backlog](backlog.md), [development notes](development-notes.md), and [review/test notes](review-testing.md).

Chinese and English historical counterparts remain beside one another for provenance. They are not independent current sources of truth.

## Maintenance rules

1. Put current behavior in the workflow overview, a task runbook, or an interface contract; put one run's values in a dated report.
2. When implementation supersedes a plan, add a banner naming the replacement instead of leaving “to be implemented” as current status.
3. Re-verify models, prices, cloud resources, and deployment state from primary evidence before using them.
4. Keep bilingual operator contracts synchronized. When Chinese is the sole source of truth, link it directly instead of creating a drifting English summary.
5. Report documentation, tests, deployment, listening review, device acceptance, and venue synchronization as separate states.
