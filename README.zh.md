# 证道视频中文字幕

<p>
  <a href="./README.md">
    <img src="https://img.shields.io/badge/Language-English-blue" alt="English README" />
  </a>
  <a href="./LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License" />
  </a>
</p>

**[从视频到新页面：中英双语 HTML 流程（GitHub）](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/main/docs/tongxing-video-to-page.html)** — 包含模型职责及 MacBook 优先、DGX Spark 回退路由。

帮助中文会众听懂英文证道。当前优先展示**周六预制、周日按同一视频时间轴播放的中文配音**：复用已审英文和中文，采用经授权的讲员原声参考配音，交付 MP3、随声字幕与证道同行大纲。双 PDF 生产和本地实时字幕继续作为独立工作流保留。

> **现状校准：2026-09-20。** Eric Geiger《耶稣的应许》已发布，中文配音在 MacBook 本地生成；用户已确认听审及 Firebase／iOS 播放通过，真实现场同步仍未证实。含本周页面真实二维码的分享海报已纳入每周默认交付。阶段时间、Token 与验收边界见[本周制作记录](docs/production-2026-09-20.zh.md)。每周完整媒体、音频和 PDF 保存在 Git 之外。

> 这是一个独立的个人开源项目，不属于 Mariners Church 官方项目，也没有获得其隶属、背书、赞助、批准或运营支持。只应处理公开或已获授权的媒体，不得绕过访问控制、DRM 或平台限制。

## 四层生产架构：从英文事实到多语言发布

生产流程统一分为四层：**英文 → 翻译 → 配音 → 发布**。这是一条逐层交付、逐层验收的链路；上一层通过，不代表下一层已经通过。当前主要生产语言是中文，韩语和西班牙语作为后续目标语言接入同一套接口，但必须各自完成翻译、配音和发布验收。

| 层 | 核心职责 | 模型与程序分工 | 交付物与验收门槛 |
|---|---|---|---|
| 1. 英文事实层 | 锁定来源、证道范围和完整英文；把字词与原音时间轴对齐，再按句号、逗号、语义分句和停顿建立稳定锚点 | `gpt-transcribe` 或可信原稿提供文字；MFA、Qwen ForcedAligner 等候选负责声学字词定位；LLM 可校对文字、标点和断句，但不能凭语言判断伪造时间戳 | 不可变英文锚点单元、字词时间、来源/hash、模型身份和覆盖率；先证明内容完整且时间可追溯 |
| 2. 目标语言翻译层 | 从英文锚点直接翻译，完整表达每句意思，并检查否定、因果、经文、专名、数字和术语 | 当前中文由 GPT/Astra 类翻译与独立审核协作；以后每种语言可选择自己的翻译模型、提示词、术语表和审核模型 | 每个译文单元必须关联英文锚点 ID；语义完整性和语言审核独立通过后才能进入配音 |
| 3. 配音与同步层 | 用已批准译文生成自然语速语音，测量真实时长，并利用英文停顿和分句安排滚动播放；较长句可在语义稳定处自动拆成约 6–8 秒单元 | Qwen3-TTS 等语音模型负责合成；Qwen3-ASR 等回转写只做机器筛查；确定性调度器负责时长、间隔和时间轴，最终仍需人工完整听审 | 目标语言音频、字幕和调度时间轴；发音、漏译、自然度、抢话/拖尾和整段听感分别验收 |
| 4. 发布与播放层 | 把正确的视频、音频、字幕、页面和语言入口绑定在一起，完成部署、下载和端上播放 | 页面构建器、FFmpeg、Firebase、Web/iOS 客户端和验证程序负责交付；Supervisor/Agent 只编排状态，不能替代内容事实或人工验收 | 按语言隔离的发布包、hash、HTTP/下载检查和播放器验证；现场同步、设备和听众体验另行留证 |

多语言扩展遵循以下契约：

- 英文事实层只生成一套共享、冻结的锚点；中文、韩语、西班牙语等都从英文直接分叉，不以中文译文作为其他语言的翻译源。
- 每种目标语言分别保存 `locale`、英文锚点 hash、翻译/审核模型、语音模型或 checkpoint、时间轴和人工审核状态；一种语言失败时，不自动阻塞或批准其他语言。
- 模型可以在层内替换和 A/B 测试，但不得跨层覆盖责任：Forced Aligner 不判断语义完整，翻译模型不决定声学时间，回转写不等于人工听审，部署成功也不等于现场验收。
- 句级锚定和 clause-stable 拆分位于英文层与翻译层的接口：先稳定“原文说了什么、何时说”，再让目标语言尽早、完整、自然地表达。

详细契约与当前实现见[工作流总览](docs/workflows/README.zh.md)、[句级锚定与滚动同传设计](docs/sentence-aligned-interpretation.zh.md)和[系统设计与模型选择](docs/sermon-dubbing-system-design.zh.md)。

