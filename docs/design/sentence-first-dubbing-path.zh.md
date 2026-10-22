# 逐句优先配音路径：从第一性原理推导的步骤

状态：**设计稿，2026-10-21。未实现、未运行。** 本页不改变任何现行门禁、豁免规则、schema 或模型政策，不授权付费调用、Spark 独占会话或发布。它回答一个问题：如果只从"视频里有一个人按顺序说了 N 句话"出发，不先假定现有流水线的任何组织方式，一条诚实、可绑定、可局部修复的多语言配音路径最少需要哪些步骤；然后对照现有仓库说明每一步今天用什么、缺什么。[四层合同](../multilingual-production-interfaces.zh.md)和 [AGENTS.md](../../AGENTS.md) 的七条不变式照旧成立；本页只是在这些边界内重新排列工作，不是另一套发布资格。

相关设计：[逐组独立任务](per-group-independent-pipeline.zh.md)（组记录、合并步骤、失效规则）、[层内解耦与预生成](../multilingual-intralayer-review-decoupling.zh.md)（`preview_only` 单元配音）、[机器质检豁免](../machine-quality-waiver.zh.md)（校准、修复账本、降级规则）、[Speaker Voice Registry](../multilingual-speaker-voice-registry.zh.md)（声音身份与授权）。

## 一、第一性原理：什么是不可再分的

去掉所有工程组织之后，剩下的事实只有这些：

1. **一段授权媒体**，有哈希和时长。讲员在其中按时间顺序说了若干句话。
2. **每一句**有：英文内容、起止时间、词级时间、句后停顿、讲员自己念这句话时的声音。这一句的声音是最真实的"这句该怎么说"的参照，不需要任何模型来想象。
3. **听众需要的**是：同一句话，用他的语言，大致在讲员说这句话的时候听到或看到；并且知道他听到的是机器译的、机器配的，还是人审过的。
4. **翻译**是句到句的函数：给定这句英文、术语约定和少量上下文，产出目标语言的这一句。它不依赖别的句子已经翻好。
5. **配音**是句到音频的函数：给定目标语言的这一句、讲员的声音身份、这句的时间预算，产出一段音频。它不依赖别的句子已经配好。
6. **只有两件事天然是整篇的**：顺序排布（一句变长会推后后面各句）和整篇比例（多少句没有配音）。

由此推出的结构：**句子是原子；翻译、审核、配音、回查都是逐句的、无状态的、可缓存的函数；整篇只在最后做一次排程、一次比例判断、一次封装。** 这与[逐组独立任务](per-group-independent-pipeline.zh.md)的结论一致（那里的"组"就是一个锚点单元，通常一句）。本页在它之上增加两点：翻译与审核由当前会话里的 Claude 逐句直接完成，而不是经 controller 调外部 API；每句配音绑定讲员念这一句的原声片段作为声音参照。

"声纹"一词在本仓库另有含义：[现场定位](../field-fingerprint-alignment-backlog.zh.md)里的"声纹"应称**音频指纹**，用于在已批准录音里找位置，不识别说话者。本页说的"对齐声纹"指**讲员的声音身份与这一句的原声参照**，下文一律写作"声音参照"，不与指纹混用。

## 二、八个步骤

每个步骤写明：输入、输出、谁执行、今天用什么工具、缺什么。标记 **已有** 的步骤直接用现有入口；标记 **缺** 的是本路径要新建的部分。

```text
S0 媒体与窗口 ──> S1 转写冻结 ──> S2 词对齐(MFA) ──> S3 逐句拆分 + 原声切片
                                                          │
                      每个 locale × 每句 g，独立、可并行、可缓存：
                      S4 Claude 逐句翻译 → 独立复核 → 术语/数字/经文确定性检查
                      S5 逐句口播规格：口播文字、时间预算、声音参照、朗读提示
                                                          │
                      每个 locale 一次：
                      S6 合并为 speech job → 本地模型(Spark Qwen TTS)逐句配音
                      S7 逐句回查(ASR、音频 QC) → 整篇排程 → 整轨 → 豁免或人审
                      S8 Layer 4 封装与发布（不变）
```

