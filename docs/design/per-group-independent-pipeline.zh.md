# 逐组独立任务：从 Layer 2 到 Layer 3，发布前唯一合并

状态：**设计稿；`DEV-GRP-001`（逐组记录、输入键、只读 `plan`）与 `DEV-GRP-003`（逐组预算上界）已实施；`DEV-GRP-002` 的按组 ID 返修（#1072）与合并第 1–2 步的 candidate 组装（`orchestration/group_assembly.py`）已实施，并行 worker、单飞锁与按 provider 路由停止尚未实现；其余批次未实现**。backlog 前缀 `DEV-GRP`（见文末分批计划）。本页不改变任何现行门限、豁免规则或 schema；不授权付费、Spark 独占会话或发布。Layer 2 逐组返修（按组 ID 重做）由另一分支的“Layer 2 revise-by-group-ID”实现承担，对应 `DEV-GRP-002`；本页定义它写入的逐组记录合同和它下游的其余各步。

## 一、为什么要改

2026-10-18 周产（来源 `15030286`，390 句、402 组）中，操作者在每个语言批准了 7–14 组的修订，流水线却只能整篇重跑：

| 现象 | 位置 | 根因 |
|---|---|---|
| 改一个语言插件，全部旧证据作废 | [`text/controller.py`](../../packages/production/src/tongxing_production/text/controller.py) `code_identity()` | Layer 2 job 身份哈希全部 `scripts/**/*.py`、`packages/production/src/**/*.py`、schema 与术语表；任何代码字节变化都是新 job，不区分是哪一步的代码 |
| 部分恢复只能串行 | [controller 文档](../canonical-layer2-controller.zh.md) execution v7 | `layer2PartialRecovery` 要求 `groupWorkers=1` |
| 重放时返修额度为 0 | [`text/auto_repair.py`](../../packages/production/src/tongxing_production/text/auto_repair.py) `_affordable_repairs`、`token_cap` | 额度 = 首轮调用与 token 的 10%（至少 `MINIMUM_REPAIR_CALLS`）；重放时首轮全部命中缓存，按 0 次计算，只剩保底 2 组 |
| 候选、豁免、音频只收整篇 | [`text/candidate.py`](../../packages/production/src/tongxing_production/text/candidate.py) `admit_evidence`；[`audio/speech_job.py`](../../packages/production/src/tongxing_production/audio/speech_job.py) `validate_target_candidate`；[机器质检豁免](../machine-quality-waiver.zh.md) | 准入要求全部组一次给齐、插件逐组 pass；speech job 要求 `reviewedGroupIds` 等于全部组；校准绑定整份成品的 `textGroupsSha256`／`audioUnitsSha256` |

操作者的方向：**每个 Layer 1 组（一个锚点单元，通常一句）从翻译到配音是一个独立任务，只在发布前合并；操作者只给组 ID。** [AGENTS.md](../../AGENTS.md) 的四条不变式（诚实标签、哈希绑定、四层、证据分立）照旧成立。

## 二、两段结构

```text
Layer 1 冻结（媒体 hash + 批准窗口 + 源包 + 锚点与组边界）           ← 全局
  └─ 每个 locale × 每个 group g，各自独立、可并行：
       T 翻译 → R 独立复核 → P 语言插件 → Q 回译文字 QC 判定
         → (C 口播精简，仅 shorten 组) → S TTS（preview_only）→ A ASR 回查 → U 单句音频 QC
       结果写入逐组记录，按输入键复用
  └─ 每个 locale 一次合并 M（整篇）：
       组装 candidate → 整篇文字检查 → 校准 → 译文豁免 → speech job v3
         → 正式 renderer 采纳同字节单元 → 滚动排程与 8 秒检查 → 字幕 cue
         → 整轨核对 → 筛查收据 → 试听豁免（5% 规则）
  └─ Layer 4：按 pageId + targetLocale 照现行 release v4 封存
```

逐组段只产生**中间证据**，从不产生发布物；合并段输出的仍是现行 schema（candidate v2、speech job v3、audio package、筛查 v2、豁免收据），所以 Layer 3 包验证器和 Layer 4 builder 在第一版不需要改。

## 三、现行门禁的归属

判断标准：一个检查的结论只依赖本组输入时归逐组；依赖其他组的结果或整篇统计量时归合并。

