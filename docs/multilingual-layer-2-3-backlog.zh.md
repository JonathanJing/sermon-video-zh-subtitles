# 多语言 Layer 2 / Layer 3 实施 Backlog

状态：**影子片段链已验证，正式生产待实施**。本 backlog 从已冻结的四层接口继续推进，覆盖：

- Layer 2「目标语言文字」：`English Source Package` → `Target-Language Candidate`；
- Layer 3「目标语言音频与同步」：人工批准的 `Target-Language Candidate` → `Target-Language Audio Package`。

首个新语言为韩语 `ko`；现有简体中文 `zh-Hans` 用作兼容与等价验证。Layer 1 的机器裁判只作为上游 shadow 开发门禁；Layer 4、设备和场地验收列为周日可用的下游依赖，不在本 backlog 中伪装成 Layer 2/3 已完成。第 2 层详细设计见[目标语言文字设计基线](multilingual-layer-2-design.zh.md)。

## 1. 开始条件与共同规则

正式运行 Layer 2 前必须取得：

- `sermon-english-source-package-v1`，状态为 `ready_for_translation`；
- 与该 package 绑定的 clause-stable anchor manifest；
- 两者 JSON SHA-256 与 `downstreamInvalidationKey`；
- 目标语言策略快照，包括模型、prompt、术语、经文版本和语言审核规则。

若 English Source Package 只有 `candidate_ready_for_translation`，只允许 shadow fixture，不得生成带人工批准或发布含义的正式候选。

共同不变量：

- 各语言直接读取同一份英文 package；禁止 `en → zh-Hans → ko`。
- 每个产物只承载一个 `targetLocale`。
- 缓存身份必须包含 source package、anchor、locale、policy 和实现 hash。
- Layer 3 不得静默改写 Layer 2 已批准文字；需要改口播文本时，回到 Layer 2 产生新 revision 并重新批准。
- 任一机器检查都不能写成人工批准；翻译审核、音频听审和同视频验收分别保存。
- 大体积音频、模型和运行目录继续留在 ignored artifacts；Git 只保存 schema、fixture、实现和紧凑收据。

建议 issue 标签：`layer:2`、`layer:3`、`locale:ko`、`locale:zh-Hans`、`gate:human-review`、`priority:p0|p1|p2`。

## 2. 当前已具备的基础

- [x] `sermon-target-language-candidate-v2` schema。
- [x] `sermon-target-language-speech-job-v1` schema。
- [x] Layer 2 → Layer 3 的 fail-closed 准备器；未人工批准的译文不能进入 speech job。
- [x] speech adapter locale 一致性、能力状态和语言隔离输出路径检查。
- [x] 韩语界面与 `sourceLocale=en` 内容 sidecar，可作为 shadow 消费端。
- [x] `sermon-target-language-audio-package-v1` 目标 schema 已定义。
- [x] 四语同源六句 shadow 候选、片段音频、完整解码与 ASR 筛查已留收据；`productionEligible=false`、人工译文及音频审核仍 pending。
- [x] Layer 1 独立机器裁判代码已提取并通过定向单测；它只解锁 Layer 2 shadow，真实来源与人工英文审核仍单独验收。
- [ ] 通用 Layer 2 producer、整篇人工批准韩语翻译、通用 Layer 3 renderer/同步器及整篇人工听审韩语音轨尚未实现。

## 3. Layer 2：目标语言文字 Backlog

### L2-P0：先打通可重复的单语言文字链

#### L2-001 冻结目标语言策略合同

- [ ] 定义版本化 `Target-Language Policy`，至少包含 `targetLocale`、translator/reviewer、prompt、术语表、经文政策、标点/断句规则和各子项 hash。
- [ ] 把中文 CUV 检查放进 `zh-Hans` policy，不进入共享英文层。
- [ ] 建立韩语 policy 初版：系列术语、专名转写、敬语/语体、自然口语、标点断句和韩文圣经引用政策。
- [ ] 明确韩文圣经版本和引用许可；未决定前经文检查状态必须是 `pending`，不得人工批准全文。

验收：修改任一 policy 组成项都会改变 `translationPolicySha256`；中文与韩语 policy 互不继承审核结果。

