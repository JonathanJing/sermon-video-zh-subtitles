# 多语言生产四层接口

正文核查：2026-10-22（`feat/deepseek-flash-layer2@21b83a97`）。新 canonical Layer 2 以[2026-10-21 起的运行时策略](production-model-runtime-policy.zh.md)为准：默认 DeepSeek Flash low 初译 / high 独立复核；Sol 6.1 high / medium 与 Claude Opus 5.5 为显式回退，不自动切换。Supervisor 默认 Codex CLI / Luna medium fast。现有 run 保留原模型、后端、凭据、缓存及未决调用身份；DeepSeek 默认尚无 canonical 真实运行证据，不能写为已生产验收。

状态：本文是预制多语言生产的规范合同。四层名称保持不变；版本号按接口演进。2026-09-27 的 Production v3 catalog、逐语言 v2 Release 与 HTTP 收据保留原日期。当前代码另支持 release v3 / v4、catalog v4 / v5 及 family 投影，入口与实施边界见下文；代码、发布、客户端和现场证据分别记录。

现有双 PDF、中文配音和 `weekly.json` 发布工具在迁移期间作为 legacy adapter 保留。它们可以完成各自明确 scope，但只有四个正式包及其门禁均有证据时，才可报告 `workflowScope=four_layer_release`。周日实时字幕属于独立 `live_session`，不在现场强制生成这些预制包；若会后复用录音，应从 Layer 1 开始。

## 统一命名

全项目只使用下面四个生产层名称。审核、哈希、人工批准和验收是贯穿各层的门禁，不另算生产层。

| 层 | 中文名称 | English name | 唯一正式输出 |
|---|---|---|---|
| Layer 1 | 共享英文事实与锚点 | Shared English Source & Anchors | `English Source Package` / `sermon-english-source-package-v1` |
| Layer 2 | 目标语言文字 | Target-Language Text | `Target-Language Candidate` / `sermon-target-language-candidate-v2` |
| Layer 3 | 目标语言音频与同步 | Target-Language Audio & Synchronization | `Target-Language Audio Package` / `sermon-target-language-audio-package-v1` |
| Layer 4 | 多语言发布与播放 | Multilingual Delivery & Playback | 每个 `pageId + targetLocale` 一个 `Target-Language Release Package`；按实际合同使用 release v2 / v3 / v4，不能用 URL 目录名推断 schema |

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

**机器质检豁免（2026-10-06 决定，接线中）：** 中文、韩语、西语的第 2、3 项改为机器质检通过后自动发布，人工改为发布后抽查。每句最多自动修复 4 次；音频仍不过关的句子只显示字幕；不配音的句子超过 5% 时，该语言改为只发文字。豁免收据保持 `humanApproval=false`，并要求当前 QC 代码有有效的注错校准。检查组件、规则与尚未接上的门禁见[机器质检豁免](machine-quality-waiver.zh.md)。已接上：译文豁免收据可以代替人工译文审核进入第 3 层（speech job v3），试听豁免收据可以代替人工试听通过 `sermon_unified` 审核门（状态记为 `waived`，不是 `approved`）。第 4 层也已接上：用了豁免的语言写成 release v4（`machine_checked` 状态、逐项审核依据和披露文案），目录同时写 catalog v4 与作为人工投影的 v3；网页和 iOS 先读 v5，再回退 v4 / v3；按实际 target 显示“机器质检”，不显示人工批准。

### 审核与执行解耦

人工审核是**正式资格门禁**，不是整个工作进程的全局锁。每层分别保存不可变候选和独立、绑定 hash 的审核收据；审核未回时保留 `pending`，可以继续不依赖该决定的计算、风险清单和审核页面。机器复核通过、人审待定的译文还可进入独立的 `preview_only` 单元配音通道；它不是正式 Layer 3 producer，也没有 speech job、Audio Package 或发布资格。待正式文字审核通过后，正式 renderer 才能逐单元验证并复用同身份原始音频；不一致单元重新合成，完整排程和听审照常执行。详见[层内解耦与预生成流程](multilingual-intralayer-review-decoupling.zh.md)。

