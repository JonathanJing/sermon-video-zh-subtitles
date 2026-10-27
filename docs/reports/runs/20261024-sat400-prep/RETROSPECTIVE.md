# 复盘：20261024-sat400-prep

数据见同目录 INDEX.md 和 manifest.json。设计见 [周六 4 点场预备](../../../design/saturday-first-service-preparation.zh.md)（`DEV-PREP-001`–`005`）。

## 结论先行

交付类型：**测试（rehearsal）**，不是 `dual_pdf`、`live_session` 或 `four_layer_release`。按设计第四节对 2026-10-24 周六 4:00 场直播做了第一次零付费预备：P1 本地 ASR、P2–P4 术语／专名／经文提取与对照、P6 审核预热包、P7 开工检查彩排均完成；P5 人工术语决定在等用户，P8 与正式 Broadcast 文件的差异报告在等文件上传，所以 H1（正式版来自 4 点场）**本轮没有验证**。所有产物 `kind=rehearsal`、`humanApproval=false`，零付费调用，没有发布。INDEX 把 `waiting` 阶段也列为 failed，这是导出器只认 `pass` 的缘故；真正失败的只有 P7 开工检查。

## 总时间

墙钟约 16 分钟（17:55–18:12 PDT），其中 Spark ASR 281.6 s，其余是切片、提取和写包。没有等人或返工。上一轮同类运行：无（首次）。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR（rehearsal） | Qwen/Qwen3-ASR-0.6B @5eb14417，Spark CUDA，`SERMON_SPEECH_BACKEND=auto`，无回退 | — | 66 块，batch 8 | 281.6 s | 1,861 s 音频，约 5,450 词 | 0.151×实时 | 0（本地） | `summary.json` asr |
| L1 词级对齐（MFA） | not_run | | | | | | | 预备不需要词时间 |
| L1 英文机器评审 | not_run | | | | | | | 设计规定不对 rehearsal 付费 |
| L2 初译／独立审核 | not_run | | | | | | | P6 机器初译是付费可选项，未授权 |
| 文本质检、L3、音频质检、L4 | not_run | | | | | | | 预备阶段不做 |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| P7 开工检查 | `code` 失败：主检出 HEAD 是已合并的设计分支 3578abaa，不是 dev d76ca6e2 | 主检出停在文档分支 | 预检 | 正式运行从 dev 的独立 worktree 开始；本轮不切分支 | — | — |
| P7 开工检查 | `QC implementation hash differs` | 本轮未传 `--expected-implementation`；另查到**没有任何产物绑定当前 QC 实现哈希** `3ba3f692…` | 预检 | 记为发现：本周若走机器质检豁免，需先付费重新校准；否则走人工审核 | — | — |
| P1 ASR | 专名误写：Corrie ten Boom 五种写法、Betsie→Betsy、D. A. Carson→De Carson、waiver wire→Waverwyer、nourishes→Nurishes、31:26 victor→victory | 小模型、无术语提示 | 预检 | 写进预热包的“正式来源 ASR 预警”，供英文四项检查 | — | — |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 把术语扫描写成 `rule_preflight` 的零付费步骤，替代本轮的手工清单 | 本轮 34 条术语靠一次性脚本列出 | 每周可重复、可测 | 待定 | `DEV-PREP-002` |
| 流程 | 预备目录与标签进合同，consumer 预检拒绝 rehearsal 转写 | 本轮目录 `artifacts/weekend-live/2026-10-25/sat400-prep/` 只是约定 | 防止误用为正式来源 | 待定 | `DEV-PREP-003` |
| 流程 | 导出器把 `waiting` 与 `fail` 区分开 | INDEX 把两个 waiting 阶段列为 failed | 报告不误导 | 待定 | 另开小修复 |
| 质量 | 正式来源 ASR 加入本周专名提示（spoken forms） | 本轮 6 类专名误写 | 减少英文审核改动 | 待定 | `DEV-PREP-004` |
| 流程 | 同一场直播有两份抓取：用户录像（h264，89fe948a…）与另一会话的 yt-dlp（av1，7f3d8e92…），时长相同、哈希不同 | 两个会话各自抓取 | 选一份作为 rehearsal 媒体身份，避免重复 | 待定 | `DEV-PREP-003` |

## 实际覆盖范围