#### L2-002 实现通用翻译 producer

- [ ] 新增只消费 `English Source Package + anchor + targetLocale + policy` 的 runner。
- [ ] CLI 使用显式 `--target-locale`、`--policy`、`--out`；移除通用路径中的 `--zh-*` 假设。
- [ ] 逐 group 保存 source unit、上下文、target utterances、coverage ledger 和模型 request ID。
- [ ] 上下文只用于消歧，不得被翻入目标文本。
- [ ] 支持确定性 resume；已成功 group 按完整身份复用，身份变化时不覆盖旧产物。

验收：同一输入重复运行得到相同 group 身份与内容 hash；`ko` 输出中不读取中文 candidate 或中文页面字段。

#### L2-003 实现独立模型复核

- [ ] reviewer 与 translator 使用不同 request；收据保留模型和 prompt 版本。
- [ ] 通用语义检查固定为：含义完整、否定/数字/专名、引文归属、无新增含义。
- [ ] fail 或 uncertainty 非空时，candidate 停在 review/revision 状态。
- [ ] 修订后重新计算 group/candidate hash，不在原 candidate 上原地提升状态。

验收：遗漏、重复、错序、否定反转、数字错误和引文归属错误 fixture 全部 fail closed。

#### L2-004 建立语言审核插件接口

- [ ] 定义 `languageReview.pluginId + policySha256 + checks[]` 的注册和调用方式。
- [ ] `zh-Hans` 插件接入中文口语、CUV、数字/专名读法及现有审校规则。
- [ ] `ko` 插件检查韩语自然度、敬语一致性、专名转写、经文版本、数字读法和 TTS 友好断句。
- [ ] 未注册 locale 或缺必需检查时停止，不使用通用 pass 代替语言检查。

验收：同一组英文可以分别通过/失败于不同语言插件，互不改变对方 candidate。

#### L2-005 建立人工文字审核收据

- [ ] 审核 UI 或 CLI 显示英文 source unit、目标译文、coverage、机器复核证据和语言检查。
- [ ] 收据绑定 source package、candidate hash、reviewed group IDs、reviewer 和带时区时间。
- [ ] 只允许完整覆盖且无 unresolved issue 的 candidate 进入 `human_translation_approved`。
- [ ] 英文 package、policy 或任一 group 改变时自动使批准失效。

验收：复制旧收据到新 candidate、漏审一个 group 或 hash 不符都不能进入 Layer 3。

### L2-P1：兼容中文并完成韩语实证

#### L2-006 `zh-Hans` legacy adapter 与 golden shadow

- [ ] 将 `chinese`、`chineseUtterances`、`spokenChinese` 映射为 v2 通用字段和中文语言检查。
- [ ] 保留旧 v1 读取路径，不重标历史产物。
- [ ] 选一篇完整、已审核中文证道做 golden replay，比较文本、source-unit coverage、审核结论和顺序。
- [ ] 差异按“合同表示变化”与“实际内容变化”分类，未解释差异不得切换生产入口。

验收：adapter 对 golden sermon 的目标文本和 coverage 逐项等价；旧中文生产仍可独立运行。

#### L2-007 韩语小 fixture

- [ ] 冻结包含普通叙述、否定、数字、专名、直接引语和经文的英文 fixture。
- [ ] 跑完初译、独立复核和韩语语言插件。
- [ ] 由韩语审核者检查全部 group，并记录未决术语与经文政策问题。
- [ ] 验证失败后 resume 不重复已完成且身份一致的 request。

验收：fixture 覆盖每个 source unit 恰好一次；候选通过 schema、代码 validator 和人工文字审核。

#### L2-008 一篇完整韩语证道

- [ ] 使用一份 `ready_for_translation` 的真实整篇 English Source Package。
- [ ] 记录 request 数、token/成本、重试、耗时、coverage 和问题分布。
- [ ] 完成人工全文阅读，抽查否定、数字、专名、经文和跨段上下文。
- [ ] 生成可供 Layer 3 使用的 immutable `human_translation_approved` candidate。

验收：完整 candidate 无漏段、重复和跨语言来源；审核收据覆盖所有 group。此项只证明韩语文字，不证明音频或发布。

#### L2-009 页面内容 sidecar producer