| 门禁 | 现在 | 目标 | 理由 |
|---|---|---|---|
| 翻译、独立复核 | 逐组请求，整轮派发 | **逐组** | 提示里的上下文只是前 3 句、后 2 句**英文**（`models.surrounding_context`），不含其他组的译文；组间无依赖 |
| 语言插件 | 逐组函数，整份 receipt | **逐组** | `evaluate_plugin_groups` 已能对单组运行（`models._plugin_group_review` 传 `[reviewed_row]`）；确定性、零模型调用 |
| 候选准入 | 整篇 `admit_evidence` | **合并** | 覆盖与顺序（全部 `sourceUnitIds` 按序恰好覆盖锚点）、translator/reviewer request ID 互斥、schema 都是整篇性质；合并时用逐组记录组装 evidence 后调用原函数，不另写准入 |
| 返修次数账本 | 按英文 source unit 累计 | **逐组**（不变） | [`machine_repair_ledger`](../machine-quality-waiver.zh.md) 本来就按句计数，换修订、重新分组不清零；并行组追加仍用现有独占锁 |
| 返修花费上限 | 首轮的 10% | **逐组**（第六节） | 首轮花费与本次要修哪几组无关 |
| 回译比对、确定性文字检查 | 整篇 `target_text_auto_qc` | **逐组判定** | 回译只给本组目标文字，比对只给本组英文与回译；按请求缓存（`review/qc_text_run.py`） |
| 文字长度离群 | 与全篇中位数比较（`review/text_qc.py` `candidate_length_median`） | **合并** | 中位数是整篇统计量；一组变化可能翻转别组结论。合并时重算，判离群的组以组 ID 退回逐组段 |
| TTS 单元 | renderer 单元 intent 含 `jobJsonSha256`、`candidateJsonSha256`、`unitIndex`、batch 窗口 | **逐组（preview_only）** | 声音只由本组文字与合成身份决定；整 job 哈希和位置只是装配信息（`_reusable_audio` 已把三个整 job 字段排除在复用比较外）。决定 1 的 A/B 未通过，batch 窗口仍属声音身份 |
| ASR 回查、单句声学检查 | 单句 | **逐组** | 结论只看本句 WAV 字节与预期文字 |
| 单句时长异常（与全篇语速中位数比较，`review/audio_qc.py`） | 整篇统计 | **逐组判定用冻结语速文件；合并重算中位数** | 逐组判定改用已绑定合成身份的 `sermon-target-speech-rate-v2`；合并时照现行方法再算一次，不一致的组退回 |
| 8 秒预算预测 | 整篇 `predicted_schedule budget` | **合并前计划** | 排程是前缀依赖：一组变长会推后其后各组，直到空隙吸收。预测确定性、零调用，每次合并前全篇重算 |
| 滚动排程、8 秒滞后、字幕 cue、整轨核对 | 整篇 | **合并** | 同上；超限时报告是哪几组导致，以组 ID 退回 C（精简）或 T |
| 注错校准 | 绑定整份成品 | **合并**，逐组复用试验 | 见第五节 |
| 5% 规则、豁免签发 | 整篇 | **合并** | 按定义是全篇比例 |
| release v4、catalog 封存 | 每 `pageId + targetLocale` | **Layer 4**（不变） | [Layer 4 公开交付](../layer4-four-product-public-delivery.zh.md) |

## 四、逐组记录与输入键

每个 `(L1 身份, targetLocale, translationGroupId, stage)` 一份不可变记录（新 schema `sermon-group-stage-record-v1`，忽略目录内存放，不进 Git）。记录包含：输入键 `inputKey`、各输入的哈希、产出字节哈希、判定 `pass | fail(codes) | stopped(reason) | unknown`、本步实现身份 `stageImplementationSha256`、花费结算引用。新记录只追加；同一键的第二次运行只能读取，不能覆盖。

| 步骤 | 输入键（变了就重做） | 复用的现有机制 |
|---|---|---|
| T 翻译 | 完整 bounded payload 哈希 + route/key 指纹（已含组英文、英文上下文、policy、术语、返修 brief、模型与 runner 身份） | [Layer 2 payload cache](../canonical-layer2-controller.zh.md)（execution v6 `layer2PayloadCache`、预算 v4 `reuseBudgetRoots` 的 `$0 reused`） |
| R 独立复核 | 同上，payload 含 T 的草稿 | 同上；草稿变则 R 必失效（payload cache 已测） |
| P 语言插件 | 插件实现哈希 `plugin_implementation_sha256` + policy `languageReview` + 本组英文与目标文字 | 零调用，插件一改即对全部组重跑 P |
| Q 文字 QC | 回译请求与比对请求哈希（transport 身份、`semanticIdentity`）+ QC 实现闭包 + 修复账本位置 | `qc_text_run` 的按请求缓存；`repair_ledger` |
| C 口播精简 | 精简请求哈希（英文、完整译文、`maxSpeechUnits`、精简模型身份） | `run_spoken_condensation.py` 同输入复用 |
| S TTS | 口播文字哈希 + 合成身份（adapter、checkpoint、speaker、languageParameter、normalization policy、seed、解码设置、`RENDERER_SOUND_IDENTITY_SHA256`） | [`--speculative-from` / `--reuse-from`](../multilingual-intralayer-review-decoupling.zh.md)；**不含** job/candidate 哈希与 `unitIndex` |
| A ASR 回查 | WAV 哈希 + 预期文字哈希 + `asrSettingsSha256` | 筛查算法与评分身份不变；二级 ASR 已“付费调用不重发” |
| U 单句音频 QC | WAV 哈希 + 文字哈希 + 冻结锚点 `sourceSeconds` + `THRESHOLDS` + QC 实现闭包 + 冻结语速文件哈希 | `target_audio_auto_qc` 单句部分 |

