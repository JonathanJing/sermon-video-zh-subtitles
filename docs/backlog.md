# 11:30 会众中文字幕 Backlog

日期：2026-06-22

## 产品目标

北星目标：在每周日 11:30 PT 场证道开始时，中文会众可以打开一个稳定、低干扰、可阅读的中文字幕界面，帮助他们在现场听道。

Backlog 排序原则：

1. 先保证 11:30 会众能看到可用中文字幕。
2. 再降低延迟、提高经文/人名/术语准确度。
3. 最后完善离线字幕、笔记、金句和运营工具。

## 当前基线

- 已有静态 Web/PWA 原型，可展示 operator 控制台、证道标题、生成状态、字幕片段、经文 sidebar、VTT/SRT 导出。
- 已有 `prepare_live_link_playback.py`，可从 YouTube live archive link 生成播放模拟数据。
- 已有 GCS 发布参数和 Secret Manager resource name 边界，生成物可进入 GCS，API key 明文不进入 artifact。
- 当前播放模拟仍以可用字幕源为基础；如果只有英文字幕，中文行显示 `AI 中文待生成`，下一步必须接入真实翻译/生成。

## P0 - 11:30 会众可用闭环

### P0.1 接入真实中文生成链路

目标：把 `AI 中文待生成` 替换为真实可读中文字幕。

开发 owner：Fix/Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- 给定直播链接运行 POC 后，`web/playback-simulation.generated.js` 中每个可展示 segment 有非占位中文 `zh` 文本。
- 英文 sidecar 保留，可用于回查翻译来源。
- 生成失败的 segment 明确标记为 `needs_review` 或等价状态，而不是静默显示空字幕。
- API key 只通过 Secret Manager resource name 配置，不写入 report、manifest、JS、日志或字幕文件。
- 单元测试覆盖：英文输入生成中文占位替换、失败 fallback、secret 不落盘。

### P0.2 会众视图与 operator 视图分离

目标：11:30 会众看到的是干净字幕页，operator 才看到监控、按钮、日志和导出。

开发 owner：UI/Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- Web 原型至少支持 `operator` 和 `congregation` 两种 view mode。
- iPhone 竖屏会众视图默认只显示证道标题、当前中文字幕、必要经文提示和连接/生成状态。
- 会众视图不显示 `开始监控`、`生成会众字幕`、`模拟播放`、导出按钮、运行日志等 operator 控件。
- iPad 横屏 operator 视图保留监控、发布、review、经文 sidebar。
- 手动 smoke test 覆盖 iPhone 竖屏、iPhone 横屏、iPad 竖屏、iPad 横屏。

### P0.3 发布状态与 11:25 readiness gate

目标：operator 能在 11:25 前判断是否可以发布给 11:30 会众。

开发 owner：Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- UI 有明确状态：`未开始`、`正在生成`、`可发布`、`已发布`、`需要人工处理`。
- 至少基于 segment 数量、中文可用率、低置信片段数量、证道标题和开始时间存在性，计算 readiness。
- 当 readiness 不满足时，`冻结并发布` 或等价发布动作需要显示原因。
- 当 readiness 满足并发布后，会众视图显示 `已发布` 或等价状态。
- 测试覆盖 readiness pass/fail、发布后状态、缺标题/缺中文/segment 太少时的阻止逻辑。

### P0.4 GCS artifact manifest 可被 Cloud Run / Web 加载

目标：生成物上传到 GCS 后，前端或服务端可以根据 manifest 找到最新播放数据。

开发 owner：Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- `cloud-manifest.json` 包含 playback JS、report、字幕文件、生成时间、live URL、sermon title、translation status。
- 支持 dry-run 测试，不需要真实上传即可验证 manifest shape。
- 支持真实 GCS URI 的路径规范：`gs://<bucket>/runs/<date>/<session_id>/...`。
- 任何 artifact 都不包含 API key 明文。
- 测试覆盖 manifest shape、路径、secret 边界、dry-run 输出。

## P1 - 质量、延迟与现场可用性