- [ ] 由 Canonical English Content 直接生成韩语标题、摘要、大纲和反思，不再依赖手写中文→英文词典链。
- [ ] sidecar 绑定 Canonical English Content hash 和 Layer 2 policy。
- [ ] 缺译字段显式列入 `fallbackPaths`，不得静默显示为已完成韩语。
- [ ] 保持页面内容翻译与逐段证道 candidate 的 provenance 区分。

验收：改变英文页面内容只使对应 sidecar 失效；不会改变逐段 candidate 或音频状态。

### Layer 2 完成门槛

- [ ] `zh-Hans` 与 `ko` runner 读取同一 English Source Package，而不是各自复制英文。
- [ ] 两种语言各自产出独立、schema-valid、hash-bound candidate。
- [ ] 中文 golden shadow 等价通过。
- [ ] 韩语完成小 fixture 和一篇真实整篇人工文字审核。
- [ ] 单个 locale 失败、重跑或失效不会修改其他 locale。
- [ ] 尚未执行 TTS 或发布；Layer 2 完成不宣称 Layer 3/4 完成。

## 4. Layer 3：目标语言音频与同步 Backlog

### L3-P0：抽出通用音频执行骨架

#### L3-001 冻结 speech adapter 合同

- [ ] 为 adapter config 增加正式 schema，而不只由 Python 字段检查。
- [ ] 固定 provider、model/checkpoint、voice authorization、locale capability、语言参数、文本规范化、ASR 筛查和字幕策略 hash。
- [ ] 区分 `unverified_poc`、`candidate`、`verified`；未验证 adapter 只能准备 job，不能合成正式候选。
- [ ] 明确 checkpoint/voice 是否真实支持 `ko`，不从中文样片推断。

验收：adapter locale、授权、checkpoint 或任一策略不匹配时，在调用模型前失败。

#### L3-002 实现语言中立 renderer

- [ ] renderer 只消费 immutable speech job，不直接读取 legacy 中文字段。
- [ ] 逐 unit 使用已批准的 `targetText`；合成前后保存 text hash。
- [ ] 文件统一写入 `languages/<locale>/audio/`，不再在通用代码生成 `zh-natural.mp3` 等名称。
- [ ] 保持自然语速、`playbackRate=1.0`、测量前无 time-stretch/裁切。
- [ ] 每个 unit 保存模型、checkpoint、seed/参数、音频 SHA-256、采样率、声道和实测时长。

验收：修改 approved text、adapter 或 checkpoint 会产生新 job；旧 job/音频不被覆盖。

#### L3-003 音频解码和完整性门禁

- [ ] 每个 unit 用 `ffprobe` 验证音频流、采样率、声道和正时长。
- [ ] 用 `ffmpeg` 完整解码，不以文件存在或 header 可读代替完整检查。
- [ ] 汇总 track 前核对 unit 数量、顺序、text hash 和 receipt hash。
- [ ] 任一 unit 缺失或损坏时保留已完成单元，但不生成完整音轨候选。

验收：截断、空文件、错 unit、旧 job 音频和 hash 漂移 fixture 全部被拒绝。

#### L3-004 抽出语言中立滚动排程器

- [ ] 从现有中文 timing 代码中分离纯确定性调度：anchor stable time、reaction lag、实测音频时长和 inter-utterance gap。
- [ ] 输出 planned start/end、end lag、overlap/overflow、source-unit 映射和失败原因。
- [ ] 排程器不理解中文或韩语文本，只消费 locale-neutral unit 和时长。
- [ ] 溢出时生成 repair worksheet；不得自动加速、裁切或删义。

验收：现有中文 golden timing 在新调度器下数值等价；同一时长输入与 locale 无关。

#### L3-005 生成 Target-Language Audio Package

- [ ] 实现 producer，将 speech job、unit receipts、track、captions、schedule、machine screening 和 human review 汇总到正式 schema。
- [ ] `downstreamInvalidationKey` 绑定 candidate、speech job、voice/checkpoint、音频、字幕和 schedule。
- [ ] 支持合法 `audio_unavailable` 包；不得借用中文音轨填充韩语。
- [ ] 状态推进严格为 `candidate → machine_screened → human_reviewed`，失败进入 `rejected` 或保留待修复状态。

