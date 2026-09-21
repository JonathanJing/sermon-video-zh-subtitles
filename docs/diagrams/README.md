# 项目流程图 / Diagram Assets

本组包含 2026-09-11 校准的 11 张流程图，以及 2026-09-20 新增、2026-09-21 补齐模型职责和 Layer 3 音频指纹的四层生产主图。原 11 图以 **GPT Image 2.5 Sunburst** 为视觉参考；四层主图重新调用 Codex 内置 ImageGen 生成参考，再按冻结接口重建为原生、可编辑 SVG。中文和连接关系均经本地校正；SVG 没有嵌入 PNG、外链字体或脚本。

图面更新时间不等于所有路径的最新实测日期。Agents API 控制层与每周调度已安装；周日实时字幕仍以既有浏览器回放等证据为限，人工语义、真实现场、实体手机与资源上限分别验收。配音候选、人工听审、现场同步与正式发布各自保留边界。历史云端图继续标为 Historical / Discovery；旧 timeline Cloud Run Job 已退役。

| Asset | Purpose | Primary documents |
|---|---|---|
| [four-layer-production-workflow.svg](four-layer-production-workflow.svg) | Canonical Layer 1–4 flow, including Layer 3 source-bound audio fingerprint generation and Layer 4 app consumption | root READMEs, workflow map and bilingual HTML guide |
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

`imagegen-prompts.jsonl` 保存 2026-09-11 的 11 份 CLI 提示，显式指定 `gpt-image-2.5-sunburst`、high、1536×1024。新增四层图使用 Codex 内置 ImageGen，不推断其未返回的具体模型版本；提示、结果路径和重建边界见[四层更新记录](refresh-four-layer-20260920.md)。图像稿仅用于设计参考，最终流程事实以向量图和源文档为准。

## 内容依据与验证

图表描述 2026-09-11 的本地工作区与部署记录；本次图表提交未一并提交其他进行中的实现改动，因此图面不代表同一 Git 版本已包含全部控制层实现。

- [完整工作流](../workflows/README.zh.md)
- [生产 runbook](../codex-local-production-runbook.zh.md) 与 [Supervisor 契约](../sermon-production-supervisor-agent.zh.md)
- [周六至周日配音计划](../saturday-to-sunday-chinese-voice-plan.zh.md)
- [本地字幕 POC](../../experiments/local-live-poc/README.md) 与 [v4.1 本机实验](../../experiments/local-live-poc/MILMMT_V41_LOCAL.zh.md)
- [Context Pack 契约](../saturday-to-sunday-context-pack-plan.zh.md)

每次修改须通过 XML、文档链接、`git diff --check`，并在浏览器中完整渲染，检查文字画布/卡片越界与连线。文档修改不重新运行模型生产、完整后端测试或现场实验。

## 2026-09-20 既有两图局部更新

该次局部更新只改 `project-map.svg` 与 `saturday-chinese-voice-workflow.svg`，其余九图保持原记录。原生源为 `diagram-specs.json`，继续由 `render_diagrams.py` 生成；两图显式记录 `calibratedAt`，未设置该字段的历史图保留 2026-09-11 日期。该次局部修改没有重新调用 ImageGen；后来新增的四层主图另见上方记录。

依据[9 月 20 日制作记录](../production-2026-09-20.zh.md)与[每周海报交付](../tongxing-weekly-release.zh.md#每周海报交付)，两图补充 MacBook 本地 TTS 的实际路径、本周用户听审与 Firebase／iOS 验收、尚未证实的现场同步，以及发布 HTTP 核验后默认制作海报的真实二维码和图像 QA。图中 Codex 图像步骤不表示定时 Supervisor 已调用 ImageGen。

验证：两张原生 SVG 通过 XML 解析，并在 Chrome 本地页面完整渲染、分段目视检查全部节点与连接；中文可读、卡片无文字越界，新海报分支与现场路径分开。源文件与渲染结果保持可复现。文档链接和差异空白另随提交检查；没有重跑模型生产或现场实验。
