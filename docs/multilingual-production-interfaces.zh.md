# 多语言生产四层接口

状态：本文是今后所有预制多语言生产的规范合同。四个层间接口名称和 JSON Schema 已冻结为 v1；Layer 1 已有确定性生成器和独立机器裁判，机器裁判不授予生产翻译资格。2026-09-20 的 2:58 三语样片已有正式 Layer 1–4 包、全文人工审核和 Dev HTTP 收据；当前周更整篇与 Production 尚未通过。可用代码路径及缺口见[合并 main 前检查](multilingual-production-premerge-2026-09-23.zh.md)。

现有双 PDF、中文配音和 `weekly.json` 发布工具在迁移期间作为 legacy adapter 保留。它们可以完成各自明确 scope，但只有四个正式包及其门禁均有证据时，才可报告 `workflowScope=four_layer_release`。周日实时字幕属于独立 `live_session`，不在现场强制生成这些预制包；若会后复用录音，应从 Layer 1 开始。

## 统一命名

全项目只使用下面四个生产层名称。审核、哈希、人工批准和验收是贯穿各层的门禁，不另算生产层。

| 层 | 中文名称 | English name | 唯一正式输出 |
|---|---|---|---|
| Layer 1 | 共享英文事实与锚点 | Shared English Source & Anchors | `English Source Package` / `sermon-english-source-package-v1` |
| Layer 2 | 目标语言文字 | Target-Language Text | `Target-Language Candidate` / `sermon-target-language-candidate-v2` |
| Layer 3 | 目标语言音频与同步 | Target-Language Audio & Synchronization | `Target-Language Audio Package` / `sermon-target-language-audio-package-v1` |
| Layer 4 | 多语言发布与播放 | Multilingual Delivery & Playback | `Target-Language Release Package` / `sermon-target-language-release-package-v1` |

`targetLocale` 一律使用 BCP 47：英文事实源为 `en`，简体中文内容为 `zh-Hans`，韩语为 `ko`，西班牙语为 `es`，越南语为 `vi`。现有 Web 界面使用的 `zh-CN` 是 legacy interface-locale adapter，不得写入新的内容、音频或发布包。

## 数据流与失效规则

```text
English Source Package
  ├─ anchorManifestJsonSha256 ──> Target-Language Candidate (zh-Hans)
  ├─ anchorManifestJsonSha256 ──> Target-Language Candidate (ko)
  └─ anchorManifestJsonSha256 ──> Target-Language Candidate (es)

Target-Language Candidate
  └─ candidate hash ────────────> Target-Language Speech Job
                                  └─ measured artifacts ─> Target-Language Audio Package

Target-Language Candidate + Target-Language Audio Package
  └─────────────────────────────> Target-Language Release Package
```

- Layer 1 的 `downstreamInvalidationKey` 改变时，所有目标语言文字、音频和发布审核失效。
- Layer 2 的 `downstreamInvalidationKey` 改变时，只使同一 `targetLocale` 的音频和发布失效，不影响其他语言。
- Layer 3 改变时，只使同一语言的发布包失效，不回写或修改译文。
- Layer 4 只聚合已存在且 hash 匹配的资产；不得补翻译、重写音频或提升上游审核状态。

### 周更最少人工审核点

同一来源、策略和产物 hash 未变化时，复用已有批准；操作员不必按每个生产步骤重新回答。正式周更只安排以下内容判断，并把机器结构检查、逐组模型复核、文件哈希、解码、ASR 筛查和 HTTP 核验交给工具自动执行：

1. **Layer 1 一轮来源审核**：确定窗口，并确认英文完整性、词时间、句界和停顿；窗口批准与英文审核仍分别保存原有收据。来源或锚点变化才重审受影响范围。
2. **Layer 2 每个 locale 一次全文文字审核**：审核最终候选及经文、术语、否定、数字；页面显示文案准备好时在同一轮展示，仍保存独立的页面字段批准记录。可用 `review_target_language_candidate.py approve-batch` 将审核者明确的全文决定展开为原有逐组收据；有疑点时先按组修订并重新生成候选，不使用批量批准。经文边界、机器初译、独立复核和页面文案不另设重复的聊天批准问题。
3. **Layer 3 每个 locale 一次正式整轨听审**：听完 1 倍速音轨并对照视频检查同步，同时裁决 ASR 标出的组；三语可在同一轮分别给出决定，收据仍按 locale 保存。已登记且授权范围、checkpoint、adapter 与 locale 能力均未变化的音色，不每周重做短样／长句能力听审；首次扩展到新语言、模型或用途时仍需能力证据。文字变动只重做该语言的音轨和听审。
4. **Layer 4 不重复内容审核**：三语资产和页面字段均与已审 hash 一致后，自动预检目标站点、发布清单、文件和 HTTP。已有明确发布授权时直接执行相应 Dev 发布；Production 按其独立授权和发布窗口执行。新三语周更仍按本次约定等待三条正式音轨齐全。