### S0 媒体与窗口（Layer 1，已有）

- 输入：授权视频或音频；操作者给出证道起止时间。
- 输出：媒体哈希、时长、批准窗口收据。
- 工具：现有 `run_post_live_subtitle_generation.py` 路径的媒体准入与窗口批准；窗口批准是人工输入，不由模型猜。
- 不变式：媒体身份变化使全部下游失效（不变式 2、3）。

### S1 转写冻结（Layer 1，已有）

- 输入：窗口内音频。
- 输出：冻结英文转写（immutable ASR finals），段与词的文字。
- 工具：现有来源 ASR 入口（见[运行模型政策](../production-model-runtime-policy.zh.md)的速度基线表中"来源 ASR"行）。
- 边界：转写一旦冻结不再改字；发现错字走 Layer 1 人工审核收据，不在下游补。

### S2 词级对齐（Layer 1，已有）

- 输入：冻结转写 + 音频。
- 输出：每个词的起止时间、音素时间，`timingQuality=mfa_word_aligned`。
- 工具：`sermon-mfa-word-alignment` skill；Spark 上的 MFA 运行时，MacBook 只在确认基础设施故障时回退。经文章节、小数等需要操作者确认的 `--mfa-spoken-forms`。
- 边界：一个正式包只用一条词时间轴（MFA 或 Qwen ForcedAligner，不混）。

### S3 逐句拆分与原声切片（Layer 1，拆分已有，切片缺）

- 输入：词时间 + 冻结转写。
- 输出 A（已有）：`clause_stable_v2` 锚点清单与 English Source Package。只在标点或可听停顿处分句；每句记录 `sourceSentenceBoundary`、`pauseAfterSeconds`、`splitEvidence`。这就是"把英文文字和每句拆开"，现有 `prepare_sentence_interpretation_shadow.py` 已同时写出 `anchor-manifest.json` 与 `english-source-package.json`。
- 输出 B（缺）：**逐句原声切片表**。对每句 g，按词时间从窗口音频切出 `[firstWord.start − 前垫, lastWord.end + 后垫]` 的 WAV，记录切片哈希、实际时长、句后停顿。切片只放在忽略的 `artifacts/`，不进 Git（不变式 6：私有媒体）。
- 为什么要 B：它是 S5 的声音参照，也是 S7 "与原声时长之比"检查的直接证据来源。现在音频 QC 用冻结锚点的 `sourceSeconds`，与切片等价，但切片把"这句原来怎么说"变成一个可听、可绑定的文件。
- 新建位置：`packages/production/src/tongxing_production/source/sentence_slices.py`，入口 `tools/ops/run.py source.sentence_slices`。确定性、零模型调用、按（媒体哈希, 锚点哈希, 前后垫参数）缓存。

### S4 Claude 逐句翻译与复核（Layer 2，缺记录合同）

这是与现行路径差别最大的一步。现行 canonical Layer 2 由 controller 以冻结 policy 调外部模型（OpenAI API，或 2026-10-14 起可选的 `claude_cli_opus` 后端经本机 Claude CLI 子进程）。本路径改为：**当前会话里的 Claude 直接读句、译句、审句**，不经 controller 派发。

逐句工作单元（每个 locale × 每句 g）：

1. **读入**：这一句英文、前 3 句后 2 句英文上下文（只用于消歧，不翻译）、[术语表](../series-terminology.zh.md)中本系列的条目、该 locale 的冻结翻译策略（经文版本、排版、语域规则）。
2. **初译**：产出目标语言这一句。要求：完整覆盖本句、不借邻句内容、经文出处与数字按英文、术语按表、系列名按表。
3. **独立复核**：换一个请求、换一个角色（不看初译的推理，只看英文与译文）判定：漏译、增译、否定、数字、人名、经文、意思偏移；给 `pass | revise(codes)`。`revise` 时带失败码回到初译，次数计入现有[修复账本](../machine-quality-waiver.zh.md)（按英文 source unit 计，每句上限见该文档）。
4. **确定性检查**：复用现有语言插件（`language_review_plugins/*_weekly_auto.py`）对单句运行：脚本、未译英文、术语人名、经文书卷、数字计数。零模型调用。
5. **写记录**：一条 `sermon-group-stage-record-v1`（已有 schema）或其逐句扩展，含：输入键（英文哈希、上下文哈希、策略哈希、术语表哈希、提示版本）、译文、复核判定、模型身份、会话标识、时间戳。只追加，不覆盖。