**步骤实现身份代替整仓代码身份做复用判断。** 每一步只绑定决定它产出的代码闭包（插件闭包、runner 生产身份、QC 闭包、renderer 声音身份），所以插件改动只使 P 重跑；P 仍为 pass 且文字未变的组，下游 Q、S、A、U 全部保留，因为它们的输入里没有插件代码。整仓 `code_identity()` 不删除：合并 M 记录合并时的完整代码身份，并用**当前**验证器重新校验每份被复用的记录（只校验，不重新生成）。验证器拒绝的记录按失效处理。

**组 ID 稳定性。** 键里不放位置序号。组 ID 和 `sourceUnitIds` 来自 Layer 1；Layer 1 的组边界改变本来就使全部失效（第七节），所以组内不需要处理拆分或合并。

## 五、合并步骤

对一个 locale，合并按下列顺序执行；任何一步失败都输出受影响的组 ID 和原因，不输出半成品：

1. **就绪检查。** 每个组都有当前键下的终态记录：T、R、P、Q 为 pass，或已按第八节停下、待降级。缺失或过期的组列出组 ID 并停止；有 `unknown` 的组时等待对账。
2. **组装 candidate。** 用逐组记录拼出 evidence 和插件 receipt，交给原 `admit_evidence`；得到的 candidate 必须与“同一批记录整篇跑一遍”逐字节相同（第一批的金样测试）。
3. **整篇文字检查。** 长度离群（全篇中位数）、覆盖与顺序。
4. **校准。** 仍是 `sermon-auto-qc-calibration` 在**本次成品**上注错，`inputs` 等于本次 QC 过的组，规则不放宽。为避免一组改动引发全篇重算：校准 v4 把“选哪些组注错”的种子从整份成品哈希改为 `H(注错类别, 组内容哈希)` 的稳定排序，未变的组仍被选中；每次试验（注错后的回译、TTS 漏词音频、两级 ASR）按请求或字节哈希缓存。于是重新校准只为改过的组付费，收据仍是新成品上的完整收据。这改变[豁免文档](../machine-quality-waiver.zh.md)的校准合同；用户已同意，并要求每类注错保留最少新组数，避免样本固定在少数组上（决定 2）。
5. **译文豁免与 speech job v3。** 原 `machine_quality_release_basis.py text` 与 `prepare_target_language_speech_job.py --text-release-basis`；人工路径则用现有 `record-group` / `approve-groups` 逐组收据在此聚合。
6. **正式渲染。** 正式 renderer 以 `--speculative-from` 指向逐组 preview 存储，只采纳声音身份与字节完全一致的单元，并重新签发正式单元收据；不一致的单元在此重新合成（应为 0，否则报告）。
7. **排程与音轨。** 滚动排程、8 秒滞后检查、字幕 cue、PCM 母带与 MP3、整轨核对 `--track-package`。滞后超限按排程定位到组，退回 C 或 T。
8. **筛查与音频 QC 收据。** 用 A、U 的逐组结果按现行格式组装 `sermon-target-language-audio-screening-v2` 与音频 QC 收据；全篇语速中位数检查在这里重算。
9. **试听豁免**（5% 规则、只显字幕／改显英文的现行结论）。
10. **合并清单** `sermon-group-merge-manifest-v1`：L1 身份、locale、按序的组记录哈希、合并时代码身份，以及上面每份产出的哈希。它进入运行报告，不进入公开资源；Layer 4 仍只读现行收据。

合并本身不调用翻译模型；第 4 步只为缓存未命中的试验付费，第 6 步只为身份不一致的单元占用 TTS。

## 六、逐组预算

返修额度改为由本次要做的组计算，与首轮无关：

```text
上限(g) = 剩余次数(g) × 每次上界
剩余次数(g) = 每句上限 − 修复账本中 g 各句已用次数（取组内最大）
每次上界 = 翻译 + 复核（2 次，按 enforced request bound 预留）
         + 回译与比对（2 次）+ 精简（仅 shorten 组，含其重试上限）
         + 二级 ASR（被一级标出的单元）
本次授权 = Σ 上限(g)（g ∈ 操作者给出的组 ID 与合并退回的组 ID）+ 合并第 4 步的缓存未命中试验
```

每句上限、精简重试次数、请求上界都取各自的权威来源（[自动修复](../layer2-bounded-auto-repair.zh.md)、[豁免](../machine-quality-waiver.zh.md)、[运行模型政策](../production-model-runtime-policy.zh.md)），本页不复制数值。预算授权新增逐组明细（组 ID → 预留上界），派发前全额预留；预留不足的组不派发并标 `repair_spend_cap`，不影响已预留的组。命中缓存的组按现有 `$0 reused` 结算，不占额度。

