# 周六 4 点场直播的预备用途：术语、经文、审核预热与链路彩排

状态：**设计稿；P9 工具 `text.term_scope` 已实现（2026-10-24），其余未实现；2026-10-24 做了第一次 rehearsal（运行报告 `20261024-sat400-prep`）**。backlog 前缀 `DEV-PREP`（见第九节）。本页不改变任何现行门限、schema、豁免规则或发布流程；不授权付费、Spark 独占会话或发布。校准日期：2026-10-24。

## 一、背景与观察

Mariners Church 每周六有两场礼拜直播：4:00 和 5:30（洛杉矶时间）。两场的经文和讲章内容大致相同。周日的正式播放版来自其中一场，经剪辑后作为 Broadcast Message 文件上传到公开 Google Drive 文件夹（见[本地生产 Runbook](../codex-local-production-runbook.zh.md#broadcast-message-网盘上传检查2026-10-18-起)）。当前周更把这份文件作为 Layer 1 来源，周产的目标窗口是周六 19:00 到周日 10:00（[backlog 的 PR #242 剩余工作一节](../backlog.zh.md#pr242-remaining-backlog)；周产交付定义归 `DEV-WEEK-001`）。

已有的一个时间线索：10-17（周六）的样本 `20261018 BROADCAST MESSAGE.mp4`（约 1 GB）在 18:47:54 至 18:50:01 之间上传完成。5:30 那场要到 18:45 前后才结束，不可能在两分钟内剪辑并传完 1 GB。由此得到待验证的假设：

> **H1：周日正式播放版来自 4:00 场，并经过剪辑。**

H1 还没有被任何运行验证。它成立与否决定本页的价值上限：成立时，4 点场直播流与正式来源是同一场讲道的两个版本，只差剪辑与编码；不成立时，4 点场只是内容相近的另一场，预备材料的可信度要按"可能偏离"处理（同一讨论见[实时翻译基准](../live-sermon-translation-benchmark.zh.md) RQ2 的 `prepared_context_copy_error`）。

## 二、合同约束：什么不能复用

[四层合同](../multilingual-production-interfaces.zh.md)和现有代码对"复用"的限制在这里全部成立，先列清楚，避免把预备产物误当正式产物：

| 对象 | 绑定到 | 对 4 点场预备的含义 |
|---|---|---|
| Layer 1 English Source Package、锚点 | 媒体哈希、时长、批准窗口 | 4 点场直播流与剪辑后的 Broadcast 文件哈希不同；即使 H1 成立，剪辑也移动时间轴。4 点场的来源包、锚点、窗口批准和英文四项人工检查都**不能**作为正式包复用 |
| Layer 2 payload 缓存、`$0 reused` 行 | 完整 bounded payload（来源单元文本、锚点、policy、runner 身份）（[controller](../canonical-layer2-controller.zh.md)） | 来源一换就是 cache miss；4 点场的译文不会自动成为正式译文 |
| policy v4 的 `sourceScope.termApprovalReceipt` | `englishSourcePackageJsonSha256`、`anchorManifestSha256`（[policy.py](../../packages/production/src/tongxing_production/text/policy.py)） | 术语的人工批准收据绑定正式来源包；对 4 点场签发的收据不能直接带到正式运行。**术语决定本身**（source→target、保留英文、排除普通短语）可以提前做好，正式运行时只需对真实来源重签一次收据 |
| 冻结翻译策略 | 模型、prompt、术语表哈希（`terminology.seriesTableSha256`）、经文版本、排版 | 术语表或 `properNames` 在运行中改动等于重新冻结策略。这正是 4 点场的价值：把所有术语改动挪到正式运行**之前** |
| 人工审核收据（Layer 2 全文、Layer 3 听审） | 候选哈希、音频哈希 | 对 4 点场产物的任何审核都不是正式审核；预备阶段的人工工作是"预热"，不产生正式收据 |

结论：4 点场的产物一律是 `rehearsal` 或 `prepared_context`，`humanApproval=false`，不进入正式四层链，不发布。它能带来的收益是让正式运行**少返工、少等人**。

## 三、目标：把"返工和等人"挪到正式运行之前

[周更运行配置](../weekly-run-profile.zh.md)的测量：10-11 周 12.5 小时墙钟里纯计算约 1.5 小时，其余是返工和等人；其中约 3 小时是会话在等操作者回答。10-11 [复盘](../reports/20261011-weekly-release-resi-54475d42-retrospective.zh.md)列出的 12 个人工介入点里，与内容有关的是：窗口批准、英文四项检查、术语和经文决定、全文审核、`request_human_review` 裁决、大纲／默想批准、官方标题确认、整轨听审。

4 点场最多能提前约 3 小时拿到同一篇讲道的英文文本。这 3 小时的正确用法：

1. 在正式策略冻结前完成术语、专名、经文版本和系列登记的全部决定；
2. 让审核者先读过讲章和一份机器初译，正式全文审核变成对照差异而不是冷读；
3. 用真实输入跑一遍零付费的开工检查，提前暴露预算预留、凭据启动器、Spark 状态和质检代码变更这类 10-11 周把运行卡住的原因。

不把这 3 小时用在算力上：三语从冻结英文到可发布包的理论最短路径约 1.5 小时，提前算 4 点场的译文和音频对正式运行没有可复用的产物，只有费用。

## 四、预备流水线

全部步骤默认零付费；标 **付费** 的步骤需要独立的预算授权，且默认不做。

```text
16:00  P0 抓取 4 点场直播链接（现有 sat400 抓取窗口）
~17:15 礼拜结束
       P1 本地 ASR（Spark Qwen3-ASR，或 MacBook MLX 回退）→ 4 点场英文转写（rehearsal）
       P2 术语与专名提取：系列名、讲题、人名、地名、保留英文的词、数字与年代
       P3 对照：系列名称表、各 locale policy 的 seriesNames/properNames、上周 register rules
       P4 经文引用清单：书卷章节、引用方式（朗读／转述）、各 locale 经文版本的候选文本
~17:40 P5 人工术语决定（按 locale）：新译名、保留英文、普通短语排除；新系列按名称表约定登记
       P6 审核预热包：4 点场英文转写 + 机器初译草稿（明确标注 rehearsal，不进入正式链）
       P7 开工检查彩排：check_run_start、预算计划、凭据启动器、Spark 主机、输出目录
~18:47 Broadcast 文件出现 → 正式 Layer 1 开始（现有流程不变）
       P8 差异报告：4 点场转写 vs 正式来源转写（时长、文本 diff、新增／删减段落）
       P9 对真实来源重签术语收据（policy v4 termApprovalReceipt），冻结策略，派发 Layer 2
```

各步说明：

- **P0 抓取。** [observability](../observability.md) 已定义互不重叠的 `sat400`（16:00–16:55 每 5 分钟）与 `sat530` 抓取窗口，`tools/ops/configure_live_source_scheduler.py` 支持 `--service sat400`。预备用的链接写到独立的预备目录，不覆盖正式 `selectedSource`；现有"已保存周六直播链接则不再 discovery"的规则不受影响。
- **P1 本地 ASR。** 用[统一 Source 准备](../unified-source-preparation.zh.md)同一套 ASR 后端跑 4 点场音频，但以 `rehearsal` 身份运行，不写正式 Source 候选、不签窗口批准、不调用付费英文机器裁判。输出只有英文文本和粗略时间，不要求词级对齐。
- **P2–P3 术语提取与对照。** 这一步就是[Layer 2 定向修复](../layer2-targeted-repair-and-resume.zh.md) R4 第 2 项"术语覆盖预检"（该文"待实现"第 1 项）：把英文文本中出现、但 policy 的 `seriesNames`/`properNames` 里没有或仍为 `pending` 的条目列出来；"保留英文"的条目生成 register rule。实现后同一个检查既服务预备阶段，也在正式派发前作为零付费门禁运行。扫描是候选清单，不是决定：普通短语的排除仍由人工给出，并记入 `ordinaryPhraseExclusions`。
- **P4 经文清单。** 列出引用的书卷章节和引用方式；对每个 locale 取出当前经文版本的候选文本，供审核者在正式运行的经文边界审核中直接比对。不改 `scripture.quoteCheckPolicy` 或 `editionId`；版本决定仍按现有策略。
- **P5 人工术语决定。** 每个 locale 一次，写入 `config/target-language-policies/<locale>.json` 的 `properNames`（`reviewStatus` 按现有枚举），新系列按[系列名称表](../series-terminology.zh.md)的自动登记约定追加一行。这些改动在正式策略冻结之前完成，正式运行里不再出现"运行中改术语表"的情况。
- **P6 审核预热包。** 一份只读材料：4 点场英文转写、机器初译草稿（可用 DeepSeek 默认后端，**付费**，默认不做；或只给英文）、术语与经文清单。封面必须标注"4 点场 rehearsal，不是正式来源，不产生审核收据"。审核者的笔记只用于正式审核时加快判断。
- **P7 开工检查彩排。** 用真实的本周输入跑现有的开工检查和预算规划，不派发任何付费请求。失败项在正式来源到达前修好。
- **P8 差异报告。** 正式来源的英文转写出来后，与 4 点场转写做对齐 diff，输出：时长差、相同段落比例、正式版新增与删除的段落。它同时是 H1 的验证证据和审核者的"本场与预读稿有何不同"清单。
- **P9 重签与冻结。** 用正式来源包哈希重签 `termApprovalReceipt`，冻结策略，按现有 runbook 派发。术语决定没有变化时，重签是分钟级动作。

  P9 的工具是 `text.term_scope`（2026-10-24，`DEV-PREP-003`）。输入 P5 的决定文件（`sat400-prep-term-decisions-v1`，见第五节）、正式 English Source Package 与 anchor manifest，每个 locale 输出一份 v4 policy 草稿和一份报告：

  ```bash
  .venv/bin/python tools/ops/run.py text.term_scope --decisions <p5-decisions/term-decisions.json> \
    --source-package <english-source-package.json> --anchor-manifest <anchor-manifest.json> \
    --base zh-Hans=<本周 zh 草稿底稿> --base ko=<ko 底稿> --base es=<es 底稿> \
    --reviewed-by <审核者> --reviewed-at <决定时间> --user-statement "<用户原话>" --out-dir <输出目录>
  ```

  - 决定里的词只要在正式英文的某个单元出现，就写进 `properNames` 和 `termApprovalReceipt`，收据行记下那个 `sourceUnitId`；没出现的列为 `decisionsAbsentFromSource`，不写入。
  - 扫描器（`policy.source_scoped_proper_names`）找出的名字，既不在决定里也不在预测排除里的，列为 `uncoveredScannerNames`（带单元 ID），该 locale 不出草稿，等人决定。预测排除只保留扫描器真的产出的那些。
  - 用到的系列名取决定里的目标，没有就沿用底稿；中文必须与系列名称表一致。
  - 每份草稿在内存里试冻结一次（`freeze_policy` 加 `validate_source_scope`），并核对所钉插件与当前代码：`current`、`stale`、`missing` 或 `unbound`。冻结本身仍由操作者用 `text.policy freeze` 选择后端；ko/es 插件过期时加 `--language-review machine_qc` 重钉。
  - 退出码：0 全部可冻结且插件为当前；2 缺决定或试冻结被拒；3 可冻结但有插件要先重钉。
  - 收据上的人工批准来自操作者传入的 `--reviewed-by` 与 `--user-statement`，工具不推断批准。

## 五、预备产物的目录、标签与边界

- 目录：`artifacts/weekend-live/<sunday>/sat400-prep/`（忽略目录，不入 Git）。子目录按 P1–P8 命名。
- 每份产物带 `kind: rehearsal | prepared_context`、`service: sat400`、`captureUrl`、`mediaSha256`、`asrBackend` 与生成时间；`humanApproval=false`。
- 预备产物不能被任何 Layer 1–4 producer 当作输入；正式 Source 候选的准入要拒绝 `kind=rehearsal` 的转写。实现时在现有 consumer 预检（`DEV-R242-001`）里加一条拒绝规则，而不是靠目录约定。
- 术语表与 policy `properNames` 的改动是正式改动，进 Git，按名称表约定在交付说明里告知用户。
- 周日 `live_session` 的 Context Pack（[合同](../saturday-to-sunday-context-pack-plan.zh.md)）可以从预备目录投影 `prepared_context`，比现在早约 3 小时；现场 `asr.final` 仍是唯一事实源，机器中文仍不可注入。

## 六、不做的事

- 不用 4 点场的任何产物发布页面、音频或海报。
- 不把对 4 点场产物的任何人工阅读或试听当作正式审核收据。
- 不让 4 点场转写替代正式来源的 ASR，也不用它"修补"正式转写里的听写疑点；正式转写的疑点走正式的英文四项检查。
- 不在正式运行开始后再改术语表或 policy；预备阶段结束时策略应已可冻结。
- 不默认为 4 点场付费跑 Layer 2 或 Layer 3；预算授权只用于正式来源。
- 不假设两场内容相同：H1 未验证前，所有预备材料按"可能偏离"标注；验证后也只说明该周。

## 七、H1 的验证方法

一个周六即可完成，零付费：

1. P0 抓取 4 点场链接，P1 本地 ASR，记录媒体时长与音频 SHA-256。
2. Drive 文件出现后（现有 `sermon-drive-upload-watch` 只检测，不下载），按现有授权流程下载正式来源，做正式 Layer 1 的 ASR。
3. P8 差异报告：对齐两份转写，报告相同段落比例与差异位置；比较 4 点场讲道段时长与正式来源时长。
4. 判定：相同段落比例高、差异集中在剪辑点时 H1 成立；出现 5:30 场特有内容（例如讲员提到"今晚"或第二场才有的见证）时 H1 不成立。
5. 结果写运行报告，并把判定记到本页第一节和 backlog `DEV-PREP-001`。

验证一次只说明那一周。建议连续三周重复第 3 步，再把 H1 写成默认假设。

## 八、与现有事项的关系

- `DEV-WEEK-001` 周产交付定义与时长预检：本页不改目标窗口，只在窗口前增加零付费预备。
- `DEV-R242-001` 全消费者预检：预备产物的拒绝规则落在这里。
- [Layer 2 定向修复](../layer2-targeted-repair-and-resume.zh.md) R4 第 2 项术语覆盖预检：由 `DEV-PREP-002` 实现，同时服务预备与正式派发。
- `DEV-LIVE-001` 与 Context Pack：预备目录只是更早的输入，不改变现场合同。
- 10-11 复盘的人工介入点：P5、P6 针对第 1、3、10 项；P7 针对复盘第五节的预算、凭据和 Spark 阻塞。

## 九、backlog 条目与验收

| ID | 优先级 | 内容 | 完成条件 |
|---|---|---|---|
| `DEV-PREP-001` | P0 | 验证 H1：一个周六完成第七节的 1–5 步，导出运行报告 | 报告含两份转写的相同段落比例、差异位置、时长比较和明确判定；无付费调用 |
| `DEV-PREP-002` | P1 | 术语覆盖预检：英文单元 vs policy `seriesNames`/`properNames`，列出出现但未批准的条目，生成 register rule 候选；作为 `rule_preflight` 的零付费步骤 | 在 `15030286` 已有来源包上离线运行，列出的条目与当时人工补入的 `properNames` 一致；预检失败时无模型调用 |
| `DEV-PREP-003` | P1 | 预备产物合同：目录、标签字段、`kind=rehearsal` 拒绝规则、P5 写 policy 的流程、P9 对真实来源重签术语收据 | consumer 预检拒绝 rehearsal 转写的测试通过；一次真实周更里术语收据在正式来源到达后 10 分钟内重签完成 |
| `DEV-PREP-004` | P1 | 审核预热包与 P8 差异报告生成器 | 一次真实周更里审核者在正式来源到达前拿到预热包；全文审核时长与 10-18 周比较并记入运行报告 |
| `DEV-PREP-005` | P2 | 开工检查彩排作为周六 17:00 的只读定时步骤 | 连续两周彩排发现的问题在正式开工前修复；定时任务只读、无付费、无发布 |

验收口径沿用 backlog 维护规则：代码合并与测试通过只是 `in_progress`；`complete` 要有真实周更的运行报告。
