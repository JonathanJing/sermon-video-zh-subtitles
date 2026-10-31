# 项目流程图 / Diagram Assets

## 当前图稿：SVG 预览与 Mermaid 拓扑

[英文技术导览](../project-technical-overview.md)与[中英后端设计](../backend-workflow-system-design.zh-en.md)各包含四层业务 DAG 和计划中的有界修订 DAG；[App 系统图](../app-system-design.zh.md)与[执行环境图](../execution-environment-design.zh.md)补充另两个设计面。默认展示原生 SVG，Markdown 折叠区保留可复制的 Mermaid 拓扑源。GitHub rich Mermaid 预览曾返回无法渲染，因此静态图不依赖该服务。

六张架构图沿用现有 `diagram-specs.json` 与 `render_diagrams.py`。节点 ID、边与英/双语源对应；strict D1–D5 代码已在 `text/strict/*`，且有[显式受控入口](../rqc-explicit-pipeline-entry.zh.md)，默认 canonical dispatcher 尚未切换，真实校准 / A-B 仍待证据。修订 DAG 保留 PLANNED，表示默认生产集成与验证仍待完成，人工批准独立。渲染命令、文件映射与校验见[架构 SVG 再生成](architecture-rendering.md)。`tools/development/docs_change_gate.py` 可在 spec 改变时重建全组并比较；修改 renderer 后也须显式执行再生成比较。检查命令和远端 CI 是否启用分别核实，不以 workflow 文件存在推断 required checks 生效；另外核查无环、L3 必经、locale 隔离、实际字号、箭头与文字边界。

2026-10-22 按代码与审核校准 9 张 SVG（含英文、双语两张修订 DAG）：Layer 1 机器裁判为 Sol / 可选 Opus；Layer 2 默认 DeepSeek Flash low / high，Sol、Opus 显式回退；双 PDF 默认 `gpt-6.1-sol high`；Supervisor 默认 Codex CLI / `gpt-6-luna medium fast`；预制本地模型计算默认 Spark、MacBook fallback。模型依据[运行时策略](../production-model-runtime-policy.zh.md)，算力依据[计算策略](../local-production-compute-policy.zh.md)。DeepSeek 尚无 canonical 真实运行证据，算力策略也不表示所有 producer 均有自动跨机回退。9/20 的已验记录保留原模型、设备与日期，不重标为当前运行。

以下保留既有 SVG 的来源、时间和再生成说明。


本组包含 2026-09-11 校准的 11 张流程图、2026-09-20 新增的四层生产主图，以及 2026-09-25 新增的 Firebase 发布边界图。2026-09-25 对两个根 README 引用的 8 张图统一重新设计为原生 SVG：白色阶段卡片、角色色条、明确的主路径与条件箭头，以及单独的审核门槛。图中的文字和连接仍来自校准后的项目图稿；本轮没有调用 ImageGen。SVG 没有嵌入 PNG、外链字体或脚本。

图面更新时间不等于所有路径的最新实测日期。Supervisor 默认 Codex CLI，Agents API 仅恢复历史原会话；调度安装与每次实际运行分别留证。周日实时字幕仍以既有浏览器回放等证据为限，人工语义、真实现场、实体手机与资源上限分别验收。配音候选、人工听审、现场同步与正式发布各自保留边界。历史云端图继续标为 Historical / Discovery；旧 timeline Cloud Run Job 已退役。

