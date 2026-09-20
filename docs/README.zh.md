# 文档导航

<p>
  <a href="./README.md">
    <img src="https://img.shields.io/badge/Language-English-blue" alt="English Documentation" />
  </a>
</p>

本页只负责路由，不重复定义流程。项目当前事实以根目录 [README](../README.zh.md)、[工作流总览](workflows/README.zh.md)、对应操作 Runbook、代码和绑定运行收据共同决定；单独一份设计稿、测试或历史报告不能升级生产状态。

状态校准：**2026-09-20，本地 `main` 546b90d**。这是代码与 tracked 证据的校准点；文档不据此声称已 push、远端部署、现场同步或实体设备验收。

## 从任务进入

| 要做的事 | 先读 | 状态边界 |
|---|---|---|
| 查看三条产品路径与完成标准 | [工作流总览](workflows/README.zh.md) | 当前总入口 |
| 周六从完整礼拜／归档生成双 PDF | [本地生产 Runbook](codex-local-production-runbook.zh.md) → [稳定双 PDF 流程](stable-post-live-reading-pdf-workflow.zh.md) | 当前 operator 路径 |
| 查看或恢复生产 Supervisor | [Supervisor 契约](sermon-production-supervisor-agent.zh.md) | Agents API 控制层；状态仍由本地证据决定 |
| 从英文视频制作中文音轨与同行页面 | [配音操作 Runbook](../experiments/sermon-dubbing-poc/SATURDAY_AUDIO_RUNBOOK.zh.md) → [系统设计](sermon-dubbing-system-design.zh.md) | 当前每周内容路径 |
| 审核 CUV 引文和口播中文 | [CUV 生产流程](sermon-cuv-production.zh.md) → [固定经文库](cuv-scripture-library.zh.md) | 翻译、字幕、TTS 共用同一锁定文本 |
| 发行同行页面和海报 | [每周发行流程](tongxing-weekly-release.zh.md) | 发布、HTTP 核验、App 验收、海报分别留证 |
| 准备周日实时字幕页面 | [Agent 执行入口](sunday-live-agent-runbook.zh.md) → [运行白皮书](sunday-live-operations-whitepaper.zh.md) | 准备模式不开始录音 |
| 修改本地实时字幕 | [POC 说明](../experiments/local-live-poc/README.md) → [POC 目录约定](../experiments/local-live-poc/AGENTS.md) | 本地代码、回放、现场验收分开 |
| 修改同行 iOS | [iOS 说明](../apps/tongxing-ios/README.zh.md) → [iOS 目录约定](../apps/tongxing-ios/AGENTS.md) | 已在 `main`；构建不等于真机／TestFlight 验收 |

## 当前生产规范

### 来源、文本与 PDF

- [稳定 post-live 双 PDF 流程](stable-post-live-reading-pdf-workflow.zh.md)及[英文版](stable-post-live-reading-pdf-workflow.md)
- [中文阅读版质量规范](chinese-reading-edition-quality.zh.md)
- [系列名称表](series-terminology.zh.md)：页面、字幕、阅读稿、大纲和配音共用术语
- [MFA 阅读稿对齐](mfa-production.zh.md)
- [双语全文显示](bilingual-transcript-display.zh.md)

### 编排、并发与证据

- [Agents API 端到端扩展](agents-end-to-end-workflow.zh.md)：显式配置才接入页面发行
- [周六统一入口](saturday-harness.zh.md)与[执行保护](sermon-execution-harness.zh.md)
- [受限并发](parallel-production.zh.md)与[配音／PDF 汇合合同](parallel-dubbing-contract.zh.md)
- [质量回归 Harness](saturday-quality-harness.zh.md)
- [流程记账](workflow-accounting.zh.md)、[Trace 导出](sermon-trace-export.zh.md)与[Temporal 编排](sermon-temporal.zh.md)

### 同行页面、音频与客户端

- [配音系统设计](sermon-dubbing-system-design.zh.md)
- [听音定位](sermon-app-field-alignment.zh.md)、[现场收听与恢复](sermon-app-field-listening.zh.md)
- [反馈](sermon-listening-feedback.zh.md)、[匿名使用摘要](sermon-app-usage.zh.md)、[微信播放](sermon-app-wechat-playback.zh.md)
- [品牌](sermon-app-brand.zh.md)与[系列补档](sermon-series-backfill.zh.md)

