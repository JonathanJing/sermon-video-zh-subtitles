# 周六 PDF 生产与周日实时字幕：完整工作流

2026-09-11 安装与验收状态见 [Agents API 生产切换记录](../agents-api-production-cutover-20260911.zh.md)：代码已安装，正式入口 shadow/execute 验收通过，每周调度已启用；当前等待目标周日匹配源。

这份 README 是项目的 workflow source of truth。它描述两条 operator 主路径，区分已验证能力、尚未接入能力和估算值。执行时先按 [AGENTS.md](../../AGENTS.md) 的任务路由读取一个对应入口，不必加载全部文档。

现状校准日期：**2026-09-04**。这里的现状以 `main` 上的代码、测试和 tracked 报告为准；本地未跟踪产物、旧截图和历史运行观察不自动升级为当前事实。运行时健康、现场声学和 Wi-Fi 条件仍需在每次使用前单独检查。

状态定义：

- **Working：** 已经有当前代码与测试，或有可追溯的 tracked 真实产物报告；不等于外部服务此刻健康。
- **POC：** 核心路径可运行，但仍包含 fixture、人工步骤或未完成的现场门槛。
- **Discovery：** 只有方案或局部实验，不能描述成端到端能力。

## 总体关系

![周六、周日与 Discovery 的总体关系](../diagrams/project-map.svg)

核心边界：

- 周六路径的目标是生成经过 QA 的 durable 文档。
- 周日路径的目标是低延迟显示，同时保留足够录音和日志供回放、A/B 与后续训练。
- 周日实时录音不能依赖 ASR 或翻译成功；模型失败时继续录音，并显示英文或降级状态。
- 周六 content pack 是可选增强；`A0 / none` 始终保留为可比较基线。

## A. 周六：直播/归档到两个 PDF

2026-09-19：[生产并发与 MacBook 调度](../parallel-production.zh.md)已接入分块 ASR、双 PDF、原声对齐与 TTS 的受限并发；配音前置条件通过时可与 PDF 渲染重叠。真实双模型短样本已验证，整篇提速与听审仍待实际运行。最终来源、PDF、音轨和人工审核门槛保持不变。

可选的[统一检查与执行入口](../saturday-harness.zh.md)按顺序连接原 PDF Supervisor 和配音桥接器，分开报告 PDF、候选、听审、同步与发布。[执行保护](../sermon-execution-harness.zh.md)连接 [Promptfoo 真实固定回归集](../saturday-quality-harness.zh.md)、[本机持久化追踪与自动观察](../sermon-trace-export.zh.md)及 [Temporal 持久工作流](../sermon-temporal.zh.md)。各自的实际集成证据和运行命令见专题文档；不表示真实生产或现场已通过，也未自动替换定时任务。

**控制层迁移说明（2026-09-11）：** [Production Supervisor](../sermon-production-supervisor-agent.zh.md) 已在本地 runner 接入 OpenAI Agents API，默认 `--agent-backend agents-api`，原 Agents SDK / Responses 通过 `--agent-backend sdk` 显式回退。服务端 session 使用 `environment: none`；本地只执行状态检查、来源媒体准备（保留 timeline 工具名）和经审批 PDF 生成三个受限业务工具，另有结构化结论提交。Session 状态和工具结果持久化，同一会话恢复；自动新建会话须先确认远端 completed/failed/cancelled 且无执行中或结果未确认的工具，本地 timeout 或取消 ACK 不足以放行；source、人工审批、lease、恢复、QA 与发布继续由确定性层约束，完成状态须重新读取 production snapshot。

Supervisor 默认使用 `gpt-6-astra` Medium（本账户旧 `gpt-5.6` 查询返回 404），SDK 回退也使用同一 Astra；生产内容的 Astra Medium 和 ASR 的 `gpt-transcribe` 不变。Agents API 仅接收固定 allowlist 的日期、动作枚举与证据布尔状态；完整 snapshot 和用于恢复配置核对的 `configFingerprint` 留在本地。