需要新建的部分：

- **会话内模型身份如何绑定。** controller 路径的身份由 transport 返回的 `modelUsage` 提供；会话内 Claude 没有这个回执。记录须写入：模型 ID（本会话为 `claude-fable-5-1`，以会话声明为准）、提示文件哈希、工具版本；并在记录上标 `executionMode=interactive_session`。这是**诚实标签**问题（不变式 1）：这样的译文是机器译文，`humanApproval=false`；它和 controller 产出的译文一样只能走机器质检豁免或人工审核进入 Layer 3，不因为"是 Claude 当场译的"获得任何额外资格。
- **记录写入与校验工具**：`text/sentence_session_records.py`，入口 `tools/ops/run.py text.sentence_records {append,validate,assemble}`。`append` 校验单条记录的字段与哈希；`validate` 检查整篇覆盖（所有 `sourceUnitIds` 按序恰好覆盖锚点）；`assemble` 用逐句记录拼出 evidence 交给现有 `admit_evidence`，产出标准 Target-Language Candidate v2。合并后的候选与现行 schema 逐字节兼容，所以 Layer 3、Layer 4 验证器不改。
- **预算与成本**：会话内调用走订阅，不进 OpenAI 账本。记录按[运行模型政策](../production-model-runtime-policy.zh.md)已有的 Claude 列价等价规则记 `countsTowardTotal: false`，并记实际 token（会话可见时）。不得把订阅调用说成零成本。
- **并行**：一个会话逐句串行即可满足一个 locale；要并行时用子代理，每个子代理一组句子，写各自的记录文件，不共享可变状态。两个写者永不写同一条键。

### S5 逐句口播规格与声音参照（Layer 2→3 交接，缺）

Claude 在 S4 产出完整译文后，为每句再产出一份**口播规格**（speech spec），这是"合并后交给本地模型"的输入：

| 字段 | 来源 | 说明 |
|---|---|---|
| `spokenText` | 由完整译文派生 | 口播形式：经文章节读法、数字读法、停顿标点；不改意思，不另译系列名。韩语章节读法按现行 `ko_spoken_numerals` 规则版本，不自造 |
| `durationBudgetSeconds` | S3 原声切片时长 + `pauseAfterSeconds` | 这一句自然语速应落在的时长；超预算的句子由 Claude 产出精简口播（只删冗余，不删论点、呼召、否定、数字、人名、经文出处，规则见[豁免文档](../machine-quality-waiver.zh.md)"允许精简"），字幕仍用完整译文 |
| `voiceIdentity` | [Speaker Voice Registry](../multilingual-speaker-voice-registry.zh.md) | 讲员 `speakerId`、授权用途、本 locale 能力状态、checkpoint 哈希。是长期资产，不每周重选 |
| `referenceSliceSha256` | S3 原声切片 | 这一句讲员原声的哈希；给支持参照条件化的 adapter 当参照，给不支持的 adapter 只作时长与情绪证据 |
| `deliveryHint` | Claude 从原声切片与英文判断 | 可选，自然语言朗读提示（语速、停顿、强调），进入现有 `--unit-instructions`（`sermon-unit-delivery-instructions-v1`）；不能借提示改译文 |

关于"对齐声纹"的两层含义，要分开记录，分开验证：