“没有进展就停”（指纹重复、连续两轮失败码不减少）保持逐组判断。系统性失败检测（同一失败码连续出现）保留在 locale 级：它是判断“规则没送到模型”的信号，不能逐组拆开；它只停止新的返修派发，不改动已有记录（第八节）。

并行：逐组任务用 worker 池并行，每个 `(locale, group, stage, inputKey)` 单飞锁。任一付费调用出现未知结果，只停止**同一 provider 路由**（供应商与项目／凭据路由，含该路由下所有模型）的新付费派发，直到对账完成；其他路由上的所有组、所有 locale 照常派发，零调用的确定性步骤（P、排程预测）也照常（决定 3）。只有确认的基础设施故障才切换算力，内容或身份失败从不切换（AGENTS.md 不变式 5）。

## 七、失效规则

| 变化 | 失效并重做 | 保留 |
|---|---|---|
| Layer 1 身份（媒体、批准窗口、源包、锚点、组边界或任一英文句） | 所有 locale 的全部组记录与合并 | 旧记录只供追溯 |
| 某 locale 的冻结 policy（含术语表哈希） | 该 locale 全部组的 T 起（payload 变）及合并 | 其他 locale |
| 翻译或复核的模型、提示、runner 身份 | 该 locale payload 变化的组的 T、R 及下游 | payload 字节未变的组 |
| 语言插件实现 | 全部组的 P（零调用）；P 结论变为 fail 的组退回 T | P 仍 pass 的组的 Q、S、A、U |
| 文字 QC 实现或回译身份 | 全部组的 Q（请求未变的命中缓存）；合并的校准 | T、R、P、S、A、U |
| 一组的译文修订（操作者给组 ID 或合并退回） | 该组 R 起全部步骤；该 locale 的合并 | 其他组全部记录；其他 locale |
| 合成身份（音色、checkpoint、设置、normalization） | 该 locale 全部组的 S、A、U；合并 | T 至 C |
| ASR 设置或评分身份 | 全部组的 A、U；合并 | T 至 S |
| 排程参数、音轨格式 | 只有合并 | 全部组记录 |
| 页面信息 | 只有 Layer 4 | Layer 1–3 |

Layer 1 的英文单句修订仍使全部失效：这是 AGENTS.md 不变式 3 的现行规则。[局部审核设计](../multilingual-intralayer-review-decoupling.zh.md)讨论过更细的英文失效，需另行修订四层合同，不在本页范围。

## 八、出错只修这一组

操作者（Jony）的硬性要求：**出错也只修改这一组。** 任何一步失败，只把受影响的组送回失败的那一步；其他组的结果原样复用，不重新生成、不重新判定、不改记录。

| 失败发生在 | 送回 | 不受影响 |
|---|---|---|
| T／R：复核不通过、输出不合格 | 该组按[自动修复](../layer2-bounded-auto-repair.zh.md)的失败分类重译（T） | 其他组全部记录 |
| P：语言插件拒绝 | 可修的失败码：该组重译。复核已通过、插件误拒：不改写译文，修插件后对全部组重跑 P（零调用），只有结论变化的组成为受影响组 | 结论仍为 pass 的组的全部下游记录 |
| Q：回译或确定性文字检查失败 | 该组带失败码重译（T），修复账本按该组的句计数 | 同上 |
| C：精简不过关 | 该组重做 C；仍不过关的保留完整译文配音（现行规则） | 同上 |
| S：合成报错或产出不完整 | 该组重做 S | 同上 |
| A／U：ASR 回查或单句音频 QC 失败 | 该组按音频修复账本重合成（S）；原因在读法或口播文字时退回 C 或 T | 同上 |
| 合并：长度离群、语速中位数离群 | 只有被判离群的组，送回 T 或 S | 未被判出的组 |
| 合并：排程超过 8 秒 | 排程归因出的组（超限组及其前面占用空隙的组，按现行排程公式确定），带 `maxSpeechUnits` 送回 C | 其余组；空隙吸收后的组不重做 |
| 合并：整轨核对、字幕组装、合并清单 | 不是组的问题：修装配代码后只重跑合并 | 全部组记录 |
| 合并：校准未达门限 | 不是组的问题：本 locale 不能签豁免，改走人工路径或暂停；不重做任何组 | 全部组记录 |

**达到返修上限的组不阻塞别的组。** 一组用完每句上限，或因“没有进展”、单组花费上限停下，就按[机器质检豁免](../machine-quality-waiver.zh.md)的现行规则在合并时降级：文字仍不过关的句改显英文原文，音频仍不过关的句只显字幕不配音。5% 门限只在本 locale 内判定：不配音的句超过 5%，本 locale 改为只发文字（`audio_unavailable`）；失去译文的句超过 5%，本 locale 暂停发布。其他 locale 不受影响。降级是合并结果，记在合并清单和豁免收据里，页面照常显示披露；不把降级的组标成通过。