真实 Agents API 的两个全模拟用例已核验：`live-synthetic-01` 缺审批用例完成 2 次工具调用、未调用生成并返回 usage；`live-synthetic-advance-01` 完成 4 次工具调用，模拟 generation 执行恰好 1 次。`live-real-shadow-minimal-01` 已完成实际生产 GCS 状态的只读检查，目标日期 `2026-09-13`，动作为 `waiting_for_matching_sunday`。三个用例均为零真实生产变更；[报告链接与验证限界](../sermon-production-supervisor-agent.zh.md#验证进度)不能代替生产入口安装或切换回执。随后已完成正式入口 execute 验收并启用每周跟进 `pdf-context-pack`；当前业务状态仍是等待匹配源，完整产物生产与未来定时唤醒各自验收，安装收据见[本地 runbook](../codex-local-production-runbook.zh.md)。本节不更新上方全项目的 2026-09-04 校准日期，也不代表周日现场验收完成。

**人工范围更新（2026-09-19）：** 完整礼拜的证道起止位置由操作员提供，已移除模型边界探测。前置阶段只下载并核验媒体，后续转写／翻译模型保持各自职责。旧 tool/action 与审批哈希字段为恢复兼容保留；[媒体证据 v2 与旧会话迁移](../codex-local-production-runbook.zh.md#人工范围流程2026-09-19-代码更新)说明具体合同。这是本地代码状态，不是远端发布或现场验收。

**新页面自动听音定位（2026-09-19）：** 同步中文音轨进入 `build_weekly_app.py` 后，固定生成原声指纹、绑定来源／人工范围／页面／音轨，并纳入发行校验。自然语速未同步试听候选明确标记不可用；新同步页面不能漏掉指纹后继续发行。用户主动授权麦克风，本地匹配同一录制并自动定位播放；真实设备与现场效果单独验收。详见[每周发行流程](../tongxing-weekly-release.zh.md#新页面固定包含自动听音定位)及[双语制作流程页](../tongxing-video-to-page.html)。

**每周默认海报交付：** 内容页发行并完成 HTTP 核验后，由 Codex 继续完成 ImageGen 主视觉、目录文字与真实二维码合成，以及最终 PNG／缩略图解码和目视 QA；无需用户每周重复要求。主题、日期、经文、讲员取本周 catalog，二维码精确指向该页 `?week=<page-id>`。这是默认交付约定，不代表 Supervisor 自动调用图像工具、付费 API 或自动发送／上传；海报不能提升页面的发布或人工验收状态。命令与证据要求见[每周海报交付](../tongxing-weekly-release.zh.md#每周海报交付)。

### 完整流程图

![周六 post-live 双 PDF 完整流程](../diagrams/saturday-post-live-workflow.svg)

当前每周配置的翻译、两轮阅读稿审核和证道同行生成统一使用 **Astra Medium**。双 PDF QA 通过后，Supervisor 自动导出周日 Context Pack 与 readiness；导出的同篇身份初始为 `unknown`，不能自动获得 live 注入资格；操作细节见[每周生产配置](../codex-local-production-runbook.zh.md)。这项配置不重做历史周次，模型审核也不替代人工确认。

### Canonical 输入与产物

| 阶段 | 必须保留的证据 |
|---|---|
| Source | canonical URL、service date、source ID、完整媒体 hash/时长 |
| 人工边界 | operator、绝对 start/end、审批时间、绑定的 source hash |
| ASR/阅读稿 | ASR reference、分段英文、中文阅读稿、prompt/model/version |
| QA | reading quality report、两个 PDF QA report、run status |
| 最终交付 | `sermon_zh_en_reading.pdf`、`sermon_interpretation_zh.pdf` |

`sermon_zh_en_reading.pdf` 是翻译稿/阅读版。`sermon_interpretation_zh.pdf` 是证道同行/大纲，只保留核心信息、结构、经文背景、神学重点、例证与必要的牧养辨析；不加入讨论题或与证道无关的应用任务。

**同行内容契约（2026-09-12 修复）：** 新生成使用 `sermon-companion-v3` prompt 与 notes schema v3，不再生成讨论题、小组指南或回应祷告；可选节按来源证据决定数量，核心信息、摘要和大纲仍必需。来源引用、精确摘录及双 PDF QA 保留。旧 v2 产物沿用原验收规则，不自动重做。[修复与离线验证记录](../prompt-agent-skill-audit-fixes-20260912.zh.md)包含双 PDF 合成样例；真实模型内容质量仍需新运行验收。

### 周六内容如何服务周日

周六英文字幕、候选中文、术语、经文引用和段落顺序可以转换成短期 `weekly-pack.json`：

完整的方案审核、数据契约、fallback 决策和开发步骤见[周六产物到周日实时字幕 Context Pack 计划](../saturday-to-sunday-context-pack-plan.zh.md)。当前已实现 exporter、builder、retriever、capability readiness、Gateway policy 上限和 replay。真实每周内容的质量收益及 ASR phrase bias 仍待验证；English-only 仅辅助对齐，不改变 A0 翻译 prompt。

1. 以稳定 caption segment 为一条 JSONL，保留 `segmentId`、时间、英文、中文状态、术语和经文引用。
2. 按周六演讲顺序生成一张 ordered sermon map。
3. 机器中文只能作为 candidate；只有 reviewed/corrected/approved 内容可以进入 live prompt。
4. 周日先运行 `A0 / none`，再用相同录音回放 `english_alignment_v1`、`weekly_terms_v1` 或 `saturday_alignment_v1`。
5. 每次翻译记录命中的 context ID、policy、cursor、模型和延迟，保证 A/B 可复现。

## B. 周日：MacBook 麦克风到实时中文字幕

### 完整流程图

![周日本地实时字幕完整流程](../diagrams/sunday-live-workflow.svg)

### 运行时 sequence

![实时字幕运行时序](../diagrams/live-runtime-sequence.svg)

### 当前实现状态

| 能力 | 状态 | 说明 |
|---|---|---|
| 麦克风选择、音量、开始/停止 | Working | 已用真实浏览器麦克风验证 |
| 增量录音、events、manifest、SHA | Working | 每次启动建立独立 session 文件夹 |
| MiLMMT A0/Ollama translation | Working | 冻结 prompt，`contextPolicy=none` 基线 |
| 大号中文、英文 sidecar、手机只读页 | Working POC | 前一句完整双语 + 当前可读字幕；LAN 用随机 token + SSE；手机横竖屏适配 |
| 蜂窝网络扫码公网分享 | Working POC | Firebase Hosting + Realtime Database 已实现并有开发部署；MacBook 只出站发布。本地 Wi-Fi 与实际蜂窝设备需分别验收 |
| 本地英文 ASR | Working POC | Qwen3-ASR 0.6B/MLX 优先；Whisper 为启动时备选，不是运行中自动切换；见下方真实模型回放证据 |
| 周六 content pack | POC | exporter、capability readiness、受控 runtime policy 已实现；须独立确认同篇信息，自动导出初始为 `unknown`，真实周日收益尚未通过盲评 |
| 会后 replay/A-B | Working | 同一组 `asr.final` 按 policy 重放；生成盲评 CSV 和 hash provenance |
| ASR Gold gate | Working gate | 六 case 队列已生成；真人未审核前正式 WER fail-closed |
| Session 保留 | Working | 默认只预览；30 天、保留最近 10 个；只有显式 `--apply` 删除 |

## ASR + 翻译总延迟预算

### 当前可读字幕证据

代码基线为 main `beeda82`；真实长测运行在 clean `edaa9d1`，之后的 POC 变更只有文档。完整 provenance、指标与限制见[2026-09-04 验收报告](../../experiments/local-live-poc/benchmarks/SUNDAY_READINESS_20260904.zh.md)。

- MacBook Pro M1 Max 64 GB，Qwen3-ASR 0.6B 8-bit + MiLMMT 4B Q8，冻结 A0、无 Pack、3 秒窗口、即时翻译。
- 3620.818 秒浏览器 WAV 回放，20 分钟唯一音频循环三轮；真实 MediaRecorder/Worklet、ASR、翻译和操作页显示，不经过物理麦克风。
- 1,287 processing/final/translation/可读首显全部结算；独立浏览器录音副本与 Gateway hash 相同，WebM/WAV 完整解码通过。
- 357 个录音窗口健康样本全部 ready、swap 0；初始缺测 40.439 秒、末尾 6.588 秒。翻译 RSS 仍增长，未证明连续多场上限。

### 延迟拆分：不是承诺的 SLO

| 阶段 / 口径 | P50 | P95 |
|---|---:|---:|
| 音频段结束 → ASR final | 1.259 s | 1.315 s |
| MiLMMT TTFT | 0.129 s | 0.150 s |
| 音频段结束 → 操作页可读首显 | 1.634 s | 1.776 s |
| 音频段结束 → 操作页可读终显 | 1.634 s | 1.777 s |
| 音频段开始 → 操作页可读首显 | 4.627 s | 4.763 s |

可读字幕各 N=1,287；P95 使用排序后的 `round((n-1)*0.95)` 索引。TTFT、完整模型输出、可读首显和手机显示是不同终点，不能互换。VAD 配置为 500 ms silence / 最长 3 秒；段结束指标不包含形成该段的等待。操作页运行状态仍展示模型首字/完整耗时，实际可读显示须查看 `caption_rendered` 与 scorer。这里的覆盖率以已发出的 ASR final 为分母，不是语音召回率或翻译准确率。

### 恢复与默认策略

独立重启回放恢复了同一 session 与观看 token，录音可完整解码；同时留下 1.6 秒 PCM gap、一个未结算在途 ASR 任务，以及 7.234 秒的新字幕更新间隔。`completed` 的保存状态不等于 `captionContinuity=uninterrupted`。停止必须核验最新连接的 worker/storage drain，再完成 manifest 和 hash；失败保留恢复副本并显示故障。

保留 `translationUnitPolicy=legacy` 和 `sourceFragmentPolicy=content_words`。真实 3/6 秒窗口和有界合并比较均出现新语义错误，`bounded_semantic_v1` 不升级默认；孤立虚词门控也不是语音/音乐分类器。Firebase 有界发布器不阻塞本地链路，公网失败可选 LAN；发布确认不等于手机呈现确认。

### ASR benchmark 必须回答的问题

现有 acoustic benchmark 已覆盖五位讲员、正常/低音量、口音、经文、音乐、双人切换等 case，并比较过 Whisper；当前 runtime 基线改为 Qwen3-ASR。正式模型选择仍要记录：

- WER，以及 Scripture/人名/地名/教会术语的 entity accuracy。
- 2 秒、4 秒、8 秒片段的 RTF、p50/p95 inference latency。
- 不同 VAD silence threshold 下的句末到 final latency。
- 噪音、音乐、远场麦克风和讲员停顿时的删除/重复/幻觉。
- 与 MiLMMT 串联后的句末到中文 p50/p95，以及是否丢 chunk。

选择标准不是单独追求最低 WER，而是在术语准确度、稳定性和句末延迟之间取平衡。GPT-transcribe 参考只能算 provisional；`benchmarks/asr-gold-review-queue-20260904.jsonl` 必须由真人逐词校正、签名、记录时间后，正式 WER gate 才会通过。

## 测试与完成标准

### Unit

- audio chunk/event 顺序、session finalize 与 SHA。
- ASR 输出 parser、VAD endpoint、稳定片段去重。
- Gateway request/response、context policy 与翻译失败降级。

### Integration

- 固定音频 fixture → ASR → MiLMMT → caption event → session artifacts。
- 同一音频分别运行 A0 和 content-pack variant，验证输入完全相同。
- 模型失败、Gateway 重启和磁盘写入失败时，录音仍保留或明确进入 browser fallback。

### 真实 E2E

- 当前合并代码已有 60 分钟真实模型浏览器 WAV 回放证据；历史麦克风 soak 保留在原报告中。两者均不替代实际场地输入、实体手机与人工语义验收。
- 音频可解码、chunk/event sequence 连续、manifest completed、SHA 匹配。
- English final 和 Chinese result 均可见，按明确口径测量 p50/p95，单列缺段、策略 skip 和故障；没有事先批准的阈值时不称“达标”。
- 录音可以在家中 replay，并复现相同 ASR/翻译版本的结果。

当前工程路径已经具备，但 production acceptance 尚未闭环：正式教会现场彩排、人工 Gold 校正、真实周六 pack 的每周盲评，以及连续多场运行的资源上限仍需验证。翻译模型后训练是独立 Discovery 项目，不是周日 POC 的上线前置条件。周日路径只有在现场音频路由、Wi-Fi 手机访问和端到端字幕都通过后，才可以称为 production-ready。

## 相关实现

- [本地 live POC](../../experiments/local-live-poc/README.md)
- [POC 设计](../../experiments/local-live-poc/DESIGN.zh.md)
- [实时音频与字幕传输决策](../../experiments/local-live-poc/STREAMING.zh.md)
- [公网手机字幕分享方案](../../experiments/local-live-poc/PUBLIC_SHARING.zh.md)
- [周六产物到周日 Runtime Pack 方案与开发步骤](../saturday-to-sunday-context-pack-plan.zh.md)
- [稳定 post-live PDF 工作流](../stable-post-live-reading-pdf-workflow.zh.md)
- [本地周末生产 runbook](../codex-local-production-runbook.zh.md)
- [完整文档索引](../README.zh.md)
