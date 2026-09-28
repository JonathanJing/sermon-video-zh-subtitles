# 多语言生产四层接口

状态：本文是今后所有预制多语言生产的规范合同。四层名称保持不变；版本号按各接口演进，不能把 v1 Schema 当作 Production 周更的现行格式。2026-09-27 整篇已在 Production 使用 v3 catalog 与逐语言 v2 Release Package，并有 HTTP 收据；客户端和现场验收分别记录。可复用的 v3 周更组装／部署工具仍待完成，不能把本周的一次性 staging 当作自动化发布器。

现有双 PDF、中文配音和 `weekly.json` 发布工具在迁移期间作为 legacy adapter 保留。它们可以完成各自明确 scope，但只有四个正式包及其门禁均有证据时，才可报告 `workflowScope=four_layer_release`。周日实时字幕属于独立 `live_session`，不在现场强制生成这些预制包；若会后复用录音，应从 Layer 1 开始。

## 统一命名

全项目只使用下面四个生产层名称。审核、哈希、人工批准和验收是贯穿各层的门禁，不另算生产层。

| 层 | 中文名称 | English name | 唯一正式输出 |
|---|---|---|---|
| Layer 1 | 共享英文事实与锚点 | Shared English Source & Anchors | `English Source Package` / `sermon-english-source-package-v1` |
| Layer 2 | 目标语言文字 | Target-Language Text | `Target-Language Candidate` / `sermon-target-language-candidate-v2` |
| Layer 3 | 目标语言音频与同步 | Target-Language Audio & Synchronization | `Target-Language Audio Package` / `sermon-target-language-audio-package-v1` |
| Layer 4 | 多语言发布与播放 | Multilingual Delivery & Playback | 每个 `pageId + targetLocale` 一个 `Target-Language Release Package`；Production 周更使用 `sermon-target-language-release-package-v2` |

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

流程图可将各语言 Layer 2–3 分支汇入一个 Layer 4 发布阶段，便于显示同一次多语言发布的等待与整体进度。这是调度与界面上的汇合，**不是**合并正式输出：Layer 4 仍为每个 `pageId + targetLocale` 生成独立 Release Package，并逐语言记录 HTTP、设备与现场结果。是否等待全部语言由该次发布计划决定；不能把某次片段或周次的发布计划永久套用到以后每周。

- Layer 1 的 `downstreamInvalidationKey` 改变时，所有目标语言文字、音频和发布审核失效。
- Layer 2 的 `downstreamInvalidationKey` 改变时，只使同一 `targetLocale` 的音频和发布失效，不影响其他语言。
- Layer 3 改变时，只使同一语言的发布包失效，不回写或修改译文。
- Layer 4 只聚合已存在且 hash 匹配的资产；不得补翻译、重写音频或提升上游审核状态。

### 周更最少人工审核点

同一来源、策略和产物 hash 未变化时，复用已有批准；操作员不必按每个生产步骤重新回答。正式周更只安排以下内容判断，并把机器结构检查、逐组模型复核、文件哈希、解码、ASR 筛查和 HTTP 核验交给工具自动执行：

1. **Layer 1 一轮来源审核**：确定窗口，并确认英文完整性、词时间、句界和停顿；窗口批准与英文审核仍分别保存原有收据。来源或锚点变化才重审受影响范围。
2. **Layer 2 每个 locale 一次全文文字审核**：审核最终候选及经文、术语、否定、数字；页面显示文案准备好时在同一轮展示，仍保存独立的页面字段批准记录。可用 `review_target_language_candidate.py approve-batch` 将审核者明确的全文决定展开为原有逐组收据；有疑点时先按组修订并重新生成候选，不使用批量批准。经文边界、机器初译、独立复核和页面文案不另设重复的聊天批准问题。
3. **Layer 3 每个 locale 一次正式整轨听审**：听完 1 倍速音轨并对照视频检查同步，同时裁决 ASR 标出的组；三语可在同一轮分别给出决定，收据仍按 locale 保存。已登记且授权范围、checkpoint、adapter 与 locale 能力均未变化的音色，不每周重做短样／长句能力听审；首次扩展到新语言、模型或用途时仍需能力证据。文字变动只重做该语言的音轨和听审。
4. **Layer 4 不重复内容审核**：本次发布计划中的各语言资产和页面字段均与已审 hash 一致后，自动预检目标站点、发布清单、文件和 HTTP。已有明确发布授权时直接执行对应环境发布；受影响的内容或绑定发生变化才重审。音频或纯文字交付遵守该周已经批准的计划及客户端能力，不追加无关审批。