验收：schema validator 与语义 validator 同时通过；单改音频或 schedule 会改变失效 key。

### L3-P1：韩语能力与质量实证

#### L3-006 韩语 voice/TTS 短探针

- [ ] 使用已授权 voice/checkpoint，合成姓名、数字、经文、英语借词、长短句和敬语 fixture。
- [ ] 记录模型实际 locale 参数、runtime 和 checkpoint hash。
- [ ] 韩语听者评价可懂度、发音、韵律、说话人相似度和不自然模式。
- [ ] 若同讲员 checkpoint 不支持自然韩语，明确选择替代 voice 或将韩语停在 `audio_unavailable`；不降低门槛。

验收：只有人工确认探针可继续时，adapter capability 才能从 `unverified_poc` 提升。

#### L3-007 韩语回转录筛查

- [ ] 选择支持韩语的 ASR，并记录 model/revision。
- [ ] 规范化韩文标点与空格后比较覆盖，同时单独检查数字、专名和经文。
- [ ] 低置信或关键实体差异进入 review queue；ASR pass 不设置人工听审 pass。
- [ ] 统计必须按 unit 和全文同时报告，避免总体分数掩盖局部漏读。

验收：故意漏词、错数字、错专名和静音 fixture 能触发 `requires_review` 或 `fail`。

#### L3-008 韩语字幕 cue 与断行

- [ ] 从 target utterance 与排程生成韩语 cue，不从中文字幕翻译或复用中文时间含义。
- [ ] 实现韩语字数/断行/标点策略，保留 group/source-unit 映射。
- [ ] 校验 cue 单调、不重叠、不越过音轨/视频边界。
- [ ] 字幕 hash 写入 Audio Package；字幕改动使同 locale 发布失效。

验收：韩语 fixture 的断行由韩语审核者检查；技术校验覆盖首尾和长句。

#### L3-009 多段 fixture 与完整音轨

- [ ] 先跑 10–20 个代表性 group，验证 resume、解码、ASR 和排程。
- [ ] 再对 L2-008 的整篇韩语 candidate 生成自然语速音轨。
- [ ] 统计生成成功率、重试、总时长、最大/分位 end lag、overflow 和成本。
- [ ] overflow 修复返回 Layer 2 新 candidate revision；不直接改 speech job 文字。

验收：整篇音轨所有 unit hash/时长齐全，排程无未解决 overflow，机器筛查达到预定门槛。

#### L3-010 人工全文听审与同视频验收

- [ ] 韩语审核者以 1 倍速听完整自然音轨，检查漏读、错读、停顿、情绪、经文和专名。
- [ ] 再与原视频 1 倍速播放，检查进入时间、累积延迟和段落对应。
- [ ] 收据绑定 Audio Package hash、reviewer、时间、完整播放和 issue 清单。
- [ ] 修复后必须生成新 Audio Package 并重新全文检查受影响范围；不得修改旧收据。

验收：`human_reviewed` 只在全文听审与同视频检查都有证据时成立；这仍不等于 Layer 4 设备或现场验收。

### L3-P2：中文迁移与运行可靠性

#### L3-011 `zh-Hans` renderer/scheduler shadow 等价

- [ ] 用现有完整中文周产物同时跑 legacy 与新 Layer 3 路径。
- [ ] 比较 approved text hash、unit 音频身份、时长、schedule、cue 和最终音轨。
- [ ] 将 `language="Chinese"`、`block.zh`、`zh-natural.mp3`、`zh-synced.mp3` 限制在 legacy adapter 内。
- [ ] 在等价证据通过前，不切换周六生产默认入口。

验收：所有差异有解释，现有中文审核和发布收据不被新路径重标。

#### L3-012 恢复、远端执行与可观测性

- [ ] cache key 包含 candidate/speech-job/adapter/checkpoint/implementation hash。
- [ ] MacBook、Spark 或其他 runtime 使用同一 job identity；远端导入逐文件校验。
- [ ] 失败恢复从最后一个已验证 unit 继续，不重新调用已成功的付费阶段。
- [ ] 记录每阶段耗时、模型调用、重试、成本、失败分类和 artifact 指针；不得记录凭据。