### 安全与公开仓库

- [开源准备检查](open-source-readiness.zh.md)及[英文版](open-source-readiness.md)
- [中文圣经来源说明](scripture-source.zh.md)及[英文版](scripture-source.md)
- [流程图清单与再生成方式](diagrams/README.md)；[PDF 示例来源](assets/pdf-examples/README.md)

## 带日期的实施与验收记录

这些文件保留观察值和证据边界，不随当前代码自动更新：

- [2026-09-20《耶稣的应许》制作记录](production-2026-09-20.zh.md)
- [2026-09-20 CUV 引用核验复盘](cuv-retrospective-2026-09-20.zh.md)
- [2026-09-11 Agents API 切换记录](agents-api-production-cutover-20260911.zh.md)
- [2026-09-12 Prompt／Agent／Skill 审计修复](prompt-agent-skill-audit-fixes-20260912.zh.md)
- [2026-09-05 周六流程开发核验](saturday-development-progress-2026-09-05.zh.md)、[完整验证](saturday-full-validation-2026-09-05.zh.md)、[配音候选记录](sermon-dubbing-astra-review-2026-09-05.zh.md)
- [2026-07-31 阅读版 PDF 生产审核](gpt-transcribe-reading-pdf-production-audit-2026-07-31.zh.md)
- `reports/`：机器可读的脱敏计量与 smoke 收据

## 研究、历史和被取代的文档

以下资料不再作为 operator 入口。使用时必须回到上面的当前规范重新核对。

| 类别 | 文档 |
|---|---|
| 已由实现与 Runbook 取代的方案 | [原讲员音色方案草案](saturday-to-sunday-chinese-voice-plan.zh.md)、[Context Pack 设计与实施记录](saturday-to-sunday-context-pack-plan.zh.md) |
| 历史 Cloud 架构／部署 | [System Design](system-design.zh.md)、[差距审计](system-design-gap-analysis.zh.md)、[Cloud Run 部署准备](cloud-run-deployment-prep.zh.md)、[旧周日 Cloud Runbook](sunday-live-test-runbook.zh.md)、[旧 Cloud 观测](observability.zh.md)、[Admin 路径](admin-workflow.zh.md) |
| 历史发布／离线实现 | [2026-07-05 页面发布复盘](post-live-reviewed-sunday-publication.zh.md)、[旧离线字幕实现笔记](weekly-offline-subtitle-generation.zh.md) |
| 早期调研 | [发现报告](findings-report.zh.md)、[公开视频可行性分析](youtube-sermon-subtitle-pipeline-analysis.zh-en.md)、[直播归档时间证据](offline-live-archive-timing-feasibility.zh.md)、[Provider 对比](model-provider-comparison.zh.md) |
| Benchmark／训练 Discovery | [实时翻译 Benchmark](live-sermon-translation-benchmark.zh.md)、[本地 ASR](local-asr-benchmark.zh.md)、[MacBook 翻译](macbook-sermon-translation-benchmark.zh.md)、[MiLMMT 后训练计划](milmmt-sermon-post-training-plan.zh.md) |
| 旧项目记录 | [Backlog](backlog.zh.md)、[Development Notes](development-notes.md)、[Review/Test Notes](review-testing.md) |

对应英文历史稿仍保留在同目录，用于来源追踪和开源阅读；它们不是另一套独立事实来源。

## 文档维护规则

1. 当前行为只写进工作流总览、任务 Runbook 或接口合同；一次运行的数据写进带日期的报告。
2. 已完成方案不再继续写“待实现”：在文件顶部标明被哪个实现／Runbook 取代，并保留原设计作为历史。
3. 模型、价格、云资源和部署状态容易变化；没有当次一手核验时只描述为历史观察。
4. 中英双份操作合同必须同步；只有中文 source of truth 的文档在英文索引中直接链接中文文件，不复制一份会漂移的摘要。
5. 文档、测试、部署、人工听审、设备验收和现场同步分别报告，不互相代替。