这里的“批量”只减少填写动作，不把模型结果升级为人工批准，也不允许跳过完整阅读、完整听播、ASR 疑点裁决或来源失效检查。设备与现场验收仍单列。

### 审核与执行解耦

人工审核是**正式资格门禁**，不是整个工作进程的全局锁。每层分别保存不可变候选和独立、绑定 hash 的审核收据；审核未回时保留 `pending`，可以继续不依赖该决定的计算、风险清单和审核页面。机器复核通过、人审待定的译文还可进入独立的 `preview_only` 单元配音通道；它不是正式 Layer 3 producer，也没有 speech job、Audio Package 或发布资格。待正式文字审核通过后，正式 renderer 才能逐单元验证并复用同身份原始音频；不一致单元重新合成，完整排程和听审照常执行。详见[层内解耦与预生成流程](multilingual-intralayer-review-decoupling.zh.md)。

| 等待的结果 | 可以并行准备 | 不可越过的正式门禁 |
| --- | --- | --- |
| Layer 1 英文审核 | 媒体完整性、词对齐、锚点、机器裁判、Layer 2 shadow 候选 | 正式 Layer 2 只接收 `ready_for_translation` |
| 某 locale 的 Layer 2 文字审核 | 其他 locale 的 Layer 2；本 locale 审核表、机器风险定位、语音资源预热，以及机器复核通过后的 `preview_only` 单元配音 | 本 locale 正式 speech job 需 `human_translation_approved` 和独立同 hash 收据 |
| 某 locale 的 Layer 3 整轨听审 | 其他 locale 的 Layer 3；本 locale 解码、ASR 筛查、排程及供听审的候选音轨 | 带正式音频的 Release Package 需 `human_reviewed` Audio Package 和全文／同步收据 |
| Layer 4 发布后设备／现场验收 | HTTP 核验完成后独立安排设备及现场检查 | HTTP、设备、现场状态分别记录，不互相推断 |

调度以 `sourceHash + targetLocale + policyHash + candidateHash` 为任务身份。某语言的审核未回只挂起该语言的后继正式任务，不阻塞其他语言；Layer 1 身份变化使所有语言失效，Layer 2/3 变化只使本语言下游失效。本项目本次三语 Dev 发布在 Layer 4 汇合：中、韩、西三条正式音轨都通过后才更新公开页面；合同允许 `audio_unavailable` 的文字页，但不能用来绕开这次明确的三语音轨要求。

以上是**目前的整包门禁**，尚未实现“同一语言内某段已审即可独立进入下一层”。单段待改仍会挡住本 locale 的正式 speech job。第一阶段代码加入段级人审收据及旧音频单元的显式哈希复用，但正式聚合仍要求全部段获批，新整轨仍需完整排程与听审；见[四层内解耦设计与当前边界](multilingual-intralayer-review-decoupling.zh.md)。

## Layer 1：共享英文事实与锚点

输入：授权媒体身份、人工批准的证道范围、冻结英文转写、一个选定的词级对齐结果，以及可选的英文人工审核收据。

处理：

1. 验证英文转写与 aligned segments 的内容 hash。
2. 记录唯一 `alignment.provider`；MFA 和 Qwen ForcedAligner 可以做 A/B，但同一个正式包不能混合两条词时间轴。
3. 生成 `clause_stable_v2` 父句／子锚；只在标点或可听停顿处分句。
4. 绑定英文完整性、词级对齐、句界和停顿审核；任何来源改动产生新的失效 key。

输出 schema：[English Source Package](../schemas/sermon-english-source-package-v1.schema.json)。人工批准输入 schema：[English Source Review](../schemas/sermon-english-source-review-v1.schema.json)。底层锚点继续使用 [clause-stable v2 anchor manifest](../schemas/sermon-sentence-anchor-manifest-v2.schema.json)。

状态含义：

- `blocked`：锚点或对齐有未解决问题，不得调用翻译模型。
- `candidate_ready_for_translation`：结构检查和绑定的逐句机器裁判通过，可用于 Layer 2 shadow 开发，但仍缺生产所需的来源或人工门禁。干净锚点在机器裁判前的 shadow 收据为 `waiting_machine_judge`。
- `ready_for_translation`：媒体身份、批准范围和四项英文人工检查均已绑定，允许正式 Layer 2 消费。

当前生成器：[build_english_source_package.py](../scripts/build_english_source_package.py)；[独立机器裁判](../scripts/judge_english_source_for_translation.py)只产生 `humanApproval=false`、`productionTranslationEligible=false` 的 shadow 收据。未来周入口 [prepare_sentence_interpretation_shadow.py](../scripts/prepare_sentence_interpretation_shadow.py) 同时写出 `anchor-manifest.json` 和 `english-source-package.json`；`run_post_live_subtitle_generation.py` 可用 `--sentence-interpretation-english-review` 绑定人工审核收据并重跑 Layer 1。这一层不写入中文 prompt，也不生成目标语言文字。