1. **声音身份**：是谁的声音。现行正式路径用按讲员 SFT 的 Qwen3-TTS checkpoint；越南语 POC 用参照克隆 adapter（Gwen-TTS）。两者都登记在 Registry，能力状态按 locale 独立。本路径不新造声音，只从 Registry 取。
2. **逐句参照**：这一句怎么说。SFT checkpoint 不接受逐句参照音频，只接受文字与 `instruct`；参照克隆 adapter 接受参照音频，但目前只有越南语在用且为 `unverified_poc`。所以"用讲员念这句的原声作参照"在中、韩、西语上**今天没有正式 adapter**。可行的推进顺序：先把原声切片只用作 `durationBudgetSeconds` 与 `deliveryHint` 的依据（SFT 路径立即可用）；再对同一讲员做"SFT checkpoint vs 原声参照克隆"的同输入盲听 A/B，通过后才在 Registry 为该 locale 登记参照克隆 adapter。A/B 结果决定第二层是否存在，设计不预设结论。

新建位置：`audio/sentence_speech_spec.py`，入口 `tools/ops/run.py audio.sentence_speech_spec`。输入逐句记录 + 原声切片表 + Registry，输出每句一条规格；`assemble` 把规格合并成现有 Target-Language Speech Job v3 的单元列表。speech job v3 若需要 `referenceSliceSha256` 字段，按"版本化任何 schema 变更"新开 v4，v3 继续可读。

### S6 合并与本地配音（Layer 3，已有 renderer，缺参照 adapter）

- 输入：一个 locale 的 speech job（S5 合并产物）、Registry 与 checkpoint map、音频操作策略。
- 执行：`sermon-layer3-dubbing` skill，Spark 上 docker 内的正式 renderer。逐单元一次自然语速合成，不拉伸、不在词组内拼接。
- **批窗口与逐句修复的冲突**：2026-10-19 `DEV-GRP-005` 的盲听 A/B 未通过，batch 成员（含窗口位置）仍属声音身份；改一句要重合成它所在的批窗口。对逐句路径有两个选择：
  - (a) 逐句路径一律 `--batch-size 1`：每句声音身份只含本句，改一句只重合成一句；代价是放弃 8×8 吞吐（速度基线见[运行模型政策](../production-model-runtime-policy.zh.md)）。
  - (b) 保留 8×8，接受修一句重合成 8 句，并在逐句记录里把批窗口成员哈希写进 S 步的输入键（[逐组设计](per-group-independent-pipeline.zh.md)第四节已这样规定）。
  **2026-10-21 用户决定：第一次片段 E2E 用 (a)，`--batch-size 1`；8×8 留给之后的吞吐对比（第五节 F）。** 这个决定只约束首次验证的 render 配置，不改 renderer、不改 `DEV-GRP-005` 的结论。
- 输出：`render-manifest.json` 与逐单元收据，再由现有 `build_target_language_audio_package.py` 组包，状态最多 `candidate`。

### S7 逐句回查、整篇排程、放行（Layer 3 门禁，已有）

逐句（可缓存，输入键 = WAV 哈希 + 预期文字哈希 + 设置哈希）：

- ASR 回转写与比对：`sermon-dubbing-asr-sync-check` skill，两级 ASR 规则与"听感等价"折叠按[豁免文档](../machine-quality-waiver.zh.md)。
- 单句音频 QC：时长异常、截断、静音、削波，`sourceSeconds` 来自冻结锚点（与 S3 切片时长一致，可互相核对）。
- 失败只送回这一句：读法或口播文字问题回 S5，译文问题回 S4，合成问题回 S6；次数记修复账本。

整篇（每个 locale 一次）：

- 滚动排程、每句滞后上限检查、字幕 cue、PCM 母带与 MP3、整轨逐窗核对。滞后超限按排程定位到句，回 S5 精简或 S4。
- 放行三选一，按现行规则：人工整轨听审收据；或机器质检豁免（需当前实现哈希下有效的注错校准，`humanApproval=false`，页面显示披露）；或 `audio_unavailable` 纯文字。不配音的句子超过比例阈值时整个语言只发文字。

### S8 Layer 4 封装与发布（不变）