| 等待的结果 | 可以并行准备 | 不可越过的正式门禁 |
| --- | --- | --- |
| Layer 1 英文审核 | 媒体完整性、词对齐、锚点、机器裁判、Layer 2 shadow 候选 | 正式 Layer 2 只接收 `ready_for_translation` |
| 某 locale 的 Layer 2 文字审核 | 其他 locale 的 Layer 2；本 locale 审核表、机器风险定位、语音资源预热，以及机器复核通过后的 `preview_only` 单元配音 | 本 locale 正式 speech job 需 `human_translation_approved` 和独立同 hash 收据 |
| 某 locale 的 Layer 3 整轨听审 | 其他 locale 的 Layer 3；本 locale 解码、ASR 筛查、排程及供听审的候选音轨 | 带正式音频的 Release Package 需 `human_reviewed` Audio Package 和全文／同步收据；用试听豁免时改为 release v4 的 `audioStatus=machine_checked` |
| Layer 4 发布后设备／现场验收 | HTTP 核验完成后独立安排设备及现场检查 | HTTP、设备、现场状态分别记录，不互相推断 |

调度以 `sourceHash + targetLocale + policyHash + candidateHash` 为任务身份。某语言的审核未回只挂起该语言的后继正式任务，不为其他语言新增审批依赖；Layer 1 身份变化使所有语言失效，Layer 2/3 变化只使本语言下游失效。审批依赖独立不等于运行资源完全隔离：[当前 canonical Layer 2 controller](canonical-layer2-controller.zh.md) v1 同一 production run 至多一个 active locale；v3 / v7 可冻结 `maxActiveLocales=1–3`、`groupWorkers=1–16`，周更默认以[运行配置](weekly-run-profile.zh.md)为准；uncertain owner 在 reconciliation 前仍占名额。表中的并行准备须遵守实际 producer 的容量；发布仍遵守该次 release plan 的多语言汇合条件。本项只描述已有配置能力，不改变冻结 run 的容量或授权。合同允许显式 `audio_unavailable` 的文字页，但现有 Production Web 桥接只支持 `zh-Hans`、`ko`、`es` 且要求正式音轨；纯文字页或新语言须先有两端客户端兼容证据，不能只改目录宣称可用。

以上是**目前的整包门禁**，尚未实现“同一语言内某段已审即可独立进入下一层”。单段待改仍会挡住本 locale 的正式 speech job。第一阶段代码加入段级人审收据及旧音频单元的显式哈希复用，但正式聚合仍要求全部段获批，新整轨仍需完整排程与听审；见[四层内解耦设计与当前边界](multilingual-intralayer-review-decoupling.zh.md)。

## Layer 1：共享英文事实与锚点

输入：授权媒体身份、人工批准的证道范围、冻结英文转写、一个选定的词级对齐结果，以及可选的英文人工审核收据。

处理：

1. 验证英文转写与 aligned segments 的内容 hash。
2. 记录唯一 `alignment.provider`；MFA 和 Qwen ForcedAligner 可以做 A/B，但同一个正式包不能混合两条词时间轴。
3. 生成 `clause_stable_v3` 父句／子锚（拆分规则同 v2，单元按首词词号编号，前面句子多拆不会让后面单元改号；已有运行保持 v2）；只在标点或可听停顿处分句。
4. 绑定英文完整性、词级对齐、句界和停顿审核；任何来源改动产生新的失效 key。

输出 schema：[English Source Package](../schemas/sermon-english-source-package-v1.schema.json)。人工批准输入 schema：[English Source Review](../schemas/sermon-english-source-review-v1.schema.json)。底层锚点继续使用 [clause-stable v2 anchor manifest](../schemas/sermon-sentence-anchor-manifest-v2.schema.json)。

状态含义：