### P1.1 翻译质量策略：经文、人名、术语优先

目标：字幕不是逐字机器翻译，而是服务听道理解。

开发 owner：Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- 支持术语表输入，至少覆盖 `Numbers`、`Moses`、`Aaron`、`Rebellion`、`Mediator`、`Intercede` 等当前证道词汇。
- 支持经文引用检测并给 segment 附上 `scripture_refs` 或等价字段。
- 术语/经文命中时，中文翻译优先使用固定译法。
- 低置信术语进入 operator review 列表。
- 测试覆盖术语固定、经文命中、低置信标记。

### P1.2 延迟指标与生成进度可观测

目标：知道字幕是否足够快，能不能跟上现场听道。

开发 owner：Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- segment 数据包含 `received_at`、`generated_at`、`published_at` 或等价时间戳。
- UI 显示最近字幕延迟、平均延迟、最慢片段。
- 当 stable/published 延迟超过目标时，operator view 显示 warning。
- 日志或 manifest 可追溯每次生成的延迟摘要。
- 测试覆盖延迟计算和 warning 阈值。

### P1.3 Live source monitor POC

目标：从手动 live archive POC 推进到周日自动发现源。

开发 owner：Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- 新增或实现 `live_source_monitor`，检查 Mariners Online、YouTube streams、手动配置 fallback。
- 输出结构化 evidence：source URL、状态、时间、标题、是否同篇证道候选。
- 8:30 失败时自动标记 10:00 fallback。
- 09:58 前没有可用源时生成 operator alert。
- 测试使用 fixture/mock，不依赖实时网络。

### P1.4 时间轴 review 工具最小可用版

目标：operator 可以修正对齐，而不是只看模拟播放。

开发 owner：UI/Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- 支持单个 segment 的时间平移、split、merge、lock。
- 批量 offset 不改动 locked segment。
- 修改后 VTT/SRT 导出使用 edited timeline。
- UI 在 iPad 横屏上可操作，不挤压主字幕。
- 测试覆盖 offset、lock、split/merge、导出时间码。

## P2 - 离线增强与会后复盘

### P2.1 证道笔记与金句生成

目标：会后自动生成可追溯笔记、摘要、应用问题和金句。

开发 owner：Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- 从 reviewed/published captions 生成摘要、大纲、应用问题、金句候选。
- 每条金句保留 source segment id、英文原文、中文字幕、timecode。
- 生成结果写入 GCS `insights/*.json`。
- UI notes tab 可以显示生成结果。
- 测试覆盖 schema、timecode、source traceability。

### P2.2 Cloud Run 部署骨架

目标：让 POC 从本地静态页面走向可部署服务。

开发 owner：DevOps/Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- 有最小 Cloud Run 服务入口，可提供 PWA 静态资源和 manifest/playback 数据。
- 配置说明包含 service account、GCS bucket、Secret Manager 权限。
- 本地启动命令和部署命令写入 README 或 deployment doc。
- 健康检查 endpoint 可用。
- 测试覆盖本地服务启动和静态资源加载。

### P2.3 历史质量回放集

目标：用多场证道回放持续测试字幕质量和 UI 稳定性。

开发 owner：Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- 至少保存 3 场不同证道的 sanitized playback fixture 或生成命令。
- 每场包含标题、sermon start、若干字幕片段、已知经文/术语样例。
- Smoke test 可以切换 fixture 验证 UI。
- 质量回归测试能发现占位中文、空字幕、时间倒序、secret 泄漏。

## 下一步建议

最优先启动 P0.1 和 P0.2：

- P0.1 让当前 POC 从“显示正在生成的字幕”推进到“显示真正中文生成结果”。
- P0.2 让产品形态从 operator demo 变成 11:30 会众可以实际打开的界面。

并行安排：

- Review/Test agent 先为 P0.1/P0.2 写验收测试和 smoke checklist。
- Fix/Debug agent 先检查当前播放模拟、secret 边界、GCS manifest 是否有已知失败点。
- UI/Dev agent 先做 view mode 分离，不要等待完整后端。