- **执行：** P1 本地 ASR（证道窗口 28:36–59:37，用户在对话中给出，仅用于预备，不是正式窗口批准）；P2–P4 列出 34 条术语（16 条专名、2 条系列名、1 条书卷、10 条神学词、5 条短语和数字），4 处直接引用、5 处概述、7 处暗引，和合本 4/4 查到；P6 预热包；P7 开工检查。
- **识别：** 系列手册第 7 周 “Jesus wins”，启示录 12–13，讲员自我介绍为 Eric（Eric Geiger）；讲道三个要点与手册第 102–103 页一致。标题表第 7 周讲员“待核”可据此更新。
- **未执行：** P5 人工术语决定（等用户）；P6 机器初译（付费，未授权）；P8 差异报告与 H1 判定（Broadcast 文件尚未上传）；P9 术语收据重签（需正式来源）；Layer 1–4 正式产物。
- **政策现状：** zh-Hans policy `properNames` 为空、系列名已定；ko、es 系列名与 Eric Geiger 都是 `pending`；ko、es 经文版本政策 `pending`。

## 遗留状态

- 本机忽略目录 `artifacts/weekend-live/2026-10-25/sat400-prep/`：窗口音频、66 个切片、ASR 结果、术语与经文 JSON、预热包。正式来源处理完、H1 判定后可删切片。
- 另一会话的 `artifacts/weekend-live/live-capture-20261024-4pm/` 与硬链接 `artifacts/broadcast-20261024/` 未动；后者目录名像正式来源，但内容是 4 点场直播。
- 没有 Spark job hold；Spark 上 llama-server 照常运行，未停。

## 补充：P5 决定与 P9 彩排（同晚 18:20–19:00）

- **P5：** 用户在对话中说“按照预热包里的来”。决定文件按语言插件的逐字检查做了归一：西语去冠词、韩文锁词干、Eric Geiger 改为仅审核参考（全名不出现，单独的 Eric 会误中 America），补上扫描器要求的 Adolf Hitler、World War、Nazi Germany。归一由 Claude 完成，用户未逐条复核；决定记录绑定预热包与决定文件的哈希，状态 `applies`。
- **P9 工具：** `text.term_scope`（PR #1357）。在 4 点场转写（按预热包改正英文后切成 372 句，非 Layer 1 锚点）上，以上周三语草稿为底稿：三语都出草稿，31 条术语全部能指到单元，没有未覆盖的扫描名，试冻结通过。
- **发现：** 上周 ko/es 草稿所钉插件哈希已过期，用 `text.policy freeze --language-review machine_qc` 冻结后重钉为当前哈希；上周 zh-Hans 草稿所钉的 `zh-Hans-weekly-auto-v1` 在当前代码里不存在，本周 zh-Hans 插件需要另选（候选 `zh-Hans-weekly-cuv-v1`，本篇有 4 处和合本直接引用）。
- **zh-Hans 插件试钉 `zh-Hans-weekly-cuv-v1`（用户指定）：** 以上周 zh 草稿为底稿，改钉该插件当前哈希 `a7826dc2…`，经文政策改为 `cmn-cu89s`／`source_bound_exact_quote`。term_scope 出草稿、试冻结通过、插件钉为 current、`productionPolicyReady=true`。但直接调用插件的 `review_group`：一句普通讲述和一处 12:14 和合本原文引用，`cuv_exact_quote` 都失败（“Human boundary receipt belongs to another source”）。该插件内嵌 9-27 讲道的经文边界收据，换来源后每一组都会被拒，本周不能用。试冻结和插件钉检查都看不出这一点。
- **上周 zh 插件：** `zh-Hans-weekly-auto-v1` 是运行目录里的 16 行文件（`layer2-broadcast-20261018/plugins/zh_hans_weekly_auto.py`），只调共享的机器质检规则，不按来源绑定，从未进仓库。用新加的 `--plugin` 指给它，钉仍为 current；但仓库外插件的哈希只算这一个文件，不含它引用的共享规则，而共享规则在 ko/es 那边已变。
- **zh-Hans 插件定为 `zh-Hans-weekly-auto-v1`（用户决定，只核经文出处，同 10-18）：** 10-18 的运行目录插件原样进仓库（`scripts/language_review_plugins/zh_hans_weekly_auto.py`，字节相同），加入与 ko/es 相同的哈希集合，插件钉从只算单个文件的 `db550763…` 变为含共享规则的 `d210645a…`（单独 PR，改 Layer 2 代码身份，不改 QC 实现文件列表；放进 `scripts/` 需要布局白名单的一行例外，单列一个提交）。在合并了两条分支的临时检出里重跑 zh-Hans：出草稿、试冻结通过、插件钉 current、31 条术语、无未覆盖名。直接调用插件：普通句与 12:14 和合本原文都 7 项全过；漏写“马丁·路德”或同句里的“撒但”时 `proper_names` 失败，说明逐字术语检查在起作用。4 处和合本直接引用由人工审核核对。

## 外部可见的变化

无。没有 Dev 或 Production 发布，没有 TestFlight，没有推送受保护分支；只有本报告的文档 PR。
