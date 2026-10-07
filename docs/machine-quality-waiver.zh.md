# 机器质检豁免与 TTS 前时长预算

## 决定

2026-10-06，Jony 在项目线程里确定了以下规则：

- 中文、韩语、西语都改为**机器质检通过后自动发布**。人工改为发布后抽查，发现问题再发修订版。证道起止时间仍由人输入。
- “每句最多落后 8 秒”是同传听感的目标，保留。时长控制前移到 TTS 之前，不再依靠事后批例外（例如 10/4 的 62 秒）。
- 翻译和复核可以用同一个模型，前提是有可测量的质量证据。
- 修复按**单句**计数：先修 2 次，不行再修 2 次，每句最多 4 次。5% 也按句子（英文 source unit）计算，一个含多句的组按它的句数计入。
  - 音频仍不过关：这一句只显示字幕，不配音。
  - 文字仍不过关：这一句改为显示英文原文。
  - 不配音的句子超过全篇 5%：整个语言改为只发文字（`audio_unavailable`）。
  - 失去译文的句子超过全篇 5%：该语言暂停发布。

2026-10-07，Jony 在决策卡片上选了“允许精简”：**配音可以像同传一样精简措辞，字幕和阅读稿保持完整译文。** 只精简 8 秒预算标为 `shorten` 的组；可以删重复、口头填充、同义复述、插入语和举例细节，不能删主要论点、呼召、否定、数字、人名、经文出处和引语出处，也不能加内容。每处删减都声明为完整译文里的一段及其类别。声明的片段必须确实已从口播稿删去，声明的总长度要能解释删掉的长度（改写允许少量出入：3 个语音单位或完整译文的 10%，取较大者），不能声明一段无关的片段来掩护没声明的删减；每条声明各占一处已删去的位置，同一段重复声明或几段互相重叠都会失败。

机器质检豁免**不是**人工批准。豁免收据里 `humanApproval` 保持 `false`，`reviewKind` 写为 `machine_quality_waiver`，页面必须显示 `disclosure` 文案。

## 组件