按 `pageId + targetLocale` 读现行收据封存 release v3/v4 与 catalog。Layer 4 不读逐句记录，不知道译文是会话内 Claude 还是 controller 产出；它只核哈希与审核状态。这是设计上的刻意隔离：S4 的改动不触碰发布合同。

## 三、与现行路径的差异一览

| 环节 | 现行 canonical | 本路径 | 变不变合同 |
|---|---|---|---|
| L1 转写、对齐、拆句 | 同 | 同，另加逐句原声切片 | 不变；切片是新产物，不进包 |
| L2 执行者 | controller 派发 OpenAI API 或 Claude CLI 子进程 | 会话内 Claude 直接逐句译审，写逐句记录 | candidate v2 不变；新增记录写入／校验工具 |
| L2 复核独立性 | 不同 request、同模型不同 reasoning | 不同请求或子代理、不同角色提示 | 机器复核仍不是人工批准 |
| L2 预算 | OpenAI 账本或 Claude 列价等价 | 订阅，记 `countsTowardTotal: false` 与实际 token | 按现行政策 |
| L2→L3 交接 | 候选 + 8 秒预算 + 精简 | 逐句口播规格（含时长预算、声音参照、朗读提示） | speech job 可能需 v4 加参照字段 |
| L3 声音 | Registry SFT checkpoint | 同；参照克隆为待 A/B 的可选项 | Registry 合同不变 |
| L3 批次 | 8×8 | 首次验证 batch 1，见 S6 决定 | renderer 不变 |
| L3 回查与放行 | 同 | 同 | 不变 |
| L4 | 同 | 同 | 不变 |

## 四、风险与边界

- **诚实标签。** 会话内 Claude 的译文、复核、口播规格、朗读提示全部是机器产物。记录与候选保持 `humanApproval=false`；进入 Layer 3 只经豁免或人审。不得把"Claude 在会话里逐句看过"写成人工审核。
- **身份可复现。** 会话内调用没有 transport 回执，提示版本与模型 ID 要显式写进记录；同一输入键第二次运行只能读，不能覆盖。另一个会话（或 Codex）可能在同一 `artifacts/` 下工作，写前先读 `decisions.ndjson` 与已有记录。
- **私有媒体。** 原声切片是讲员原声，只在 `artifacts/`；S5 规格里只写哈希与路径别名，公开包不复制。
- **参照克隆未验证。** 中、韩、西语的参照克隆 adapter 没有 Registry 登记，不得在 A/B 前用于任何有发布意图的音轨；A/B 本身按现有 demo 流程（完整解码、ASR 筛查、母语盲听），结论按 locale 分别记录。
- **切句粒度。** 太短的句子损害 TTS 韵律，太长的句子撞时长预算。沿用 `clause_stable_v2`（标点或可听停顿）不另造规则；觉得粒度不对时改 Layer 1 政策并接受全篇失效，不在 S4 偷偷合并或拆分句子。
- **术语表。** 读表不等于消费了表；S4 的记录要写术语表哈希，`validate` 核对它等于冻结策略里的哈希。

## 五、实施顺序

每一批独立可合并，先后依赖只在箭头方向。都遵守[目标布局](repository-layout-proposal.zh.md)：代码进 `packages/production/src/tongxing_production/<area>/`，入口经 `tools/ops/run.py`，测试进 `tests/`，不新增 `scripts/` 文件。

