# Dev 统一 Backlog

更新：2026-09-24。本页是项目 **Dev 开发工作的唯一顶层 backlog**，统一管理四层生产、Firebase Dev、Web／iOS、现场对齐、审核后台、Tracker、CI 和独立 `live_session` 的优先级与依赖。新增开发事项先在这里取得稳定 ID；专项文档只展开接口、实现和验收，不再各自形成互相竞争的顶层排期。

English index: [backlog.md](./backlog.md)

本页不代替：

- [四层接口合同](multilingual-production-interfaces.zh.md)：定义生产包、hash、门禁和失效规则；
- [四层制作 Tracker](four-layer-production-tracker.zh.md)：记录某一篇、某一语言、某一次运行的实际状态、证据与 ETA；
- 发布收据、设备收据和现场收据：分别证明对应环境的事实。

## 维护规则

1. 顶层优先级和跨模块依赖只在本页维护；专项 backlog 用本页 ID 反向引用。
2. `complete` 必须绑定已合并代码及对应测试；涉及发布时还要分别记录 Dev／Production HTTP、设备和现场证据。
3. 当前工作树、PR、单元测试、Dev 页面可播和 Production 可发布是不同状态，不能互相推断。
4. P0 是进入下一次完整周产或修复已观察现场问题所必需；P1 是稳定性、效率和可运营性；P2 是实验、扩展或历史方向。
5. 每周内容运行不在这里逐组打勾；使用 Tracker 的 `L1-01`—`L4-04`。这里管理让这些检查点可重复完成的工程能力。

状态枚举：`verified_baseline`、`in_progress`、`pending`、`waiting_evidence`、`blocked`、`complete`。`verified_baseline` 只说明列出的基线已验证，不代表该项所有未来周次完成；只有满足本页第 2 条维护规则和该项验收定义后才能标记 `complete`。

## 当前已验证基线

- 2026-09-20 的 2:58 中文、韩语、西语样片已有正式 Layer 1–4 包、三语文字和音频人审、Firebase Dev HTTP／Range 及浏览器短时播放证据；iOS 真机和现场仍是 `not_run`。
- Firebase Dev 已有可保留旧 POC、旧中文九周和正式三语样片的完整预览；Production 仍按独立发布授权和核验流程处理，不能从 Dev 自动晋升。
- Layer 2 的 Astra 初译 → Sol 独立逐组复核、语言插件和人工批准链已有通用实现；Layer 3 的正式 renderer、筛查、排程和包构建已有样片证据，但完整周产、可移植媒体恢复和第二周复现仍未完成。
- iOS v2 catalog／Release Package reader、语言选择和 Dev origin 适配已有实现候选及自动化测试；实体设备上的三语下载、离线、播放和 WebView 正文可见性仍须验收。
- 远距离座位的自动声音对齐“不容易触发”是已观察现场问题；当前只有 backlog 设计，没有 AGC／10→15 秒自适应采集的运行实现或现场通过证据。

## P0：下一次完整 Dev 周产与已观察问题