| 环节 | 入口 | 作用 |
|---|---|---|
| L2 逐组确定性检查 | `language_review_plugins/ko_weekly_auto.py`、`es_weekly_auto.py`（共享 `auto_qc_text_common.py`） | 每周通用，不写死任何一篇讲道。检查目标文字脚本与占位符（西语须以拉丁字母为主；中文须为简体，假名、谚文或繁体字都会失败）、未翻译的英文（西语只有一个词的组也算，原样照抄即失败；Amén、Jesús 这类西语拼写、No、Amen 等共用词和术语表人名除外）、语域（西语不得用 vosotros，包括省略主语的 decís、sois）、术语表人名（按完整词匹配：西语 Ana 不能靠 mañana 里的字母算出现；中韩名字后面可以接助词）、经文出处（英文说了就必须有，没说不能加；带书卷名的引用要对上同一卷书，66 卷的中韩西名称在 `_BIBLE_BOOKS`；一边带节号、一边只说到章时按章比较书卷；英文带书卷的章节在译文里只剩数字（“John 3:16” 译成光秃的 “3:16”）时，同组任何位置都没写这卷书就判 `missing book`；“John 3 verse 16” 这种不说 chapter 的读法也算到节）、数字（英文说的数字须以数字或目标语言读法出现，说了几次就要出现几次（“five loaves and five fish” 译成“五个饼和六条鱼”会失败）；中文单独的“一”只有后面跟量词（一次、一个、一条）或在句末时才算数字 1，“一直、一起、一样”不算；只扣掉带节号的经文引用本身占用的数字，同值的普通数量照查（“John 3:16 mentions three people” 漏了三个人会失败），只说到章的引用仍按数字查，含小数和 “nineteen ninety-nine” 这类年份读法；译文写出的阿拉伯数字必须是英文说过的值，序数、经文、时间、书卷序号、“5万/5만/50 mil” 这类大数单位都按英文核对，单独的 1 不查，因为英文冠词常译成 1。目标语言的数字词和序数没有可靠的表面形式，由回译和 `added_number`、`wrong_ordinal` 注错校准把关） |
| L2 整篇检查 | `scripts/target_text_auto_qc.py` | 长度离群：与本篇中位数比较。**回译比对**：第一次调用只给目标语言文字，翻回英文；第二次调用对比冻结英文和回译，判断有没有漏译、增译、否定、数字、人名、经文、意思偏移。模型调用由调用方注入，没有回译结果的组不能判为通过。**口播模式：** 带 `condensation` 的精简组（由 `spoken_condensation.py qc-groups` 标出）不做长度离群检查，比对改用核心意思标准：允许的删减最多算轻微问题；丢了或改了主要论点、呼召、否定、数字、人名、经文、引语出处，或有任何增译、意思偏移，仍是重大问题。每组结果记 `mode`，收据记 `condensedGroupIds` |
| 配音精简 | `scripts/spoken_condensation.py` | 读 8 秒预算，只为 `shorten` 组生成精简请求（英文句、完整译文、`maxSpeechUnits`）。预算记录片段时长和每组的片段内原声时间；生成请求前先核对这些时间就是冻结锚点的时间（整体只差一个片段偏移），再用预算自己的语速、排程参数和这份候选的文字重算一遍，结果必须与预算完全一致，别的时间轴或改过的决定不能指定要精简哪一组。精简模型由调用方注入；每次结果都做确定性检查：不超字数、删减段必须是完整译文的子串且类别允许、数字人名经文照常检查，不过关的带着问题重试，最多 2 次。记录（`sermon-spoken-condensation-record-v1`）绑定完整候选、预算（含合成身份）和精简模型身份（与回译身份同样要求非空 `backend`、`model`、`modelRevision`、`cacheNamespace` 和 `settings`，规范化为有限 JSON 后取哈希），导出现有格式的 revision brief，口播候选沿用 L2 链生成。之后 `bind` 把口播候选绑回记录：未精简的组必须与完整译文相同，精简组重新核对字数、省略段和确定性检查；复核改变口播文本时，须重新生成描述最终文本的精简记录，旧记录不能绑定 |
| L3 单句检查 | `scripts/target_audio_auto_qc.py` | TTS 之后马上检查，指标一律从每句 WAV 解码，不接受调用方提供的指标：时长异常（与本篇语速中位数比较，以及与原声时长之比）、截断、近乎无声、静音过多、长停顿、削波、句首句尾静音过长。每句的原声时长 `sourceSeconds` 必须为正数，并记入结果；签发试听豁免时按冻结锚点逐句核对（口播稿该组首句起点到末句终点，误差 ≤ 1 ms），调用方不能用 0 或拉长的时长关掉“与原声时长之比”的检查。回转写两级：小 ASR 标出的疑点由强 ASR 复核（必须是另一个模型），两边都不一致才判失败。每个 ASR 结果都绑定所听音频和预期文字的哈希、模型，以及规范化运行设置的哈希 `settingsSha256`（后端、语言与提示选项、解码、缓存命名空间、相似度算法）；一级 ASR 的设置取自绑定的筛查收据（`screening_asr_settings`）：只有 `sermon-target-language-audio-screening-v2` 收据记录了完整运行设置 `asrSettings`（协议、模型与修订、批大小、解码、精度、设备、推理运行时、筛查脚本哈希、阈值和相似度算法）及其哈希，v1 收据仍可供人工试听链读取，但不能签发试听豁免，须用 v2 重新筛查；音频重合成后沿用旧分数无效，这一句停在 `pending_primary_asr`，不能只凭声学指标通过 |
| L3 整轨核对 | `scripts/target_audio_auto_qc.py --track-package` | 单句检查只听单句 WAV，整轨核对把它们绑到听众实际听到的音轨：PCM 母带必须与各句音频按排程起点逐样本放置的结果完全一致（漏句、错序、旧音频都会失败）；MP3 解码到 12 kHz 后，逐个可听的 50 ms 窗口比较母带波形，相关性须 ≥ 0.94、相对误差须 ≤ 0.35；不允许用整篇的通过比例掩盖短句替换。响度包络与长度差保留为辅助检查。签发试听豁免时，核对结果的比较参数必须等于发布标准 `TRACK_ENVELOPE`，比较方法须与音轨格式一致（MP3 必须有通过的逐窗波形证据） |
| 8 秒预算 | `scripts/target_audio_predicted_schedule.py` | 用已测音频拟合各语言语速，再用正式排程公式按**预测时长**排一次。超窗的组给出 `maxSpeechUnits`，供口播修订一次改到位。预算记录 `sourceSeconds` 和每组的 `sourceStart`/`sourceEnd`，以便重算核对。语速绑定 speech job 的合成身份（adapter、配置、模型版本、音色、说话人、conditioning、语言参数、文本规范化）和所测音频的哈希；身份不同就拒绝预算，需要重新拟合 |
| 注错校准 | `scripts/auto_qc_seeded_errors.py` | 在干净成品里注入已知错误，统计每类检出率和干净样例的误报率。只有出现干净版本没有的新问题才算检出（错句配音必须由 ASR 判出），不会把原有误报算成检出。文字类含换书卷（wrong_book）和改序数（wrong_ordinal：英文说 first 而译文的“第一/첫 번째/primer”被改成下一个；英文没说序数的组则在句首加“第二，/둘째, /En segundo lugar,”），音频类含换成别句的配音（wrong_sentence，需要注入 ASR transport）。口播类（`spoken.*`）只注入精简组：换成别组内容（swapped_content）、追加别组内容（added_content）、翻转否定（flipped_negation）、删掉最长的一个分句（dropped_claim，模拟把论点、呼召或引语出处当成可删的插入语删掉）。删冗余本来就是精简允许的，所以口播类注的是“说的意思变了”；和 `semantic_negation`、`added_number`、`wrong_ordinal`、`swapped_quantity`（两个英文数量在译文里对调，比如“十二个儿子和四十个女儿”变成“四十个儿子和十二个女儿”，数字都还在，只有意思错了）一样，只有回译判出新的重大问题才算检出，人名、数字等表面检查同时判失败也不算回译的检出 |
| 豁免收据 | `scripts/machine_quality_waiver.py` | 汇总最终 QC 结果，按上面的 5% 规则决定这个语言是自动发布、只发文字还是暂停。先核对 QC 收据确实检查的是这份候选（每组译文哈希）和这份音频包（候选哈希、每句音频哈希），对不上就报错 |
| 门禁收据 | `scripts/machine_quality_release_basis.py` | 生成并校验两种绑定到具体产物的收据：**译文豁免**（`sermon-target-language-machine-text-waiver-v1`，绑定一个 L2 候选；有精简组时还必须绑定一份通过的精简绑定，组别完全一致，并记录 `condensedGroupIds` 和 `condensationBindingJsonSha256`。这样的收据只能当口播稿的依据，L4 不接受它作完整译文）和**试听豁免**（`sermon-target-language-machine-audio-waiver-v2`，绑定一个 L3 音频包、它的 ASR 筛查和口播稿的译文豁免） |

