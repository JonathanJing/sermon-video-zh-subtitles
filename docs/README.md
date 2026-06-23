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
| System design | [system-design.md](./system-design.md) | [system-design.zh.md](./system-design.zh.md) |
| Findings report | [findings-report.md](./findings-report.md) | [findings-report.zh.md](./findings-report.zh.md) |
| Model/provider comparison | [model-provider-comparison.md](./model-provider-comparison.md) | [model-provider-comparison.zh.md](./model-provider-comparison.zh.md) |
| Cloud Run deployment prep | [cloud-run-deployment-prep.md](./cloud-run-deployment-prep.md) | [cloud-run-deployment-prep.zh.md](./cloud-run-deployment-prep.zh.md) |
| Sunday live test runbook | [sunday-live-test-runbook.md](./sunday-live-test-runbook.md) | [sunday-live-test-runbook.zh.md](./sunday-live-test-runbook.zh.md) |
| YouTube source analysis | [youtube-sermon-subtitle-pipeline-analysis.zh-en.md](./youtube-sermon-subtitle-pipeline-analysis.zh-en.md) | same bilingual document |
| Development backlog | [backlog.md](./backlog.md) | [backlog.zh.md](./backlog.zh.md) |
| Development notes | [development-notes.md](./development-notes.md) | English-first content in same file |
| Review and testing notes | [review-testing.md](./review-testing.md) | English-first content in same file |

## Reading Order

1. Start with the root [README](../README.md) for the product goal and POC commands.
2. Read [system-design.md](./system-design.md) for the 11:30 congregation caption architecture.
3. Read [findings-report.md](./findings-report.md) to understand why public VOD is not enough.
4. Use [model-provider-comparison.md](./model-provider-comparison.md), [cloud-run-deployment-prep.md](./cloud-run-deployment-prep.md), and [sunday-live-test-runbook.md](./sunday-live-test-runbook.md) before provider, Cloud Run, or live-test work.
5. Use [backlog.md](./backlog.md) and [review-testing.md](./review-testing.md) to pick and verify implementation work.

## Current Documentation Language

The repository entrypoint is English by default for open-source readability. Chinese documents live beside their English counterparts with `.zh.md` filenames. If a document materially changes product behavior, deployment behavior, or the 11:30 congregation goal, update both language versions.