**唯一的例外是未知结果。** 一组的付费调用结果未知时，它既不算通过也不算失败，要先对账（AGENTS.md 不变式 5）。在对账前，同一 provider 路由不派发新的付费调用，该组所在 locale 的合并等待；其他路由的派发和其他 locale 的合并照常（决定 3）。对账后按结果归入通过或失败，仍只处理这一组。

**系统性失败也不改动已有结果。** 同一失败码连续出现时，locale 级的系统性检测停止新的返修派发（规则没送到模型，逐组修只会浪费）；已通过的组记录保持不变。修好规则后，只有失败的组重做。若修规则改变了 policy 或提示，按第七节的失效规则处理，那是输入变化，不是返修扩散。

**怎样保证“原样复用”。** 记录不可变，返修只写受影响组的新记录。每次合并清单与上一次合并清单逐组比较，列出记录哈希变化的组；变化的组必须恰好等于本次受影响的组（操作者给的组 ID、合并退回的组、P 结论变化的组），多出任何一组就拒绝合并。操作者在 `status` 与合并报告里看到的是这份组 ID 清单，不是哈希。

## 九、诚实标签与哈希绑定对操作者不可见

操作者只写：

```bash
python scripts/group_tasks.py plan  --run <run> --locale ko --group-id g0123 g0201   # 列出将重做的步骤、复用数和预算上界，不派发
python scripts/group_tasks.py redo  --run <run> --locale ko --group-id g0123 g0201 [--reason <修订意见>]
python scripts/group_tasks.py status --run <run>                                       # 每组每步的状态
python scripts/group_tasks.py merge --run <run> --locale ko
```

（命令名为占位，第一批确定。）其余全部自动：

- **键与哈希由系统计算。** 操作者从不输入哈希、收据路径或状态字段；`plan` 根据现有产物算出过期步骤。
- **逐组记录永远不是发布物。** 每份记录写死 `releaseEligible=false`、`humanApproval=false`；preview 音频沿用 `preview_only`、`synthesisEligible=false`。合并之前不存在可发布的 locale 状态。
- **操作者的组 ID 指令不是内容批准。** 它记为 `operator_directive` 收据（组 ID、可选修订意见、时间），绑定进 T 的返修 brief，因而进入 payload 身份；生成的新译文仍是机器结果。人读过并接受某组 QC 失败时，走现有 `text_qc_human_acceptance` / `audio_qc_human_acceptance`，豁免仍为 `humanApproval=false`、`review=waived`，页面照常显示披露。
- **合并输出现行标签。** candidate 保持 `machine_review_pass_human_review_pending`；豁免照旧 `reviewKind=machine_quality_waiver`；release v4 的 `contentStatus`／`audioStatus`／`disclosure` 由现有 builder 写出。
- **证据分立。** 逐组 pass、合并成功、HTTP 回读、浏览器、设备、场地仍是各自的状态；合并成功不代表已发布。

## 十、复用的现有构件

| 构件 | 用途 | 需要补的 |
|---|---|---|
| [组审核收据](../multilingual-intralayer-review-decoupling.zh.md) `record-group` / `approve-groups`（`sermon-target-language-group-review-receipt-v1`） | 人工路径的逐组决定与合并聚合 | 无；机器路径不用它 |
| `render_speculative_target_language_speech.py --group-id` 与正式 `--speculative-from` | S 的 preview 生成与合并时采纳 | 输入从“整份 machine-pass candidate”放宽为“该组的 T–Q 记录”；支持口播文字；正式 batch8 路径也走采纳（现在 `--spark-production` 跳过） |
| renderer `--reuse-from` | 采纳旧正式单元 | ~~比较时去掉 `unitIndex` 与 batch 窗口成员~~：决定 1 的 A/B 未通过，不做 |
| Layer 2 payload cache（v6）与预算 v4 `$0 reused` | T、R 复用 | 从“prior root 列表”改为按组键直接查找 |
| `qc_text_run` 按请求缓存、`english_source_judge_cache` 单飞模式 | Q 与校准试验复用 | 校准 v4 的稳定选组 |
| `machine_repair_ledger` | 逐句返修次数 | 并行追加压力测试 |
| controller v7 部分恢复 | 失败 job 的续跑 | 由逐组记录取代；v7 保留读旧 job |

## 十一、分批实施与测试

每批单独 PR，先合并代码与离线测试，再按 runbook 做真实路径检查；任何真实付费、Spark 或发布运行都需要单独授权，并按惯例导出运行报告。