文本 QC 逐组记录 `englishSha256` 与 `sourceUnitIdsSha256`，签发豁免时按候选的 source-unit 顺序与冻结 anchor 中的英文核对。旧 QC 收据缺少这些字段时须重新检查，不能沿用。音频 QC 的 `thresholds` 必须等于当前标准 `THRESHOLDS`，放宽设置的结果不能授权试听豁免。

发布 v4 中，试听豁免必须同时绑定口播文本豁免；仅口播文本使用豁免、音频仍为人工审核的组合继续有效。

试听豁免 v2 从校准通过的 QC 行提取 `secondaryAsrModel`（`model` 与 `modelRevision`），并在使用二级 ASR 的单句结果中记录相同身份。`--secondary-asr-model` 仅是可选的一致性断言，不能替换 QC 身份。迁移时，未使用二级 ASR 的旧 v1 收据仍可验证；含二级 ASR 的 v1 收据必须用与当前实现、校准和产物匹配的 QC 重新签发为 v2，不能靠旧字符串补出修订身份。

## 校准门槛

只有满足以下全部条件，才允许豁免：

- 校准收据的 `implementationSha256` 与当前 QC 代码一致。QC 代码包括 `scripts/spoken_condensation.py`（L4 不重跑精简检查，只认绑定），以及准入候选、签发和验收豁免的门禁本身（`scripts/machine_quality_waiver.py`、`scripts/machine_quality_release_basis.py`）。代码一改，必须重新校准。签发后的译文豁免和试听豁免在 L3、L4 验证时也要求收据的 `implementationSha256` 等于当前实现，所以代码改动后旧收据不再能授权发布，必须重新校准、重新签发。文字和音频 QC 收据也记录运行时的 `implementationSha256`，旧代码生成的 QC 结果不能搭配新校准使用。
- 校准时回译检查实际参与了（`semanticChecksIncluded=true`），且 `text.semantic_negation`、`text.added_number`（在英文不含数字的组里加一个用目标语言写出的人数）、`text.wrong_ordinal` 注错必须新增明确的回译问题；`text.dropped_half`（删掉半句）也只认回译问题，长度检查同时判失败不算，因为在长度范围内的小删减只有回译能发现（序数没有可靠的表面检查：first 常译成“起初/처음/en primer lugar”）；确定性规则发现的表面错误不能计为这一类的检出。
- 本次 QC 用的回译运行身份 `semanticIdentity` 必须包含非空 `backend`、`model`、`modelRevision`、`cacheNamespace` 和非空 `settings` 对象（声明实际解码、推理等设置）。规范化 JSON 后绑定哈希，拒绝非有限数值。该身份、ASR 模型和两级 ASR 的设置哈希（校准记录为 `asrSettingsSha256`）必须与校准时一致；改变设置、缓存命名空间、模型修订或后端，必须重新校准。
- 按本次交付所需注错类别的计数重算总检出率 ≥ 95%，每类 ≥ 90%。收据中每类及总体的计数与预存比率必须一致；布尔值、负计数或检出数大于试验数均拒绝。每一类注错都必须实际试过（`trials > 0`）；缺一类或某类零样本都算校准不足。要发配音时，校准还必须包含音频各类；只发文字时，音频类的结果不影响放行。QC 判过精简组时，校准还必须包含口播各类（`spokenIncluded=true`）。
- 干净样例误报率按 `cleanFalsePositives / cleanChecked` 重算并核对，必须 ≤ 10%，且实际检查至少一个干净样例。