验收：模拟中断、旧缓存、部分远端导入和重复恢复，均不覆盖旧产物或重复计费步骤。

### Layer 3 完成门槛

- [ ] 通用 renderer、调度器和 Audio Package producer 不含目标语言硬编码。
- [ ] `zh-Hans` legacy shadow 等价通过，原中文生产未被破坏。
- [ ] `ko` 完成短探针、多段 fixture、整篇自然音轨、回转录筛查和韩语人工全文听审。
- [ ] 每个 unit、track、caption、schedule 与批准文字 hash 一致。
- [ ] `audio_unavailable` 能作为明确、合法的文字版结果。
- [ ] 未做 Layer 4 发布、HTTP、设备或现场验证，不宣称多语言产品已经上线。

## 5. 推荐执行顺序

```text
L2-001 policy
  → L2-002 producer
  → L2-003 model review
  → L2-004 language plugins
  → L2-005 human review
  → L2-006 zh-Hans shadow
  → L2-007 ko fixture
  → L2-008 full ko text

L3-001 adapter contract
  → L3-002 renderer + L3-003 decode gate
  → L3-004 scheduler
  → L3-005 audio package
  → L3-006 ko probe
  → L3-007 ASR + L3-008 captions
  → L3-009 full ko audio
  → L3-010 human playback review
  → L3-011 zh-Hans migration
  → L3-012 recovery/observability hardening
```

Layer 2 的 P0 全部通过后才能开始正式 Layer 3 韩语合成。Layer 3 的通用骨架可以并行开发，但只能使用合成 fixture；不得绕过 Layer 2 人工批准门禁运行真实整篇韩语音频。

## 6. 建议拆分提交

1. `feat: add target-language policy and text runner`
2. `feat: add independent target-language review plugins`
3. `feat: adapt legacy Chinese candidates to multilingual text`
4. `test: add reviewed Korean text fixtures`
5. `feat: add locale-neutral speech renderer and scheduler`
6. `feat: produce target-language audio packages`
7. `test: validate Korean speech capability and screening`
8. `docs: record full Korean text and audio acceptance evidence`

每个提交只推进一个层内接口或一组对应验证；真实模型运行、人工批准和发布证据不得用单元测试结果代替。

## 7. 从 Dev 片段到周日可用的里程碑

本节把已有任务排成可验收的依赖链。目标首先是**周六完成预制、周日可播放**的 `four_layer_release`；周日麦克风实时字幕保持独立 `live_session`。任何阶段只在绑定相同来源、locale 和 hash 的证据通过后推进，不用 Dev 页面可播或机器分数替代人工审核。

### M0：把已验证进度纳入 Dev

- [x] 从 `dev` 基线集成 Layer 1 逐句机器裁判、schema、anchor 修订和定向测试；保留 `humanApproval=false`、`productionTranslationEligible=false`。旧 anchor/source package 因实现 hash 改变而失效，按新身份生成，不重标旧收据。
- [ ] 在干净 shadow 输入上重放确定性构建和机器裁判；核对 receipt、package、anchor 的 JSON/file SHA，证明只进入 `candidate_ready_for_translation`。使用真实正式输入时，英文人工审核仍须产生 `ready_for_translation`。
- [ ] 对 `zh-Hans`、`ko`、`es`、`vi` 六句 POC 收据做只读回归：schema、同一英文来源、逐 locale 候选与音频 hash、低于 ASR 门线的复核状态。Dev 演示资产保持 `productionEligible=false`。

完成证据：合并提交、CI、更新后的 Layer 1 shadow 收据和未改变生产门禁的测试。集成代码本身不代表已在远端 Dev 或周日现场验收。

### M1：完成正式 Layer 2（L2-001—L2-009）

- [ ] 从一份人工英文审核的 `ready_for_translation` 源包出发，按 `sourcePackage + anchor + locale + policy + implementation` 建不可变单语言 job；初译、独立复核、语言插件和人工批准各有独立收据。先实现 `zh-Hans` 与 `ko`，`es`、`vi` 只有在各自策略和审核者就绪后加入。
- [ ] `zh-Hans` 对已批准整篇做 legacy→v2 golden shadow；韩语先做含否定、数字、专名、引文和经文的 fixture，再做一篇真实整篇。缺经文版本或授权政策时保持 pending。
- [ ] 验证修改 Layer 1 会使全部 locale 失效；修改某语言 policy、译文或人审只使该语言下游失效。旧收据复制、漏审、错序、跨语言缓存和恢复中断必须 fail closed。

