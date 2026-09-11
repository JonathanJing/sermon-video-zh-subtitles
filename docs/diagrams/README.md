# 项目流程图 / Diagram Assets

本组 11 张流程图按 2026-09-11 的项目设计与切换记录重新校准，以 **GPT Image 2.5 Sunburst** 图稿为视觉参考，再重建为原生、可编辑 SVG。中文和连接关系经过本地校正；SVG 没有嵌入 PNG、外链字体或脚本。

图面更新时间不等于所有路径的最新实测日期。Agents API 控制层与每周调度已安装；周日实时字幕仍以既有浏览器回放等证据为限，人工语义、真实现场、实体手机与资源上限分别验收。配音候选、人工听审、现场同步与正式发布各自保留边界。历史云端图继续标为 Historical / Discovery；旧 timeline Cloud Run Job 已退役。

| Asset | Purpose | Primary documents |
|---|---|---|
| [project-map.svg](project-map.svg) | Documents, reviewed audio and live captions with shared evidence and Discovery boundaries | root READMEs |
| [solution-journey.svg](solution-journey.svg) | Observed bottlenecks, rejected assumption, current hybrid, and gated future enhancement | root READMEs |
| [saturday-chinese-voice-workflow.svg](saturday-chinese-voice-workflow.svg) | Featured parallel source routes, speaker training, Chinese audio review and Sunday playback gates | root READMEs, dubbing system design and runbook |
| [saturday-post-live-workflow.svg](saturday-post-live-workflow.svg) | Astra Medium weekly profile, dual-PDF QA, automatic export and separate readiness gates | workflow and stable post-live docs |
| [sunday-live-workflow.svg](sunday-live-workflow.svg) | Detailed Sunday live path and visible degradation branches | workflow and POC docs |
| [saturday-to-sunday-context-pack-flow.svg](saturday-to-sunday-context-pack-flow.svg) | Separate message/content approval, capability ceiling and live-English source of truth | Context Pack plan and POC docs |
| [local-live-architecture.svg](local-live-architecture.svg) | Gateway-owned default runtime, isolated v4.1 experiment, recovery and bounded publishing | POC design and streaming docs |
| [live-runtime-sequence.svg](live-runtime-sequence.svg) | Gateway-mediated capture/model/render events; latest-connection drain before finalize | workflow and streaming docs |
| [supervisor-control-plane.svg](supervisor-control-plane.svg) | Agents API session, local tools, minimal outbound state, human approval and recovery gates | Supervisor docs |
| [evidence-promotion-gates.svg](evidence-promotion-gates.svg) | Difference between smoke, reviewed reference, Gold, soak, venue, and promotion | benchmark docs |
| [historical-cloud-architecture.svg](historical-cloud-architecture.svg) | Explicitly historical Cloud/Discovery architecture | historical system-design docs |


## 设计与维护

- 简体中文为主，保留必要英文模型/契约名；使用统一的浅色画布、节点、箭头与边界说明。
- 实线表示当前主路径，虚线表示条件、可选、实验或历史关系；状态同时用文字标明，不只靠颜色。
- 保留 `viewBox`、无障碍 `<title>` / `<desc>`、可选择文字和原生向量路径。
- 图稿不能自动证明上线、人工 Gold 或现场通过；模型生成稿中的日期、节点和连接须依据下列源文件校正。
- 不放凭据、私人 URL、本机用户路径或生成的证道原文。没有用户要求时不提交、push 或发布。

## 可复现来源

`diagram-specs.json` 保存节点、文案与连接坐标；`render_diagrams.py` 生成所有 SVG：

```bash
python3 docs/diagrams/render_diagrams.py \
  --spec docs/diagrams/diagram-specs.json \
  --out-dir docs/diagrams
```

`imagegen-prompts.jsonl` 保存这次发送的 11 份提示，显式指定 `gpt-image-2.5-sunburst`、high、1536×1024。生成使用 imagegen 技能自带 CLI；没有修改该 CLI 或换用其他图像模型。图像稿仅用于设计参考，最终流程事实以向量图和源文档为准。原始 PNG、调用日志、替换前备份及逐图视觉检查保存在项目 ignored 产物目录，见[本次验证记录](refresh-20260911.md)。

## 内容依据与验证

图表描述 2026-09-11 的本地工作区与部署记录；本次图表提交未一并提交其他进行中的实现改动，因此图面不代表同一 Git 版本已包含全部控制层实现。

- [完整工作流](../workflows/README.zh.md)
- [生产 runbook](../codex-local-production-runbook.zh.md) 与 [Supervisor 契约](../sermon-production-supervisor-agent.zh.md)
- [周六至周日配音计划](../saturday-to-sunday-chinese-voice-plan.zh.md)
- [本地字幕 POC](../../experiments/local-live-poc/README.md) 与 [v4.1 本机实验](../../experiments/local-live-poc/MILMMT_V41_LOCAL.zh.md)
- [Context Pack 契约](../saturday-to-sunday-context-pack-plan.zh.md)

每次修改须通过 XML、文档链接、`git diff --check`，并在浏览器中完整渲染，检查文字画布/卡片越界与连线。文档修改不重新运行模型生产、完整后端测试或现场实验。