只做离线确定性检查时，“删掉半句”这类错误只能检出约 58% 到 75%（见测试样例）。这正是必须加入回译检查的原因。

## 命令

```bash
# 用已有正式音频拟合语速（rows: [{text, audioSeconds, audioSha256}]，--speech-job 为这些音频的 job）
python scripts/target_audio_predicted_schedule.py fit --input rate-input.json --speech-job measured-job.json --out rate.json
# TTS 前预测排程（groups: [{gid, sourceStart, sourceEnd, text}]，时间相对 clip；--speech-job 为本次要合成的 job）
python scripts/target_audio_predicted_schedule.py budget --input groups.json --rate rate.json --speech-job job.json --out budget.json
# 单句音频 QC（units: [{groupId, text, sourceSeconds, wavPath, asr: {primary, secondary?}, priorFailedAttempts?}]，
# 每个 ASR 结果为 {similarity, audioSha256, textSha256, model, modelRevision?, settingsSha256}）
python scripts/target_audio_auto_qc.py --input units.json --out audio-qc.json
# 整轨核对（读取音频包里的排程、单句音频和音轨；MP3 需要 ffmpeg 和同名 .wav 母带）
python scripts/target_audio_auto_qc.py --track-package audio-package.json --out track-check.json
# 精简记录导出 L2 revision brief（精简本身需要注入模型 transport，没有离线命令）
python scripts/spoken_condensation.py brief --record condensation.json --candidate full-candidate.json --out brief.json
# 口播候选生成后绑回记录，再写出口播 QC 的输入（精简组带 condensation）
python scripts/spoken_condensation.py bind --record condensation.json --candidate full-candidate.json \
  --anchor anchor.json --spoken-candidate spoken-candidate.json --policy policy.json --out condensation-binding.json
python scripts/spoken_condensation.py qc-groups --binding condensation-binding.json --anchor anchor.json \
  --spoken-candidate spoken-candidate.json --out spoken-qc-groups.json
# 离线注错校准（不含回译和 ASR transport，因此不能单独解锁豁免；spokenGroups 为上面的 qc-groups 输出）
python scripts/auto_qc_seeded_errors.py --input calibration-input.json --out calibration.json
# 豁免决定
python scripts/machine_quality_waiver.py --locale ko --candidate candidate.json \
  --text-qc text-qc.json --audio-qc audio-qc.json --audio-package audio-package.json \
  --calibration calibration.json --out waiver.json
# 译文豁免收据（代替人工译文审核收据）
python scripts/machine_quality_release_basis.py text --source source.json --anchor anchor.json \
  --candidate candidate.json --text-qc text-qc.json --calibration calibration.json --out text-waiver.json
# 口播稿有精简组时，还要给精简绑定；这份收据只能作口播稿依据，不能当完整译文的依据
python scripts/machine_quality_release_basis.py text ... --candidate spoken-candidate.json \
  --condensation-binding condensation-binding.json --out spoken-text-waiver.json
# 用译文豁免进入第 3 层：写出 speech job v3
python scripts/prepare_target_language_speech_job.py ... --text-release-basis text-waiver.json --out speech-job
# 试听豁免收据（代替人工试听收据）；ASR 标出的句子必须有强 ASR 复核
python scripts/machine_quality_release_basis.py audio --package audio-package.json --screening screening.json \
  --audio-qc audio-qc.json --track-check track-check.json --text-waiver spoken-text-waiver.json \
  --anchor anchor.json --spoken-candidate spoken-candidate.json \
  --calibration calibration.json --secondary-asr-model gpt-transcribe --out audio-waiver.json
# 第 4 层：精简过的配音要带同一份精简绑定（sermon_unified_delivery 的 inputs.condensation_binding 同理）
python scripts/build_full_video_app_release.py prepare ... --condensation-binding ko=condensation-binding.json
```