1. **A：原声切片**（`source/sentence_slices.py`）。输入现有 English Source Package 与窗口音频，输出切片表与 WAV；确定性，带缓存键与哈希；测试用合成音频夹具。零模型、零付费。
2. **B：逐句记录工具**（`text/sentence_session_records.py`）。`append`／`validate`／`assemble`；`assemble` 的金样测试：同一批记录拼出的 candidate 必须与现行 controller 对同输入产出的 candidate 结构一致并通过 `admit_evidence`。附带一份逐句提示文件（初译、复核两个角色）放 `config/`，哈希进记录。
3. **C：口播规格**（`audio/sentence_speech_spec.py`）。从记录 + 切片 + Registry 生成规格并合并为 speech job；若加参照字段则开 speech job v4 并带迁移说明。
4. **D：片段 E2E（真实运行）**。一个已批准片段、一个 locale（建议 `zh-Hans`，声音能力已有人审）、batch 1、SFT checkpoint、原声切片只作时长与提示依据。走完 S0–S7，人工听审或豁免按现行规则。按 [AGENTS.md](../../AGENTS.md) 导出脱敏运行报告并开 docs-only PR。
5. **E：参照克隆 A/B**（独立于 D，可并行）。同讲员、同句、同种子，SFT vs 参照克隆，完整解码 + ASR 筛查 + 母语盲听；结果写 `docs/reports/`，通过的 locale 才登记 Registry adapter。
6. **F：量吞吐**。D 通过后比较 batch 1 与 8×8 在逐句修复场景下的总耗时与重合成句数，决定 S6 的 (a)/(b)。

D 之前的 A–C 全是本地确定性代码，不需要 Spark 独占、不付费。D 与 E 各需用户的一次性授权（片段范围、locale、声音用途、Spark 会话）。

## 六、给执行代理的步骤清单

代理按本节逐步执行一次逐句路径运行时，遵守下面的顺序。每步先核对输入哈希，再做事，再写记录；任何一步的输出都带输入键。标 **（待建）** 的入口在第五节的批次合并前不存在，代理不得用临时脚本代替后宣称完成。

1. 读 [AGENTS.md](../../AGENTS.md)、本页、[四层合同](../multilingual-production-interfaces.zh.md)、[术语表](../series-terminology.zh.md)本系列条目。核对当前分支与 `artifacts/` 下是否已有同来源的运行（另一个代理可能在跑）。
2. **S0–S2**：复用已验证的媒体身份、窗口批准、冻结转写与 MFA 结果；缺哪个才跑哪个。MFA 按 `sermon-mfa-word-alignment` skill 连 Spark，先查连通性，再查运行时，不猜。
3. **S3**：确认 `anchor-manifest.json` 与 `english-source-package.json` 存在且哈希匹配；运行 `tools/ops/run.py source.sentence_slices`（待建）生成原声切片表。
4. **S4**：对每句依次执行初译、独立复核（换请求／子代理）、确定性检查；每句一条记录 `append`。全部句子完成后 `validate` 覆盖与顺序，再 `assemble` 出 candidate v2（工具待建）。中途停下再续时，只对没有终态记录的句子工作。
5. **S5**：运行 `tools/ops/run.py audio.sentence_speech_spec`（待建）生成逐句规格并合并为 speech job；核对 Registry 中讲员的本 locale 能力状态与授权用途，不满足则停，不换声音。
6. **S6**：按 `sermon-layer3-dubbing` skill 在 Spark 渲染，首次验证 `--batch-size 1`（2026-10-21 用户决定），新建 render 根目录，不与旧缓存混，不加 `--spark-production`。断线或超时先对账，不本地重跑。
7. **S7**：按 `sermon-dubbing-asr-sync-check` skill 做逐句筛查与音频 QC；整篇排程与整轨核对；失败句只回它失败的那一步。放行按现行三选一，状态如实写 `candidate`／`waived`／`human_reviewed`。
8. **S8**：只在本次 release plan 包含该 locale 时进入 Layer 4，按[Layer 4 公开交付](../layer4-four-product-public-delivery.zh.md)执行。
9. 导出脱敏运行报告到 `docs/reports/runs/`，开 docs-only PR；报告写明：实际使用的主机与模型、逐句记录数与重做数、batch 设置、放行方式、未验证的部分。

## 七、需要用户决定的事项

1. ~~S6 的批次策略~~ 已决定（2026-10-21）：首次验证 batch 1，8×8 留作吞吐对比。
2. 参照克隆 A/B（第五节 E）是否纳入本轮，以及先做哪个 locale。
3. 片段 E2E（第五节 D）的来源、窗口、locale 与声音用途授权。
4. 会话内 Claude 译审的记录是否需要进入现有 Layer 2 预算账本的只读投影，还是只在运行报告里按列价等价披露。