这里的“批量”只减少填写动作，不把模型结果升级为人工批准，也不允许跳过完整阅读、完整听播、ASR 疑点裁决或来源失效检查。设备与现场验收仍单列。

### 审核与执行解耦

人工审核是**正式资格门禁**，不是整个工作进程的全局锁。每层分别保存不可变候选和独立、绑定 hash 的审核收据；审核未回时保留 `pending`，可以继续不依赖该决定的计算、风险清单和审核页面。机器复核通过、人审待定的译文还可进入独立的 `preview_only` 单元配音通道；它不是正式 Layer 3 producer，也没有 speech job、Audio Package 或发布资格。待正式文字审核通过后，正式 renderer 才能逐单元验证并复用同身份原始音频；不一致单元重新合成，完整排程和听审照常执行。详见[层内解耦与预生成流程](multilingual-intralayer-review-decoupling.zh.md)。

| 等待的结果 | 可以并行准备 | 不可越过的正式门禁 |
| --- | --- | --- |
| Layer 1 英文审核 | 媒体完整性、词对齐、锚点、机器裁判、Layer 2 shadow 候选 | 正式 Layer 2 只接收 `ready_for_translation` |
| 某 locale 的 Layer 2 文字审核 | 其他 locale 的 Layer 2；本 locale 审核表、机器风险定位、语音资源预热，以及机器复核通过后的 `preview_only` 单元配音 | 本 locale 正式 speech job 需 `human_translation_approved` 和独立同 hash 收据 |
| 某 locale 的 Layer 3 整轨听审 | 其他 locale 的 Layer 3；本 locale 解码、ASR 筛查、排程及供听审的候选音轨 | 带正式音频的 Release Package 需 `human_reviewed` Audio Package 和全文／同步收据 |
| Layer 4 发布后设备／现场验收 | HTTP 核验完成后独立安排设备及现场检查 | HTTP、设备、现场状态分别记录，不互相推断 |

调度以 `sourceHash + targetLocale + policyHash + candidateHash` 为任务身份。某语言的审核未回只挂起该语言的后继正式任务，不阻塞其他语言；Layer 1 身份变化使所有语言失效，Layer 2/3 变化只使本语言下游失效。合同允许显式 `audio_unavailable` 的文字页，但现有 Production Web 桥接只支持 `zh-Hans`、`ko`、`es` 且要求正式音轨；纯文字页或新语言须先有两端客户端兼容证据，不能只改目录宣称可用。

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

输入：已批准的目标语言文字包、同 locale 的音频包（发布计划允许时可为 `audio_unavailable`）、经批准的口播文字身份、页面元数据批准、来源身份及显式发布文件清单。若未另写短稿，口播文字身份仍指向批准的全文候选；Layer 4 不修改文字、音轨或上游审核状态。

处理：按 `pageId + targetLocale` 聚合、检查上游 hash／审核收据并构建 allowlist。`interfaceLocale` 是用户客户端偏好，不由发布包替用户切换；`contentLocale` 与 `audioLocale` 分别对应实际文字和音轨，不静默借用另一语言。新周次在当前正式站完整快照上**只追加**页面和资产，保留 legacy `weekly.json`、旧 catalog、历史页面、反馈功能和仍被引用的文件；同 page ID 的来源身份变动须新建 ID。先上传内容、音频、字幕、英文对照、定位索引及逐语言 Release，最后更新唯一可变入口 `/multilingual-v3.json`。发布前后对照 catalog 与文件清单，拒绝意外删除、覆盖旧 hash 或回退到 v1/v2 目录。

输出：每种语言一个 [Target-Language Release Package v2](../schemas/sermon-target-language-release-package-v2.schema.json)，再汇总成 [Multilingual Catalog v3](../schemas/sermon-multilingual-catalog-v3.schema.json)。v2 包必须绑定 Layer 2 全文、已批准口播稿和 Layer 3 Audio Package 的 hash；实际资产也须匹配。v1 Release 与 v2 Catalog 继续供历史／Dev 读取，不可覆盖到正式 v3 路径。公开包不得复制含本机绝对路径、凭据或私有收据的上游原件。