## Layer 2：目标语言文字

输入：一个 `ready_for_translation` 的 English Source Package、`targetLocale` 和冻结的翻译策略 hash（模型、prompt、术语表、经文版本及排版规则）。

处理：只翻译目标 `sourceUnitIds`，上下文仅用于消歧；初译和独立复核使用不同 request；通用语义检查与语言专属检查分开；人工审核独立记录。

输出 schema：[Target-Language Candidate](../schemas/sermon-target-language-candidate-v2.schema.json)。一个文件只承载一个 locale。中文、韩语和西班牙语不得写进同一个对象，也不得通过中文回译产生其他语言。

现有 `sermon-sentence-interpretation-candidate-v1` 是把中文和音频耦合在一起的 legacy 合同；迁移时由 `zh-Hans` adapter 转成新文字包，历史产物保持可读。

## Layer 3：目标语言音频与同步

输入：一个 `human_translation_approved` Target-Language Candidate、绑定其完整 hash 和每组决定的[独立人审收据](../schemas/sermon-target-language-human-review-receipt-v1.schema.json)、支持相同 `targetLocale` 的授权 voice/checkpoint、同一个 English Source Package 锚点以及自然语速策略。准备阶段使用 [Target-Language Speech Job v2](../schemas/sermon-target-language-speech-job-v2.schema.json) 锁定人审收据、注册表、adapter 和输出目录；v1 仅保留为旧 shadow 合同，不授予新合成资格。

长期讲员 checkpoint、授权范围与各语言能力由 [Speaker Voice Registry](multilingual-speaker-voice-registry.zh.md) 独立管理；训练不算第五层，也不随每周内容自动重跑。Layer 1 完成后，各 locale 的 Layer 2 并行；某 locale 通过文字门禁后即可独立进入本 locale 的 Layer 3，不等待其他语言。

处理：以目标语言的完整自然句子或已审核的完整分句为 TTS 单元，每个单元一次自然语速合成，不在词组内部拼接，不为匹配英文总时长强制变速／拉伸；然后完整解码、回转写筛查、实测时长、确定性滚动排程、字幕 cue、人耳全文听审和同视频 1 倍速检查。Layer 1 的英文词级停顿是源语证据，不自动成为目标语言的合成切点；如果目标语言与源时间轴不合，记录局部偏差并回到译文、自然句界或候选语音审核，不靠句内碎片补静音掩盖。ASR 筛查不等于人工听审，听感通过也不等于同步通过。

输出 schema：[Target-Language Audio Package](../schemas/sermon-target-language-audio-package-v1.schema.json)。每个要发布的 locale 都必须留下这一层的包；`audio_unavailable` 是合法状态，可进入纯文字发布，不得借用另一语言音轨冒充当前 locale。

## Layer 4：多语言发布与播放

输入：目标语言文字包，以及同 locale 的音频包（可以为 `audio_unavailable`）；页面来源身份和显式发布文件清单。

处理：按 `pageId + targetLocale` 聚合，分别记录 `interfaceLocale`、`contentLocale` 和 `audioLocale`，构建 allowlist，验证文件 hash、HTTP、Range 和客户端播放。

输出 schema：[Target-Language Release Package](../schemas/sermon-target-language-release-package-v1.schema.json)。schema 中可空的音频包 hash 只用于迁移期 legacy 兼容；新的四层生产须绑定 Layer 3 包。HTTP 通过、设备通过和现场通过是三个独立状态。

## 当前实现边界

- Layer 1：确定性锚点和机器裁判代码可运行；无机器裁判且无正式英文人工收据的干净 shadow 输入停在 `waiting_machine_judge`。机器裁判通过只允许 Layer 2 shadow，正式 `ready_for_translation` 仍需英文人工收据。
- Layer 2：中文 legacy runner 可工作；`zh-Hans`、`ko`、`es`、`vi` 有同源六句 shadow 候选及机器复核。通用模型执行器、语言插件和候选准入器已实现，新生产策略采用 Astra 初译与 Sol 逐组独立复核；每次正式运行仍需就绪的来源、冻结 policy、逐组机器证据及独立人工批准，代码可运行不等于整篇生产验收。
- Layer 3：中文 legacy TTS／同步可工作；9 月 20 日样片的中、韩、西正式 renderer、实测同步、ASR 筛查和 Audio Package producer 已通过对应人工门禁。整篇周更尚未实跑；新的 MP3 输出仅有合成测试，仍需逐语言完整听审及同步批准。
- Layer 4：Dev 样片已有正式同语言 Release Package、三语发布与 HTTP 收据；Production 的完整旧站点叠加、首页替换、部署前基线和发布后核验已有候选代码及本地模拟器验证。实际 Production 发布、设备／现场验收和周更整篇仍未完成。
- Canonical English Content 是从英文事实派生的页面内容输入，可以作为 English Source Package 的可选绑定；它不是英文逐字稿，也不能替代 Layer 1 审核。