| ID | 内容 | 测试与验收 |
|---|---|---|
| `DEV-GRP-001` | 逐组记录 schema 与输入键函数；只读 `plan`：从现有运行产物算出每组每步是否过期，不派发 | 金样：同输入同键；Layer 1 任一变化全部过期；只改插件只 P 过期；只改一组译文只该组 R 起过期；跨 locale 不串用；用 `15030286` 已有产物离线跑 `plan`，零调用 |
| `DEV-GRP-002` | Layer 2 逐组 T、R、P 与按组 ID 返修（另一分支的 revise-by-group-ID 实现）；合并第 1–2 步的 candidate 组装；并行 worker 与单飞锁 | 从逐组记录组装的 candidate 与整篇路径逐字节相同；过期或 `unknown` 记录阻止组装；未知结果只停止同一 provider 路由的新付费派发；并行与串行结果相同 |
| `DEV-GRP-003` | 逐组预算：额度按第六节计算；预算授权加逐组明细 | 全缓存重放后仍能修授权的组；超出单组上界时派发前停止且不影响其他组；`$0 reused` 不占额度；旧授权 v4 照旧可读 |
| `DEV-GRP-004` | Q 逐组判定；长度离群移至合并；校准 v4 稳定选组与试验缓存 | 未变组零新调用；改 k 组只为 k 组的试验付费，另加为满足每类最少新组数而补选的未变组（有上限，计入预算）；校准 `inputs` 等于新成品；v3 收据照旧验证；注错检出率与误报率在同一夹具上与 v3 一致 |
| `DEV-GRP-005` | S、A、U 逐组：preview 生成接受逐组记录；声音身份去掉位置与 batch 成员；A、U 按 WAV 哈希缓存；冻结语速文件做逐组时长判定 | preview 不能进入音频包；正式只采纳同字节；改一组只重合成该组；真实 A/B 通过后，batch 成员变化不触发重合成；未通过则 batch 成员留在键内；A/B 绑定测过的合成身份，身份一变即失效（决定 1）。2026-10-19 A/B 未通过：batch 成员留在键内 |
| `DEV-GRP-006` | 合并第 3–10 步与合并清单；合并失败映射回组 ID | 合并产物通过未修改的 L3 包验证器与 L4 builder；8 秒超限报告正确的组；5% 规则边界；合并不调用翻译模型 |
| `DEV-GRP-008` | 第八节的出错隔离与逐组降级：失败路由表；达到上限的组在合并时改显英文或只显字幕；5% 门限按 locale；合并清单逐组比较，变化组必须等于受影响组。降级要接通豁免、L3 音频包与 L4 release 对“改显英文／只显字幕”句的支持（[豁免文档](../machine-quality-waiver.zh.md)“还没有接上”第 3 项） | 一组失败时其他组记录哈希不变；多出一组变化即拒绝合并；降级组正确显示；不配音 > 5% 写 `audio_unavailable`、失去译文 > 5% 暂停，且只影响本 locale；`unknown` 组只阻塞本 locale 合并 |
| `DEV-GRP-007` | 操作者命令 `plan`/`redo`/`status`/`merge`；runbook 与 tracker 接线 | 先在已有运行上零付费演练；再经授权做一次小规模真实返修（建议 1 个 locale、≤ 3 组），记录复用率、新调用数、墙钟与人工等待，导出运行报告 |

### DEV-GRP-001 实施说明（2026-10-18）