- `blocked`：锚点或对齐有未解决问题，不得调用翻译模型。
- `candidate_ready_for_translation`：结构检查和绑定的逐句机器裁判通过，可用于 Layer 2 shadow 开发，但仍缺生产所需的来源或人工门禁。干净锚点在机器裁判前的 shadow 收据为 `waiting_machine_judge`。
- `ready_for_translation`：媒体身份、批准范围和四项英文人工检查均已绑定，允许正式 Layer 2 消费。

当前生成器：[english_source_package.py](../packages/production/src/tongxing_production/source/english_source_package.py)；[独立机器裁判](../packages/production/src/tongxing_production/source/english_source_judge.py)只产生 `humanApproval=false`、`productionTranslationEligible=false` 的 shadow 收据。未来周入口 [prepare_sentence_interpretation_shadow.py](../packages/production/src/tongxing_production/source/sentence_interpretation_shadow.py) 同时写出 `anchor-manifest.json` 和 `english-source-package.json`；`run_post_live_subtitle_generation.py` 可用 `--sentence-interpretation-english-review` 绑定人工审核收据并重跑 Layer 1。这一层不写入中文 prompt，也不生成目标语言文字。

## Layer 2：目标语言文字

输入：一个 `ready_for_translation` 的 English Source Package、`targetLocale` 和冻结的翻译策略 hash（模型、prompt、术语表、经文版本及排版规则）。

处理：只翻译目标 `sourceUnitIds`，上下文仅用于消歧；初译和独立复核使用不同 request；通用语义检查与语言专属检查分开；人工审核独立记录。

输出 schema：[Target-Language Candidate](../schemas/sermon-target-language-candidate-v2.schema.json)。一个文件只承载一个 locale。中文、韩语和西班牙语不得写进同一个对象，也不得通过中文回译产生其他语言。

现有 `sermon-sentence-interpretation-candidate-v1` 是把中文和音频耦合在一起的 legacy 合同；迁移时由 `zh-Hans` adapter 转成新文字包，历史产物保持可读。

## Layer 3：目标语言音频与同步

输入：一个 `human_translation_approved` Target-Language Candidate、绑定其完整 hash 和每组决定的[独立人审收据](../schemas/sermon-target-language-human-review-receipt-v1.schema.json)、支持相同 `targetLocale` 的授权 voice/checkpoint、同一个 English Source Package 锚点以及自然语速策略。准备阶段使用 [Target-Language Speech Job v2](../schemas/sermon-target-language-speech-job-v2.schema.json) 锁定人审收据、注册表、adapter 和输出目录；v1 仅保留为旧 shadow 合同，不授予新合成资格。

长期讲员 checkpoint、授权范围与各语言能力由 [Speaker Voice Registry](multilingual-speaker-voice-registry.zh.md) 独立管理；训练不算第五层，也不随每周内容自动重跑。Layer 1 完成后，各 locale 的 Layer 2 审批依赖独立，实际派发遵守 producer 容量（v1 为一个 active locale；v3 / v7 按冻结配置允许 1–3 个）；某 locale 通过文字门禁后即可独立进入本 locale 的 Layer 3，不等待其他语言。

处理：以目标语言的完整自然句子或已审核的完整分句为 TTS 单元，每个单元一次自然语速合成，不在词组内部拼接，不为匹配英文总时长强制变速／拉伸；然后完整解码、回转写筛查、实测时长、确定性滚动排程、字幕 cue、人耳全文听审和同视频 1 倍速检查。Layer 1 的英文词级停顿是源语证据，不自动成为目标语言的合成切点；如果目标语言与源时间轴不合，记录局部偏差并回到译文、自然句界或候选语音审核，不靠句内碎片补静音掩盖。ASR 筛查不等于人工听审，听感通过也不等于同步通过。

输出 schema：[Target-Language Audio Package](../schemas/sermon-target-language-audio-package-v1.schema.json)。每个要发布的 locale 都必须留下这一层的包；`audio_unavailable` 是合法状态，可进入纯文字发布，不得借用另一语言音轨冒充当前 locale。