| Asset | Purpose | Primary documents |
|---|---|---|
| [four-layer-production-workflow.svg](four-layer-production-workflow.svg) | Canonical Layer 1–4 flow with each layer's input, process, models/tools, output and gate | project technical overviews, workflow map and bilingual HTML guide |
| [firebase-release-flow.svg](firebase-release-flow.svg) | Separate content approval, Dev preview, Git promotion, Production deployment and device/venue acceptance | project technical overviews, branch policy and Firebase release backlog |
| [project-map.svg](project-map.svg) | Documents, reviewed audio and live captions with shared evidence and Discovery boundaries | project technical overviews |
| [solution-journey.svg](solution-journey.svg) | Observed bottlenecks, rejected assumption, current hybrid, and gated future enhancement | project technical overviews |
| [saturday-chinese-voice-workflow.svg](saturday-chinese-voice-workflow.svg) | Featured parallel source routes, speaker training, Chinese audio review and Sunday playback gates | project technical overviews, dubbing system design and runbook |
| [saturday-post-live-workflow.svg](saturday-post-live-workflow.svg) | gpt-6.1-sol high dual-PDF profile, QA, automatic export and separate readiness gates | workflow and stable post-live docs |
| [sunday-live-workflow.svg](sunday-live-workflow.svg) | Detailed Sunday live path and visible degradation branches | workflow and POC docs |
| [saturday-to-sunday-context-pack-flow.svg](saturday-to-sunday-context-pack-flow.svg) | Separate message/content approval, capability ceiling and live-English source of truth | Context Pack plan and POC docs |
| [local-live-architecture.svg](local-live-architecture.svg) | Gateway-owned default runtime, isolated v4.1 experiment, recovery and bounded publishing | POC design and streaming docs |
| [live-runtime-sequence.svg](live-runtime-sequence.svg) | Gateway-mediated capture/model/render events; latest-connection drain before finalize | workflow and streaming docs |
| [supervisor-control-plane.svg](supervisor-control-plane.svg) | Codex CLI session, local tools, minimal outbound state, human approval and recovery gates; Agents API legacy recovery | Supervisor docs |
| [evidence-promotion-gates.svg](evidence-promotion-gates.svg) | Difference between smoke, reviewed reference, Gold, soak, venue, and promotion | benchmark docs |
| [historical-cloud-architecture.svg](historical-cloud-architecture.svg) | Explicitly historical Cloud/Discovery architecture | historical system-design docs |
| [tongxing-system-architecture.svg](tongxing-system-architecture.svg) | System overview: local four-layer production, review receipts, guarded publishing, Firebase Hosting and the Web/iOS clients | root READMEs, four-layer interface contract |
| [sentence-first-weekly-workflow.svg](sentence-first-weekly-workflow.svg) | Sentence-first agent-direct dubbing: human gates, local scripts, Spark exclusive session and publication | root READMEs, sentence-first runbook |