- **代码。** [`group_records.py`](../../packages/production/src/tongxing_production/orchestration/group_records.py) 定义 [`sermon-group-stage-record-v1`](../../schemas/sermon-group-stage-record-v1.schema.json)、每步的输入名单（`STAGE_INPUTS`）、输入键与只追加的记录目录（`<locale>/<group>/<stage>/<inputKey>.json`，同键第二次写入只能字节相同）。键 = 步骤 + Layer 1 身份 + locale + 组 ID + 命名输入哈希 + 步骤实现身份，不含位置。步骤实现身份：T/R 为 runner 生产身份，P 为插件实现，Q/C/U 为机器质检闭包 W，S 为 renderer 声音身份，A 为 ASR 筛查实现。[`group_legacy.py`](../../packages/production/src/tongxing_production/orchestration/group_legacy.py) 从整篇运行的产物读出逐组记录（只读）：T/R 取 round 缓存与 policy preview，Layer 1 取该 round 冻结的 `request.json`；P 取插件收据；Q 取文字 QC 收据；S 取正式 renderer 单元 intent 与单元收据；A 取回听 ASR 缓存与筛查收据；U 取音频 QC 收据。产物没有记录的值写入 `provenance.notRecorded`，不借用当前代码的值。
- **命令。** 第九节的占位命令定为 `tools/ops/group_tasks.py`（运维入口，绑定宿主后读当前实现身份）：`.venv/bin/python tools/ops/group_tasks.py plan --manifest <inputs.json> [--locale ko --group-id <组 ID>…] [--records <记录目录>] [--output plan.json]`。`inputs.json`（`sermon-group-plan-inputs-v1`）列出源包、锚点及每个 locale 的 candidate、policy、插件、插件收据、Layer 2 round 目录（旧到新）、文字 QC 收据、speech job 目录、筛查收据、音频 QC 收据，以及下一次筛查要用的 ASR 设置（`asrSettings`；不给时 A 不能判为可复用）和运行用过的旧冻结 policy（`priorPolicies`，用来算文字 QC 收据看到的 QC 侧 policy 身份）；缺的产物在 `plan` 中显示为 `missing`。读取旧产物时按生产代码自己的接受条件判定：翻译与复核回复按 runner 的组身份、覆盖与语义复核检查，插件按 policy 的 `requiredChecks`，文字 QC 按正式准入的 pass／keep 与回译条件。`--output` 只写新文件，不覆盖已有文件。
- **判定。** 每组每步输出 `fresh`／`expected_reusable`／`stale`／`failed`／`stopped`／`unknown`／`conflict`／`missing`／`not_applicable` 及原因。**从整篇运行产物读出的记录最多是 `expected_reusable`：只用于规划和预算估算，不是复用依据。**`fresh` 只给逐组流水线（`DEV-GRP-002` 起）写入时做完整校验的记录，派发（`DEV-GRP-006`）前还要用生产者自己的校验函数再核一次。有生产者 schema 的产物（音频筛查 v2、单元收据 v1）按 schema 校验，不合格的不读；文字 QC 与音频 QC 还要求修复账本仍停在该次运行写下的位置（`repairLedgerRoot`）。产出字节的步骤（T、R、C、S、A）过期时，读其产出的下游步骤一并过期；P、Q 只是判定，过期不外溢。操作者给出的组 ID 使该组 T 起过期。
- **限制（如实）。** T/R 比较的是构成请求的输入（组英文、英文上下文、policy 的术语/经文/格式、模型设置、runner 身份）；精确请求哈希含凭据路由，派发时由 payload cache 再匹配。逐组规则、修订指令、文字 QC 的语义身份、S 的合成身份（除声音身份外）只记录不重算；batch 成员尚未进入键：决定 1 的 A/B 未通过，它应留在键内，由 `DEV-GRP-005` 补上。没有预算数字（`DEV-GRP-003`）。
- **`15030286` 离线演练**（三语各 402 组，零模型调用，不写产物，约 6 秒）：T、R 三语全部 `fresh`；没有一个 round 写下 runner 身份（最终 round 无 payload-cache 成功收据，`run-identity.json` 只存合成哈希），所以 T/R 的实现身份记为未比较。P 三语全部 `stale`：运行分支把三个 15030286 插件登记为 `common.py`、`auto_qc_text_common.py`、`weekly_15030286_common.py` 四文件闭包，`dev` 没有这项登记，按 `dev` 算的插件身份不同；按运行分支的四文件闭包重算，三语插件身份与收据完全一致。Q 全部 `stale`：文字 QC 在 W `51e2b9…` 下运行，`dev` 是 G1 最终 W `df299e…`（[G1 记录](../reports/20261017-g1-implementation-generation.zh.md)）。es、ko 的 S `fresh`（声音身份 `fef760…` 未变、口播文字等于 candidate），A `stale`（筛查实现 `40bc41…` → `38c743…`），U `stale`（W 与上游 A）。zh-Hans 本次没有 Layer 3 产物，S/A/U 为 `missing`；三语 C 均为 `not_applicable`（文字 QC 全部 `full`）。

### DEV-GRP-003 实施说明（2026-10-19）

- **代码。** [`group_budget.py`](../../packages/production/src/tongxing_production/orchestration/group_budget.py) 按第六节计算：每次上界取 [运行档案](../weekly-run-profile.zh.md)（`config/weekly-run-profile.json`）的 Layer 2 与 QC 请求上限，用 `compute.provider_limits` 的价格算最坏情况；精简次数取 `review.condensation.MAX_ATTEMPTS`，二级 ASR 取 `compute.transcription_request` 的 180 秒整分钟预留；每句上限取 `review.text_qc.MAX_TEXT_REPAIR_ATTEMPTS`，已用次数取文字 QC 收据记下的修复账本次数。操作者点名的组按剩余次数 × 每次上界；只因某步过期的组只算一次需要重跑的付费步骤；`plan` 判为 `fresh` 的步骤记 $0，不占额度。
- **预留。** 点名的组按操作者顺序在前，其余按 candidate 顺序；每个付费系统（`layer2`、`qc`、`secondaryAsr`）按运行档案的每 locale 上限分别扣减。放不下的组标 `repair_spend_cap`、不预留，已预留的组不变；次数用完的组标 `repair_limit_reached`、不预留（第八节在合并时降级）。`admit(budget, groupId)` 给派发器在调用前取该组的预留，未预留的组直接拒绝。
- **文件。** `plan --budget-profile config/weekly-run-profile.json [--budget-scale week|clip]` 在每个 locale 下输出 `sermon-group-budget-v1`（只读、`humanApproval=false`，派发前须由操作者批准并按哈希绑定）。现行 Layer 2 v1–v4 与机器质检的预算授权格式不变、照旧可读；逐组明细与派发的接线随派发器（`DEV-GRP-006`/`007`）落地。
- **`15030286` 离线结果（week 档）。** 每对翻译加复核上界 $0.12288（与 v8 按组号修订收据的 `worstCasePairCostMicrousd` 一致），每组回译加比对上界 $0.09216。三语文字 QC 因 W 变化全部过期：按最坏情况预留，整语言重跑文字 QC 需约 $37，超过 QC 每 locale 上限 $30，所以 77 组标为 `repair_spend_cap`。这是最坏情况的输入上界（16,384 token），不是实际花费。ko 点名 3 组时，3 组各预留 4 次，排在最前面全部预留。
- **限制。** 二级 ASR 每次按一个被标出的单元、180 秒上限预留。QC 请求按请求上限计算最坏情况，没有用实际请求大小。合并第 4 步的校准试验费用属于 `DEV-GRP-004`。