现行 Production 三语完整视频周更采用固定的 [`three_locale_full_video_v1` 文件数合同](tongxing-weekly-release.zh.md#正式三语周更文件数合同)：21 个新周资源加 1 个更新的 v3 catalog，总计 22 个 Hosting 文件。此合同只约束本周内容增量；既有站点完整快照、App 代码发布及 Dev 模拟流程分别计数。其他语言、纯文字发行或 bucket 视频须使用另一个经客户端验收的版本化发布配置，不把缺失资产凑成 22 个。

### 每周 App 内容合同与刷新门槛

1. v3 catalog 的 `defaultPageId` 指向本周 `pages[].id`；本周页 `title` 使用默认内容语言已批准的「系列名 · 本篇标题」，并与该语言 `content/<pageId>/<locale>.json` 的 `series`、`title` 一致。每个 target 的 `releasePackageUrl` 固定为同源 `/releases-v2/<pageId>/<locale>.json`，其 SHA 指向不可变 v2 包。页面、内容、字幕、音轨和完整原视频均为本周同一来源；页面须在 App 内打开，独立 HTML URL 只能是兼容入口，不能代替 App 的本周页。
2. 目录只声明真实可用的语言和能力。正式音轨需要已听审 Layer 3 与可 Range 读取的同语言音频；全文字幕、英文对照、现场声音定位若列为本周交付，就必须发布各自 sidecar、验证身份绑定与公开 GET。缺少 sidecar 时不能静默把对应功能标为可用。Web 与 iOS 共同支持的现行周更范围是中、韩、西正式音轨；扩展语言／文字版先改客户端并验收。
3. `/multilingual-v3.json` 必须能在刷新时取到最新版本，明确设置 `Cache-Control: no-store`；逐语言 Release 及资产按路径／hash 校验缓存。客户端读取新目录失败时保留上一次已验证内容，显示刷新失败，不把网络错误说成“未发布”。切换页面不覆盖正在播放的旧周次；刷新后本周页必须在 **Firebase App 内的选页入口**和 **已安装 iOS App 的选页入口**出现，选择后在原 App 内加载本周三语页面，无须每周发新版 IPA 或让用户另开网页。iOS 显式刷新目录、Web 重新加载 App 是当前可执行入口；若要求 Web 内按钮或返回前台自动刷新，须先实现并单独验收。
4. 发布收据分别记录：完整站点基线与变更差异、catalog 旧／新 hash、逐语言 Release 和每个公开资产的 GET／SHA、MP3 HTTP 206／Range、Web 刷新选页与播放、iOS 同一已安装版本刷新选页与播放、设备验收、现场验收。`published_http_verified` 只表示线上文件通过；客户端与现场未测时各记 `not_run`。回滚只切换已验证的 catalog 指针，保留可恢复的旧资产。

## 当前实现边界

- Layer 1：确定性锚点和机器裁判代码可运行；无机器裁判且无正式英文人工收据的干净 shadow 输入停在 `waiting_machine_judge`。机器裁判通过只允许 Layer 2 shadow，正式 `ready_for_translation` 仍需英文人工收据。
- Layer 2：中文 legacy runner 可工作；`zh-Hans`、`ko`、`es`、`vi` 有同源六句 shadow 候选及机器复核。通用模型执行器、语言插件和候选准入器已实现，新生产策略采用 Astra 初译与 Sol 逐组独立复核；每次正式运行仍需就绪的来源、冻结 policy、逐组机器证据及独立人工批准，代码可运行不等于整篇生产验收。
- Layer 3：中文 legacy TTS／同步及三语正式 renderer 可工作；整篇音轨的听审、同步与批准以各周实际收据为准，不由本合同自动继承。
- Layer 4：2026-09-27 Production 已发布 v3 目录、逐语言 v2 包及整篇三语资产并通过 HTTP／Range 核验。本周 Web 桥接实现仍在忽略的 staging 产物，可复用的 v3 组装／发布／核验脚本尚未入库；已有 iOS 版本可主动刷新 v3 目录，Web 可通过重新加载读取目录，但跨周同版本设备验收仍需单独做。现有 v2／legacy CLI 不能作为 v3 周更成功证据。
- Canonical English Content 是从英文事实派生的页面内容输入，可以作为 English Source Package 的可选绑定；它不是英文逐字稿，也不能替代 Layer 1 审核。