## Layer 4：多语言发布与播放

输入：已批准的目标语言文字包、同 locale 的音频包（发布计划允许时可为 `audio_unavailable`）、经批准的口播文字身份、页面元数据批准、来源身份及显式发布文件清单。若未另写短稿，口播文字身份仍指向批准的全文候选；Layer 4 不修改文字、音轨或上游审核状态。

处理：按 `pageId + targetLocale` 聚合、检查上游 hash／审核收据并构建 allowlist。`interfaceLocale` 是用户客户端偏好，不由发布包替用户切换；`contentLocale` 与 `audioLocale` 分别对应实际文字和音轨，不静默借用另一语言。新周次在当前正式站完整快照上**只追加**页面和资产，保留 legacy `weekly.json`、旧 catalog、历史页面、反馈功能和仍被引用的文件；同 page ID 的来源身份变动须新建 ID。先上传内容、音频、字幕、英文对照、定位索引及逐语言 Release，最后发布适用的 `/multilingual-v5.json`、`/multilingual-v4.json` 与 `/multilingual-v3.json` 目录及兼容投影；family 发布按同一 Hosting version 原子更新并回读三份目录。发布前后对照 catalog 与文件清单，拒绝意外删除、覆盖旧 hash 或回退到 v1/v2 目录。

输出：每种语言一个 Release Package，按版本绑定同 locale 的文字、音频、学习产物与审核依据；公开包不得复制本机绝对路径、凭据或私有收据。

| 接口 | 当前合同与兼容范围 |
| --- | --- |
| [release v2](../schemas/sermon-target-language-release-package-v2.schema.json) / [v3](../schemas/sermon-target-language-release-package-v3.schema.json) | v2 绑定全文、口播稿和 Audio Package；v3 增加四产物封存。两者都可位于 `/releases-v2/<editionId>/<locale>.json`，目录名是兼容路由 |
| [release v4](../schemas/sermon-target-language-release-package-v4.schema.json) | 机器质检豁免路径，位于 `/releases-v4/`；保留 `humanApproval=false`、审核依据与披露 |
| [catalog v3](../schemas/sermon-multilingual-catalog-v3.schema.json) / [v4](../schemas/sermon-multilingual-catalog-v4.schema.json) | v3 是人工审核投影；v4 可包含机器质检 target，不把豁免写成人工批准 |
| [catalog v5](../schemas/sermon-multilingual-catalog-v5.schema.json) | family 页面可汇聚同一讲道的不同来源 edition；各语言仍绑定自己的 L1、edition、release、视频与定位，不把不同来源合成一个 L1 身份 |

两端当前读取顺序为 v5 → v4 → v3；旧 v2 Catalog / v1 Release 仅保留兼容范围。具体封存、比较交换、投影及发布门禁见[四产物公开交付](layer4-four-product-public-delivery.zh.md)。

