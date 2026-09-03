# Documentation

<p>
  <a href="./README.zh.md">
    <img src="https://img.shields.io/badge/Language-中文文档-blue" alt="中文文档索引" />
  </a>
</p>

This folder contains product, system design, research, backlog, and testing notes for the sermon Chinese caption pipeline.

## Core Documents

| Topic | English | Chinese |
|---|---|---|
| Two working workflows and local latency budget | [Chinese source of truth](./workflows/README.zh.md) | [workflows/README.zh.md](./workflows/README.zh.md) |
| Stable workflow | [stable-post-live-reading-pdf-workflow.md](./stable-post-live-reading-pdf-workflow.md) | [stable-post-live-reading-pdf-workflow.zh.md](./stable-post-live-reading-pdf-workflow.zh.md) |
| Production Supervisor Agent | [sermon-production-supervisor-agent.md](./sermon-production-supervisor-agent.md) | [sermon-production-supervisor-agent.zh.md](./sermon-production-supervisor-agent.zh.md) |
| System design | [system-design.md](./system-design.md) | [system-design.zh.md](./system-design.zh.md) |
| System design gap analysis | [system-design-gap-analysis.md](./system-design-gap-analysis.md) | [system-design-gap-analysis.zh.md](./system-design-gap-analysis.zh.md) |
| Findings report | [findings-report.md](./findings-report.md) | [findings-report.zh.md](./findings-report.zh.md) |
| Model/provider comparison | [model-provider-comparison.md](./model-provider-comparison.md) | [model-provider-comparison.zh.md](./model-provider-comparison.zh.md) |
| Cloud Run deployment prep | [cloud-run-deployment-prep.md](./cloud-run-deployment-prep.md) | [cloud-run-deployment-prep.zh.md](./cloud-run-deployment-prep.zh.md) |
| Admin workflow | [admin-workflow.md](./admin-workflow.md) | [admin-workflow.zh.md](./admin-workflow.zh.md) |
| Post-live reviewed Sunday publication | [post-live-reviewed-sunday-publication.zh.md](./post-live-reviewed-sunday-publication.zh.md) | same Chinese document |
| Scripture source | [scripture-source.md](./scripture-source.md) | [scripture-source.zh.md](./scripture-source.zh.md) |
| Observability and logs | [observability.md](./observability.md) | [observability.zh.md](./observability.zh.md) |
| Open-source readiness | [open-source-readiness.md](./open-source-readiness.md) | [open-source-readiness.zh.md](./open-source-readiness.zh.md) |
| Sunday live test runbook | [sunday-live-test-runbook.md](./sunday-live-test-runbook.md) | [sunday-live-test-runbook.zh.md](./sunday-live-test-runbook.zh.md) |
| Weekly offline subtitle generation | [weekly-offline-subtitle-generation.zh.md](./weekly-offline-subtitle-generation.zh.md) | same Chinese document |
| YouTube source analysis | [youtube-sermon-subtitle-pipeline-analysis.zh-en.md](./youtube-sermon-subtitle-pipeline-analysis.zh-en.md) | same bilingual document |
| Offline live-archive timing feasibility | [offline-live-archive-timing-feasibility.zh.md](./offline-live-archive-timing-feasibility.zh.md) | same Chinese document |
| Development backlog | [backlog.md](./backlog.md) | [backlog.zh.md](./backlog.zh.md) |
| Development notes | [development-notes.md](./development-notes.md) | English-first content in same file |
| Review and testing notes | [review-testing.md](./review-testing.md) | English-first content in same file |

## Reading Order

1. Start with the root [README](../README.md) for the two working workflows and the Discovery boundary.
2. Read [workflows/README.zh.md](./workflows/README.zh.md) for the complete diagrams, local latency budget, and test gates.
3. Read [stable-post-live-reading-pdf-workflow.md](./stable-post-live-reading-pdf-workflow.md) for the repository's current stable operator path.
4. Read [sermon-production-supervisor-agent.md](./sermon-production-supervisor-agent.md) for the Agent control plane, human approval contract, and Scheduler integration.
5. Enter the remaining System Design, Discovery, deployment, and historical experiment documents only when that work is in scope.

## Current Documentation Language

The repository entrypoint is English by default for open-source readability. Chinese documents live beside their English counterparts with `.zh.md` filenames. If a document materially changes product behavior, deployment behavior, or the 11:30 congregation goal, update both language versions.