| ID | 范围 | 当前状态 | 下一可验收结果 | 详细合同／证据 |
|---|---|---|---|---|
| `DEV-GOV-001` | 分支、CI 与 Dev→main 晋升 | `in_progress` | 功能从最新 `dev` 经 required checks 合并；晋升后按受检查 sync PR 回同步，不直接修改受保护分支 | [分支与 Firebase 环境](development-branch-and-firebase-environments.zh.md) |
| `DEV-L1-001` | Layer 1 完整英文事实与锚点 | `in_progress` | 一篇真实整篇完成媒体／范围／英文逐字／词时间／句界停顿／人工审核的可重复 hash 绑定，并产出 `ready_for_translation` | [Tracker 的 Layer 1 工程项](four-layer-production-tracker.zh.md#layer-1-工程-backlog) |
| `DEV-L2-001` | Layer 2 每周多语言文字 | `in_progress` | `zh-Hans`、`ko`、`es` 从同一正式 Layer 1 独立运行 Astra→Sol→语言插件→人工批准；逐组失败可恢复且不污染其他语言 | [Layer 2/3 backlog](multilingual-layer-2-3-backlog.zh.md#3-layer-2目标语言文字-backlog) |
| `DEV-L3-001` | Layer 3 正式整篇音频包 | `in_progress` | 同语言正式 Candidate 经授权音色、自然语速合成、完整解码、回转写、滚动排程、字幕、全文听审与 1 倍速同步形成可移植 Audio Package | [Layer 2/3 backlog](multilingual-layer-2-3-backlog.zh.md#4-layer-3目标语言音频与同步-backlog) |
| `DEV-L3-002` | 英文声学停顿驱动的自然表达 | `in_progress` | 目标语言完整自然句只在已审英文声学锚点处排程；局部 overrun 返回翻译／句界修订，不以词组拼接或拉伸掩盖 | [多语言 Prosody POC](multilingual-prosody-poc.zh.md) |
| `DEV-L4-001` | 可重复的 Firebase Dev 周更新 | `in_progress` | `build-update → preflight → deploy → verify` 从完整线上 Dev 基线追加新周，保留所有仍被 catalog 引用的旧资产，并生成逐文件 HTTP／SHA／Range 收据 | [Dev 预演](evidence/2026-09-23-production-readiness/DEV-PREVIEW.zh.md#后续-dev-周次) |
| `DEV-IOS-001` | 原生多语言消费与真机验收 | `in_progress` | 补齐原生三语音频切换、跨轨 source-unit 定位、`PlaybackHistory` v2 和韩／西语支持，再由真机完成 v2 catalog 刷新、下载、离线恢复、历史隔离、WebView 正文、VoiceOver 和系统媒体验证 | [iOS backlog](../apps/tongxing-ios/BACKLOG.zh.md) |
| `DEV-FIELD-001` | 远场声音指纹对齐 | `pending` | Web 与 iOS 实现隐私受限诊断、AGC profile 和同一次 10→15 秒自适应采集；不降低匹配门槛，远处同源至少 9/10 正确、30 次负样本零误跳 | [本页专项设计](#dev-field-001远场声音对齐) |
| `DEV-TRACK-001` | Producer 自动记账、状态与 ETA | `in_progress` | 正式 Layer 1–4 producer 自动写实际运行、等待、重试与审核事件；公开 Tracker 只投影脱敏状态，ETA 只来自可追溯速率／估时 | [Tracker 接入项](four-layer-production-tracker.zh.md#tracker-接入-backlog) |
| `DEV-REVIEW-001` | 私有多语言人工审核后台 | `pending` | 两位不同语言审核者可并行审阅 Layer 2/3；权限、hash、版本、移交、修订失效和不可变收据均 fail closed | [审核后台设计](four-layer-production-tracker.zh.md#多语言人工审核后台-backlog) |
| `DEV-LIVE-001` | 独立 Sunday `live_session` | `in_progress` | 现场 ASR final 保持事实源；翻译、术语、延迟、发布和 fallback 有独立真实回放／现场证据，不借用四层预制完成状态 | [工作流总览](workflows/README.zh.md)及本页历史附录 |
| `DEV-PROD-001` | Dev 晋升 Production | `blocked` | 只有完整周产、Dev HTTP、回滚基线、Production 发布授权和部署前核验齐全后，才从 `dev` 晋升 `main` 并执行 Production 发布；设备／现场仍独立 | [Production 合并检查](multilingual-production-premerge-2026-09-23.zh.md) |

### `DEV-FIELD-001`：远场声音对齐

现场反馈表明后排座位经常无法触发可靠定位。该问题属于 Layer 4 客户端采集／匹配，不是 Layer 3 指纹索引生成失败。

- [ ] Web 保留 `raw-v1` 基线，新增 `far-field-agc-v1`，请求 `autoGainControl:{ideal:true}`；读取授权后 track 的实际 settings，只记录布尔值与区间化质量数据，不记录 device ID、PCM 或 landmark。
- [ ] 同一次麦克风会话最多 15 秒：10 秒 checkpoint 可靠匹配即停止；`silence`、`insufficient_audio`、`no_consensus`、`low_confidence` 或 `ambiguous` 时继续 5 秒并以完整 15 秒重试。
- [ ] 延长只增加证据，不降低 votes、anchor、覆盖、runner-up ratio、match fraction 或三段覆盖门槛；失败不改变播放位置。
- [ ] UI 区分麦克风未启动、音量／特征不足、没有共识、含糊和低置信，并显示“声音较远，继续听 5 秒”；取消、切后台、换篇／换轨和超时立即关闭麦克风。
- [ ] iOS 保留 `.measurement` 基线；AGC POC 必须实际启用 `AVAudioEngine` Voice Processing 并核对 route／mode，不能只改成 `.voiceChat` 后宣称生效。
- [ ] 近／中／远 × 安静／附近说话／纯环境声做 Web／iOS 独立冻结 A/B；远处有效同源至少 10 次中 9 次正确定位，非同源／纯噪声／含糊片段至少 30 次零误跳。

Firebase Hosting 只发布静态运行时和指纹索引；采集、特征和匹配留在客户端。复用现有 fingerprint runtime 文件不需要改变 Hosting 架构；新增模块时必须同步 build allowlist、deploy allowlist 和哈希验证。

## P1：稳定性、恢复与运营效率

| ID | 工作 | 当前状态 | 完成定义 | 详细入口 |
|---|---|---|---|---|
| `DEV-VOICE-001` | Speaker Voice Registry 授权与可移植恢复 | `in_progress` | 每语言 checkpoint 的授权范围、能力、hash、媒体恢复位置和归档验证可在干净环境重建，不依赖原工作站绝对路径 | [Speaker Voice Registry](multilingual-speaker-voice-registry.zh.md) |
| `DEV-L4-002` | 原子 catalog、单语言回滚与旧资产保护 | `in_progress` | 新语言／周次更新不删除其他 locale 或旧周资产；catalog 最后发布；单 locale 可回滚 | [Layer 4 backlog](multilingual-layer-4-delivery-app-backlog.zh.md#6-layer-4-与-app-改进-backlog) |
| `DEV-IOS-002` | iOS WebView／CI 偶发空白与系统表面 | `in_progress` | 相同 CI 系统和真机稳定显示正文；Now Playing、锁屏、耳机／中断、Live Activity、无障碍分别验收 | [iOS backlog](../apps/tongxing-ios/BACKLOG.zh.md) |
| `DEV-TRK-002` | 第二周真实全流程复现与恢复 | `pending` | 用新周次验证缓存、断点恢复、上游失效、旧资产保留和 ETA 校准，不复用第一周人工结论 | [四层 Tracker](four-layer-production-tracker.zh.md) |
| `DEV-SPD-001` | 并发、审核等待与模型路由优化 | `pending` | 先完成完整 trace 审计，再逐一比较语言并行、Layer 3 并发和 Astra／Luna shadow；只采用端到端更快且质量门禁不降的方案 | [提速 backlog](four-layer-production-tracker.zh.md#周日页面提速-backlog本轮结束后按审计证据实施) |
| `DEV-LOCALE-001` | 界面本地化母语复核 | `in_progress` | 中文、英文、韩语、西语、越南语界面候选分别完成核心流程、错误、权限、VoiceOver 和长文本复核；界面语言不改变内容／音频选择 | [Layer 4 语言设计](multilingual-layer-4-delivery-app-backlog.zh.md#24-app-界面语言) |

## P2：实验与非阻塞扩展

| ID | 工作 | 当前状态 | 边界 |
|---|---|---|---|
| `DEV-EXP-001` | Gemini 音视频 sidecar／事件分类 | `in_progress` | 继续 Discovery/shadow；没有人工 Gold 和按类别质量证据前，不改写 Layer 1、翻译、TTS 或发布状态。 |
| `DEV-EXP-002` | VoxCPM2、MOSS、AuK 等 TTS challenger | `pending` | 只做同输入盲听 A/B；不能因为短样本更好替换 Qwen3-TTS SFT 正式 checkpoint。 |
| `DEV-EXP-003` | Cloud Run、笔记、金句与历史回放 | `pending` | 不阻塞四层 Dev 周产或独立 live session；引用必须保留 source unit 与 timecode，历史 Cloud 方案不自动成为当前部署方向。 |
| `DEV-EXP-004` | DeepSeek Harness／Terra 调度 A/B | `pending` | 先隔离比较 CUV 状态检查、工具调度和恢复；保持生产翻译／核验模型及人工门禁不变。未测量前不替换正式入口。详见[实验提案](scheduler-harness-ab-experiment.zh.md)。 |

## 专项文档归属

| 文档 | 现在负责什么 | 不再负责什么 |
|---|---|---|
| [四层制作 Tracker](four-layer-production-tracker.zh.md) | 单次生产检查点、证据、耗时、阻塞和 ETA | 全项目 Dev 优先级 |
| [Layer 2/3 backlog](multilingual-layer-2-3-backlog.zh.md) | 文字与音频 producer 的原子实现、schema 和验收 | 跨层排序 |
| [Layer 4 backlog](multilingual-layer-4-delivery-app-backlog.zh.md) | catalog、发布、Web／App 交互和验证矩阵 | Layer 1–3 优先级 |
| [iOS backlog](../apps/tongxing-ios/BACKLOG.zh.md) | 原生客户端详细需求与平台验收 | 上游内容／音频完成声明 |
| [分支与 Firebase 环境](development-branch-and-firebase-environments.zh.md) | Dev／Production 隔离和晋升规则 | 某次发布已完成的证明 |

## 历史附录：2026-06-22 11:30 会众中文字幕 Backlog

以下内容保留早期 `live_session` 的需求来源，**不再是当前顶层排期**。仍有效的工作已映射到 `DEV-LIVE-001`、`DEV-EXP-003`；实施前必须以当前 live POC、运行手册和真实现场证据重新校准。

### 产品目标

北星目标：在每周日 11:30 PT 场证道开始时，中文会众可以打开一个稳定、低干扰、可阅读的中文字幕界面，帮助他们在现场听道。

Backlog 排序原则：

1. 先保证 11:30 会众能看到可用中文字幕。
2. 再降低延迟、提高经文/人名/术语准确度。
3. 最后完善离线字幕、笔记、金句和运营工具。

### 当前基线

- 已有静态 Web/PWA 原型，可展示 operator 控制台、证道标题、生成状态、字幕片段、经文 sidebar、VTT/SRT 导出。
- 已有 `prepare_live_link_playback.py`，可从 YouTube live archive link 生成播放模拟数据。
- 已有 GCS 发布参数和 Secret Manager resource name 边界，生成物可进入 GCS，API key 明文不进入 artifact。
- 当前播放模拟仍以可用字幕源为基础；如果只有英文字幕，中文行显示 `AI 中文待生成`，下一步必须接入真实翻译/生成。

### P0 - 11:30 会众可用闭环

#### P0.1 接入真实中文生成链路

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

#### P0.2 会众视图与 operator 视图分离

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

#### P0.3 发布状态与 11:25 readiness gate

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

#### P0.4 GCS artifact manifest 可被 Cloud Run / Web 加载

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

### P1 - 质量、延迟与现场可用性

#### P1.1 翻译质量策略：经文、人名、术语优先

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

#### P1.2 延迟指标与生成进度可观测

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

#### P1.3 Live source monitor POC

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

#### P1.4 时间轴 review 工具最小可用版

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

### P2 - 离线增强与会后复盘

#### P2.1 证道笔记与金句生成

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

#### P2.2 Cloud Run 部署骨架

目标：让 POC 从本地静态页面走向可部署服务。

开发 owner：DevOps/Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- 有最小 Cloud Run 服务入口，可提供 PWA 静态资源和 manifest/playback 数据。
- 配置说明包含 service account、GCS bucket、Secret Manager 权限。
- 使用 [Cloud Run 部署准备与 Secret Manager 清单](./cloud-run-deployment-prep.zh.md) 作为部署前 checklist。
- 本地启动命令和部署命令写入 README 或 deployment doc。
- 健康检查 endpoint 可用。
- 测试覆盖本地服务启动和静态资源加载。

#### P2.3 历史质量回放集

目标：用多场证道回放持续测试字幕质量和 UI 稳定性。

开发 owner：Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- 至少保存 3 场不同证道的 sanitized playback fixture 或生成命令。
- 每场包含标题、sermon start、若干字幕片段、已知经文/术语样例。
- Smoke test 可以切换 fixture 验证 UI。
- 质量回归测试能发现占位中文、空字幕、时间倒序、secret 泄漏。

### 历史下一步建议

最优先启动 P0.1 和 P0.2：

- P0.1 让当前 POC 从“显示正在生成的字幕”推进到“显示真正中文生成结果”。
- P0.2 让产品形态从 operator demo 变成 11:30 会众可以实际打开的界面。

并行安排：

- Review/Test agent 先为 P0.1/P0.2 写验收测试和 smoke checklist。
- Fix/Debug agent 先检查当前播放模拟、secret 边界、GCS manifest 是否有已知失败点。
- UI/Dev agent 先做 view mode 分离，不要等待完整后端。