## 当前接线范围

**已接上：**

- **L2 → L3：** 签发译文豁免时，文字 QC 记录的 `policyJsonSha256` 必须等于候选的 `translationPolicySha256`（不带政策或带别的政策跑 QC，人名术语检查就没按这份候选做）；锚点必须就是英文源包 `anchors.artifact.jsonSha256` 绑定的那份（L4 拿不到锚点，不能拿一份删短的锚点凑覆盖）；候选各组的 `sourceUnitIds` 拼起来必须按顺序恰好覆盖冻结锚点的全部英文句子；漏掉的句子没有可检查的结果，所以由签发时直接核对，收据再绑定这份候选的哈希。`prepare_target_language_speech_job.py` 接受译文豁免收据（`--text-release-basis`）。候选每组的语义复核必须 `status=pass`、四项检查（`completeMeaning`、`negationsNumbersNames`、`quotationAttribution`、`noAddedMeaning`）全部 pass，且 `issues`、`uncertainty` 都为空，与 speech job 交接的要求相同；模型留下问题或不确定的组要走新修订，不能靠豁免放行。这时候选保持 `machine_review_pass_human_review_pending`、`humanReview.translation=pending`，写出的 speech job 是 v3：`inputs.textReleaseBasis` 绑定豁免收据，`textPolicy` 为 `exact_machine_waived_target_text`。人工收据仍写出原来的 v2，已有的 job 身份不变。所有读取 speech job 的生产者（音频包构建、单句完整性、严格链 L3 准备、恢复计划、ASR 筛查）都接受 v2 和 v3。
- **L3：** 音频包仍按构建结果保持 `machine_screened`（ASR 全过）或 `candidate`（ASR 标出疑点），`humanApproval=false`。试听豁免收据必须绑定一份通过的整轨核对（`trackCheckJsonSha256`），可以代替人工试听收据，通过 `validate_audio_screening_review`、`inspect_canonical_audio`（配置项 `machineWaiver`）和 `sermon_unified` 的 `audio` 审核。ASR 标出的每一句都必须有强 ASR 复核通过。筛查收据里每一句的 `status` 必须与它自己的相似度、阈值和差异一致；签发时还用口播稿原文按筛查脚本的同一算法（`score`）重算每句的相似度、差异和结论，必须与收据完全一致，不能把低分句标成 pass。
- **sermon_unified：** `ingest_review` 接收两种豁免收据，把该步记为 `review=waived`、事件 `review.waived`，不写 `approvedAt`。`translation_approved` 和 `listen_approved` 两个范围接受 `waived`；大纲与默想仍要求人工 `approved`。