这两张图由 [Archify](https://github.com/tt-a1i/archify) 生成，视觉语言与手绘 SVG 不同（角色色圆角节点、细体标签、点阵画布），事实仍以仓库代码与合同为准。可复制的 spec 与再生成命令见 [Archify 源与再生成](archify-sources.md)。提交的是清理后的静态 SVG：无脚本、无内嵌字体、无外链；交互版 HTML（明暗主题、缩放、透视、来源面板）不进入仓库——文档门禁只接受根 README、`docs/` 下的 Markdown／SVG／图片，需要交互版时按该文件的命令在本地生成。


## 设计与维护

- 简体中文为主，保留必要英文模型/契约名；使用统一的浅色画布、节点、箭头与边界说明。
- 实线表示当前主路径，虚线表示条件、可选、实验或历史关系；状态同时用文字标明，不只靠颜色。
- 保留 `viewBox`、无障碍 `<title>` / `<desc>`、可选择文字和原生向量路径。
- 图稿不能自动证明上线、人工 Gold 或现场通过；模型生成稿中的日期、节点和连接须依据下列源文件校正。
- 不放凭据、私人 URL、本机用户路径或生成的证道原文。提交与 push 遵循仓库 `AGENTS.md`；内容部署须在已授权范围内执行。

## 可复现来源

历史部分的 `diagram-specs.json` 保存原有 12 张图的节点、文案与连接坐标；加上本次 6 张架构图共 18 个 spec，`render_diagrams.py` 连同独立 Firebase 图生成 19 张 SVG。`readme_diagram_renderer.py` 为迁入技术导览的 7 张历史 README 图提供新版样式，并生成 Firebase 发布边界图；其余 5 张继续使用原有渲染器：

```bash
python3 docs/diagrams/render_diagrams.py \
  --spec docs/diagrams/diagram-specs.json \
  --out-dir docs/diagrams
```

`firebase-release-flow.svg` 的发布边界文案与布局写在 `readme_diagram_renderer.py` 的 `render_firebase_release()`，由同一命令重建。修改发布状态时须与根 README 和 release 记录核对，再完成浏览器目视检查。

2026-09-25 曾记录两段三语 Dev 片段及旧九周中文正式站，这是历史快照。当前发布图按[四层合同中的 9/27 正式发布记录](../multilingual-production-interfaces.zh.md)与[10/11 三语页面复核](../reports/20261011-weekly-release-resi-54475d42-retrospective.zh.md)校准为“9/27 起已有三语正式内容，逐周证据另记”；其余未发布内容语言仍禁用。Dev 候选、代码晋升、正式发布、设备与现场验收继续分开。发布流程依据[分支与环境策略](../development-branch-and-firebase-environments.zh.md)，不以本轮图稿更新代替线上复验。

`imagegen-prompts.jsonl` 保存 2026-09-11 的 11 份历史 CLI 提示，显式指定 `gpt-image-2.5-sunburst`、high、1536×1024。四层图的历史 ImageGen 参考见[四层更新记录](refresh-four-layer-20260920.md)。从 README 迁出的技术导览图由 SVG 代码直接绘制；流程事实仍以图稿和源文档为准。

## 内容依据与验证

历史图表以各自 `calibratedAt` 为准；2026-10-22 校准仅覆盖上文 9 张图的职责、默认值与状态文字，不表示重新执行了模型、部署、设备或现场验证。

- [完整工作流](../workflows/README.zh.md)
- [生产 runbook](../codex-local-production-runbook.zh.md) 与 [Supervisor 契约](../sermon-production-supervisor-agent.zh.md)
- [周六至周日配音计划](../saturday-to-sunday-chinese-voice-plan.zh.md)
- [本地字幕 POC](../../experiments/local-live-poc/README.md) 与 [v4.1 本机实验](../../experiments/local-live-poc/MILMMT_V41_LOCAL.zh.md)
- [Context Pack 契约](../saturday-to-sunday-context-pack-plan.zh.md)

每次修改须通过 XML、文档链接、`git diff --check`，并在浏览器中完整渲染，检查文字画布/卡片越界与连线。文档修改不重新运行模型生产、完整后端测试或现场实验。

## 2026-09-20 既有两图局部更新

该次局部更新只改 `project-map.svg` 与 `saturday-chinese-voice-workflow.svg`，其余九图保持原记录。原生源为 `diagram-specs.json`，继续由 `render_diagrams.py` 生成；两图显式记录 `calibratedAt`，未设置该字段的历史图保留 2026-09-11 日期。该次局部修改没有重新调用 ImageGen；后来新增的四层主图另见上方记录。

依据[9 月 20 日制作记录](../production-2026-09-20.zh.md)与[每周海报交付](../tongxing-weekly-release.zh.md#每周海报交付)，该次两图记录了 MacBook 本地 TTS、当周用户听审与 Firebase／iOS 验收、尚未证实的现场同步，以及发布 HTTP 核验后默认制作海报的真实二维码和图像 QA。2026-10-22 校准后，当前预制模型计算标为 Spark 默认 / MacBook fallback，9/20 的 MacBook 与 Astra job 保留为历史记录。图中 Codex 图像步骤不表示定时 Supervisor 已调用 ImageGen。

验证：两张原生 SVG 通过 XML 解析，并在 Chrome 本地页面完整渲染、分段目视检查全部节点与连接；中文可读、卡片无文字越界，新海报分支与现场路径分开。源文件与渲染结果保持可复现。文档链接和差异空白另随提交检查；没有重跑模型生产或现场实验。