依赖：001 → 002、003 可并行 → 004、005 可并行 → 006 → 008 → 007。008 的失败路由与合并比较在 006 内先实现；降级显示依赖 L3／L4 的支持，未接通前达到上限的组使本 locale 走人工路径或暂停，不阻塞其他 locale。002 的逐组记录格式以 001 为准；若 002 先合入且格式不同，001 以适配层读取，不改已写记录。

## 十二、决定（2026-10-19 用户确认）

1. **batch 成员不属于声音身份（同意，A/B 通过后生效）。** 复用以字节为准（字节已经过 A、U 检查），batch 窗口只记为来源信息，不进 S 的输入键。生效条件：`DEV-GRP-005` 做一次真实 A/B，每个 locale 至少 10 组句子，同一组句子按批合成与单独补合成各一份，盲听比较。若有任何一对被听出音色、语速或音量差异，这项改动不生效，batch 成员继续留在键内（同 [正式 renderer](../formal-layer3-renderer.zh.md) 现行规则）。A/B 结果写入运行报告，并按哈希绑定它测过的合成身份：S 键里的 `synthesisIdentitySha256`（adapter、checkpoint、speaker、语言参数、normalization、种子与解码设置）加 renderer 声音身份与运行时。豁免只在当前合成身份与测过的完全相同时成立；其中任何一项改变，batch 成员先回到键内，直到新身份上再做一次 A/B 并通过。合并后的整轨听感抽查照旧。工具：[`tools/ops/batch_identity_ab.py`](../../tools/ops/batch_identity_ab.py)（模块 [`audio/batch_identity_ab.py`](../../packages/production/src/tongxing_production/audio/batch_identity_ab.py)）。`select` 从正式 speech job 按时长均匀选组，并绑定测过的合成身份（`TESTED_FIELDS`：声音、解码与 batch 实现字段）；`pack` 把这些组的正式批合成 WAV 与 `render_speculative_target_language_speech.py --group-id` 的单独渲染配成盲听对，X/Y 随机，密钥另存并按哈希绑定；`record` 要求每一对都有判定，任何一对 `audible_difference` 即不通过；`applies(result, intent)` 只在当前合成身份与测过的相同时为真。工具本身不渲染、不调模型；单独渲染要在 Spark 独占会话里跑。

   **结果（2026-10-19）：未通过，本项改动不生效。** 15030286 盲听：ko 10 对中 5 对、es 10 对中 4 对被判有差别（被测身份 ko `f6bdd661bc29`、es `9a246266ab1a`），batch 成员继续留在键内。单独渲染的种子是 43 加单元序号；批渲染的种子是 43 加窗口起点，8 条序列共用一条随机流。只有 es 一对两边种子相同，它仍被判有差别。所以单独补合成在结构上复现不了批内声音；以后若重提此豁免，先说明怎样复现批内随机流，或改为评估整轨一致性。见[运行报告](../reports/runs/20261019-grp005-ab-listening/RETROSPECTIVE.md)。
2. **校准 v4 稳定选组（同意）。** 选组种子改为 `H(注错类别, 组内容哈希)` 的稳定排序，试验按请求或字节哈希缓存；不放宽检出率、误报率或“在本次成品上校准”的规则。缓解：每类注错保留最少新组数，优先从本次改过的组中选；改过的组不够时才补选未变组，补选的组要为新试验付费，数量有上限并计入预算授权。因此“改 k 组只为 k 组付费”的条件写为“k 组加补选组”。具体数值随 `DEV-GRP-004` 的金样一并评审。
3. **未知结果只停同一 provider 路由（用户决定）。** 一组付费调用结果未知时，只停止同一 provider 路由（供应商与项目／凭据路由，含该路由下所有模型）的新付费派发，直到对账完成；其他路由上的所有组、所有 locale 照常派发。未知的组本身仍要先对账再归入通过或失败，该组所在 locale 的合并仍等待它（合并不能含 `unknown`）。用户确认这一范围不另行修订成本规则，[AGENTS.md](../../AGENTS.md) 不变式 5 已注明逐组流水线的停止范围是该 provider 路由；路由内的停止与对账照旧。
