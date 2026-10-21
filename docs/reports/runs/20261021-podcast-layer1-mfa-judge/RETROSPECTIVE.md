# 复盘：20261021-podcast-layer1-mfa-judge

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

- **交付类型**：`four_layer_release` 的 Layer 1 前置（双讲员播客《If I Had More Time | Jesus sends and resurrects His own》，YouTube `AKY0k5KiKns`，周日 2026-10-18，批准窗口 0:05.5–40:06）。
- **最终状态**：`blocked` / `source_machine_judge_rejected`。第 9 轮（v9）走完整条 Layer 1：ASR 14 块、Spark MFA 对齐 720 句 / 796 单元 / 7313 词、锚点清单、720 句机器评审；裁判通过 711 句、不通过 9 句（其中 8 句高风险），因此 `translationEligible=false`、`humanApproval=false`，候选包不可进入 Layer 2。
- **证据边界**：机器裁判是模型判定，不是人工审核；候选包 `output-v9/english-source-candidate.json` 已落盘但状态为 `blocked`，没有产生任何人工批准。
- **本轮真正解决的**：MFA 长参考块对齐失败（chunk_0010）、Claude 订阅登录过期、裁判 turn 计数过严、裁判批次超出冻结输入上限且随 ASR 漂移复发。

## 总时间

- 墙钟：v1 本地 07:46 → v9 本地 10:06（2026-10-21），约 2 小时 20 分；其中等待（Spark 队列准入、人工重新登录、参数修正）占大部分。
- v9 单轮约 9 分钟：ASR ~2 分钟、MFA ~1.5 分钟、机器评审 ~5 分钟（6 workers）。
- 返工：9 轮 Layer 1，其中 7 轮因基础设施/判定适配问题停下，1 轮（v9）到达裁判结论。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | `gpt-transcribe`（OpenAI 音频 API） | default | 14（每轮）/ 126 累计 | ~40 s | 2400.5 s 音频 | — | 每轮约 USD 0.18 | `layer1/output-v9/chunks/*.asr-final.json` |
| L1 词级对齐（MFA） | DGX Spark MFA 3.4.2（`dgx-spark-ssh`） | beam 100 / retry 400 | 14 chunk | ~90 s | 2400.5 s 音频 | ~26× 实时 | 本地算力
| L1 英文机器评审 | `claude-opus-5-5`（Claude Code 订阅 CLI） | high | 120 批 / 240 条收据 | ~5 min | 720 句 / 7313 词 | — | 订阅，不按 token 计费 | `layer1/output-v9/machine-judge.json` |
| L2 初译／独立审核／回译质检 | not_run | — | — | — | — | — | — | Layer 1 未放行 |
| L3 配音／回转写／音频质检 | not_run | — | — | — | — | — | — | — |
| L4 构建与发布 | not_run | — | — | — | — | — | — | — |

## 错误

1. **MFA `NoAlignmentsError`（已修）**：发现于远端对齐执行中。180 秒、506 词的参考块在默认 beam(10)/retry_beam(40) 下无可行路径。修复：显式 `--beam 100 --retry_beam 400`（本地 21.7 s、506/506 词验证），并纳入对齐身份。提交 `46a03d9b`。
2. **Claude CLI 401 OAuth 过期（用户修复）**：4 次裁判调用零用量失败，账本记为 `started_response_unconfirmed`，按设计阻断该账本后续派发。需要操作者重新登录；重新登录后只能开新运行身份。
3. **裁判输入上限 `source_judge_input_bound_exceeded`（已修）**：冻结上限 `maxInputTokens=16384`；批次 10/8/6 在不同轮次先后超限。根因是每轮重跑 ASR 导致句子长度漂移，"按上一轮测得的批量"不可靠。修复：裁判对超限批次二分拆分（提交 `2fe13b6c`），保留源顺序与独立缓存键。
4. **`claude_language_unexpected_turn_count`（已修）**：109 次调用中出现 1 次 `num_turns=3`（结果为合法结构化输出）。CLI 把自身的 schema 修复轮计入 turn，放宽到 3 并保留 0/4+ 拒绝。提交 `408d0bf4`。
5. **`source_budget_exhausted`（配置问题）**：v5 用 batchSize=5 需要 143 次裁判调用，超过其 106 请求上限；后续身份把请求与 wall-time 上限按实际批次数重算。
6. **未知结果不可复用（设计如此）**：v3 的 4 条、v6 的 1 条 `started_response_unconfirmed` 永久留在已关闭账本中，没有对账收据；这些账本不能再派发，只能开新身份。

## 费用

- 付费实际：9 轮 × 14 次 `gpt-transcribe` ≈ **USD 1.62**（每轮估算 USD 0.180075）。所有 ASR 行 `costStatus=unknown`（供应商无 token 用量），`invoiceVerified=false`，没有账本记录实际账单。
- 预留上限：v9 单轮预留 USD 20.52（Claude 订阅按冻结挂牌价预留，不是扣费）；累计 9 本账本预留约 USD 45.8，均为最坏情况上界。
- 授权：用户批准 USD 25 / 106–170 请求（分轮收据），实际付费远低于上限。

## 待办 / 下一步

1. **9 句边界问题的根因**：`A.D. 70` 在缩写句点处被切开（产生孤立年份）、引语列表在逗号处被切、"either … but" 结构被拆开。需要修锚点/句子切分策略（缩写表、引语与并列结构保护），或用 `anchorPolicy.boundaryOverrides` 定点合并；修好后重跑 Layer 1。
2. **跨配置 ASR 复用缺失**：每轮重跑 ASR 既是费用也是身份漂移来源；建议给该 producer 接上预算账本已有的 `reuseBudgetRoots`。
3. **未知结果对账**：v3/v6 的 unconfirmed 行需要一份对账收据（当前无工具支持"已知失败"释放），否则这些账本永久不可用。