已发行的 Hosting 视频周次沿用 [`three_locale_full_video_v1` 文件数合同](tongxing-weekly-release.zh.md#正式三语周更文件数合同)：21 个新周 Hosting 资源加 1 个 catalog 更新。新的 `three_locale_bucket_video_v2` 合同为 20 个新周 Hosting 资源、1 个 catalog 更新及 1 个 Cloud Storage 视频对象；两种配置不能混报文件数。bucket 视频对客户端保留同源 `/pages/<pageId>/full-video-browser.mp4`，Hosting 以精确 302 指向不可变对象，catalog 的可选 `videoDelivery` 记录对象身份与哈希。Dev、Production 对象及凭据分离；完整上线顺序、回退与 Web／iOS 验收见每周发行合同。其他语言或纯文字发行仍需独立版本化配置。

### Layer 4 收尾：先三语页面，再三语海报

2026-10-07 用户确定每周默认交付顺序：优先分别完成中文（`zh-Hans`）、韩语（`ko`）、西班牙语（`es`）内容页面，然后制作对应三种语言的海报。海报生成纳入 Layer 4 的页面发布收尾步骤，不另起内容生产层，也不反向修改 Layer 1–3。

1. 按当前 release plan 所含的语言（默认三语；单语计划只含中文）分别准备页面、文稿、字幕、同语言音频或允许的显式 `audio_unavailable`、大纲／默想及 Release Package；逐语言检查完整性与上游 hash。三种页面各自绑定本语言的包，不能用中文页面代替另外两种。
2. 按发行合同发布页面与资产、最后更新 catalog，再分别核验 `zh-Hans`、`ko`、`es` 的准确周次、内容语言、界面语言、GET／SHA 和适用 Range。页面发布汇合条件仍由当前 release plan 决定；已可发布的页面不等海报。
3. 三语页面交付阶段完成后，再以同一周的已核对内容提取视觉 brief，生成一个共享的无文字主视觉；遵守 [内容对应提示词](tongxing-weekly-poster-content-brief.zh.md)。客户端／现场验收单独安排，`not_run` 不阻断这个 HTTP 发布后的海报步骤。
4. 用 `tools/ops/run.py delivery.posters.build` 新模板入口为 release plan 已发布的语言分别合成海报（默认中、韩、西三张；纯文字 `audio_unavailable` 语言暂不生成，记为海报待完成），遵循[规范海报](tongxing-weekly-poster-format.zh.md)，每种各有高清图、手机预览与收据；标题、系列、经文、日期、讲员、免责声明和机器／人工审核披露按对应语言的实际内容与状态取值。下载徽章使用对应语言官方素材，网页版二维码分别绑定该语言；固定 iOS 下载二维码共用。
5. 逐语言对两尺寸最终图独立解码两个二维码，目视核对文字及裁切，浏览器验证对应页面。计划包含海报上云时，页面发布核验后再上传图片，最后更新海报索引；每条 sidecar 绑定同环境、同 pageId、同 locale 的当前 release SHA，保留其他语言／历史文件，读回验证图片与索引。
6. 收尾分别报告三语页面、三语海报、上传与设备验收状态。一种海报失败只续跑该海报，不重发已经核验的页面或重跑上游。release plan 内某语言页面未就绪时保留该语言页面与海报为待完成；不在本周 release plan 内的语言不产生页面或海报待办，不为制作海报跳过发布门禁；继续推进其他已授权页面，后续补齐语言再完成海报收尾。

生成顺序与发布状态是两件事：页面可以先记录 `published_http_verified`，海报仍为 `pending`；不能因此将整周海报交付说成完成。各 locale 的内容／音频审核披露保持原状态；一张共享背景或中文打样通过不代表三语海报通过。这是制作与收尾约定，现有 Supervisor／CLI 尚未因文档更新自动接入 ImageGen、双二维码合成或三语海报上传；执行范围见 [每周海报交付](tongxing-weekly-release.zh.md#每周海报交付)。

### 每周 App 内容合同与刷新门槛

1. catalog 的 `defaultPageId` 指向当前 `pages[].id`；本周页标题与已批准的内容文案一致。v5 用 family page ID 选择页面，各 target 用 `editionId` 引用自己的 content、release 与源视频；v4 / v3 保留相应 edition 兼容投影。release v2 / v3 的 `releasePackageUrl` 在 `/releases-v2/`，release v4 在 `/releases-v4/`，SHA 绑定确切包字节。不能把 family ID、edition ID 或不同 target 的来源混用；独立 HTML 仅是兼容入口，不能代替 App 内选页。
2. 目录只声明真实可用的语言和能力。正式音轨需要已听审 Layer 3 与可 Range 读取的同语言音频；全文字幕、英文对照、现场声音定位若列为本周交付，就必须发布各自 sidecar、验证身份绑定与公开 GET。缺少 sidecar 时不能静默把对应功能标为可用。Web 与 iOS 共同支持的现行周更范围是中、韩、西正式音轨；扩展语言／文字版先改客户端并验收。
3. 适用的 `/multilingual-v5.json`、`/multilingual-v4.json`、`/multilingual-v3.json` 必须能在刷新时取到最新版本，明确设置 `Cache-Control: no-store`；逐语言 Release 及资产按路径／hash 校验缓存。客户端读取新目录失败时保留上一次已验证内容，显示刷新失败，不把网络错误说成“未发布”。切换页面不覆盖正在播放的旧周次；刷新后本周页必须在 **Firebase App 内的选页入口**和 **已安装 iOS App 的选页入口**出现，选择后在原 App 内加载本周三语页面，无须每周发新版 IPA 或让用户另开网页。iOS 已有原生 `FullVideoSheet` 视频入口（源码实现与已安装版本、真机播放验收分别记录）；iOS 显式刷新目录、Web 重新加载 App 是可执行的目录刷新入口；若要求 Web 内按钮或返回前台自动刷新，须先实现并单独验收。
4. 发布收据分别记录：完整站点基线与变更差异、catalog 旧／新 hash、逐语言 Release 和每个公开资产的 GET／SHA、MP3 HTTP 206／Range、Web 刷新选页与播放、iOS 同一已安装版本刷新选页与播放、设备验收、现场验收。`published_http_verified` 只表示线上文件通过；客户端与现场未测时各记 `not_run`。回滚只切换已验证的 catalog 指针，保留可恢复的旧资产。

2026-10-03 用户确定的翻译／配音／大纲／默想 App 内容候选，新增 [App 只读交付检查](pr229-local-development.zh.md)：同候选在 iOS Beta 与 Firebase Dev 的能力与人工查看批准均匹配后，才可报告提升资格。`app_delivery_readiness` 与历史 `dual_pdf` completion scope 独立，按需 PDF 不进入 App 候选 hash 或阻断链。新 schema 不表示旧客户端已支持大纲／默想新 sidecar；producer、客户端与通知仍须显式迁移，生产、设备与现场结果另记。

## 当前实现边界

- Layer 1：确定性锚点和机器裁判代码可运行；无机器裁判且无正式英文人工收据的干净 shadow 输入停在 `waiting_machine_judge`。机器裁判通过只允许 Layer 2 shadow，正式 `ready_for_translation` 仍需英文人工收据。
- Layer 2：中文 legacy runner 可工作；`zh-Hans`、`ko`、`es`、`vi` 有同源六句 shadow 候选及机器复核。通用模型执行器、语言插件和候选准入器已实现，新 canonical policy 默认 DeepSeek Flash low / high，Sol / Opus 显式回退；[按组执行与恢复](design/per-group-independent-pipeline.zh.md)保留有效结果，机器失败的人工作法见[override 合同](layer2-human-override.zh.md)；每次正式运行仍需就绪的来源、冻结 policy、逐组机器证据及对应人审，或受支持路径上的有效机器质检豁免，代码可运行不等于整篇生产验收。
- Layer 3：中文 legacy TTS／同步及三语正式 renderer 可工作；整篇音轨的听审、同步与批准以各周实际收据为准，不由本合同自动继承。
- Layer 4：2026-09-27 Production 的 v3 目录／v2 包与 HTTP / Range 是历史发布收据；当前已有[四产物 builder / seal](../packages/production/src/tongxing_production/delivery/app_release.py)、[统一 CD](../tools/ops/run_multilingual_cd.py)、release v3 / v4、catalog v5 / v4 / v3 和 Web / iOS reader。不能继续称它们仅在临时 staging；具体周次的发布、同版本 App 刷新、原生视频、设备与现场验收仍须各自收据，旧 v1 / v2 CLI 不自动获得新 schema 交付资格。
- Canonical English Content 是从英文事实派生的页面内容输入，可以作为 English Source Package 的可选绑定；它不是英文逐字稿，也不能替代 Layer 1 审核。