完成证据：两语言 schema 与语义 validator、完整 coverage、不可变 `human_translation_approved` candidate 和逐 group 人审收据。六句机器通过及 PDF 中文阅读稿不能替代这些证据。

### M2：完成正式 Layer 3（L3-001—L3-012）

- [ ] renderer 只消费正式 `sermon-target-language-speech-job-v1` 和已批准的同 locale 文字；授权、checkpoint hash、locale 能力及文本 hash 在模型加载前核对。先用合成 fixture 实现通用 unit receipt、完整解码、自然语速排程和字幕，随后做中文 golden timing 等价。
- [ ] 为 Audio Package 加语义 validator：核对实际 speech job/schema、来源与候选 hash、每个 unit/track/caption/schedule 的文件 hash；失效 key 必须覆盖 candidate、job、voice/checkpoint、音频、字幕和排程。现有片段 POC 的 `poc-speech-job` 与只含 candidate/audio/schedule 的失效 key 不满足此门槛。
- [ ] 停顿只从 Layer 1 已审英文声学证据出发，Layer 3 判断能否放在目标语言完整自然句界。逐句报告局部起点偏差、尾延迟、overrun 和自然度；不以总时长接近或词组拼接掩盖局部失败。原声指纹如供周日自动定位，由本层生成绑定来源和实际音轨的 companion receipt，Layer 4 只发布和核验。
- [ ] 韩语按短探针→10–20 group→整篇顺序完成回转写、实体音频解码、字幕校验、母语全文听审和同视频 1 倍速检查。语音能力或授权不足时生成合法 `audio_unavailable` 包供纯文字路径，不借用中文音轨。

完成证据：正式 Audio Package 的机器与人工收据、局部排程报告、中文等价对照和失败恢复验证。VoxCPM2、MOSS、AuK 的短样本只保留为 challenger；模型替换须另有同输入 A/B 和目标语母语听审。

### M3：周日预制播放验收（下游依赖）

- [ ] 为每个要交付的 `pageId + targetLocale` 生成同源、同 locale 且 hash 匹配的 Layer 4 Release Package；纯文字版本也绑定状态为 `audio_unavailable` 的 Layer 3 包。仅在上游文字、音频和页面各自的人审状态满足门禁后进入发布。
- [ ] 周六发布后逐文件 GET/SHA 与音频 Range 206；周日早上在实体设备检查目录刷新、下载、离线、蓝牙/扬声器、同一录制 1 倍速播放和定位；场地音频路由及会众可读性另留现场收据。HTTP、设备和现场状态分别报告。
- [ ] 周末 Supervisor 保留 `dual_pdf`、`four_layer_release`、`live_session` 三种独立 scope；按 lease/身份恢复已验证单元，遇缺来源、审核或媒体时停在具体层，不因 PDF 完成或 Dev 页面可播宣称周日就绪。

完成证据：一次真实整篇同源、同 locale 的四包链及周六到周日的 HTTP、实体设备、场地收据；再用另一周次验证恢复与复用。阈值须在运行前固定，不能事后按结果调整。

### 可选：已审文字辅助周日实时字幕

四层预制音轨不进入现场低延迟字幕链。若需复用 Layer 2 已审译文，新增确定性投影 adapter，把已批准的来源、locale、候选、人审 hash 映射进 Saturday Evidence Bundle / Sunday Runtime Pack；仅允许审核过的术语、经文和受控示例进入现场 prompt。仍须人工确认周六/周日同篇、检查有效期和 capability；现场 `asr.final` 是唯一事实源，Pack 不合格降为 `none` 基线。韩语/西语实时字幕另需模型、UI、设备和现场验收，不由预制韩语音轨自动获得资格。参见[Context Pack 合同](saturday-to-sunday-context-pack-plan.zh.md)和[周日运行入口](sunday-live-agent-runbook.zh.md)。
