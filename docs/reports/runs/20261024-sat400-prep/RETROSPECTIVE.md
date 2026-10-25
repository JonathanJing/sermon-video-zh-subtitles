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

## 外部可见的变化

无。没有 Dev 或 Production 发布，没有 TestFlight，没有推送受保护分支；只有本报告的文档 PR。