## 周日运行：准备页面与创建本场字幕会话

[运行白皮书](docs/sunday-live-operations-whitepaper.zh.md) · [Agent 直接执行入口](docs/sunday-live-agent-runbook.zh.md)

复用现有应用打开操作页，开始录音后自动建立本场 session 和手机观看链接；每周无需重新部署网页。入口文档包含预检、音频与分享范围、恢复和保存核验。“准备页面”停在待机，不自动录音。

把下面指令交给 Agent 即可开始：

```text
读取 docs/sunday-live-agent-runbook.zh.md，准备本周日实时字幕操作页。
复用本机已安装环境，先检查现有录音；打开页面后停在待机。
返回页面、有效模型、预检结果和还需要我处理的事项。
```

## 1. 优先展示：英文证道视频 → 讲员音色中文配音

[打开中文听译 App](https://ai-for-god-sermon-audio.web.app) · [系统设计与模型选择](docs/sermon-dubbing-system-design.zh.md) · [操作 Runbook](experiments/sermon-dubbing-poc/SATURDAY_AUDIO_RUNBOOK.zh.md) · [本周制作记录](docs/production-2026-09-20.zh.md)

![两路来源、讲员音色训练、中文配音审核与周日播放](docs/diagrams/saturday-chinese-voice-workflow.svg)

**按来源身份选择播放方式。** 9 月 20 日版采用用户确认的完整礼拜录像，完整片长 **1:16:07**，证道范围 **29:49–1:02:09**。同版本视频入口支持完整录像中的已批准范围，也支持核验后的纯证道整片。归档入口继续保留；同一篇信息的另一场录制不自动视为同版本视频。

| 阶段 | 当前实现 |
|---|---|
| 视频英文转写 | `gpt-transcribe`；已有可信英文可复用，疑难原声单独复查 |
| 中文口播修订与审核 | 本对话 `gpt-6-astra`；完整语义、否定、经文、专名及引文边界分别核对 |
| 讲员音色 | 本周已使用 MacBook 本地 MLX Qwen3-TTS 与获准原声参考；Spark 训练保留为独立路径 |
| 语音检查与时间定位 | 本地 Qwen3-ASR 回转写、ForcedAligner 声学定位；自然语音时长逐段核验 |
| 试听交付 | 独立 Firebase App；按周选择、MP3 下载、字幕、大纲、时间跳转与微调 |

**本周版本：** [9 月 20 日《耶稣的应许》](https://ai-for-god-sermon-audio.web.app/?week=2026-09-20-same_video-7c193fd4-bc90-4f3b-aa00-37dfe8423aa0)，讲员 Eric Geiger，经文《启示录》2–3 章。完成来源绑定、中文与和合本引文审校、本地配音、真实时长核验及发音修复；用户已确认听审与 Firebase／iOS 播放通过。[本周制作记录](docs/production-2026-09-20.zh.md)保留阶段时间、Token 统计与证据边界。

**每周默认海报：** 内容发布并通过 HTTP 核验后，由 Codex 生成 ImageGen 主视觉，合成目录文字与精确指向本周页面的真实二维码，完成最终 PNG 和分享缩略图解码与目视 QA。无需用户每周重复要求；这不表示定时 Supervisor 自动调用 ImageGen，也不自动上传或发送海报。详见[每周发行流程](docs/tongxing-weekly-release.zh.md#每周海报交付)。

**当前边界：** 用户听审及 Firebase／iOS 播放通过不等于真实现场同步通过。原视频时间轴对齐、同录制声音定位与现场效果分别留证；另一场现场讲述不能直接沿用预制时间轴。[8 月 30 日候选记录](docs/sermon-dubbing-astra-review-2026-09-05.zh.md)保留为历史证据。

## 为什么保留双 PDF 与实时字幕

![双 PDF 与实时字幕的工作流关系](docs/diagrams/project-map.svg)

周日现场目前没有可靠的中文字幕。通用实时语音翻译可以生成初稿，但对经文出处、圣经人名、逐字引用和教会特定术语的处理不够稳定；分段抖动和端到端延迟也会让本来正确的文字难以在现场阅读。

当周日是重新现场讲述而不是播放同一个视频时，不能直接套用预制配音。此前的实时字幕设想，是提取并翻译周六公开直播中的证道，再把内容用于周日。实测发现了一个关键边界：周六和周日可能共享同一篇信息的框架，但不能假定两次讲述逐字一致；措辞、顺序、例子和现场新增内容都可能变化。因此，周六转写适合做准备资料，却不能成为周日字幕的事实来源。

当前架构支持可选的受控混合方案，已测周日默认仍为 `contextPolicy=none`：周日现场音频及由它识别出的当下英文始终具有最高优先级；公开或已获授权的周六材料，只提供受控的结构、术语、经文出处和经过审核的例句。领域后训练继续独立评估，v4.1 候选已可在本机试用。质量和延迟改善必须通过冻结评估证明；完成接入不代表候选已获准升级。

![从周日字幕缺口演进到受控混合方案](docs/diagrams/solution-journey.svg)

## 2. 其他独立工作流

### A. 周六：从直播/归档生成两个经过审核的 PDF

周六工作流负责发现或接收公开直播链接、保存完整 post-live 媒体、由 operator 确认证道时间窗、生成英文转写与中文阅读稿，最后在周日前形成两个 canonical 交付物：

1. `sermon_zh_en_reading.pdf`：中英翻译稿 / 阅读版。
2. `sermon_interpretation_zh.pdf`：中文“证道同行”/证道大纲，只保留与证道直接相关的辅助信息。

<table>
  <tr>
    <th>中英对照阅读版</th>
    <th>中文证道同行</th>
  </tr>
  <tr>
    <td><img src="docs/assets/pdf-examples/sermon-zh-en-reading-real-page-1.png" alt="真实中英对照阅读版 PDF 第一页" /></td>
    <td><img src="docs/assets/pdf-examples/sermon-interpretation-zh-real-page-1.png" alt="真实中文证道同行 PDF 第一页" /></td>
  </tr>
</table>

_图片来自 2026-08-30 真实运行的第一页；两份 PDF 各自的 QA 都为 `pass`，完整运行产物仍保持在 Git 之外。来源和校验信息见[示例 provenance](docs/assets/pdf-examples/README.md)。_

![周六 post-live 双 PDF 流程](docs/diagrams/saturday-post-live-workflow.svg)

每周 Supervisor 使用 Astra Medium 完成翻译、两轮阅读稿审核和证道同行，并在 PDF QA 后启用 Context Pack 导出。同篇身份初始为 `unknown`；自动导出不等于人工批准。

这是当前更成熟的 post-live 路径。只有 source、人工批准的时间窗、阅读稿 QA、两个 PDF 以及两个 PDF QA 都存在并通过，才算完成。

关键文档：

- [稳定的 post-live 阅读版 PDF 工作流](docs/stable-post-live-reading-pdf-workflow.zh.md)
- [Codex 本地周末生产 runbook](docs/codex-local-production-runbook.zh.md)
- [证道生产 Supervisor Agent](docs/sermon-production-supervisor-agent.zh.md)

### B. 周日：从本地麦克风生成实时中文字幕

周日工作流在 MacBook 本地运行：浏览器麦克风采集、录音和事件持久化、本地英文 ASR、MiLMMT 英译中，以及单页大字号中文字幕。

![周日本地实时字幕流程](docs/diagrams/sunday-live-workflow.svg)

当前默认实现采用独立 MediaRecorder 恢复录音、16 kHz PCM WebSocket、Qwen3-ASR/MLX 与 Ollama 上的 MiLMMT Q8。不可变英文 final 先经过孤立虚词门控，再即时翻译；`readable_chunks` 保留前一句完整双语字幕。Firebase Hosting/Realtime Database 提供公网只读观看，LAN/SSE 作为独立退路。Gateway 重启可恢复同一 session、录音及观看身份，但字幕缺口会明确记录。

合并版本完成了 **60 分钟浏览器 WAV 回放**（20 分钟唯一音频循环三轮）：**1,287 个 ASR final → 1,287 次翻译 → 1,287 条操作页可读显示**。可读首显 P95 从音频段结束计算为 **1.776 秒**，从段开始计算为 **4.763 秒**。这是链路交付证据，不是翻译准确率、物理麦克风/手机或现场验收。详见[当前验收报告](experiments/local-live-poc/benchmarks/SUNDAY_READINESS_20260904.zh.md)。

**v4.1 可选试用：** 先用 [Sunday Live Captions.command](experiments/local-live-poc/Sunday%20Live%20Captions.command) 启动 POC，再于录音前选择 **v4.1 Q5 · 实验候选**。本机已有冻结模型包时，可从网页启动独立 MLX 服务。该候选尚未通过神学质量门，实验会话仅在本机显示与保存，LAN/Firebase 分享关闭。详见[安装条件、操作与恢复说明](experiments/local-live-poc/MILMMT_V41_LOCAL.zh.md)。

![本地运行、恢复存储与公网/LAN 观看架构](docs/diagrams/local-live-architecture.svg)

关键文档：

- [周六/周日完整工作流与延迟预算](docs/workflows/README.zh.md)
- [本地实时字幕 POC](experiments/local-live-poc/README.md)
- [本地实时字幕设计](experiments/local-live-poc/DESIGN.zh.md)

## 3. Discovery、缺口与下一步

[同行 iOS 原生客户端](apps/tongxing-ios/README.zh.md)已合入 `main`，仍属开发验证客户端；它复用已发布目录、音频和字幕，覆盖离线收听、系统音频控制、双语全文与短时麦克风听音定位。代码合入或开发构建不代表真机、TestFlight、现场或 App Store 验收。

### 已经证明的能力

| 方向 | 当前证据 |
|---|---|
| 周六 PDF 生产 | 工作流代码、测试、带日期的 QA 证据、人工确认证道时间窗和可恢复状态；生成 PDF 保持本地且被忽略 |
| 周日 live POC | 真实模型浏览器 WAV 回放、可读显示回执、恢复录音校验、手机视口与重连检查；现场门槛未闭合 |
| 周六到周日 context | exporter、builder/retriever、readiness、Gateway capability 上限已实现；Supervisor 在 PDF QA 后导出，同篇身份初始为 `unknown` |
| Replay 与 A/B | 冻结输入和 hash；真实 3 秒/6 秒 ASR 与有界翻译单位比较；候选均未升级默认 |
| v4.1 后训练接入 | POC 可选 Q5/MLX；45 秒原声文件回放得到 17 条英文和 17 条中文 final；网页录音及保存另行验证；质量门仍未通过 |
| 运行维护 | 一键启动/停止、运行身份、当前连接 drain、同会话恢复、有界公网发布器与 LAN 退路 |

### 正在探索和仍需补齐的门槛

- **周六生产桥接：** Supervisor 在双 PDF QA 后启用 `--export-sunday-context`。导出不代表允许现场注入；同篇确认、hash、有效期和审核状态共同决定 readiness。English-only 仅用于对齐，不改变冻结 A0 prompt。详见[Context Pack 契约](docs/saturday-to-sunday-context-pack-plan.zh.md)。
- **语义忠实度：** 专名、断句、否定、因果和经文关系仍需听音及人工双语校对。ASR Gold 门保持 fail-closed；本机已准备八组诊断听审材料，机器审核不等于 human Gold。
- **分段选择：** 保留 3 秒窗口、`translationUnitPolicy=legacy`、`content_words` 孤立虚词门控和 `contextPolicy=none`。加长窗口及有界语义合并都有改善与退化；后者只作为显式启用的评估代码。
- **故障恢复：** 实际 Gateway 重启测试保住独立录音，但有 1.6 秒 PCM gap、一个未结算在途 ASR 任务，以及 7.234 秒的新字幕更新间隔。恢复不等于字幕无损。
- **现场验收：** 实际麦克风/调音台、非讲话声音、实体手机 Wi-Fi/蜂窝网络和手机真实显示延迟仍需验证。公网标签页重连、横竖屏浏览器检查不能代替这些门槛。
- **资源上限：** 最新回放的 357 个录音窗口样本中 swap 为 0，起始和末尾缺测区间已单列。翻译进程 RSS 从 5,863.719 增至 9,664.609 MiB，最后十分钟仍增长；尚未证明平台或连续多场运行上限。
- **可选增强：** 真实每周 Pack 收益、其他本地 serving 和领域后训练继续独立评估；无 Pack 的 A0 主路径必须保持可用。

### 后训练方案

v4.1 候选已可在本地 POC 中选择；独立运行时保留录音恢复，并将模型身份绑定到每次会话。[接入验证报告](experiments/local-live-poc/benchmarks/MILMMT_V41_POC_INTEGRATION_20260905.zh.md) 分别记录文件回放与安静环境的网页录音检查；本轮没有验证语音翻译在浏览器中的实际显示、真实声学输入或现场可用性。

训练和质量验收继续与操作流程分开推进：

1. 从既有字幕、周六/周日经过审核的译文、术语修订和选定音频证据构建保留 provenance 的平行语料。
2. 按整篇 sermon 固定 train/dev/test，防止 segment 泄漏；只有人工批准的 `Gold` 数据可以进入 promotion 集合。
3. 用强 teacher 生成初译，再做独立双语 review；仅对高风险片段和固定抽样进行音频核验。
4. 对较小 student model 做 SFT/LoRA，并与 MiLMMT A0 比较术语、经文名称、忠实度、幻觉率和延迟。
5. 只有 frozen evaluation gate 通过才允许 promotion。Ollama 模型使用 `LOCAL_LIVE_OLLAMA_MODEL`；v4.1 MLX 实验模型通过独立固定适配器接入，在录音前显式选择。启动成功或代码合并都不改变默认模型。

其他架构、provider 对比、Cloud 实验、历史 realtime prototype 和部署笔记统一放在[文档索引](docs/README.zh.md)，不再挤进项目首页。
