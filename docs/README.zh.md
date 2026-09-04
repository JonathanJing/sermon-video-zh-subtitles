# 文档索引

<p>
  <a href="./README.md">
    <img src="https://img.shields.io/badge/Language-English-blue" alt="English Documentation" />
  </a>
</p>

这里收集证道中文字幕 pipeline 的产品目标、系统设计、研究报告、backlog 和测试审查文档。

## 核心文档

| 主题 | English | 中文 |
|---|---|---|
| 两条主工作流与本地延迟预算 | [中文 source of truth](./workflows/README.zh.md) | [workflows/README.zh.md](./workflows/README.zh.md) |
| 周日公网手机字幕分享方案 | 暂无独立英文版 | [PUBLIC_SHARING.zh.md](../experiments/local-live-poc/PUBLIC_SHARING.zh.md) |
| 稳定主流程 | [stable-post-live-reading-pdf-workflow.md](./stable-post-live-reading-pdf-workflow.md) | [stable-post-live-reading-pdf-workflow.zh.md](./stable-post-live-reading-pdf-workflow.zh.md) |
| Production Supervisor Agent | [sermon-production-supervisor-agent.md](./sermon-production-supervisor-agent.md) | [sermon-production-supervisor-agent.zh.md](./sermon-production-supervisor-agent.zh.md) |
| `gpt-transcribe` 阅读版生产审核（2026-07-31） | [gpt-transcribe-reading-pdf-production-audit-2026-07-31.zh.md](./gpt-transcribe-reading-pdf-production-audit-2026-07-31.zh.md) | 同一份中文文档 |
| System Design | [system-design.md](./system-design.md) | [system-design.zh.md](./system-design.zh.md) |
| System Design 实现差距审计 | [system-design-gap-analysis.md](./system-design-gap-analysis.md) | [system-design-gap-analysis.zh.md](./system-design-gap-analysis.zh.md) |
| Findings Report | [findings-report.md](./findings-report.md) | [findings-report.zh.md](./findings-report.zh.md) |
| 模型/Provider 比较 | [model-provider-comparison.md](./model-provider-comparison.md) | [model-provider-comparison.zh.md](./model-provider-comparison.zh.md) |
| 证道实时翻译 Benchmark / A-B Test | 暂无独立英文版 | [live-sermon-translation-benchmark.zh.md](./live-sermon-translation-benchmark.zh.md) |
| MacBook Pro M1 Max 64 GB 主硬件 Profile | 暂无独立英文版 | [macbook-m1-max-64gb-profile.json](../data/benchmarks/live-sermon-translation-v1/macbook-m1-max-64gb-profile.json) |
| MacBook Ollama / MLX 翻译 Benchmark V1 | 暂无独立英文版 | [macbook-sermon-translation-benchmark.zh.md](./macbook-sermon-translation-benchmark.zh.md) |
| MacBook 本地英文 ASR Benchmark V1 | 暂无独立英文版 | [local-asr-benchmark.zh.md](./local-asr-benchmark.zh.md) |
| MacBook Translation-only 主榜（2026-09-03） | 暂无独立英文版 | [translation-only-leaderboard-20260903.md](../data/benchmarks/live-sermon-translation-v1/runs/macbook-text-baselines/translation-only-leaderboard-20260903.md) |
| Hy-MT2-1.8B MacBook Ollama Benchmark | 暂无独立英文版 | [report.md](../data/benchmarks/live-sermon-translation-v1/runs/macbook-text-baselines/hymt2-1.8b-q8-ollama-full-20260903/report.md) |
| MiLMMT-46-4B-v1.0 MacBook Ollama Benchmark | 暂无独立英文版 | [report.md](../data/benchmarks/live-sermon-translation-v1/runs/macbook-text-baselines/milmmt-46-4b-v1-q8-ollama-full-20260903/report.md) |
| MiLMMT-46-4B MacBook 运行时选择与后训练计划 | 暂无独立英文版 | [milmmt-sermon-post-training-plan.zh.md](./milmmt-sermon-post-training-plan.zh.md) |
| Qwen3.5-4B-Base BF16 MacBook Ollama Benchmark | 暂无独立英文版 | [report.md](../data/benchmarks/live-sermon-translation-v1/runs/macbook-text-baselines/qwen35-4b-base-bf16-ollama-full-20260903/report.md) |
| Qwen3.5-9B-Base BF16 MacBook Ollama Benchmark | 暂无独立英文版 | [report.md](../data/benchmarks/live-sermon-translation-v1/runs/macbook-text-baselines/qwen35-9b-base-bf16-ollama-full-20260903/report.md) |
| A0 Base 模型 Baseline（生成与速度） | 暂无独立英文版 | [baseline-report.md](../data/benchmarks/live-sermon-translation-v1/runs/a0-baseline/baseline-report.md) |
| Hy-MT2-1.8B DGX Spark Benchmark | 暂无独立英文版 | [report.md](../data/benchmarks/live-sermon-translation-v1/runs/external-baselines/hymt2-1.8b-q8-chinese-full-20260903/report.md) |
| Hy-MT2-30B-A3B Heretic DGX Spark Benchmark | 暂无独立英文版 | [report.md](../data/benchmarks/live-sermon-translation-v1/runs/external-baselines/hymt2-30b-a3b-heretic-q8-full-20260903/report.md) |
| Cloud Run 部署准备 | [cloud-run-deployment-prep.md](./cloud-run-deployment-prep.md) | [cloud-run-deployment-prep.zh.md](./cloud-run-deployment-prep.zh.md) |
| Admin 工作流 | [admin-workflow.md](./admin-workflow.md) | [admin-workflow.zh.md](./admin-workflow.zh.md) |
| Post-live reviewed Sunday 发布路径 | [post-live-reviewed-sunday-publication.zh.md](./post-live-reviewed-sunday-publication.zh.md) | 同一份中文文档 |
| 中文圣经来源 | [scripture-source.md](./scripture-source.md) | [scripture-source.zh.md](./scripture-source.zh.md) |
| 观测与日志 | [observability.md](./observability.md) | [observability.zh.md](./observability.zh.md) |
| 开源准备检查 | [open-source-readiness.md](./open-source-readiness.md) | [open-source-readiness.zh.md](./open-source-readiness.zh.md) |
| 周日 live test runbook | [sunday-live-test-runbook.md](./sunday-live-test-runbook.md) | [sunday-live-test-runbook.zh.md](./sunday-live-test-runbook.zh.md) |
| 每周离线字幕文件生成流程 | [weekly-offline-subtitle-generation.zh.md](./weekly-offline-subtitle-generation.zh.md) | 同一份中文文档 |
| YouTube source analysis | [youtube-sermon-subtitle-pipeline-analysis.zh-en.md](./youtube-sermon-subtitle-pipeline-analysis.zh-en.md) | 同一份中英文文档 |
| 离线直播链接时间可行性 | [offline-live-archive-timing-feasibility.zh.md](./offline-live-archive-timing-feasibility.zh.md) | 同一份中文文档 |
| 开发 Backlog | [backlog.md](./backlog.md) | [backlog.zh.md](./backlog.zh.md) |
| Development Notes | [development-notes.md](./development-notes.md) | 同文件英文优先内容 |
| Review / Testing Notes | [review-testing.md](./review-testing.md) | 同文件英文优先内容 |

## 推荐阅读顺序

1. 先读根目录 [中文版 README](../README.zh.md)，了解两条主工作流与 Discovery 边界。
2. 再读 [workflows/README.zh.md](./workflows/README.zh.md)，查看完整流程图、本地延迟预算和测试门槛。
3. 阅读 [stable-post-live-reading-pdf-workflow.zh.md](./stable-post-live-reading-pdf-workflow.zh.md)，这是当前 repo 最稳定的 operator 路径。
4. 读 [sermon-production-supervisor-agent.zh.md](./sermon-production-supervisor-agent.zh.md)，了解 Agent 控制层、人工审批契约和 Scheduler 接入。
5. 查看 [gpt-transcribe-reading-pdf-production-audit-2026-07-31.zh.md](./gpt-transcribe-reading-pdf-production-audit-2026-07-31.zh.md)，确认当前模型、质量门禁与完整 PDF 审核证据。
6. 再按需要进入其余 System Design、Discovery、部署与历史实验文档。

## 文档语言策略

repo 默认入口使用英文，便于 GitHub 浏览和开源协作；中文文档与英文文档并列存放，文件名使用 `.zh.md`。如果文档改动影响产品行为、部署行为或 11:30 会众目标，应同步更新中英文版本。