- **L4：** `build_full_video_app_release.py` 和 `sermon_unified_delivery` 接受译文豁免和试听豁免（试听豁免必须绑定口播稿的那份译文豁免）。只要有一项是机器质检，就写出 [release v4](../schemas/sermon-target-language-release-package-v4.schema.json)，路径为 `/releases-v4/<pageId>/<locale>.json`：`contentStatus`、`audioStatus` 各自为 `human_reviewed` 或 `machine_checked`，`reviewBasis` 逐项记录完整文稿、口播稿、音轨用的是人工收据还是豁免收据，`disclosure` 是该语言的披露文案。完整文稿为机器质检时，正文用 [content v3](../schemas/sermon-full-video-text-content-v3.schema.json)（`status=machine_checked`，带同一份 `disclosure`），静态页面也显示“机器质检”和披露（披露前的标签跟披露同一语言：机器质检 / 기계 품질 검사 / Control de calidad automático）。三项都是人工时仍写 release v3，什么都不变。v4 还记录 `captionText`：配音字幕显示 `full_text`（完整译文）还是 `spoken_text`（口播稿）；口播稿与完整译文相同时为 `full_text`。完整译文和口播稿的组 id 必须按顺序完全一致（网页和 iOS 按组 id 对齐两套字幕），否则构建失败。**配音精简时**，口播稿的译文豁免必须带精简绑定，L4 核对绑定的哈希与收据一致、绑定的正是这份完整译文和这份口播稿、与完整译文不同的组正好是精简组，然后写 `captionText=full_text` 和 `spokenCondensation`（精简记录哈希、绑定哈希、精简组），静态页面说明配音为同传式精简口播、配音字幕显示完整译文。音轨资产里的字幕文件不变（仍是口播稿，L3 的哈希绑定照旧），客户端按 `textGroupId` 把字幕文字换成完整译文，时间仍跟配音。精简口播只能是机器质检的配音；带精简组的收据不能当完整译文的依据。
- **目录：** 封存时同时写出 [catalog v4](../schemas/sermon-multilingual-catalog-v4.schema.json)（`/multilingual-v4.json`）和 `/multilingual-v3.json`。v3 是 v4 去掉所有机器质检语言后的投影，旧客户端读到的内容不变；只有机器质检页面、没有人工基线时拒绝封存，因为投影会是空目录。托管发布对两份目录都做比较交换和回读，`validate_catalog_snapshot` 要求投影与 v3 完全一致。
- **客户端：** 网页和 iOS 先读 v4，404 时读 v3；v4 无法读取或校验失败也退回 v3 并记录错误。机器质检的语言显示“机器质检 / 기계 품질 검사 / Control de calidad automático”和发布包里的披露文案，机器质检的产物不会显示“已审核批准”。`captionText=full_text` 时，网页和 iOS Core 用完整译文作配音字幕；有 `spokenCondensation` 时，网页的提示文案说明配音为同传式精简口播（iOS App 的对应文案待补）。旧版 iOS 只读 v3，看不到机器质检的语言，更新到新版后才能看到。
- **海报：** `build_multilingual_sermon_posters.py` 有 v4 时读 v4，审核标签按两项状态分别写明（例如“译文与配音经机器质检 · 未经人工审核”）。只会写 v3 的旧工具（`assemble_multilingual_v3_update.py`、`bind_published_alignment_catalog.py`）遇到带 v4 的快照会拒绝，避免两份目录不一致。

第 1 版豁免只放行**每一句都通过**的语言：有句子要只显字幕或改显英文时，收据不会生成，这个语言仍走人工路径。

**还没有接上：**

1. 新版 iOS 客户端提交 App Store / TestFlight；生成英文对照（`build_published_english_reference.py`）、对齐绑定和听审统计目录的工具仍只读 v3，还不能为机器质检周次生成这些附加资源。
2. 回译检查的真实模型 transport（沿用 L2 的后端身份与缓存规则），以及首次真实校准。
3. 冻结 policy 时，为韩/西选择 `ko-weekly-auto-v1` / `es-weekly-auto-v1` 插件，并把 `requiredChecks` 设为 `auto_qc_text_common.REQUIRED`。
4. 只显字幕的句子、改显英文的句子和只发文字的语言（`audio_unavailable`）。
5. 配音精简：配音字幕显示完整译文、发布包绑定精简记录、网页文案已完成；iOS App 的精简提示文案待补。精简模型和回译模型的真实 transport，以及首次口播校准，需要授权后运行；没有口播校准，精简稿签不出豁免。
6. 英文转写审核、页面信息、大纲与默想的机器检查，以及每周发布授权改为长期授权。
7. 严格链（`sermon_strict_candidate_bridge` / `sermon_strict_gate_admission`）的门禁决定把收据记为人工批准，所以严格链目前只收人工收据，遇到译文豁免会以 `strict_bridge_requires_human_receipt` 拒绝。译文豁免目前只能走 `prepare_target_language_speech_job.py --text-release-basis`；严格链要接受豁免，门禁决定需要单独记录豁免状态。
